"""Tamper-evident hash chain over ``agent_events`` (per tenant).

The chain makes **tampering detectable**; it does not make the log immutable.
See ``migration/add_audit_chain.sql`` for what the database enforces (no
content UPDATE, no UPDATE of a sealed row) and for the residual risks
(superuser rewrite, DELETE, tail truncation).

* :func:`seal` assigns ``chain_seq`` / ``prev_hash`` / ``record_hash`` to the
  tenant's unsealed events, in id order, inside one transaction serialized by a
  per-tenant advisory lock. Inserts never wait on it.
* :func:`verify` recomputes every hash in ``chain_seq`` order and reports the
  first break (gap, broken link or modified content) plus the head hash, which
  operators can export and compare with an external copy.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence

GENESIS = "0" * 64
CHAIN_VERSION = "aec-1"
_LOCK_NAMESPACE = 727001  # first key of pg_advisory_xact_lock(int, int)

#: Columns covered by the hash, in a fixed order. Adding a column later must
#: bump CHAIN_VERSION and keep hashing old rows with the old list.
HASHED_COLUMNS: Sequence[str] = (
    "id", "event_id", "tenant_id", "agent_id", "execution_id", "event_type", "source",
    "action", "decision", "risk_score", "severity", "correlation_id", "occurred_at",
    "trace_id", "session_id", "task_id", "parent_event_id", "category",
    "normalized_action", "resource", "outcome", "duration_ms", "ingest_source",
    "ingest_principal",
)
_SELECT_COLS = ", ".join(HASHED_COLUMNS)


def _norm(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, str) and value[:1] in "{[":
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def canonical(row: Dict[str, Any]) -> str:
    body = {col: _norm(row.get(col)) for col in HASHED_COLUMNS}
    body["_v"] = CHAIN_VERSION
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      default=str)


def record_hash(prev_hash: str, row: Dict[str, Any]) -> str:
    return hashlib.sha256((prev_hash + "\n" + canonical(row)).encode("utf-8")).hexdigest()


def _row(values: Sequence[Any]) -> Dict[str, Any]:
    return dict(zip(HASHED_COLUMNS, values))


def _default_conn():
    from ..database_postgres import db_manager
    return db_manager.get_db_connection()


def _default_db():
    from ..database_postgres import db_manager
    return db_manager


def seal(tenant_id: int, *, batch_size: int = 1000,
         connection: Optional[Callable[[], Any]] = None) -> Dict[str, Any]:
    """Seal up to ``batch_size`` unsealed events of the tenant. Returns counts."""
    connection = connection or _default_conn
    sealed = 0
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s, %s)",
                        (_LOCK_NAMESPACE, int(tenant_id) % 2147483647))
            cur.execute(
                "SELECT chain_seq, record_hash FROM agent_events "
                "WHERE tenant_id = %s AND chain_seq IS NOT NULL "
                "ORDER BY chain_seq DESC LIMIT 1",
                (tenant_id,),
            )
            head = cur.fetchone()
            seq = int(head[0]) if head else 0
            prev = head[1] if head else GENESIS
            cur.execute(
                f"SELECT {_SELECT_COLS} FROM agent_events "
                "WHERE tenant_id = %s AND record_hash IS NULL ORDER BY id LIMIT %s",
                (tenant_id, int(batch_size)),
            )
            rows = cur.fetchall() or []
            for values in rows:
                row = _row(values)
                seq += 1
                h = record_hash(prev, row)
                cur.execute(
                    "UPDATE agent_events SET chain_seq = %s, prev_hash = %s, record_hash = %s "
                    "WHERE tenant_id = %s AND id = %s AND record_hash IS NULL",
                    (seq, prev, h, tenant_id, row["id"]),
                )
                prev = h
                sealed += 1
        conn.commit()
    return {"sealed": sealed, "head_seq": seq, "head_hash": prev}


def safe_seal(tenant_id: int, **kw) -> Optional[Dict[str, Any]]:
    """Best-effort seal: sealing must never break the caller's primary path."""
    try:
        return seal(tenant_id, **kw)
    except Exception:  # noqa: BLE001
        return None


def verify(tenant_id: int, *, page_size: int = 2000, max_rows: int = 200_000,
           db=None) -> Dict[str, Any]:
    """Recompute the tenant's chain. Read-only."""
    db = db or _default_db()
    expected_seq = 1
    prev = GENESIS
    checked = 0
    first_break: Optional[Dict[str, Any]] = None
    while checked < max_rows:
        rows = db.execute_query(
            f"SELECT chain_seq, prev_hash, record_hash, {_SELECT_COLS} FROM agent_events "
            "WHERE tenant_id = %s AND chain_seq IS NOT NULL AND chain_seq >= %s "
            "ORDER BY chain_seq LIMIT %s",
            (tenant_id, expected_seq, int(page_size)),
            fetch_all=True,
        ) or []
        if not rows:
            break
        for r in rows:
            seq, stored_prev, stored_hash = int(r[0]), r[1], r[2]
            row = _row(r[3:])
            if seq != expected_seq:
                first_break = {"chain_seq": expected_seq, "reason": "missing_record",
                               "detail": f"next sealed record is {seq}"}
                break
            if stored_prev != prev:
                first_break = {"chain_seq": seq, "event_id": row["event_id"],
                               "reason": "broken_link"}
                break
            if record_hash(prev, row) != stored_hash:
                first_break = {"chain_seq": seq, "event_id": row["event_id"],
                               "reason": "content_modified"}
                break
            prev = stored_hash
            expected_seq += 1
            checked += 1
        if first_break is not None or len(rows) < page_size:
            break
    unsealed = db.execute_query(
        "SELECT COUNT(*) FROM agent_events WHERE tenant_id = %s AND record_hash IS NULL",
        (tenant_id,), fetch_one=True,
    )
    return {
        "valid": first_break is None,
        "checked": checked,
        "complete": checked < max_rows,
        "head_seq": expected_seq - 1,
        "head_hash": prev,
        "unsealed_count": int(unsealed[0]) if unsealed else None,
        "first_break": first_break,
        "chain_version": CHAIN_VERSION,
        "guarantee": "tamper-evident (not immutable): see docs/AGENT_BEHAVIORAL_FIREWALL.md",
    }
