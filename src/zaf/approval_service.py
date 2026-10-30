"""Human approval workflow for ZAF (Task 12).

When the PDP returns REQUIRE_APPROVAL, :func:`request_approval` records a pending
approval bound to the exact action + parameters via a hash (reusing
``governance_service.params_hash``). Approval/rejection set the terminal status.
``is_authorized`` answers whether a given action+params has an *approved*
approval — because the hash is over the exact params, a modified request yields
a different hash and is NOT authorized by a prior approval (SRS §4.5).

The data-access functions use the shared ``db_manager``; the hashing/binding
logic is pure and tested directly.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from . import governance_service as gov
from ..aro import event_service as es


def _get_db():
    from ..database_postgres import db_manager
    return db_manager


def _as_json(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def request_approval(
    tenant_id: int,
    action: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    agent_identity: Optional[str] = None,
    resource: Optional[str] = None,
    risk_explanation: str = "",
    triggering_policy: Optional[Dict[str, Any]] = None,
    ttl_seconds: int = 3600,
    events_repo=None,
) -> Dict[str, Any]:
    """Create (or return existing) pending approval bound to action+params.

    If a pending approval already exists for the same params_hash, it is
    returned rather than duplicated.
    """
    if events_repo is None:
        from ..aro import events_repository as _er
        events_repo = _er

    phash = gov.params_hash(action, params)
    db = _get_db()
    existing = db.execute_query(
        "SELECT id FROM approval_requests WHERE tenant_id = %s AND params_hash = %s "
        "AND status = 'pending'",
        (tenant_id, phash),
        fetch_one=True,
    )
    if existing:
        return get_approval(tenant_id, int(existing[0]))

    expires_at = datetime.now(timezone.utc) + timedelta(seconds=max(1, int(ttl_seconds)))
    row = db.execute_query(
        """
        INSERT INTO approval_requests (
            tenant_id, agent_identity, action, resource, params, params_hash,
            risk_explanation, triggering_policy, expires_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            tenant_id, agent_identity, action, resource, json.dumps(params or {}),
            phash, risk_explanation,
            json.dumps(triggering_policy) if triggering_policy is not None else None,
            expires_at,
        ),
        fetch_one=True,
    )
    es.emit(events_repo, tenant_id, "approval.requested", "zaf-approval",
            agent_id=agent_identity,
            action={"action": action, "resource": resource},
            decision="REQUIRE_APPROVAL", severity="MEDIUM")
    return get_approval(tenant_id, int(row[0]))


def get_approval(tenant_id: int, approval_id: int) -> Optional[Dict[str, Any]]:
    row = _get_db().execute_query(
        "SELECT id, agent_identity, action, resource, params, params_hash, "
        "risk_explanation, triggering_policy, status, approver_user_id, "
        "decided_at, created_at FROM approval_requests "
        "WHERE tenant_id = %s AND id = %s",
        (tenant_id, approval_id),
        fetch_one=True,
    )
    if not row:
        return None
    return {
        "id": int(row[0]), "agent_identity": row[1], "action": row[2],
        "resource": row[3], "params": _as_json(row[4]), "params_hash": row[5],
        "risk_explanation": row[6], "triggering_policy": _as_json(row[7]),
        "status": row[8], "approver_user_id": int(row[9]) if row[9] is not None else None,
        "decided_at": row[10].isoformat() if row[10] else None,
        "created_at": row[11].isoformat() if row[11] else None,
    }


def list_pending(tenant_id: int, limit: int = 200) -> List[Dict[str, Any]]:
    rows = _get_db().execute_query(
        "SELECT id FROM approval_requests WHERE tenant_id = %s AND status = 'pending' "
        "ORDER BY created_at DESC LIMIT %s",
        (tenant_id, max(1, min(int(limit), 1000))),
        fetch_all=True,
    )
    return [get_approval(tenant_id, int(r[0])) for r in (rows or [])]


def _decide(tenant_id: int, approval_id: int, status: str, approver_user_id: int,
            events_repo) -> Optional[Dict[str, Any]]:
    db = _get_db()
    rows = db.execute_query(
        "UPDATE approval_requests SET status = %s, approver_user_id = %s, "
        "decided_at = CURRENT_TIMESTAMP WHERE tenant_id = %s AND id = %s AND status = 'pending'",
        (status, approver_user_id, tenant_id, approval_id),
    )
    if not rows:
        return None
    approval = get_approval(tenant_id, approval_id)
    es.emit(events_repo, tenant_id,
            "approval.granted" if status == "approved" else "approval.rejected",
            "zaf-approval", agent_id=approval["agent_identity"] if approval else None,
            action={"action": approval["action"] if approval else None,
                    "approver": approver_user_id},
            decision="ALLOW" if status == "approved" else "DENY",
            severity="MEDIUM")
    return approval


def approve(tenant_id: int, approval_id: int, approver_user_id: int, events_repo=None):
    if events_repo is None:
        from ..aro import events_repository as _er
        events_repo = _er
    return _decide(tenant_id, approval_id, "approved", approver_user_id, events_repo)


def reject(tenant_id: int, approval_id: int, approver_user_id: int, events_repo=None):
    if events_repo is None:
        from ..aro import events_repository as _er
        events_repo = _er
    return _decide(tenant_id, approval_id, "rejected", approver_user_id, events_repo)


def is_authorized(tenant_id: int, action: str, params: Optional[Dict[str, Any]]) -> bool:
    """Return True only when an *approved* approval exists for this exact action+params.

    A different params value hashes differently, so a prior approval for other
    params does not authorize this one (re-authorization required).
    """
    phash = gov.params_hash(action, params)
    row = _get_db().execute_query(
        "SELECT 1 FROM approval_requests WHERE tenant_id = %s AND params_hash = %s "
        "AND status = 'approved' LIMIT 1",
        (tenant_id, phash),
        fetch_one=True,
    )
    return bool(row)
