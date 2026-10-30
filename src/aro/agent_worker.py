"""Agent task worker (Task 10).

Polls the ``agent_tasks`` queue, claims tasks atomically, executes them through
the agent's runtime adapter, streams output, and records terminal status —
modeled on ``src/serverless/worker.py`` (claim + poll + cancel + timeout).

The execution of a single claimed task is factored into
:func:`execute_claimed_task`, which depends only on injected collaborators
(task repo, an adapter resolver, an events repo and a cancel probe) so it is
unit-testable without a live DB, SSH or a real runtime. Retry is handled by
re-enqueue semantics via ``attempts``/``max_attempts``.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, Optional

from . import event_service as es
from . import task_repository as task_repo


def execute_claimed_task(
    task: Dict[str, Any],
    *,
    adapter_for: Callable[[Dict[str, Any]], Any],
    agent_loader: Callable[[int, int], Optional[Dict[str, Any]]],
    events_repo,
    repo=task_repo,
    cancel_probe: Optional[Callable[[int], bool]] = None,
) -> Dict[str, Any]:
    """Execute one claimed task to a terminal status; return the terminal dict.

    Streams the adapter's execution, honoring cancellation (checked before and
    during streaming). On adapter error the task is marked failed; if attempts
    remain (< max_attempts) the caller may re-enqueue. Emits task lifecycle
    events (received, completed/failed/cancelled).
    """
    tenant_id = task["tenant_id"]
    task_id = task["id"]
    agent = agent_loader(tenant_id, task["agent_id"])
    if agent is None:
        repo.complete(task_id, "failed", {"error": "agent not found"})
        return {"status": "failed", "error": "agent not found"}

    corr = f"task-{task['task_ref']}"
    es.emit(events_repo, tenant_id, "task.received", "worker",
            agent_id=agent["identity"], execution_id=task["task_ref"],
            action={"operation": task["operation"]}, correlation_id=corr)

    cancel_probe = cancel_probe or repo.is_cancel_requested
    if cancel_probe(task_id):
        repo.complete(task_id, "cancelled", {"error": "cancelled before start"})
        es.emit(events_repo, tenant_id, "task.cancelled", "worker",
                agent_id=agent["identity"], execution_id=task["task_ref"], correlation_id=corr)
        return {"status": "cancelled"}

    repo.mark_running(task_id)
    adapter = adapter_for(agent)
    collected = []
    try:
        handle = adapter.execute(agent["identity"], task.get("payload") or {})
        for chunk in handle.stream():
            if chunk.channel in ("stdout", "stderr") and chunk.data:
                collected.append(chunk.data)
            if cancel_probe(task_id):
                handle.cancel()
                repo.complete(task_id, "cancelled", {"output": "".join(collected)})
                es.emit(events_repo, tenant_id, "task.cancelled", "worker",
                        agent_id=agent["identity"], execution_id=task["task_ref"], correlation_id=corr)
                return {"status": "cancelled", "output": "".join(collected)}
        result = handle.result()
    except Exception as exc:  # noqa: BLE001 - adapter errors are terminal for the attempt
        repo.complete(task_id, "failed", {"error": f"{type(exc).__name__}: {exc}"})
        es.emit(events_repo, tenant_id, "task.failed", "worker",
                agent_id=agent["identity"], execution_id=task["task_ref"],
                action={"error": str(exc)}, severity="MEDIUM", correlation_id=corr)
        return {"status": "failed", "error": str(exc)}

    status = "succeeded" if result.success else "failed"
    repo.complete(task_id, status, result.as_dict())
    es.emit(events_repo, tenant_id, f"task.{status}", "worker",
            agent_id=agent["identity"], execution_id=task["task_ref"],
            action={"returncode": result.returncode},
            severity="INFO" if result.success else "MEDIUM", correlation_id=corr)
    return {"status": status, "output": result.output}


class AgentTaskWorker:
    """Blocking poll loop claiming and executing agent tasks."""

    def __init__(
        self,
        worker_id: str,
        *,
        adapter_for: Callable[[Dict[str, Any]], Any],
        agent_loader: Callable[[int, int], Optional[Dict[str, Any]]],
        events_repo=None,
        poll_interval: float = 1.0,
        repo=task_repo,
    ):
        self.worker_id = worker_id
        self._adapter_for = adapter_for
        self._agent_loader = agent_loader
        if events_repo is None:
            from . import events_repository as _er
            events_repo = _er
        self._events = events_repo
        self._poll_interval = poll_interval
        self._repo = repo
        self.running = False

    def run_once(self) -> bool:
        """Claim and execute a single task. Returns True when one was handled."""
        task = self._repo.claim_next_task(self.worker_id)
        if task is None:
            return False
        execute_claimed_task(
            task,
            adapter_for=self._adapter_for,
            agent_loader=self._agent_loader,
            events_repo=self._events,
            repo=self._repo,
        )
        return True

    def run(self) -> None:  # pragma: no cover - long-running loop
        self.running = True
        while self.running:
            try:
                handled = self.run_once()
            except Exception:  # noqa: BLE001 - never let the loop die
                handled = False
            if not handled:
                time.sleep(self._poll_interval)

    def stop(self) -> None:  # pragma: no cover
        self.running = False
