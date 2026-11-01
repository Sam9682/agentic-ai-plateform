#!/usr/bin/env python3
"""Property test for the Agent_Worker wall-clock timeout terminal (Task 14.2).

Feature: phase2-aro-completion, Property 23: Timeout always yields the
timed_out terminal.

Validates: Requirements 6.1, 6.2.

``execute_claimed_task`` computes a wall-clock ``deadline = clock() +
timeout_seconds`` at the start of streamed execution and, when the deadline is
reached mid-stream, cancels the ExecutionHandle, drives the attempt to the
``timed_out`` terminal (routed through the task store's
``reenqueue_or_finalize``) and emits a ``task.timed_out`` event (Req 6.1, 6.2).

Property: for an adapter whose stream never completes before the deadline — here
a handle that yields chunks while an injected clock advances past the deadline —
``execute_claimed_task`` ALWAYS yields the ``timed_out`` terminal (status
``"timed_out"``) and ALWAYS emits exactly one ``task.timed_out`` event, for any
positive ``timeout_seconds`` and any ``max_attempts``. With ``max_attempts == 1``
the task finalizes ``timed_out``; with ``attempts < max_attempts`` the store may
re-enqueue the task to ``pending`` — but the ATTEMPT's terminal for the timeout
path is still ``timed_out`` and the ``task.timed_out`` event still fires.

Uses the ``InMemoryTaskRepo`` + injected-clock pattern from
``tests/test_aro_task_worker.py`` (cf. ``test_heartbeat_renewed_during_streaming``
for the clock/handle injection).

Run directly:
    python3 tests/test_aro_worker_timeout.py
Or via pytest:
    pytest tests/test_aro_worker_timeout.py
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
    ExecutionHandle,
    ExecutionResult,
)

# Reuse the in-memory task store + capturing events stub from the worker suite
# so the lease/heartbeat/re-enqueue contract is modeled exactly as elsewhere.
from tests.test_aro_task_worker import (  # noqa: E402
    CapturingEvents,
    InMemoryTaskRepo,
    _agent_loader,
)


class _ClockBox:
    """A tiny mutable virtual clock advanced by the never-completing handle."""

    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:  # used as the injected ``clock`` callable
        return self.now


class _NeverCompletingHandle(ExecutionHandle):
    """A handle whose stream advances the clock past the deadline every read.

    Each yielded chunk advances the injected clock by ``step`` seconds, so no
    matter how large ``timeout_seconds`` is the deadline is always crossed
    mid-stream before the stream would ever end. ``cancel`` records that it was
    invoked (the worker must cancel the handle on the timeout path, Req 6.2).
    ``result`` would only be reached if the stream completed first — on the
    timeout path it never is, so it is a defensive success that, if ever hit,
    would make the property fail loudly rather than silently pass.
    """

    def __init__(self, clock: _ClockBox, step: float, n_chunks: int):
        self._clock = clock
        self._step = step
        self._n = n_chunks
        self.cancelled = False

    def stream(self):
        for i in range(self._n):
            self._clock.now += self._step
            yield ExecutionChunk(channel="stdout", data=f"c{i}")

    def cancel(self) -> bool:
        self.cancelled = True
        return True

    def result(self) -> ExecutionResult:
        # Reaching here means the stream ended before the deadline, which the
        # generator strategy below is constructed to never allow on the timeout
        # path. Return a success so the property assertion would catch a bug.
        return ExecutionResult(success=True, returncode=0, output="completed")


class _TimeoutAdapter(AgentRuntimeAdapter):
    """Adapter returning a never-completing handle (clock crosses the deadline)."""

    adapter_id = "timeout-fake"

    def __init__(self, clock: _ClockBox, step: float, n_chunks: int):
        self._clock = clock
        self._step = step
        self._n = n_chunks
        self.last_handle = None

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

    def execute(self, agent_id, task):
        self.last_handle = _NeverCompletingHandle(self._clock, self._step, self._n)
        return self.last_handle

    def get_logs(self, agent_id, limit=200):
        return ""

    def health_check(self):
        return True


@settings(max_examples=150, deadline=None)
@given(
    # Positive wall-clock budget. The deadline is clock()+timeout_seconds at the
    # start of streaming; the clock starts at 0 so the deadline is exactly this.
    timeout_seconds=st.integers(min_value=1, max_value=600),
    # Vary attempt bound: 1 => the attempt finalizes timed_out; >1 => the store
    # may re-enqueue, but the attempt's terminal is still timed_out.
    max_attempts=st.integers(min_value=1, max_value=5),
    # How much the clock jumps per stream read; the first chunk must already put
    # the clock at/after the deadline, so step >= timeout guarantees a crossing
    # on (or before) the first post-chunk deadline check regardless of budget.
    over=st.integers(min_value=0, max_value=50),
    # A handful of chunks are available, but the deadline is crossed on the
    # first read so the exact count never lets the stream finish first.
    n_chunks=st.integers(min_value=1, max_value=4),
)
def test_timeout_always_yields_timed_out_terminal(
    timeout_seconds, max_attempts, over, n_chunks
):
    """Feature: phase2-aro-completion, Property 23: Timeout always yields the
    timed_out terminal.

    Validates: Requirements 6.1, 6.2.

    For a stream that never completes before the wall-clock deadline, the
    attempt ALWAYS reaches the ``timed_out`` terminal and emits exactly one
    ``task.timed_out`` event, for any positive ``timeout_seconds`` and any
    ``max_attempts``; the ExecutionHandle is cancelled on the timeout path.
    """
    clock = _ClockBox()
    # Step strictly guarantees the deadline (= timeout_seconds) is reached on the
    # first stream read: one jump of (timeout_seconds + over) lands at/after it.
    step = timeout_seconds + over
    adapter = _TimeoutAdapter(clock, step=step, n_chunks=n_chunks)

    repo = InMemoryTaskRepo()
    repo.submit(1, 10, payload={"prompt": "x"}, max_attempts=max_attempts)
    # Claim with a generous lease so heartbeat/reaper never interferes with the
    # deadline path (the clock we advance drives the deadline, not the lease).
    task = repo.claim_next_task("w", lease_ttl=10 ** 9)
    # The wall-clock budget the worker enforces is read from the task's
    # ``timeout_seconds`` (Req 6.1). The in-memory submit helper does not carry
    # it, so attach it to the claimed task the worker executes.
    task["timeout_seconds"] = timeout_seconds
    events = CapturingEvents()

    out = worker.execute_claimed_task(
        task,
        adapter_for=lambda a: adapter,
        agent_loader=_agent_loader,
        events_repo=events,
        repo=repo,
        lease_ttl=10 ** 9,
        clock=clock,
    )

    # The attempt's terminal is always timed_out (Req 6.2).
    assert out["status"] == "timed_out"
    # The handle was cancelled on the timeout path (Req 6.2).
    assert adapter.last_handle is not None and adapter.last_handle.cancelled is True
    # Exactly one task.timed_out event fired (Req 6.2 / 6.12).
    timed_out_events = [
        e for e in events.events if e["event_type"] == "task.timed_out"
    ]
    assert len(timed_out_events) == 1

    # The store's terminal disposition depends only on the attempt bound:
    #  * at the bound (attempts == max_attempts) the task finalizes timed_out;
    #  * below the bound the store re-enqueues the attempt to pending (Req 6.3/6.4)
    #    while the attempt itself remained a timed_out terminal.
    stored = repo.tasks[task["id"]]
    if max_attempts == 1:
        assert stored["status"] == "timed_out"
    else:
        assert stored["status"] == "pending"
        assert out.get("outcome") == "reenqueued"


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
