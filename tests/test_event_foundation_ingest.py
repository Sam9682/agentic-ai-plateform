"""ABF/AET event foundation (Phase 1): authenticated telemetry ingestion.

Covers the TelemetryIngestService with injected collaborators (no DB):
* invalid/absent token -> 401; identity and tenant bound from the token only.
* runtime events are tagged runtime_reported with the token as principal and a
  server-assigned telemetry.<category> event type.
* cross-agent task_id rejected (trace poisoning); own task accepted.
* duplicates reported, not re-counted; client ids namespaced per agent.
* batch cap (413), malformed body (400), per-token rate limit (429).
* partial acceptance: one bad event does not drop the good ones.
And the ingest token repository (hash-only storage, expiry, revocation,
terminated agents) against an in-memory stub DB.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.obs import ingest_tokens  # noqa: E402
from src.obs.telemetry_ingest import TelemetryIngestService  # noqa: E402
from src.zaf.mcp_gateway import RateLimiter  # noqa: E402

NOW = datetime(2026, 11, 21, 12, 0, 0, tzinfo=timezone.utc)
BINDING = {"token_id": 3, "tenant_id": 1, "agent_db_id": 7,
           "agent_identity": "agent://default/coder", "agent_status": "RUNNING",
           "scope": "telemetry:ingest", "expires_at": None}


class MemEvents:
    def __init__(self):
        self.rows = {}

    def append_event(self, event):
        key = (event["tenant_id"], event["event_id"])
        inserted = key not in self.rows
        if inserted:
            self.rows[key] = event
        return dict(event, inserted=inserted, id=len(self.rows))


def _svc(events=None, *, binding=BINDING, task_owner=None, rpm=120, max_batch=500):
    touched = []
    svc = TelemetryIngestService(
        verify_token=lambda tok: dict(binding) if tok == "aig_good" else None,
        touch_token=touched.append,
        events_repo=events if events is not None else MemEvents(),
        task_owner=task_owner or (lambda tenant, ref: {"t-own": 7, "t-other": 8}.get(ref)),
        rate_limiter=RateLimiter(),
        requests_per_minute=rpm,
        max_batch=max_batch,
        clock=lambda: NOW,
    )
    return svc, touched


def _ev(**over):
    e = {"category": "SHELL", "action": "exec", "resource": "ls -la"}
    e.update(over)
    return e


def test_missing_or_invalid_token_is_401():
    svc, _ = _svc()
    assert svc.ingest(None, {"events": [_ev()]}).status_code == 401
    assert svc.ingest("aig_bad", {"events": [_ev()]}).status_code == 401


def test_identity_bound_from_token_and_provenance_tagged():
    events = MemEvents()
    svc, touched = _svc(events)
    res = svc.ingest("aig_good", {"events": [_ev(agent_id="agent://default/admin", tenant_id=2,
                                                 severity="INFO", event_type="governance.decision")]})
    assert res.status_code == 200 and res.payload["accepted"] == 1
    (row,) = events.rows.values()
    assert row["tenant_id"] == 1
    assert row["agent_id"] == "agent://default/coder"
    assert row["event_type"] == "telemetry.shell"
    assert row["ingest_source"] == "runtime_reported"
    assert row["ingest_principal"] == "ingest-token:3"
    assert row["source"] == "runtime-telemetry"
    assert set(row["action"]["ignored_client_fields"]) >= {"agent_id", "tenant_id", "severity", "event_type"}
    assert touched == [3]


def test_server_assigns_severity():
    events = MemEvents()
    svc, _ = _svc(events)
    svc.ingest("aig_good", {"events": [_ev(category="DATABASE", action="drop_table",
                                           resource="prod-db", severity="INFO")]})
    (row,) = events.rows.values()
    assert row["severity"] != "INFO" and row["risk_score"] > 0


def test_cross_agent_task_id_rejected_own_task_accepted():
    svc, _ = _svc()
    res = svc.ingest("aig_good", {"events": [_ev(task_id="t-other"), _ev(task_id="t-own"),
                                             _ev(task_id="t-missing")]})
    statuses = [r["status"] for r in res.payload["results"]]
    assert statuses == ["rejected", "accepted", "rejected"]
    assert "does not belong" in res.payload["results"][0]["error"]


def test_task_events_get_task_correlation():
    events = MemEvents()
    svc, _ = _svc(events)
    svc.ingest("aig_good", {"events": [_ev(task_id="t-own")]})
    (row,) = events.rows.values()
    assert row["task_id"] == "t-own" and row["correlation_id"] == "task-t-own"


def test_duplicates_reported_and_ids_namespaced():
    events = MemEvents()
    svc, _ = _svc(events)
    first = svc.ingest("aig_good", {"events": [_ev(event_id="e1")]})
    again = svc.ingest("aig_good", {"events": [_ev(event_id="e1", resource="changed")]})
    assert first.payload["accepted"] == 1
    assert again.payload["duplicates"] == 1 and again.payload["accepted"] == 0
    assert list(events.rows)[0] == (1, "rt-7-e1")
    assert events.rows[(1, "rt-7-e1")]["resource"] == "ls -la"  # first write wins


def test_parent_ids_namespaced_unless_platform_ids():
    events = MemEvents()
    svc, _ = _svc(events)
    svc.ingest("aig_good", {"events": [
        _ev(event_id="c1", parent_event_id="p1"),
        _ev(event_id="c2", parent_event_id="evt-abc"),
    ]})
    assert events.rows[(1, "rt-7-c1")]["parent_event_id"] == "rt-7-p1"
    assert events.rows[(1, "rt-7-c2")]["parent_event_id"] == "evt-abc"


def test_partial_acceptance():
    svc, _ = _svc()
    res = svc.ingest("aig_good", {"events": [_ev(), _ev(category="SECURITY"), "junk", _ev()]})
    assert (res.payload["accepted"], res.payload["rejected"]) == (2, 2)
    assert [r["index"] for r in res.payload["results"]] == [0, 1, 2, 3]


def test_batch_limits_and_malformed_body():
    svc, _ = _svc(max_batch=3)
    assert svc.ingest("aig_good", {"events": [_ev()] * 4}).status_code == 413
    assert svc.ingest("aig_good", {"events": []}).status_code == 400
    assert svc.ingest("aig_good", {"events": "x"}).status_code == 400
    assert svc.ingest("aig_good", ["not", "an", "object"]).status_code == 400


def test_rate_limit_per_token():
    svc, _ = _svc(rpm=2)
    assert svc.ingest("aig_good", {"events": [_ev()]}).status_code == 200
    assert svc.ingest("aig_good", {"events": [_ev()]}).status_code == 200
    res = svc.ingest("aig_good", {"events": [_ev()]})
    assert res.status_code == 429 and res.headers.get("Retry-After") == "60"


def test_secrets_in_reported_commands_are_redacted():
    events = MemEvents()
    svc, _ = _svc(events)
    svc.ingest("aig_good", {"events": [_ev(resource="mysql --password=hunter2 -h db",
                                           metadata={"env": "API_KEY=sk_live_123", "api_key": "x"})]})
    (row,) = events.rows.values()
    flat = repr(row)
    assert "hunter2" not in flat and "sk_live_123" not in flat


# --------------------------------------------------------------------------- #
# Ingest token repository
# --------------------------------------------------------------------------- #
class TokenDb:
    def __init__(self, agent_status="RUNNING"):
        self.tokens = {}
        self.agent_status = agent_status
        self.next_id = 1

    def execute_query(self, sql, params=None, fetch_one=False, fetch_all=False):
        s = " ".join(sql.split()).upper()
        if s.startswith("INSERT INTO AGENT_INGEST_TOKENS"):
            tenant, agent, thash, prefix, scope, exp, creator = params
            tid = self.next_id
            self.next_id += 1
            self.tokens[tid] = dict(id=tid, tenant=tenant, agent=agent, hash=thash,
                                    prefix=prefix, scope=scope, exp=exp, revoked=False)
            return (tid,)
        if s.startswith("SELECT T.ID"):
            (thash,) = params
            for t in self.tokens.values():
                if t["hash"] == thash:
                    return (t["id"], t["tenant"], t["agent"], t["scope"], t["exp"],
                            t["revoked"], "agent://default/coder", self.agent_status)
            return None
        if s.startswith("UPDATE AGENT_INGEST_TOKENS SET REVOKED") and "AND ID" in s:
            tenant, agent, tid = params
            t = self.tokens.get(tid)
            if t and t["tenant"] == tenant and t["agent"] == agent and not t["revoked"]:
                t["revoked"] = True
                return 1
            return 0
        if s.startswith("UPDATE AGENT_INGEST_TOKENS SET REVOKED"):
            tenant, agent = params
            n = 0
            for t in self.tokens.values():
                if t["tenant"] == tenant and t["agent"] == agent and not t["revoked"]:
                    t["revoked"] = True
                    n += 1
            return n
        raise AssertionError(f"unexpected SQL: {s}")


def _with_db(monkeypatch, db):
    monkeypatch.setattr(ingest_tokens, "_get_db", lambda: db)


def test_issue_stores_only_hash_and_verifies(monkeypatch):
    db = TokenDb()
    _with_db(monkeypatch, db)
    issued = ingest_tokens.issue(1, 7, now=NOW)
    stored = db.tokens[issued["id"]]
    assert issued["token"] not in repr(stored)
    assert stored["hash"] == ingest_tokens.hash_token(issued["token"])
    binding = ingest_tokens.verify(issued["token"], now=NOW)
    assert binding["tenant_id"] == 1 and binding["agent_db_id"] == 7
    assert binding["agent_identity"] == "agent://default/coder"


def test_expired_revoked_and_malformed_tokens_fail_closed(monkeypatch):
    db = TokenDb()
    _with_db(monkeypatch, db)
    issued = ingest_tokens.issue(1, 7, ttl_seconds=60, now=NOW)
    assert ingest_tokens.verify(issued["token"], now=NOW + timedelta(seconds=61)) is None
    assert ingest_tokens.verify("not-a-token", now=NOW) is None
    assert ingest_tokens.verify(None, now=NOW) is None
    assert ingest_tokens.revoke(1, 7, issued["id"]) is True
    assert ingest_tokens.verify(issued["token"], now=NOW) is None
    assert ingest_tokens.revoke(1, 7, issued["id"]) is False


def test_revoke_is_tenant_and_agent_scoped(monkeypatch):
    db = TokenDb()
    _with_db(monkeypatch, db)
    issued = ingest_tokens.issue(1, 7, now=NOW)
    assert ingest_tokens.revoke(2, 7, issued["id"]) is False
    assert ingest_tokens.revoke(1, 8, issued["id"]) is False
    assert ingest_tokens.verify(issued["token"], now=NOW) is not None


def test_revoke_all_for_agent(monkeypatch):
    db = TokenDb()
    _with_db(monkeypatch, db)
    a = ingest_tokens.issue(1, 7, now=NOW)
    b = ingest_tokens.issue(1, 7, now=NOW)
    assert ingest_tokens.revoke_all_for_agent(1, 7) == 2
    assert ingest_tokens.verify(a["token"], now=NOW) is None
    assert ingest_tokens.verify(b["token"], now=NOW) is None


def test_terminated_agent_token_refused(monkeypatch):
    db = TokenDb(agent_status="TERMINATED")
    _with_db(monkeypatch, db)
    issued = ingest_tokens.issue(1, 7, now=NOW)
    assert ingest_tokens.verify(issued["token"], now=NOW) is None


def test_ttl_is_clamped(monkeypatch):
    db = TokenDb()
    _with_db(monkeypatch, db)
    issued = ingest_tokens.issue(1, 7, ttl_seconds=10 ** 9, now=NOW)
    exp = datetime.fromisoformat(issued["expires_at"])
    assert exp - NOW == timedelta(seconds=ingest_tokens.MAX_TTL_SECONDS)
