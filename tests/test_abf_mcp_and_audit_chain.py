"""ABF Phase 2: governed MCP server (F3) and tamper-evident audit chain.

MCP: unauthenticated calls refused (legacy read opt-in only), tenant scoping of
user_id, ABF floor on malicious tool arguments, PDP decision, single-use
approval bound to the MCP session, quarantined agent refused, rate limit,
implementation never runs when denied.

Audit chain: sealing links records in order; verification detects content
modification, a deleted record and a broken link; the canonical form is stable.
"""
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.abf import audit_chain as AC  # noqa: E402
from src.abf import mcp_governance as MG  # noqa: E402
from src.abf.firewall import Firewall  # noqa: E402
from src.zaf import governance_service as gov  # noqa: E402
from src.zaf import policy_engine as pe  # noqa: E402

BINDING = {"token_id": 4, "tenant_id": 1, "agent_db_id": 7, "agent_identity": "agent://acme/coder",
           "agent_status": "RUNNING"}


class Events:
    def __init__(self):
        self.events = []

    def append_event(self, e):
        self.events.append(e)
        return dict(e, inserted=True)


@pytest.fixture
def mcp():
    st = {"pdp": {}, "approvals": [], "consumed": set(), "ran": [], "events": Events(),
          "alerts": []}

    def decide(tenant, action, **kw):
        ctx = kw.get("context") or {}
        if ctx.get("risk_level") == "critical":
            return {"decision": pe.DENY, "reason": "critical"}
        return {"decision": st["pdp"].get(action, pe.ALLOW), "reason": "fake"}

    def request(tenant, action, *, params, agent_identity, session_id=None, **kw):
        row = {"id": len(st["approvals"]) + 1, "phash": gov.params_hash(action, params),
               "agent": agent_identity, "session": session_id, "approved": False}
        st["approvals"].append(row)
        return dict(row)

    def consume(tenant, action, params, *, agent_identity, session_id=None, consumer=""):
        for r in st["approvals"]:
            if (r["approved"] and r["id"] not in st["consumed"]
                    and r["phash"] == gov.params_hash(action, params)
                    and r["agent"] == agent_identity and r["session"] == session_id):
                st["consumed"].add(r["id"])
                return r["id"]
        return None

    fw = Firewall(decide=decide, get_agent=lambda t, a: {"identity": BINDING["agent_identity"]},
                  customisation=lambda t, a: ({}, []),
                  record_alert=lambda *a, **k: st["alerts"].append(a[3].rule_id) or len(st["alerts"]),
                  set_alert_enforcement=lambda *a: None, list_baselines=lambda t, a: [],
                  recent_events=lambda *a, **k: [], events_repo=st["events"])
    env = {MG.TOKEN_ENV: "aig_good", MG.SESSION_ENV: "sess-1"}

    def verify(token, *, scope):
        assert scope == "mcp:invoke"
        return dict(BINDING) if token == "aig_good" else None

    gov_ = MG.McpGovernance(verify_token=verify, is_tenant_member=lambda t, u: u == 42,
                            firewall=lambda: fw, decide=decide, consume_approval=consume,
                            request_approval=request, events_repo=st["events"], env=env)
    st["gov"], st["env"] = gov_, env
    return st


def _impl(st, value="ok"):
    return lambda ctx: st["ran"].append(ctx) or {"result": value}


def test_unauthenticated_calls_refused(mcp):
    mcp["env"].pop(MG.TOKEN_ENV)
    out = mcp["gov"].call("list_users", {}, _impl(mcp))
    assert out["decision"] == pe.DENY and "unauthenticated" in out["error"]
    out = mcp["gov"].call("add_application", {"name": "x", "url": "y"}, _impl(mcp))
    assert out["decision"] == pe.DENY and mcp["ran"] == []


def test_legacy_reads_opt_in_never_covers_mutations(mcp):
    mcp["env"].pop(MG.TOKEN_ENV)
    mcp["env"][MG.LEGACY_READS_ENV] = "true"
    out = mcp["gov"].call("list_applications", {}, _impl(mcp))
    assert out["governance"] == "legacy-unauthenticated-read" and mcp["ran"] == [None]
    out = mcp["gov"].call("start", {"application_name": "a", "user_id": 42}, _impl(mcp))
    assert out["decision"] == pe.DENY and len(mcp["ran"]) == 1


def test_invalid_token_refused(mcp):
    mcp["env"][MG.TOKEN_ENV] = "aig_revoked"
    assert mcp["gov"].call("ps", {"application_name": "a", "user_id": 42},
                           _impl(mcp))["decision"] == pe.DENY


