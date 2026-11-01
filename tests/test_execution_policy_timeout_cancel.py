#!/usr/bin/env python3
"""Property tests for execution_policy timeout and cancellation terminals.

Feature: phase4-runtime-execution-hardening, Property 3 and Property 4.

These two properties exercise the terminal classification of
``src.execution_policy.run_with_policy`` for the two non-failure, non-success
terminals, using a virtual clock and a scripted op so no live Docker,
PostgreSQL, or SSH is touched (R1.11, R8.2):

* **Property 3: Timeout yields a terminal timed-out outcome** (Validates
  Requirements 1.2). With a virtual clock that advances past the wall-clock
  budget, an op whose work exceeds the budget yields
  ``Outcome(status=TIMED_OUT)``. Both the "budget already exhausted before the
  attempt" branch and the "op reports its own deadline" branch are covered.

* **Property 4: Cancellation yields a terminal cancelled outcome** (Validates
  Requirements 1.7). When cancellation is requested (before the first attempt
  or mid-flight by the op), the result is ``Outcome(status=CANCELLED)`` and no
  further retries are performed.

Both properties run >=100 iterations.

Run directly:
    python3 tests/test_execution_policy_timeout_cancel.py
Or via pytest:
    pytest tests/test_execution_policy_timeout_cancel.py
"""
import os
import sys

from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.execution_policy import (  # noqa: E402
    BackoffParams,
    CancelToken,
    CancelledError,
    DeadlineExceeded,
    Outcome,
    OutcomeStatus,
    run_with_policy,
)


class VirtualClock:
    """A deterministic, monotonic clock whose value only ever advances.

    ``now()`` returns the current virtual time; ``advance(dt)`` moves it
    forward. Wiring the clock as both the policy's ``clock`` and (via
    :meth:`sleep`) its ``sleep`` keeps every time reference virtual so the test
    never waits on the wall clock.
    """

    def __init__(self, start: float = 0.0) -> None:
        self._t = start

    def now(self) -> float:
        return self._t

    def advance(self, dt: float) -> None:
        if dt > 0:
            self._t += dt

    def sleep(self, dt: float) -> None:
        # A policy sleep simply advances virtual time.
        self.advance(dt)


def _never_transient(_exc: BaseException) -> bool:
    return False


def _always_transient(_exc: BaseException) -> bool:
    return True


# --------------------------------------------------------------------------- #
# Property 3: Timeout yields a terminal timed-out outcome.
# --------------------------------------------------------------------------- #
@settings(max_examples=200, deadline=None)
@given(
    timeout=st.floats(min_value=0.001, max_value=1_000.0),
    overshoot=st.floats(min_value=0.0, max_value=5_000.0),
    max_attempts=st.integers(min_value=1, max_value=8),
    start=st.floats(min_value=0.0, max_value=10_000.0),
)
def test_op_exceeding_budget_yields_timed_out(timeout, overshoot, max_attempts, start):
    """Feature: phase4-runtime-execution-hardening, Property 3.

    Validates: Requirements 1.2.

    An op whose work advances the virtual clock to or past the wall-clock
    deadline yields ``Outcome(status=TIMED_OUT)``. The op advances the clock by
    ``timeout + overshoot`` and then reports its own deadline, mirroring a real
    op that notices it ran out of time; the policy must classify the run as
    TIMED_OUT and make exactly one attempt.
    """
    clock = VirtualClock(start=start)

    def op(_token):
        # Simulate work that consumes at least the whole budget.
        clock.advance(timeout + overshoot)
        raise DeadlineExceeded("op ran past its budget")

    outcome = run_with_policy(
        op,
        timeout=timeout,
        max_attempts=max_attempts,
        backoff=BackoffParams(),
        is_transient=_always_transient,
        clock=clock.now,
        sleep=clock.sleep,
        rand=lambda: 0.5,
    )

    assert isinstance(outcome, Outcome)
    assert outcome.status is OutcomeStatus.TIMED_OUT
    # The op reported its own deadline on the first attempt; no retry past it.
    assert outcome.attempts == 1


