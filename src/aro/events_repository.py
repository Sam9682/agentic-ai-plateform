"""Append-only persistence for the unified event stream (Task 2).

Pure-SQL data access over ``agent_events`` mirroring the repository style of
``runtime_monitor_repository.py``. The table is append-only by design: this
module exposes ``append_event`` and read helpers, and deliberately offers no
update or delete path, so immutable security audit records cannot be mutated
through the application.

All reads are tenant-scoped (the caller passes the resolved ``tenant_id`` from
``g.tenant_id``), enforcing tenant isolation at the data layer.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


def _dumps(value: Any) -> str:
    """Serialize a JSON-able value for a JSONB column."""
    return json.dumps(value if value is not None else {})


def _as_json(value: Any) -> Any:
    """Normalize a JSONB column that psycopg2 may hand back as text or object."""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def _get_db():
    """Return the shared db_manager (deferred import; no pool at import time)."""
    from ..database_postgres import db_manager
    return db_manager


def append_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """Append one event and return it augmented with its DB primary key.

    The event dict is the canonical shape produced by
    ``event_service.build_event`` (already redacted/validated). On a duplicate
    ``(tenant_id, event_id)`` the existing row is kept (ON CONFLICT DO NOTHING)
    and its id is fetched — append is therefore idempotent per business id.
    """
    db = _get_db()
    row = db.execute_query(
        """
        INSERT INTO agent_events (
            event_id, tenant_id, agent_id, execution_id, event_type, source,
            action, decision, risk_score, severity, correlation_id, occurred_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (tenant_id, event_id) DO NOTHING
        RETURNING id
        """,
        (
            event["event_id"],
            event["tenant_id"],
            event.get("agent_id"),
            event.get("execution_id"),
            event["event_type"],
            event["source"],
            _dumps(event.get("action")),
            event.get("decision"),
            int(event.get("risk_score") or 0),
            event.get("severity") or "INFO",
            event.get("correlation_id"),
            event.get("occurred_at"),
        ),
        fetch_one=True,
    )
    result = dict(event)
    if row is not None:
        result["id"] = int(row[0])
    else:
        # Conflict: fetch the existing row's id so callers still get a pk.
        existing = db.execute_query(
            "SELECT id FROM agent_events WHERE tenant_id = %s AND event_id = %s",
            (event["tenant_id"], event["event_id"]),
            fetch_one=True,
        )
        result["id"] = int(existing[0]) if existing else None
    return result


def _row_to_dict(row: Any) -> Dict[str, Any]:
    return {
        "id": int(row[0]),
        "event_id": row[1],
        "tenant_id": int(row[2]),
        "agent_id": row[3],
        "execution_id": row[4],
        "event_type": row[5],
        "source": row[6],
        "action": _as_json(row[7]),
        "decision": row[8],
        "risk_score": int(row[9]) if row[9] is not None else 0,
        "severity": row[10],
        "correlation_id": row[11],
        "occurred_at": row[12].isoformat() if row[12] else None,
    }


_SELECT = (
    "SELECT id, event_id, tenant_id, agent_id, execution_id, event_type, "
    "source, action, decision, risk_score, severity, correlation_id, occurred_at "
    "FROM agent_events"
)


def list_events(
    tenant_id: int,
    *,
    agent_id: Optional[str] = None,
    event_type: Optional[str] = None,
    severity: Optional[str] = None,
    correlation_id: Optional[str] = None,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    """Return tenant-scoped events (newest first), optionally filtered."""
    limit = max(1, min(int(limit), 2000))
    conditions = ["tenant_id = %s"]
    params: List[Any] = [tenant_id]
    if agent_id:
        conditions.append("agent_id = %s")
        params.append(agent_id)
    if event_type:
        conditions.append("event_type = %s")
        params.append(event_type)
    if severity:
        conditions.append("severity = %s")
        params.append(severity)
    if correlation_id:
        conditions.append("correlation_id = %s")
        params.append(correlation_id)
    where = " WHERE " + " AND ".join(conditions)
    params.append(limit)
    rows = _get_db().execute_query(
        f"{_SELECT}{where} ORDER BY occurred_at DESC, id DESC LIMIT %s",
        tuple(params),
        fetch_all=True,
    )
    return [_row_to_dict(r) for r in (rows or [])]


def get_agent_timeline(tenant_id: int, agent_id: str, limit: int = 200) -> List[Dict[str, Any]]:
    """Return an agent's event timeline (newest first), tenant-scoped."""
    return list_events(tenant_id, agent_id=agent_id, limit=limit)
