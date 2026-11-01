#!/usr/bin/env python3
"""Integration-style tests for the OBS detection step wired into the worker loop.

Feature: phase5-obs-supervisor (Task 5.2).

These tests exercise the LIVE Phase 2 worker poll loop (``AgentTaskWorker`` +
``run_once`` + the top-level ``run`` handler) with the Phase 5 detection pass
injected as a collaborator, so they are integration-style rather than pure unit
tests (R14.6): they verify the ordering and failure-propagation behavior of the
wired loop, not an isolated pure function.

What is validated:

* **Ordering (R1.7)** — ``_maybe_detect`` (deterministic OBS detection) runs
  BEFORE any later scoring / claim step within a single ``run_once`` cycle. A
  shared recording list captures the call order: the injected
  ``detection_pass.run_cycle`` appends ``"detect"`` and the repo's
  ``claim_next_task`` (the next step that would feed ML scoring / execution)
  appends ``"claim"``; detection must come first.

* **Failure propagation (R1.8)** — when ``detection_pass.run_cycle`` raises a
  ``DetectionError``, it propagates OUT of ``run_once`` (not swallowed) and the
  top-level ``run`` loop RE-RAISES it rather than treating the cycle as a normal
  empty poll, so enforcement is never left silently disabled. This deliberately
  contrasts with ``reap_step``, which swallows to keep the loop alive.

* **Backward compatibility** — with ``detection_pass=None`` (the default),
  ``run_once`` behaves exactly as before: no detection side effects and the
  claimed task still executes to success.

Run directly:
    python3 tests/test_phase5_worker_detect_ordering.py
Or via pytest:
    pytest tests/test_phase5_worker_detect_ordering.py -q
"""
import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.aro import agent_worker as worker  # noqa: E402
from src.aro.adapters.base import FakeAdapter  # noqa: E402
from src.obs.detection_pass import DetectionError  # noqa: E402

# Mark the whole module as integration where it exercises the live worker loop.
pytestmark = pytest.mark.integration


class CapturingEvents:
    def __init__(self):
        self.events = []

    def append_event(self, event):
        self.events.append(event)
        return dict(event, id=len(self.events))


class RecordingTaskRepo:
    """Minimal in-memory task store that records when a claim happens.

    The ``order`` list is shared with the fake detection pass so the test can
    assert the relative call order of detection vs. the claim within one
    ``run_once`` cycle. Only the methods the worker actually calls are
    implemented; a single pending task is claimed exactly once then executed.
    """

    def __init__(self, order):
        self._order = order
        self.tasks = {}
        self._id = 1
        self._now = 0.0

    def submit(self, tenant_id, agent_id, *, payload=None, **kw):
        tid = self._id
        self._id += 1
        t = dict(
            id=tid, tenant_id=tenant_id, agent_id=agent_id, task_ref=f"task-{tid}",
            operation=kw.get("operation", "prompt"), payload=payload or {},
            status="pending", cancel_requested=False, attempts=0,
            max_attempts=kw.get("max_attempts", 1), result=None,
        )
        self.tasks[tid] = t
        return dict(t)

    def pending_tenants(self):
        counts = {}
        for t in self.tasks.values():
            if t["status"] == "pending" and not t["cancel_requested"]:
                counts[t["tenant_id"]] = counts.get(t["tenant_id"], 0) + 1
        return counts

    def claim_next_task(self, worker_id, *, lease_ttl=60, preferred_tenant=None):
        # Record the claim step — the point past which execution / ML scoring
        # would proceed. It must be observed AFTER detection (R1.7).
        self._order.append("claim")
        candidates = [
            t for t in self.tasks.values()
            if t["status"] == "pending" and not t["cancel_requested"]
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda t: (t["tenant_id"] != preferred_tenant, t["id"]))
        t = candidates[0]
        t["status"] = "claimed"
        t["attempts"] += 1
        t["worker_id"] = worker_id
        t["lease_expires_at"] = self._now + lease_ttl
        t["heartbeat_at"] = self._now
        return dict(t)

    def mark_running(self, tenant_id, task_id):
        self.tasks[task_id]["status"] = "running"
        return True

    def complete(self, tenant_id, task_id, status, result=None):
        t = self.tasks[task_id]
        t["status"] = status
        t["result"] = result
        return True

    def heartbeat(self, tenant_id, task_id, *, lease_ttl=60):
        t = self.tasks.get(task_id)
        if not t or t["status"] not in ("claimed", "running"):
            return False
        t["lease_expires_at"] = self._now + lease_ttl
        return True

    def is_cancel_requested(self, task_id):
        return bool(self.tasks.get(task_id, {}).get("cancel_requested"))


class RecordingDetectionPass:
    """Fake Detection_Pass whose run_cycle records the call order (R1.7)."""

    def __init__(self, order):
        self._order = order
        self.calls = 0

    def run_cycle(self):
        self.calls += 1
        self._order.append("detect")
        return []


