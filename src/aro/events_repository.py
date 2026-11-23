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
    from .event_service import INGEST_CONTROL_PLANE, category_for_event_type

    db = _get_db()
    # Legacy emitters do not set a category: derive it from the event type so
    # every row is classifiable in the normalized taxonomy.
    category = event.get("category") or category_for_event_type(event.get("event_type"))
    row = db.execute_query(
        """
        INSERT INTO agent_events (
            event_id, tenant_id, agent_id, execution_id, event_type, source,
            action, decision, risk_score, severity, correlation_id, occurred_at,
            trace_id, session_id, task_id, parent_event_id, category,
            normalized_action, resource, outcome, duration_ms,
            ingest_source, ingest_principal
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                  %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
            event.get("trace_id"),
            event.get("session_id"),
            event.get("task_id"),
            event.get("parent_event_id"),
            category,
            event.get("normalized_action"),
            event.get("resource"),
            event.get("outcome"),
            event.get("duration_ms"),
            event.get("ingest_source") or INGEST_CONTROL_PLANE,
            event.get("ingest_principal"),
        ),
        fetch_one=True,
    )
    result = dict(event)
    # ``inserted`` is False when the (tenant_id, event_id) already existed: the
    # caller can tell a replayed/duplicate event from a new one.
    result["inserted"] = row is not None
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


# --------------------------------------------------------------------------- #
# Normalized, paginated event query (ABF/AET event foundation)
# --------------------------------------------------------------------------- #
MAX_PAGE_SIZE = 500

_SELECT_EXT = (
    "SELECT id, event_id, tenant_id, agent_id, execution_id, event_type, "
    "source, action, decision, risk_score, severity, correlation_id, occurred_at, "
    "trace_id, session_id, task_id, parent_event_id, category, normalized_action, "
    "resource, outcome, duration_ms, ingest_source, ingest_principal "
    "FROM agent_events"
)

# Filterable columns -> exact-match SQL fragment. Values are always bound as
# parameters; only these fixed column names are interpolated.
_EXACT_FILTERS = (
    "agent_id", "event_type", "severity", "correlation_id", "trace_id",
    "session_id", "task_id", "category", "outcome", "ingest_source",
)


def _row_to_dict_ext(row: Any) -> Dict[str, Any]:
    base = _row_to_dict(row[:13])
    base.update({
        "trace_id": row[13],
        "session_id": row[14],
        "task_id": row[15],
        "parent_event_id": row[16],
        "category": row[17],
        "normalized_action": row[18],
        "resource": row[19],
        "outcome": row[20],
        "duration_ms": int(row[21]) if row[21] is not None else None,
        "ingest_source": row[22],
        "ingest_principal": row[23],
    })
    return base


def encode_cursor(occurred_at_iso: Optional[str], row_id: Optional[int]) -> Optional[str]:
    """Opaque keyset cursor ``<iso-timestamp>|<id>`` (None when no next page)."""
    if not occurred_at_iso or row_id is None:
        return None
    return f"{occurred_at_iso}|{int(row_id)}"


def decode_cursor(cursor: Optional[str]):
    """Return ``(occurred_at_iso, id)`` or ``None``; raise ValueError if malformed."""
    if not cursor:
        return None
    ts, sep, rid = str(cursor).rpartition("|")
    if not sep or not ts:
        raise ValueError("malformed cursor")
    from datetime import datetime as _dt
    _dt.fromisoformat(ts)  # validates the timestamp; raises ValueError
    return ts, int(rid)


def query_events(
    tenant_id: int,
    *,
    filters: Optional[Dict[str, Any]] = None,
    min_severity: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    search: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: int = 100,
    order: str = "desc",
) -> Dict[str, Any]:
    """Tenant-scoped, keyset-paginated event query over the normalized fields.

    Returns ``{"events": [...], "next_cursor": str|None}``. The page size is
    bounded by :data:`MAX_PAGE_SIZE` so no query is unbounded. ``order`` is
    ``desc`` (newest first, default) or ``asc`` (chronological, for timelines).
    ``search`` matches ``normalized_action`` / ``resource`` case-insensitively.
    """
    from .event_service import VALID_SEVERITIES

    limit = max(1, min(int(limit), MAX_PAGE_SIZE))
    asc = str(order).lower() == "asc"
    conditions = ["tenant_id = %s"]
    params: List[Any] = [tenant_id]
    for column in _EXACT_FILTERS:
        value = (filters or {}).get(column)
        if value not in (None, ""):
            conditions.append(f"{column} = %s")
            params.append(value)
    if min_severity and str(min_severity).upper() in VALID_SEVERITIES:
        idx = VALID_SEVERITIES.index(str(min_severity).upper())
        conditions.append("severity IN (" + ", ".join(["%s"] * (len(VALID_SEVERITIES) - idx)) + ")")
        params.extend(VALID_SEVERITIES[idx:])
    if since:
        conditions.append("occurred_at >= %s")
        params.append(since)
    if until:
        conditions.append("occurred_at <= %s")
        params.append(until)
    if search:
        like = "%" + str(search).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")[:200] + "%"
        conditions.append("(normalized_action ILIKE %s OR resource ILIKE %s)")
        params.extend([like, like])
    decoded = decode_cursor(cursor)
    if decoded is not None:
        op = ">" if asc else "<"
        conditions.append(f"(occurred_at, id) {op} (%s, %s)")
        params.extend([decoded[0], decoded[1]])
    direction = "ASC" if asc else "DESC"
    params.append(limit + 1)  # fetch one extra row to know if a next page exists
    rows = _get_db().execute_query(
        f"{_SELECT_EXT} WHERE {' AND '.join(conditions)} "
        f"ORDER BY occurred_at {direction}, id {direction} LIMIT %s",
        tuple(params),
        fetch_all=True,
    ) or []
    events = [_row_to_dict_ext(r) for r in rows[:limit]]
    next_cursor = None
    if len(rows) > limit and events:
        last = events[-1]
        next_cursor = encode_cursor(last["occurred_at"], last["id"])
    return {"events": events, "next_cursor": next_cursor}