@settings(max_examples=200, deadline=None)
@given(
    timeout=st.floats(min_value=1.0, max_value=1_000.0),
    max_attempts=st.integers(min_value=2, max_value=8),
    start=st.floats(min_value=0.0, max_value=10_000.0),
)
def test_budget_exhausted_before_retry_attempt_yields_timed_out(
    timeout, max_attempts, start
):
    """Feature: phase4-runtime-execution-hardening, Property 3.

    Validates: Requirements 1.2.

    The policy measures its wall-clock budget from the moment it starts
    (``deadline = clock() + timeout``), so the budget can only be exhausted
    *before an attempt* on a retry — after a prior transient failure whose work
    advanced the virtual clock past the deadline. Here the first attempt fails
    transiently and the op advances the clock past the deadline; the policy's
    post-failure budget check must yield ``Outcome(status=TIMED_OUT)`` with no
    additional op invocation.
    """
    clock = VirtualClock(start=start)
    calls = {"n": 0}

    def op(_token):
        calls["n"] += 1
        # The first (and only) attempt consumes the entire budget, then fails
        # transiently; the policy wants to retry but the deadline is now gone.
        clock.advance(timeout + 1.0)
        raise RuntimeError("transient connection reset")

    outcome = run_with_policy(
        op,
        timeout=timeout,
        max_attempts=max_attempts,
        backoff=BackoffParams(base=0.001, cap=0.01),
        is_transient=_always_transient,
        clock=clock.now,
        sleep=clock.sleep,
        rand=lambda: 0.5,
    )

    # Budget gone after the first failure: the retry path short-circuits to a
    # timeout rather than invoking the op again.
    assert outcome.status is OutcomeStatus.TIMED_OUT
    assert calls["n"] == 1
    assert outcome.attempts == 1


@settings(max_examples=200, deadline=None)
@given(
    timeout=st.floats(min_value=0.01, max_value=1_000.0),
    max_attempts=st.integers(min_value=2, max_value=8),
    start=st.floats(min_value=0.0, max_value=10_000.0),
)
def test_transient_retries_time_out_when_budget_runs_out(timeout, max_attempts, start):
    """Feature: phase4-runtime-execution-hardening, Property 3.

    Validates: Requirements 1.2.

    An op that always raises a transient failure while the virtual clock keeps
    advancing eventually exhausts the wall-clock budget; the terminal is
    TIMED_OUT (the budget bound wins over the remaining attempt budget), with at
    least one attempt made and no more than ``max_attempts``.
    """
    clock = VirtualClock(start=start)
    # Each attempt consumes a slice of the budget so the deadline is reached.
    per_attempt = timeout  # one attempt alone exhausts the whole budget

    def op(_token):
        clock.advance(per_attempt)
        raise RuntimeError("transient connection reset")

    outcome = run_with_policy(
        op,
        timeout=timeout,
        max_attempts=max_attempts,
        backoff=BackoffParams(base=0.01, cap=0.1),
        is_transient=_always_transient,
        clock=clock.now,
        sleep=clock.sleep,
        rand=lambda: 0.5,
    )

    assert outcome.status is OutcomeStatus.TIMED_OUT
    assert 1 <= outcome.attempts <= max_attempts


