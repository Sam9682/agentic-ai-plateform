"""Durable agent task queue persistence (Task 10).

Pure-SQL data access over ``agent_tasks``. The claim uses
``FOR UPDATE SKIP LOCKED`` inside a single transaction (via
``db_manager.get_db_connection``) so concurrent workers never claim the same
task — the same no-double-execution guarantee the serverless worker relies on.
Idempotency is enforced by a partial unique index; submitting the same
``idempotency_key`` returns the existing task instead of creating a duplicate.
"""

from __future__ import annotations

import json
import uuid
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


def submit(
    tenant_id: int,
    agent_id: int,
    *,
    operation: str = "prompt",
    payload: Optional[Dict[str, Any]] = None,
    initiator_user_id: Optional[int] = None,
    priority: int = 100,
    max_attempts: int = 1,
    timeout_seconds: int = 1800,
    idempotency_key: Optional[str] = None,
    policy_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Enqueue a task; return it. Idempotent on (tenant, idempotency_key).

    When an idempotency key is supplied and a task already exists for it, the
    existing task is returned unchanged (no duplicate enqueue).
    """
    db = _get_db()
    if idempotency_key:
        existing = db.execute_query(
            "SELECT id FROM agent_tasks WHERE tenant_id = %s AND idempotency_key = %s",
            (tenant_id, idempotency_key),
            fetch_one=True,
        )
        if existing:
            return get_task(tenant_id, int(existing[0]))

    task_ref = f"task-{uuid.uuid4().hex[:12]}"
    row = db.execute_query(
        """
        INSERT INTO agent_tasks (
            tenant_id, agent_id, task_ref, operation, payload, initiator_user_id,
            priority, max_attempts, timeout_seconds, idempotency_key, policy_context
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            tenant_id, agent_id, task_ref, operation,
            json.dumps(payload or {}), initiator_user_id, priority,
            max_attempts, timeout_seconds, idempotency_key,
            json.dumps(policy_context or {}),
        ),
        fetch_one=True,
    )
    return get_task(tenant_id, int(row[0]))


_SELECT = (
    "SELECT id, tenant_id, agent_id, task_ref, operation, payload, "
    "initiator_user_id, priority, status, policy_context, result_ref, result, "
    "attempts, max_attempts, timeout_seconds, cancel_requested, worker_id, "
    "created_at, started_at, finished_at, idempotency_key FROM agent_tasks"
)


def _row(row: Any) -> Dict[str, Any]:
    return {
        "id": int(row[0]),
        "tenant_id": int(row[1]),
        "agent_id": int(row[2]),
        "task_ref": row[3],
        "operation": row[4],
        "payload": _as_json(row[5]),
        "initiator_user_id": int(row[6]) if row[6] is not None else None,
        "priority": int(row[7]),
        "status": row[8],
        "policy_context": _as_json(row[9]),
        "result_ref": row[10],
        "result": _as_json(row[11]),
        "attempts": int(row[12]),
        "max_attempts": int(row[13]),
        "timeout_seconds": int(row[14]),
        "cancel_requested": bool(row[15]),
        "worker_id": row[16],
        "created_at": row[17].isoformat() if row[17] else None,
        "started_at": row[18].isoformat() if row[18] else None,
        "finished_at": row[19].isoformat() if row[19] else None,
        "idempotency_key": row[20],
    }


def get_task(tenant_id: int, task_id: int) -> Optional[Dict[str, Any]]:
    row = _get_db().execute_query(
        f"{_SELECT} WHERE tenant_id = %s AND id = %s",
        (tenant_id, task_id),
        fetch_one=True,
    )
    return _row(row) if row else None


def list_tasks(tenant_id: int, agent_id: Optional[int] = None, limit: int = 100) -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit), 1000))
    if agent_id is not None:
        rows = _get_db().execute_query(
            f"{_SELECT} WHERE tenant_id = %s AND agent_id = %s ORDER BY created_at DESC LIMIT %s",
            (tenant_id, agent_id, limit),
            fetch_all=True,
        )
    else:
        rows = _get_db().execute_query(
            f"{_SELECT} WHERE tenant_id = %s ORDER BY created_at DESC LIMIT %s",
            (tenant_id, limit),
            fetch_all=True,
        )
    return [_row(r) for r in (rows or [])]


def claim_next_task(worker_id: str) -> Optional[Dict[str, Any]]:
    """Atomically claim one pending task across all tenants. No double-claim.

    Uses ``FOR UPDATE SKIP LOCKED`` within a transaction so concurrent workers
    each get a distinct task (or none). Returns the claimed task dict or None.
    """
    db = _get_db()
    with db.get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id FROM agent_tasks
                WHERE status = 'pending' AND cancel_requested = FALSE
                ORDER BY priority ASC, created_at ASC
                FOR UPDATE SKIP LOCKED
                LIMIT 1
                """
            )
            row = cur.fetchone()
            if not row:
                conn.commit()
                return None
            task_id = row[0]
            cur.execute(
                """
                UPDATE agent_tasks
                SET status = 'claimed', worker_id = %s, attempts = attempts + 1,
                    started_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (worker_id, task_id),
            )
            conn.commit()
    # Read back outside the claim txn (tenant known from the row).
    row2 = db.execute_query(f"{_SELECT} WHERE id = %s", (task_id,), fetch_one=True)
    return _row(row2) if row2 else None


def mark_running(task_id: int) -> None:
    _get_db().execute_query(
        "UPDATE agent_tasks SET status = 'running' WHERE id = %s", (task_id,)
    )


def complete(task_id: int, status: str, result: Optional[Dict[str, Any]] = None) -> None:
    """Record a terminal status + result for a task."""
    _get_db().execute_query(
        "UPDATE agent_tasks SET status = %s, result = %s, finished_at = CURRENT_TIMESTAMP WHERE id = %s",
        (status, json.dumps(result or {}), task_id),
    )


def request_cancel(tenant_id: int, task_id: int) -> bool:
    """Flag a task for cancellation (the worker observes and stops)."""
    rows = _get_db().execute_query(
        "UPDATE agent_tasks SET cancel_requested = TRUE WHERE tenant_id = %s AND id = %s "
        "AND status IN ('pending', 'claimed', 'running')",
        (tenant_id, task_id),
    )
    return bool(rows)


def is_cancel_requested(task_id: int) -> bool:
    row = _get_db().execute_query(
        "SELECT cancel_requested FROM agent_tasks WHERE id = %s", (task_id,), fetch_one=True
    )
    return bool(row[0]) if row else False
