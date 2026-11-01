#!/usr/bin/env python3
"""Property test for the worker max-in-flight cap (Phase 2 ARO, Task 14.5).

Feature: phase2-aro-completion, Property 28.

Exercises the max-in-flight concurrency cap enforced by
``AgentTaskWorker.run_once`` in ``src/aro/agent_worker.py`` (Req 6.9). The
worker tracks an ``in_flight`` counter and a ``max_in_flight`` cap; while
``in_flight >= max_in_flight`` ``run_once`` skips claiming entirely (returns
``False`` and never consults ``claim_next_task``), leaving any pending task
untouched. Below the cap ``run_once`` claims and executes a task.

Because the executor is synchronous (``execute_claimed_task`` runs a claimed
task to a terminal status before returning), the worker cannot naturally hold
more than one task in flight at a time. The documented, observable way to
simulate occupancy is to set ``worker.in_flight`` directly — the increment /
decrement around the synchronous execution is exactly what makes the cap
enforceable and testable.

Property 28 (cap blocks new claims): for an arbitrary cap ``C`` and an
arbitrary ``in_flight`` level ``k``:
  * when ``k >= C`` the worker does NOT claim — ``run_once()`` is ``False``,
    the pending task's status is unchanged (``pending``), and the claim path is
    never consulted;
  * when ``k < C`` the worker DOES claim — ``run_once()`` is ``True`` and the
    pending task is claimed and executed to a terminal status.

Validates: Requirements 6.9

Run directly:
    python3 tests/test_aro_worker_max_in_flight.py
Or via pytest:
    pytest tests/test_aro_worker_max_in_flight.py -v
"""
import os
import sys

from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.aro import agent_worker as worker  # noqa: E402
from src.aro.adapters.base import FakeAdapter  # noqa: E402

# Reuse the in-memory task store and agent loader that the worker suite models
# the claim + completion contract with (tests/test_aro_task_worker.py pattern).
from tests.test_aro_task_worker import (  # noqa: E402
    InMemoryTaskRepo,
    CapturingEvents,
    _agent_loader,
)


class _ClaimSpyRepo(InMemoryTaskRepo):
    """InMemoryTaskRepo that records every ``claim_next_task`` call so the test
    can assert that at capacity the claim path is never consulted (Req 6.9)."""

    def __init__(self):
        super().__init__()
        self.claim_calls = 0

    def claim_next_task(self, worker_id, *, lease_ttl=60, preferred_tenant=None):
        self.claim_calls += 1
        return super().claim_next_task(
            worker_id, lease_ttl=lease_ttl, preferred_tenant=preferred_tenant
        )


@settings(max_examples=200, deadline=None)
@given(
    cap=st.integers(min_value=1, max_value=16),
    in_flight=st.integers(min_value=0, max_value=32),
)
def test_at_capacity_blocks_claim_below_capacity_claims(cap, in_flight):
    """For an arbitrary cap C and occupancy k: k >= C does NOT claim (pending
    task untouched, claim path never consulted); k < C DOES claim and execute.

    Feature: phase2-aro-completion, Property 28.
    Validates: Requirements 6.9
    """
    repo = _ClaimSpyRepo()
    repo.submit(1, 10, payload={"prompt": "x"})

    w = worker.AgentTaskWorker(
        "w",
        adapter_for=lambda a: FakeAdapter(),
        agent_loader=_agent_loader,
        events_repo=CapturingEvents(),
        repo=repo,
        max_in_flight=cap,
        clock=lambda: repo._now,
    )
    assert w.max_in_flight == cap

    # Simulate the worker already holding ``in_flight`` tasks (the documented
    # observable since the synchronous executor can't naturally hold >1).
    w.in_flight = in_flight

    handled = w.run_once()

    if in_flight >= cap:
        # At/over capacity: no claim happened and the pending task is untouched.
        assert handled is False
        assert repo.claim_calls == 0
        assert repo.tasks[1]["status"] == "pending"
        # The cap did not corrupt the in-flight accounting.
        assert w.in_flight == in_flight
    else:
        # Below capacity: the worker claimed and executed the task to a
        # terminal status and the slot was freed again afterwards.
        assert handled is True
        assert repo.claim_calls == 1
        assert repo.tasks[1]["status"] == "succeeded"
        assert w.in_flight == in_flight


@settings(max_examples=200, deadline=None)
@given(
    cap=st.integers(min_value=1, max_value=16),
    over=st.integers(min_value=0, max_value=16),
)
def test_exactly_at_or_above_cap_never_claims(cap, over):
    """Occupancy exactly at the cap (and any amount above it) never claims and
    never touches the pending task.

    Feature: phase2-aro-completion, Property 28.
    Validates: Requirements 6.9
    """
    repo = _ClaimSpyRepo()
    repo.submit(1, 10, payload={"prompt": "x"})

    w = worker.AgentTaskWorker(
        "w",
        adapter_for=lambda a: FakeAdapter(),
        agent_loader=_agent_loader,
        events_repo=CapturingEvents(),
        repo=repo,
        max_in_flight=cap,
        clock=lambda: repo._now,
    )
    w.in_flight = cap + over  # at the cap (over=0) or strictly above it

    assert w.run_once() is False
    assert repo.claim_calls == 0
    assert repo.tasks[1]["status"] == "pending"


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([os.path.abspath(__file__), "-v"]))
