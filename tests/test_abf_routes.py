"""ABF Phase 2: API security (spec §12.5).

Real ``src.authz`` decorators, repositories stubbed:
* IDOR: another tenant's agent id is a 404 on every ABF route.
* Roles: quarantine needs operator, release / rules / audit need admin.
* /firewall/check needs an agent token with the firewall scope (a session or a
  telemetry-only token is refused) and never returns rule internals.
* Task submission to a quarantined agent is refused (F6).
* A lifecycle policy deny surfaces as 403 (F1).
* Approval aliases reuse the governance views (same role checks).
* Rule customisation accepts data only (no pattern / code).
"""
import os
import sys

import pytest
from flask import Flask

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

AGENTS = {(1, 7): {"id": 7, "tenant_id": 1, "identity": "agent://t1/coder", "status": "RUNNING"},
          (1, 8): {"id": 8, "tenant_id": 1, "identity": "agent://t1/jail", "status": "QUARANTINED"},
          (2, 9): {"id": 9, "tenant_id": 2, "identity": "agent://t2/other", "status": "RUNNING"}}


@pytest.fixture
def ctx(monkeypatch):
    from src import authz
    from src.abf import firewall as fwmod
    from src.routes import abf_routes as ar
    from src.routes import aro_agent_routes as agr
    from src.routes import aro_task_routes as tr
    from src.routes import zaf_governance_routes as zg
    from src.zaf import wiring

    state = {"role": "admin", "tenant": 1, "audit": [], "guards": [], "quarantined": [],
             "approved": [], "submitted": [], "rules": []}
    get = lambda tid, aid: AGENTS.get((tid, aid))  # noqa: E731
    monkeypatch.setattr(authz, "membership_loader", lambda uid: [
        {"tenant_id": state["tenant"], "tenant_slug": "t", "role": state["role"], "is_default": True}])
    monkeypatch.setattr(ar.agent_repo, "get_agent", get)
    monkeypatch.setattr(agr.repo, "get_agent", get)
    monkeypatch.setattr(tr.agent_repo, "get_agent", get)
    monkeypatch.setattr(tr.repo, "submit", lambda *a, **k: state["submitted"].append(a) or {"id": 1})
    monkeypatch.setattr(ar.es, "emit", lambda repo, tid, et, src, **kw: state["audit"].append(et))
    monkeypatch.setattr(ar.abf_repo, "list_alerts", lambda tid, **kw: [
        {"id": 5}] if kw.get("agent_db_id") == 7 else [])
    monkeypatch.setattr(ar.abf_repo, "set_alert_status", lambda *a: True)
    monkeypatch.setattr(ar.abf_repo, "list_rules", lambda tid, aid=None: [])
    monkeypatch.setattr(ar.abf_repo, "create_rule",
                        lambda tid, spec, **kw: state["rules"].append(spec) or 3)
    monkeypatch.setattr(ar.abf_repo, "get_rule", lambda tid, rid: {"id": rid, "agent_id": 7})
    monkeypatch.setattr(ar.abf_repo, "list_baselines", lambda tid, aid: [])
    monkeypatch.setattr(ar.audit_chain, "verify", lambda tid: {"valid": True, "tenant": tid})

    def fake_quarantine(tid, aid, **kw):
        state["quarantined"].append((tid, aid, kw["reason"]))
        return {"id": aid, "status": "QUARANTINED", "revoked": {}}

    monkeypatch.setattr(wiring, "quarantine_agent", fake_quarantine)

    def fake_verify(token, *, now=None, scope="telemetry:ingest"):
        if token == "aig_fw" and scope == "firewall:check":
            return {"token_id": 4, "tenant_id": 1, "agent_db_id": 7,
                    "agent_identity": "agent://t1/coder", "agent_status": "RUNNING"}
        return None  # aig_telemetry only has telemetry:ingest

    monkeypatch.setattr(ar.ingest_tokens, "verify", fake_verify)
    monkeypatch.setattr(ar.ingest_tokens, "touch", lambda tid: None)

    class FakeFirewall:
        def guard(self, req):
            state["guards"].append(req)
            return fwmod.GuardResult("ALLOW", True, "ok", "abf.shell.exec",
                                     rule_hits=[{"rule_id": "secret"}])

    fwmod.set_firewall(FakeFirewall())
    monkeypatch.setattr(zg.approvals, "list_pending", lambda tid: [{"id": 1, "tenant": tid}])
    monkeypatch.setattr(zg.approvals, "approve",
                        lambda tid, aid, uid: state["approved"].append((tid, aid, uid)) or {"id": aid})

    app = Flask(__name__)
    app.secret_key = "t"
    for bp in (ar.abf_bp, agr.aro_agent_bp, tr.aro_task_bp, zg.zaf_governance_bp):
        app.register_blueprint(bp)
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 1
    yield client, state, agr
    fwmod.set_firewall(None)


