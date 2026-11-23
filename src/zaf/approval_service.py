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
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create (or return existing) pending approval bound to action+params.

    The approval is bound to the exact action + params (``params_hash``), to the
    requesting agent identity and, when given, to the session. If an unexpired
    pending approval already exists for the same binding, it is returned rather
    than duplicated.
    """
    if events_repo is None:
        from ..aro import events_repository as _er
        events_repo = _er

    phash = gov.params_hash(action, params)
    db = _get_db()
    existing = db.execute_query(
        "SELECT id FROM approval_requests WHERE tenant_id = %s AND params_hash = %s "
        "AND status = 'pending' AND agent_identity IS NOT DISTINCT FROM %s "
        "AND session_id IS NOT DISTINCT FROM %s "
        "AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)",
        (tenant_id, phash, agent_identity, session_id),
        fetch_one=True,
    )
    if existing:
        return get_approval(tenant_id, int(existing[0]))

    expires_at = datetime.now(timezone.utc) + timedelta(seconds=max(1, int(ttl_seconds)))
    row = db.execute_query(
        """
        INSERT INTO approval_requests (
            tenant_id, agent_identity, action, resource, params, params_hash,
            risk_explanation, triggering_policy, expires_at, session_id
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            tenant_id, agent_identity, action, resource, json.dumps(params or {}),
            phash, risk_explanation,
            json.dumps(triggering_policy) if triggering_policy is not None else None,
            expires_at, session_id,
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
        "decided_at, created_at, expires_at, session_id, consumed_at, consumed_by "
        "FROM approval_requests "
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
        "expires_at": _iso(row[12]) if len(row) > 12 else None,
        "session_id": row[13] if len(row) > 13 else None,
        "consumed_at": _iso(row[14]) if len(row) > 14 else None,
        "consumed_by": row[15] if len(row) > 15 else None,
    }


def _iso(value: Any) -> Optional[str]:
    return value.isoformat() if hasattr(value, "isoformat") else value


def expire_stale(tenant_id: int) -> int:
    """Mark pending approvals past their expiry as ``expired``."""
    return _get_db().execute_query(
        "UPDATE approval_requests SET status = 'expired' WHERE tenant_id = %s "
        "AND status = 'pending' AND expires_at IS NOT NULL "
        "AND expires_at <= CURRENT_TIMESTAMP",
        (tenant_id,),
    ) or 0


def list_pending(tenant_id: int, limit: int = 200) -> List[Dict[str, Any]]:
    try:
        expire_stale(tenant_id)
    except Exception:  # noqa: BLE001 - listing must still work read-only
        pass
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
        "decided_at = CURRENT_TIMESTAMP WHERE tenant_id = %s AND id = %s AND status = 'pending' "
        "AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)",
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


_ANY = object()


def is_authorized(tenant_id: int, action: str, params: Optional[Dict[str, Any]],
                  *, agent_identity: Any = _ANY) -> bool:
    """Return True when a *usable* approval exists for this exact action+params.

    Usable = approved, not expired, not yet consumed and, when
    ``agent_identity`` is given, bound to that agent. Read-only: it does not
    consume the approval. Enforcement points use :func:`consume_authorization`,
    which is single-use (finding F4).

    A different params value hashes differently, so a prior approval for other
    params does not authorize this one (re-authorization required).
    """
    phash = gov.params_hash(action, params)
    sql = ("SELECT 1 FROM approval_requests WHERE tenant_id = %s AND params_hash = %s "
           "AND status = 'approved' AND consumed_at IS NULL "
           "AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)")
    args: tuple = (tenant_id, phash)
    if agent_identity is not _ANY:
        sql += " AND agent_identity IS NOT DISTINCT FROM %s"
        args = args + (agent_identity,)
    row = _get_db().execute_query(sql + " LIMIT 1", args, fetch_one=True)
    return bool(row)


def consume_authorization(
    tenant_id: int,
    action: str,
    params: Optional[Dict[str, Any]],
    *,
    agent_identity: Optional[str],
    session_id: Optional[str] = None,
    consumer: str = "",
    events_repo=None,
) -> Optional[int]:
    """Atomically consume one usable approval; return its id, or None.

    One statement, so it is race-free: the inner ``FOR UPDATE SKIP LOCKED``
    lets exactly one concurrent caller take a given approval and the outer
    ``consumed_at IS NULL`` re-check guards against a lost update. Binding:
    exact params hash, same agent identity, same session when the approval was
    issued for a session, unexpired.
    """
    phash = gov.params_hash(action, params)
    row = _get_db().execute_query(
        """
        UPDATE approval_requests SET consumed_at = CURRENT_TIMESTAMP, consumed_by = %s
        WHERE id = (
            SELECT id FROM approval_requests
            WHERE tenant_id = %s AND params_hash = %s AND status = 'approved'
              AND consumed_at IS NULL
              AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
              AND agent_identity IS NOT DISTINCT FROM %s
              AND (session_id IS NULL OR session_id = %s)
            ORDER BY decided_at
            LIMIT 1
            FOR UPDATE SKIP LOCKED
        ) AND consumed_at IS NULL
        RETURNING id
        """,
        ((consumer or "")[:255], tenant_id, phash, agent_identity, session_id),
        fetch_one=True,
    )
    if not row:
        return None
    approval_id = int(row[0])
    if events_repo is None:
        from ..aro import events_repository as _er
        events_repo = _er
    try:
        es.emit(events_repo, tenant_id, "approval.consumed", "zaf-approval",
                agent_id=agent_identity,
                action={"action": action, "approval_id": approval_id,
                        "session_id": session_id, "consumer": consumer},
                decision="ALLOW", severity="MEDIUM")
    except Exception:  # noqa: BLE001 - consumption already happened; audit best effort
        pass
    return approval_id
