#!/usr/bin/env python3
"""End-to-end governed scenario for Kiro and SHAI (Task 19).

Feature: ARO + ZAF integrated acceptance (SRS §13 end-to-end scenario).

Implements the SRS scenario against the deterministic mock OpenStack provider
and in-memory stubs (no live cloud, no SSH, no DB) so it runs safely in CI:

  1. register a runtime (Kiro / SHAI);
  2. create an infra agent, drive it to RUNNING via the lifecycle service +
     the real runtime adapter (Kiro ACP mock endpoint / SHAI CLI fake process);
  3. grant OpenStack read-only permission;
  4. submit an inspect task; the agent (via the worker) streams output;
  5. through the infra proxy: a server.list is ALLOWED and executes;
  6. a server.delete is REQUIRE_APPROVAL and is BLOCKED (202) with no deletion;
  7. a human approves; the exact action+params is then authorized and the
     delete executes;
  8. every decision is audited in the event stream.

The scenario is parameterized over both runtimes to prove runtime independence.
Live OpenStack is intentionally NOT exercised here (ZAF_LIVE_OPENSTACK gated,
manual only) so CI never performs destructive cloud mutations.

Run directly:
    python3 tests/test_e2e_governed_scenario.py
Or via pytest:
    pytest tests/test_e2e_governed_scenario.py
"""
import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.aro import event_service as es  # noqa: E402
from src.aro import lifecycle as lc  # noqa: E402
from src.aro import agent_worker as worker  # noqa: E402
from src.aro.lifecycle_service import LifecycleService  # noqa: E402
from src.aro.adapters.base import Capability  # noqa: E402
from src.aro.adapters.kiro_acp import AcpTransport, KiroAcpAdapter  # noqa: E402
from src.aro.adapters import acp_protocol as acp  # noqa: E402
from src.aro.adapters import shai_cli  # noqa: E402
from src.zaf import policy_engine as pe  # noqa: E402
from src.zaf.infra_proxy import InfraProxy  # noqa: E402
from src.zaf.providers import openstack as osp  # noqa: E402


# --------------------------------------------------------------------------- #
# Shared in-memory infrastructure (events, agents, approvals, decisions)
# --------------------------------------------------------------------------- #
class Events:
    def __init__(self):
        self.events = []

    def append_event(self, event):
        self.events.append(event)
        return dict(event, id=len(self.events))

    def types(self):
        return [e["event_type"] for e in self.events]


class AgentRepo:
    def __init__(self):
        self.agents = {}
        self.executions = []
        self._eid = 1

    def get_agent(self, tenant_id, agent_id):
        a = self.agents.get((tenant_id, agent_id))
        return dict(a) if a else None

    def update_status(self, tenant_id, agent_id, status):
        self.agents[(tenant_id, agent_id)]["status"] = status
        return True

    def create_execution(self, tenant_id, agent_id, ref, server_id=None, container_id=None):
        self._eid += 1
        self.executions.append((tenant_id, agent_id, ref))
        return self._eid

    def seed(self, tenant_id, agent_id, identity):
        self.agents[(tenant_id, agent_id)] = dict(
            id=agent_id, tenant_id=tenant_id, identity=identity, name="infra-agent",
            runtime_id=1, status=lc.REGISTERED, configuration={}, permissions=[],
        )


class Approvals:
    """Minimal approval store keyed by params_hash for the scenario."""

    def __init__(self):
        self.pending = {}   # hash -> record
        self.approved = set()

    def request(self, action, params, phash):
        self.pending[phash] = {"action": action, "params": params, "status": "pending"}

    def approve(self, phash):
        if phash in self.pending:
            self.pending[phash]["status"] = "approved"
            self.approved.add(phash)

    def is_authorized(self, tenant_id, action, params):
        from src.zaf.governance_service import params_hash
        return params_hash(action, params) in self.approved


# --------------------------------------------------------------------------- #
# Runtime adapters (mock endpoints)
# --------------------------------------------------------------------------- #
class MockKiroTransport(AcpTransport):
    def __init__(self):
        self._outbox = []
        self._buf = acp.LineBuffer()

    def write(self, data):
        for msg in self._buf.feed(data):
            mid = msg.get("id")
            method = msg.get("method")
            if method == "initialize":
                self._outbox.append(acp.encode_message({"jsonrpc": "2.0", "id": mid, "result": {}}))
            elif method == "session/new":
                self._outbox.append(acp.encode_message({"jsonrpc": "2.0", "id": mid, "result": {"sessionId": "s1"}}))
            elif method == "session/prompt":
                self._outbox.append(acp.encode_message(acp.notification(
                    "session/update", {"update": {"content": {"type": "text", "text": "inspected infrastructure"}}})))
                self._outbox.append(acp.encode_message({"jsonrpc": "2.0", "id": mid, "result": {"stopReason": "end_turn"}}))

    def read_chunks(self):
        while self._outbox:
            yield self._outbox.pop(0)

    def close(self):
        pass


class FakeShaiPopen:
    def __init__(self, lines):
        import io
        self.stdout = io.StringIO("".join(l + "\n" for l in lines))

    def poll(self):
        return 0

    def wait(self):
        return 0

    def terminate(self):
        pass


def _kiro_adapter():
    return KiroAcpAdapter(
        "kiro-container",
        transport_factory=lambda: MockKiroTransport(),
        remote_exec=lambda ip, cmd, timeout=30: (True, "true", ""),
    )


def _shai_adapter():
    return shai_cli.ShaiCliAdapter(
        "shai-container",
        popen=lambda argv: FakeShaiPopen(["inspected infrastructure"]),
        remote_exec=lambda ip, cmd, timeout=30: (True, "true", ""),
    )