@pytest.mark.parametrize("method,path", [
    ("get", "/api/v1/agents/9/alerts"), ("get", "/api/v1/agents/9/rules"),
    ("get", "/api/v1/agents/9/baseline"), ("post", "/api/v1/agents/9/quarantine"),
    ("post", "/api/v1/agents/9/rules"), ("post", "/api/v1/agents/9/baseline/reset"),
    ("post", "/api/v1/agents/9/alerts/5/acknowledge"),
])
def test_cross_tenant_agent_is_404(ctx, method, path):
    client, state, _ = ctx
    resp = getattr(client, method)(path, json={"kind": "override", "rule_key": "abf.fs.mkfs"})
    assert resp.status_code == 404
    assert state["quarantined"] == [] and state["rules"] == []


def test_alert_of_another_agent_is_404(ctx):
    client, _, _ = ctx
    assert client.post("/api/v1/agents/8/alerts/5/resolve").status_code == 404
    assert client.post("/api/v1/agents/7/alerts/5/resolve").status_code == 200


@pytest.mark.parametrize("role,path,expected", [
    ("viewer", "/api/v1/agents/7/quarantine", 403),
    ("operator", "/api/v1/agents/7/quarantine", 200),
    ("operator", "/api/v1/agents/7/release", 403),
    ("viewer", "/api/v1/agents/7/release", 403),
    ("operator", "/api/v1/agents/7/baseline/reset", 403),
    ("operator", "/api/v1/agents/7/rules", 403),
])
def test_roles(ctx, role, path, expected):
    client, state, _ = ctx
    state["role"] = role
    resp = client.post(path, json={"kind": "override", "rule_key": "abf.fs.mkfs"})
    assert resp.status_code == expected


def test_quarantine_records_actor_reason(ctx):
    client, state, _ = ctx
    state["role"] = "operator"
    resp = client.post("/api/v1/agents/7/quarantine", json={"reason": "suspicious"})
    assert resp.status_code == 200 and state["quarantined"] == [(1, 7, "manual: suspicious")]
    assert "abf.quarantine.manual" in state["audit"]


def test_audit_verify_admin_only(ctx):
    client, state, _ = ctx
    state["role"] = "operator"
    assert client.get("/api/v1/governance/audit/verify").status_code == 403
    state["role"] = "admin"
    resp = client.get("/api/v1/governance/audit/verify")
    assert resp.status_code == 200 and resp.get_json() == {"valid": True, "tenant": 1}


