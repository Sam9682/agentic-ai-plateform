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
        # Virtual clock (seconds) so lease/heartbeat/reaper behavior is
        # deterministic in tests; advance it via ``advance``.
        self._now = 0.0

    def advance(self, seconds):
        self._now += seconds

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

    def pending_tenants(self):
        """Return {tenant_id: pending_count} for claimable rows (Req 6.10)."""
        counts = {}
        for t in self.tasks.values():
            if t["status"] == "pending" and not t["cancel_requested"]:
                counts[t["tenant_id"]] = counts.get(t["tenant_id"], 0) + 1
        return counts

    def claim_next_task(self, worker_id, *, lease_ttl=60, preferred_tenant=None):
        with self._lock:
            candidates = [
                t for t in self.tasks.values()
                if t["status"] == "pending" and not t["cancel_requested"]
            ]
            if not candidates:
                return None
            # Per-tenant fairness: the preferred tenant's work sorts first, then
            # by insertion order (id) as a stable tiebreak (Req 6.10). With no
            # preferred tenant this stays plain FIFO.
            candidates.sort(
                key=lambda t: (t["tenant_id"] != preferred_tenant, t["id"])
            )
            t = candidates[0]
            t["status"] = "claimed"
            t["attempts"] += 1
            t["worker_id"] = worker_id
            # Grant a lease; a live worker renews it via heartbeat.
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

    # --- Phase 2 lease / heartbeat / reaper / re-enqueue (task 13.3) -------- #
    def heartbeat(self, tenant_id, task_id, *, lease_ttl=60):
        """Renew a claimed/running lease. Returns True when applicable."""
        t = self.tasks.get(task_id)
        if not t or t["tenant_id"] != tenant_id:
            return False
        if t["status"] not in ("claimed", "running"):
            return False
        t["lease_expires_at"] = self._now + lease_ttl
        t["heartbeat_at"] = self._now
        return True

    def reap_expired_leases(self):
        """Return claimed/running rows whose lease has expired."""
        expired = []
        for t in self.tasks.values():
            if t["status"] in ("claimed", "running") \
                    and t.get("lease_expires_at") is not None \
                    and t["lease_expires_at"] < self._now:
                expired.append({
                    "id": t["id"], "tenant_id": t["tenant_id"],
                    "attempts": t["attempts"], "max_attempts": t["max_attempts"],
                    "status": t["status"],
                    # Context carried so the reaper can emit a correlated task
                    # lifecycle event (Req 6.12).
                    "task_ref": t["task_ref"], "agent_id": t["agent_id"],
                })
        return expired

    def reenqueue_or_finalize(self, tenant_id, task_id, terminal_status, reason=None):
        """Bounded retry: re-enqueue below max_attempts else finalize."""
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


# --------------------------------------------------------------------------- #
# Task 14.3 — re-enqueue / heartbeat renewal / reaper step
# --------------------------------------------------------------------------- #
def test_non_success_terminal_reenqueues_below_max_attempts():
    """A failed attempt below max_attempts returns the task to pending (Req 6.3)."""
    repo = InMemoryTaskRepo()
    repo.submit(1, 10, payload={"prompt": "x"}, max_attempts=2)
    task = repo.claim_next_task("w")  # attempts -> 1, below max 2

    class BoomAdapter(FakeAdapter):
        def execute(self, agent_id, task):
            raise RuntimeError("kaboom")

    events = CapturingEvents()
    out = worker.execute_claimed_task(
        task, adapter_for=lambda a: BoomAdapter(), agent_loader=_agent_loader,
        events_repo=events, repo=repo,
    )
    assert out["status"] == "failed"
    assert out["outcome"] == "reenqueued"
    # Task is back in the pending queue for another attempt.
    assert repo.tasks[task["id"]]["status"] == "pending"
    # The failure event is still emitted even though the task was re-enqueued.
    assert any(e["event_type"] == "task.failed" for e in events.events)


