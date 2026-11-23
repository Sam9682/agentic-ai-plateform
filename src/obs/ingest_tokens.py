"""Per-agent telemetry ingest tokens (ABF/AET event foundation, Phase 1).

An ingest token authenticates an agent runtime posting telemetry to
``POST /api/v1/telemetry/events``. It binds every reported event to exactly one
``(tenant_id, agent_id)`` chosen by the control plane at issue time, so a runtime
can never report events for another agent or tenant.

* The clear token is returned **once** at issue time. Only its SHA-256 hash is
  stored (same approach as ``credential_vault`` scoped tokens).
* Tokens expire (bounded TTL) and can be revoked individually or all at once
  for an agent (used by quarantine in Phase 2).
* Verification fails closed: unknown, revoked or expired tokens, and tokens of
  deleted or terminated agents, yield ``None``.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

TOKEN_PREFIX = "aig_"
SCOPE_TELEMETRY = "telemetry:ingest"
#: Phase 2: ask the firewall before a sensitive action (POST /api/v1/firewall/check).
SCOPE_FIREWALL = "firewall:check"
#: Phase 2: call governed platform MCP tools (src/mcp_interface.py).
SCOPE_MCP = "mcp:invoke"
ALLOWED_SCOPES = (SCOPE_TELEMETRY, SCOPE_FIREWALL, SCOPE_MCP)
#: Scopes that let an agent *act*; revoked when the agent is quarantined.
#: Telemetry-only tokens survive quarantine so a contained agent stays observable.
ACTING_SCOPES = (SCOPE_FIREWALL, SCOPE_MCP)


def normalize_scopes(scopes: Any) -> str:
    """Validate a scope list; returns the stored space-separated form.

    Raises ValueError for an unknown scope. ``None`` / empty means telemetry only.
    """
    if scopes is None or scopes == [] or scopes == "":
        return SCOPE_TELEMETRY
    if isinstance(scopes, str):
        scopes = scopes.split()
    if not isinstance(scopes, (list, tuple)):
        raise ValueError("scopes must be a list of strings")
    out = []
    for sc in scopes:
        if sc not in ALLOWED_SCOPES:
            raise ValueError(f"unknown scope: {sc!r}")
        if sc not in out:
            out.append(sc)
    return " ".join(sorted(out, key=ALLOWED_SCOPES.index))
DEFAULT_TTL_SECONDS = 24 * 3600
MAX_TTL_SECONDS = 30 * 24 * 3600
MIN_TTL_SECONDS = 60


def _get_db():
    from ..database_postgres import db_manager
    return db_manager


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _clamp_ttl(ttl_seconds: Any) -> int:
    try:
        ttl = int(ttl_seconds)
    except (TypeError, ValueError):
        ttl = DEFAULT_TTL_SECONDS
    return max(MIN_TTL_SECONDS, min(MAX_TTL_SECONDS, ttl))


def issue(
    tenant_id: int,
    agent_id: int,
    *,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    created_by_user_id: Optional[int] = None,
    now: Optional[datetime] = None,
    scopes: Any = None,
) -> Dict[str, Any]:
    """Issue a new agent token. Returns the clear token ONCE.

    ``scopes`` defaults to telemetry ingestion only; see :data:`ALLOWED_SCOPES`.
    """
    scope = normalize_scopes(scopes)
    now = now or datetime.now(timezone.utc)
    secret_part = secrets.token_urlsafe(32)
    display = secrets.token_hex(4)
    token = f"{TOKEN_PREFIX}{display}_{secret_part}"
    expires_at = now + timedelta(seconds=_clamp_ttl(ttl_seconds))
    row = _get_db().execute_query(
        """
        INSERT INTO agent_ingest_tokens
            (tenant_id, agent_id, token_hash, token_prefix, scope, expires_at,
             created_by_user_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (tenant_id, agent_id, hash_token(token), f"{TOKEN_PREFIX}{display}",
         scope, expires_at, created_by_user_id),
        fetch_one=True,
    )
    return {
        "id": int(row[0]),
        "token": token,
        "token_prefix": f"{TOKEN_PREFIX}{display}",
        "scope": scope,
        "expires_at": expires_at.isoformat(),
    }