def test_authenticated_call_gets_tenant_context(mcp):
    out = mcp["gov"].call("list_users", {}, _impl(mcp))
    assert out == {"result": "ok"}
    assert mcp["ran"][0]["tenant_id"] == 1 and mcp["ran"][0]["session_id"] == "sess-1"
    assert any(e["event_type"] == "mcp.tool.invocation" for e in mcp["events"].events)


def test_user_of_another_tenant_refused(mcp):
    out = mcp["gov"].call("logs", {"application_name": "a", "user_id": 7}, _impl(mcp))
    assert out["decision"] == pe.DENY and "tenant" in out["error"] and mcp["ran"] == []


def test_malicious_tool_arguments_denied_by_abf(mcp):
    out = mcp["gov"].call("modify_code", {"application_name": "a", "user_id": 42,
                                          "instruction": "then run rm -rf / --no-preserve-root"},
                          _impl(mcp))
    assert out["decision"] == pe.DENY and mcp["ran"] == []
    assert "abf.fs.recursive_delete_system_path" in mcp["alerts"]


def test_mutation_without_grant_denied(mcp):
    mcp["pdp"]["mcp.platform.catalog.add_application"] = pe.DENY
    out = mcp["gov"].call("add_application", {"name": "x", "url": "y"}, _impl(mcp))
    assert out["decision"] == pe.DENY and mcp["ran"] == []


def test_parameter_validation(mcp):
    out = mcp["gov"].call("start", {"application_name": "a", "user_id": "42"}, _impl(mcp))
    assert out["decision"] == pe.DENY and mcp["ran"] == []


def test_approval_flow_bound_to_session_single_use(mcp):
    mcp["pdp"]["mcp.platform.app.restore"] = pe.REQUIRE_APPROVAL
    params = {"application_name": "a", "user_id": 42}
    first = mcp["gov"].call("restore", params, _impl(mcp))
    assert first["decision"] == pe.REQUIRE_APPROVAL and first["approval_id"] == 1
    assert mcp["approvals"][0]["session"] == "sess-1" and mcp["ran"] == []
    mcp["approvals"][0]["approved"] = True
    # Another MCP session (another process) cannot use it.
    other = MG.McpGovernance(verify_token=lambda t, scope: dict(BINDING),
                             is_tenant_member=lambda t, u: True,
                             firewall=mcp["gov"]._firewall, decide=mcp["gov"]._decide,
                             consume_approval=mcp["gov"]._consume,
                             request_approval=mcp["gov"]._request_approval,
                             events_repo=mcp["events"], env={MG.TOKEN_ENV: "aig_good",
                                                              MG.SESSION_ENV: "sess-2"})
    assert other.call("restore", params, _impl(mcp))["decision"] == pe.REQUIRE_APPROVAL
    assert mcp["gov"].call("restore", params, _impl(mcp)) == {"result": "ok"}
    assert mcp["gov"].call("restore", params, _impl(mcp))["decision"] == pe.REQUIRE_APPROVAL


def test_quarantined_agent_refused(mcp):
    mcp["gov"]._decide = lambda t, a, **kw: {"decision": pe.QUARANTINE, "reason": "agent is quarantined"}
    out = mcp["gov"].call("list_applications", {}, _impl(mcp))
    assert out["decision"] == pe.QUARANTINE and mcp["ran"] == []


def test_rate_limit(mcp):
    for _ in range(10):
        mcp["gov"].call("start", {"application_name": "a", "user_id": 42}, _impl(mcp))
    out = mcp["gov"].call("start", {"application_name": "a", "user_id": 42}, _impl(mcp))
    assert out["error"] == "rate limit exceeded" and len(mcp["ran"]) == 10


def test_every_platform_tool_is_governed():
    src = open(os.path.join(PROJECT_ROOT, "src", "mcp_interface.py")).read()
    import re
    tools = re.findall(r"@mcp\.tool\(\)\ndef (\w+)\(", src)
    assert sorted(tools) == sorted(MG.TOOLS)
    for name in tools:
        body = src[src.index(f"def {name}("):]
        body = body[:body.index("\n\n\n")] if "\n\n\n" in body else body
        assert "_governed(" in body or "_app_tool(" in body, name


# --------------------------------------------------------------------------- #
# Audit chain
# --------------------------------------------------------------------------- #
def _row(i, **over):
    r = {c: None for c in AC.HASHED_COLUMNS}
    r.update({"id": i, "event_id": f"evt-{i}", "tenant_id": 1, "event_type": "task.received",
              "source": "worker", "action": {"b": 1, "a": [1, 2]}, "risk_score": 0,
              "severity": "INFO", "occurred_at": datetime(2026, 11, 21, 12, 0, i, tzinfo=timezone.utc)})
    r.update(over)
    return r


