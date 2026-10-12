"""Repository layer for Runtime Security.

All PostgreSQL access for the runtime monitor goes through this module so the
rest of the package stays free of SQL. Every function uses the shared
``db_manager.execute_query`` interface, matching the conventions used by the
serverless and GPU features.

Tables (see ``migration/add_runtime_monitor.sql``):
    - runtime_containers    one row per discovered container (per server)
    - runtime_observations  time-series rows building per-container timelines
    - runtime_anomalies     alert-only anomalies
    - runtime_scan_runs     audit of each scan
"""

import json
import logging
from typing import Any, Dict, List, Optional

from ..database_postgres import db_manager

logger = logging.getLogger(__name__)


def _dumps(value: Any) -> str:
    """Serialize a Python value to a JSON string for a JSONB column."""
    return json.dumps(value if value is not None else [])


def upsert_container(
    server_id: int,
    container_id: str,
    name: Optional[str],
    image: Optional[str],
    runtime: Optional[str],
    state: str,
    is_platform_managed: bool,
    classification: str,
    confidence_score: float,
    classification_evidence: List[str],
    labels: Dict[str, Any],
) -> int:
    """Insert or update a discovered container and return its primary key.

    Keyed by ``(server_id, container_id)``. On a repeat sighting the row is
    updated in place (classification, state, labels, ``last_seen``) without
    creating duplicates, so ``first_seen`` is preserved.

    Returns:
        The ``runtime_containers.id`` primary key of the upserted row.
    """
    row = db_manager.execute_query(
        """
        INSERT INTO runtime_containers (
            server_id, container_id, name, image, runtime, state,
            is_platform_managed, classification, confidence_score,
            classification_evidence, labels, first_seen, last_seen
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        )
        ON CONFLICT (server_id, container_id) DO UPDATE SET
            name = EXCLUDED.name,
            image = EXCLUDED.image,
            runtime = EXCLUDED.runtime,
            state = EXCLUDED.state,
            is_platform_managed = EXCLUDED.is_platform_managed,
            classification = EXCLUDED.classification,
            confidence_score = EXCLUDED.confidence_score,
            classification_evidence = EXCLUDED.classification_evidence,
            labels = EXCLUDED.labels,
            last_seen = CURRENT_TIMESTAMP
        RETURNING id
        """,
        (
            server_id,
            container_id,
            name,
            image,
            runtime,
            state,
            is_platform_managed,
            classification,
            confidence_score,
            _dumps(classification_evidence),
            _dumps(labels if labels is not None else {}),
        ),
        fetch_one=True,
    )
    return int(row[0])


