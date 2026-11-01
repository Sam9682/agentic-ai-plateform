"""Pure-SQL persistence for agents + executions (Task 7).

Tenant-scoped CRUD over ``agents`` and ``agent_executions`` in the repository
style of ``runtime_monitor_repository.py``. Status transitions are validated by
:mod:`src.aro.lifecycle` in the service layer; the repository's
``update_status`` is the low-level setter.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


def _dumps(value: Any) -> str:
    return json.dumps(value if value is not None else [])


def _as_json(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def _get_db():
    from ..database_postgres import db_manager
    return db_manager


_AGENT_SELECT = (
    "SELECT id, tenant_id, identity, name, runtime_id, environment_id, "
    "owner_user_id, status, configuration, permissions, policy_refs, "
    "credential_refs, created_at, updated_at FROM agents"
)


def _agent_row(row: Any) -> Dict[str, Any]:
    return {
        "id": int(row[0]),
        "tenant_id": int(row[1]),
        "identity": row[2],
        "name": row[3],
        "runtime_id": int(row[4]),
        "environment_id": int(row[5]) if row[5] is not None else None,
        "owner_user_id": int(row[6]) if row[6] is not None else None,
        "status": row[7],
        "configuration": _as_json(row[8]),
        "permissions": _as_json(row[9]),
        "policy_refs": _as_json(row[10]),
        "credential_refs": _as_json(row[11]),
        "created_at": row[12].isoformat() if row[12] else None,
        "updated_at": row[13].isoformat() if row[13] else None,
    }


def make_identity(tenant_slug: str, name: str) -> str:
    """Build the canonical zero-trust identity string for an agent."""
    return f"agent://{tenant_slug}/{name}"


def create_agent(
    tenant_id: int,
    tenant_slug: str,
    name: str,
    runtime_id: int,
    *,
    environment_id: Optional[int] = None,
    owner_user_id: Optional[int] = None,
    configuration: Optional[Dict[str, Any]] = None,
    permissions: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Insert a new agent in REGISTERED state and return it. Identity is unique."""
    identity = make_identity(tenant_slug, name)
    row = _get_db().execute_query(
        """
        INSERT INTO agents (
            tenant_id, identity, name, runtime_id, environment_id, owner_user_id,
            status, configuration, permissions
        ) VALUES (%s, %s, %s, %s, %s, %s, 'REGISTERED', %s, %s)
        RETURNING id
        """,
        (
            tenant_id, identity, name, runtime_id, environment_id, owner_user_id,
            json.dumps(configuration or {}), _dumps(permissions or []),
        ),
        fetch_one=True,
    )
    return get_agent(tenant_id, int(row[0]))


def get_agent(tenant_id: int, agent_id: int) -> Optional[Dict[str, Any]]:
    row = _get_db().execute_query(
        f"{_AGENT_SELECT} WHERE tenant_id = %s AND id = %s",
        (tenant_id, agent_id),
        fetch_one=True,
    )
    return _agent_row(row) if row else None


def list_agents(tenant_id: int) -> List[Dict[str, Any]]:
    rows = _get_db().execute_query(
        f"{_AGENT_SELECT} WHERE tenant_id = %s ORDER BY id DESC",
        (tenant_id,),
        fetch_all=True,
    )
    return [_agent_row(r) for r in (rows or [])]


def update_status(tenant_id: int, agent_id: int, new_status: str) -> bool:
    """Set an agent's status (validation is the service layer's job)."""
    rows = _get_db().execute_query(
        "UPDATE agents SET status = %s, updated_at = CURRENT_TIMESTAMP "
        "WHERE tenant_id = %s AND id = %s",
        (new_status, tenant_id, agent_id),
    )
    return bool(rows)


def delete_agent(tenant_id: int, agent_id: int) -> bool:
    rows = _get_db().execute_query(
        "DELETE FROM agents WHERE tenant_id = %s AND id = %s",
        (tenant_id, agent_id),
    )
    return bool(rows)


