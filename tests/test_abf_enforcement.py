"""ABF Phase 2: enforcement — PDP, approvals, seams, firewall, quarantine.

Covers spec §12.1 enforcement and §12.5 security cases with in-memory fakes:
* PDP: quarantined / terminated / unknown agent refused; agent_status cannot be
  supplied by the caller; platform baseline keeps lifecycle allowed; store
  outage fails closed; an unauditable ALLOW is not returned.
* Approvals (F4): single use, replay refused, bound to agent and session,
  expired approval unusable, modified params need a new approval.
* Seams (F1): progress transitions gated, containment/stop/health never gated.
* Firewall guard: ABF floor tightens never loosens, approval flow, fail closed,
  rate limit; inspect: dedupe, post-hoc DENY reported as not enforceable,
  exfiltration quarantines, detection errors never raise.
* Quarantine (F6): status, scoped tokens and acting agent tokens revoked,
  telemetry tokens kept.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.abf import firewall as F  # noqa: E402
from src.abf import rules as R  # noqa: E402
from src.zaf import approval_service as appr  # noqa: E402
from src.zaf import enforcement  # noqa: E402
from src.zaf import governance_service as gov  # noqa: E402
from src.zaf import policy_engine as pe  # noqa: E402
from src.zaf import wiring  # noqa: E402

NOW = datetime(2026, 11, 21, 12, 0, 0, tzinfo=timezone.utc)
AGENT = {"id": 7, "tenant_id": 1, "identity": "agent://acme/coder", "status": "RUNNING"}


class Events:
    def __init__(self):
        self.events = []

    def append_event(self, event):
        self.events.append(event)
        return dict(event, inserted=True)


# --------------------------------------------------------------------------- #
# Pure PDP
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("status,decision", [
    ("QUARANTINED", pe.QUARANTINE), ("TERMINATED", pe.DENY), ("UNKNOWN", pe.DENY),
    ("RUNNING", pe.ALLOW)])
def test_pdp_agent_status(status, decision):
    rules = [{"action": "x.*", "decision": "ALLOW"}]
    assert pe.evaluate("x.y", rules=rules, context={"agent_status": status}).decision == decision


def test_pdp_explicit_deny_still_wins_over_quarantine():
    rules = [{"action": "x.*", "decision": "DENY"}]
    d = pe.evaluate("x.y", rules=rules, context={"agent_status": "QUARANTINED"})
    assert d.decision == pe.DENY and d.reason == "explicit deny rule matched"


# --------------------------------------------------------------------------- #
# governance_service.decide
# --------------------------------------------------------------------------- #
@pytest.fixture
def pdp_store(monkeypatch):
    store = {"rules": [], "perms": [], "status": "RUNNING", "decisions": [], "fail": False}

    def maybe_fail(v):
        if store["fail"]:
            raise RuntimeError("db down")
        return v

    monkeypatch.setattr(gov.repo, "effective_rules", lambda t: maybe_fail(list(store["rules"])))
    monkeypatch.setattr(gov.repo, "agent_permissions", lambda t, a: maybe_fail(store["perms"]))
    monkeypatch.setattr(gov.repo, "agent_status", lambda t, a: maybe_fail(store["status"]))

    def record(*a, **kw):
        if store["fail"]:
            raise RuntimeError("db down")
        store["decisions"].append(kw)
        return 1

    monkeypatch.setattr(gov.repo, "record_decision", record)
    monkeypatch.delenv("ZAF_PLATFORM_BASELINE", raising=False)
    return store


def test_decide_baseline_keeps_lifecycle_allowed(pdp_store):
    d = gov.decide(1, "agent.transition.STARTING", agent_db_id=7, events_repo=Events())
    assert d["decision"] == pe.ALLOW and d["baseline_version"]


def test_decide_strict_mode_without_baseline(pdp_store, monkeypatch):
    monkeypatch.setenv("ZAF_PLATFORM_BASELINE", "off")
    d = gov.decide(1, "agent.transition.STARTING", agent_db_id=7, events_repo=Events())
    assert d["decision"] == pe.DENY and d["baseline_version"] is None


def test_decide_quarantined_agent_and_caller_cannot_spoof_status(pdp_store):
    pdp_store["status"] = "QUARANTINED"
    d = gov.decide(1, "agent.transition.STARTING", agent_db_id=7,
                   context={"agent_status": "RUNNING"}, events_repo=Events())
    assert d["decision"] == pe.QUARANTINE


def test_decide_tenant_approval_rule_beats_baseline_allow(pdp_store):
    pdp_store["rules"] = [{"action": "agent.transition.RUNNING", "decision": "REQUIRE_APPROVAL"}]
    assert gov.decide(1, "agent.transition.RUNNING", agent_db_id=7,
                      events_repo=Events())["decision"] == pe.REQUIRE_APPROVAL


def test_decide_abf_risk_escalation(pdp_store):
    assert gov.decide(1, "abf.shell.exec", agent_db_id=7, context={"risk_level": "critical"},
                      events_repo=Events())["decision"] == pe.DENY
    assert gov.decide(1, "abf.shell.exec", agent_db_id=7, context={"risk_level": "high"},
                      events_repo=Events())["decision"] == pe.REQUIRE_APPROVAL
    assert gov.decide(1, "abf.shell.exec", agent_db_id=7, context={"risk_level": "low"},
                      events_repo=Events())["decision"] == pe.ALLOW


def test_decide_fails_closed_when_store_down(pdp_store):
    pdp_store["fail"] = True
    d = gov.decide(1, "agent.transition.STARTING", agent_db_id=7, events_repo=Events())
    assert d["decision"] == pe.DENY and d["service_available"] is False


def test_unauditable_allow_is_not_returned(pdp_store):
    class Broken:
        def append_event(self, e):
            raise RuntimeError("audit down")
    with pytest.raises(RuntimeError):
        gov.decide(1, "agent.transition.STARTING", agent_db_id=7, events_repo=Broken())
    # ... but a deny still stands when the audit store is down.
    pdp_store["status"] = "QUARANTINED"
    assert gov.decide(1, "x", agent_db_id=7, events_repo=Broken())["decision"] == pe.QUARANTINE


# --------------------------------------------------------------------------- #
# Approvals (F4)
# --------------------------------------------------------------------------- #
class ApprovalDb:
    """Evaluates the consume statement's binding semantics from its parameters."""

    def __init__(self):
        self.rows = []
        self.sql = []

    def execute_query(self, sql, params=None, fetch_one=False, fetch_all=False):
        flat = " ".join(sql.split())
        self.sql.append(flat)
        if flat.startswith("UPDATE approval_requests SET consumed_at"):
            consumer, tenant, phash, agent, session = params
            for r in self.rows:
                if (r["tenant"] == tenant and r["phash"] == phash and r["status"] == "approved"
                        and r["consumed"] is None and r["expires"] > datetime.now(timezone.utc)
                        and r["agent"] == agent and (r["session"] is None or r["session"] == session)):
                    r["consumed"] = consumer
                    return (r["id"],)
            return None
        raise AssertionError(flat)


