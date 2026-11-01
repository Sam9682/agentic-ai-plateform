#!/usr/bin/env python3
"""Property test for bounded retry in the shared execution policy.

Feature: phase4-runtime-execution-hardening, Property 2.

Property 2 (retry count is bounded by max_attempts): when ``op`` always raises
a transient error, ``run_with_policy`` invokes the op at most ``max_attempts``
times (exactly ``max_attempts`` here, since every attempt fails transiently and
nothing else — no timeout or cancellation — can cut the loop short), and the
terminal outcome is ``FAILED`` (R1.4). The retry loop never exceeds the attempt
bound (R1.3).

All time and randomness are injected (a virtual clock that never advances, a
no-op sleep that records the delays, and a deterministic ``rand``), so no real
sleeping or wall-clock dependence occurs and the whole contract is exercised by
a scripted op alone.

Validates: Requirements 1.3, 1.4

Run directly:
    python3 tests/test_execution_policy_bounded_retry.py
Or via pytest:
    pytest tests/test_execution_policy_bounded_retry.py -v
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
    Outcome,
    OutcomeStatus,
    run_with_policy,
)


class _AlwaysTransient(Exception):
    """A transient failure the op raises on every invocation."""


def _always_transient(_exc):
    """Classifier used for this property: every error is transient (retryable).

    Isolates the attempt-bound behavior — with an unconditionally transient
    classifier, only ``max_attempts`` can stop the loop, so the observed
    invocation count is the attempt bound itself.
    """
    return True


@settings(max_examples=200, deadline=None)
@given(
    max_attempts=st.integers(min_value=1, max_value=50),
    base=st.floats(min_value=0.0, max_value=5.0),
    multiplier=st.floats(min_value=1.0, max_value=3.0),
    jitter_fraction=st.floats(min_value=0.0, max_value=1.0),
    cap=st.floats(min_value=0.0, max_value=30.0),
    rand_value=st.floats(min_value=0.0, max_value=0.999999),
)
def test_retry_is_bounded_by_max_attempts(
    max_attempts, base, multiplier, jitter_fraction, cap, rand_value
):
    """Feature: phase4-runtime-execution-hardening, Property 2.

    op always raises a transient error ⇒ invoked ≤ max_attempts times and the
    terminal outcome is FAILED. Validates: Requirements 1.3, 1.4.
    """
    invocations = {"count": 0}

    def op(_token):
        invocations["count"] += 1
        raise _AlwaysTransient("connection reset by peer")

    # Virtual clock that never advances: no wall-clock bound interferes with
    # the attempt bound (timeout=None also guarantees no deadline).
    def clock():
        return 0.0

    slept = []

    def sleep(delay):
        slept.append(delay)

    def rand():
        return rand_value

    outcome = run_with_policy(
        op,
        timeout=None,
        max_attempts=max_attempts,
        backoff=BackoffParams(
            base=base,
            multiplier=multiplier,
            jitter_fraction=jitter_fraction,
            cap=cap,
        ),
        is_transient=_always_transient,
        clock=clock,
        sleep=sleep,
        rand=rand,
    )

    assert isinstance(outcome, Outcome)
    # Never exceeds the attempt bound (R1.3) and, with every attempt failing
    # transiently and no timeout/cancel, invokes exactly max_attempts (R1.4).
    assert invocations["count"] <= max_attempts
    assert invocations["count"] == max_attempts
    assert outcome.attempts == max_attempts
    # Terminal outcome is FAILED carrying the last transient error (R1.4).
    assert outcome.status is OutcomeStatus.FAILED
    assert isinstance(outcome.error, _AlwaysTransient)
    # At most one backoff gap per retry (max_attempts - 1); a zero-length delay
    # is not slept on, so the count is bounded above rather than exact. Every
    # recorded delay stays within the cap.
    assert len(slept) <= max_attempts - 1
    for delay in slept:
        assert 0.0 <= delay <= cap


@settings(max_examples=200, deadline=None)
@given(max_attempts=st.integers(min_value=-5, max_value=0))
def test_non_positive_max_attempts_runs_op_once_then_fails(max_attempts):
    """Feature: phase4-runtime-execution-hardening, Property 2.

    A max_attempts below 1 is clamped to 1: the op runs exactly once and the
    terminal outcome is FAILED. Validates: Requirements 1.3, 1.4.
    """
    invocations = {"count": 0}

    def op(_token):
        invocations["count"] += 1
        raise _AlwaysTransient("connection timed out")

    outcome = run_with_policy(
        op,
        timeout=None,
        max_attempts=max_attempts,
        is_transient=_always_transient,
        clock=lambda: 0.0,
        sleep=lambda _d: None,
        rand=lambda: 0.5,
    )

    assert invocations["count"] == 1
    assert outcome.attempts == 1
    assert outcome.status is OutcomeStatus.FAILED


if __name__ == "__main__":
    test_retry_is_bounded_by_max_attempts()
    test_non_positive_max_attempts_runs_op_once_then_fails()
    print("ok")
