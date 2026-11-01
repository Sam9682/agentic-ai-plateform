#!/usr/bin/env python3
"""Property test for cooperative cancellation in the ARO worker (Task 14.7).

Feature: phase2-aro-completion.

Validates:
* Property 30: Cancellation yields the cancelled terminal — for a task whose
  ``cancel_probe`` returns True (either before streaming starts, or at some
  point during the stream), :func:`agent_worker.execute_claimed_task` ALWAYS
  yields status ``"cancelled"``, emits a ``task.cancelled`` event, and NEVER
  re-enqueues the task. The task stays ``cancelled`` regardless of
  ``attempts``/``max_attempts`` (cancellation is a deliberate user decision, not
  a transient failure routed through bounded retry).

No live DB / SSH / real runtime: the task store is the in-memory repo modeling
the claim + completion + re-enqueue contract and the adapter is a deterministic
fake whose stream length is varied. The ``cancel_probe`` is driven to fire at a
chosen point (before start or after ``k`` chunks) so the test exercises both
cancellation paths in ``execute_claimed_task``.

Run directly:
    python3 tests/test_aro_worker_cancel.py
Or via pytest:
    pytest tests/test_aro_worker_cancel.py
"""
import os
import sys
import threading

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.aro import agent_worker as worker  # noqa: E402
from src.aro.adapters.base import (  # noqa: E402
    AgentRuntimeAdapter,
    Capability,
    ExecutionChunk,
    ExecutionHandle,
    ExecutionResult,
)


# --------------------------------------------------------------------------- #
# Test doubles
# --------------------------------------------------------------------------- #
class CapturingEvents:
    """Events repo stub that records every appended event."""

    def __init__(self):
        self.events = []

    def append_event(self, event):
        self.events.append(event)
        return dict(event, id=len(self.events))


class InMemoryTaskRepo:
    """In-memory task store modeling the claim + completion + retry contract.

    Mirrors the stub used by ``tests/test_aro_task_worker.py`` so the worker's
    real re-enqueue path (``reenqueue_or_finalize``) is exercised — proving that
    cancellation never takes it regardless of ``attempts``/``max_attempts``.
    """

    def __init__(self):
        self.tasks = {}
        self._id = 1
        self._lock = threading.Lock()
        self._now = 0.0

    def submit(self, tenant_id, agent_id, *, idempotency_key=None, payload=None, **kw):
        tid = self._id
        self._id += 1
        t = dict(
            id=tid, tenant_id=tenant_id, agent_id=agent_id, task_ref=f"task-{tid}",
            operation=kw.get("operation", "prompt"), payload=payload or {},
            status="pending", idempotency_key=idempotency_key,
            cancel_requested=False, attempts=0,
            max_attempts=kw.get("max_attempts", 1), result=None,
        )
        self.tasks[tid] = t
        return dict(t)

    def claim_next_task(self, worker_id, *, lease_ttl=60, preferred_tenant=None):
        with self._lock:
            candidates = [
                t for t in self.tasks.values()
                if t["status"] == "pending" and not t["cancel_requested"]
            ]
            if not candidates:
                return None
            candidates.sort(key=lambda t: t["id"])
            t = candidates[0]
            t["status"] = "claimed"
            t["attempts"] += 1
            t["worker_id"] = worker_id
            t["lease_expires_at"] = self._now + lease_ttl
            t["heartbeat_at"] = self._now
            return dict(t)

    def mark_running(self, tenant_id, task_id):
        t = self.tasks[task_id]
        if t["tenant_id"] != tenant_id:
            return False
        t["status"] = "running"
        return True

    def complete(self, tenant_id, task_id, status, result=None):
        t = self.tasks[task_id]
        if t["tenant_id"] != tenant_id:
            return False
        t["status"] = status
        t["result"] = result
        return True

    def heartbeat(self, tenant_id, task_id, *, lease_ttl=60):
        t = self.tasks.get(task_id)
        if not t or t["tenant_id"] != tenant_id:
            return False
        if t["status"] not in ("claimed", "running"):
            return False
        t["lease_expires_at"] = self._now + lease_ttl
        t["heartbeat_at"] = self._now
        return True

    def reenqueue_or_finalize(self, tenant_id, task_id, terminal_status, reason=None):
        """Bounded retry: re-enqueue below max_attempts else finalize.

        If cancellation ever (incorrectly) routed through this path, a task
        below ``max_attempts`` would flip back to ``pending`` — which the
        property asserts never happens. We also record every call so the test
        can assert the retry path was NOT consulted for a cancellation.
        """
        self.reenqueue_calls.append((tenant_id, task_id, terminal_status, reason))
        t = self.tasks.get(task_id)
        if not t or t["tenant_id"] != tenant_id:
            return {"outcome": "noop", "status": None,
                    "attempts": None, "max_attempts": None}
        attempts, max_attempts = t["attempts"], t["max_attempts"]
        if attempts < max_attempts:
            t["status"] = "pending"
            t["worker_id"] = None
            t["lease_expires_at"] = None
            t["heartbeat_at"] = None
            return {"outcome": "reenqueued", "status": "pending",
                    "attempts": attempts, "max_attempts": max_attempts}
        t["status"] = terminal_status
        t["result"] = {"reason": reason} if reason is not None else {}
        return {"outcome": "finalized", "status": terminal_status,
                "attempts": attempts, "max_attempts": max_attempts}

    reenqueue_calls = None  # set per-instance below

    def is_cancel_requested(self, task_id):
        return bool(self.tasks.get(task_id, {}).get("cancel_requested"))


