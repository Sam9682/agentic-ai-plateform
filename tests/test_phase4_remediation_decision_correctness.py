#!/usr/bin/env python3
"""Property test for remediation decision correctness.

Feature: phase4-runtime-execution-hardening, Property 11.

Task 6.2 added the pure state machine
``orchestrator.decide_remediation(health_state, consecutive_failures,
within_grace, cap, replaced) -> RemediationAction`` implementing the design
decision table:

    healthy                       -> NONE              (R4.1 / R4.5 converged)
    within_grace                  -> NONE              (R4.1 still starting up)
    consecutive_failures < cap    -> RESTART           (R4.2 restart in place)
    not replaced                  -> REPLACE           (R4.3 replace once)
    else                          -> NEEDS_ATTENTION   (R4.4 terminal surface)

Property 11 (design.md): *for any* combination of
``(healthy/grace/failures/cap/replaced)`` inputs across the full input space,
``decide_remediation`` returns ``NONE`` / ``RESTART`` / ``REPLACE`` /
``NEEDS_ATTENTION`` in agreement with the decision table.

This test encodes the decision table as an independent pure oracle
(:func:`oracle`) derived directly from the acceptance criteria — it does NOT
call ``decide_remediation`` — and asserts the live function matches the oracle
across the full cross-product of inputs (healthy flag, grace flag,
consecutive-failure count spanning below/at/above the cap, a range of caps, and
the replaced flag). Pure function; no live Docker, PostgreSQL, or SSH.

Validates: Requirements 4.1, 4.2, 4.3, 4.4.

Run directly:
    python3 tests/test_phase4_remediation_decision_correctness.py
Or via pytest:
    pytest tests/test_phase4_remediation_decision_correctness.py
"""
import os
import sys

from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.orchestrator import RemediationAction, decide_remediation  # noqa: E402


# --------------------------------------------------------------------------- #
# Independent oracle — the RemediationAction the decision table mandates for a
# given input, derived purely from the acceptance criteria (R4.1-R4.4), NOT
# from decide_remediation. This is the model Property 11 compares against.
# --------------------------------------------------------------------------- #
def oracle(healthy, consecutive_failures, within_grace, cap, replaced):
    """Return the expected :class:`RemediationAction` for the given inputs."""
    if healthy:
        return RemediationAction.NONE          # R4.1 / R4.5 converged
    if within_grace:
        return RemediationAction.NONE          # R4.1 still starting up
    if consecutive_failures < cap:
        return RemediationAction.RESTART       # R4.2 restart in place
    if not replaced:
        return RemediationAction.REPLACE       # R4.3 replace once
    return RemediationAction.NEEDS_ATTENTION   # R4.4 terminal surface


# --------------------------------------------------------------------------- #
# Property 11 — decide_remediation agrees with the decision table across the
# full input space.
# --------------------------------------------------------------------------- #
@settings(max_examples=300, deadline=None)
@given(
    healthy=st.booleans(),
    within_grace=st.booleans(),
    replaced=st.booleans(),
    cap=st.integers(min_value=1, max_value=10),
    # Span well below, at, and above the cap so RESTART/REPLACE/NEEDS_ATTENTION
    # boundaries are all exercised.
    consecutive_failures=st.integers(min_value=0, max_value=20),
)
def test_property11_remediation_decision_correctness(
    healthy, within_grace, replaced, cap, consecutive_failures
):
    """Feature: phase4-runtime-execution-hardening, Property 11: Remediation \
decision correctness.

    For any ``(healthy/grace/failures/cap/replaced)`` input,
    ``decide_remediation`` returns the ``NONE``/``RESTART``/``REPLACE``/
    ``NEEDS_ATTENTION`` action mandated by the decision table.

    Validates: Requirements 4.1, 4.2, 4.3, 4.4
    """
    health_state = {"healthy": healthy, "within_grace": within_grace}

    actual = decide_remediation(
        health_state, consecutive_failures, within_grace, cap, replaced
    )
    expected = oracle(healthy, consecutive_failures, within_grace, cap, replaced)

    assert actual == expected, (
        f"healthy={healthy} grace={within_grace} "
        f"failures={consecutive_failures} cap={cap} replaced={replaced}: "
        f"{actual!r} != {expected!r}"
    )
    # The returned value is always a valid RemediationAction member.
    assert isinstance(actual, RemediationAction)


# --------------------------------------------------------------------------- #
# Concrete anchors — one deterministic example per branch of the table.
# --------------------------------------------------------------------------- #
def _hs(healthy, within_grace=False):
    return {"healthy": healthy, "within_grace": within_grace}


def test_healthy_returns_none():
    # Healthy short-circuits regardless of failures/cap/replaced (R4.1/R4.5).
    assert decide_remediation(_hs(True), 99, False, 3, True) == RemediationAction.NONE


def test_within_grace_returns_none():
    # Unhealthy but still inside the grace window -> no action yet (R4.1).
    assert (
        decide_remediation(_hs(False), 99, True, 3, True) == RemediationAction.NONE
    )


def test_below_cap_returns_restart():
    # Unhealthy, past grace, failures below cap -> restart in place (R4.2).
    assert (
        decide_remediation(_hs(False), 0, False, 3, False)
        == RemediationAction.RESTART
    )
    assert (
        decide_remediation(_hs(False), 2, False, 3, False)
        == RemediationAction.RESTART
    )


def test_at_cap_not_replaced_returns_replace():
    # Failures reached the cap and not yet replaced -> replace once (R4.3).
    assert (
        decide_remediation(_hs(False), 3, False, 3, False)
        == RemediationAction.REPLACE
    )
    assert (
        decide_remediation(_hs(False), 5, False, 3, False)
        == RemediationAction.REPLACE
    )


def test_at_cap_already_replaced_returns_needs_attention():
    # Failures past the cap and already replaced -> terminal surface (R4.4).
    assert (
        decide_remediation(_hs(False), 3, False, 3, True)
        == RemediationAction.NEEDS_ATTENTION
    )
    assert (
        decide_remediation(_hs(False), 9, False, 3, True)
        == RemediationAction.NEEDS_ATTENTION
    )


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