def test_non_success_terminal_finalizes_at_max_attempts():
    """A failed attempt at the max_attempts bound stays failed (Req 6.4)."""
    repo = InMemoryTaskRepo()
    repo.submit(1, 10, payload={"prompt": "x"}, max_attempts=1)
    task = repo.claim_next_task("w")  # attempts -> 1, at max 1

    class BoomAdapter(FakeAdapter):
        def execute(self, agent_id, task):
            raise RuntimeError("kaboom")

    events = CapturingEvents()
    out = worker.execute_claimed_task(
        task, adapter_for=lambda a: BoomAdapter(), agent_loader=_agent_loader,
        events_repo=events, repo=repo,
    )
    assert out["status"] == "failed"
    assert out["outcome"] == "finalized"
    assert repo.tasks[task["id"]]["status"] == "failed"


def test_succeeded_is_never_reenqueued():
    """Success is terminal and recorded directly (no retry path)."""
    repo = InMemoryTaskRepo()
    repo.submit(1, 10, payload={"prompt": "hi"}, max_attempts=3)
    task = repo.claim_next_task("w")
    events = CapturingEvents()
    out = worker.execute_claimed_task(
        task, adapter_for=lambda a: FakeAdapter(), agent_loader=_agent_loader,
        events_repo=events, repo=repo,
    )
    assert out["status"] == "succeeded"
    assert "outcome" not in out  # no reenqueue decision was consulted
    assert repo.tasks[task["id"]]["status"] == "succeeded"


def test_cancel_during_stream_is_never_reenqueued():
    """Cancellation is a user decision and is never re-enqueued."""
    repo = InMemoryTaskRepo()
    repo.submit(1, 10, payload={"prompt": "x"}, max_attempts=3)
    task = repo.claim_next_task("w")
    events = CapturingEvents()
    calls = {"n": 0}

    def probe(task_id):
        calls["n"] += 1
        return calls["n"] > 1

    out = worker.execute_claimed_task(
        task, adapter_for=lambda a: FakeAdapter(), agent_loader=_agent_loader,
        events_repo=events, repo=repo, cancel_probe=probe,
    )
    assert out["status"] == "cancelled"
    assert repo.tasks[task["id"]]["status"] == "cancelled"


def test_heartbeat_renewed_during_streaming():
    """The lease is renewed between stream reads at the heartbeat interval (Req 6.5)."""
    repo = InMemoryTaskRepo()
    repo.submit(1, 10, payload={"prompt": "x"})
    beats = []
    orig_hb = repo.heartbeat

    def spy_hb(tenant_id, task_id, *, lease_ttl=60):
        beats.append((task_id, repo._now))
        return orig_hb(tenant_id, task_id, lease_ttl=lease_ttl)

    repo.heartbeat = spy_hb

    task = repo.claim_next_task("w", lease_ttl=30)

    # Virtual clock driven off the fake repo's ``_now``; each stream read
    # advances it by 15s so with a 10s heartbeat interval every read beats.
    def clock():
        return repo._now

    class _Adapter(FakeAdapter):
        def execute(self, agent_id, t):
            class _Handle:
                def stream(_self):
                    from src.aro.adapters.base import ExecutionChunk
                    for i in range(4):
                        repo.advance(15)
                        yield ExecutionChunk(channel="stdout", data=f"c{i}")

                def cancel(_self):
                    return True

                def result(_self):
                    return ExecutionResult(success=True, returncode=0, output="done")

            return _Handle()

    events = CapturingEvents()
    out = worker.execute_claimed_task(
        task, adapter_for=lambda a: _Adapter(), agent_loader=_agent_loader,
        events_repo=events, repo=repo, lease_ttl=30, heartbeat_interval=10,
        clock=clock,
    )
    assert out["status"] == "succeeded"
    # At least one heartbeat fired during streaming and it extended the lease.
    assert beats, "expected the lease to be renewed during streaming"
    assert repo.tasks[task["id"]]["status"] == "succeeded"


