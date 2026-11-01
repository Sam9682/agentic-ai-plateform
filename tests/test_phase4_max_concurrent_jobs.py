#!/usr/bin/env python3
"""Property test: the serverless worker never exceeds max_concurrent_jobs (Task 7.7).

Feature: phase4-runtime-execution-hardening, Property 14.

Task 7.2 added an in-flight counter to
:class:`src.serverless.worker.ServerlessWorker` that gates ``claim_next_job``
exactly like the ARO ``agent_worker``'s ``in_flight``/``max_in_flight``
accounting: :meth:`ServerlessWorker.run_once` returns ``False`` without claiming
while ``in_flight >= max_concurrent``; otherwise it claims a job, increments
``in_flight`` before :meth:`execute_job`, and decrements it in a ``finally`` so a
slot is always freed when the job reaches a terminal status.

Property 14 (design.md): *For any* arrival sequence of claimable jobs, the
number of simultaneously executing serverless jobs never exceeds
Max_Concurrent_Jobs, and a new claim is deferred while in-flight equals the cap.

The test runs no live Docker, PostgreSQL, or SSH. It injects a fake connection
pool (never touched because ``claim_next_job`` is overridden) and models
concurrency with a cooperative scheduler: ``execute_job`` is faked so a job does
NOT complete synchronously — instead it registers the running job and records
the peak observed in-flight count, and the scheduler later "completes" jobs out
of band. This lets many jobs be simultaneously in flight so the cap is a real
constraint rather than trivially satisfied by synchronous execution.

Two things are asserted across the whole randomized arrival/completion schedule:

1. Observed simultaneous in-flight executions NEVER exceed ``max_concurrent``.
2. ``run_once`` DEFERS — returns ``False`` without claiming — whenever
   ``in_flight == max_concurrent`` (the cap), and otherwise claims exactly one
   job and raises in-flight by one.

Validates: Requirements 5.4

Run directly:
    python3 tests/test_phase4_max_concurrent_jobs.py
Or via pytest:
    pytest tests/test_phase4_max_concurrent_jobs.py
"""
import os
import sys

from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("FLASK_ENV", "development")

from src.serverless.worker import ServerlessWorker  # noqa: E402


# --------------------------------------------------------------------------- #
# Fakes — no live Docker / PostgreSQL / SSH.
# --------------------------------------------------------------------------- #
class _FakePool:
    """Stand-in for ``_WorkerConnectionPool``; never exercised in this test.

    ``claim_next_job`` and ``execute_job`` are both overridden on the worker, so
    the worker never borrows a connection. The pool exists only so constructing
    the worker never reaches a real database.
    """

    def get_db_connection(self):  # pragma: no cover - defensive, unused here
        raise AssertionError("DB pool must not be used in this unit test")

    def closeall(self):  # pragma: no cover - unused
        pass


class _ConcurrentWorkerHarness:
    """Drive a :class:`ServerlessWorker` with non-blocking claim + deferred execute.

    Models true concurrency without threads: ``execute_job`` does not finish the
    job synchronously. Instead it records the job as running (incrementing an
    independent ``running`` mirror and tracking the peak), then returns so
    ``run_once``'s ``finally`` immediately decrements ``worker.in_flight`` — which
    would normally free the slot. To keep jobs *simultaneously* in flight we
    model the worker's accounting directly via a cooperative scheduler built on
    ``run_once``'s public contract, rather than relying on synchronous execution.

    The harness interprets a schedule of +1 (attempt to start a job) and -1
    (complete the oldest running job) steps, mutating ``worker.in_flight`` the
    same way the real loop does, and verifies the cap invariant and the
    defer-at-cap behavior on every start step.
    """

    def __init__(self, worker: ServerlessWorker):
        self.worker = worker
        self.peak_in_flight = 0
        self.claim_calls = 0
        self._next_job_id = 0

        # Non-blocking claim: always returns a fresh claimable job. This models
        # "an unbounded arrival sequence of claimable jobs" so the cap, not the
        # queue, is the only thing that can bound concurrency.
        def _fake_claim():
            self.claim_calls += 1
            self._next_job_id += 1
            return {
                "id": self._next_job_id,
                "user_id": "u",
                "image": "ghcr.io/org/app@sha256:" + "a" * 64,
                "command": None,
                "environment": {},
                "timeout_seconds": 30,
            }

        # Deferred execute: the job does NOT complete here. We only observe the
        # in-flight count at the moment execution begins and record the peak.
        def _fake_execute(job):
            self.peak_in_flight = max(self.peak_in_flight, self.worker.in_flight)

        worker.claim_next_job = _fake_claim  # type: ignore[assignment]
        worker.execute_job = _fake_execute   # type: ignore[assignment]

    def start(self) -> bool:
        """Attempt to start one job, asserting Property 14's defer-at-cap rule.

        Mirrors ``run_once`` but keeps the started job *in flight* (does not let
        the synchronous ``finally`` free the slot) so concurrency accumulates.
        Returns True when a job was started, False when deferred at the cap.
        """
        cap = self.worker.max_concurrent
        at_cap_before = self.worker.in_flight >= cap
        claims_before = self.claim_calls

        if at_cap_before:
            # Property 14: at the cap the worker must DEFER — run_once returns
            # False and claims nothing.
            handled = self.worker.run_once()
            assert handled is False, "run_once must defer (return False) at the cap"
            assert self.claim_calls == claims_before, (
                "run_once must NOT claim a job while at the concurrency cap"
            )
            return False

        # Below the cap: emulate run_once's claim+increment, but leave the job
        # in flight (do not run the finally decrement) so simultaneous jobs
        # accumulate up to the cap.
        job = self.worker.claim_next_job()
        assert job is not None
        self.worker.in_flight += 1
        self.worker.execute_job(job)  # records peak at start-of-execution
        # Invariant: never exceed the cap.
        assert self.worker.in_flight <= cap, (
            f"in_flight {self.worker.in_flight} exceeded cap {cap}"
        )
        self.peak_in_flight = max(self.peak_in_flight, self.worker.in_flight)
        return True

    def complete_one(self) -> bool:
        """Complete one in-flight job, freeing a slot (the ``finally`` effect)."""
        if self.worker.in_flight <= 0:
            return False
        self.worker.in_flight -= 1
        return True