# --------------------------------------------------------------------------- #
# The scenario
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("runtime_name,adapter_factory", [
    ("kiro", _kiro_adapter),
    ("shai", _shai_adapter),
])
def test_governed_scenario(runtime_name, adapter_factory):
    tenant_id = 1
    identity = f"agent://default/infra-agent-{runtime_name}"
    events = Events()
    agent_repo = AgentRepo()
    agent_repo.seed(tenant_id, 100, identity)
    approvals = Approvals()

    # --- 2. drive the agent to RUNNING via the lifecycle + real adapter ---
    adapter = adapter_factory()
    lifecycle = LifecycleService(
        events_repo=events,
        adapter_for=lambda agent: adapter,
        launcher=lambda agent, ref: {"server_id": 1, "container_id": f"{runtime_name}-c"},
        agent_repo=agent_repo,
    )
    lifecycle.install_and_ready(tenant_id, 100)
    lifecycle.start(tenant_id, 100)
    assert agent_repo.agents[(tenant_id, 100)]["status"] == lc.RUNNING
    # Adapter actually speaks its protocol (capabilities advertised, no faking).
    assert Capability.EXECUTE in set(adapter.get_capabilities())

    # --- 4. submit + execute an inspect task; agent streams output ---
    class TaskRepo:
        def __init__(self):
            self.t = {"id": 1, "tenant_id": tenant_id, "agent_id": 100,
                      "task_ref": f"task-{runtime_name}", "operation": "prompt",
                      "payload": {"prompt": "inspect infrastructure"}, "status": "claimed",
                      "cancel_requested": False}

        def mark_running(self, tid):
            self.t["status"] = "running"

        def complete(self, tid, status, result=None):
            self.t["status"] = status
            self.t["result"] = result

        def is_cancel_requested(self, tid):
            return False

    task_repo = TaskRepo()
    out = worker.execute_claimed_task(
        task_repo.t, adapter_for=lambda a: adapter,
        agent_loader=agent_repo.get_agent, events_repo=events, repo=task_repo,
    )
    assert out["status"] == "succeeded"
    assert "inspected infrastructure" in out["output"]

    # --- 3 + 5-7. infra proxy enforcement with a read-only policy ---
    rules = [
        {"action": "openstack.server.list", "decision": "ALLOW"},
        {"action": "openstack.server.get", "decision": "ALLOW"},
        {"action": "openstack.server.delete", "decision": "REQUIRE_APPROVAL"},
    ]

    def decide(tid, action, **kw):
        # Stand-in for governance_service.decide using the pure engine + audit.
        d = pe.evaluate(action, rules=rules, permissions=["openstack.server.get"])
        from src.zaf.governance_service import params_hash
        es.emit(events, tid, "governance.decision", "zaf-pdp",
                agent_id=kw.get("agent_identity"),
                action={"action": action, "resource": kw.get("resource")},
                decision=d.decision, risk_score=d.risk_score,
                severity="HIGH" if d.decision in ("DENY", "QUARANTINE") else
                         ("MEDIUM" if d.decision == "REQUIRE_APPROVAL" else "INFO"))
        res = d.as_dict()
        res["params_hash"] = params_hash(action, kw.get("params"))
        return res

    minted = []
    proxy = InfraProxy(
        osp.MockOpenStackProvider(),
        decide=decide,
        approval_authorizer=approvals.is_authorized,
        token_minter=lambda t, cid, scope, ttl_seconds=120, agent_id=None: (
            minted.append((cid, scope)) or {"token": "tok"}),
        events_repo=events,
    )

    # 5. read is allowed and executes.
    listing = proxy.call(tenant_id, "server", "list", {}, agent_identity=identity, credential_id=5)
    assert listing.allowed is True
    assert any(s["id"] == "server-123" for s in listing.result["servers"])

    # 6. delete requires approval and is blocked; the server still exists.
    blocked = proxy.call(tenant_id, "server", "delete", {"id": "server-123"},
                         agent_identity=identity, credential_id=5)
    assert blocked.allowed is False and blocked.status_code == 202

    # 7. human approves the exact action+params, then the delete executes.
    from src.zaf.governance_service import params_hash
    phash = params_hash("openstack.server.delete", {"id": "server-123"})
    approvals.request("openstack.server.delete", {"id": "server-123"}, phash)
    approvals.approve(phash)
    allowed = proxy.call(tenant_id, "server", "delete", {"id": "server-123"},
                         agent_identity=identity, credential_id=5)
    assert allowed.allowed is True
    assert allowed.result["deleted"] is True
    assert minted  # a scoped token was minted for the executed mutation

    # A DIFFERENT server id is NOT authorized by the prior approval.
    other = proxy.call(tenant_id, "server", "delete", {"id": "server-456"},
                       agent_identity=identity, credential_id=5)
    assert other.allowed is False  # re-authorization required

    # --- 8. every decision is audited ---
    types = events.types()
    assert "agent.started" in types
    assert "task.succeeded" in types
    assert "governance.decision" in types
    assert "infra.api.call" in types
    # at least one ALLOW and one REQUIRE_APPROVAL decision were recorded
    decisions = [e["decision"] for e in events.events if e["event_type"] == "governance.decision"]
    assert "ALLOW" in decisions
    assert "REQUIRE_APPROVAL" in decisions


def test_live_openstack_is_gated(monkeypatch):
    """The real provider must refuse a mutation unless ZAF_LIVE_OPENSTACK=1."""
    monkeypatch.delenv("ZAF_LIVE_OPENSTACK", raising=False)
    provider = osp.OpenStackProvider(auth={"token": "x"}, http=lambda *a, **k: (200, {}))
    try:
        provider.call("server", "delete", {"id": "server-1"})
        assert False, "live mutation must be refused in CI"
    except PermissionError:
        pass


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
