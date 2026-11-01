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
from typing import Any, Dict, Iterable, List, Mapping, Optional


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
    "created_at, started_at, finished_at, idempotency_key, "
    "deadline, lease_expires_at, heartbeat_at FROM agent_tasks"
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
        # Phase 2 additive columns (all TIMESTAMP WITH TIME ZONE; nullable).
        "deadline": row[21].isoformat() if row[21] else None,
        "lease_expires_at": row[22].isoformat() if row[22] else None,
        "heartbeat_at": row[23].isoformat() if row[23] else None,
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


#: Default lease time-to-live (seconds) a claim grants before a task is
#: considered reclaimable by the reaper. The worker renews the lease via
#: ``heartbeat`` at an interval shorter than this (Req 6.5).
DEFAULT_LEASE_TTL_SECONDS = 60


def pick_next_tenant(
    pending_by_tenant: "Iterable[Any] | Mapping[Any, int]",
    last_served: Optional[Any] = None,
) -> Optional[Any]:
    """Round-robin the next tenant to serve so no tenant is starved (Req 6.10).

    Pure and deterministic. Given the tenants that currently have pending work
    and the tenant served on the previous pick, return the tenant to serve next.

    Args:
        pending_by_tenant: The tenants with pending tasks. May be any iterable
            of ``tenant_id`` values (list/set/tuple) or a mapping
            ``{tenant_id: pending_count}``; only tenants with a positive count
            are eligible when a mapping is given.
        last_served: The ``tenant_id`` returned on the previous pick, or
            ``None`` for the first pick.

    Returns:
        The next ``tenant_id`` to serve, or ``None`` when no tenant has pending
        work.

    Selection rule (stable, cyclic):
        Order the eligible tenants ascending. Starting from the position *after*
        ``last_served`` in that order, return the first tenant, wrapping around
        to the lowest. When ``last_served`` is ``None`` or no longer has pending
        work (so it is absent from the ordering), start from the lowest tenant.

    Because the cursor always advances past ``last_served`` and wraps, each
    tenant with pending work is reached within one full cycle (at most N picks
    for N pending tenants) — i.e. no tenant's backlog can indefinitely starve
    another's. Property 29 (task 13.8) asserts this bound.
    """
    if isinstance(pending_by_tenant, Mapping):
        eligible = sorted(t for t, count in pending_by_tenant.items() if count and int(count) > 0)
    else:
        eligible = sorted(set(pending_by_tenant))

    if not eligible:
        return None

    if last_served is None:
        return eligible[0]

    # Advance to the first tenant strictly greater than last_served; if none is
    # greater (last_served is >= the max, or absent/largest), wrap to the lowest.
    for tenant in eligible:
        if tenant > last_served:
            return tenant
    return eligible[0]


def pending_tenants() -> Dict[Any, int]:
    """Return ``{tenant_id: pending_count}`` for tenants with claimable work.

    Lightweight discovery source for per-tenant fairness (Req 6.10): the worker
    (task 14.4) feeds this into :func:`pick_next_tenant` to compute the round-
    robin preferred tenant before claiming. Only ``pending`` rows that are not
    cancel-requested are counted — exactly the rows :func:`claim_next_task`
    considers. Returns an empty mapping when nothing is claimable.
    """
    rows = _get_db().execute_query(
        "SELECT tenant_id, COUNT(*) FROM agent_tasks "
        "WHERE status = 'pending' AND cancel_requested = FALSE "
        "GROUP BY tenant_id"
    )
    return {r[0]: int(r[1]) for r in (rows or [])}


