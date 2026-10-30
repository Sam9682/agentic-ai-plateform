#!/usr/bin/env python3
"""Tests for agent identity + lifecycle (Task 7).

Feature: ARO agent lifecycle management (SRS §3.2, §4.2).

Validates:
* lifecycle graph: only allowed transitions are permitted; illegal transitions
  rejected (hypothesis over all state pairs); TERMINATED is terminal.
* lifecycle service: a full REGISTERED -> READY -> RUNNING -> STOPPED drive
  against an in-memory agent repo + FakeAdapter; illegal transition raises
  IllegalTransition without mutating recorded status; an event is emitted per
  transition.
* identity: make_identity produces agent://{tenant}/{name}.
* route: end-to-end lifecycle over the Flask blueprint with stubbed repo/auth.

Run directly:
    python3 tests/test_aro_lifecycle.py
Or via pytest:
    pytest tests/test_aro_lifecycle.py
"""
import os
import sys

from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.aro import lifecycle as lc  # noqa: E402
from src.aro import agent_repository as agent_repo  # noqa: E402
from src.aro.adapters.base import FakeAdapter  # noqa: E402
from src.aro.lifecycle_service import IllegalTransition, LifecycleService  # noqa: E402


# --------------------------------------------------------------------------- #
# Pure lifecycle graph
# --------------------------------------------------------------------------- #
def test_happy_path_transitions():
    assert lc.can_transition(lc.REGISTERED, lc.INSTALLING)
    assert lc.can_transition(lc.READY, lc.STARTING)
    assert lc.can_transition(lc.STARTING, lc.RUNNING)
    assert lc.can_transition(lc.RUNNING, lc.STOPPING)
    assert lc.can_transition(lc.STOPPING, lc.STOPPED)
    assert lc.can_transition(lc.STOPPED, lc.STARTING)  # restart


def test_illegal_transitions_rejected():
    assert not lc.can_transition(lc.REGISTERED, lc.RUNNING)
    assert not lc.can_transition(lc.STOPPED, lc.RUNNING)
    assert not lc.can_transition(lc.TERMINATED, lc.RUNNING)


def test_terminated_is_terminal():
    assert lc.is_terminal(lc.TERMINATED)
    assert lc.allowed_transitions(lc.TERMINATED) == frozenset()


def test_any_nonterminal_can_be_quarantined_or_terminated():
    for state in lc.ALL_STATES - {lc.QUARANTINED, lc.TERMINATED}:
        assert lc.can_transition(state, lc.QUARANTINED)
        assert lc.can_transition(state, lc.TERMINATED)


_STATES = st.sampled_from(sorted(lc.ALL_STATES))


@given(a=_STATES, b=_STATES)
@settings(max_examples=300)
def test_property_transition_membership(a, b):
    assert lc.can_transition(a, b) == (b in lc.allowed_transitions(a))


# --------------------------------------------------------------------------- #
# Lifecycle service against in-memory repo + FakeAdapter
# --------------------------------------------------------------------------- #
class InMemoryAgentRepo:
    def __init__(self):
        self.agents = {}
        self.executions = []
        self._eid = 1

    def get_agent(self, tenant_id, agent_id):
        a = self.agents.get((tenant_id, agent_id))
        return dict(a) if a else None

    def update_status(self, tenant_id, agent_id, new_status):
        a = self.agents.get((tenant_id, agent_id))
        if not a:
            return False
        a["status"] = new_status
        return True

    def create_execution(self, tenant_id, agent_id, execution_ref, server_id=None, container_id=None):
        eid = self._eid
        self._eid += 1
        self.executions.append(dict(id=eid, tenant_id=tenant_id, agent_id=agent_id,
                                    execution_ref=execution_ref, server_id=server_id,
                                    container_id=container_id, status="STARTING"))
        return eid

    def seed(self, tenant_id, agent_id, identity="agent://default/a1"):
        self.agents[(tenant_id, agent_id)] = dict(
            id=agent_id, tenant_id=tenant_id, identity=identity, name="a1",
            runtime_id=1, status=lc.REGISTERED, configuration={}, permissions=[],
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


def test_identity_format():
    assert agent_repo.make_identity("default", "infra-agent-01") == "agent://default/infra-agent-01"


def test_full_lifecycle_drive():
    repo_obj = InMemoryAgentRepo()
    repo_obj.seed(1, 10)
    events = CapturingEvents()
    svc = _service_with(repo_obj, events)

    svc.install_and_ready(1, 10)
    assert repo_obj.agents[(1, 10)]["status"] == lc.READY
    svc.start(1, 10)
    assert repo_obj.agents[(1, 10)]["status"] == lc.RUNNING
    assert len(repo_obj.executions) == 1
    svc.stop(1, 10)
    assert repo_obj.agents[(1, 10)]["status"] == lc.STOPPED
    # events emitted for transitions + milestones
    assert any(e["event_type"] == "agent.started" for e in events.events)
    assert any(e["event_type"] == "agent.stopped" for e in events.events)


def test_illegal_transition_does_not_mutate_status():
    repo_obj = InMemoryAgentRepo()
    repo_obj.seed(1, 11)  # status REGISTERED
    svc = _service_with(repo_obj, CapturingEvents())
    try:
        svc.transition(1, 11, lc.RUNNING)  # REGISTERED -> RUNNING is illegal
        assert False
    except IllegalTransition:
        pass
    assert repo_obj.agents[(1, 11)]["status"] == lc.REGISTERED


def test_quarantine_from_running():
    repo_obj = InMemoryAgentRepo()
    repo_obj.seed(1, 12)
    svc = _service_with(repo_obj, CapturingEvents())
    svc.install_and_ready(1, 12)
    svc.start(1, 12)
    svc.quarantine(1, 12, reason="anomaly")
    assert repo_obj.agents[(1, 12)]["status"] == lc.QUARANTINED


# --------------------------------------------------------------------------- #
# Route-level lifecycle
# --------------------------------------------------------------------------- #
def test_route_lifecycle(monkeypatch):
    from src import authz
    from src.routes import aro_agent_routes as routes
    from flask import Flask

    repo_obj = InMemoryAgentRepo()
    repo_obj.seed(1, 20)

    monkeypatch.setattr(
        authz, "membership_loader",
        lambda uid: [{"tenant_id": 1, "tenant_slug": "default", "role": "operator", "is_default": True}],
    )
    # Point the route's repo + service at our in-memory objects.
    monkeypatch.setattr(routes.repo, "get_agent", repo_obj.get_agent)
    monkeypatch.setattr(routes.repo, "list_agents",
                        lambda tid: [v for (t, _), v in repo_obj.agents.items() if t == tid])
    monkeypatch.setattr(routes, "_service", lambda: _service_with(repo_obj, CapturingEvents()))

    app = Flask(__name__)
    app.secret_key = "t"
    app.register_blueprint(routes.aro_agent_bp)
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 1

    assert client.post("/api/v1/agents/20/ready").status_code == 200
    assert repo_obj.agents[(1, 20)]["status"] == lc.READY
    assert client.post("/api/v1/agents/20/start").status_code == 200
    assert repo_obj.agents[(1, 20)]["status"] == lc.RUNNING
    # Illegal: start again while RUNNING -> STARTING is not allowed from RUNNING
    resp = client.post("/api/v1/agents/20/start")
    assert resp.status_code == 409
    assert client.post("/api/v1/agents/20/stop").status_code == 200
    assert repo_obj.agents[(1, 20)]["status"] == lc.STOPPED


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
