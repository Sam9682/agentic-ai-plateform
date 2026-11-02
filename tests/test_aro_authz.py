#!/usr/bin/env python3
"""Property + unit tests for ARO/ZAF multi-tenant authorization (Task 1).

Feature: Agent Runtime Orchestrator / Zero-trust Agent Firewall.
Validates the pure authorization core in ``src.authz`` and the Flask
decorators that wrap it:

* resolve_tenant: deny-by-default when the user is not a member of the
  requested tenant; unambiguous resolution of the default/sole membership.
* role_satisfies: role hierarchy (viewer < operator < admin); unknown roles
  never satisfy a requirement.
* decorators: 401 unauthenticated, 403 cross-tenant / insufficient role,
  200 within tenant with sufficient role.

Run directly:
    python3 tests/test_aro_authz.py
Or via pytest:
    pytest tests/test_aro_authz.py
"""
import os
import sys

from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src import authz  # noqa: E402


# --------------------------------------------------------------------------- #
# Pure core: role_satisfies
# --------------------------------------------------------------------------- #
def test_role_hierarchy_basic():
    assert authz.role_satisfies("admin", "operator")
    assert authz.role_satisfies("operator", "operator")
    assert authz.role_satisfies("operator", "viewer")
    assert not authz.role_satisfies("viewer", "operator")
    assert not authz.role_satisfies("operator", "admin")


def test_role_unknown_never_satisfies():
    assert not authz.role_satisfies(None, "viewer")
    assert not authz.role_satisfies("superuser", "viewer")
    assert not authz.role_satisfies("admin", "superuser")


_ROLES = st.sampled_from(["viewer", "operator", "admin"])


@given(actual=_ROLES, required=_ROLES)
@settings(max_examples=100)
def test_role_satisfies_is_rank_order(actual, required):
    rank = {"viewer": 0, "operator": 1, "admin": 2}
    assert authz.role_satisfies(actual, required) == (rank[actual] >= rank[required])


# --------------------------------------------------------------------------- #
# Pure core: resolve_tenant
# --------------------------------------------------------------------------- #
def test_resolve_requested_tenant_member():
    memberships = [
        {"tenant_id": 1, "role": "admin", "is_default": True},
        {"tenant_id": 2, "role": "viewer", "is_default": False},
    ]
    assert authz.resolve_tenant(memberships, 2)["role"] == "viewer"


def test_resolve_requested_tenant_non_member_denied():
    memberships = [{"tenant_id": 1, "role": "admin", "is_default": True}]
    assert authz.resolve_tenant(memberships, 99) is None


def test_resolve_default_membership():
    memberships = [
        {"tenant_id": 1, "role": "operator", "is_default": False},
        {"tenant_id": 2, "role": "admin", "is_default": True},
    ]
    assert authz.resolve_tenant(memberships, None)["tenant_id"] == 2


def test_resolve_single_membership_without_default():
    memberships = [{"tenant_id": 7, "role": "operator", "is_default": False}]
    assert authz.resolve_tenant(memberships, None)["tenant_id"] == 7


def test_resolve_ambiguous_returns_none():
    memberships = [
        {"tenant_id": 1, "role": "operator", "is_default": False},
        {"tenant_id": 2, "role": "operator", "is_default": False},
    ]
    assert authz.resolve_tenant(memberships, None) is None


def test_resolve_no_membership_returns_none():
    assert authz.resolve_tenant([], None) is None
    assert authz.resolve_tenant([], 1) is None


@st.composite
def membership_lists(draw):
    """Generate memberships with unique tenant_ids and at most one default."""
    n = draw(st.integers(min_value=0, max_value=5))
    tenant_ids = draw(
        st.lists(st.integers(min_value=1, max_value=50), min_size=n, max_size=n, unique=True)
    )
    default_idx = draw(st.integers(min_value=-1, max_value=max(n - 1, -1)))
    out = []
    for i, tid in enumerate(tenant_ids):
        out.append(
            {
                "tenant_id": tid,
                "role": draw(_ROLES),
                "is_default": (i == default_idx),
            }
        )
    return out


@given(memberships=membership_lists(), requested=st.one_of(st.none(), st.integers(1, 60)))
@settings(max_examples=200)
def test_resolve_tenant_never_grants_foreign_tenant(memberships, requested):
    """resolve_tenant must only ever return a tenant the user belongs to."""
    result = authz.resolve_tenant(memberships, requested)
    if result is not None:
        member_tenants = {m["tenant_id"] for m in memberships}
        assert result["tenant_id"] in member_tenants
        if requested is not None:
            assert result["tenant_id"] == requested


# --------------------------------------------------------------------------- #
# Flask decorators (real Flask app, stubbed membership loader + session)
# --------------------------------------------------------------------------- #
def _make_app():
    from flask import Flask, g, jsonify

    app = Flask(__name__)
    app.secret_key = "test"

    @app.route("/open")
    @authz.login_required
    def open_route():
        return jsonify({"ok": True})

    @app.route("/scoped")
    @authz.tenant_scoped
    def scoped_route():
        return jsonify({"tenant_id": g.tenant_id, "role": g.tenant_role})

    @app.route("/admin")
    @authz.role_required("admin")
    def admin_route():
        return jsonify({"tenant_id": g.tenant_id})

    return app


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id


def test_login_required_401_when_anonymous():
    app = _make_app()
    client = app.test_client()
    assert client.get("/open").status_code == 401


def test_login_required_200_when_authenticated():
    app = _make_app()
    client = app.test_client()
    _login(client, 1)
    assert client.get("/open").status_code == 200


def test_tenant_scoped_resolves_default(monkeypatch):
    app = _make_app()
    monkeypatch.setattr(
        authz, "membership_loader",
        lambda uid: [{"tenant_id": 5, "tenant_slug": "t5", "role": "operator", "is_default": True}],
    )
    client = app.test_client()
    _login(client, 1)
    resp = client.get("/scoped")
    assert resp.status_code == 200
    assert resp.get_json()["tenant_id"] == 5


def test_tenant_scoped_403_cross_tenant(monkeypatch):
    app = _make_app()
    monkeypatch.setattr(
        authz, "membership_loader",
        lambda uid: [{"tenant_id": 5, "tenant_slug": "t5", "role": "operator", "is_default": True}],
    )
    client = app.test_client()
    _login(client, 1)
    # Request a tenant the user is not a member of.
    resp = client.get("/scoped", headers={"X-Tenant-Id": "999"})
    assert resp.status_code == 403


def test_role_required_allows_admin(monkeypatch):
    app = _make_app()
    monkeypatch.setattr(
        authz, "membership_loader",
        lambda uid: [{"tenant_id": 5, "tenant_slug": "t5", "role": "admin", "is_default": True}],
    )
    client = app.test_client()
    _login(client, 1)
    assert client.get("/admin").status_code == 200


def test_role_required_denies_operator(monkeypatch):
    app = _make_app()
    monkeypatch.setattr(
        authz, "membership_loader",
        lambda uid: [{"tenant_id": 5, "tenant_slug": "t5", "role": "operator", "is_default": True}],
    )
    client = app.test_client()
    _login(client, 1)
    assert client.get("/admin").status_code == 403


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