class RaisingDetectionPass:
    """Fake Detection_Pass whose run_cycle raises DetectionError (R1.8)."""

    def __init__(self):
        self.calls = 0

    def run_cycle(self):
        self.calls += 1
        raise DetectionError("detection cycle failed")


def _agent_loader(tenant_id, agent_id):
    return {"id": agent_id, "tenant_id": tenant_id, "identity": "agent://default/a1"}


# --------------------------------------------------------------------------- #
# (1) Ordering: detection runs BEFORE the claim / ML scoring step (R1.7)
# --------------------------------------------------------------------------- #
def test_detection_runs_before_claim_within_a_cycle():
    order = []
    repo = RecordingTaskRepo(order)
    repo.submit(1, 10, payload={"prompt": "hello"})
    detection = RecordingDetectionPass(order)

    w = worker.AgentTaskWorker(
        "w", adapter_for=lambda a: FakeAdapter(), agent_loader=_agent_loader,
        events_repo=CapturingEvents(), repo=repo, clock=lambda: repo._now,
        detection_pass=detection,
    )

    handled = w.run_once()

    assert handled is True
    # Detection ran exactly once this cycle, and it ran BEFORE the claim step
    # (which precedes any ML scoring / execution) — R1.7.
    assert detection.calls == 1
    assert order[0] == "detect"
    assert "claim" in order
    assert order.index("detect") < order.index("claim")
    # The task still executed to success after detection.
    assert repo.tasks[1]["status"] == "succeeded"


def test_detection_runs_even_when_at_capacity_before_claim_is_skipped():
    """Detection runs before the in-flight cap check, so it fires even when the
    worker is at capacity and skips the claim entirely (R1.7)."""
    order = []
    repo = RecordingTaskRepo(order)
    repo.submit(1, 10, payload={"prompt": "x"})
    detection = RecordingDetectionPass(order)

    w = worker.AgentTaskWorker(
        "w", adapter_for=lambda a: FakeAdapter(), agent_loader=_agent_loader,
        events_repo=CapturingEvents(), repo=repo, clock=lambda: repo._now,
        detection_pass=detection,
    )
    # Simulate being at capacity so the claim is skipped.
    w.in_flight = w.max_in_flight

    handled = w.run_once()

    assert handled is False  # no claim happened (at capacity)
    assert detection.calls == 1  # detection still ran first
    assert order == ["detect"]  # claim was never reached
    assert repo.tasks[1]["status"] == "pending"


# --------------------------------------------------------------------------- #
# (2) Failure propagation: a DetectionError is raised, never swallowed (R1.8)
# --------------------------------------------------------------------------- #
def test_detection_error_propagates_out_of_run_once():
    order = []
    repo = RecordingTaskRepo(order)
    repo.submit(1, 10, payload={"prompt": "x"})
    detection = RaisingDetectionPass()

    w = worker.AgentTaskWorker(
        "w", adapter_for=lambda a: FakeAdapter(), agent_loader=_agent_loader,
        events_repo=CapturingEvents(), repo=repo, clock=lambda: repo._now,
        detection_pass=detection,
    )

    with pytest.raises(DetectionError):
        w.run_once()

    assert detection.calls == 1
    # The failure happened before the claim: enforcement off must stop the
    # cycle, not let it proceed to claim/execute (R1.8).
    assert "claim" not in order
    assert repo.tasks[1]["status"] == "pending"


def test_run_loop_reraises_detection_error_instead_of_treating_as_empty():
    """The top-level run handler re-raises a DetectionError rather than
    swallowing it as a normal empty poll cycle (R1.8)."""
    order = []
    repo = RecordingTaskRepo(order)
    repo.submit(1, 10, payload={"prompt": "x"})
    detection = RaisingDetectionPass()

    w = worker.AgentTaskWorker(
        "w", adapter_for=lambda a: FakeAdapter(), agent_loader=_agent_loader,
        events_repo=CapturingEvents(), repo=repo, clock=lambda: repo._now,
        detection_pass=detection,
    )
    w.running = True

    with pytest.raises(DetectionError):
        w.run()

    assert detection.calls == 1


# --------------------------------------------------------------------------- #
# (3) Backward compatibility: detection_pass=None behaves exactly as before
# --------------------------------------------------------------------------- #
def test_no_detection_pass_is_inert_and_backward_compatible():
    order = []
    repo = RecordingTaskRepo(order)
    repo.submit(1, 10, payload={"prompt": "hi"})

    w = worker.AgentTaskWorker(
        "w", adapter_for=lambda a: FakeAdapter(), agent_loader=_agent_loader,
        events_repo=CapturingEvents(), repo=repo, clock=lambda: repo._now,
    )

    handled = w.run_once()

    assert handled is True
    # No detection side effect: the only recorded step is the claim.
    assert "detect" not in order
    assert order == ["claim"]
    assert repo.tasks[1]["status"] == "succeeded"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
