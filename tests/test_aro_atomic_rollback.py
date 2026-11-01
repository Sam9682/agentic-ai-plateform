#!/usr/bin/env python3
"""Property test for atomic install/start rollback (Task 9.10).

Feature: phase2-aro-completion, Property 4.

Property 4 — Install/start failure rolls back to pre-op status atomically
(Validates: Requirements 1.9, 1.10):

* install_and_ready() starts from REGISTERED. When the injected adapter's
  install() returns ExecutionResult(success=False), the operation compensates
  (task 9.9 _rollback_to): after the operation the agent's persisted status
  EQUALS the pre-op status (REGISTERED), NOT FAILED, and an
  ``agent.install.failed`` event is emitted.

* start() starts from a valid pre-op status (READY or STOPPED). When the
  injected adapter's start() returns ExecutionResult(success=False), the
  operation compensates: the agent's persisted status EQUALS the pre-op status
  (READY/STOPPED), NOT FAILED; the created Execution_Row is closed out (FAILED,
  ended_at set); and an ``agent.start.failed`` event is emitted.

The property varies tenant/agent ids, agent configurations, and (for start) the
pre-op status in {READY, STOPPED}. It uses an InMemoryAgentRepo + CapturingEvents
and a failing adapter subclassing FakeAdapter (base.py) whose install()/start()
return ExecutionResult(success=False).

Run directly:
    python3 tests/test_aro_atomic_rollback.py
Or via pytest:
    pytest tests/test_aro_atomic_rollback.py
"""
import os
import sys

from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.aro import lifecycle as lc  # noqa: E402
from src.aro.adapters.base import Capability, ExecutionResult, FakeAdapter  # noqa: E402
from src.aro.lifecycle_service import LifecycleService  # noqa: E402


# --------------------------------------------------------------------------- #
# In-memory test doubles (same shape as tests/test_aro_lifecycle.py)
# --------------------------------------------------------------------------- #
class InMemoryAgentRepo:
    def __init__(self):
        self.agents = {}
        self.executions = []
        self._eid = 1

    def get_agent(self, tenant_id, agent_id):
        a = self.agents.get((tenant_id, agent_id))
        return dict(a) if a else None

    def update_status(self, tenant_id, agent_id, new_status):
        a = self.agents.get((tenant_id, agent_id))
        if not a:
            return False
        a["status"] = new_status
        return True

    def create_execution(self, tenant_id, agent_id, execution_ref,
                         server_id=None, container_id=None):
        eid = self._eid
        self._eid += 1
        self.executions.append(dict(id=eid, tenant_id=tenant_id, agent_id=agent_id,
                                    execution_ref=execution_ref, server_id=server_id,
                                    container_id=container_id, status="STARTING",
                                    ended_at=None))
        return eid

    def _find_execution(self, tenant_id, execution_id):
        for e in self.executions:
            if e["tenant_id"] == tenant_id and e["id"] == execution_id:
                return e
        return None

    def latest_running_execution(self, tenant_id, agent_id):
        candidates = [
            e for e in self.executions
            if e["tenant_id"] == tenant_id and e["agent_id"] == agent_id
            and e.get("ended_at") is None
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda e: e["id"])["id"]

    def set_execution_status(self, tenant_id, execution_id, status, ended=False):
        e = self._find_execution(tenant_id, execution_id)
        if not e:
            return False
        e["status"] = status
        if ended:
            e["ended_at"] = "2026-01-01T00:00:00Z"
        return True

    def seed(self, tenant_id, agent_id, status, configuration=None,
             identity="agent://default/a1"):
        self.agents[(tenant_id, agent_id)] = dict(
            id=agent_id, tenant_id=tenant_id, identity=identity, name="a1",
            runtime_id=1, status=status, configuration=configuration or {},
            permissions=[],
        )


class CapturingEvents:
    def __init__(self):
        self.events = []

    def append_event(self, event):
        self.events.append(event)
        return dict(event, id=len(self.events))


class _FailingInstallAdapter(FakeAdapter):
    """FakeAdapter whose install() returns ExecutionResult(success=False)."""

    def install(self, configuration):
        self._require(Capability.INSTALL)
        return ExecutionResult(success=False, returncode=1, output="",
                               error="install boom")


class _FailingStartAdapter(FakeAdapter):
    """FakeAdapter whose start() returns ExecutionResult(success=False).

    install() still succeeds so the agent can be driven to READY when needed.
    """

    def start(self, agent_id, configuration):
        self._require(Capability.START)
        return ExecutionResult(success=False, returncode=1, output="",
                               error="start boom")


