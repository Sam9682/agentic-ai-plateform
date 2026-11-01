#!/usr/bin/env python3
"""Property test for the QUARANTINED release edge in the pure graph (Task 9.2).

Feature: phase2-aro-completion, Property 1: QUARANTINED releases only to READY.

Validates: Requirements 1.1.

Req 1.1 states the Lifecycle_Graph SHALL define an outgoing transition from
QUARANTINED to a released state of READY. In ``src/aro/lifecycle.py`` the pure
graph encodes exactly ``QUARANTINED: {READY}`` in ``_BASE`` and deliberately
excludes QUARANTINED from ``_CONTAINMENT_SOURCES`` so that no containment target
(QUARANTINED/TERMINATED) and no other state becomes reachable from QUARANTINED.

The property under test: for every lifecycle state ``S``,
``can_transition(QUARANTINED, S)`` is True iff ``S == READY``. Equivalently,
``allowed_transitions(QUARANTINED)`` equals ``frozenset({READY})`` exactly — no
QUARANTINED self-loop, no TERMINATED containment target, no other target.

Run directly:
    python3 tests/test_aro_quarantine_release_edge.py
Or via pytest:
    pytest tests/test_aro_quarantine_release_edge.py
"""
import os
import sys

from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.aro import lifecycle as lc  # noqa: E402


# Arbitrary target state across ALL lifecycle states plus a couple of
# out-of-graph sentinels, so the property also pins that bogus targets are
# never reachable from QUARANTINED.
_STATES = st.sampled_from(sorted(lc.ALL_STATES) + ["", "bogus-state"])


@given(target=_STATES)
@settings(max_examples=200)
def test_quarantined_releases_only_to_ready(target):
    """Feature: phase2-aro-completion, Property 1: QUARANTINED releases only to
    READY.

    Validates: Requirements 1.1.
    """
    # Req 1.1: the sole legal outgoing transition from QUARANTINED is to READY.
    assert lc.can_transition(lc.QUARANTINED, target) == (target == lc.READY)


def test_allowed_transitions_from_quarantined_is_exactly_ready():
    """The full outgoing set from QUARANTINED is exactly {READY}.

    Validates: Requirements 1.1.

    This pins the stronger set-equality: QUARANTINED has no self-loop and no
    TERMINATED containment target (it is excluded from _CONTAINMENT_SOURCES),
    so READY is the one and only reachable state.
    """
    assert lc.allowed_transitions(lc.QUARANTINED) == frozenset({lc.READY})
    # Explicit anchors for the exclusions the set-equality implies.
    assert not lc.can_transition(lc.QUARANTINED, lc.QUARANTINED)
    assert not lc.can_transition(lc.QUARANTINED, lc.TERMINATED)


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
