#!/usr/bin/env python3
"""Property test for the worker's three non-success/interrupted terminal paths.

Feature: phase2-aro-completion, Property 31.

This is the cross-path property (Req 6.12) that ties together the three ways a
task can leave success behind in ``src/aro/agent_worker.py`` and asserts that in
*every* case the task reaches the CORRECT terminal (or bounded re-enqueue) state
AND the MATCHING task lifecycle event is emitted:

* TIMED_OUT — ``execute_claimed_task`` hits the wall-clock deadline mid-stream,
  cancels the handle, lands the ``timed_out`` terminal and emits
  ``task.timed_out`` (Req 6.1/6.2/6.12). Bounded retry still applies: below
  ``max_attempts`` the row returns to ``pending``; at the bound it stays
  ``timed_out``.
* CANCELLED — a cooperative cancel (before or during streaming) lands the
  ``cancelled`` terminal, emits ``task.cancelled`` and is NEVER re-enqueued
  (cancellation is a deliberate user decision) (Req 6.11/6.12).
* RECLAIMED — ``AgentTaskWorker.reap_step()`` reclaims a dead worker's expired
  lease via ``reenqueue_or_finalize`` (Req 6.6/6.7/6.12): below ``max_attempts``
  the row goes back to ``pending`` and emits ``task.reclaimed``; at the bound it
  is finalized ``failed`` with reason ``"lease expired"`` and emits
  ``task.failed``.

The test reuses the ``InMemoryTaskRepo`` + injected ``clock``/``cancel_probe``
patterns (and the reaper harness) from ``tests/test_aro_task_worker.py`` and a
``CapturingEvents`` sink to assert emitted event types. Hypothesis drives which
path to exercise and the relevant params (``max_attempts``, timing); min 100
iterations.

Run directly:
    python3 tests/test_aro_worker_terminal_events.py
Or via pytest:
    pytest tests/test_aro_worker_terminal_events.py
"""
import os
import sys

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
    ExecutionResult,
)

# Reuse the in-memory repo + capturing events sink from the worker unit suite so
# the property test exercises exactly the same claim/lease/reaper contract.
from tests.test_aro_task_worker import (  # noqa: E402
    CapturingEvents,
    InMemoryTaskRepo,
    _agent_loader,
)


# --------------------------------------------------------------------------- #
# A clock-driven adapter whose stream advances the repo's virtual clock so the
# worker's wall-clock deadline can be made to fire deterministically mid-stream,
# and whose stream is long enough to give the cancel_probe a chance to trip.
# --------------------------------------------------------------------------- #
class _ClockAdapter(AgentRuntimeAdapter):
    """Streams ``n_chunks`` chunks, advancing the clock by ``step`` per chunk."""

    adapter_id = "clock-fake"

    def __init__(self, repo, *, step=0.0, n_chunks=5):
        self._repo = repo
        self._step = step
        self._n_chunks = n_chunks

    def get_capabilities(self):
        return list(Capability)

    def install(self, configuration):
        return ExecutionResult(success=True, returncode=0, output="installed")

    def start(self, agent_id, configuration):
        return ExecutionResult(success=True, returncode=0, output="started")

    def stop(self, agent_id):
        return ExecutionResult(success=True, returncode=0, output="stopped")

    def get_status(self, agent_id):
        return "RUNNING"

    def get_logs(self, agent_id, limit=200):
        return ""

    def health_check(self):
        return True

    def execute(self, agent_id, task):
        repo, step, n_chunks = self._repo, self._step, self._n_chunks

        class _Handle:
            def stream(_self):
                for i in range(n_chunks):
                    if step:
                        repo.advance(step)
                    yield ExecutionChunk(channel="stdout", data=f"c{i}")

            def cancel(_self):
                return True

            def result(_self):
                return ExecutionResult(success=True, returncode=0, output="done")

        return _Handle()


def _event_types(events):
    return [e["event_type"] for e in events.events]


