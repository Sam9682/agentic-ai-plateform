"""Reusable authentication / tenant-scoping / role authorization (ARO/ZAF).

The legacy routes authorize inline (``if 'user_id' not in session: 401`` plus a
magic ``username == 'admin'`` check). The ARO/ZAF surface needs real
multi-tenant authorization, so this module provides:

* A **pure** core (:func:`resolve_tenant`, :func:`role_satisfies`) that holds all
  the decision logic with no Flask / DB dependency, so it is unit- and
  property-testable in isolation.
* Flask decorators (:func:`login_required`, :func:`tenant_scoped`,
  :func:`role_required`) that read ``session``, load membership through an
  injectable loader, and attach the resolved tenant/role to ``flask.g``.

Design principles (mirrors the rest of ``src/``):
* Deny by default. A user with no membership in the requested tenant is
  rejected (403); an unauthenticated request is rejected (401).
* The decorators are only applied to the new ARO/ZAF/OBS blueprints. Existing
  routes keep their inline checks to preserve compatibility; migrating them is
  tracked as follow-up.
"""

from __future__ import annotations

import functools
from typing import Any, Callable, Dict, List, Optional

# Role hierarchy: a higher role satisfies any requirement at or below it.
# Index position encodes rank (viewer < operator < admin).
_ROLE_RANK = {"viewer": 0, "operator": 1, "admin": 2}


def role_satisfies(actual_role: Optional[str], required_role: str) -> bool:
    """Return True when ``actual_role`` meets or exceeds ``required_role``.

    Unknown or missing roles never satisfy a requirement (deny by default).

    Args:
        actual_role: The role the member holds in the tenant (or None).
        required_role: The minimum role the operation requires.
    """
    if actual_role not in _ROLE_RANK or required_role not in _ROLE_RANK:
        return False
    return _ROLE_RANK[actual_role] >= _ROLE_RANK[required_role]


def resolve_tenant(
    memberships: List[Dict[str, Any]],
    requested_tenant_id: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """Resolve which tenant membership applies for a request. Pure function.

    Given a user's memberships (each a dict with ``tenant_id``, ``role`` and
    optionally ``is_default``), pick the effective membership:

    * If ``requested_tenant_id`` is given, return the matching membership or
      ``None`` when the user is not a member of that tenant (deny by default,
      which the caller turns into a 403).
    * Otherwise return the membership flagged ``is_default``; if none is
      flagged, fall back to the single membership when there is exactly one;
      otherwise return ``None`` (ambiguous — the caller must require an explicit
      tenant).

    Args:
        memberships: The user's tenant memberships.
        requested_tenant_id: Tenant the request explicitly targets, if any.

    Returns:
        The resolved membership dict, or ``None`` when no unambiguous tenant can
        be resolved / the user lacks access.
    """
    members = list(memberships or [])
    if requested_tenant_id is not None:
        for m in members:
            if m.get("tenant_id") == requested_tenant_id:
                return m
        return None  # not a member of the requested tenant -> deny

    if not members:
        return None
    defaults = [m for m in members if m.get("is_default")]
    if len(defaults) == 1:
        return defaults[0]
    if len(members) == 1:
        return members[0]
    return None  # ambiguous: the caller must pass an explicit tenant


# --------------------------------------------------------------------------- #
# Membership loading (injectable so tests need no live DB).
# --------------------------------------------------------------------------- #
def _default_membership_loader(user_id: int) -> List[Dict[str, Any]]:
    """Load a user's tenant memberships from the database.

    Returns a list of ``{tenant_id, tenant_slug, role, is_default}`` dicts.
    Imports are deferred so importing this module never opens a DB pool.
    """
    from .database_postgres import db_manager

    rows = db_manager.execute_query(
        """
        SELECT tm.tenant_id, t.slug, tm.role, tm.is_default
        FROM tenant_members tm
        JOIN tenants t ON t.id = tm.tenant_id
        WHERE tm.user_id = %s AND t.status = 'active'
        ORDER BY tm.is_default DESC, tm.tenant_id
        """,
        (user_id,),
        fetch_all=True,
    ) or []
    return [
        {
            "tenant_id": r[0],
            "tenant_slug": r[1],
            "role": r[2],
            "is_default": bool(r[3]),
        }
        for r in rows
    ]


# The loader is module-level so tests can monkeypatch it.
membership_loader: Callable[[int], List[Dict[str, Any]]] = _default_membership_loader


def _requested_tenant_id():
    """Extract an explicitly requested tenant id from the current request.

    Reads ``X-Tenant-Id`` header or ``tenant_id`` query arg; returns an int or
    None. Invalid values resolve to None so :func:`resolve_tenant` falls back to
    the default-membership path.
    """
    from flask import request

    raw = request.headers.get("X-Tenant-Id") or request.args.get("tenant_id")
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def login_required(fn):
    """Reject unauthenticated requests with 401 before calling ``fn``."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        from flask import session, jsonify

        if "user_id" not in session:
            return jsonify({"error": "authentication required"}), 401
        return fn(*args, **kwargs)

    return wrapper


def tenant_scoped(fn):
    """Resolve the active tenant and attach it to ``flask.g`` before ``fn``.

    Requires authentication (401 when absent). Resolves the effective membership
    via :func:`resolve_tenant`; a user with no access to the requested/default
    tenant gets 403. On success ``g.tenant_id`` and ``g.tenant_role`` are set.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        from flask import session, jsonify, g

        if "user_id" not in session:
            return jsonify({"error": "authentication required"}), 401

        memberships = membership_loader(session["user_id"])
        member = resolve_tenant(memberships, _requested_tenant_id())
        if member is None:
            return jsonify({"error": "tenant access denied"}), 403

        g.tenant_id = member["tenant_id"]
        g.tenant_role = member["role"]
        g.tenant_slug = member.get("tenant_slug")
        return fn(*args, **kwargs)

    return wrapper


def role_required(required_role: str):
    """Decorator factory: require a minimum tenant role (implies tenant_scoped).

    Resolves the tenant (like :func:`tenant_scoped`) and then checks the
    member's role against ``required_role`` using :func:`role_satisfies`,
    returning 403 when insufficient.
    """

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            from flask import session, jsonify, g

            if "user_id" not in session:
                return jsonify({"error": "authentication required"}), 401

            memberships = membership_loader(session["user_id"])
            member = resolve_tenant(memberships, _requested_tenant_id())
            if member is None:
                return jsonify({"error": "tenant access denied"}), 403
            if not role_satisfies(member.get("role"), required_role):
                return jsonify({"error": "insufficient role"}), 403

            g.tenant_id = member["tenant_id"]
            g.tenant_role = member["role"]
            g.tenant_slug = member.get("tenant_slug")
            return fn(*args, **kwargs)

        return wrapper

    return decorator