@pytest.fixture
def approvals_db(monkeypatch):
    db = ApprovalDb()
    monkeypatch.setattr(appr, "_get_db", lambda: db)
    return db


def _approved(db, params, *, agent="agent://acme/coder", session=None, expires_in=600, rid=1):
    db.rows.append({"id": rid, "tenant": 1, "phash": gov.params_hash("db.drop", params),
                    "status": "approved", "consumed": None, "agent": agent, "session": session,
                    "expires": datetime.now(timezone.utc) + timedelta(seconds=expires_in)})


def test_approval_is_single_use(approvals_db):
    _approved(approvals_db, {"t": "x"})
    kw = dict(agent_identity="agent://acme/coder", events_repo=Events())
    assert appr.consume_authorization(1, "db.drop", {"t": "x"}, **kw) == 1
    assert appr.consume_authorization(1, "db.drop", {"t": "x"}, **kw) is None  # replay
    sql = approvals_db.sql[0]
    assert "FOR UPDATE SKIP LOCKED" in sql and "consumed_at IS NULL" in sql
    assert "expires_at > CURRENT_TIMESTAMP" in sql


def test_approval_bound_to_agent_session_params_and_expiry(approvals_db):
    ev = Events()
    _approved(approvals_db, {"t": "x"}, session="s-1")
    assert appr.consume_authorization(1, "db.drop", {"t": "x"},
                                      agent_identity="agent://acme/other", events_repo=ev) is None
    assert appr.consume_authorization(1, "db.drop", {"t": "x"}, agent_identity="agent://acme/coder",
                                      session_id="s-2", events_repo=ev) is None
    assert appr.consume_authorization(1, "db.drop", {"t": "y"}, agent_identity="agent://acme/coder",
                                      session_id="s-1", events_repo=ev) is None
    assert appr.consume_authorization(2, "db.drop", {"t": "x"}, agent_identity="agent://acme/coder",
                                      session_id="s-1", events_repo=ev) is None
    _approved(approvals_db, {"t": "z"}, expires_in=-5, rid=2)
    assert appr.consume_authorization(1, "db.drop", {"t": "z"}, agent_identity="agent://acme/coder",
                                      events_repo=ev) is None
    assert appr.consume_authorization(1, "db.drop", {"t": "x"}, agent_identity="agent://acme/coder",
                                      session_id="s-1", events_repo=ev) == 1
    assert [e["event_type"] for e in ev.events] == ["approval.consumed"]


