#!/usr/bin/env python3
"""Property test for the pure health-reconcile decision (Task 2.4).

Feature: phase2-aro-completion, Property 3: Health reconcile drives
RUNNING<->UNHEALTHY (decision portion).

Validates: Requirements 1.4, 1.5.

The pure ``reconcile_health(status, healthy)`` decision function in
``src/aro/lifecycle.py`` must:

* return UNHEALTHY when the agent is RUNNING and not healthy (Req 1.4);
* return RUNNING when the agent is UNHEALTHY and healthy (Req 1.5);
* return None for every other (status, healthy) pair (no transition).

Run directly:
    python3 tests/test_aro_reconcile_health.py
Or via pytest:
    pytest tests/test_aro_reconcile_health.py
"""
import os
import sys

from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.aro import lifecycle as lc  # noqa: E402


# Arbitrary (status, healthy) pairs across ALL lifecycle states plus a couple
# of out-of-graph sentinels, paired with both health outcomes.
_STATES = st.sampled_from(sorted(lc.ALL_STATES) + ["", "bogus-state"])


@given(status=_STATES, healthy=st.booleans())
@settings(max_examples=200)
def test_reconcile_health_decision(status, healthy):
    """Feature: phase2-aro-completion, Property 3: Health reconcile drives
    RUNNING<->UNHEALTHY (decision portion).

    Validates: Requirements 1.4, 1.5.
    """
    result = lc.reconcile_health(status, healthy)

    if status == lc.RUNNING and not healthy:
        # Req 1.4: a running agent that fails its probe degrades to UNHEALTHY.
        assert result == lc.UNHEALTHY
    elif status == lc.UNHEALTHY and healthy:
        # Req 1.5: an unhealthy agent that passes its probe recovers to RUNNING.
        assert result == lc.RUNNING
    else:
        # Every other pair is a no-op decision.
        assert result is None

    # The decision is only ever None or one of the two reconcile targets, and
    # when non-None it is always a graph-legal edge from the current status.
    assert result in (None, lc.RUNNING, lc.UNHEALTHY)
    if result is not None:
        assert lc.can_transition(status, result)


def test_reconcile_health_examples():
    """Concrete anchors for the two directed edges and representative no-ops."""
    assert lc.reconcile_health(lc.RUNNING, False) == lc.UNHEALTHY
    assert lc.reconcile_health(lc.UNHEALTHY, True) == lc.RUNNING
    # No-ops: matching-but-opposite health, and unrelated states.
    assert lc.reconcile_health(lc.RUNNING, True) is None
    assert lc.reconcile_health(lc.UNHEALTHY, False) is None
    assert lc.reconcile_health(lc.READY, False) is None
    assert lc.reconcile_health(lc.STOPPED, True) is None


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
