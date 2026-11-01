#!/usr/bin/env python3
"""Property test for reachable-session reconnect (Task 11.4).

Feature: ARO session durability (Phase 2, Req 4.2).

Validates:
* Property 18 — Reachable RUNNING sessions reconnect without relaunch:
  :func:`src.aro.execution_manager.reconnect_running_sessions` loads the RUNNING
  Execution_Rows for a tenant and, for every row whose ``probe`` reports it is
  still reachable, re-attaches in place: the agent stays RUNNING, the row stays
  RUNNING and is never ended, NO new runtime is launched, NO lifecycle
  transition is driven, and the row id is listed under ``reconnected`` (and never
  under ``closed_out``).

Run directly:
    python3 tests/test_aro_session_reconnect.py
Or via pytest:
    pytest tests/test_aro_session_reconnect.py
"""
import os
import sys

from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.aro import execution_manager as em  # noqa: E402
from src.aro import lifecycle as lc  # noqa: E402


# --------------------------------------------------------------------------- #
# Injected fakes (no DB, no SSH)
# --------------------------------------------------------------------------- #
class FakeAgentRepo:
    """Fake agent repository tracking the RUNNING rows and any mutations.

    * ``list_running_executions`` returns the generated RUNNING rows.
    * ``set_execution_status`` records every call so the test can assert a
      reachable row is NEVER closed out / transitioned off RUNNING.
    """

    def __init__(self, rows):
        # Store independent copies so a mutation attempt is observable but the
        # generated input stays pristine.
        self._rows = [dict(r) for r in rows]
        self.set_status_calls = []

    def list_running_executions(self, tenant_id):
        return [dict(r) for r in self._rows]

    def set_execution_status(self, tenant_id, execution_id, status, ended=False):
        self.set_status_calls.append(
            dict(tenant_id=tenant_id, execution_id=execution_id,
                 status=status, ended=ended)
        )
        for r in self._rows:
            if r["id"] == execution_id:
                r["status"] = status
                if ended:
                    r["ended_at"] = "2026-01-01T00:00:00Z"
        return True


class TransitionDetectingLifecycleService:
    """Lifecycle-service fake that records any transition / launch attempt.

    A reachable reconnect must drive NO transition at all, so every call here is
    a property violation we can assert against.
    """

    def __init__(self):
        self.transitions = []
        self.launches = []

    def transition(self, tenant_id, agent_id, new_status, **kwargs):
        self.transitions.append(
            dict(tenant_id=tenant_id, agent_id=agent_id, new_status=new_status)
        )
        return True

    # Present so that if the routine ever tried to (re)launch through the
    # service it would be caught; reconnect must never launch for reachable rows.
    def start(self, tenant_id, agent_id, *args, **kwargs):
        self.launches.append(dict(tenant_id=tenant_id, agent_id=agent_id))
        return True


class RecordingEvents:
    """Events repo fake; a reachable reconnect emits nothing."""

    def __init__(self):
        self.events = []

    def append_event(self, event):
        self.events.append(event)
        return dict(event, id=len(self.events))


# --------------------------------------------------------------------------- #
# Strategies
# --------------------------------------------------------------------------- #
def _build_rows(ids):
    return [
        {
            "id": eid,
            "agent_id": 100 + i,
            "execution_ref": f"exec-{eid}",
            "server_id": 1,
            "container_id": f"c{eid}",
            "session_id": f"sess-{eid}",
            "runtime_handle": f"handle-{eid}",
            "runtime_adapter": "mcp",
            "status": lc.RUNNING,
            "ended_at": None,
        }
        for i, eid in enumerate(ids)
    ]


def _running_rows():
    """Generate a set of RUNNING execution rows with distinct ids."""
    return st.lists(
        st.integers(min_value=1, max_value=10_000),
        min_size=0,
        max_size=12,
        unique=True,
    ).map(_build_rows)


# --------------------------------------------------------------------------- #
# Property 18: Reachable RUNNING sessions reconnect without relaunch
# --------------------------------------------------------------------------- #
@given(rows=_running_rows())
@settings(max_examples=150)
def test_reachable_sessions_reconnect_without_relaunch(rows):
    """Feature: phase2-aro-completion, Property 18: Reachable RUNNING sessions \
reconnect without relaunch.

    Validates: Requirements 4.2

    For an arbitrary set of RUNNING execution rows where ``probe`` returns True
    for every row, ``reconnect_running_sessions`` re-attaches every reachable
    row: the agent stays RUNNING, the row stays RUNNING and is not ended, NO
    launch is invoked, NO lifecycle transition is driven, and the returned
    summary lists exactly those rows under ``reconnected`` with an empty
    ``closed_out``.
    """
    tenant_id = 7
    agent_repo = FakeAgentRepo(rows)
    svc = TransitionDetectingLifecycleService()
    events = RecordingEvents()

    # An explicit launch tracker proves the routine never launches a new runtime
    # for a reachable row. adapter_for is wired to a factory that would record a
    # call if the routine ever asked for an adapter to (re)launch.
    launches = []

    def adapter_for(agent):
        launches.append(agent)
        return object()

    # probe returns True for every row -> all rows are reachable.
    summary = em.reconnect_running_sessions(
        tenant_id,
        adapter_for=adapter_for,
        probe=lambda row: True,
        lifecycle_service=svc,
        agent_repo=agent_repo,
        events_repo=events,
    )

    expected_ids = [r["id"] for r in rows]

    # Every reachable row is reported as reconnected, none closed out.
    assert sorted(summary["reconnected"]) == sorted(expected_ids)
    assert summary["closed_out"] == []

    # NO relaunch: neither the lifecycle service start nor the adapter factory
    # was consulted to launch a new runtime.
    assert svc.launches == []
    assert launches == []

    # NO transition driven for any reachable row.
    assert svc.transitions == []

    # Row stays RUNNING / not ended and no close-out write happened.
    assert agent_repo.set_status_calls == []
    for r in agent_repo._rows:
        assert r["status"] == lc.RUNNING
        assert r.get("ended_at") is None

    # No events emitted for a clean reconnect.
    assert events.events == []


def test_reachable_subset_still_reconnects_all_true_rows():
    """Deterministic example: a generated subset probed True all reconnect.

    Validates: Requirements 4.2
    """
    tenant_id = 3
    rows = [
        {"id": 1, "agent_id": 11, "status": lc.RUNNING, "ended_at": None},
        {"id": 2, "agent_id": 12, "status": lc.RUNNING, "ended_at": None},
        {"id": 3, "agent_id": 13, "status": lc.RUNNING, "ended_at": None},
    ]
    agent_repo = FakeAgentRepo(rows)
    svc = TransitionDetectingLifecycleService()
    events = RecordingEvents()

    summary = em.reconnect_running_sessions(
        tenant_id,
        adapter_for=lambda agent: object(),
        probe=lambda row: True,
        lifecycle_service=svc,
        agent_repo=agent_repo,
        events_repo=events,
    )

    assert sorted(summary["reconnected"]) == [1, 2, 3]
    assert summary["closed_out"] == []
    assert svc.transitions == []
    assert agent_repo.set_status_calls == []


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
