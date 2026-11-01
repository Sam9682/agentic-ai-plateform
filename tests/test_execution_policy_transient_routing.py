#!/usr/bin/env python3
"""Property test for transient-vs-deterministic classification routing.

Feature: phase4-runtime-execution-hardening, Property 5.

Property 5: Transient-vs-deterministic classification routing.
  * A Deterministic_Failure yields a terminal FAILED outcome after exactly ONE
    attempt (no retry) — Requirement 1.5.
  * A Transient_Failure is eligible for retry: the op is invoked more than once
    (up to ``max_attempts``) before the policy gives up with FAILED — this is
    the retry eligibility that the SSH changed-key vs transient-SSH decision in
    ``ssh_is_transient`` feeds (Requirement 2.2: a changed host key is a
    Deterministic_Failure and is therefore never retried).

Validates: Requirements 1.5, 2.2

The test drives ``run_with_policy`` with an injected ``is_transient`` classifier
and injected ``clock``/``sleep``/``rand`` so no real sleeping or wall-clock time
is involved (R1.11, R8.2). The op always raises; whether it is classified
transient or deterministic is the single variable under test.

Run directly:
    python3 tests/test_execution_policy_transient_routing.py
Or via pytest:
    pytest tests/test_execution_policy_transient_routing.py
"""
import os
import sys

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.execution_policy import (  # noqa: E402
    BackoffParams,
    OutcomeStatus,
    run_with_policy,
)


class _DeterministicError(Exception):
    """A non-transient failure — the policy must not retry it."""


class _TransientError(Exception):
    """A transient failure — the policy is eligible to retry it."""


def _counting_op(exc):
    """Return an ``op(token)`` that records its invocation count and raises ``exc``.

    The returned callable carries a ``calls`` attribute the test asserts on, so
    we can count the real number of op invocations independently of the
    ``Outcome.attempts`` field.
    """

    def op(_token):
        op.calls += 1
        raise exc

    op.calls = 0
    return op


# A virtual clock that never advances and a no-op sleep guarantee the timeout
# branch is never taken, so the ONLY thing deciding the outcome is the
# transient/deterministic classification.
def _frozen_clock():
    return 0.0


def _no_sleep(_delay):
    # Assert no real sleeping occurs; the policy only ever calls this with the
    # injected virtual delay, never touching ``time.sleep``.
    return None


def _fixed_rand():
    # Deterministic jitter so the test is reproducible; value in [0, 1).
    return 0.5


@given(
    max_attempts=st.integers(min_value=1, max_value=20),
    timeout=st.one_of(st.none(), st.floats(min_value=1.0, max_value=1_000.0)),
    base=st.floats(min_value=0.0, max_value=5.0),
    multiplier=st.floats(min_value=1.0, max_value=3.0),
    jitter_fraction=st.floats(min_value=0.0, max_value=1.0),
    cap=st.floats(min_value=0.0, max_value=30.0),
)
@settings(max_examples=200)
def test_deterministic_failure_fails_after_exactly_one_attempt(
    max_attempts, timeout, base, multiplier, jitter_fraction, cap
):
    """A deterministic failure => terminal FAILED after exactly one attempt.

    Feature: phase4-runtime-execution-hardening, Property 5.
    Validates: Requirements 1.5, 2.2

    No matter how large ``max_attempts`` is, a failure the classifier rules
    deterministic is terminal on the first raise — the op is invoked exactly
    once and the outcome is FAILED carrying the raised error.
    """
    err = _DeterministicError("changed host key / auth failure / policy denial")
    op = _counting_op(err)

    outcome = run_with_policy(
        op,
        timeout=timeout,
        max_attempts=max_attempts,
        backoff=BackoffParams(
            base=base, multiplier=multiplier, jitter_fraction=jitter_fraction, cap=cap
        ),
        is_transient=lambda _e: False,
        clock=_frozen_clock,
        sleep=_no_sleep,
        rand=_fixed_rand,
    )

    assert outcome.status is OutcomeStatus.FAILED
    assert outcome.attempts == 1, "deterministic failure must not be retried"
    assert op.calls == 1, "the op must be invoked exactly once"
    assert outcome.error is err


