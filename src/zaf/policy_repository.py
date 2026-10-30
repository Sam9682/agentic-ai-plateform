"""Policy + decision persistence for ZAF (Task 11).

Pure-SQL access over ``governance_policies``, ``agent_permissions`` and
``governance_decisions``. A YAML loader converts the SRS policy document shape
into the stored rule list. Decisions are append-only (audit).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import yaml


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


def parse_policy_yaml(text: str) -> Dict[str, Any]:
    """Parse an SRS-style policy YAML into ``{name, scope, rules}``.

    Example input::

        policy:
          name: infrastructure-protection
          scope: tenant
          rules:
            - action: openstack.server.delete
              decision: REQUIRE_APPROVAL

    Returns a normalized dict. Raises ValueError on malformed input.
    """
    doc = yaml.safe_load(text) or {}
    policy = doc.get("policy", doc)
    if not isinstance(policy, dict) or "name" not in policy:
        raise ValueError("policy document must contain a 'name'")
    rules = policy.get("rules") or []
    if not isinstance(rules, list):
        raise ValueError("policy 'rules' must be a list")
    return {
        "name": policy["name"],
        "scope": policy.get("scope", "tenant"),
        "rules": rules,
    }


def create_policy(
    tenant_id: int, name: str, rules: List[Dict[str, Any]], *, scope: str = "tenant"
) -> int:
    """Create a new policy version (version = max(existing)+1) and return id."""
    db = _get_db()
    row = db.execute_query(
        "SELECT COALESCE(MAX(version), 0) FROM governance_policies "
        "WHERE tenant_id = %s AND name = %s",
        (tenant_id, name),
        fetch_one=True,
    )
    next_version = int(row[0]) + 1 if row else 1
    ins = db.execute_query(
        """
        INSERT INTO governance_policies (tenant_id, name, version, scope, rules, enabled)
        VALUES (%s, %s, %s, %s, %s, TRUE)
        RETURNING id
        """,
        (tenant_id, name, next_version, scope, json.dumps(rules)),
        fetch_one=True,
    )
    return int(ins[0])


def list_policies(tenant_id: int) -> List[Dict[str, Any]]:
    rows = _get_db().execute_query(
        "SELECT id, name, version, scope, rules, enabled, created_at "
        "FROM governance_policies WHERE tenant_id = %s ORDER BY name, version DESC",
        (tenant_id,),
        fetch_all=True,
    )
    return [
        {
            "id": int(r[0]), "name": r[1], "version": int(r[2]), "scope": r[3],
            "rules": _as_json(r[4]), "enabled": bool(r[5]),
            "created_at": r[6].isoformat() if r[6] else None,
        }
        for r in (rows or [])
    ]


def effective_rules(tenant_id: int) -> List[Dict[str, Any]]:
    """Return the flattened rule list from all enabled latest-version policies."""
    rows = _get_db().execute_query(
        """
        SELECT DISTINCT ON (name) rules
        FROM governance_policies
        WHERE tenant_id = %s AND enabled = TRUE
        ORDER BY name, version DESC
        """,
        (tenant_id,),
        fetch_all=True,
    ) or []
    rules: List[Dict[str, Any]] = []
    for r in rows:
        parsed = _as_json(r[0]) or []
        if isinstance(parsed, list):
            rules.extend(parsed)
    return rules


def grant_permission(tenant_id: int, agent_id: int, action_glob: str) -> None:
    _get_db().execute_query(
        """
        INSERT INTO agent_permissions (tenant_id, agent_id, action_glob)
        VALUES (%s, %s, %s)
        ON CONFLICT (tenant_id, agent_id, action_glob) DO NOTHING
        """,
        (tenant_id, agent_id, action_glob),
    )


def agent_permissions(tenant_id: int, agent_id: int) -> List[str]:
    rows = _get_db().execute_query(
        "SELECT action_glob FROM agent_permissions WHERE tenant_id = %s AND agent_id = %s",
        (tenant_id, agent_id),
        fetch_all=True,
    )
    return [r[0] for r in (rows or [])]


def record_decision(
    tenant_id: int,
    *,
    agent_identity: Optional[str],
    action: str,
    resource: Optional[str],
    decision: str,
    matched_rule: Optional[Dict[str, Any]],
    risk_score: int,
    reason: str,
    params_hash: Optional[str] = None,
) -> int:
    row = _get_db().execute_query(
        """
        INSERT INTO governance_decisions (
            tenant_id, agent_identity, action, resource, decision, matched_rule,
            risk_score, reason, params_hash
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            tenant_id, agent_identity, action, resource, decision,
            json.dumps(matched_rule) if matched_rule is not None else None,
            int(risk_score), reason, params_hash,
        ),
        fetch_one=True,
    )
    return int(row[0])


def list_decisions(tenant_id: int, limit: int = 200) -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit), 2000))
    rows = _get_db().execute_query(
        "SELECT id, agent_identity, action, resource, decision, matched_rule, "
        "risk_score, reason, params_hash, decided_at FROM governance_decisions "
        "WHERE tenant_id = %s ORDER BY decided_at DESC LIMIT %s",
        (tenant_id, limit),
        fetch_all=True,
    )
    return [
        {
            "id": int(r[0]), "agent_identity": r[1], "action": r[2], "resource": r[3],
            "decision": r[4], "matched_rule": _as_json(r[5]), "risk_score": int(r[6]),
            "reason": r[7], "params_hash": r[8],
            "decided_at": r[9].isoformat() if r[9] else None,
        }
        for r in (rows or [])
    ]
