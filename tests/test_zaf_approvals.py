#!/usr/bin/env python3
"""Tests for the ZAF human approval workflow (Task 12).

Feature: ZAF approvals bound to exact action+params (SRS §4.5).

Validates:
* params_hash is stable for identical action+params and differs when params
  change (re-authorization required).
* request_approval creates a pending record; approve/reject set terminal status
  and emit events.
* is_authorized is True only for the exact approved action+params; a modified
  param is NOT authorized by a prior approval.
* a duplicate pending request for the same hash is coalesced.

Run directly:
    python3 tests/test_zaf_approvals.py
Or via pytest:
    pytest tests/test_zaf_approvals.py
"""
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.zaf import approval_service as appr  # noqa: E402
from src.zaf import governance_service as gov  # noqa: E402


class CapturingEvents:
    def __init__(self):
        self.events = []

    def append_event(self, event):
        self.events.append(event)
        return dict(event, id=len(self.events))


class StubDb:
    """In-memory approval store matching approval_service's SQL shapes."""

    def __init__(self):
        self.rows = {}
        self._id = 1

    def execute_query(self, sql, params=None, fetch_one=False, fetch_all=False):
        s = " ".join(sql.split()).upper()
        if s.startswith("SELECT ID FROM APPROVAL_REQUESTS WHERE TENANT_ID = %S AND PARAMS_HASH"):
            tenant_id, phash = params
            for r in self.rows.values():
                if r["tenant_id"] == tenant_id and r["params_hash"] == phash and r["status"] == "pending":
                    return (r["id"],)
            return None
        if s.startswith("INSERT INTO APPROVAL_REQUESTS"):
            (tenant_id, agent_identity, action, resource, params_json, phash,
             risk, policy, expires) = params
            rid = self._id
            self._id += 1
            import json as _j
            self.rows[rid] = dict(
                id=rid, tenant_id=tenant_id, agent_identity=agent_identity,
                action=action, resource=resource, params=_j.loads(params_json),
                params_hash=phash, risk_explanation=risk, triggering_policy=None,
                status="pending", approver_user_id=None, decided_at=None, created_at=None,
            )
            return (rid,)
        if s.startswith("SELECT ID, AGENT_IDENTITY, ACTION, RESOURCE, PARAMS, PARAMS_HASH"):
            tenant_id, approval_id = params
            r = self.rows.get(approval_id)
            if not r or r["tenant_id"] != tenant_id:
                return None
            return (r["id"], r["agent_identity"], r["action"], r["resource"], r["params"],
                    r["params_hash"], r["risk_explanation"], r["triggering_policy"],
                    r["status"], r["approver_user_id"], r["decided_at"], r["created_at"])
        if s.startswith("SELECT ID FROM APPROVAL_REQUESTS WHERE TENANT_ID = %S AND STATUS = 'PENDING'"):
            tenant_id, _limit = params
            return [(r["id"],) for r in self.rows.values()
                    if r["tenant_id"] == tenant_id and r["status"] == "pending"]
        if s.startswith("UPDATE APPROVAL_REQUESTS SET STATUS"):
            status, approver, tenant_id, approval_id = params
            r = self.rows.get(approval_id)
            if r and r["tenant_id"] == tenant_id and r["status"] == "pending":
                r["status"] = status
                r["approver_user_id"] = approver
                return 1
            return 0
        if s.startswith("SELECT 1 FROM APPROVAL_REQUESTS"):
            tenant_id, phash = params
            for r in self.rows.values():
                if r["tenant_id"] == tenant_id and r["params_hash"] == phash and r["status"] == "approved":
                    return (1,)
            return None
        return None


def _wire(monkeypatch):
    stub = StubDb()
    monkeypatch.setattr(appr, "_get_db", lambda: stub)
    return stub


def test_params_hash_binding():
    h1 = gov.params_hash("openstack.server.delete", {"id": "server-123"})
    h2 = gov.params_hash("openstack.server.delete", {"id": "server-123"})
    h3 = gov.params_hash("openstack.server.delete", {"id": "server-999"})
    assert h1 == h2
    assert h1 != h3


def test_request_and_approve_unblocks(monkeypatch):
    _wire(monkeypatch)
    events = CapturingEvents()
    params = {"id": "server-123"}
    a = appr.request_approval(1, "openstack.server.delete", params=params,
                              agent_identity="agent://default/a1", events_repo=events)
    assert a["status"] == "pending"
    assert not appr.is_authorized(1, "openstack.server.delete", params)
    appr.approve(1, a["id"], approver_user_id=7, events_repo=events)
    assert appr.is_authorized(1, "openstack.server.delete", params)
    assert any(e["event_type"] == "approval.granted" for e in events.events)


def test_modified_params_require_reapproval(monkeypatch):
    _wire(monkeypatch)
    events = CapturingEvents()
    a = appr.request_approval(1, "openstack.server.delete", params={"id": "server-123"},
                              events_repo=events)
    appr.approve(1, a["id"], approver_user_id=7, events_repo=events)
    # A different parameter is NOT authorized by the prior approval.
    assert not appr.is_authorized(1, "openstack.server.delete", {"id": "server-999"})


def test_reject_does_not_authorize(monkeypatch):
    _wire(monkeypatch)
    events = CapturingEvents()
    a = appr.request_approval(1, "db.drop", params={"t": "x"}, events_repo=events)
    appr.reject(1, a["id"], approver_user_id=7, events_repo=events)
    assert not appr.is_authorized(1, "db.drop", {"t": "x"})


def test_duplicate_pending_coalesced(monkeypatch):
    stub = _wire(monkeypatch)
    events = CapturingEvents()
    a = appr.request_approval(1, "x.y", params={"p": 1}, events_repo=events)
    b = appr.request_approval(1, "x.y", params={"p": 1}, events_repo=events)
    assert a["id"] == b["id"]
    assert len([r for r in stub.rows.values() if r["status"] == "pending"]) == 1


def test_tenant_scoped(monkeypatch):
    _wire(monkeypatch)
    events = CapturingEvents()
    a = appr.request_approval(1, "x.y", params={"p": 1}, events_repo=events)
    # tenant 2 cannot see tenant 1's approval
    assert appr.get_approval(2, a["id"]) is None


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