class _StreamHandle(ExecutionHandle):
    """A handle yielding a fixed number of chunks; records cancel() calls."""

    def __init__(self, n_chunks):
        self._n = n_chunks
        self.cancelled = False

    def stream(self):
        for i in range(self._n):
            yield ExecutionChunk(channel="stdout", data=f"c{i}")

    def cancel(self):
        self.cancelled = True
        return True

    def result(self):
        return ExecutionResult(success=True, returncode=0, output="done")


class _StreamAdapter(AgentRuntimeAdapter):
    """Minimal adapter whose ``execute`` returns a fixed-length stream handle."""

    adapter_id = "stream-fake"

    def __init__(self, n_chunks):
        self._n = n_chunks
        self.handle = None

    def get_capabilities(self):
        return list(Capability)

    def install(self, configuration):
        return ExecutionResult(success=True, returncode=0)

    def start(self, agent_id, configuration):
        return ExecutionResult(success=True, returncode=0)

    def stop(self, agent_id):
        return ExecutionResult(success=True, returncode=0)

    def get_status(self, agent_id):
        return "RUNNING"

    def execute(self, agent_id, task):
        self.handle = _StreamHandle(self._n)
        return self.handle

    def get_logs(self, agent_id, limit=200):
        return ""

    def health_check(self):
        return True


def _agent_loader(tenant_id, agent_id):
    return {"id": agent_id, "tenant_id": tenant_id, "identity": "agent://default/a1"}


def _make_repo():
    repo = InMemoryTaskRepo()
    repo.reenqueue_calls = []
    return repo


# --------------------------------------------------------------------------- #
# Property 30: Cancellation yields the cancelled terminal
# --------------------------------------------------------------------------- #
# The property's precondition is that cancel_probe DOES return True at some
# reachable point — either before streaming starts or during the stream. The
# probe is called once before the stream (pre-start check) and once per chunk
# read, so there are exactly ``1 + n_chunks`` probe opportunities. We therefore
# constrain ``cancel_at`` to the range that actually fires:
#   cancel_at == 0   -> cancel on the pre-start check (before streaming starts).
#   1 <= cancel_at <= n_chunks -> cancel on the cancel_at-th in-stream read.
# ``n_chunks`` is drawn first and ``cancel_at`` is drawn dependent on it so the
# cancel is always reachable (an unreachable cancel is not an instance of this
# property — the task would simply succeed, which is correct behavior).
@given(data=st.data())
@settings(max_examples=200)
def test_property30_cancellation_yields_cancelled_terminal(data):
    """Cancellation always yields ``cancelled``, emits the event, never re-enqueues.

    Feature: phase2-aro-completion, Property 30: Cancellation yields the
    cancelled terminal.
    Validates: Requirements 6.11
    """
    n_chunks = data.draw(st.integers(min_value=1, max_value=8), label="n_chunks")
    # cancel_at in [0, n_chunks]: 0 = before start, k = during the k-th read.
    cancel_at = data.draw(
        st.integers(min_value=0, max_value=n_chunks), label="cancel_at"
    )
    max_attempts = data.draw(
        st.integers(min_value=1, max_value=10), label="max_attempts"
    )
    tenant_id = data.draw(
        st.integers(min_value=1, max_value=10_000), label="tenant_id"
    )
    agent_id = data.draw(
        st.integers(min_value=1, max_value=10_000), label="agent_id"
    )
    timeout_seconds = data.draw(
        st.one_of(st.none(), st.integers(min_value=1, max_value=10_000)),
        label="timeout_seconds",
    )

    repo = _make_repo()
    repo.submit(tenant_id, agent_id, payload={"prompt": "x"},
                max_attempts=max_attempts)
    task = repo.claim_next_task("w")
    # A deadline may be present; the pinned clock keeps monotonic() at 0.0 so
    # the timeout path can never pre-empt cancellation.
    if timeout_seconds is not None:
        task["timeout_seconds"] = timeout_seconds

    # Drive the cancel_probe. ``cancel_at == 0`` fires on the pre-start check
    # (1st call); ``cancel_at == k`` returns False for the first k calls (the
    # pre-start check plus the first k-1 in-stream checks) then True on the
    # k-th in-stream read — always reachable because cancel_at <= n_chunks.
    calls = {"n": 0}

    def probe(task_id):
        calls["n"] += 1
        return calls["n"] > cancel_at

    events = CapturingEvents()
    # Clock pinned so no real-time deadline is reached during the test.
    out = worker.execute_claimed_task(
        task,
        adapter_for=lambda a: _StreamAdapter(n_chunks),
        agent_loader=_agent_loader,
        events_repo=events,
        repo=repo,
        cancel_probe=probe,
        clock=lambda: 0.0,
    )

    # 1. The terminal status is ALWAYS "cancelled".
    assert out["status"] == "cancelled"

    # 2. The persisted task row is "cancelled".
    assert repo.tasks[task["id"]]["status"] == "cancelled"

    # 3. A task.cancelled event was emitted (and no success/fail/timeout event).
    types = [e["event_type"] for e in events.events]
    assert "task.cancelled" in types
    assert "task.succeeded" not in types
    assert "task.failed" not in types
    assert "task.timed_out" not in types

    # 4. Cancellation is NEVER re-enqueued — the retry path was never consulted,
    #    regardless of attempts/max_attempts. The result dict carries no
    #    re-enqueue outcome either.
    assert repo.reenqueue_calls == []
    assert "outcome" not in out


