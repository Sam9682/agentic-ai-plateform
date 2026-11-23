"""ABF/AET event foundation (Phase 1): telemetry + behavior routes.

Behind the real ``src.authz`` decorators with repositories stubbed:
* /telemetry/events requires a bearer ingest token, never a session; size cap.
* token issue/revoke require admin, list requires operator; issuance is audited
  without the token value.
* /agents/{id}/behavior is tenant-scoped: another tenant's agent -> 404 (IDOR),
  the query is pinned to the agent's identity, bad cursor -> 400.
"""
import os
import sys

import pytest
from flask import Flask

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

AGENTS = {(1, 7): {"id": 7, "tenant_id": 1, "identity": "agent://t1/coder", "status": "RUNNING"},
          (2, 9): {"id": 9, "tenant_id": 2, "identity": "agent://t2/other", "status": "RUNNING"}}


@pytest.fixture
def ctx(monkeypatch):
    from src import authz
    from src.routes import telemetry_routes as tr

    state = {"role": "admin", "tenant": 1, "audit": [], "queries": [], "issued": []}

    monkeypatch.setattr(authz, "membership_loader", lambda uid: [
        {"tenant_id": state["tenant"], "tenant_slug": "t", "role": state["role"], "is_default": True}])
    monkeypatch.setattr(tr.agent_repo, "get_agent", lambda tid, aid: AGENTS.get((tid, aid)))

    def fake_issue(tid, aid, **kw):
        state["issued"].append((tid, aid, kw))
        return {"id": 11, "token": "aig_abcd_SECRETVALUE", "token_prefix": "aig_abcd",
                "scope": "telemetry:ingest", "expires_at": "2026-11-22T00:00:00+00:00"}

    monkeypatch.setattr(tr.ingest_tokens, "issue", fake_issue)
    monkeypatch.setattr(tr.ingest_tokens, "list_for_agent", lambda tid, aid: [{"id": 11}])
    monkeypatch.setattr(tr.ingest_tokens, "revoke", lambda tid, aid, tok: tok == 11)
    monkeypatch.setattr(tr.event_service, "emit",
                        lambda repo, tid, et, src, **kw: state["audit"].append((tid, et, kw)))

    def fake_query(tid, **kw):
        state["queries"].append((tid, kw))
        if kw.get("cursor") == "bad":
            raise ValueError("malformed cursor")
        return {"events": [{"id": 1}], "next_cursor": None}

    monkeypatch.setattr(tr.events_repo, "query_events", fake_query)

    class FakeService:
        def __init__(self):
            self.calls = []

        def ingest(self, token, body):
            from src.obs.telemetry_ingest import IngestResult
            self.calls.append((token, body))
            if token != "aig_good":
                return IngestResult(401, {"error": "invalid"})
            return IngestResult(200, {"accepted": 1}, {"X-Test": "1"})

    service = FakeService()
    monkeypatch.setattr(tr, "get_ingest_service", lambda: service)

    app = Flask(__name__)
    app.secret_key = "t"
    app.register_blueprint(tr.telemetry_bp)
    client = app.test_client()
    state["service"] = service
    return client, state


def _login(client, uid=1):
    with client.session_transaction() as sess:
        sess["user_id"] = uid


def test_ingest_requires_bearer_token_not_session(ctx):
    client, state = ctx
    _login(client)  # a browser session alone must not authenticate ingestion
    assert client.post("/api/v1/telemetry/events", json={"events": []}).status_code == 401
    assert client.post("/api/v1/telemetry/events", json={"events": []},
                       headers={"Authorization": "Basic x"}).status_code == 401
    assert state["service"].calls == []
    resp = client.post("/api/v1/telemetry/events", json={"events": [{}]},
                       headers={"Authorization": "Bearer aig_good"})
    assert resp.status_code == 200 and resp.headers["X-Test"] == "1"


def test_ingest_body_size_cap(ctx, monkeypatch):
    from src.routes import telemetry_routes as tr
    client, _ = ctx
    monkeypatch.setattr(tr, "MAX_INGEST_BODY_BYTES", 10)
    resp = client.post("/api/v1/telemetry/events", data="x" * 100,
                       headers={"Authorization": "Bearer aig_good", "Content-Type": "application/json"})
    assert resp.status_code == 413


def test_issue_token_admin_only_and_audited_without_secret(ctx):
    client, state = ctx
    _login(client)
    state["role"] = "operator"
    assert client.post("/api/v1/agents/7/telemetry-tokens", json={}).status_code == 403
    state["role"] = "admin"
    resp = client.post("/api/v1/agents/7/telemetry-tokens", json={"ttl_seconds": 600})
    assert resp.status_code == 201 and resp.get_json()["token"].startswith("aig_")
    assert state["issued"][0][:2] == (1, 7)
    (tid, et, kw), = state["audit"]
    assert et == "security.ingest_token.issued"
    assert "SECRETVALUE" not in repr(kw)


def test_issue_token_for_other_tenant_agent_is_404(ctx):
    client, state = ctx
    _login(client)
    assert client.post("/api/v1/agents/9/telemetry-tokens", json={}).status_code == 404
    assert state["issued"] == []


def test_list_and_revoke_tokens(ctx):
    client, state = ctx
    _login(client)
    state["role"] = "viewer"
    assert client.get("/api/v1/agents/7/telemetry-tokens").status_code == 403
    state["role"] = "operator"
    assert client.get("/api/v1/agents/7/telemetry-tokens").status_code == 200
    assert client.post("/api/v1/agents/7/telemetry-tokens/11/revoke").status_code == 403
    state["role"] = "admin"
    assert client.post("/api/v1/agents/7/telemetry-tokens/11/revoke").status_code == 200
    assert client.post("/api/v1/agents/7/telemetry-tokens/12/revoke").status_code == 404
    assert state["audit"][-1][1] == "security.ingest_token.revoked"


def test_behavior_requires_auth(ctx):
    client, _ = ctx
    assert client.get("/api/v1/agents/7/behavior").status_code == 401


def test_behavior_is_tenant_scoped_and_pinned_to_identity(ctx):
    client, state = ctx
    _login(client)
    state["role"] = "viewer"
    resp = client.get("/api/v1/agents/7/behavior?category=shell&min_severity=HIGH"
                      "&agent_id=agent://t2/other&limit=20")
    assert resp.status_code == 200
    tid, kw = state["queries"][-1]
    assert tid == 1
    assert kw["filters"]["agent_id"] == "agent://t1/coder"  # query param cannot override
    assert kw["filters"]["category"] == "SHELL"
    assert kw["min_severity"] == "HIGH" and kw["limit"] == 20


def test_behavior_idor_other_tenant_agent_404(ctx):
    client, state = ctx
    _login(client)
    assert client.get("/api/v1/agents/9/behavior").status_code == 404
    # Even forcing the other tenant via header fails: user is not a member there.
    resp = client.get("/api/v1/agents/9/behavior", headers={"X-Tenant-Id": "2"})
    assert resp.status_code == 403
    assert state["queries"] == []


def test_behavior_bad_cursor_and_limit(ctx):
    client, _ = ctx
    _login(client)
    assert client.get("/api/v1/agents/7/behavior?cursor=bad").status_code == 400
    assert client.get("/api/v1/agents/7/behavior?limit=abc").status_code == 400