def _service(repo_obj, events, adapter):
    return LifecycleService(
        events_repo=events,
        adapter_for=lambda agent: adapter,
        launcher=lambda agent, ref: {"server_id": 1, "container_id": "c123"},
        agent_repo=repo_obj,
    )


# --------------------------------------------------------------------------- #
# Strategies
# --------------------------------------------------------------------------- #
_tenant_ids = st.integers(min_value=1, max_value=10_000)
_agent_ids = st.integers(min_value=1, max_value=10_000)
# Small, JSON-ish configurations to vary adapter input without affecting the
# compensation outcome.
_configs = st.dictionaries(
    keys=st.text(min_size=1, max_size=8),
    values=st.one_of(
        st.integers(),
        st.text(max_size=16),
        st.booleans(),
        st.none(),
    ),
    max_size=4,
)
# start() is legal only from READY or STOPPED (the valid pre-op statuses).
_start_pre_op = st.sampled_from([lc.READY, lc.STOPPED])


# --------------------------------------------------------------------------- #
# Property 4: install_and_ready failure rolls back to REGISTERED atomically
# --------------------------------------------------------------------------- #
@given(tenant_id=_tenant_ids, agent_id=_agent_ids, configuration=_configs)
@settings(max_examples=150)
def test_property4_install_failure_rolls_back_to_pre_op(tenant_id, agent_id,
                                                        configuration):
    """Feature: phase2-aro-completion, Property 4.

    For an agent at its valid pre-op status (REGISTERED) with an adapter whose
    install() returns success=False, after install_and_ready the agent's
    persisted status EQUALS the pre-op status (REGISTERED), NOT FAILED, and
    ``agent.install.failed`` is emitted (Req 1.9).
    """
    repo_obj = InMemoryAgentRepo()
    pre_op = lc.REGISTERED
    repo_obj.seed(tenant_id, agent_id, status=pre_op, configuration=configuration)
    events = CapturingEvents()
    svc = _service(repo_obj, events, _FailingInstallAdapter())

    svc.install_and_ready(tenant_id, agent_id)

    final = repo_obj.agents[(tenant_id, agent_id)]["status"]
    assert final == pre_op, f"expected rollback to {pre_op}, got {final}"
    assert final != lc.FAILED
    assert any(e["event_type"] == "agent.install.failed" for e in events.events)


# --------------------------------------------------------------------------- #
# Property 4: start failure rolls back to pre-op + releases the execution row
# --------------------------------------------------------------------------- #
@given(
    tenant_id=_tenant_ids,
    agent_id=_agent_ids,
    configuration=_configs,
    pre_op=_start_pre_op,
)
@settings(max_examples=150)
def test_property4_start_failure_rolls_back_and_releases_row(tenant_id, agent_id,
                                                             configuration, pre_op):
    """Feature: phase2-aro-completion, Property 4.

    For an agent at a valid pre-op status (READY or STOPPED) with an adapter
    whose start() returns success=False, after start() the agent's persisted
    status EQUALS the pre-op status (NOT FAILED); the created Execution_Row is
    closed out (FAILED, ended_at set); and ``agent.start.failed`` is emitted
    (Req 1.10).
    """
    repo_obj = InMemoryAgentRepo()
    repo_obj.seed(tenant_id, agent_id, status=pre_op, configuration=configuration)
    events = CapturingEvents()
    svc = _service(repo_obj, events, _FailingStartAdapter())

    svc.start(tenant_id, agent_id)

    # Agent restored to its pre-op status, never FAILED (Req 1.10).
    final = repo_obj.agents[(tenant_id, agent_id)]["status"]
    assert final == pre_op, f"expected rollback to {pre_op}, got {final}"
    assert final != lc.FAILED

    # Exactly one Execution_Row was created and it is closed out: FAILED with
    # ended_at recorded (Req 1.10 — release the created execution row).
    rows = [e for e in repo_obj.executions
            if e["tenant_id"] == tenant_id and e["agent_id"] == agent_id]
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == lc.FAILED
    assert row["ended_at"] is not None
    # No execution row is left open after compensation.
    assert repo_obj.latest_running_execution(tenant_id, agent_id) is None

    assert any(e["event_type"] == "agent.start.failed" for e in events.events)


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