def test_is_authorized_and_decide_refuse_expired_or_consumed():
    import inspect
    src = inspect.getsource(appr.is_authorized)
    assert "consumed_at IS NULL" in src and "expires_at > CURRENT_TIMESTAMP" in src
    assert "expires_at > CURRENT_TIMESTAMP" in inspect.getsource(appr._decide)


# --------------------------------------------------------------------------- #
# Seams
# --------------------------------------------------------------------------- #
def test_enforcer_consumes_approval_once():
    consumed = iter([42, None])
    fns = enforcement.build_enforcers(
        pdp=lambda *a, **k: {"decision": pe.REQUIRE_APPROVAL, "reason": "approval"},
        audit=lambda *a, **k: None,
        authenticated_identity=lambda ctx: ("agent://acme/coder", 7),
        consume_approval=lambda *a, **k: next(consumed))
    ctx = {"tenant_id": 1, "agent_id": "7", "operation": "deploy", "payload_keys": []}
    fns["exec"](ctx)
    with pytest.raises(enforcement.EnforcementError):
        fns["exec"](ctx)


@pytest.mark.parametrize("frm,to,gated", [
    ("READY", "STARTING", True), ("STARTING", "RUNNING", True), ("REGISTERED", "INSTALLING", True),
    ("RUNNING", "QUARANTINED", False), ("RUNNING", "STOPPING", False),
    ("STOPPING", "STOPPED", False), ("RUNNING", "TERMINATED", False),
    ("RUNNING", "UNHEALTHY", False), ("UNHEALTHY", "RUNNING", False),
    ("QUARANTINED", "READY", False), ("CONFIGURING", "READY", True),
])
def test_transition_gating(frm, to, gated):
    assert wiring.is_gated_transition(frm, to) is gated


def test_live_pre_transition_denies_gated_and_never_blocks_containment():
    calls = []

    def deny(tenant, action, **kw):
        calls.append((action, kw.get("agent_db_id"), kw.get("agent_identity")))
        return {"decision": pe.DENY, "reason": "tenant rule"}

    fn = wiring.build_live_pre_transition(pdp=deny, events_repo=Events())
    base = {"tenant_id": 1, "agent_id": 7, "identity": "agent://acme/coder"}
    with pytest.raises(enforcement.EnforcementError):
        fn({**base, "from": "READY", "to": "STARTING"})
    assert calls == [("agent.transition.STARTING", 7, "agent://acme/coder")]
    fn({**base, "from": "RUNNING", "to": "QUARANTINED"})  # no raise, PDP not consulted
    assert len(calls) == 1


def test_live_exec_loads_identity_and_denies_unknown_agent():
    seen = []
    fn = wiring.build_live_exec(
        pdp=lambda t, a, **kw: seen.append(kw) or {"decision": pe.ALLOW},
        get_agent=lambda t, a: AGENT if a == 7 else None, events_repo=Events())
    fn({"tenant_id": 1, "agent_id": 7, "operation": "prompt", "payload_keys": []})
    assert seen[0]["agent_identity"] == AGENT["identity"] and seen[0]["agent_db_id"] == 7
    with pytest.raises(enforcement.EnforcementError):
        fn({"tenant_id": 1, "agent_id": 99, "operation": "prompt", "payload_keys": []})


