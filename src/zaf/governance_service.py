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