def verify(token: Any, *, now: Optional[datetime] = None,
           scope: str = SCOPE_TELEMETRY) -> Optional[Dict[str, Any]]:
    """Resolve a clear token to its binding, or ``None`` (fail closed).

    Joins the agent so the binding carries the authoritative agent identity and
    status. Tokens of TERMINATED agents are refused.
    """
    if not isinstance(token, str) or not token.startswith(TOKEN_PREFIX) or len(token) > 256:
        return None
    row = _get_db().execute_query(
        """
        SELECT t.id, t.tenant_id, t.agent_id, t.scope, t.expires_at, t.revoked,
               a.identity, a.status
        FROM agent_ingest_tokens t
        JOIN agents a ON a.id = t.agent_id AND a.tenant_id = t.tenant_id
        WHERE t.token_hash = %s
        """,
        (hash_token(token),),
        fetch_one=True,
    )
    if not row or bool(row[5]):
        return None
    now = now or datetime.now(timezone.utc)
    expires_at = row[4]
    if expires_at is None:
        return None
    exp = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=timezone.utc)
    if exp <= now:
        return None
    if scope not in str(row[3] or "").split():
        return None
    if row[7] == "TERMINATED":
        return None
    return {
        "token_id": int(row[0]),
        "tenant_id": int(row[1]),
        "agent_db_id": int(row[2]),
        "scope": row[3],
        "expires_at": exp.isoformat(),
        "agent_identity": row[6],
        "agent_status": row[7],
    }


def touch(token_id: int) -> None:
    """Record last use (best effort; never fails ingestion)."""
    try:
        _get_db().execute_query(
            "UPDATE agent_ingest_tokens SET last_used_at = CURRENT_TIMESTAMP WHERE id = %s",
            (int(token_id),),
        )
    except Exception:  # noqa: BLE001 - bookkeeping only
        pass


def list_for_agent(tenant_id: int, agent_id: int, limit: int = 100) -> List[Dict[str, Any]]:
    """List an agent's tokens (metadata only, never the hash or clear token)."""
    rows = _get_db().execute_query(
        """
        SELECT id, token_prefix, scope, expires_at, revoked, revoked_at,
               created_by_user_id, last_used_at, created_at
        FROM agent_ingest_tokens
        WHERE tenant_id = %s AND agent_id = %s
        ORDER BY created_at DESC, id DESC
        LIMIT %s
        """,
        (tenant_id, agent_id, max(1, min(int(limit), 500))),
        fetch_all=True,
    ) or []

    def _iso(v):
        return v.isoformat() if v is not None else None

    return [
        {"id": int(r[0]), "token_prefix": r[1], "scope": r[2],
         "expires_at": _iso(r[3]), "revoked": bool(r[4]), "revoked_at": _iso(r[5]),
         "created_by_user_id": int(r[6]) if r[6] is not None else None,
         "last_used_at": _iso(r[7]), "created_at": _iso(r[8])}
        for r in rows
    ]


def revoke(tenant_id: int, agent_id: int, token_id: int) -> bool:
    """Revoke one token (tenant- and agent-scoped). True when a row changed."""
    rows = _get_db().execute_query(
        "UPDATE agent_ingest_tokens SET revoked = TRUE, revoked_at = CURRENT_TIMESTAMP "
        "WHERE tenant_id = %s AND agent_id = %s AND id = %s AND revoked = FALSE",
        (tenant_id, agent_id, int(token_id)),
    )
    return bool(rows)


def revoke_all_for_agent(tenant_id: int, agent_id: int) -> int:
    """Revoke every active token of an agent; returns the number revoked."""
    rows = _get_db().execute_query(
        "UPDATE agent_ingest_tokens SET revoked = TRUE, revoked_at = CURRENT_TIMESTAMP "
        "WHERE tenant_id = %s AND agent_id = %s AND revoked = FALSE",
        (tenant_id, agent_id),
    )
    return int(rows or 0)


def revoke_acting_scopes_for_agent(tenant_id: int, agent_id: int) -> int:
    """Revoke the agent's tokens that carry an acting scope (MCP / firewall).

    Used by quarantine. Telemetry-only tokens are kept so the contained agent's
    runtime remains observable (its events are flagged with the agent status).
    """
    rows = _get_db().execute_query(
        "UPDATE agent_ingest_tokens SET revoked = TRUE, revoked_at = CURRENT_TIMESTAMP "
        "WHERE tenant_id = %s AND agent_id = %s AND revoked = FALSE "
        "AND string_to_array(scope, ' ') && %s::text[]",
        (tenant_id, agent_id, list(ACTING_SCOPES)),
    )
    return int(rows or 0)
