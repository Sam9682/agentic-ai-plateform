#!/usr/bin/env python3
"""Property + unit tests for the unified event backbone (Task 2).

Feature: ARO/ZAF unified event + audit model (SRS §6, §9).

Validates:
* redaction: no credential-shaped substring survives into a built event's
  action payload (secret keys masked; token/PEM/long-hex values masked).
* schema stability: build_event always returns the full canonical field set,
  with enums normalized and risk clamped to 0..100 regardless of input.
* correlation defaults: a standalone event correlates to its own id.
* repository: append + tenant-scoped list via a stub db_manager (no live DB).

Run directly:
    python3 tests/test_aro_events.py
Or via pytest:
    pytest tests/test_aro_events.py
"""
import os
import sys

from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.aro import event_service as es  # noqa: E402

_CANONICAL_FIELDS = {
    "event_id", "tenant_id", "agent_id", "execution_id", "event_type",
    "source", "action", "decision", "risk_score", "severity",
    "correlation_id", "occurred_at",
}

_SECRET = "AKIA1234567890ABCDEF1234567890ABCDEF1234"  # long base64-ish blob


def test_schema_is_stable():
    ev = es.build_event(1, "agent.started", "lifecycle")
    assert set(ev.keys()) == _CANONICAL_FIELDS
    assert ev["decision"] is None
    assert ev["severity"] == "INFO"
    assert ev["risk_score"] == 0
    # standalone event correlates to itself
    assert ev["correlation_id"] == ev["event_id"]


def test_secret_key_is_redacted():
    ev = es.build_event(
        1, "mcp.tool.invocation", "mcp-gateway",
        action={"tool": "x", "password": "hunter2", "api_key": "abc"},
    )
    assert ev["action"]["password"] == es._REDACTED
    assert ev["action"]["api_key"] == es._REDACTED
    assert ev["action"]["tool"] == "x"


def test_secret_value_is_redacted_under_innocuous_key():
    ev = es.build_event(
        1, "x", "s",
        action={"note": "token is " + _SECRET, "blob": _SECRET},
    )
    assert es._REDACTED in ev["action"]["note"] or ev["action"]["note"] == es._REDACTED
    assert ev["action"]["blob"] == es._REDACTED


def test_nested_redaction():
    ev = es.build_event(
        1, "x", "s",
        action={"outer": {"secret": "s3cr3t", "ok": "fine"}, "list": [{"token": "t"}]},
    )
    assert ev["action"]["outer"]["secret"] == es._REDACTED
    assert ev["action"]["outer"]["ok"] == "fine"
    assert ev["action"]["list"][0]["token"] == es._REDACTED


def test_pem_private_key_redacted():
    pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIabc\n-----END RSA PRIVATE KEY-----"
    ev = es.build_event(1, "x", "s", action={"material": pem})
    assert ev["action"]["material"] == es._REDACTED


def test_risk_clamped_and_enums_normalized():
    assert es.build_event(1, "x", "s", risk_score=999)["risk_score"] == 100
    assert es.build_event(1, "x", "s", risk_score=-5)["risk_score"] == 0
    assert es.build_event(1, "x", "s", risk_score="nope")["risk_score"] == 0
    assert es.build_event(1, "x", "s", severity="weird")["severity"] == "INFO"
    assert es.build_event(1, "x", "s", severity="high")["severity"] == "HIGH"
    assert es.build_event(1, "x", "s", decision="bogus")["decision"] is None
    assert es.build_event(1, "x", "s", decision="deny")["decision"] == "DENY"


# Property: a secret-named key never leaks its value into the built action.
_secret_keys = st.sampled_from(["password", "secret", "api_key", "token", "authorization"])


@given(key=_secret_keys, val=st.text(min_size=1, max_size=40))
@settings(max_examples=100)
def test_property_secret_key_never_leaks(key, val):
    ev = es.build_event(1, "x", "s", action={key: val})
    assert ev["action"][key] == es._REDACTED


@given(
    tenant=st.integers(1, 1000),
    etype=st.text(min_size=1, max_size=20),
    src=st.text(min_size=1, max_size=20),
    risk=st.integers(-100, 500),
)
@settings(max_examples=100)
def test_property_schema_always_full(tenant, etype, src, risk):
    ev = es.build_event(tenant, etype, src, risk_score=risk)
    assert set(ev.keys()) == _CANONICAL_FIELDS
    assert 0 <= ev["risk_score"] <= 100
    assert ev["severity"] in es.VALID_SEVERITIES


# --------------------------------------------------------------------------- #
# Repository against a stub db_manager
# --------------------------------------------------------------------------- #
class StubDb:
    """Captures INSERTs and serves tenant-scoped SELECTs from memory."""

    def __init__(self):
        self.rows = []
        self._next_id = 1

    def execute_query(self, sql, params=None, fetch_one=False, fetch_all=False):
        s = sql.strip().upper()
        if s.startswith("INSERT INTO AGENT_EVENTS"):
            rid = self._next_id
            self._next_id += 1
            # columns order matches the INSERT in events_repository
            self.rows.append({"id": rid, "params": params})
            return (rid,) if fetch_one else rid
        if s.startswith("SELECT ID, EVENT_ID"):
            # list_events: first param is tenant_id, last is limit
            tenant_id = params[0]
            out = []
            for r in self.rows:
                p = r["params"]
                # p: event_id, tenant_id, agent_id, execution_id, type, source,
                #    action, decision, risk, severity, correlation, occurred_at
                if p[1] != tenant_id:
                    continue
                out.append((
                    r["id"], p[0], p[1], p[2], p[3], p[4], p[5], p[6],
                    p[7], p[8], p[9], p[10], None,
                ))
            return out if fetch_all else (out[0] if out else None)
        if s.startswith("SELECT ID FROM AGENT_EVENTS"):
            return None
        return None


def test_repository_append_and_tenant_scoped_list(monkeypatch):
    from src.aro import events_repository as repo

    stub = StubDb()
    monkeypatch.setattr(repo, "_get_db", lambda: stub)

    es.emit(repo, 1, "agent.started", "lifecycle", agent_id="a1")
    es.emit(repo, 1, "task.received", "worker", agent_id="a1")
    es.emit(repo, 2, "agent.started", "lifecycle", agent_id="b1")

    t1 = repo.list_events(1)
    t2 = repo.list_events(2)
    assert len(t1) == 2
    assert len(t2) == 1
    assert all(e["tenant_id"] == 1 for e in t1)
    assert t2[0]["agent_id"] == "b1"


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
