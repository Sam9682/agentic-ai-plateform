#!/usr/bin/env python3
"""Property test for the orchestrator crash-loop cap (Task 5.3).

Feature: phase4-runtime-execution-hardening, Property 10.

Property 10 (Crash-loop cap bounds restarts): the pure decision function
``should_attempt_start(restart_attempts, cap)`` returns ``True`` if and only if
``restart_attempts < cap``. The persisted consecutive-failure count bounds
restarts across reconcile passes, so once ``restart_attempts`` reaches the cap
no further start is attempted and a persistently failing image cannot
restart-loop forever (R3.2, R3.3).

The function is pure, so the property is exercised without live Docker or
PostgreSQL (R3.9).

Validates: Requirements 3.2, 3.3

Run directly:
    python3 tests/test_orchestrator_crash_loop_cap.py
Or via pytest:
    pytest tests/test_orchestrator_crash_loop_cap.py -v
"""
import os
import sys

from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.orchestrator import should_attempt_start  # noqa: E402


@settings(max_examples=300, deadline=None)
@given(
    restart_attempts=st.integers(min_value=0, max_value=1000),
    cap=st.integers(min_value=0, max_value=1000),
)
def test_should_attempt_start_iff_below_cap(restart_attempts, cap):
    """Feature: phase4-runtime-execution-hardening, Property 10.

    should_attempt_start returns True iff restart_attempts < cap, so once the
    recorded failure count reaches the cap no further start is attempted.
    Validates: Requirements 3.2, 3.3.
    """
    result = should_attempt_start(restart_attempts, cap)
    assert isinstance(result, bool)
    # Biconditional: the start is attempted exactly while strictly below cap.
    assert result == (restart_attempts < cap)


@settings(max_examples=300, deadline=None)
@given(cap=st.integers(min_value=1, max_value=200))
def test_at_and_above_cap_never_attempts(cap):
    """Feature: phase4-runtime-execution-hardening, Property 10.

    At the cap and for every count above it, no start is attempted — the cap is
    a hard ceiling on consecutive restart attempts. Validates: Requirements
    3.2, 3.3.
    """
    # Reaching the cap stops retrying (R3.3).
    assert should_attempt_start(cap, cap) is False
    # Any count beyond the cap also stops retrying.
    for extra in range(1, 6):
        assert should_attempt_start(cap + extra, cap) is False


@settings(max_examples=300, deadline=None)
@given(cap=st.integers(min_value=1, max_value=200))
def test_below_cap_always_attempts(cap):
    """Feature: phase4-runtime-execution-hardening, Property 10.

    Every consecutive-failure count strictly below the cap still attempts a
    start (R3.2). Validates: Requirements 3.2, 3.3.
    """
    for attempts in range(0, cap):
        assert should_attempt_start(attempts, cap) is True


@settings(max_examples=300, deadline=None)
@given(
    cap=st.integers(min_value=0, max_value=500),
    extra=st.integers(min_value=0, max_value=500),
)
def test_monotonic_once_capped_stays_capped(cap, extra):
    """Feature: phase4-runtime-execution-hardening, Property 10.

    The decision is monotonically non-increasing in restart_attempts: once the
    count reaches the cap, incrementing it further never re-enables a start, so
    the bound cannot be escaped by accumulating more failures. Validates:
    Requirements 3.2, 3.3.
    """
    # At the cap no start is attempted; adding more failures keeps it blocked.
    assert should_attempt_start(cap, cap) is False
    assert should_attempt_start(cap + extra, cap) is False


if __name__ == "__main__":
    test_should_attempt_start_iff_below_cap()
    test_at_and_above_cap_never_attempts()
    test_below_cap_always_attempts()
    test_monotonic_once_capped_stays_capped()
    print("ok")
