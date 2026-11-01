#!/usr/bin/env python3
"""Property test for unreachable-session close-out (Task 11.5).

Feature: ARO session durability — control-plane-restart reconnect routine.

Covers ``execution_manager.reconnect_running_sessions(...)`` on the UNREACHABLE
path: for each RUNNING ``agent_executions`` row whose injected ``probe(row)``
returns falsy, the routine

* transitions the agent RUNNING -> UNHEALTHY (Req 4.3) via the lifecycle
  service (a graph-legal edge),
* closes out the Execution_Row as UNHEALTHY with ``ended=True`` so a non-null
  ``ended_at`` is recorded (Req 4.3 / 4.4),
* emits an ``agent.unhealthy`` event through the existing event service with the
  canonical schema (Req 4.5),
* lists the row under ``"closed_out"`` in the returned summary, and
* launches NO new runtime (Req 4.2 is the complement; here we assert the
  unreachable path never relaunches).

The routine is driven against injected fakes only (no DB / SSH): an in-memory
agent repo with RUNNING agents + rows that track ``set_execution_status``/
``ended``, a real ``LifecycleService`` wired to those fakes, a ``CapturingEvents``
sink, and ``probe=lambda row: False`` so every persisted session is unreachable.

Run directly:
    python3 tests/test_aro_session_reconnect_unreachable.py
Or via pytest:
    pytest tests/test_aro_session_reconnect_unreachable.py
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
from src.aro.lifecycle_service import LifecycleService  # noqa: E402


# --------------------------------------------------------------------------- #
# In-memory agent repo + capturing events (mirrors the InMemoryAgentRepo /
# CapturingEvents pattern used across tests/test_aro_*.py). The repo tracks
# executions with a status and an ended_at and exposes list_running_executions
# so the reconnect routine can be unit-driven with no DB.
# --------------------------------------------------------------------------- #
class InMemoryAgentRepo:
    def __init__(self):
        self.agents = {}
        self.executions = []
        # Record every set_execution_status call so the close-out is observable.
        self.status_calls = []

    def get_agent(self, tenant_id, agent_id):
        a = self.agents.get((tenant_id, agent_id))
        return dict(a) if a else None

    def update_status(self, tenant_id, agent_id, new_status):
        a = self.agents.get((tenant_id, agent_id))
        if not a:
            return False
        a["status"] = new_status
        return True

    def _find_execution(self, tenant_id, execution_id):
        for e in self.executions:
            if e["tenant_id"] == tenant_id and e["id"] == execution_id:
                return e
        return None

    def list_running_executions(self, tenant_id):
        # Only RUNNING rows for this tenant are candidates for reconnect
        # (mirrors the real agent_repository.list_running_executions).
        return [
            dict(e)
            for e in self.executions
            if e["tenant_id"] == tenant_id and e["status"] == lc.RUNNING
        ]

    def set_execution_status(self, tenant_id, execution_id, status, ended=False):
        self.status_calls.append((tenant_id, execution_id, status, ended))
        e = self._find_execution(tenant_id, execution_id)
        if not e:
            return False
        e["status"] = status
        if ended:
            # Non-null end timestamp recorded on close-out (Req 4.3 / 4.4).
            e["ended_at"] = "2026-01-01T00:00:00Z"
        return True

    def seed_running(self, tenant_id, agent_id, exec_id, *, identity):
        """Seed a RUNNING agent with an open RUNNING Execution_Row."""
        self.agents[(tenant_id, agent_id)] = dict(
            id=agent_id, tenant_id=tenant_id, identity=identity, name="a1",
            runtime_id=1, status=lc.RUNNING, configuration={}, permissions=[],
        )
        self.executions.append(dict(
            id=exec_id, tenant_id=tenant_id, agent_id=agent_id,
            execution_ref=f"exec-{exec_id}", server_id=1,
            container_id=f"c{exec_id}", runtime_handle=f"h{exec_id}",
            status=lc.RUNNING, ended_at=None,
        ))


class CapturingEvents:
    def __init__(self):
        self.events = []

    def append_event(self, event):
        self.events.append(event)
        return dict(event, id=len(self.events))


class _LaunchSpy:
    """A probe-wrapper that also records whether any launch was requested.

    The reconnect routine drives reachability solely through ``probe`` and never
    launches on the unreachable path; this spy lets the test assert no launch
    occurred by exposing an ``adapter_for`` that must never be invoked.
    """

    def __init__(self):
        self.adapter_calls = 0

    def adapter_for(self, agent):
        self.adapter_calls += 1
        raise AssertionError("reconnect must not build an adapter / relaunch")


# --------------------------------------------------------------------------- #
# Strategies: a set of distinct (tenant_id, agent_id, exec_id) RUNNING sessions.
# --------------------------------------------------------------------------- #
_IDS = st.integers(min_value=1, max_value=10_000)
_SLUG = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789-", min_size=1, max_size=12,
)


def _distinct_sessions(draw, tenant_id):
    """Draw 1..6 sessions with distinct agent ids and distinct exec ids."""
    n = draw(st.integers(min_value=1, max_value=6))
    agent_ids = draw(
        st.lists(_IDS, min_size=n, max_size=n, unique=True)
    )
    exec_ids = draw(
        st.lists(_IDS, min_size=n, max_size=n, unique=True)
    )
    names = draw(st.lists(_SLUG, min_size=n, max_size=n))
    return list(zip(agent_ids, exec_ids, names))


@st.composite
def _scenario(draw):
    tenant_id = draw(_IDS)
    sessions = _distinct_sessions(draw, tenant_id)
    return tenant_id, sessions


# --------------------------------------------------------------------------- #
# Property 19: Unreachable persisted sessions go UNHEALTHY and close out
# Validates: Requirements 4.3
# --------------------------------------------------------------------------- #
@given(scenario=_scenario())
@settings(max_examples=150)
def test_unreachable_sessions_go_unhealthy_and_close_out(scenario):
    """Feature: phase2-aro-completion, Property 19: Unreachable persisted sessions
    go UNHEALTHY and close out.

    For arbitrary RUNNING execution rows with ``probe`` returning False, each
    unreachable session results in: the agent transitioned RUNNING -> UNHEALTHY,
    the Execution_Row closed out with status UNHEALTHY and ended_at set, an
    ``agent.unhealthy`` event emitted, and the row listed under ``closed_out`` in
    the returned summary — with NO new runtime launched (Req 4.3, and the 4.2
    complement). (Req 4.4/4.5 covered as the close-out + canonical-event side.)
    """
    tenant_id, sessions = scenario
    repo_obj = InMemoryAgentRepo()
    for agent_id, exec_id, name in sessions:
        repo_obj.seed_running(
            tenant_id, agent_id, exec_id, identity=f"agent://{name}/{agent_id}"
        )

    events = CapturingEvents()
    spy = _LaunchSpy()
    svc = LifecycleService(
        events_repo=events,
        adapter_for=spy.adapter_for,  # must never be called on this path
        agent_repo=repo_obj,
    )

    exec_ids = {exec_id for _, exec_id, _ in sessions}

    summary = em.reconnect_running_sessions(
        tenant_id,
        probe=lambda row: False,  # every persisted session is unreachable
        lifecycle_service=svc,
        agent_repo=repo_obj,
        events_repo=events,
    )

    # Summary: every row closed out, none reconnected.
    assert sorted(summary["closed_out"]) == sorted(exec_ids)
    assert summary["reconnected"] == []

    # No new runtime launched: the adapter factory was never consulted.
    assert spy.adapter_calls == 0

    # Each unreachable session: agent UNHEALTHY + row closed out UNHEALTHY/ended.
    for agent_id, exec_id, _ in sessions:
        assert repo_obj.agents[(tenant_id, agent_id)]["status"] == lc.UNHEALTHY
        row = repo_obj._find_execution(tenant_id, exec_id)
        assert row["status"] == lc.UNHEALTHY
        assert row["ended_at"] is not None
        # The close-out write was a UNHEALTHY + ended=True set_execution_status.
        assert (tenant_id, exec_id, lc.UNHEALTHY, True) in repo_obj.status_calls
        # No RUNNING row remains for this tenant/agent.
        assert row not in repo_obj.list_running_executions(tenant_id)

    # One agent.unhealthy event per unreachable session, canonical schema,
    # scoped to the tenant.
    unhealthy = [e for e in events.events if e["event_type"] == "agent.unhealthy"]
    assert len(unhealthy) == len(sessions)
    for e in unhealthy:
        assert e["tenant_id"] == tenant_id
        # Canonical build_event shape fields are present.
        for field in ("event_id", "event_type", "source", "action",
                      "correlation_id", "occurred_at", "execution_id"):
            assert field in e


@given(tenant_id=_IDS, agent_id=_IDS, exec_id=_IDS, name=_SLUG)
@settings(max_examples=150)
def test_single_unreachable_session_closed_even_if_agent_status_drifted(
    tenant_id, agent_id, exec_id, name
):
    """Feature: phase2-aro-completion, Property 19: Unreachable persisted sessions
    go UNHEALTHY and close out.

    When the row is RUNNING but the agent status has drifted off RUNNING (so the
    RUNNING -> UNHEALTHY transition is no longer graph-legal), the illegal
    transition is swallowed and the stale row is STILL closed out as UNHEALTHY
    with ended set and listed under ``closed_out`` — no half-open session
    survives (Req 4.3), and still no relaunch.
    """
    repo_obj = InMemoryAgentRepo()
    repo_obj.seed_running(
        tenant_id, agent_id, exec_id, identity=f"agent://{name}/{agent_id}"
    )
    # Drift the agent off RUNNING (STOPPING) while the row stays RUNNING: now
    # STOPPING -> UNHEALTHY is NOT a legal edge, so transition() raises and is
    # swallowed, but the row must still be closed out.
    repo_obj.agents[(tenant_id, agent_id)]["status"] = lc.STOPPING

    events = CapturingEvents()
    spy = _LaunchSpy()
    svc = LifecycleService(
        events_repo=events, adapter_for=spy.adapter_for, agent_repo=repo_obj,
    )

    summary = em.reconnect_running_sessions(
        tenant_id,
        probe=lambda row: False,
        lifecycle_service=svc,
        agent_repo=repo_obj,
        events_repo=events,
    )

    assert summary["closed_out"] == [exec_id]
    assert summary["reconnected"] == []
    assert spy.adapter_calls == 0

    row = repo_obj._find_execution(tenant_id, exec_id)
    assert row["status"] == lc.UNHEALTHY
    assert row["ended_at"] is not None
    assert (tenant_id, exec_id, lc.UNHEALTHY, True) in repo_obj.status_calls
    # The close-out event is still emitted on the drifted path.
    assert any(e["event_type"] == "agent.unhealthy" for e in events.events)


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
