#!/usr/bin/env python3
"""Tests for automated response + containment (Task 17).

Feature: ZAF automated response (SRS §5.6).

Validates:
* plan_response escalation ladder (alert -> stop -> quarantine+incident ->
  +revoke+block at CRITICAL); risk >= 85 forces the CRITICAL plan.
* respond() executes the plan: quarantine called, credentials revoked, incident
  opened on CRITICAL; an incident record captures the actions.
* break_glass requires operator + reason, and writes an audited incident/event.

Run directly:
    python3 tests/test_zaf_response.py
Or via pytest:
    pytest tests/test_zaf_response.py
"""
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.zaf.response_service import ResponseService, plan_response  # noqa: E402


class CapturingEvents:
    def __init__(self):
        self.events = []

    def append_event(self, event):
        self.events.append(event)
        return dict(event, id=len(self.events))


class FakeIncidents:
    def __init__(self):
        self.incidents = []

    def create_incident(self, tenant_id, agent_identity, kind, severity, summary,
                        detail=None, actions_taken=None):
        iid = len(self.incidents) + 1
        self.incidents.append(dict(id=iid, kind=kind, severity=severity,
                                   actions_taken=actions_taken or []))
        return iid


def test_plan_ladder():
    assert plan_response("LOW", 0) == ["alert"]
    assert plan_response("MEDIUM", 0) == ["alert", "stop_task"]
    assert "quarantine" in plan_response("HIGH", 0)
    assert "open_incident" in plan_response("HIGH", 0)
    crit = plan_response("CRITICAL", 0)
    assert "revoke_credentials" in crit and "block_network" in crit


def test_high_risk_score_forces_critical_plan():
    plan = plan_response("LOW", 90)
    assert "revoke_credentials" in plan


def test_respond_critical_executes_full_containment():
    quarantined = []
    revoked = []
    blocked = []
    events = CapturingEvents()
    incidents = FakeIncidents()
    svc = ResponseService(
        quarantine=lambda t, a, reason: quarantined.append((t, a, reason)),
        revoke_credential=lambda t, cid: revoked.append(cid),
        block_network=lambda t, ident: blocked.append(ident),
        incident_repo=incidents, events_repo=events,
    )
    out = svc.respond(
        1, agent_identity="agent://default/a1", agent_db_id=10,
        severity="CRITICAL", risk_score=95, rule_id="process.control_socket_access",
        credential_ids=[5, 6], evidence=["docker.sock access"],
    )
    assert "quarantine" in out["actions_taken"]
    assert "revoke_credentials" in out["actions_taken"]
    assert "block_network" in out["actions_taken"]
    assert out["incident_id"] is not None
    assert quarantined and revoked == [5, 6] and blocked == ["agent://default/a1"]
    assert any(e["event_type"] == "agent.quarantined" for e in events.events)
    assert any(e["event_type"] == "security.incident.opened" for e in events.events)


def test_respond_medium_only_alerts_and_stops():
    events = CapturingEvents()
    incidents = FakeIncidents()
    svc = ResponseService(quarantine=lambda *a: None, incident_repo=incidents, events_repo=events)
    out = svc.respond(1, agent_identity="a", agent_db_id=1, severity="MEDIUM",
                      risk_score=40, rule_id="execution.loop")
    assert out["actions_taken"] == ["alert"]  # stop_task has no collaborator here; alert always
    assert out["incident_id"] is None
    assert incidents.incidents == []


def test_break_glass_requires_operator_and_reason():
    events = CapturingEvents()
    incidents = FakeIncidents()
    svc = ResponseService(incident_repo=incidents, events_repo=events)
    try:
        svc.break_glass(1, agent_identity="a", operator_identity="", reason="x")
        assert False
    except ValueError:
        pass
    out = svc.break_glass(1, agent_identity="a", operator_identity="ops-admin", reason="false positive")
    assert out["incident_id"] is not None
    assert any(e["event_type"] == "security.break_glass" for e in events.events)


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
