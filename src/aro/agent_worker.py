"""Agent task worker (Task 10).

Polls the ``agent_tasks`` queue, claims tasks atomically, executes them through
the agent's runtime adapter, streams output, and records terminal status —
modeled on ``src/serverless/worker.py`` (claim + poll + cancel + timeout).

The execution of a single claimed task is factored into
:func:`execute_claimed_task`, which depends only on injected collaborators
(task repo, an adapter resolver, an events repo and a cancel probe) so it is
unit-testable without a live DB, SSH or a real runtime. Retry is handled by
re-enqueue semantics via ``attempts``/``max_attempts``: a non-success terminal
(``failed``/``timed_out``) is routed through the task store's
``reenqueue_or_finalize`` so a task below its ``max_attempts`` bound returns to
``pending`` for another attempt and one at the bound is finalized. Successful
and cancelled terminals are recorded directly (never re-enqueued).

Background behavior extends the existing poll loop rather than adding a new
process (clarify decision 1): the loop renews the claimed task's lease via
``heartbeat`` interleaved with stream reads, and runs a guarded reaper step
(:meth:`AgentTaskWorker.reap_step`) that reclaims tasks whose lease expired
because their owning worker died.

Concurrency accounting (Req 6.9/6.10): the worker tracks an ``in_flight``
counter and a ``max_in_flight`` cap and skips claiming while
``in_flight >= max_in_flight`` until an in-flight task reaches a terminal
status. In the current single-threaded design ``execute_claimed_task`` runs
synchronously to a terminal status, so ``in_flight`` is incremented before the
execution and decremented after it returns; with the default
``max_in_flight = 1`` behavior is unchanged while the cap is enforced and
observable (true concurrent execution is future work, but the accounting is in
place and unit-testable). Before claiming, the worker computes a round-robin
``preferred_tenant`` via :func:`task_repository.pick_next_tenant` over the
tenants that currently have pending work (discovered via the repo's
``pending_tenants`` helper when available) and passes it to
``claim_next_task`` so one tenant's backlog cannot starve another's; the
claimed task's ``tenant_id`` becomes the new ``last_served`` cursor. When the
repo exposes neither ``preferred_tenant`` support nor pending-tenant discovery,
the worker degrades gracefully to a plain claim.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, Optional

from . import event_service as es
from . import task_repository as task_repo

#: Default heartbeat interval (seconds). MUST be strictly less than the lease
#: TTL so a live worker always renews its lease before it can expire (Req 6.5).
DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 20

#: Terminal statuses that are never re-enqueued. ``succeeded`` is terminal
#: success; ``cancelled`` is a deliberate user decision. Any other terminal
#: (``failed``/``timed_out``) is a non-success terminal routed through
#: ``reenqueue_or_finalize`` for bounded retry (Req 6.3/6.4).
_NON_REENQUEUE_TERMINALS = frozenset({"succeeded", "cancelled"})


def _finalize_terminal(
    repo,
    tenant_id: int,
    task_id: int,
    status: str,
    result: Optional[Dict[str, Any]],
    *,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Record a terminal status, routing non-success terminals through retry.

    ``succeeded``/``cancelled`` are recorded directly via ``repo.complete``.
    A non-success terminal (``failed``/``timed_out``) is routed through
    ``repo.reenqueue_or_finalize`` so a task below ``max_attempts`` returns to
    ``pending`` and one at the bound is finalized in ``status``. The returned
    dict carries the store's ``outcome`` (``"reenqueued"`` / ``"finalized"``)
    when the retry path was taken so the caller/tests can assert it.

    Falls back to ``repo.complete`` when the repo does not expose
    ``reenqueue_or_finalize`` (keeps older/simpler repos working).
    """
    if status in _NON_REENQUEUE_TERMINALS:
        repo.complete(tenant_id, task_id, status, result)
        return {}

    reenqueue = getattr(repo, "reenqueue_or_finalize", None)
    if reenqueue is None:
        repo.complete(tenant_id, task_id, status, result)
        return {}

    # Record the attempt's result/output first so it is not lost when the task
    # is re-enqueued to pending for another attempt.
    repo.complete(tenant_id, task_id, status, result)
    outcome = reenqueue(tenant_id, task_id, status, reason) or {}
    return {"outcome": outcome.get("outcome"), "reenqueue": outcome}


