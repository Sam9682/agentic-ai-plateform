"""Pure-SQL persistence for the agent runtime registry (Task 4).

Tenant-scoped CRUD over ``agent_runtimes`` mirroring the repository style of
``runtime_monitor_repository.py``. Definitions are validated by
:mod:`runtime_registry_service` before reaching here.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


def _dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {})


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


_SELECT = (
    "SELECT id, tenant_id, identifier, name, version, vendor, install_source, "
    "install_method, supported_protocols, dependencies, required_permissions, "
    "execution_modes, health_check, config_schema, status, created_at "
    "FROM agent_runtimes"
)


def _row_to_dict(row: Any) -> Dict[str, Any]:
    return {
        "id": int(row[0]),
        "tenant_id": int(row[1]),
        "identifier": row[2],
        "name": row[3],
        "version": row[4],
        "vendor": row[5],
        "install_source": row[6],
        "install_method": _as_json(row[7]),
        "supported_protocols": _as_json(row[8]),
        "dependencies": _as_json(row[9]),
        "required_permissions": _as_json(row[10]),
        "execution_modes": _as_json(row[11]),
        "health_check": _as_json(row[12]),
        "config_schema": _as_json(row[13]),
        "status": row[14],
        "created_at": row[15].isoformat() if row[15] else None,
    }


def register(tenant_id: int, definition: Dict[str, Any]) -> int:
    """Insert or update (by identifier) a validated runtime definition."""
    db = _get_db()
    row = db.execute_query(
        """
        INSERT INTO agent_runtimes (
            tenant_id, identifier, name, version, vendor, install_source,
            install_method, supported_protocols, dependencies,
            required_permissions, execution_modes, health_check, config_schema
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (tenant_id, identifier) DO UPDATE SET
            name = EXCLUDED.name,
            version = EXCLUDED.version,
            vendor = EXCLUDED.vendor,
            install_source = EXCLUDED.install_source,
            install_method = EXCLUDED.install_method,
            supported_protocols = EXCLUDED.supported_protocols,
            dependencies = EXCLUDED.dependencies,
            required_permissions = EXCLUDED.required_permissions,
            execution_modes = EXCLUDED.execution_modes,
            health_check = EXCLUDED.health_check,
            config_schema = EXCLUDED.config_schema,
            status = 'registered'
        RETURNING id
        """,
        (
            tenant_id,
            definition["identifier"],
            definition["name"],
            definition["version"],
            definition.get("vendor"),
            definition.get("install_source"),
            _dumps(definition.get("install_method")),
            _dumps(definition.get("supported_protocols")),
            _dumps(definition.get("dependencies")),
            _dumps(definition.get("required_permissions")),
            _dumps(definition.get("execution_modes")),
            _dumps(definition.get("health_check")),
            _dumps(definition.get("config_schema")),
        ),
        fetch_one=True,
    )
    return int(row[0])


def list_runtimes(tenant_id: int) -> List[Dict[str, Any]]:
    rows = _get_db().execute_query(
        f"{_SELECT} WHERE tenant_id = %s ORDER BY identifier",
        (tenant_id,),
        fetch_all=True,
    )
    return [_row_to_dict(r) for r in (rows or [])]


def get_runtime(tenant_id: int, runtime_id: int) -> Optional[Dict[str, Any]]:
    row = _get_db().execute_query(
        f"{_SELECT} WHERE tenant_id = %s AND id = %s",
        (tenant_id, runtime_id),
        fetch_one=True,
    )
    return _row_to_dict(row) if row else None


def get_by_identifier(tenant_id: int, identifier: str) -> Optional[Dict[str, Any]]:
    row = _get_db().execute_query(
        f"{_SELECT} WHERE tenant_id = %s AND identifier = %s",
        (tenant_id, identifier),
        fetch_one=True,
    )
    return _row_to_dict(row) if row else None
