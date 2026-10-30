"""Persistence for observability anomalies + security incidents (Task 16/17).

Pure-SQL access over ``agent_anomalies`` and ``security_incidents``,
tenant-scoped, in the repository style of the rest of the codebase.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


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


def record_anomaly(
    tenant_id: int, agent_identity: Optional[str], rule_id: str,
    severity: str, risk_score: int, evidence: List[str],
) -> int:
    row = _get_db().execute_query(
        """
        INSERT INTO agent_anomalies (tenant_id, agent_identity, rule_id, severity, risk_score, evidence)
        VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
        """,
        (tenant_id, agent_identity, rule_id, severity, int(risk_score), json.dumps(evidence or [])),
        fetch_one=True,
    )
    return int(row[0])


def list_anomalies(tenant_id: int, limit: int = 200) -> List[Dict[str, Any]]:
    rows = _get_db().execute_query(
        "SELECT id, agent_identity, rule_id, severity, risk_score, evidence, status, detected_at "
        "FROM agent_anomalies WHERE tenant_id = %s ORDER BY detected_at DESC LIMIT %s",
        (tenant_id, max(1, min(int(limit), 1000))),
        fetch_all=True,
    )
    return [
        {"id": int(r[0]), "agent_identity": r[1], "rule_id": r[2], "severity": r[3],
         "risk_score": int(r[4]), "evidence": _as_json(r[5]), "status": r[6],
         "detected_at": r[7].isoformat() if r[7] else None}
        for r in (rows or [])
    ]


def create_incident(
    tenant_id: int, agent_identity: Optional[str], kind: str, severity: str,
    summary: str, *, detail: Optional[Dict[str, Any]] = None,
    actions_taken: Optional[List[str]] = None,
) -> int:
    row = _get_db().execute_query(
        """
        INSERT INTO security_incidents
            (tenant_id, agent_identity, kind, severity, summary, detail, actions_taken, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'open') RETURNING id
        """,
        (tenant_id, agent_identity, kind, severity, summary,
         json.dumps(detail or {}), json.dumps(actions_taken or [])),
        fetch_one=True,
    )
    return int(row[0])


def set_incident_status(tenant_id: int, incident_id: int, status: str,
                        actions_taken: Optional[List[str]] = None) -> bool:
    if actions_taken is not None:
        rows = _get_db().execute_query(
            "UPDATE security_incidents SET status = %s, actions_taken = %s "
            "WHERE tenant_id = %s AND id = %s",
            (status, json.dumps(actions_taken), tenant_id, incident_id),
        )
    else:
        rows = _get_db().execute_query(
            "UPDATE security_incidents SET status = %s WHERE tenant_id = %s AND id = %s",
            (status, tenant_id, incident_id),
        )
    return bool(rows)


def list_incidents(tenant_id: int, limit: int = 200) -> List[Dict[str, Any]]:
    rows = _get_db().execute_query(
        "SELECT id, agent_identity, kind, severity, summary, detail, actions_taken, status, created_at "
        "FROM security_incidents WHERE tenant_id = %s ORDER BY created_at DESC LIMIT %s",
        (tenant_id, max(1, min(int(limit), 1000))),
        fetch_all=True,
    )
    return [
        {"id": int(r[0]), "agent_identity": r[1], "kind": r[2], "severity": r[3],
         "summary": r[4], "detail": _as_json(r[5]), "actions_taken": _as_json(r[6]),
         "status": r[7], "created_at": r[8].isoformat() if r[8] else None}
        for r in (rows or [])
    ]
