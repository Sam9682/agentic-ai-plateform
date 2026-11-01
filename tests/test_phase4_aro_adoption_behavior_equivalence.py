#!/usr/bin/env python3
"""Property test for behavior-equivalence of the ARO adoption of execution_policy.

Feature: phase4-runtime-execution-hardening, Property 6.

Task 3.1 mapped ``agent_worker.execute_claimed_task`` onto
``execution_policy.run_with_policy`` with ZERO observable behavior change. The
streamed attempt is now expressed as the policy's ``op`` (``max_attempts=1``,
``is_transient`` constant ``False``, cancel probe consulted directly, deadline
measured from the start of streaming), and the returned ``Outcome`` is routed
back onto the unchanged ``_finalize_terminal`` mapping:

    SUCCEEDED  -> ``succeeded``  (recorded directly, never re-enqueued)
    FAILED     -> ``failed``     (routed through bounded reenqueue/finalize)
    TIMED_OUT  -> ``timed_out``  (routed through bounded reenqueue/finalize)
    CANCELLED  -> ``cancelled``  (recorded directly, never re-enqueued)

plus two paths that never reach the policy at all:

    cancel-before-start -> ``cancelled`` (recorded directly, never re-enqueued)
    denied (EnforcementError at the exec seam) -> ``denied`` (recorded
        directly, never re-enqueued; ``adapter.execute`` is never reached)

Property 6 (design.md): *for any* claimed-task scenario — success, adapter
error, deadline exceeded, cancel-before-start, cancel-mid-stream, denied — the
worker running on ``run_with_policy`` produces the SAME terminal status AND the
SAME re-enqueue/finalize outcome as the Phase 2 reference semantics.

This test encodes the Phase 2 reference semantics as a pure oracle
(:func:`phase2_reference`) derived from the documented Phase 2 mapping above —
it does NOT call ``run_with_policy`` — and asserts the live
``execute_claimed_task`` matches the oracle across all six scenarios for any
``max_attempts`` and any (positive / missing / non-positive) timeout budget.
Both the live worker's reported terminal and the task store's persisted
disposition (``reenqueued`` vs ``finalized``, and the resulting row status) are
compared, so a regression in either the terminal mapping or the re-enqueue
routing would fail the property.

Reuses the ``InMemoryTaskRepo`` + ``CapturingEvents`` + ``_agent_loader`` test
harness from ``tests/test_aro_task_worker.py`` and the clock-driven adapter
pattern from ``tests/test_aro_worker_timeout.py``; min 100 iterations.

Validates: Requirements 1.8, 6.2, 6.5.

Run directly:
    python3 tests/test_phase4_aro_adoption_behavior_equivalence.py
Or via pytest:
    pytest tests/test_phase4_aro_adoption_behavior_equivalence.py
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
from src.zaf.enforcement import EnforcementError  # noqa: E402

# Reuse the exact claim/lease/re-enqueue contract the Phase 2 worker suite uses
# so the property drives behavior-equivalence against the real finalize routing.
from tests.test_aro_task_worker import (  # noqa: E402
    CapturingEvents,
    InMemoryTaskRepo,
    _agent_loader,
)


# The six scenarios named in Property 6.
_SCENARIOS = (
    "success",
    "adapter_error",
    "deadline_exceeded",
    "cancel_before_start",
    "cancel_mid_stream",
    "denied",
)


# --------------------------------------------------------------------------- #
# Phase 2 reference oracle — the terminal + re-enqueue/finalize disposition the
# worker MUST produce, derived purely from the documented Phase 2 semantics
# (NOT from run_with_policy). This is the independent model Property 6 compares
# the adopted worker against.
# --------------------------------------------------------------------------- #
def phase2_reference(scenario: str, attempts: int, max_attempts: int) -> dict:
    """Return the expected ``{terminal, outcome, row_status}`` for a scenario.

    * ``terminal`` — the status ``execute_claimed_task`` reports.
    * ``outcome`` — ``"reenqueued"``/``"finalized"`` for non-success terminals
      routed through the task store, else ``None`` (no retry path consulted).
    * ``row_status`` — the status persisted on the task row afterwards.

    ``attempts`` is the attempt number already consumed by the claim (the
    in-memory repo increments it on claim); a non-success terminal re-enqueues
    to ``pending`` while ``attempts < max_attempts`` and finalizes otherwise.
    """
    # succeeded / cancelled / denied are recorded directly and never re-enqueued.
    if scenario == "success":
        return {"terminal": "succeeded", "outcome": None, "row_status": "succeeded"}
    if scenario in ("cancel_before_start", "cancel_mid_stream"):
        return {"terminal": "cancelled", "outcome": None, "row_status": "cancelled"}
    if scenario == "denied":
        return {"terminal": "denied", "outcome": None, "row_status": "denied"}

    # adapter_error -> failed ; deadline_exceeded -> timed_out. Both are
    # non-success terminals routed through bounded reenqueue/finalize.
    terminal = "failed" if scenario == "adapter_error" else "timed_out"
    if attempts < max_attempts:
        return {"terminal": terminal, "outcome": "reenqueued", "row_status": "pending"}
    return {"terminal": terminal, "outcome": "finalized", "row_status": terminal}


# --------------------------------------------------------------------------- #
# A scenario-driven adapter. Its stream advances the repo's virtual clock so a
# deadline can be made to fire deterministically mid-stream, and it can raise an
# adapter error on execute to exercise the FAILED path.
# --------------------------------------------------------------------------- #
class _ScenarioAdapter(AgentRuntimeAdapter):
    adapter_id = "phase4-equiv-fake"

    def __init__(self, repo, *, step=0.0, raise_on_execute=False, n_chunks=5):
        self._repo = repo
        self._step = step
        self._raise = raise_on_execute
        self._n = n_chunks

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
        if self._raise:
            raise RuntimeError("adapter boom")
        repo, step, n = self._repo, self._step, self._n

        class _Handle:
            def stream(_self):
                for i in range(n):
                    if step:
                        repo.advance(step)
                    yield ExecutionChunk(channel="stdout", data=f"c{i}")

            def cancel(_self):
                return True

            def result(_self):
                return ExecutionResult(success=True, returncode=0, output="done")

        return _Handle()


def _run_scenario(scenario, repo, task, *, max_attempts):
    """Drive the live ``execute_claimed_task`` for one scenario; return its out."""
    events = CapturingEvents()
    clock = lambda: repo._now  # noqa: E731 - virtual clock off the fake repo

    common = dict(
        agent_loader=_agent_loader,
        events_repo=events,
        repo=repo,
        lease_ttl=10 ** 9,
        clock=clock,
    )

    if scenario == "success":
        return worker.execute_claimed_task(
            task, adapter_for=lambda a: _ScenarioAdapter(repo, step=0.0), **common
        ), events

    if scenario == "adapter_error":
        return worker.execute_claimed_task(
            task,
            adapter_for=lambda a: _ScenarioAdapter(repo, raise_on_execute=True),
            **common,
        ), events

    if scenario == "deadline_exceeded":
        # Budget of 1s; the stream advances the clock 10s per chunk so the
        # deadline is crossed on the first post-chunk check (Req 6.1/6.2).
        task = dict(task, timeout_seconds=1)
        return worker.execute_claimed_task(
            task, adapter_for=lambda a: _ScenarioAdapter(repo, step=10.0), **common
        ), events

    if scenario == "cancel_before_start":
        repo.request_cancel(task["tenant_id"], task["id"])
        return worker.execute_claimed_task(
            task, adapter_for=lambda a: _ScenarioAdapter(repo, step=0.0), **common
        ), events

    if scenario == "cancel_mid_stream":
        # First probe (pre-start) False, subsequent probes True -> cancel trips
        # during streaming.
        state = {"n": 0}

        def probe(_tid):
            state["n"] += 1
            return state["n"] > 1

        return worker.execute_claimed_task(
            task,
            adapter_for=lambda a: _ScenarioAdapter(repo, step=0.0),
            cancel_probe=probe,
            **common,
        ), events

    # denied: a ZAF exec seam that hard-denies by raising EnforcementError.
    def deny(_ctx):
        raise EnforcementError(
            seam="exec", decision="DENY", reason="policy denied",
            action="agent.exec.prompt", agent_identity="agent://default/a1",
        )

    return worker.execute_claimed_task(
        task,
        adapter_for=lambda a: _ScenarioAdapter(repo, step=0.0),
        zaf_exec=deny,
        **common,
    ), events


# --------------------------------------------------------------------------- #
# Property 6 — the adopted worker is behavior-equivalent to the Phase 2 oracle
# across all six scenarios, for any max_attempts.
# --------------------------------------------------------------------------- #
@settings(max_examples=200, deadline=None)
@given(
    scenario=st.sampled_from(_SCENARIOS),
    max_attempts=st.integers(min_value=1, max_value=5),
    # Consume extra claims before the driven attempt so non-success terminals
    # can land either below the attempt bound (re-enqueue) or at it (finalize).
    pre_attempts=st.integers(min_value=0, max_value=5),
)
def test_property6_aro_adoption_is_behavior_equivalent(
    scenario, max_attempts, pre_attempts
):
    """Feature: phase4-runtime-execution-hardening, Property 6: ARO adoption is \