def execute_claimed_task(
    task: Dict[str, Any],
    *,
    adapter_for: Callable[[Dict[str, Any]], Any],
    agent_loader: Callable[[int, int], Optional[Dict[str, Any]]],
    events_repo,
    repo=task_repo,
    cancel_probe: Optional[Callable[[int], bool]] = None,
    lease_ttl: int = task_repo.DEFAULT_LEASE_TTL_SECONDS,
    heartbeat_interval: float = DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
    clock: Callable[[], float] = time.monotonic,
    zaf_exec: Optional[Callable[[Dict[str, Any]], Any]] = None,
) -> Dict[str, Any]:
    """Execute one claimed task to a terminal status; return the terminal dict.

    Streams the adapter's execution, honoring cancellation (checked before and
    during streaming) and the wall-clock deadline (Req 6.1/6.2). Non-success
    terminals (adapter error, ``timed_out``, ``result.success == False``) are
    routed through :func:`_finalize_terminal` so the task store can re-enqueue
    the attempt when ``attempts < max_attempts`` or finalize it at the bound
    (Req 6.3/6.4). ``succeeded`` and ``cancelled`` are recorded directly and are
    never re-enqueued.

    While streaming, the task's lease is renewed by calling
    ``repo.heartbeat(tenant_id, task_id, lease_ttl=...)`` whenever
    ``heartbeat_interval`` has elapsed since the last beat (Req 6.5). The
    ``clock`` is injectable for deterministic tests; ``heartbeat_interval`` must
    be strictly less than ``lease_ttl`` so a live worker always renews before
    the lease can expire.

    Emits task lifecycle events (received, completed/failed/cancelled/timed_out)
    regardless of whether a non-success terminal is re-enqueued or finalized.

    ZAF exec seam (Req 8.1, 8.2, 8.3): ``zaf_exec`` is an injectable callable
    consulted exactly once at task execution start — immediately before the
    adapter's ``execute(...)`` that begins the task's streamed execution. The
    default is an inert no-op (``lambda ctx: None``) and the callable's RETURN
    VALUE is intentionally discarded: in Phase 2 no enforcement decision may
    alter execution (inertness, Req 8.2). Phase 3 ZAF enforcement hooks in
    here. The documented decision inputs the Phase 3 enforcement point will
    consume at this seam (AC 8.3) are:
      - tenant id
      - agent id
      - the requested operation
      - the payload shape — the task payload's sorted top-level key names only,
        never the payload values
    """
    tenant_id = task["tenant_id"]
    task_id = task["id"]
    agent = agent_loader(tenant_id, task["agent_id"])
    if agent is None:
        return {
            "status": "failed",
            "error": "agent not found",
            **_finalize_terminal(repo, tenant_id, task_id, "failed",
                                 {"error": "agent not found"},
                                 reason="agent not found"),
        }

    corr = f"task-{task['task_ref']}"
    es.emit(events_repo, tenant_id, "task.received", "worker",
            agent_id=agent["identity"], execution_id=task["task_ref"],
            action={"operation": task["operation"]}, correlation_id=corr)

    cancel_probe = cancel_probe or repo.is_cancel_requested
    if cancel_probe(task_id):
        # Cancelled is a deliberate user decision — recorded directly, never
        # re-enqueued.
        repo.complete(tenant_id, task_id, "cancelled", {"error": "cancelled before start"})
        es.emit(events_repo, tenant_id, "task.cancelled", "worker",
                agent_id=agent["identity"], execution_id=task["task_ref"], correlation_id=corr)
        return {"status": "cancelled"}

    repo.mark_running(tenant_id, task_id)
    adapter = adapter_for(agent)
    collected = []

    # Heartbeat renewal state. ``heartbeat_interval`` must be strictly less than
    # ``lease_ttl`` (Req 6.5); clamp defensively so a misconfiguration can never
    # make the interval meet/exceed the lease and let a live worker's lease lapse.
    hb_renew = getattr(repo, "heartbeat", None)
    hb_interval = float(heartbeat_interval)
    if hb_interval <= 0 or hb_interval >= lease_ttl:
        hb_interval = max(1.0, float(lease_ttl) / 3.0)
    last_beat = clock()

    def _maybe_heartbeat() -> None:
        nonlocal last_beat
        if hb_renew is None:
            return
        now = clock()
        if now - last_beat >= hb_interval:
            try:
                hb_renew(tenant_id, task_id, lease_ttl=lease_ttl)
            except TypeError:
                # Repos whose heartbeat does not accept lease_ttl keyword.
                hb_renew(tenant_id, task_id)
            last_beat = now

    # Inert ZAF exec seam (Req 8.1, 8.2). Consulted exactly once immediately
    # before the adapter.execute(...) that starts the streamed execution. The
    # default is a no-op and the return value is intentionally discarded: in
    # Phase 2 no enforcement decision may alter execution. Phase 3 enforcement
    # hooks in here. Decision inputs for Phase 3: tenant id, agent id, the
    # requested operation, and the payload shape (sorted top-level key names
    # only — never the payload values).
    zaf = zaf_exec or (lambda ctx: None)
    payload = task.get("payload") or {}
    zaf(
        {
            "tenant_id": tenant_id,
            "agent_id": task["agent_id"],
            "operation": task["operation"],
            "payload_keys": sorted(list(payload.keys())),
        }
    )

    try:
        handle = adapter.execute(agent["identity"], payload)
        # Wall-clock deadline measured from the start of streamed execution
        # (AC 6.1). A missing/non-positive budget means no deadline is imposed.
        timeout_seconds = task.get("timeout_seconds")
        deadline = (
            clock() + timeout_seconds
            if timeout_seconds and timeout_seconds > 0
            else None
        )
        for chunk in handle.stream():
            if chunk.channel in ("stdout", "stderr") and chunk.data:
                collected.append(chunk.data)
            if cancel_probe(task_id):
                handle.cancel()
                repo.complete(tenant_id, task_id, "cancelled", {"output": "".join(collected)})
                es.emit(events_repo, tenant_id, "task.cancelled", "worker",
                        agent_id=agent["identity"], execution_id=task["task_ref"], correlation_id=corr)
                return {"status": "cancelled", "output": "".join(collected)}
            if deadline is not None and clock() >= deadline:
                # Deadline reached before completion: cancel the handle and
                # set the task to the timed_out terminal (AC 6.2). timed_out is
                # a non-success terminal so bounded retry applies (Req 6.3/6.4).
                handle.cancel()
                extra = _finalize_terminal(
                    repo, tenant_id, task_id, "timed_out",
                    {"error": "deadline exceeded", "output": "".join(collected)},
                    reason="deadline exceeded")
                es.emit(events_repo, tenant_id, "task.timed_out", "worker",
                        agent_id=agent["identity"], execution_id=task["task_ref"],
                        severity="MEDIUM", correlation_id=corr)
                return {"status": "timed_out", "output": "".join(collected), **extra}
            # Renew the lease between stream reads so the reaper never reclaims a
            # task this worker is actively processing (Req 6.5).
            _maybe_heartbeat()
        result = handle.result()
    except Exception as exc:  # noqa: BLE001 - adapter errors are terminal for the attempt
        # Adapter error is a non-success terminal → bounded retry (Req 6.3/6.4).
        extra = _finalize_terminal(
            repo, tenant_id, task_id, "failed",
            {"error": f"{type(exc).__name__}: {exc}"},
            reason=f"{type(exc).__name__}: {exc}")
        es.emit(events_repo, tenant_id, "task.failed", "worker",
                agent_id=agent["identity"], execution_id=task["task_ref"],
                action={"error": str(exc)}, severity="MEDIUM", correlation_id=corr)
        return {"status": "failed", "error": str(exc), **extra}

    status = "succeeded" if result.success else "failed"
    # succeeded → recorded directly; failed → routed through bounded retry.
    extra = _finalize_terminal(
        repo, tenant_id, task_id, status, result.as_dict(),
        reason=None if result.success else "execution failed")
    es.emit(events_repo, tenant_id, f"task.{status}", "worker",
            agent_id=agent["identity"], execution_id=task["task_ref"],
            action={"returncode": result.returncode},
            severity="INFO" if result.success else "MEDIUM", correlation_id=corr)
    return {"status": status, "output": result.output, **extra}


