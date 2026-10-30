#!/usr/bin/env python3
"""Tests for the infra proxy + OpenStack provider (Task 14).

Feature: ZAF infra proxy enforcement point (SRS §4.3, §4.4, §9; E2E §13).

Validates:
* canonical action mapping + read/mutating classification.
* mock provider determinism: list returns seeded servers; delete mutates state.
* PDP gate: list -> ALLOW executes; delete -> REQUIRE_APPROVAL blocks (202) until
  the approval authorizer returns True, then executes; DENY blocks (403).
* a scoped token is minted for an allowed call (least privilege).
* live-mutation guard: the real provider refuses a mutation without
  ZAF_LIVE_OPENSTACK=1.
* every attempt is audited independently of what an agent reports.

Run directly:
    python3 tests/test_zaf_infra_proxy.py
Or via pytest:
    pytest tests/test_zaf_infra_proxy.py
"""
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.zaf import policy_engine as pe  # noqa: E402
from src.zaf.infra_proxy import InfraProxy  # noqa: E402
from src.zaf.providers import openstack as osp  # noqa: E402


class CapturingEvents:
    def __init__(self):
        self.events = []

    def append_event(self, event):
        self.events.append(event)
        return dict(event, id=len(self.events))


# --------------------------------------------------------------------------- #
# provider + mapping
# --------------------------------------------------------------------------- #
def test_canonical_action_mapping():
    assert osp.canonical_action("server", "list") == "openstack.server.list"
    assert osp.canonical_action("server", "delete") == "openstack.server.delete"
    assert osp.canonical_action("widget", "frob") == "openstack.widget.frob"


def test_read_vs_mutating():
    assert not osp.is_mutating("openstack.server.list")
    assert osp.is_mutating("openstack.server.delete")


def test_mock_provider_deterministic():
    p = osp.MockOpenStackProvider()
    listing = p.call("server", "list", {})
    ids = {s["id"] for s in listing["servers"]}
    assert "server-123" in ids
    deleted = p.call("server", "delete", {"id": "server-123"})
    assert deleted["deleted"] is True
    assert "server-123" not in {s["id"] for s in p.call("server", "list", {})["servers"]}


# --------------------------------------------------------------------------- #
# proxy gating
# --------------------------------------------------------------------------- #
def _proxy(decision_map, *, authorizer=None, minted=None, events=None):
    events = events or CapturingEvents()
    provider = osp.MockOpenStackProvider()

    def decide(tenant_id, action, **kw):
        return {"decision": decision_map.get(action, pe.DENY), "reason": "stub", "risk_score": 0}

    def mint(tenant_id, credential_id, scope, ttl_seconds=120, agent_id=None):
        if minted is not None:
            minted.append((credential_id, scope))
        return {"token": "tok", "scope": scope}

    proxy = InfraProxy(
        provider, decide=decide, approval_authorizer=authorizer,
        token_minter=mint, events_repo=events,
    )
    return proxy, provider, events


def test_list_allowed_executes():
    proxy, _, events = _proxy({"openstack.server.list": pe.ALLOW})
    res = proxy.call(1, "server", "list", {}, agent_identity="agent://default/a1",
                     credential_id=5)
    assert res.allowed is True
    assert "servers" in res.result
    assert any(e["event_type"] == "infra.api.call" for e in events.events)


def test_delete_requires_approval_then_executes():
    minted = []
    # First: no approval -> blocked 202
    proxy, provider, _ = _proxy({"openstack.server.delete": pe.REQUIRE_APPROVAL},
                                authorizer=lambda t, a, p: False, minted=minted)
    res = proxy.call(1, "server", "delete", {"id": "server-123"},
                     agent_identity="agent://default/a1", credential_id=5)
    assert res.allowed is False and res.status_code == 202
    assert provider.call("server", "get", {"id": "server-123"})["server"] is not None  # not deleted

    # Then: approval granted -> executes + mints token
    minted2 = []
    proxy2, provider2, _ = _proxy({"openstack.server.delete": pe.REQUIRE_APPROVAL},
                                  authorizer=lambda t, a, p: True, minted=minted2)
    res2 = proxy2.call(1, "server", "delete", {"id": "server-123"},
                       agent_identity="agent://default/a1", credential_id=5)
    assert res2.allowed is True
    assert res2.result["deleted"] is True
    assert minted2  # a scoped token was minted for the allowed call


def test_deny_blocks():
    proxy, provider, _ = _proxy({"openstack.server.delete": pe.DENY})
    res = proxy.call(1, "server", "delete", {"id": "server-123"}, credential_id=5)
    assert res.allowed is False and res.status_code == 403


def test_independent_authorization_of_mutation():
    # Even if the "agent" context claims a benign action, the proxy authorizes
    # the real action (delete) it was asked to perform.
    proxy, _, events = _proxy({"openstack.server.delete": pe.DENY},
                              )
    res = proxy.call(1, "server", "delete", {"id": "server-123"},
                     context={"agent_reported": "listed servers"}, credential_id=5)
    assert res.decision == pe.DENY  # governed by the true action, not the claim


# --------------------------------------------------------------------------- #
# live-mutation guard on the real provider
# --------------------------------------------------------------------------- #
def test_live_mutation_refused_without_env(monkeypatch):
    monkeypatch.delenv("ZAF_LIVE_OPENSTACK", raising=False)
    provider = osp.OpenStackProvider(auth={"token": "x"}, http=lambda *a, **k: (200, {}))
    try:
        provider.call("server", "delete", {"id": "server-1"})
        assert False, "expected PermissionError"
    except PermissionError:
        pass


def test_live_read_allowed_without_env(monkeypatch):
    monkeypatch.delenv("ZAF_LIVE_OPENSTACK", raising=False)
    provider = osp.OpenStackProvider(
        auth={"token": "x"},
        http=lambda service, verb, params, auth: (200, {"servers": []}),
    )
    out = provider.call("server", "list", {})
    assert out["status"] == 200


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