def claim_next_task(
    worker_id: str,
    *,
    lease_ttl: int = DEFAULT_LEASE_TTL_SECONDS,
    preferred_tenant: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """Atomically claim one pending task across all tenants. No double-claim.

    Uses ``FOR UPDATE SKIP LOCKED`` within a transaction so concurrent workers
    each get a distinct task (or none). The claim also grants a lease
    (``lease_expires_at = now + lease_ttl``) and stamps ``heartbeat_at = now``
    so the reaper can reclaim the task if the owning worker dies without
    renewing (Req 6.5). Returns the claimed task dict or None.

    Per-tenant fairness (Req 6.10): when ``preferred_tenant`` is supplied, the
    candidate pending tasks are ordered by ``(tenant_rank, priority, created_at)``
    where ``tenant_rank`` is ``0`` for the preferred tenant (the round-robin
    cursor from :func:`pick_next_tenant`) and ``1`` for every other tenant, so
    the preferred tenant's work sorts first and one tenant's backlog cannot
    starve another's. With no ``preferred_tenant`` the ordering stays
    ``priority ASC, created_at ASC`` (backward compatible). The worker wiring
    (task 14.4) tracks ``last_served`` and passes the preferred tenant here.
    """
    db = _get_db()
    lease_ttl = max(1, int(lease_ttl))
    with db.get_db_connection() as conn:
        with conn.cursor() as cur:
            if preferred_tenant is None:
                cur.execute(
                    """
                    SELECT id FROM agent_tasks
                    WHERE status = 'pending' AND cancel_requested = FALSE
                    ORDER BY priority ASC, created_at ASC
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                    """
                )
            else:
                cur.execute(
                    """
                    SELECT id FROM agent_tasks
                    WHERE status = 'pending' AND cancel_requested = FALSE
                    ORDER BY (tenant_id = %s) DESC, priority ASC, created_at ASC
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                    """,
                    (preferred_tenant,),
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
                    started_at = CURRENT_TIMESTAMP,
                    lease_expires_at = CURRENT_TIMESTAMP + (%s * INTERVAL '1 second'),
                    heartbeat_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (worker_id, lease_ttl, task_id),
            )
            conn.commit()
    # Read back outside the claim txn (tenant known from the row).
    row2 = db.execute_query(f"{_SELECT} WHERE id = %s", (task_id,), fetch_one=True)
    return _row(row2) if row2 else None


def heartbeat(
    tenant_id: int, task_id: int, *, lease_ttl: int = DEFAULT_LEASE_TTL_SECONDS
) -> bool:
    """Renew a claimed/running task's lease. Tenant-scoped (Req 6.5).

    Extends ``lease_expires_at`` to ``now + lease_ttl`` and stamps
    ``heartbeat_at = now`` so that a worker which keeps heart-beating (at an
    interval shorter than ``lease_ttl``) always holds a lease whose expiry is
    strictly in the future, and is therefore never reclaimed by the reaper.
    Returns True when a matching claimed/running row was updated.
    """
    lease_ttl = max(1, int(lease_ttl))
    rows = _get_db().execute_query(
        "UPDATE agent_tasks "
        "SET lease_expires_at = CURRENT_TIMESTAMP + (%s * INTERVAL '1 second'), "
        "    heartbeat_at = CURRENT_TIMESTAMP "
        "WHERE tenant_id = %s AND id = %s AND status IN ('claimed', 'running')",
        (lease_ttl, tenant_id, task_id),
    )
    return bool(rows)


def reap_expired_leases() -> List[Dict[str, Any]]:
    """Identify claimed/running tasks whose lease has expired (Req 6.6, 6.7).

    Selects the expired rows with ``FOR UPDATE SKIP LOCKED`` inside a single
    transaction (mirroring ``claim_next_task``'s connection/txn pattern) so a
    concurrent reaper never double-processes the same row. This step only
    *identifies* the dead-worker tasks; the actual re-enqueue-vs-finalize
    decision (bounded by ``max_attempts``) is applied per row via
    ``reenqueue_or_finalize``. Returns a list of expired task dicts carrying at
    least ``id``, ``tenant_id``, ``attempts``, ``max_attempts``, ``status`` plus
    ``task_ref`` and ``agent_id`` so the reaper can emit a correlated task
    lifecycle event (Req 6.12) without a second round-trip to load the row.
    """
    db = _get_db()
    expired: List[Dict[str, Any]] = []
    with db.get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, tenant_id, attempts, max_attempts, status,
                       task_ref, agent_id
                FROM agent_tasks
                WHERE status IN ('claimed', 'running')
                  AND lease_expires_at IS NOT NULL
                  AND lease_expires_at < CURRENT_TIMESTAMP
                FOR UPDATE SKIP LOCKED
                """
            )
            rows = cur.fetchall() or []
            for r in rows:
                expired.append({
                    "id": int(r[0]),
                    "tenant_id": int(r[1]),
                    "attempts": int(r[2]),
                    "max_attempts": int(r[3]),
                    "status": r[4],
                    "task_ref": r[5],
                    "agent_id": int(r[6]) if r[6] is not None else None,
                })
            conn.commit()
    return expired


def reenqueue_or_finalize(
    tenant_id: int,
    task_id: int,
    terminal_status: str,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Re-enqueue a non-success task or finalize it, bounded by max_attempts.

    Consults ``attempts`` vs ``max_attempts`` in one tenant-scoped UPDATE:

    * ``attempts < max_attempts`` → return the task to ``pending`` for another
      attempt, clearing ``worker_id``/``lease_expires_at``/``heartbeat_at`` while
      keeping ``attempts`` (Req 6.3, 6.6). Outcome ``"reenqueued"``.
    * ``attempts >= max_attempts`` → leave the task in ``terminal_status`` (e.g.
      ``failed`` for lease expiry) recording ``reason`` in ``result`` and
      stamping ``finished_at``, without re-enqueue (Req 6.4, 6.7). Outcome
      ``"finalized"``.

    Returns a dict ``{"outcome": "reenqueued"|"finalized"|"noop", "status": ...,
    "attempts": ..., "max_attempts": ...}`` so the worker and tests can assert.
    """
    db = _get_db()
    row = db.execute_query(
        "SELECT attempts, max_attempts FROM agent_tasks WHERE tenant_id = %s AND id = %s",
        (tenant_id, task_id),
        fetch_one=True,
    )
    if not row:
        return {"outcome": "noop", "status": None, "attempts": None, "max_attempts": None}

    attempts = int(row[0])
    max_attempts = int(row[1])

    if attempts < max_attempts:
        db.execute_query(
            "UPDATE agent_tasks "
            "SET status = 'pending', worker_id = NULL, "
            "    lease_expires_at = NULL, heartbeat_at = NULL "
            "WHERE tenant_id = %s AND id = %s",
            (tenant_id, task_id),
        )
        return {
            "outcome": "reenqueued",
            "status": "pending",
            "attempts": attempts,
            "max_attempts": max_attempts,
        }

    result = {"reason": reason} if reason is not None else {}
    db.execute_query(
        "UPDATE agent_tasks "
        "SET status = %s, result = %s, finished_at = CURRENT_TIMESTAMP "
        "WHERE tenant_id = %s AND id = %s",
        (terminal_status, json.dumps(result), tenant_id, task_id),
    )
    return {
        "outcome": "finalized",
        "status": terminal_status,
        "attempts": attempts,
        "max_attempts": max_attempts,
    }


def mark_running(tenant_id: int, task_id: int) -> bool:
    """Mark a claimed task running. Tenant-scoped (Req 6.8)."""
    rows = _get_db().execute_query(
        "UPDATE agent_tasks SET status = 'running' WHERE tenant_id = %s AND id = %s",
        (tenant_id, task_id),
    )
    return bool(rows)


def complete(
    tenant_id: int, task_id: int, status: str, result: Optional[Dict[str, Any]] = None
) -> bool:
    """Record a terminal status + result for a task. Tenant-scoped (Req 6.8)."""
    rows = _get_db().execute_query(
        "UPDATE agent_tasks SET status = %s, result = %s, finished_at = CURRENT_TIMESTAMP "
        "WHERE tenant_id = %s AND id = %s",
        (status, json.dumps(result or {}), tenant_id, task_id),
    )
    return bool(rows)


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