# --------------------------------------------------------------------------- #
# Firewall
# --------------------------------------------------------------------------- #
class FakeApprovals:
    def __init__(self):
        self.rows = []

    def request(self, tenant, action, *, params, agent_identity, session_id=None, **kw):
        row = {"id": len(self.rows) + 1, "status": "pending", "action": action,
               "phash": gov.params_hash(action, params), "agent": agent_identity,
               "session": session_id, "consumed": False}
        self.rows.append(row)
        return dict(row)

    def approve(self, rid):
        self.rows[rid - 1]["status"] = "approved"

    def consume(self, tenant, action, params, *, agent_identity, session_id=None, consumer=""):
        for r in self.rows:
            if (r["status"] == "approved" and not r["consumed"] and r["action"] == action
                    and r["phash"] == gov.params_hash(action, params)
                    and r["agent"] == agent_identity
                    and (r["session"] is None or r["session"] == session_id)):
                r["consumed"] = True
                return r["id"]
        return None


@pytest.fixture
def fw_env():
    env = {"alerts": [], "quarantined": [], "revoked": [], "decide": [], "events": Events(),
           "approvals": FakeApprovals(), "pdp": pe.ALLOW, "pdp_fail": False, "recent": []}

    def decide(tenant, action, **kw):
        env["decide"].append((action, kw))
        if env["pdp_fail"]:
            raise RuntimeError("pdp down")
        ctx = kw.get("context") or {}
        verdict = env["pdp"]
        if ctx.get("risk_level") == "critical":
            verdict = pe.DENY
        elif ctx.get("risk_level") == "high" and verdict == pe.ALLOW:
            verdict = pe.REQUIRE_APPROVAL
        return {"decision": verdict, "reason": "fake"}

    keys = set()

    def record_alert(tenant, identity, agent_db_id, hit, **kw):
        if hit.dedupe_key and hit.dedupe_key in keys:
            return None
        if hit.dedupe_key:
            keys.add(hit.dedupe_key)
        env["alerts"].append(hit)
        return len(env["alerts"])

    fw = F.Firewall(
        decide=decide, consume_approval=env["approvals"].consume,
        request_approval=env["approvals"].request,
        get_agent=lambda t, a: AGENT if (t, a) == (1, 7) else None,
        customisation=lambda t, a: ({}, []), record_alert=record_alert,
        set_alert_enforcement=lambda t, aid, status: env.setdefault("status", []).append(status),
        list_baselines=lambda t, a: [], recent_events=lambda t, i, since: env["recent"],
        quarantine=lambda t, a, reason: env["quarantined"].append((t, a, reason)),
        revoke_permissions=lambda t, a: env["revoked"].append((t, a)),
        events_repo=env["events"], clock=lambda: NOW)
    env["fw"] = fw
    return env


def _req(**kw):
    base = dict(tenant_id=1, agent_db_id=7, category="SHELL", action="exec",
                command="ls -la", session_id="s-1")
    base.update(kw)
    return F.GuardRequest(**base)


def test_guard_allows_benign_action_through_pdp(fw_env):
    res = fw_env["fw"].guard(_req())
    assert res.allowed and res.decision == pe.ALLOW and res.status_code == 200
    action, kw = fw_env["decide"][0]
    assert action == "abf.shell.exec" and kw["agent_identity"] == AGENT["identity"]
    assert any(e["event_type"] == "abf.guard" for e in fw_env["events"].events)


def test_guard_unknown_or_cross_tenant_agent(fw_env):
    assert fw_env["fw"].guard(_req(tenant_id=2)).status_code == 404
    assert fw_env["decide"] == []


def test_guard_critical_command_denied_and_quarantined(fw_env):
    res = fw_env["fw"].guard(_req(command="rm -rf /"))
    assert res.decision == pe.DENY and not res.allowed and res.status_code == 403
    assert fw_env["quarantined"] == [(1, 7, "abf:abf.fs.recursive_delete_system_path")]
    assert res.enforcement == [R.QUARANTINE]


def test_abf_floor_tightens_permissive_pdp(fw_env):
    # Even if a tenant policy would ALLOW, a DENY-requesting rule wins.
    fw_env["fw"]._decide = lambda t, a, **kw: {"decision": pe.ALLOW, "reason": "tenant allow"}
    res = fw_env["fw"].guard(_req(category="API", command="GET agent://other/x"))
    assert res.decision == pe.DENY and res.pdp_decision == pe.ALLOW
    assert "ABF rule floor" in res.reason