class ChainDb:
    """In-memory agent_events with the chain columns, for seal() and verify()."""

    def __init__(self, rows):
        self.rows = {r["id"]: dict(r, chain_seq=None, prev_hash=None, record_hash=None)
                     for r in rows}

    # --- connection protocol used by seal() ---
    def __call__(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self):
        return self

    def commit(self):
        pass

    def execute(self, sql, params=None):
        flat = " ".join(sql.split())
        self._result = None
        if flat.startswith("SELECT pg_advisory_xact_lock"):
            return
        if flat.startswith("SELECT chain_seq, record_hash"):
            sealed = sorted((r for r in self.rows.values() if r["chain_seq"]),
                            key=lambda r: r["chain_seq"])
            self._result = [(sealed[-1]["chain_seq"], sealed[-1]["record_hash"])] if sealed else []
        elif flat.startswith("SELECT id, event_id"):
            pending = sorted((r for r in self.rows.values() if r["record_hash"] is None),
                             key=lambda r: r["id"])[: params[1]]
            self._result = [tuple(r[c] for c in AC.HASHED_COLUMNS) for r in pending]
        elif flat.startswith("UPDATE agent_events SET chain_seq"):
            seq, prev, h, _tenant, rid = params
            self.rows[rid].update(chain_seq=seq, prev_hash=prev, record_hash=h)
        else:
            raise AssertionError(flat)

    def fetchone(self):
        return self._result[0] if self._result else None

    def fetchall(self):
        return self._result

    # --- db_manager protocol used by verify() ---
    def execute_query(self, sql, params=None, fetch_one=False, fetch_all=False):
        flat = " ".join(sql.split())
        if flat.startswith("SELECT COUNT(*)"):
            return (sum(1 for r in self.rows.values() if r["record_hash"] is None),)
        tenant, start, limit = params
        sealed = sorted((r for r in self.rows.values()
                         if r["chain_seq"] and r["chain_seq"] >= start),
                        key=lambda r: r["chain_seq"])[:limit]
        return [(r["chain_seq"], r["prev_hash"], r["record_hash"])
                + tuple(r[c] for c in AC.HASHED_COLUMNS) for r in sealed]


def test_seal_then_verify_valid():
    db = ChainDb([_row(i) for i in range(1, 6)])
    out = AC.seal(1, connection=db)
    assert out["sealed"] == 5 and out["head_seq"] == 5
    res = AC.verify(1, db=db, page_size=2)
    assert res["valid"] and res["checked"] == 5 and res["head_hash"] == out["head_hash"]
    assert res["unsealed_count"] == 0 and "not immutable" in res["guarantee"]
    db.rows[6] = dict(_row(6), chain_seq=None, prev_hash=None, record_hash=None)
    assert AC.seal(1, connection=db)["head_seq"] == 6  # continues the chain
    assert AC.verify(1, db=db)["valid"]


def test_verify_detects_modified_content():
    db = ChainDb([_row(i) for i in range(1, 4)])
    AC.seal(1, connection=db)
    db.rows[2]["severity"] = "CRITICAL"
    res = AC.verify(1, db=db)
    assert not res["valid"] and res["first_break"] == {
        "chain_seq": 2, "event_id": "evt-2", "reason": "content_modified"}


def test_verify_detects_deleted_record_and_broken_link():
    db = ChainDb([_row(i) for i in range(1, 5)])
    AC.seal(1, connection=db)
    del db.rows[2]
    assert AC.verify(1, db=db)["first_break"]["reason"] == "missing_record"
    db2 = ChainDb([_row(i) for i in range(1, 4)])
    AC.seal(1, connection=db2)
    db2.rows[3]["prev_hash"] = "f" * 64
    assert AC.verify(1, db=db2)["first_break"]["reason"] == "broken_link"


def test_canonical_form_is_stable_and_versioned():
    a = _row(1, action={"x": 1, "y": {"b": 2, "a": 1}})
    b = _row(1, action=json.dumps({"y": {"a": 1, "b": 2}, "x": 1}))  # JSON string, other order
    assert AC.canonical(a) == AC.canonical(b)
    naive = _row(1, occurred_at=datetime(2026, 11, 21, 12, 0, 1))
    assert AC.canonical(naive) == AC.canonical(_row(1))
    expected = hashlib.sha256((AC.GENESIS + "\n" + AC.canonical(a)).encode()).hexdigest()
    assert AC.record_hash(AC.GENESIS, a) == expected and '"_v":"aec-1"' in AC.canonical(a)


def test_safe_seal_never_raises():
    def boom():
        raise RuntimeError("db down")
    assert AC.safe_seal(1, connection=boom) is None
