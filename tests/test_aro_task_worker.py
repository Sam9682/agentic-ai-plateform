#!/usr/bin/env python3
"""Tests for the agent task queue + worker (Task 10).

Feature: ARO task execution (SRS §3.4, §3.5).

Validates:
* idempotency: submitting the same idempotency_key returns the existing task
  (no duplicate enqueue).
* claim: concurrent claims never return the same task (stub models
  FOR UPDATE SKIP LOCKED single-row pop).
* execute_claimed_task: happy path -> succeeded with output + events; adapter
  error -> failed; cancel before/during -> cancelled.

Run directly:
    python3 tests/test_aro_task_worker.py
Or via pytest:
    pytest tests/test_aro_task_worker.py
"""
import os
import sys
import threading

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.aro import agent_worker as worker  # noqa: E402
from src.aro import task_repository as task_repo  # noqa: E402
from src.aro.adapters.base import FakeAdapter, ExecutionResult  # noqa: E402


class CapturingEvents:
    def __init__(self):
        self.events = []

    def append_event(self, event):
        self.events.append(event)
        return dict(event, id=len(self.events))


# --------------------------------------------------------------------------- #
# Idempotency + claim (stub task repo over an in-memory queue)
# --------------------------------------------------------------------------- #
class InMemoryTaskRepo:
    """In-memory task store modeling the claim + completion contract."""

    def __init__(self):
        self.tasks = {}
        self._id = 1
        self._lock = threading.Lock()

    def submit(self, tenant_id, agent_id, *, idempotency_key=None, payload=None, **kw):
        if idempotency_key:
            for t in self.tasks.values():
                if t["tenant_id"] == tenant_id and t.get("idempotency_key") == idempotency_key:
                    return dict(t)
        tid = self._id
        self._id += 1
        t = dict(id=tid, tenant_id=tenant_id, agent_id=agent_id, task_ref=f"task-{tid}",
                 operation=kw.get("operation", "prompt"), payload=payload or {},
                 status="pending", idempotency_key=idempotency_key, cancel_requested=False,
                 attempts=0, max_attempts=kw.get("max_attempts", 1), result=None)
        self.tasks[tid] = t
        return dict(t)

    def claim_next_task(self, worker_id):
        with self._lock:
            for t in self.tasks.values():
                if t["status"] == "pending" and not t["cancel_requested"]:
                    t["status"] = "claimed"
                    t["attempts"] += 1
                    t["worker_id"] = worker_id
                    return dict(t)
            return None

    def mark_running(self, task_id):
        self.tasks[task_id]["status"] = "running"

    def complete(self, task_id, status, result=None):
        self.tasks[task_id]["status"] = status
        self.tasks[task_id]["result"] = result

    def request_cancel(self, tenant_id, task_id):
        t = self.tasks.get(task_id)
        if t and t["tenant_id"] == tenant_id:
            t["cancel_requested"] = True
            return True
        return False

    def is_cancel_requested(self, task_id):
        return bool(self.tasks.get(task_id, {}).get("cancel_requested"))


def test_idempotent_submit():
    repo = InMemoryTaskRepo()
    a = repo.submit(1, 10, idempotency_key="k1", payload={"prompt": "x"})
    b = repo.submit(1, 10, idempotency_key="k1", payload={"prompt": "x"})
    assert a["id"] == b["id"]
    assert len(repo.tasks) == 1


def test_claim_no_double_execution():
    repo = InMemoryTaskRepo()
    for _ in range(5):
        repo.submit(1, 10, payload={"prompt": "x"})
    claimed = []
    lock = threading.Lock()

    def claimer():
        while True:
            t = repo.claim_next_task("w")
            if t is None:
                return
            with lock:
                claimed.append(t["id"])

    threads = [threading.Thread(target=claimer) for _ in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert sorted(claimed) == [1, 2, 3, 4, 5]
    assert len(claimed) == len(set(claimed))  # no task claimed twice


# --------------------------------------------------------------------------- #
# execute_claimed_task
# --------------------------------------------------------------------------- #
def _agent_loader(tenant_id, agent_id):
    return {"id": agent_id, "tenant_id": tenant_id, "identity": "agent://default/a1"}


def test_execute_success():
    repo = InMemoryTaskRepo()
    task = repo.submit(1, 10, payload={"prompt": "hello"})
    task = repo.claim_next_task("w")
    events = CapturingEvents()
    out = worker.execute_claimed_task(
        task, adapter_for=lambda a: FakeAdapter(), agent_loader=_agent_loader,
        events_repo=events, repo=repo,
    )
    assert out["status"] == "succeeded"
    assert "echo: hello" in out["output"]
    assert repo.tasks[task["id"]]["status"] == "succeeded"
    assert any(e["event_type"] == "task.succeeded" for e in events.events)


def test_execute_adapter_error_marks_failed():
    repo = InMemoryTaskRepo()
    repo.submit(1, 10, payload={"prompt": "x"})
    task = repo.claim_next_task("w")

    class BoomAdapter(FakeAdapter):
        def execute(self, agent_id, task):
            raise RuntimeError("kaboom")

    events = CapturingEvents()
    out = worker.execute_claimed_task(
        task, adapter_for=lambda a: BoomAdapter(), agent_loader=_agent_loader,
        events_repo=events, repo=repo,
    )
    assert out["status"] == "failed"
    assert repo.tasks[task["id"]]["status"] == "failed"
    assert any(e["event_type"] == "task.failed" for e in events.events)


def test_execute_cancel_before_start():
    repo = InMemoryTaskRepo()
    repo.submit(1, 10, payload={"prompt": "x"})
    task = repo.claim_next_task("w")
    repo.request_cancel(1, task["id"])
    events = CapturingEvents()
    out = worker.execute_claimed_task(
        task, adapter_for=lambda a: FakeAdapter(), agent_loader=_agent_loader,
        events_repo=events, repo=repo,
    )
    assert out["status"] == "cancelled"
    assert repo.tasks[task["id"]]["status"] == "cancelled"


def test_execute_cancel_during_stream():
    repo = InMemoryTaskRepo()
    repo.submit(1, 10, payload={"prompt": "x"})
    task = repo.claim_next_task("w")
    events = CapturingEvents()

    # cancel_probe returns False first (before start) then True (during stream).
    calls = {"n": 0}

    def probe(task_id):
        calls["n"] += 1
        return calls["n"] > 1

    out = worker.execute_claimed_task(
        task, adapter_for=lambda a: FakeAdapter(), agent_loader=_agent_loader,
        events_repo=events, repo=repo, cancel_probe=probe,
    )
    assert out["status"] == "cancelled"


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