def test_reaper_reclaims_expired_lease_below_max_attempts():
    """The guarded reaper step re-enqueues a dead worker's expired task (Req 6.6)."""
    repo = InMemoryTaskRepo()
    repo.submit(1, 10, payload={"prompt": "x"}, max_attempts=2)
    # A worker claims then dies (no heartbeat); advance past the lease TTL.
    claimed = repo.claim_next_task("dead-worker", lease_ttl=30)
    repo.advance(31)

    events = CapturingEvents()
    w = worker.AgentTaskWorker(
        "reaper", adapter_for=lambda a: FakeAdapter(),
        agent_loader=_agent_loader, events_repo=events, repo=repo,
        clock=lambda: repo._now,
    )
    processed = w.reap_step()
    assert processed == 1
    # attempts (1) < max_attempts (2) → returned to pending.
    assert repo.tasks[claimed["id"]]["status"] == "pending"
    # A re-enqueued reclaim emits a matching task.reclaimed event (Req 6.12),
    # correlated to the task_ref carried on the reap projection.
    reclaimed = [e for e in events.events if e["event_type"] == "task.reclaimed"]
    assert len(reclaimed) == 1
    assert reclaimed[0]["execution_id"] == claimed["task_ref"]


def test_reaper_finalizes_expired_lease_at_max_attempts():
    """At the attempt bound the reaper finalizes the task failed (Req 6.7)."""
    repo = InMemoryTaskRepo()
    repo.submit(1, 10, payload={"prompt": "x"}, max_attempts=1)
    claimed = repo.claim_next_task("dead-worker", lease_ttl=30)  # attempts -> 1
    repo.advance(31)

    events = CapturingEvents()
    w = worker.AgentTaskWorker(
        "reaper", adapter_for=lambda a: FakeAdapter(),
        agent_loader=_agent_loader, events_repo=events, repo=repo,
        clock=lambda: repo._now,
    )
    assert w.reap_step() == 1
    t = repo.tasks[claimed["id"]]
    assert t["status"] == "failed"
    assert t["result"] == {"reason": "lease expired"}
    # A finalized reclaim emits a matching task.failed event with the
    # lease-expiry reason (Req 6.12), correlated to the task_ref.
    failed = [e for e in events.events if e["event_type"] == "task.failed"]
    assert len(failed) == 1
    assert failed[0]["execution_id"] == claimed["task_ref"]
    assert failed[0]["action"].get("reason") == "lease expired"


def test_reaper_never_raises_on_repo_error():
    """A reaper failure is swallowed so the poll loop never dies (Req 6.6)."""
    class BoomRepo(InMemoryTaskRepo):
        def reap_expired_leases(self):
            raise RuntimeError("db down")

    repo = BoomRepo()
    w = worker.AgentTaskWorker(
        "reaper", adapter_for=lambda a: FakeAdapter(),
        agent_loader=_agent_loader, events_repo=CapturingEvents(), repo=repo,
        clock=lambda: repo._now,
    )
    assert w.reap_step() == 0  # no exception escapes


def test_run_once_runs_reaper_before_claim():
    """run_once reaps first so a reclaimed task becomes claimable this cycle."""
    repo = InMemoryTaskRepo()
    repo.submit(1, 10, payload={"prompt": "x"}, max_attempts=2)
    repo.claim_next_task("dead-worker", lease_ttl=30)  # task now claimed, not pending
    repo.advance(31)

    w = worker.AgentTaskWorker(
        "w2", adapter_for=lambda a: FakeAdapter(),
        agent_loader=_agent_loader, events_repo=CapturingEvents(), repo=repo,
        clock=lambda: repo._now,
    )
    # The reaper returns the expired task to pending, then the claim picks it up
    # and it executes to success in a single run_once cycle.
    handled = w.run_once()
    assert handled is True
    assert repo.tasks[1]["status"] == "succeeded"


