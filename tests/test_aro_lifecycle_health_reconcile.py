#!/usr/bin/env python3
"""Property test for the health-reconcile service flow (Task 9.6).

Feature: phase2-aro-completion, Property 3: Health reconcile drives
RUNNING<->UNHEALTHY (service portion).

Validates: Requirements 1.4, 1.5.

This is the SERVICE portion of Property 3 (the pure decision portion lives in
``tests/test_aro_reconcile_health.py``, Task 2.4). It exercises
``LifecycleService.health_reconcile(tenant_id, agent_id)`` end to end:

* probe the injected adapter's ``health_check()`` result;
* apply ``lifecycle.reconcile_health(status, healthy)`` via ``transition()``;
* emit ``agent.unhealthy`` on RUNNING -> UNHEALTHY (Req 1.4) and
  ``agent.recovered`` on UNHEALTHY -> RUNNING (Req 1.5);
* otherwise leave the agent unchanged and emit no reconcile event.

For an agent seeded in an arbitrary lifecycle status with an injected adapter
whose ``health_check()`` returns an arbitrary bool, the property asserts the
service ends in exactly the state predicted by ``reconcile_health`` and emits
the matching event only on the two directed edges.

Run directly:
    python3 tests/test_aro_lifecycle_health_reconcile.py
Or via pytest:
    pytest tests/test_aro_lifecycle_health_reconcile.py
"""
import os
import sys

from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.aro import lifecycle as lc  # noqa: E402
from src.aro.lifecycle_service import LifecycleService  # noqa: E402


# --------------------------------------------------------------------------- #
# Minimal in-memory test doubles (no DB, no SSH) for the service flow.
# --------------------------------------------------------------------------- #
class InMemoryAgentRepo:
    """Tiny agent repo backing LifecycleService.health_reconcile."""

    def __init__(self):
        self.agents = {}

    def get_agent(self, tenant_id, agent_id):
        a = self.agents.get((tenant_id, agent_id))
        return dict(a) if a else None

    def update_status(self, tenant_id, agent_id, new_status):
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


class _StubAdapter:
    """Adapter stub whose health_check() returns a configurable fixed bool."""

    def __init__(self, healthy):
        self._healthy = healthy

    def health_check(self):
        return self._healthy


# Arbitrary lifecycle status to seed the agent in (every real state).
_STATES = st.sampled_from(sorted(lc.ALL_STATES))

# The two reconcile event names the service emits on a directed edge.
_RECONCILE_EVENTS = {"agent.unhealthy", "agent.recovered"}


@given(status=_STATES, healthy=st.booleans())
@settings(max_examples=200)
def test_health_reconcile_service_flow(status, healthy):
    """Feature: phase2-aro-completion, Property 3: Health reconcile drives
    RUNNING<->UNHEALTHY (service portion).

    Validates: Requirements 1.4, 1.5.

    For an agent seeded in an arbitrary status with an injected adapter whose
    health_check() returns an arbitrary bool, health_reconcile() ends in the
    state predicted by reconcile_health(status, healthy) and emits the matching
    event only on the two directed edges.
    """
    repo_obj = InMemoryAgentRepo()
    repo_obj.seed(1, 10, status=status)
    events = CapturingEvents()
    svc = LifecycleService(
        events_repo=events,
        adapter_for=lambda agent: _StubAdapter(healthy),
        agent_repo=repo_obj,
    )

    expected_target = lc.reconcile_health(status, healthy)

    result = svc.health_reconcile(1, 10)

    final_status = repo_obj.agents[(1, 10)]["status"]
    emitted_types = [e["event_type"] for e in events.events]
    reconcile_emitted = [t for t in emitted_types if t in _RECONCILE_EVENTS]

    if expected_target is None:
        # No reconcile decision: the agent is unchanged and no reconcile event
        # (and no transition event) is emitted.
        assert final_status == status
        assert result["status"] == status
        assert reconcile_emitted == []
        assert "agent.transition" not in emitted_types
    elif expected_target == lc.UNHEALTHY:
        # Req 1.4: RUNNING + unhealthy -> UNHEALTHY, emits agent.unhealthy.
        assert status == lc.RUNNING and not healthy
        assert final_status == lc.UNHEALTHY
        assert result["status"] == lc.UNHEALTHY
        assert reconcile_emitted == ["agent.unhealthy"]
    else:
        # Req 1.5: UNHEALTHY + healthy -> RUNNING, emits agent.recovered.
        assert expected_target == lc.RUNNING
        assert status == lc.UNHEALTHY and healthy
        assert final_status == lc.RUNNING
        assert result["status"] == lc.RUNNING
        assert reconcile_emitted == ["agent.recovered"]

    # The final persisted status is exactly what the pure decision predicts:
    # the reconcile target when one exists, otherwise the untouched seed status.
    assert final_status == (expected_target if expected_target is not None else status)


def test_health_reconcile_no_adapter_is_noop():
    """With no adapter_for there is nothing to probe: the agent is unchanged
    and no reconcile event is emitted."""
    repo_obj = InMemoryAgentRepo()
    repo_obj.seed(1, 11, status=lc.RUNNING)
    events = CapturingEvents()
    svc = LifecycleService(events_repo=events, agent_repo=repo_obj)

    result = svc.health_reconcile(1, 11)

    assert result["status"] == lc.RUNNING
    assert repo_obj.agents[(1, 11)]["status"] == lc.RUNNING
    assert [e["event_type"] for e in events.events
            if e["event_type"] in _RECONCILE_EVENTS] == []


def test_health_reconcile_examples():
    """Concrete anchors for the two directed edges and representative no-ops."""
    # RUNNING + unhealthy -> UNHEALTHY (agent.unhealthy).
    repo_obj = InMemoryAgentRepo()
    repo_obj.seed(1, 20, status=lc.RUNNING)
    events = CapturingEvents()
    svc = LifecycleService(events_repo=events,
                           adapter_for=lambda a: _StubAdapter(False),
                           agent_repo=repo_obj)
    out = svc.health_reconcile(1, 20)
    assert out["status"] == lc.UNHEALTHY
    assert any(e["event_type"] == "agent.unhealthy" for e in events.events)

    # UNHEALTHY + healthy -> RUNNING (agent.recovered).
    repo_obj = InMemoryAgentRepo()
    repo_obj.seed(1, 21, status=lc.UNHEALTHY)
    events = CapturingEvents()
    svc = LifecycleService(events_repo=events,
                           adapter_for=lambda a: _StubAdapter(True),
                           agent_repo=repo_obj)
    out = svc.health_reconcile(1, 21)
    assert out["status"] == lc.RUNNING
    assert any(e["event_type"] == "agent.recovered" for e in events.events)

    # No-ops: RUNNING + healthy, UNHEALTHY + unhealthy, and an unrelated state.
    for aid, status, healthy in [(30, lc.RUNNING, True),
                                 (31, lc.UNHEALTHY, False),
                                 (32, lc.READY, False)]:
        repo_obj = InMemoryAgentRepo()
        repo_obj.seed(1, aid, status=status)
        events = CapturingEvents()
        svc = LifecycleService(events_repo=events,
                               adapter_for=lambda a, h=healthy: _StubAdapter(h),
                               agent_repo=repo_obj)
        out = svc.health_reconcile(1, aid)
        assert out["status"] == status
        assert [e["event_type"] for e in events.events
                if e["event_type"] in _RECONCILE_EVENTS] == []


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