def test_abf_never_loosens_pdp_deny(fw_env):
    fw_env["pdp"] = pe.QUARANTINE  # e.g. agent quarantined
    res = fw_env["fw"].guard(_req())
    assert res.decision == pe.QUARANTINE and not res.allowed


def test_guard_approval_flow_single_use_and_session_bound(fw_env):
    fw = fw_env["fw"]
    req = _req(command="docker run --privileged alpine")
    first = fw.guard(req)
    assert first.decision == pe.REQUIRE_APPROVAL and first.status_code == 202
    assert first.approval["status"] == "pending" and not first.allowed
    fw_env["approvals"].approve(first.approval["id"])
    # Other session cannot use it.
    assert not fw.guard(_req(command=req.command, session_id="s-2")).allowed
    # Modified command cannot use it.
    assert not fw.guard(_req(command="docker run --privileged alpine sh", session_id="s-1")).allowed
    ok = fw.guard(req)
    assert ok.allowed and ok.approval_consumed == first.approval["id"]
    replay = fw.guard(req)
    assert not replay.allowed and replay.status_code == 202


def test_guard_fails_closed_when_pdp_unavailable(fw_env):
    fw_env["pdp_fail"] = True
    res = fw_env["fw"].guard(_req())
    assert res.decision == pe.DENY and "fail closed" in res.reason


def test_rate_limit_cooldown(fw_env):
    fw = fw_env["fw"]
    fw.cooldowns.set((1, 7), 60)
    res = fw.guard(_req())
    assert res.status_code == 429 and not res.allowed and fw_env["decide"] == []


def _ev(i, cat, seconds_ago=1, **kw):
    return {"event_id": f"rt-7-{i}", "category": cat, "normalized_action": kw.pop("action", "x"),
            "occurred_at": (NOW - timedelta(seconds=seconds_ago)).isoformat(), **kw}


def test_inspect_records_alert_once_and_reports_post_hoc_limits(fw_env):
    fw = fw_env["fw"]
    ev = _ev(1, "API", action="get", action_payload=None)
    ev["action"] = {"metadata": {"url": "agent://other/secret"}}
    fw_env["recent"] = [ev]
    out = fw.inspect(1, 7, AGENT["identity"], [ev])
    assert out["alerts"] == 1 and fw_env["status"] == ["not_enforceable_post_hoc"]
    again = fw.inspect(1, 7, AGENT["identity"], [ev])  # replayed batch
    assert again["alerts"] == 0


def test_inspect_exfiltration_quarantines(fw_env):
    evs = [
        dict(_ev(1, "FILESYSTEM", 100), action={"metadata": {"command": "cat ~/.aws/credentials"}}),
        dict(_ev(2, "NETWORK", 50), resource="paste.example",
             action={"metadata": {"bytes_out": 5_000_000}}),
    ]
    fw_env["recent"] = evs
    out = fw_env["fw"].inspect(1, 7, AGENT["identity"], evs[1:])
    assert R.QUARANTINE in out["enforcement"]
    assert fw_env["quarantined"][0][2] == "abf:abf.exfiltration.sequence"


def test_inspect_burst_rate_limits(fw_env):
    evs = [_ev(i, "MCP", action=f"t{i}") for i in range(60)]
    fw_env["recent"] = evs
    out = fw_env["fw"].inspect(1, 7, AGENT["identity"], evs[-1:])
    assert R.RATE_LIMIT in out["enforcement"]
    assert fw_env["fw"].cooldowns.remaining((1, 7)) > 0


def test_inspect_never_raises(fw_env):
    fw = fw_env["fw"]
    fw._customisation = lambda t, a: (_ for _ in ()).throw(RuntimeError("down"))
    fw._recent = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down"))
    fw._record_alert = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down"))
    assert fw.inspect(1, 7, AGENT["identity"], [_ev(1, "SHELL")])["alerts"] == 0