def test_firewall_check_requires_scoped_agent_token(ctx):
    client, state, _ = ctx
    body = {"category": "SHELL", "action": "exec", "command": "ls"}
    assert client.post("/api/v1/firewall/check", json=body).status_code == 401  # session only
    assert client.post("/api/v1/firewall/check", json=body,
                       headers={"Authorization": "Bearer aig_telemetry"}).status_code == 401
    resp = client.post("/api/v1/firewall/check", json=body,
                       headers={"Authorization": "Bearer aig_fw"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["allowed"] is True and "rule_hits" not in data and data["rules_matched"] == 1
    req = state["guards"][0]
    assert (req.tenant_id, req.agent_db_id) == (1, 7)  # from the token, not the body


@pytest.mark.parametrize("body", [
    {"category": "SECURITY", "action": "x"},    # control-plane-only category
    {"category": "RUNTIME", "action": "x"},
    {"category": "SHELL"},                       # missing action
    {"category": "SHELL", "action": "x", "command": 5},
    {"category": "SHELL", "action": "x", "session_id": "bad id"},
    {"category": "SHELL", "action": "x", "params": ["not", "object"]},
])
def test_firewall_check_validation(ctx, body):
    client, state, _ = ctx
    resp = client.post("/api/v1/firewall/check", json=body,
                       headers={"Authorization": "Bearer aig_fw"})
    assert resp.status_code == 400 and state["guards"] == []


def test_firewall_check_rejects_foreign_task(ctx, monkeypatch):
    from src.aro import task_repository
    client, state, _ = ctx
    monkeypatch.setattr(task_repository, "get_task_agent_by_ref", lambda t, ref: 99)
    resp = client.post("/api/v1/firewall/check",
                       json={"category": "SHELL", "action": "x", "task_id": "task-abc"},
                       headers={"Authorization": "Bearer aig_fw"})
    assert resp.status_code == 400 and state["guards"] == []


def test_task_submission_refused_for_quarantined_agent(ctx):
    client, state, _ = ctx
    state["role"] = "operator"
    resp = client.post("/api/v1/agents/tasks", json={"agent_id": 8})
    assert resp.status_code == 409 and resp.get_json()["agent_status"] == "QUARANTINED"
    assert state["submitted"] == []
    assert client.post("/api/v1/agents/tasks", json={"agent_id": 7}).status_code == 201


def test_lifecycle_policy_deny_is_403(ctx, monkeypatch):
    from src.zaf.enforcement import EnforcementError
    client, state, agr = ctx
    state["role"] = "operator"

    class Svc:
        def start(self, t, a):
            raise EnforcementError(seam="pre_transition", decision="DENY", reason="tenant rule",
                                   action="agent.transition.STARTING", agent_identity="x")

    monkeypatch.setattr(agr, "_service", lambda: Svc())
    resp = client.post("/api/v1/agents/7/start")
    assert resp.status_code == 403 and resp.get_json()["reason"] == "tenant rule"


def test_live_service_has_enforcer_wired():
    from src.routes import aro_agent_routes as agr
    svc = agr._service()
    assert svc._zaf.__name__ == "pre_transition"  # not the inert lambda


def test_approval_aliases_share_role_checks(ctx):
    client, state, _ = ctx
    assert client.get("/api/v1/approvals").get_json() == {"approvals": [{"id": 1, "tenant": 1}]}
    state["role"] = "operator"
    assert client.post("/api/v1/approvals/3/approve").status_code == 403
    state["role"] = "admin"
    assert client.post("/api/v1/approvals/3/approve").status_code == 200
    assert state["approved"] == [(1, 3, 1)]


@pytest.mark.parametrize("body", [
    {"kind": "override", "rule_key": "not.a.builtin"},
    {"kind": "threshold", "rule_key": "x", "threshold": 5},              # no window
    {"kind": "threshold", "rule_key": "x", "threshold": 5, "window_seconds": 60,
     "matcher": {"pattern": ".*"}},                                      # code-like matcher
    {"kind": "override", "rule_key": "abf.fs.mkfs", "enforcement_action": "EXEC"},
    {"kind": "override", "rule_key": "abf.fs.mkfs", "risk_level": "extreme"},
    {"kind": "script", "rule_key": "x"},
])
def test_rule_customisation_is_validated_data(ctx, body):
    client, state, _ = ctx
    assert client.post("/api/v1/agents/7/rules", json=body).status_code == 400
    assert state["rules"] == []


def test_rule_customisation_created(ctx):
    client, state, _ = ctx
    resp = client.post("/api/v1/agents/7/rules", json={
        "kind": "override", "rule_key": "abf.sql.drop_table", "enforcement_action": "QUARANTINE",
        "scope": "tenant"})
    assert resp.status_code == 201
    assert state["rules"][0]["agent_id"] is None and "abf.rule.created" in state["audit"]