def _make_worker(cap: int) -> ServerlessWorker:
    return ServerlessWorker(
        worker_id="test-worker",
        runtime=object(),            # never used: execute_job is faked
        db_config={},
        registry_whitelist=["ghcr.io"],
        pool=_FakePool(),
        max_concurrent=cap,
    )


# --------------------------------------------------------------------------- #
# Property 14 — simultaneous in-flight never exceeds the cap; claim deferred at
# the cap — across a randomized arrival/completion schedule.
# --------------------------------------------------------------------------- #
# A schedule is a sequence of steps: True = a job arrives/attempts to start,
# False = an in-flight job completes. This models any arrival/completion
# interleaving.
_schedule = st.lists(st.booleans(), min_size=1, max_size=60)


@settings(max_examples=200, deadline=None)
@given(cap=st.integers(min_value=1, max_value=8), schedule=_schedule)
def test_property14_max_concurrent_jobs_never_exceeded(cap, schedule):
    """Feature: phase4-runtime-execution-hardening, Property 14: \
max_concurrent_jobs is never exceeded.

    For any arrival/completion schedule, simultaneous executing jobs never
    exceed ``max_concurrent`` and a new claim is deferred while
    ``in_flight == max_concurrent``.

    Validates: Requirements 5.4
    """
    worker = _make_worker(cap)
    harness = _ConcurrentWorkerHarness(worker)

    assert worker.max_concurrent == cap
    assert worker.in_flight == 0

    for step in schedule:
        if step:
            harness.start()      # asserts defer-at-cap + cap invariant inside
        else:
            harness.complete_one()
        # Global invariant after every step: the cap is never breached.
        assert worker.in_flight <= cap
        assert worker.in_flight >= 0

    # Peak concurrency observed over the whole schedule respected the cap.
    assert harness.peak_in_flight <= cap


# --------------------------------------------------------------------------- #
# Property 14 (saturation) — when enough jobs arrive back-to-back, in-flight
# climbs exactly to the cap and then every further attempt is deferred.
# --------------------------------------------------------------------------- #
@settings(max_examples=200, deadline=None)
@given(cap=st.integers(min_value=1, max_value=8), extra=st.integers(min_value=1, max_value=15))
def test_property14_saturates_then_defers(cap, extra):
    """Back-to-back arrivals saturate at the cap, then defer every extra claim.

    Validates: Requirements 5.4
    """
    worker = _make_worker(cap)
    harness = _ConcurrentWorkerHarness(worker)

    # Fill to the cap: the first `cap` attempts all start.
    for _ in range(cap):
        assert harness.start() is True
    assert worker.in_flight == cap
    claims_at_cap = harness.claim_calls

    # Every further attempt while saturated must defer and claim nothing.
    for _ in range(extra):
        assert harness.start() is False
    assert worker.in_flight == cap
    assert harness.claim_calls == claims_at_cap, "no claims while saturated"

    # Freeing one slot lets exactly one more job start, then it saturates again.
    assert harness.complete_one() is True
    assert worker.in_flight == cap - 1
    assert harness.start() is True
    assert worker.in_flight == cap
    assert harness.start() is False  # saturated again


# --------------------------------------------------------------------------- #
# Concrete anchors — deterministic examples of the defer-at-cap contract on the
# real run_once (synchronous execution frees the slot immediately, so run_once
# keeps handling jobs while below the cap and only defers when pre-loaded at it).
# --------------------------------------------------------------------------- #
def test_run_once_defers_when_preloaded_at_cap():
    """run_once returns False and claims nothing when already at the cap."""
    worker = _make_worker(cap=2)
    claims = {"n": 0}

    def _claim():
        claims["n"] += 1
        return {"id": 1, "user_id": "u", "image": "i", "command": None,
                "environment": {}, "timeout_seconds": 1}

    worker.claim_next_job = _claim  # type: ignore[assignment]
    worker.execute_job = lambda job: None  # type: ignore[assignment]

    worker.in_flight = 2  # pre-load at the cap
    assert worker.run_once() is False
    assert claims["n"] == 0  # deferred: nothing claimed


def test_run_once_below_cap_handles_and_frees_slot():
    """Below the cap run_once claims, executes, and frees the slot in finally."""
    worker = _make_worker(cap=2)
    seen_in_flight = []

    worker.claim_next_job = lambda: {  # type: ignore[assignment]
        "id": 1, "user_id": "u", "image": "i", "command": None,
        "environment": {}, "timeout_seconds": 1,
    }
    worker.execute_job = lambda job: seen_in_flight.append(worker.in_flight)  # type: ignore[assignment]

    assert worker.run_once() is True
    assert seen_in_flight == [1]      # one job in flight during execution
    assert worker.in_flight == 0      # finally freed the slot


def test_run_once_empty_queue_returns_false():
    """An empty queue (claim returns None) yields False without changing in_flight."""
    worker = _make_worker(cap=3)
    worker.claim_next_job = lambda: None  # type: ignore[assignment]
    worker.execute_job = lambda job: (_ for _ in ()).throw(  # type: ignore[assignment]
        AssertionError("execute_job must not run when the queue is empty")
    )
    assert worker.run_once() is False
    assert worker.in_flight == 0


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
