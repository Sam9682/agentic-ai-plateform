#!/usr/bin/env python3
"""Property test for execution-row close-out (Task 9.8).

Feature: ARO agent lifecycle management — session Execution_Row close-out.

Covers the lifecycle service's stop() close-out path: stop() reads the agent's
latest still-open Execution_Row via ``latest_running_execution`` and sets it to
STOPPED with ``ended=True`` (recording the session end timestamp), satisfying
Req 1.8 (stop sets the Execution_Row STOPPED and records the session end
timestamp) and Req 4.4 (when a session ends, the Execution_Row is set to its
closed-out status and the session end timestamp is recorded).

The test drives the real ``LifecycleService`` against the shared in-memory
repo + capturing-events + FakeAdapter pattern (no DB / SSH), exercising both a
full start() -> stop() cycle and a stop() issued against an agent already in
RUNNING with an open Execution_Row, across arbitrary tenant/agent ids and
configurations.

Run directly:
    python3 tests/test_aro_execution_close_out.py
Or via pytest:
    pytest tests/test_aro_execution_close_out.py
"""
import os
import sys

from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.aro import lifecycle as lc  # noqa: E402
from src.aro.adapters.base import FakeAdapter  # noqa: E402
from src.aro.lifecycle_service import LifecycleService  # noqa: E402


# --------------------------------------------------------------------------- #
# In-memory repo + capturing events (InMemoryAgentRepo + CapturingEvents pattern
# mirrored from tests/test_aro_lifecycle.py). The repo tracks executions with a
# status and an ended_at so the close-out invariant is observable.
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
        self.executions.append(dict(
            id=eid, tenant_id=tenant_id, agent_id=agent_id,
            execution_ref=execution_ref, server_id=server_id,
            container_id=container_id, status="STARTING", ended_at=None,
        ))
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
            # Non-null end timestamp recorded on close-out (Req 1.8 / 4.4).
            e["ended_at"] = "2026-01-01T00:00:00Z"
        return True

    def set_execution_session(self, tenant_id, execution_id, session_id=None,
                              runtime_handle=None, runtime_adapter=None):
        # Mirror the real agent_repository.set_execution_session (Req 4.1):
        # persist the session handle columns so start()'s successful-path write
        # is honored by this close-out fake.
        e = self._find_execution(tenant_id, execution_id)
        if not e:
            return False
        e["session_id"] = session_id
        e["runtime_handle"] = runtime_handle
        e["runtime_adapter"] = runtime_adapter
        return True

    def seed(self, tenant_id, agent_id, *, identity, configuration):
        self.agents[(tenant_id, agent_id)] = dict(
            id=agent_id, tenant_id=tenant_id, identity=identity, name="a1",
            runtime_id=1, status=lc.REGISTERED, configuration=configuration,
            permissions=[],
        )


class CapturingEvents:
    def __init__(self):
        self.events = []

    def append_event(self, event):
        self.events.append(event)
        return dict(event, id=len(self.events))


def _service_with(repo_obj, events, configuration):
    return LifecycleService(
        events_repo=events,
        adapter_for=lambda agent: FakeAdapter(),
        launcher=lambda agent, ref: {"server_id": 1, "container_id": "c123"},
        agent_repo=repo_obj,
    )


# --------------------------------------------------------------------------- #
# Property 6: Execution-row close-out records ended status and timestamp
# Validates: Requirements 1.8, 4.4
# --------------------------------------------------------------------------- #
# Keep ids in a realistic positive range; configurations are arbitrary small
# JSON-ish dicts to show the close-out is independent of agent configuration.
_IDS = st.integers(min_value=1, max_value=10_000)
_CONFIG = st.dictionaries(
    keys=st.text(min_size=1, max_size=8),
    values=st.one_of(
        st.booleans(),
        st.integers(min_value=-1000, max_value=1000),
        st.text(max_size=16),
    ),
    max_size=4,
)
_SLUG = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789-", min_size=1, max_size=12,
)


@given(tenant_id=_IDS, agent_id=_IDS, slug=_SLUG, name=_SLUG, configuration=_CONFIG)
@settings(max_examples=150)
def test_start_stop_cycle_closes_out_execution_row(tenant_id, agent_id, slug, name,
                                                    configuration):
    """Feature: phase2-aro-completion, Property 6: Execution-row close-out records
    ended status and timestamp.

    After a successful start() -> stop() cycle, the agent's Execution_Row is
    closed out: its status is STOPPED and its ended_at is non-null, for
    arbitrary tenant/agent ids and configurations (Req 1.8, 4.4).
    """
    identity = f"agent://{slug}/{name}"
    repo_obj = InMemoryAgentRepo()
    repo_obj.seed(tenant_id, agent_id, identity=identity, configuration=configuration)
    svc = _service_with(repo_obj, CapturingEvents(), configuration)

    svc.install_and_ready(tenant_id, agent_id)
    svc.start(tenant_id, agent_id)
    assert repo_obj.agents[(tenant_id, agent_id)]["status"] == lc.RUNNING
    # Exactly one Execution_Row, open and RUNNING, before stop.
    assert len(repo_obj.executions) == 1
    assert repo_obj.executions[0]["status"] == lc.RUNNING
    assert repo_obj.executions[0]["ended_at"] is None

    svc.stop(tenant_id, agent_id)

    assert repo_obj.agents[(tenant_id, agent_id)]["status"] == lc.STOPPED
    row = repo_obj.executions[0]
    # Close-out invariant: STOPPED status + non-null end timestamp (Req 1.8/4.4).
    assert row["status"] == lc.STOPPED
    assert row["ended_at"] is not None
    # No open row remains for the agent.
    assert repo_obj.latest_running_execution(tenant_id, agent_id) is None


@given(tenant_id=_IDS, agent_id=_IDS, slug=_SLUG, name=_SLUG, configuration=_CONFIG)
@settings(max_examples=150)
def test_stop_from_running_with_open_row_closes_out(tenant_id, agent_id, slug, name,
                                                     configuration):
    """Feature: phase2-aro-completion, Property 6: Execution-row close-out records
    ended status and timestamp.

    Starting from a RUNNING agent with an open Execution_Row, stop() closes out
    that row — status becomes STOPPED and ended_at is set (non-null) — for
    arbitrary tenant/agent ids and configurations (Req 1.8, 4.4).
    """
    identity = f"agent://{slug}/{name}"
    repo_obj = InMemoryAgentRepo()
    repo_obj.seed(tenant_id, agent_id, identity=identity, configuration=configuration)
    # Place the agent directly in RUNNING with an open (RUNNING) Execution_Row,
    # modeling an already-running session rather than driving install/start.
    repo_obj.agents[(tenant_id, agent_id)]["status"] = lc.RUNNING
    eid = repo_obj.create_execution(tenant_id, agent_id, "exec-open")
    repo_obj.set_execution_status(tenant_id, eid, lc.RUNNING)
    assert repo_obj.latest_running_execution(tenant_id, agent_id) == eid

    svc = _service_with(repo_obj, CapturingEvents(), configuration)
    svc.stop(tenant_id, agent_id)

    assert repo_obj.agents[(tenant_id, agent_id)]["status"] == lc.STOPPED
    row = repo_obj._find_execution(tenant_id, eid)
    assert row["status"] == lc.STOPPED
    assert row["ended_at"] is not None
    assert repo_obj.latest_running_execution(tenant_id, agent_id) is None


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