@given(
    max_attempts=st.integers(min_value=1, max_value=20),
    attempts_consumed=st.integers(min_value=0, max_value=19),
)
@settings(max_examples=200)
def test_property30_cancel_before_start_never_reenqueues_any_attempt(
    max_attempts, attempts_consumed
):
    """Cancel-before-start stays cancelled for any attempts/max_attempts state.

    Even when the task is deep into its retry budget (``attempts`` just below or
    at ``max_attempts``), a cancel requested before streaming starts yields the
    ``cancelled`` terminal with no re-enqueue.

    Feature: phase2-aro-completion, Property 30: Cancellation yields the
    cancelled terminal.
    Validates: Requirements 6.11
    """
    repo = _make_repo()
    submitted = repo.submit(1, 10, payload={"prompt": "x"}, max_attempts=max_attempts)
    # Pre-set attempts to an arbitrary point in the retry budget, then claim
    # (which increments attempts by one, as a real claim does).
    repo.tasks[submitted["id"]]["attempts"] = min(attempts_consumed, max_attempts)
    task = repo.claim_next_task("w")

    events = CapturingEvents()
    out = worker.execute_claimed_task(
        task,
        adapter_for=lambda a: _StreamAdapter(5),
        agent_loader=_agent_loader,
        events_repo=events,
        repo=repo,
        cancel_probe=lambda _tid: True,  # cancel before start
        clock=lambda: 0.0,
    )

    assert out["status"] == "cancelled"
    assert repo.tasks[task["id"]]["status"] == "cancelled"
    assert repo.reenqueue_calls == []
    assert any(e["event_type"] == "task.cancelled" for e in events.events)


def test_property30_cancel_during_stream_calls_handle_cancel():
    """Cancellation during the stream force-cancels the adapter handle.

    Feature: phase2-aro-completion, Property 30: Cancellation yields the
    cancelled terminal.
    Validates: Requirements 6.11
    """
    repo = _make_repo()
    repo.submit(1, 10, payload={"prompt": "x"}, max_attempts=3)
    task = repo.claim_next_task("w")

    adapter = _StreamAdapter(8)
    calls = {"n": 0}

    def probe(_tid):
        calls["n"] += 1
        return calls["n"] > 1  # False pre-start, True during the stream

    events = CapturingEvents()
    out = worker.execute_claimed_task(
        task,
        adapter_for=lambda a: adapter,
        agent_loader=_agent_loader,
        events_repo=events,
        repo=repo,
        cancel_probe=probe,
        clock=lambda: 0.0,
    )

    assert out["status"] == "cancelled"
    assert adapter.handle is not None
    assert adapter.handle.cancelled is True
    assert repo.reenqueue_calls == []
    assert repo.tasks[task["id"]]["status"] == "cancelled"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
