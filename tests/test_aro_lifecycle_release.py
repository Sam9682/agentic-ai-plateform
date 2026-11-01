#!/usr/bin/env python3
"""Property test for QUARANTINED release semantics (Task 9.4).

Feature: phase2-aro-completion.

Validates:
* Property 2 — Release succeeds only from QUARANTINED, otherwise no change
  (Requirements 1.2, 1.3). For an agent seeded in an arbitrary starting
  lifecycle status, LifecycleService.release() transitions it to READY and
  emits exactly one `agent.released` event ONLY when the starting status is
  QUARANTINED. For any other starting status, release() raises
  IllegalTransition and leaves the recorded status UNCHANGED, performing no
  status write and emitting no event.

This file intentionally replicates the InMemoryAgentRepo + CapturingEvents
pattern from tests/test_aro_lifecycle.py (that file is left untouched). The
InMemoryAgentRepo is extended with a write counter so the property can assert
"no write" on the rejection path, not merely "status unchanged".

Run directly:
    python3 tests/test_aro_lifecycle_release.py
Or via pytest:
    pytest tests/test_aro_lifecycle_release.py
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
# In-memory fixtures (replicated from tests/test_aro_lifecycle.py, extended
# with a status-write counter so "no write" is directly observable).
# --------------------------------------------------------------------------- #
class InMemoryAgentRepo:
    def __init__(self):
        self.agents = {}
        self.executions = []
        self._eid = 1
        self.status_writes = 0

    def get_agent(self, tenant_id, agent_id):
        a = self.agents.get((tenant_id, agent_id))
        return dict(a) if a else None

    def update_status(self, tenant_id, agent_id, new_status):
        a = self.agents.get((tenant_id, agent_id))
        if not a:
            return False
        a["status"] = new_status
        self.status_writes += 1
        return True

    def create_execution(self, tenant_id, agent_id, execution_ref, server_id=None, container_id=None):
        eid = self._eid
        self._eid += 1
        self.executions.append(dict(id=eid, tenant_id=tenant_id, agent_id=agent_id,
                                    execution_ref=execution_ref, server_id=server_id,
                                    container_id=container_id, status="STARTING",
                                    ended_at=None))
        return eid

    def _find_execution(self, tenant_id, execution_id):
        for e in self.executions:
            if e["tenant_id"] == tenant_id and e["id"] == execution_id:
                return e
        return None

    def latest_running_execution(self, tenant_id, agent_id):
        candidates = [
            e for e in self.executions
            if e["tenant_id"] == tenant_id and e["agent_id"] == agent_id
            and e.get("ended_at") is None
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda e: e["id"])["id"]

    def set_execution_status(self, tenant_id, execution_id, status, ended=False):
        e = self._find_execution(tenant_id, execution_id)
        if not e:
            return False
        e["status"] = status
        if ended:
            e["ended_at"] = "2026-01-01T00:00:00Z"
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


def _service_with(repo_obj, events):
    return LifecycleService(
        events_repo=events,
        adapter_for=lambda agent: FakeAdapter(),
        launcher=lambda agent, ref: {"server_id": 1, "container_id": "c123"},
        agent_repo=repo_obj,
    )


# All lifecycle states are candidate starting points for the property.
_STATES = st.sampled_from(sorted(lc.ALL_STATES))


@given(start=_STATES)
@settings(max_examples=200)
def test_property_release_only_from_quarantined(start):
    """Feature: phase2-aro-completion, Property 2: Release succeeds only from
    QUARANTINED, otherwise no change (Validates: Requirements 1.2, 1.3).

    For any starting status:
    * QUARANTINED -> release() moves to READY, emits exactly one
      ``agent.released`` event (Req 1.2).
    * otherwise  -> release() raises IllegalTransition, status is UNCHANGED,
      no status write occurred, and no event was emitted (Req 1.3).
    """
    repo_obj = InMemoryAgentRepo()
    repo_obj.seed(1, 10, status=start)
    events = CapturingEvents()
    svc = _service_with(repo_obj, events)

    if start == lc.QUARANTINED:
        result = svc.release(1, 10)
        # Req 1.2: transitioned to READY and emitted agent.released.
        assert result["status"] == lc.READY
        assert repo_obj.agents[(1, 10)]["status"] == lc.READY
        released = [e for e in events.events if e["event_type"] == "agent.released"]
        assert len(released) == 1
    else:
        try:
            svc.release(1, 10)
            assert False, f"release() should reject start status {start!r}"
        except IllegalTransition as exc:
            # The rejection names the actual illegal edge start -> READY.
            assert exc.from_state == start
            assert exc.to_state == lc.READY
        # Req 1.3: no state change — status unchanged, no write, no event.
        assert repo_obj.agents[(1, 10)]["status"] == start
        assert repo_obj.status_writes == 0
        assert events.events == []


# --------------------------------------------------------------------------- #
# Concrete anchor examples complementing the property (fast to read, pin the
# two representative cases explicitly).
# --------------------------------------------------------------------------- #
def test_release_from_quarantined_goes_ready_and_emits():
    repo_obj = InMemoryAgentRepo()
    repo_obj.seed(1, 1, status=lc.QUARANTINED)
    events = CapturingEvents()
    svc = _service_with(repo_obj, events)

    svc.release(1, 1)

    assert repo_obj.agents[(1, 1)]["status"] == lc.READY
    assert any(e["event_type"] == "agent.released" for e in events.events)


def test_release_from_running_is_rejected_without_change():
    repo_obj = InMemoryAgentRepo()
    repo_obj.seed(1, 2, status=lc.RUNNING)
    events = CapturingEvents()
    svc = _service_with(repo_obj, events)

    try:
        svc.release(1, 2)
        assert False
    except IllegalTransition:
        pass

    assert repo_obj.agents[(1, 2)]["status"] == lc.RUNNING
    assert repo_obj.status_writes == 0
    assert events.events == []


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
