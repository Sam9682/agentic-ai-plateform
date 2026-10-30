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
    ):
        if events_repo is None:
            from . import events_repository as _er
            events_repo = _er
        self._events = events_repo
        self._adapter_for = adapter_for
        self._launcher = launcher
        self._repo = agent_repo

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
        self._repo.update_status(tenant_id, agent_id, to_state)
        agent["status"] = to_state
        self._emit(agent, "agent.transition",
                   {"from": from_state, "to": to_state})
        return agent

    def install_and_ready(self, tenant_id: int, agent_id: int) -> Dict[str, Any]:
        """Drive REGISTERED -> INSTALLING -> INSTALLED -> CONFIGURING -> READY.

        Uses the adapter's install() when an adapter_for is provided. On adapter
        failure the agent transitions to FAILED and the error is recorded.
        """
        agent = self._repo.get_agent(tenant_id, agent_id)
        if agent is None:
            raise LookupError("agent not found")
        corr = f"evt-{uuid.uuid4().hex}"
        self.transition(tenant_id, agent_id, lifecycle.INSTALLING)
        if self._adapter_for is not None:
            adapter = self._adapter_for(agent)
            result = adapter.install(agent.get("configuration") or {})
            if not getattr(result, "success", True):
                self.transition(tenant_id, agent_id, lifecycle.FAILED)
                self._emit(agent, "agent.install.failed",
                           {"error": getattr(result, "error", "install failed")}, corr)
                return self._repo.get_agent(tenant_id, agent_id)
        self.transition(tenant_id, agent_id, lifecycle.INSTALLED)
        self.transition(tenant_id, agent_id, lifecycle.CONFIGURING)
        self.transition(tenant_id, agent_id, lifecycle.READY)
        return self._repo.get_agent(tenant_id, agent_id)

    def start(self, tenant_id: int, agent_id: int) -> Dict[str, Any]:
        """Drive READY/STOPPED -> STARTING -> RUNNING, launching the container.

        The launcher (if provided) is called to place the agent on a server and
        returns ``{server_id, container_id}`` recorded as an execution.
        """
        agent = self._repo.get_agent(tenant_id, agent_id)
        if agent is None:
            raise LookupError("agent not found")
        self.transition(tenant_id, agent_id, lifecycle.STARTING)
        execution_ref = f"exec-{uuid.uuid4().hex[:12]}"
        server_id = container_id = None
        if self._launcher is not None:
            placement = self._launcher(agent, execution_ref) or {}
            server_id = placement.get("server_id")
            container_id = placement.get("container_id")
        self._repo.create_execution(
            tenant_id, agent_id, execution_ref,
            server_id=server_id, container_id=container_id,
        )
        if self._adapter_for is not None:
            adapter = self._adapter_for(agent)
            result = adapter.start(agent["identity"], agent.get("configuration") or {})
            if not getattr(result, "success", True):
                self.transition(tenant_id, agent_id, lifecycle.FAILED)
                self._emit(agent, "agent.start.failed",
                           {"error": getattr(result, "error", "start failed")})
                return self._repo.get_agent(tenant_id, agent_id)
        self.transition(tenant_id, agent_id, lifecycle.RUNNING)
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