# --------------------------------------------------------------------------- #
# Quarantine (F6)
# --------------------------------------------------------------------------- #
def test_quarantine_agent_revokes_acting_credentials(monkeypatch):
    from src.aro import agent_repository
    from src.obs import ingest_tokens
    from src.zaf import credential_vault

    calls = {}
    monkeypatch.setattr(agent_repository, "get_agent", lambda t, a: dict(AGENT))
    monkeypatch.setattr(credential_vault, "revoke_agent_scoped_tokens",
                        lambda t, ident: calls.setdefault("scoped", (t, ident)) and 2)
    monkeypatch.setattr(ingest_tokens, "revoke_acting_scopes_for_agent",
                        lambda t, a: calls.setdefault("tokens", (t, a)) and 1)

    class Lifecycle:
        def quarantine(self, tenant, agent_id, reason):
            calls["lifecycle"] = (tenant, agent_id, reason)
            return dict(AGENT, status="QUARANTINED")

    out = wiring.quarantine_agent(1, 7, reason="manual: test", lifecycle_svc=Lifecycle(),
                                  events_repo=Events())
    assert out["status"] == "QUARANTINED"
    assert calls["lifecycle"] == (1, 7, "manual: test")
    assert calls["scoped"] == (1, AGENT["identity"]) and calls["tokens"] == (1, 7)
    assert out["revoked"]["credentials"] == 0  # base credentials untouched by default


def test_acting_scope_revocation_keeps_telemetry_tokens():
    from src.obs import ingest_tokens as it
    import inspect
    src = inspect.getsource(it.revoke_acting_scopes_for_agent)
    assert "string_to_array(scope, ' ') && %s::text[]" in src
    assert it.SCOPE_TELEMETRY not in it.ACTING_SCOPES
    assert set(it.ACTING_SCOPES) == {it.SCOPE_MCP, it.SCOPE_FIREWALL}


def test_token_scopes_validated():
    from src.obs import ingest_tokens as it
    assert it.normalize_scopes(None) == "telemetry:ingest"
    assert it.normalize_scopes(["mcp:invoke", "telemetry:ingest", "mcp:invoke"]) == \
        "telemetry:ingest mcp:invoke"
    with pytest.raises(ValueError):
        it.normalize_scopes(["admin:*"])


# --------------------------------------------------------------------------- #
# Telemetry ingestion -> detection hook
# --------------------------------------------------------------------------- #
def _ingest_svc(inspector, sealer=None):
    from src.obs.telemetry_ingest import TelemetryIngestService
    from src.zaf.mcp_gateway import RateLimiter
    binding = {"token_id": 3, "tenant_id": 1, "agent_db_id": 7,
               "agent_identity": AGENT["identity"], "agent_status": "RUNNING"}
    store = {}

    class Mem:
        def append_event(self, event):
            key = event["event_id"]
            inserted = key not in store
            store.setdefault(key, event)
            return dict(event, inserted=inserted)

    return TelemetryIngestService(
        verify_token=lambda tok: dict(binding), touch_token=lambda i: None,
        events_repo=Mem(), task_owner=lambda t, r: None, rate_limiter=RateLimiter(),
        clock=lambda: NOW, inspector=inspector, sealer=sealer)


def test_ingest_runs_detection_on_accepted_events_only():
    seen, sealed = [], []
    svc = _ingest_svc(lambda t, a, i, evs: seen.append((t, a, i, [e["event_id"] for e in evs])),
                      sealer=sealed.append)
    body = {"events": [{"category": "SHELL", "action": "exec", "event_id": "a",
                        "metadata": {"command": "rm -rf /"}},
                       {"category": "SECURITY", "action": "x"}]}
    res = svc.ingest("aig_x", body)
    assert res.status_code == 200 and res.payload["accepted"] == 1
    assert seen == [(1, 7, AGENT["identity"], ["rt-7-a"])] and sealed == [1]
    assert "detection" not in res.payload and "alerts" not in str(res.payload)
    svc.ingest("aig_x", {"events": [{"category": "SHELL", "action": "exec", "event_id": "a"}]})
    assert len(seen) == 1  # duplicate-only batch triggers no detection


def test_ingest_survives_detection_failure():
    def boom(*a):
        raise RuntimeError("detector down")
    svc = _ingest_svc(boom, sealer=boom)
    res = svc.ingest("aig_x", {"events": [{"category": "SHELL", "action": "exec"}]})
    assert res.status_code == 200 and res.payload["accepted"] == 1