# --------------------------------------------------------------------------- #
# Property 31 — correct terminal + matching event across all three paths.
# --------------------------------------------------------------------------- #
@settings(max_examples=200, deadline=None)
@given(
    path=st.sampled_from(["timed_out", "cancelled", "reclaimed"]),
    max_attempts=st.integers(min_value=1, max_value=4),
    # How many claims have already been consumed before the path is driven. This
    # lets us land either below the attempt bound (re-enqueue) or at it
    # (finalize) for the paths where bounded retry applies.
    pre_attempts=st.integers(min_value=0, max_value=4),
    cancel_before_start=st.booleans(),
)
def test_property31_terminal_and_matching_event_across_paths(
    path, max_attempts, pre_attempts, cancel_before_start
):
    """Feature: phase2-aro-completion, Property 31: Timed-out, cancelled, and \
reclaimed tasks reach a correct terminal state with the matching event.

    Validates: Requirements 6.12
    """
    repo = InMemoryTaskRepo()
    tenant_id, agent_id = 1, 10
    submitted = repo.submit(
        tenant_id, agent_id, payload={"prompt": "x"}, max_attempts=max_attempts
    )
    task_id = submitted["id"]

    if path == "timed_out":
        # Claim (attempts -> 1) so the deadline path runs on a live claim.
        task = repo.claim_next_task("w", lease_ttl=1_000_000)
        # The stream advances the virtual clock by 10s per chunk; a 1s budget is
        # reached on the first read so the deadline fires mid-stream.
        task = dict(task, timeout_seconds=1)
        events = CapturingEvents()
        out = worker.execute_claimed_task(
            task,
            adapter_for=lambda a: _ClockAdapter(repo, step=10.0, n_chunks=5),
            agent_loader=_agent_loader,
            events_repo=events,
            repo=repo,
            lease_ttl=1_000_000,
            clock=lambda: repo._now,
        )
        # Correct terminal reported by the worker.
        assert out["status"] == "timed_out"
        # Matching event present, and no cancelled/succeeded leaked in.
        types = _event_types(events)
        assert "task.timed_out" in types
        assert "task.cancelled" not in types
        assert "task.succeeded" not in types
        # Bounded retry: attempts==1. Below the bound -> re-enqueued to pending;
        # at the bound (max_attempts==1) -> finalized timed_out.
        row = repo.tasks[task_id]
        if max_attempts > 1:
            assert out["outcome"] == "reenqueued"
            assert row["status"] == "pending"
        else:
            assert out["outcome"] == "finalized"
            assert row["status"] == "timed_out"

    elif path == "cancelled":
        task = repo.claim_next_task("w", lease_ttl=1_000_000)
        events = CapturingEvents()
        if cancel_before_start:
            # Cancel requested before execution starts.
            repo.request_cancel(tenant_id, task_id)
            probe = None  # falls back to repo.is_cancel_requested
        else:
            # Cancel trips on the second probe (i.e. during streaming): first
            # probe (before start) is False, subsequent probes are True.
            state = {"n": 0}

            def probe(_tid):
                state["n"] += 1
                return state["n"] > 1

        out = worker.execute_claimed_task(
            task,
            adapter_for=lambda a: _ClockAdapter(repo, step=0.0, n_chunks=5),
            agent_loader=_agent_loader,
            events_repo=events,
            repo=repo,
            lease_ttl=1_000_000,
            clock=lambda: repo._now,
            cancel_probe=probe,
        )
        assert out["status"] == "cancelled"
        types = _event_types(events)
        assert "task.cancelled" in types
        assert "task.timed_out" not in types
        assert "task.succeeded" not in types
        # Cancellation is terminal and NEVER re-enqueued, regardless of attempts.
        row = repo.tasks[task_id]
        assert row["status"] == "cancelled"
        assert "outcome" not in out

    else:  # path == "reclaimed"
        # Drive attempts toward the chosen bound by re-claiming the same task
        # repeatedly (each claim increments attempts) and returning it to
        # pending, until the next claim lands the attempt count we want.
        target_attempts = min(max_attempts, 1 + pre_attempts)
        # Consume (target_attempts - 1) attempts before the final claim.
        for _ in range(target_attempts - 1):
            t = repo.claim_next_task("churn", lease_ttl=1_000_000)
            # Return it to pending without finalizing (simulate re-enqueue).
            t_row = repo.tasks[t["id"]]
            t_row["status"] = "pending"
        # Final claim by the "dead" worker; attempts now == target_attempts.
        claimed = repo.claim_next_task("dead-worker", lease_ttl=30)
        assert repo.tasks[task_id]["attempts"] == target_attempts
        # The worker dies (no heartbeat); advance past the lease TTL.
        repo.advance(31)

        events = CapturingEvents()
        w = worker.AgentTaskWorker(
            "reaper",
            adapter_for=lambda a: _ClockAdapter(repo),
            agent_loader=_agent_loader,
            events_repo=events,
            repo=repo,
            clock=lambda: repo._now,
        )
        processed = w.reap_step()
        assert processed == 1

        row = repo.tasks[task_id]
        types = _event_types(events)
        if target_attempts < max_attempts:
            # Below the bound: re-enqueued to pending with a reclaim event.
            assert row["status"] == "pending"
            reclaimed = [e for e in events.events if e["event_type"] == "task.reclaimed"]
            assert len(reclaimed) == 1
            assert reclaimed[0]["execution_id"] == claimed["task_ref"]
            assert "task.failed" not in types
        else:
            # At the bound: finalized failed with the lease-expiry reason.
            assert row["status"] == "failed"
            assert row["result"] == {"reason": "lease expired"}
            failed = [e for e in events.events if e["event_type"] == "task.failed"]
            assert len(failed) == 1
            assert failed[0]["execution_id"] == claimed["task_ref"]
            assert failed[0]["action"].get("reason") == "lease expired"
            assert "task.reclaimed" not in types


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
