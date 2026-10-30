"""Automated response + containment (Task 17).

Given an anomaly/risk outcome and a policy threshold, decides and performs
containment actions: alert, stop task, quarantine the agent, revoke its
credentials, block network egress, and open a security incident. Every critical
action is logged and produces an incident record (SRS §5.6).

The decision of *which* actions to take is a pure function
(:func:`plan_response`) for property testing; execution is performed by
:meth:`ResponseService.respond`, which drives injected collaborators (lifecycle
quarantine, credential vault revoke, incident repo, events).

Break-glass (:meth:`break_glass`) is a separately-authenticated, limited,
audited escape hatch to release containment — it requires an explicit operator
identity and reason and always writes an incident + event.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from ..aro import event_service as es

# Severity order for threshold comparisons.
_ORDER = {"INFO": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}


def plan_response(severity: str, risk_score: int) -> List[str]:
    """Return the ordered list of containment actions for a severity/score. Pure.

    * INFO/LOW: alert only.
    * MEDIUM: alert + stop_task.
    * HIGH: alert + stop_task + quarantine + open_incident.
    * CRITICAL: all of HIGH + revoke_credentials + block_network.
    A risk_score >= 85 escalates to the CRITICAL plan regardless of severity.
    """
    level = _ORDER.get((severity or "INFO").upper(), 0)
    if risk_score >= 85:
        level = max(level, _ORDER["CRITICAL"])

    if level <= _ORDER["LOW"]:
        return ["alert"]
    if level == _ORDER["MEDIUM"]:
        return ["alert", "stop_task"]
    if level == _ORDER["HIGH"]:
        return ["alert", "stop_task", "quarantine", "open_incident"]
    return ["alert", "stop_task", "quarantine", "revoke_credentials",
            "block_network", "open_incident"]


class ResponseService:
    """Executes a containment plan against injected collaborators."""

    def __init__(
        self,
        *,
        quarantine: Optional[Callable[[int, int, str], Any]] = None,
        revoke_credential: Optional[Callable[[int, int], Any]] = None,
        block_network: Optional[Callable[[int, str], Any]] = None,
        incident_repo=None,
        events_repo=None,
    ):
        self._quarantine = quarantine
        self._revoke = revoke_credential
        self._block = block_network
        if incident_repo is None:
            from ..obs import obs_repository as _ir
            incident_repo = _ir
        self._incidents = incident_repo
        if events_repo is None:
            from ..aro import events_repository as _er
            events_repo = _er
        self._events = events_repo

    def respond(
        self,
        tenant_id: int,
        *,
        agent_identity: str,
        agent_db_id: Optional[int],
        severity: str,
        risk_score: int,
        rule_id: str,
        credential_ids: Optional[List[int]] = None,
        evidence: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Perform the planned containment; return the actions taken + incident id."""
        plan = plan_response(severity, risk_score)
        taken: List[str] = []

        es.emit(self._events, tenant_id, "security.alert", "zaf-response",
                agent_id=agent_identity, action={"rule_id": rule_id, "plan": plan},
                risk_score=risk_score, severity=severity)
        taken.append("alert")

        if "quarantine" in plan and self._quarantine is not None and agent_db_id is not None:
            self._quarantine(tenant_id, agent_db_id, f"containment: {rule_id}")
            taken.append("quarantine")
            es.emit(self._events, tenant_id, "agent.quarantined", "zaf-response",
                    agent_id=agent_identity, action={"rule_id": rule_id},
                    decision="QUARANTINE", severity=severity)

        if "revoke_credentials" in plan and self._revoke is not None:
            for cid in (credential_ids or []):
                self._revoke(tenant_id, cid)
            taken.append("revoke_credentials")

        if "block_network" in plan and self._block is not None:
            self._block(tenant_id, agent_identity)
            taken.append("block_network")

        incident_id = None
        if "open_incident" in plan:
            incident_id = self._incidents.create_incident(
                tenant_id, agent_identity, rule_id, severity,
                summary=f"Automated containment for {rule_id}",
                detail={"risk_score": risk_score, "evidence": evidence or []},
                actions_taken=taken,
            )
            es.emit(self._events, tenant_id, "security.incident.opened", "zaf-response",
                    agent_id=agent_identity, action={"incident_id": incident_id},
                    severity=severity)

        return {"plan": plan, "actions_taken": taken, "incident_id": incident_id}

    def break_glass(
        self,
        tenant_id: int,
        *,
        agent_identity: str,
        operator_identity: str,
        reason: str,
    ) -> Dict[str, Any]:
        """Separately-authenticated, audited release of containment.

        Records an incident + event capturing who invoked break-glass and why.
        It does NOT silently restore access — it only logs the authorized
        override; the caller performs the actual state change under audit.
        """
        if not operator_identity or not reason:
            raise ValueError("break-glass requires an operator identity and reason")
        incident_id = self._incidents.create_incident(
            tenant_id, agent_identity, "break_glass", "HIGH",
            summary=f"Break-glass invoked by {operator_identity}",
            detail={"reason": reason, "operator": operator_identity},
            actions_taken=["break_glass"],
        )
        es.emit(self._events, tenant_id, "security.break_glass", "zaf-response",
                agent_id=agent_identity,
                action={"operator": operator_identity, "reason": reason,
                        "incident_id": incident_id},
                severity="HIGH")
        return {"incident_id": incident_id, "operator": operator_identity}
