#!/usr/bin/env python3
"""Property test for illegal-transition rejection (Task 9.11).

Feature: phase2-aro-completion, Property 5 — Only graph-legal transitions
mutate state.

Validates: Requirements 1.11.

``LifecycleService.transition()`` is the sole forward-mutation path and is the
single point where the lifecycle graph is enforced. This test pins the full
biconditional over *every* (from_state, to_state) pair across all lifecycle
states:

    transition(from -> to) mutates the persisted status AND emits an
    ``agent.transition`` event   IFF   lifecycle.can_transition(from, to).

When the edge is NOT graph-legal, transition() must raise IllegalTransition,
leave the persisted status UNCHANGED, perform NO status write at all, and emit
NO event. The inert ``zaf_pre_transition`` seam (task 9.12) is consulted only
AFTER the legality check, so it cannot influence rejection; this property holds
regardless of the seam.

Run directly:
    python3 tests/test_aro_illegal_transition.py
Or via pytest:
    pytest tests/test_aro_illegal_transition.py
"""
import os
import sys

from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.aro import lifecycle as lc  # noqa: E402
from src.aro.adapters.base import FakeAdapter  # noqa: E402
from src.aro.lifecycle_service import IllegalTransition, LifecycleService  # noqa: E402


# --------------------------------------------------------------------------- #
# Test doubles
# --------------------------------------------------------------------------- #
class InMemoryAgentRepo:
    """Minimal in-memory agent repo that TRACKS every status write.

    ``status_writes`` records each (tenant_id, agent_id, new_status) passed to
    update_status so a caller can assert that NO write occurred on a rejected
    transition ("no write" is directly observable, not inferred).
    """

    def __init__(self):
        self.agents = {}
        self.status_writes = []

    def get_agent(self, tenant_id, agent_id):
        a = self.agents.get((tenant_id, agent_id))
        return dict(a) if a else None

    def update_status(self, tenant_id, agent_id, new_status):
        self.status_writes.append((tenant_id, agent_id, new_status))
        a = self.agents.get((tenant_id, agent_id))
        if not a:
            return False
        a["status"] = new_status
        return True

    def seed(self, tenant_id, agent_id, status, identity="agent://default/a1"):
        self.agents[(tenant_id, agent_id)] = dict(
            id=agent_id, tenant_id=tenant_id, identity=identity, name="a1",
            runtime_id=1, status=status, configuration={}, permissions=[],
        )


class CapturingEvents:
    def __init__(self):
        self.events = []

    def append_event(self, event):
        self.events.append(event)
        return dict(event, id=len(self.events))


def _service(repo_obj, events):
    return LifecycleService(
        events_repo=events,
        adapter_for=lambda agent: FakeAdapter(),
        launcher=lambda agent, ref: {"server_id": 1, "container_id": "c123"},
        agent_repo=repo_obj,
    )


_STATES = st.sampled_from(sorted(lc.ALL_STATES))


# --------------------------------------------------------------------------- #
# Property 5: Only graph-legal transitions mutate state
# --------------------------------------------------------------------------- #
@given(from_state=_STATES, to_state=_STATES)
@settings(max_examples=200)
def test_property_only_legal_transitions_mutate_state(from_state, to_state):
    """Feature: phase2-aro-completion, Property 5"""
    repo_obj = InMemoryAgentRepo()
    repo_obj.seed(1, 7, status=from_state)
    events = CapturingEvents()
    svc = _service(repo_obj, events)

    legal = lc.can_transition(from_state, to_state)

    if legal:
        result = svc.transition(1, 7, to_state)
        # Persisted status mutated to the requested target.
        assert repo_obj.agents[(1, 7)]["status"] == to_state
        assert result["status"] == to_state
        # Exactly the write for this transition was recorded.
        assert repo_obj.status_writes == [(1, 7, to_state)]
        # Exactly one agent.transition event emitted, carrying from/to.
        transition_events = [
            e for e in events.events if e["event_type"] == "agent.transition"
        ]
        assert len(transition_events) == 1
        assert transition_events[0]["action"] == {
            "from": from_state, "to": to_state
        }
    else:
        # Illegal edge: must raise IllegalTransition...
        raised = False
        try:
            svc.transition(1, 7, to_state)
        except IllegalTransition as exc:
            raised = True
            assert exc.from_state == from_state
            assert exc.to_state == to_state
        assert raised, f"expected IllegalTransition for {from_state} -> {to_state}"
        # ...persisted status UNCHANGED...
        assert repo_obj.agents[(1, 7)]["status"] == from_state
        # ...NO status write performed...
        assert repo_obj.status_writes == []
        # ...and NO event emitted.
        assert events.events == []


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
