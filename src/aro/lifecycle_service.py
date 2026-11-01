"""Agent lifecycle service (Task 7).

Coordinates agent state transitions, validating each against the pure
:mod:`src.aro.lifecycle` graph, persisting via :mod:`agent_repository`, and
emitting an event (:mod:`event_service`) for every transition. Start/stop drive
the runtime adapter (Task 5) and the hardened execution manager (Task 6); here
they are injected so the service is testable with the FakeAdapter and a stub
server selector (no SSH).

A transition that violates the graph raises :class:`IllegalTransition` and
performs no side effect — the agent's recorded status is never corrupted.
"""

from __future__ import annotations

import uuid
from typing import Any, Callable, Dict, Optional

from . import agent_repository as repo
from . import event_service as es
from . import lifecycle


class IllegalTransition(Exception):
    """Raised when a requested state transition is not permitted by the graph."""

    def __init__(self, from_state: str, to_state: str):
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(f"illegal transition {from_state} -> {to_state}")


class LifecycleService:
    """Drives agent lifecycle operations with validated transitions + events.

    Dependencies are injected for testability:
        events_repo:  object with append_event(event) (defaults to events_repository)
        adapter_for:  callable(agent) -> AgentRuntimeAdapter
        launcher:     callable(agent, execution_ref) -> dict(server_id, container_id)
                      (defaults to a no-op that records nothing)
    """

    def __init__(
        self,
        *,
        events_repo=None,
        adapter_for: Optional[Callable[[Dict[str, Any]], Any]] = None,
        launcher: Optional[Callable[[Dict[str, Any], str], Dict[str, Any]]] = None,
        agent_repo=repo,
        zaf_pre_transition: Optional[Callable[[Dict[str, Any]], Any]] = None,
    ):
        if events_repo is None:
            from . import events_repository as _er
            events_repo = _er
        self._events = events_repo
        self._adapter_for = adapter_for
        self._launcher = launcher
        self._repo = agent_repo
        # Inert ZAF (Zero-trust Access Fabric) pre-transition seam (Req 1.12,
        # 8.1, 8.2, 8.3). A defaulted no-op policy hook consulted inside
        # transition() after the legality check and before the status write. In
        # Phase 2 the callable's return value is deliberately DISCARDED and
        # cannot alter the transition outcome (AC 8.2 — inert); it exists so
        # Phase 3 can wire in enforcement without re-architecting the lifecycle
        # service.
        #
        # Documented Phase 3 decision inputs this seam will consume (AC 8.3):
        #   - tenant id
        #   - agent identity
        #   - from/to state (the source and target lifecycle states)
        #   - the agent's policy_refs
        self._zaf = zaf_pre_transition or (lambda ctx: None)

    def _emit(self, agent: Dict[str, Any], event_type: str, action: Dict[str, Any],
              correlation_id: Optional[str] = None):
        return es.emit(
            self._events,
            agent["tenant_id"],
            event_type,
            "lifecycle",
            agent_id=agent["identity"],
            action=action,
            correlation_id=correlation_id,
        )

    def transition(self, tenant_id: int, agent_id: int, to_state: str) -> Dict[str, Any]:
        """Validate + apply a single transition, emitting an event.

        Raises :class:`IllegalTransition` (no side effect) when illegal, or
        LookupError when the agent does not exist in the tenant.
        """
        agent = self._repo.get_agent(tenant_id, agent_id)
        if agent is None:
            raise LookupError("agent not found")
        from_state = agent["status"]
        if not lifecycle.can_transition(from_state, to_state):
            raise IllegalTransition(from_state, to_state)
        # Inert ZAF pre-transition seam (Req 1.12, 8.1, 8.2, 8.3): consulted
        # AFTER the legality check (which already raised IllegalTransition
        # before any write) and BEFORE the status write. The return value is
        # intentionally discarded — in Phase 2 the seam cannot allow, deny, or
        # otherwise alter a transition the graph already permits (AC 8.2,
        # inert). Documented Phase 3 decision inputs (AC 8.3): tenant id, agent
        # identity, from/to state, and the agent's policy_refs. The context
        # dict below carries {tenant_id, agent_id, from, to, identity}; Phase 3
        # additionally resolves the agent's policy_refs when consuming it.
        self._zaf({
            "tenant_id": tenant_id,
            "agent_id": agent_id,
            "from": from_state,
            "to": to_state,
            "identity": agent["identity"],
        })
        self._repo.update_status(tenant_id, agent_id, to_state)
        agent["status"] = to_state
        self._emit(agent, "agent.transition",
                   {"from": from_state, "to": to_state})
        return agent

    def _rollback_to(
        self,
        tenant_id: int,
        agent_id: int,
        prior_status: str,
        exec_id: Optional[int] = None,
    ) -> None:
        """Compensate a failed mid-sequence operation (Req 1.9, 1.10).

        Restores the agent's pre-op status and releases any execution row that
        the aborted operation created. This is the *only* status write that
        does not route through :meth:`transition`: it deliberately writes a
        previously-valid status (the status the agent held before the operation
        began) directly via ``update_status``, because the pre-op status is not
        necessarily a graph-legal successor of the mid-sequence state. It never
        writes a novel or mid-sequence status, so the illegal-transition
        guarantee for normal transitions (Req 1.11) is preserved: ``transition()``
        remains the sole mutation path for forward progress.

        * When ``exec_id`` is provided, the created Execution_Row is closed out
          as FAILED with ``ended=True`` so no row is left open (AC 1.10).
        * The agent's recorded status is restored to ``prior_status`` (AC 1.9).
        """
        if exec_id is not None:
            self._repo.set_execution_status(
                tenant_id, exec_id, lifecycle.FAILED, ended=True
            )
        self._repo.update_status(tenant_id, agent_id, prior_status)

    def install_and_ready(self, tenant_id: int, agent_id: int) -> Dict[str, Any]:
        """Drive REGISTERED -> INSTALLING -> INSTALLED -> CONFIGURING -> READY.

        Uses the adapter's install() when an adapter_for is provided. On ANY
        mid-sequence failure (adapter install failure or an exception raised in
        the transition chain) the operation compensates: the agent is rolled
        back to its pre-op status (the status held before the first transition)
        and ``agent.install.failed`` is emitted (Req 1.9). This replaces the
        prior behavior of landing on FAILED — FAILED stays reachable only via
        the explicit recovery/health/quarantine edges.
        """
        agent = self._repo.get_agent(tenant_id, agent_id)
        if agent is None:
            raise LookupError("agent not found")
        corr = f"evt-{uuid.uuid4().hex}"
        # Capture the pre-op status BEFORE the first transition so a failure
        # anywhere in the sequence can atomically restore it (AC 1.9).
        prior = agent["status"]
        # The entry transition is OUTSIDE the compensation scope: if it is
        # graph-illegal it raises IllegalTransition before any write, which must
        # propagate as a rejection (AC 1.11). Only once state has begun to
        # mutate do we compensate operational/mid-sequence failures.
        self.transition(tenant_id, agent_id, lifecycle.INSTALLING)
        try:
            if self._adapter_for is not None:
                adapter = self._adapter_for(agent)
                result = adapter.install(agent.get("configuration") or {})
                if not getattr(result, "success", True):
                    raise RuntimeError(
                        getattr(result, "error", "install failed")
                    )
            self.transition(tenant_id, agent_id, lifecycle.INSTALLED)
            self.transition(tenant_id, agent_id, lifecycle.CONFIGURING)
            self.transition(tenant_id, agent_id, lifecycle.READY)
        except Exception as exc:  # noqa: BLE001 - compensate on any failure
            self._rollback_to(tenant_id, agent_id, prior)
            self._emit(agent, "agent.install.failed", {"error": str(exc)}, corr)
            return self._repo.get_agent(tenant_id, agent_id)
        return self._repo.get_agent(tenant_id, agent_id)

    def start(self, tenant_id: int, agent_id: int) -> Dict[str, Any]:
        """Drive READY/STOPPED -> STARTING -> RUNNING, launching the container.

        The launcher (if provided) is called to place the agent on a server and
        returns ``{server_id, container_id}`` recorded as an execution.
        """
        agent = self._repo.get_agent(tenant_id, agent_id)
        if agent is None:
            raise LookupError("agent not found")
        # Capture the pre-op status (READY or STOPPED) BEFORE the first
        # transition so a mid-sequence failure can atomically restore it (AC 1.9).
        prior = agent["status"]
        exec_id = None
        # The entry transition is OUTSIDE the compensation scope: a start
        # requested from an illegal source (e.g. RUNNING) raises
        # IllegalTransition before any write and must propagate as a rejection
        # (AC 1.11). Compensation only applies once state has begun to mutate.
        self.transition(tenant_id, agent_id, lifecycle.STARTING)
        try:
            execution_ref = f"exec-{uuid.uuid4().hex[:12]}"
            server_id = container_id = None
            if self._launcher is not None:
                placement = self._launcher(agent, execution_ref) or {}
                server_id = placement.get("server_id")
                container_id = placement.get("container_id")
            # Execution_Row is created in STARTING (Req 1.6); capture its pk so a
            # successful adapter start can advance it to RUNNING (Req 1.7), and
            # so a failure can release it during rollback (AC 1.10).
            exec_id = self._repo.create_execution(
                tenant_id, agent_id, execution_ref,
                server_id=server_id, container_id=container_id,
            )
            start_result = None
            runtime_adapter_id = None
            if self._adapter_for is not None:
                adapter = self._adapter_for(agent)
                runtime_adapter_id = getattr(adapter, "adapter_id", None)
                result = adapter.start(
                    agent["identity"], agent.get("configuration") or {}
                )
                if not getattr(result, "success", True):
                    raise RuntimeError(getattr(result, "error", "start failed"))
                start_result = result
            self.transition(tenant_id, agent_id, lifecycle.RUNNING)
            # Adapter start succeeded and the agent is RUNNING: advance the
            # Execution_Row from STARTING to RUNNING (Req 1.7).
            self._repo.set_execution_status(tenant_id, exec_id, lifecycle.RUNNING)
            # Persist the session handle on the Execution_Row so a control-plane
            # restart can reconnect to the remote runtime rather than launching
            # a new one (Req 4.1). server_id is already persisted at
            # create_execution; here we add session_id, runtime_handle, and the
            # concrete runtime_adapter id. This happens ONLY on the successful
            # start path (never during rollback). Values are derived defensively
            # from the adapter start ExecutionResult.extra when present, falling
            # back to the launch container_id for the reconnect handle.
            extra = getattr(start_result, "extra", None) or {}
            session_id = extra.get("session_id")
            runtime_handle = extra.get("runtime_handle") or container_id
            self._repo.set_execution_session(
                tenant_id,
                exec_id,
                session_id=session_id,
                runtime_handle=runtime_handle,
                runtime_adapter=runtime_adapter_id,
            )
        except Exception as exc:  # noqa: BLE001 - compensate on any failure
            # Restore the pre-start status and release the created execution
            # row so nothing is left open (AC 1.9, AC 1.10).
            self._rollback_to(tenant_id, agent_id, prior, exec_id=exec_id)
            self._emit(agent, "agent.start.failed", {"error": str(exc)})
            return self._repo.get_agent(tenant_id, agent_id)
        self._emit(agent, "agent.started", {"execution_ref": execution_ref})
        return self._repo.get_agent(tenant_id, agent_id)

    def stop(self, tenant_id: int, agent_id: int) -> Dict[str, Any]:
        """Drive RUNNING -> STOPPING -> STOPPED, stopping the runtime."""
        agent = self._repo.get_agent(tenant_id, agent_id)
        if agent is None:
            raise LookupError("agent not found")
        self.transition(tenant_id, agent_id, lifecycle.STOPPING)
        if self._adapter_for is not None:
            adapter = self._adapter_for(agent)
            adapter.stop(agent["identity"])
        self.transition(tenant_id, agent_id, lifecycle.STOPPED)
        # Close out the agent's still-open Execution_Row: set it STOPPED and
        # record the session end timestamp via ended=True (Req 1.8).
        exec_id = self._repo.latest_running_execution(tenant_id, agent_id)
        if exec_id is not None:
            self._repo.set_execution_status(
                tenant_id, exec_id, lifecycle.STOPPED, ended=True
            )
        self._emit(agent, "agent.stopped", {})
        return self._repo.get_agent(tenant_id, agent_id)

    def restart(self, tenant_id: int, agent_id: int) -> Dict[str, Any]:
        """Stop (if running) then start again."""
        agent = self._repo.get_agent(tenant_id, agent_id)
        if agent is None:
            raise LookupError("agent not found")
        if agent["status"] == lifecycle.RUNNING:
            self.stop(tenant_id, agent_id)
        return self.start(tenant_id, agent_id)

    def quarantine(self, tenant_id: int, agent_id: int, reason: str) -> Dict[str, Any]:
        """Force an agent into QUARANTINED (containment), emitting an event."""
        agent = self._repo.get_agent(tenant_id, agent_id)
        if agent is None:
            raise LookupError("agent not found")
        self.transition(tenant_id, agent_id, lifecycle.QUARANTINED)
        self._emit(agent, "agent.quarantined", {"reason": reason})
        return self._repo.get_agent(tenant_id, agent_id)

    def release(self, tenant_id: int, agent_id: int) -> Dict[str, Any]:
        """Release a QUARANTINED agent back to READY, emitting an event.

        Release is anchored to the QUARANTINED source status specifically
        (Req 1.2/1.3), not merely to the generic graph edge into READY: the
        pure graph makes READY a legal successor of both QUARANTINED and
        CONFIGURING, so routing release() blindly through
        ``transition(..., READY)`` would also accept a CONFIGURING agent and
        violate Req 1.3. Therefore a release request for an agent whose status
        is not QUARANTINED is rejected as an :class:`IllegalTransition` BEFORE
        any write (Req 1.3 — no state change). The legal QUARANTINED -> READY
        path still routes through :meth:`transition` so that remains the sole
        mutation path (Req 1.2).
        """
        agent = self._repo.get_agent(tenant_id, agent_id)
        if agent is None:
            raise LookupError("agent not found")
        if agent["status"] != lifecycle.QUARANTINED:
            # Req 1.3: reject any non-QUARANTINED source with no persisted
            # state change, before transition() is ever reached.
            raise IllegalTransition(agent["status"], lifecycle.READY)
        self.transition(tenant_id, agent_id, lifecycle.READY)
        self._emit(agent, "agent.released", {})
        return self._repo.get_agent(tenant_id, agent_id)

    def health_reconcile(self, tenant_id: int, agent_id: int) -> Dict[str, Any]:
        """Probe runtime health and reconcile RUNNING<->UNHEALTHY.

        Probes ``adapter.health_check()`` and feeds the agent's current status
        plus the probe result into the pure :func:`lifecycle.reconcile_health`
        decision (Req 1.4, 1.5):

        * RUNNING + unhealthy  -> UNHEALTHY, emitting ``agent.unhealthy``
        * UNHEALTHY + healthy  -> RUNNING,   emitting ``agent.recovered``
        * anything else        -> no change

        RUNNING<->UNHEALTHY are already legal edges in the pure graph, so the
        change is routed through :meth:`transition` with no graph change. When
        no adapter_for is configured there is nothing to probe, so the agent is
        returned unchanged.
        """
        agent = self._repo.get_agent(tenant_id, agent_id)
        if agent is None:
            raise LookupError("agent not found")
        if self._adapter_for is None:
            return agent
        healthy = self._adapter_for(agent).health_check()
        target = lifecycle.reconcile_health(agent["status"], healthy)
        if target is None:
            return agent
        self.transition(tenant_id, agent_id, target)
        evt = "agent.unhealthy" if target == lifecycle.UNHEALTHY else "agent.recovered"
        self._emit(agent, evt, {})
        return self._repo.get_agent(tenant_id, agent_id)