def record_observation(
    container_pk: int,
    cpu_percent: Optional[float],
    memory_bytes: Optional[int],
    pids: Optional[int],
    process_summary: List[Any],
    network_summary: Dict[str, Any],
    state: Optional[str],
) -> int:
    """Append a point-in-time observation for a container.

    Returns:
        The ``runtime_observations.id`` of the inserted row.
    """
    row = db_manager.execute_query(
        """
        INSERT INTO runtime_observations (
            container_pk, cpu_percent, memory_bytes, pids,
            process_summary, network_summary, state
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            container_pk,
            cpu_percent,
            memory_bytes,
            pids,
            _dumps(process_summary),
            _dumps(network_summary if network_summary is not None else {}),
            state,
        ),
        fetch_one=True,
    )
    return int(row[0])


def mark_containers_stopped(server_id: int, active_container_ids: List[str]) -> int:
    """Mark containers on a server as 'stopped' when no longer present.

    Any container row for ``server_id`` whose ``container_id`` is not in
    ``active_container_ids`` and is not already 'stopped' is transitioned to
    'stopped'. This captures disappearance between polls.

    Returns:
        The number of rows transitioned to 'stopped'.
    """
    if active_container_ids:
        placeholders = ",".join(["%s"] * len(active_container_ids))
        query = (
            "UPDATE runtime_containers SET state = 'stopped', "
            "last_seen = last_seen WHERE server_id = %s AND state != 'stopped' "
            f"AND container_id NOT IN ({placeholders})"
        )
        params = tuple([server_id] + list(active_container_ids))
    else:
        query = (
            "UPDATE runtime_containers SET state = 'stopped' "
            "WHERE server_id = %s AND state != 'stopped'"
        )
        params = (server_id,)
    affected = db_manager.execute_query(query, params)
    try:
        return int(affected or 0)
    except (TypeError, ValueError):
        return 0


def list_containers(
    classification: Optional[str] = None,
    state: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return the container inventory, optionally filtered.

    Args:
        classification: Optional filter ('probable_agent' or 'unclassified').
        state: Optional container state filter (e.g. 'running', 'stopped').

    Returns:
        A list of container dicts ordered by newest activity first.
    """
    conditions = []
    params: List[Any] = []
    if classification:
        conditions.append("rc.classification = %s")
        params.append(classification)
    if state:
        conditions.append("rc.state = %s")
        params.append(state)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    rows = db_manager.execute_query(
        f"""
        SELECT rc.id, rc.server_id, s.server_name, rc.container_id, rc.name,
               rc.image, rc.runtime, rc.state, rc.is_platform_managed,
               rc.classification, rc.confidence_score, rc.classification_evidence,
               rc.labels, rc.first_seen, rc.last_seen
        FROM runtime_containers rc
        LEFT JOIN servers s ON s.id = rc.server_id
        {where}
        ORDER BY rc.last_seen DESC
        """,
        tuple(params) if params else None,
        fetch_all=True,
    )
    return [_container_row_to_dict(r) for r in (rows or [])]


def get_container(container_pk: int) -> Optional[Dict[str, Any]]:
    """Return a single container by primary key, or None if not found."""
    row = db_manager.execute_query(
        """
        SELECT rc.id, rc.server_id, s.server_name, rc.container_id, rc.name,
               rc.image, rc.runtime, rc.state, rc.is_platform_managed,
               rc.classification, rc.confidence_score, rc.classification_evidence,
               rc.labels, rc.first_seen, rc.last_seen
        FROM runtime_containers rc
        LEFT JOIN servers s ON s.id = rc.server_id
        WHERE rc.id = %s
        """,
        (container_pk,),
        fetch_one=True,
    )
    return _container_row_to_dict(row) if row else None


def get_container_timeline(
    container_pk: int, limit: int = 200
) -> List[Dict[str, Any]]:
    """Return a container's observation timeline, newest first.

    Args:
        container_pk: The container primary key.
        limit: Maximum number of observations to return (clamped 1..1000).
    """
    limit = max(1, min(int(limit), 1000))
    rows = db_manager.execute_query(
        """
        SELECT id, cpu_percent, memory_bytes, pids, process_summary,
               network_summary, state, observed_at
        FROM runtime_observations
        WHERE container_pk = %s
        ORDER BY observed_at DESC
        LIMIT %s
        """,
        (container_pk, limit),
        fetch_all=True,
    )
    timeline = []
    for r in rows or []:
        timeline.append(
            {
                "id": int(r[0]),
                "cpu_percent": r[1],
                "memory_bytes": r[2],
                "pids": r[3],
                "process_summary": _as_json(r[4]),
                "network_summary": _as_json(r[5]),
                "state": r[6],
                "observed_at": r[7].isoformat() if r[7] else None,
            }
        )
    return timeline


def get_recent_observations(
    container_pk: int, limit: int = 10
) -> List[Dict[str, Any]]:
    """Return the most recent observations oldest-first for anomaly analysis."""
    timeline = get_container_timeline(container_pk, limit=limit)
    return list(reversed(timeline))


def record_anomaly(
    container_pk: int,
    rule_id: str,
    severity: str,
    evidence: List[str],
) -> int:
    """Persist an alert-only anomaly and return its id."""
    row = db_manager.execute_query(
        """
        INSERT INTO runtime_anomalies (container_pk, rule_id, severity, evidence)
        VALUES (%s, %s, %s, %s)
        RETURNING id
        """,
        (container_pk, rule_id, severity, _dumps(evidence)),
        fetch_one=True,
    )
    return int(row[0])


def has_open_anomaly(container_pk: int, rule_id: str) -> bool:
    """Return True if an open anomaly for this container+rule already exists.

    Used to avoid emitting duplicate alerts for the same ongoing condition on
    every scan cycle.
    """
    row = db_manager.execute_query(
        """
        SELECT 1 FROM runtime_anomalies
        WHERE container_pk = %s AND rule_id = %s AND status = 'open'
        LIMIT 1
        """,
        (container_pk, rule_id),
        fetch_one=True,
    )
    return bool(row)


def list_anomalies(status: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return anomalies with container context, optionally filtered by status."""
    conditions = []
    params: List[Any] = []
    if status:
        conditions.append("ra.status = %s")
        params.append(status)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    rows = db_manager.execute_query(
        f"""
        SELECT ra.id, ra.container_pk, rc.name, rc.container_id, ra.rule_id,
               ra.severity, ra.evidence, ra.status, ra.detected_at
        FROM runtime_anomalies ra
        LEFT JOIN runtime_containers rc ON rc.id = ra.container_pk
        {where}
        ORDER BY ra.detected_at DESC
        """,
        tuple(params) if params else None,
        fetch_all=True,
    )
    result = []
    for r in rows or []:
        result.append(
            {
                "id": int(r[0]),
                "container_pk": int(r[1]),
                "container_name": r[2],
                "container_id": r[3],
                "rule_id": r[4],
                "severity": r[5],
                "evidence": _as_json(r[6]),
                "status": r[7],
                "detected_at": r[8].isoformat() if r[8] else None,
            }
        )
    return result


def count_open_anomalies() -> int:
    """Return the number of open anomalies across all containers."""
    row = db_manager.execute_query(
        "SELECT COUNT(*) FROM runtime_anomalies WHERE status = 'open'",
        fetch_one=True,
    )
    return int(row[0]) if row else 0


def summary_counts() -> Dict[str, int]:
    """Return summary metrics for the Runtime Security dashboard."""
    row = db_manager.execute_query(
        """
        SELECT
            COUNT(*) FILTER (WHERE state != 'stopped') AS monitored,
            COUNT(*) FILTER (WHERE classification = 'probable_agent'
                             AND state != 'stopped') AS probable_agents
        FROM runtime_containers
        """,
        fetch_one=True,
    )
    monitored = int(row[0]) if row and row[0] is not None else 0
    probable = int(row[1]) if row and row[1] is not None else 0
    return {
        "containers_monitored": monitored,
        "probable_agents": probable,
        "active_anomalies": count_open_anomalies(),
    }


def start_scan_run(server_id: Optional[int]) -> int:
    """Create a scan-run audit record and return its id."""
    row = db_manager.execute_query(
        "INSERT INTO runtime_scan_runs (server_id) VALUES (%s) RETURNING id",
        (server_id,),
        fetch_one=True,
    )
    return int(row[0])


def finish_scan_run(
    scan_run_id: int, containers_seen: int, error: Optional[str] = None
) -> None:
    """Finalize a scan-run audit record with results."""
    db_manager.execute_query(
        """
        UPDATE runtime_scan_runs
        SET finished_at = CURRENT_TIMESTAMP, containers_seen = %s, error = %s
        WHERE id = %s
        """,
        (containers_seen, error, scan_run_id),
    )


def _as_json(value: Any) -> Any:
    """Return a JSON value as a Python object regardless of driver typing.

    psycopg2 may hand back JSONB as an already-parsed object or as text
    depending on configuration; normalize both.
    """
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def _container_row_to_dict(row: Any) -> Dict[str, Any]:
    """Map a container SELECT row to a serializable dict."""
    return {
        "id": int(row[0]),
        "server_id": int(row[1]) if row[1] is not None else None,
        "server_name": row[2],
        "container_id": row[3],
        "name": row[4],
        "image": row[5],
        "runtime": row[6],
        "state": row[7],
        "is_platform_managed": bool(row[8]),
        "classification": row[9],
        "confidence_score": float(row[10]) if row[10] is not None else 0.0,
        "classification_evidence": _as_json(row[11]),
        "labels": _as_json(row[12]),
        "first_seen": row[13].isoformat() if row[13] else None,
        "last_seen": row[14].isoformat() if row[14] else None,
    }
