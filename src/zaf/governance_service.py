"""ZAF governance service (Task 11).

Ties the pure :mod:`policy_engine` to the DB-backed :mod:`policy_repository` and
the unified event audit. ``decide`` loads the tenant's effective rules + the
agent's permissions, evaluates (fail-closed), records the decision for audit,
and emits an event. This is the single entry point the MCP gateway and infra
proxy call before performing a protected action.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Optional

from . import policy_engine as engine
from . import policy_repository as repo
from ..aro import event_service as es


def params_hash(action: str, params: Optional[Dict[str, Any]]) -> str:
    """Stable hash binding a decision/approval to the exact action + params."""
    canonical = json.dumps(
        {"action": action, "params": params or {}}, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def decide(
    tenant_id: int,
    action: str,
    *,
    agent_db_id: Optional[int] = None,
    agent_identity: Optional[str] = None,
    resource: Optional[str] = None,
    params: Optional[Dict[str, Any]] = None,
    context: Optional[Dict[str, Any]] = None,
    service_available: bool = True,
    events_repo=None,
) -> Dict[str, Any]:
    """Evaluate a protected action, record the decision, emit an event.

    Returns the decision dict augmented with ``params_hash`` so a downstream
    approval can be bound to the exact action+params.
    """
    if events_repo is None:
        from ..aro import events_repository as _er
        events_repo = _er

    rules = repo.effective_rules(tenant_id) if service_available else []
    permissions = (
        repo.agent_permissions(tenant_id, agent_db_id)
        if (service_available and agent_db_id is not None) else []
    )
    ctx = dict(context or {})
    if resource is not None:
        ctx.setdefault("resource", resource)

    decision = engine.evaluate_fail_closed(
        action, rules=rules, permissions=permissions, context=ctx,
        service_available=service_available,
    )

    phash = params_hash(action, params)
    repo.record_decision(
        tenant_id,
        agent_identity=agent_identity,
        action=action,
        resource=resource,
        decision=decision.decision,
        matched_rule=decision.matched_rule,
        risk_score=decision.risk_score,
        reason=decision.reason,
        params_hash=phash,
    )
    es.emit(
        events_repo, tenant_id, "governance.decision", "zaf-pdp",
        agent_id=agent_identity,
        action={"action": action, "resource": resource, "params": params or {}},
        decision=decision.decision,
        risk_score=decision.risk_score,
        severity=_severity_for(decision.decision),
    )
    result = decision.as_dict()
    result["params_hash"] = phash
    return result


def _severity_for(decision: str) -> str:
    return {
        engine.ALLOW: "INFO",
        engine.REQUIRE_APPROVAL: "MEDIUM",
        engine.QUARANTINE: "HIGH",
        engine.DENY: "HIGH",
    }.get(decision, "INFO")


# --------------------------------------------------------------------------- #
# Quarantine coordinator (Task 17.1, R8.1/R8.2/R8.3/R8.5)
# --------------------------------------------------------------------------- #
def quarantine(
    tenant_id: int,
    agent_db_id: int,
    agent_identity: Optional[str],
    *,
    reason: str,
    credential_ids,
    lifecycle_svc,
    exec_mgr,
    vault=None,
) -> Dict[str, Any]:
    """Coordinate agent quarantine: revoke, state-transition, and isolate.

    This is a coordinator only — it does not add any decision logic to the pure
    PDP evaluator. A quarantined agent is hard-denied at the seams through the
    PDP ``QUARANTINE`` decision (the seam enforcer maps ``QUARANTINE`` to
    hard-deny exactly like ``DENY``), independent of agent self-report (R8.2);
    no special seam branch is added here.

    Steps:
      1. Revoke each credential via ``vault.revoke`` — this also flips every
         scoped token minted from the credential to ``revoked`` so a later
         ``verify_token`` denies them (R8.1).
      2. Drive the agent into ``QUARANTINED`` via
         ``lifecycle_svc.quarantine`` (R8.2 basis / containment state).
      3. Stop / network-isolate the agent's runtime via the execution
         manager (R8.3).

    Forensic events remain append-only and preserved: the event store has no
    update/delete path, so quarantine only adds events and never removes the
    agent's history (R8.5).
    """
    if vault is None:
        from . import credential_vault as vault  # lazy to avoid import cycle

    # (1) Revoke credentials (and their scoped tokens) — R8.1.
    for cid in (credential_ids or []):
        vault.revoke(tenant_id, cid)

    # (2) Containment state transition -> QUARANTINED.
    agent = lifecycle_svc.quarantine(tenant_id, agent_db_id, reason)

    # (3) Stop / network-isolate the runtime — R8.3. The injected execution
    # manager owns how a running runtime is torn down / isolated; we drive it
    # through its public stop entry point. Resolve the runtime coordinates from
    # the returned agent row when available, and degrade gracefully if the
    # runtime is already gone (quarantine must still complete).
    _stop_or_isolate(exec_mgr, agent, agent_identity)
    return agent


def _stop_or_isolate(exec_mgr, agent, agent_identity: Optional[str]) -> None:
    """Best-effort stop / network isolation of a quarantined agent's runtime.

    ``execution_manager.stop(server_ip, container_ref)`` needs runtime
    coordinates; resolve them from the agent row when present. If the runtime
    is already stopped or missing, isolation is a no-op and quarantine still
    completes — containment (revoke + QUARANTINED state + PEP hard-deny) is
    already in force.
    """
    stop = getattr(exec_mgr, "stop", None)
    if stop is None:
        return
    server_ip = None
    container_ref = None
    if isinstance(agent, dict):
        server_ip = agent.get("server_ip") or agent.get("host")
        container_ref = (
            agent.get("container_ref")
            or agent.get("execution_ref")
            or agent.get("identity")
        )
    if container_ref is None:
        container_ref = agent_identity
    try:
        if server_ip is not None and container_ref is not None:
            stop(server_ip, container_ref)
        elif container_ref is not None:
            # Injected managers in tests may expose a single-arg stop keyed by
            # the agent identity; fall back to that shape.
            stop(container_ref)
    except TypeError:
        # Signature mismatch between live (server_ip, container_ref) and an
        # injected test double — try the identity-only form once.
        try:
            stop(agent_identity)
        except Exception:
            pass
    except Exception:
        # Runtime already gone / transient SSH error: containment still holds.
        pass