@given(
    max_attempts=st.integers(min_value=2, max_value=20),
    timeout=st.one_of(st.none(), st.floats(min_value=1.0, max_value=1_000.0)),
    base=st.floats(min_value=0.0, max_value=5.0),
    multiplier=st.floats(min_value=1.0, max_value=3.0),
    jitter_fraction=st.floats(min_value=0.0, max_value=1.0),
    cap=st.floats(min_value=0.0, max_value=30.0),
)
@settings(max_examples=200)
def test_transient_failure_is_retried_up_to_max_attempts(
    max_attempts, timeout, base, multiplier, jitter_fraction, cap
):
    """A transient failure is eligible for retry (>1 attempt, up to max).

    Feature: phase4-runtime-execution-hardening, Property 5.
    Validates: Requirements 1.5, 2.2

    When the classifier rules the failure transient and ``max_attempts >= 2``,
    the op that always raises is invoked more than once and exactly
    ``max_attempts`` times before the policy gives up with FAILED. The virtual
    clock never advances, so the retry loop is driven purely by the
    transient classification and the attempt bound — never by a timeout.
    """
    err = _TransientError("connection timed out")
    op = _counting_op(err)

    sleeps = []

    def _recording_sleep(delay):
        # Still no real sleeping; just record that a (virtual) backoff happened.
        sleeps.append(delay)

    outcome = run_with_policy(
        op,
        timeout=timeout,
        max_attempts=max_attempts,
        backoff=BackoffParams(
            base=base, multiplier=multiplier, jitter_fraction=jitter_fraction, cap=cap
        ),
        is_transient=lambda _e: True,
        clock=_frozen_clock,
        sleep=_recording_sleep,
        rand=_fixed_rand,
    )

    assert outcome.status is OutcomeStatus.FAILED
    # Retried: strictly more than one attempt, bounded by max_attempts.
    assert 1 < outcome.attempts <= max_attempts
    assert outcome.attempts == max_attempts, (
        "an always-transient op should exhaust the full attempt budget"
    )
    assert op.calls == max_attempts
    # At most one backoff between each pair of attempts (max_attempts - 1). The
    # policy only sleeps when the computed delay is strictly positive, so a
    # zero backoff (e.g. base=0 or cap=0) still retries but records no sleep.
    assert len(sleeps) <= max_attempts - 1
    assert all(d > 0 for d in sleeps), "sleep is only called for a positive delay"
    assert outcome.error is err


@given(
    max_attempts=st.integers(min_value=1, max_value=20),
    transient=st.booleans(),
)
@settings(max_examples=200)
def test_classification_alone_decides_retry_eligibility(max_attempts, transient):
    """The classifier alone decides retry eligibility; FAILED is the terminal.

    Feature: phase4-runtime-execution-hardening, Property 5.
    Validates: Requirements 1.5, 2.2

    Holds the attempt budget and op fixed and flips only the classification:
      * deterministic => exactly one invocation (never retried);
      * transient     => invoked ``max_attempts`` times (fully retried).
    Either way the terminal outcome is FAILED — classification changes the
    retry eligibility, not the terminal class.
    """
    err = Exception("boom")
    op = _counting_op(err)

    outcome = run_with_policy(
        op,
        timeout=None,
        max_attempts=max_attempts,
        is_transient=lambda _e: transient,
        clock=_frozen_clock,
        sleep=_no_sleep,
        rand=_fixed_rand,
    )

    assert outcome.status is OutcomeStatus.FAILED
    if transient:
        assert op.calls == max_attempts
        assert outcome.attempts == max_attempts
    else:
        assert op.calls == 1
        assert outcome.attempts == 1


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