# --------------------------------------------------------------------------- #
# Task 14.4 — max-in-flight cap + per-tenant fairness claim
# --------------------------------------------------------------------------- #
def test_max_in_flight_default_is_one_and_in_flight_settles_to_zero():
    """Default cap preserves one-at-a-time behavior; in_flight settles to 0."""
    repo = InMemoryTaskRepo()
    repo.submit(1, 10, payload={"prompt": "x"})
    w = worker.AgentTaskWorker(
        "w", adapter_for=lambda a: FakeAdapter(), agent_loader=_agent_loader,
        events_repo=CapturingEvents(), repo=repo, clock=lambda: repo._now,
    )
    assert w.max_in_flight == 1
    assert w.in_flight == 0
    assert w.run_once() is True
    # After a synchronous execution the slot is freed again.
    assert w.in_flight == 0
    assert repo.tasks[1]["status"] == "succeeded"


def test_cap_blocks_claim_while_at_capacity():
    """run_once skips the claim while in_flight >= max_in_flight (Req 6.9)."""
    repo = InMemoryTaskRepo()
    repo.submit(1, 10, payload={"prompt": "x"})
    w = worker.AgentTaskWorker(
        "w", adapter_for=lambda a: FakeAdapter(), agent_loader=_agent_loader,
        events_repo=CapturingEvents(), repo=repo, clock=lambda: repo._now,
    )
    # Simulate a task already in flight at the cap: run_once must NOT claim.
    w.in_flight = w.max_in_flight
    assert w.run_once() is False
    # The pending task was left untouched because no claim happened.
    assert repo.tasks[1]["status"] == "pending"


def test_per_tenant_fairness_rotates_preferred_tenant():
    """Fairness claim rotates across tenants so none is starved (Req 6.10)."""
    repo = InMemoryTaskRepo()
    # Tenant 1 has a deep backlog; tenant 2 has a single task enqueued second.
    repo.submit(1, 10, payload={"prompt": "a"})   # id 1, tenant 1
    repo.submit(1, 10, payload={"prompt": "b"})   # id 2, tenant 1
    repo.submit(2, 20, payload={"prompt": "c"})   # id 3, tenant 2
    repo.submit(1, 10, payload={"prompt": "d"})   # id 4, tenant 1

    served = []

    class _Recorder(InMemoryTaskRepo):
        pass

    # Record which tenant each claim served via last_served progression.
    w = worker.AgentTaskWorker(
        "w", adapter_for=lambda a: FakeAdapter(), agent_loader=_agent_loader,
        events_repo=CapturingEvents(), repo=repo, clock=lambda: repo._now,
    )
    # First claim: last_served is None → lowest tenant (1).
    assert w.run_once() is True
    served.append(w.last_served)
    # Second claim: round-robin advances past tenant 1 → tenant 2 is served
    # even though tenant 1 still has older pending work (no starvation).
    assert w.run_once() is True
    served.append(w.last_served)
    assert served == [1, 2]
    assert repo.tasks[3]["status"] == "succeeded"  # tenant 2's task ran second


def test_fairness_degrades_gracefully_without_pending_tenants_helper():
    """A repo lacking pending_tenants falls back to a plain claim (Req 6.10)."""
    class NoDiscoveryRepo(InMemoryTaskRepo):
        pending_tenants = None  # advertise no discovery helper

    repo = NoDiscoveryRepo()
    repo.submit(1, 10, payload={"prompt": "x"})
    w = worker.AgentTaskWorker(
        "w", adapter_for=lambda a: FakeAdapter(), agent_loader=_agent_loader,
        events_repo=CapturingEvents(), repo=repo, clock=lambda: repo._now,
    )
    assert w.run_once() is True
    assert repo.tasks[1]["status"] == "succeeded"


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