class AgentTaskWorker:
    """Blocking poll loop claiming and executing agent tasks.

    Extends the existing poll loop (clarify decision 1) with a guarded reaper
    step: each cycle (throttled by ``reap_interval``) the loop calls
    ``repo.reap_expired_leases()`` and routes every expired row through
    ``repo.reenqueue_or_finalize(..., "failed", "lease expired")`` so a
    dead worker's tasks are reclaimed (re-enqueued below ``max_attempts`` or
    finalized at the bound) without the reaper's failure ever killing the loop.
    """

    def __init__(
        self,
        worker_id: str,
        *,
        adapter_for: Callable[[Dict[str, Any]], Any],
        agent_loader: Callable[[int, int], Optional[Dict[str, Any]]],
        events_repo=None,
        poll_interval: float = 1.0,
        repo=task_repo,
        lease_ttl: int = task_repo.DEFAULT_LEASE_TTL_SECONDS,
        heartbeat_interval: float = DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
        reap_interval: float = 0.0,
        max_in_flight: int = 1,
        clock: Callable[[], float] = time.monotonic,
        zaf_exec: Optional[Callable[[Dict[str, Any]], Any]] = None,
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
        self._lease_ttl = lease_ttl
        self._heartbeat_interval = heartbeat_interval
        #: Minimum seconds between reaper sweeps. ``0`` means run it every cycle
        #: (the reaper is cheap and safe to call each poll — a no-op when no
        #: lease has expired).
        self._reap_interval = reap_interval
        self._clock = clock
        #: Inert ZAF exec seam (Req 8.1, 8.2, 8.3) threaded into every
        #: ``execute_claimed_task`` call so a worker can be constructed with the
        #: Phase 3 enforcement hook. Defaults to an inert no-op; its return
        #: value is discarded and cannot alter execution in Phase 2. Documented
        #: Phase 3 decision inputs (AC 8.3): tenant id, agent id, operation,
        #: payload shape (top-level key names only, never values).
        self._zaf_exec = zaf_exec
        self._last_reap = 0.0
        #: Max-in-flight cap (Req 6.9). While ``in_flight >= max_in_flight`` the
        #: worker skips claiming until an in-flight task reaches a terminal
        #: status. Default ``1`` preserves the current synchronous behavior.
        self._max_in_flight = max(1, int(max_in_flight))
        #: Number of tasks currently being executed. Incremented before
        #: ``execute_claimed_task`` and decremented after it returns a terminal
        #: status (single-threaded-correct; true concurrency is future work).
        self.in_flight = 0
        #: Round-robin cursor for per-tenant fairness (Req 6.10): the tenant of
        #: the most recently claimed task. Fed to ``pick_next_tenant`` to pick
        #: the next preferred tenant so no tenant's backlog starves another's.
        self.last_served = None
        self.running = False

    @property
    def max_in_flight(self) -> int:
        """The configured max-in-flight cap (read-only, for observability)."""
        return self._max_in_flight

    def _preferred_tenant(self):
        """Compute the round-robin preferred tenant to claim next (Req 6.10).

        Discovers the tenants with pending work via the repo's
        ``pending_tenants`` helper (when available) and rotates to the next one
        after :attr:`last_served` via :func:`task_repository.pick_next_tenant`.
        Returns ``None`` (plain claim) when the repo lacks pending-tenant
        discovery or no tenant currently has pending work.
        """
        discover = getattr(self._repo, "pending_tenants", None)
        if discover is None:
            return None
        try:
            pending = discover() or {}
        except Exception:  # noqa: BLE001 - discovery must never kill the loop
            return None
        if not pending:
            return None
        return task_repo.pick_next_tenant(pending, self.last_served)

    def _claim(self):
        """Claim the next task, applying per-tenant fairness when supported.

        Passes the computed ``preferred_tenant`` to ``claim_next_task`` so the
        fairness-ordered claim is used. Degrades gracefully to a plain claim
        when the repo's ``claim_next_task`` does not accept ``preferred_tenant``
        (older/simpler repos).
        """
        preferred = self._preferred_tenant()
        if preferred is None:
            return self._repo.claim_next_task(self.worker_id)
        try:
            return self._repo.claim_next_task(
                self.worker_id, preferred_tenant=preferred
            )
        except TypeError:
            # Repo's claim_next_task does not support preferred_tenant.
            return self._repo.claim_next_task(self.worker_id)

    def reap_step(self) -> int:
        """Reclaim tasks whose lease expired (dead worker). Never raises.

        Calls ``repo.reap_expired_leases()`` and routes each expired row through
        ``repo.reenqueue_or_finalize(tenant_id, id, "failed", "lease expired")``
        so a task below ``max_attempts`` returns to ``pending`` and one at the
        bound is finalized ``failed`` with the lease-expiry reason (Req 6.6/6.7).

        For each reclaimed row a matching task lifecycle event is emitted
        (Req 6.12): ``task.reclaimed`` when the task was re-enqueued for another
        attempt, and ``task.failed`` (reason ``"lease expired"``) when it was
        finalized at the attempt bound. When the store does not report an
        outcome, a ``task.reclaimed`` event is emitted as a safe default so the
        reclaim is always observable. The event carries the reduced context the
        reaper has from the expired row — ``execution_id`` is the row's
        ``task_ref`` and ``agent_id`` is the row's agent FK (the reaper does not
        load the agent's full identity); both are ``None`` when the projection
        omits them (older repos), which :func:`event_service.build_event`
        tolerates.

        Any exception (including a repo that lacks the reaper methods, or an
        event emission failure) is swallowed so a transient error can never kill
        the poll loop. Returns the number of expired rows processed.
        """
        reap = getattr(self._repo, "reap_expired_leases", None)
        reenqueue = getattr(self._repo, "reenqueue_or_finalize", None)
        if reap is None or reenqueue is None:
            return 0
        processed = 0
        try:
            expired = reap() or []
        except Exception:  # noqa: BLE001 - reaper must never kill the loop
            return 0
        for row in expired:
            try:
                outcome = reenqueue(
                    row["tenant_id"], row["id"], "failed", "lease expired"
                ) or {}
                processed += 1
            except Exception:  # noqa: BLE001 - one bad row must not abort the sweep
                continue
            # Emit the matching lifecycle event for the reclaimed row. Isolated
            # in its own guard so an events failure never aborts the sweep or
            # loses the re-enqueue/finalize that already happened (Req 6.12).
            try:
                self._emit_reap_event(row, outcome)
            except Exception:  # noqa: BLE001 - events must never kill the loop
                pass
        return processed

    def _emit_reap_event(self, row: Dict[str, Any], outcome: Dict[str, Any]) -> None:
        """Emit the task lifecycle event for one reclaimed row (Req 6.12).

        Re-enqueued → ``task.reclaimed`` (the task will run again);
        finalized → ``task.failed`` with the lease-expiry reason (terminal).
        Uses the reduced context available from the reap projection
        (``task_ref``/``agent_id`` when present).
        """
        if self._events is None:
            return
        decided = outcome.get("outcome")
        task_ref = row.get("task_ref")
        agent_id = row.get("agent_id")
        corr = f"task-{task_ref}" if task_ref is not None else None
        if decided == "finalized":
            es.emit(self._events, row["tenant_id"], "task.failed", "reaper",
                    agent_id=agent_id, execution_id=task_ref,
                    action={"reason": "lease expired"},
                    severity="MEDIUM", correlation_id=corr)
        else:
            # "reenqueued" (or an unknown/None outcome): the task was reclaimed
            # and will be attempted again — emit the reclaim lifecycle event.
            es.emit(self._events, row["tenant_id"], "task.reclaimed", "reaper",
                    agent_id=agent_id, execution_id=task_ref,
                    action={"reason": "lease expired"},
                    severity="MEDIUM", correlation_id=corr)

    def _maybe_reap(self) -> None:
        """Run the reaper step when ``reap_interval`` has elapsed (guarded)."""
        now = self._clock()
        if self._reap_interval <= 0 or (now - self._last_reap) >= self._reap_interval:
            self._last_reap = now
            self.reap_step()

    def run_once(self) -> bool:
        """Claim and execute a single task. Returns True when one was handled.

        The guarded reaper step runs each cycle before the claim so a dead
        worker's expired tasks are returned to ``pending`` and become claimable
        again on this very poll.

        Enforces the max-in-flight cap (Req 6.9): while
        ``in_flight >= max_in_flight`` the worker skips claiming entirely and
        returns ``False`` until an in-flight task reaches a terminal status. The
        claim uses the per-tenant fairness ordering (Req 6.10) and the claimed
        task's tenant becomes the new ``last_served`` cursor.
        """
        self._maybe_reap()
        # Max-in-flight cap: do not claim new work while at capacity (Req 6.9).
        if self.in_flight >= self._max_in_flight:
            return False
        task = self._claim()
        if task is None:
            return False
        # Advance the round-robin cursor to the claimed task's tenant (Req 6.10).
        self.last_served = task.get("tenant_id", self.last_served)
        # Account for the in-flight task across the synchronous execution. With
        # max_in_flight == 1 this reproduces the current one-at-a-time behavior;
        # the increment/decrement make the cap observable and correctly enforced
        # (Req 6.9).
        self.in_flight += 1
        try:
            execute_claimed_task(
                task,
                adapter_for=self._adapter_for,
                agent_loader=self._agent_loader,
                events_repo=self._events,
                repo=self._repo,
                lease_ttl=self._lease_ttl,
                heartbeat_interval=self._heartbeat_interval,
                clock=self._clock,
                zaf_exec=self._zaf_exec,
            )
        finally:
            # The task has reached a terminal status; free its slot (Req 6.9).
            self.in_flight -= 1
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