# --------------------------------------------------------------------------- #
# Property 4: Cancellation yields a terminal cancelled outcome.
# --------------------------------------------------------------------------- #
@settings(max_examples=200, deadline=None)
@given(
    timeout=st.one_of(st.none(), st.floats(min_value=0.001, max_value=1_000.0)),
    max_attempts=st.integers(min_value=1, max_value=8),
    start=st.floats(min_value=0.0, max_value=10_000.0),
)
def test_cancel_before_start_yields_cancelled_no_attempt(timeout, max_attempts, start):
    """Feature: phase4-runtime-execution-hardening, Property 4.

    Validates: Requirements 1.7.

    A token already cancelled before the run yields ``Outcome(CANCELLED)`` at
    the pre-attempt check; the op is never invoked and there are no retries.
    """
    clock = VirtualClock(start=start)
    calls = {"n": 0}

    def op(_token):
        calls["n"] += 1
        return "unreachable"

    token = CancelToken()
    token.cancel()

    outcome = run_with_policy(
        op,
        timeout=timeout,
        max_attempts=max_attempts,
        backoff=BackoffParams(),
        is_transient=_always_transient,
        cancel_token=token,
        clock=clock.now,
        sleep=clock.sleep,
        rand=lambda: 0.5,
    )

    assert outcome.status is OutcomeStatus.CANCELLED
    assert calls["n"] == 0
    assert outcome.attempts == 0


@settings(max_examples=200, deadline=None)
@given(
    timeout=st.one_of(st.none(), st.floats(min_value=0.001, max_value=1_000.0)),
    max_attempts=st.integers(min_value=1, max_value=8),
    start=st.floats(min_value=0.0, max_value=10_000.0),
)
def test_cancel_mid_flight_yields_cancelled(timeout, max_attempts, start):
    """Feature: phase4-runtime-execution-hardening, Property 4.

    Validates: Requirements 1.7.

    An op that observes the token and raises :class:`CancelledError` mid-flight
    yields ``Outcome(CANCELLED)``. The op cancels its own token on the first
    invocation, so the run cancels on attempt 1 with no further retries.
    """
    clock = VirtualClock(start=start)

    def op(token):
        # Simulate a long op that honors cooperative cancellation mid-stream.
        token.cancel()
        raise CancelledError("cancelled mid-stream")

    outcome = run_with_policy(
        op,
        timeout=timeout,
        max_attempts=max_attempts,
        backoff=BackoffParams(),
        is_transient=_always_transient,
        clock=clock.now,
        sleep=clock.sleep,
        rand=lambda: 0.5,
    )

    assert outcome.status is OutcomeStatus.CANCELLED
    assert outcome.attempts == 1


@settings(max_examples=200, deadline=None)
@given(
    cancel_after=st.integers(min_value=1, max_value=6),
    max_attempts=st.integers(min_value=1, max_value=8),
    start=st.floats(min_value=0.0, max_value=10_000.0),
)
def test_cancel_during_transient_retries_stops_retrying(
    cancel_after, max_attempts, start
):
    """Feature: phase4-runtime-execution-hardening, Property 4.

    Validates: Requirements 1.7.

    An op that raises transient failures but has its token cancelled after a
    bounded number of attempts terminates as CANCELLED and stops retrying: the
    attempt count never exceeds either the cancel point or ``max_attempts``, and
    a deliberate cancel is never masked by continued retry.
    """
    clock = VirtualClock(start=start)
    state = {"n": 0}
    token = CancelToken()

    def op(_token):
        state["n"] += 1
        if state["n"] >= cancel_after:
            token.cancel()
        raise RuntimeError("transient connection timeout")

    outcome = run_with_policy(
        op,
        timeout=None,
        max_attempts=max_attempts,
        backoff=BackoffParams(base=0.001, cap=0.01),
        is_transient=_always_transient,
        cancel_token=token,
        clock=clock.now,
        sleep=clock.sleep,
        rand=lambda: 0.5,
    )

    if cancel_after <= max_attempts:
        # Cancellation observed within the attempt budget: terminal CANCELLED,
        # and no attempt beyond the one that cancelled.
        assert outcome.status is OutcomeStatus.CANCELLED
        assert outcome.attempts == cancel_after
    else:
        # The attempt budget ran out before cancellation could be observed:
        # transient failures exhausted at the bound are a terminal FAILED.
        assert outcome.status is OutcomeStatus.FAILED
        assert outcome.attempts == max_attempts
    # Never more invocations than the attempt cap.
    assert state["n"] <= max_attempts


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