# --------------------------------------------------------------------------- #
# Executions
# --------------------------------------------------------------------------- #
def create_execution(
    tenant_id: int,
    agent_id: int,
    execution_ref: str,
    *,
    server_id: Optional[int] = None,
    container_id: Optional[str] = None,
) -> int:
    row = _get_db().execute_query(
        """
        INSERT INTO agent_executions
            (tenant_id, agent_id, execution_ref, server_id, container_id, status)
        VALUES (%s, %s, %s, %s, %s, 'STARTING')
        RETURNING id
        """,
        (tenant_id, agent_id, execution_ref, server_id, container_id),
        fetch_one=True,
    )
    return int(row[0])


def latest_running_execution(tenant_id: int, agent_id: int) -> Optional[int]:
    """Return the id of the agent's newest still-open Execution_Row, or None.

    An execution is "still open" while it has not been closed out
    (``ended_at IS NULL``). The newest such row for the agent is returned so a
    stop can close out the session that start opened (Req 1.8). Tenant-scoped.
    """
    row = _get_db().execute_query(
        "SELECT id FROM agent_executions "
        "WHERE tenant_id = %s AND agent_id = %s AND ended_at IS NULL "
        "ORDER BY id DESC LIMIT 1",
        (tenant_id, agent_id),
        fetch_one=True,
    )
    return int(row[0]) if row else None


def set_execution_status(
    tenant_id: int, execution_id: int, status: str, *, ended: bool = False
) -> bool:
    ended_sql = ", ended_at = CURRENT_TIMESTAMP" if ended else ""
    rows = _get_db().execute_query(
        f"UPDATE agent_executions SET status = %s{ended_sql} "
        "WHERE tenant_id = %s AND id = %s",
        (status, tenant_id, execution_id),
    )
    return bool(rows)


# --------------------------------------------------------------------------- #
# Session durability (Req 4.1, 4.2)
# --------------------------------------------------------------------------- #
_RUNNING_EXECUTION_SELECT = (
    "SELECT id, agent_id, execution_ref, server_id, container_id, "
    "session_id, runtime_handle, runtime_adapter, status "
    "FROM agent_executions"
)


def _running_execution_row(row: Any) -> Dict[str, Any]:
    return {
        "id": int(row[0]),
        "agent_id": int(row[1]),
        "execution_ref": row[2],
        "server_id": int(row[3]) if row[3] is not None else None,
        "container_id": row[4],
        "session_id": row[5],
        "runtime_handle": row[6],
        "runtime_adapter": row[7],
        "status": row[8],
    }


def list_running_executions(tenant_id: int) -> List[Dict[str, Any]]:
    """Return all RUNNING Execution_Rows for the tenant (Req 4.2).

    The control-plane reconnect routine loads these at restart to re-attach to
    (or close out) recorded remote runtimes rather than launching new ones. The
    session-durability columns (``session_id``, ``runtime_handle``,
    ``runtime_adapter``) are included alongside the server/container identifiers
    so the reconnect routine has everything it needs to probe each session.
    Tenant-scoped.
    """
    rows = _get_db().execute_query(
        f"{_RUNNING_EXECUTION_SELECT} "
        "WHERE tenant_id = %s AND status = 'RUNNING' ORDER BY id DESC",
        (tenant_id,),
        fetch_all=True,
    )
    return [_running_execution_row(r) for r in (rows or [])]


def set_execution_session(
    tenant_id: int,
    execution_id: int,
    *,
    session_id: Optional[str] = None,
    runtime_handle: Optional[str] = None,
    runtime_adapter: Optional[str] = None,
) -> bool:
    """Persist the session handle on an Execution_Row after a successful start.

    Writes the session-durability columns (``session_id``, ``runtime_handle``,
    ``runtime_adapter``) so a control-plane restart can reconnect to the remote
    runtime (Req 4.1). Tenant-scoped by id.
    """
    rows = _get_db().execute_query(
        "UPDATE agent_executions SET "
        "session_id = %s, runtime_handle = %s, runtime_adapter = %s "
        "WHERE tenant_id = %s AND id = %s",
        (session_id, runtime_handle, runtime_adapter, tenant_id, execution_id),
    )
    return bool(rows)