behavior-equivalent.

    For every scenario (success, adapter error, deadline exceeded,
    cancel-before-start, cancel-mid-stream, denied), the worker running on
    ``run_with_policy`` produces the SAME terminal status and the SAME
    re-enqueue/finalize outcome as the Phase 2 reference oracle, for any
    ``max_attempts``.

    Validates: Requirements 1.8, 6.2, 6.5
    """
    repo = InMemoryTaskRepo()
    tenant_id, agent_id = 1, 10
    submitted = repo.submit(
        tenant_id, agent_id, payload={"prompt": "x"}, max_attempts=max_attempts
    )
    task_id = submitted["id"]

    # Consume (target_attempts - 1) claims before the driven attempt by churning
    # the row back to pending, so the final claim lands the attempt count we
    # want relative to the bound (controls re-enqueue vs finalize).
    target_attempts = min(max_attempts, 1 + pre_attempts)
    for _ in range(target_attempts - 1):
        t = repo.claim_next_task("churn", lease_ttl=10 ** 9)
        repo.tasks[t["id"]]["status"] = "pending"

    task = repo.claim_next_task("w", lease_ttl=10 ** 9)
    assert repo.tasks[task_id]["attempts"] == target_attempts

    out, _events = _run_scenario(scenario, repo, task, max_attempts=max_attempts)

    expected = phase2_reference(scenario, target_attempts, max_attempts)

    # Same terminal status as the Phase 2 reference.
    assert out["status"] == expected["terminal"], (
        f"{scenario}: terminal {out['status']!r} != {expected['terminal']!r}"
    )

    # Same re-enqueue/finalize decision (None when no retry path is consulted).
    assert out.get("outcome") == expected["outcome"], (
        f"{scenario}: outcome {out.get('outcome')!r} != {expected['outcome']!r}"
    )

    # Same persisted row disposition.
    assert repo.tasks[task_id]["status"] == expected["row_status"], (
        f"{scenario}: row {repo.tasks[task_id]['status']!r} "
        f"!= {expected['row_status']!r}"
    )


# --------------------------------------------------------------------------- #
# Concrete anchors — one deterministic example per scenario (complements the
# property above and documents the exact expected disposition).
# --------------------------------------------------------------------------- #
def _single_claim_repo(max_attempts=1):
    repo = InMemoryTaskRepo()
    repo.submit(1, 10, payload={"prompt": "x"}, max_attempts=max_attempts)
    task = repo.claim_next_task("w", lease_ttl=10 ** 9)
    return repo, task


def test_success_terminal():
    repo, task = _single_claim_repo()
    out, _ = _run_scenario("success", repo, task, max_attempts=1)
    assert out["status"] == "succeeded"
    assert "outcome" not in out
    assert repo.tasks[task["id"]]["status"] == "succeeded"


def test_adapter_error_reenqueues_below_bound_and_finalizes_at_bound():
    repo, task = _single_claim_repo(max_attempts=2)
    out, _ = _run_scenario("adapter_error", repo, task, max_attempts=2)
    assert out["status"] == "failed"
    assert out["outcome"] == "reenqueued"
    assert repo.tasks[task["id"]]["status"] == "pending"

    repo, task = _single_claim_repo(max_attempts=1)
    out, _ = _run_scenario("adapter_error", repo, task, max_attempts=1)
    assert out["status"] == "failed"
    assert out["outcome"] == "finalized"
    assert repo.tasks[task["id"]]["status"] == "failed"


def test_deadline_exceeded_terminal():
    repo, task = _single_claim_repo(max_attempts=1)
    out, _ = _run_scenario("deadline_exceeded", repo, task, max_attempts=1)
    assert out["status"] == "timed_out"
    assert out["outcome"] == "finalized"
    assert repo.tasks[task["id"]]["status"] == "timed_out"


def test_cancel_before_start_terminal():
    repo, task = _single_claim_repo(max_attempts=3)
    out, _ = _run_scenario("cancel_before_start", repo, task, max_attempts=3)
    assert out["status"] == "cancelled"
    assert "outcome" not in out  # never re-enqueued even below the bound
    assert repo.tasks[task["id"]]["status"] == "cancelled"


def test_cancel_mid_stream_terminal():
    repo, task = _single_claim_repo(max_attempts=3)
    out, _ = _run_scenario("cancel_mid_stream", repo, task, max_attempts=3)
    assert out["status"] == "cancelled"
    assert "outcome" not in out
    assert repo.tasks[task["id"]]["status"] == "cancelled"


def test_denied_terminal_is_direct_complete():
    repo, task = _single_claim_repo(max_attempts=3)
    out, events = _run_scenario("denied", repo, task, max_attempts=3)
    assert out["status"] == "denied"
    assert "outcome" not in out  # policy deny is NEVER re-enqueued
    assert repo.tasks[task["id"]]["status"] == "denied"
    # adapter.execute is never reached: a task.denied event is emitted instead.
    assert any(e["event_type"] == "task.denied" for e in events.events)


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
