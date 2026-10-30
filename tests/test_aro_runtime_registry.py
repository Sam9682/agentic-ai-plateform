#!/usr/bin/env python3
"""Tests for the agent runtime registry (Task 4).

Feature: ARO runtime registry (SRS §3.1).

Validates:
* service validation: unpinned versions rejected; unknown protocols rejected;
  arbitrary install scripts rejected; integrity material required; a valid Kiro
  and SHAI definition normalize successfully.
* route auth: list requires auth (401) and tenant scope; register requires the
  admin role (403 for operator); a valid POST returns 201.

Run directly:
    python3 tests/test_aro_runtime_registry.py
Or via pytest:
    pytest tests/test_aro_runtime_registry.py
"""
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.aro import runtime_registry_service as svc  # noqa: E402


_KIRO = {
    "identifier": "kiro",
    "name": "Kiro CLI",
    "version": "1.0.0",
    "vendor": "Kiro",
    "supported_protocols": ["acp", "cli"],
    "install_method": {"kind": "binary", "sha256": "a" * 64},
}
_SHAI = {
    "identifier": "shai-cli",
    "name": "SHAI",
    "version": "0.2.2",
    "vendor": "OVHcloud",
    "supported_protocols": ["cli"],
    "install_method": {"kind": "npm", "digest": "sha512-xyz"},
}


def test_valid_kiro_and_shai_normalize():
    k = svc.validate_definition(_KIRO)
    s = svc.validate_definition(_SHAI)
    assert k["identifier"] == "kiro"
    assert set(k["supported_protocols"]) == {"acp", "cli"}
    assert s["identifier"] == "shai-cli"


def test_unpinned_version_rejected():
    bad = dict(_KIRO, version="latest")
    try:
        svc.validate_definition(bad)
        assert False
    except svc.RuntimeValidationError:
        pass


def test_unknown_protocol_rejected():
    bad = dict(_KIRO, supported_protocols=["telepathy"])
    try:
        svc.validate_definition(bad)
        assert False
    except svc.RuntimeValidationError:
        pass


def test_arbitrary_script_install_rejected():
    bad = dict(_KIRO, install_method={"kind": "script", "shell": "curl x | sh"})
    try:
        svc.validate_definition(bad)
        assert False
    except svc.RuntimeValidationError:
        pass


def test_install_without_integrity_rejected():
    bad = dict(_KIRO, install_method={"kind": "binary"})
    try:
        svc.validate_definition(bad)
        assert False
    except svc.RuntimeValidationError:
        pass


def test_missing_identifier_rejected():
    bad = dict(_KIRO)
    bad.pop("identifier")
    try:
        svc.validate_definition(bad)
        assert False
    except svc.RuntimeValidationError:
        pass


# --------------------------------------------------------------------------- #
# Route auth + tenant scoping
# --------------------------------------------------------------------------- #
def _make_client(monkeypatch, role):
    from src import authz
    from src.aro import runtime_registry_repository as repo
    from src.routes import aro_runtime_routes as routes
    from flask import Flask

    monkeypatch.setattr(
        authz, "membership_loader",
        lambda uid: [{"tenant_id": 1, "tenant_slug": "default", "role": role, "is_default": True}],
    )
    # Stub the repository so no DB is needed.
    store = {"registered": []}
    monkeypatch.setattr(repo, "list_runtimes", lambda tid: list(store["registered"]))

    def _register(tid, definition):
        store["registered"].append(dict(definition, id=len(store["registered"]) + 1, tenant_id=tid))
        return len(store["registered"])

    monkeypatch.setattr(repo, "register", _register)
    monkeypatch.setattr(routes.repo, "list_runtimes", repo.list_runtimes)
    monkeypatch.setattr(routes.repo, "register", repo.register)

    app = Flask(__name__)
    app.secret_key = "t"
    app.register_blueprint(routes.aro_runtime_bp)
    return app.test_client(), store


def _login(client, uid=1):
    with client.session_transaction() as sess:
        sess["user_id"] = uid


def test_list_requires_auth(monkeypatch):
    client, _ = _make_client(monkeypatch, "operator")
    assert client.get("/api/v1/agents/runtimes").status_code == 401


def test_list_ok_when_authenticated(monkeypatch):
    client, _ = _make_client(monkeypatch, "operator")
    _login(client)
    assert client.get("/api/v1/agents/runtimes").status_code == 200


def test_register_requires_admin(monkeypatch):
    client, _ = _make_client(monkeypatch, "operator")
    _login(client)
    resp = client.post("/api/v1/agents/runtimes", json=_KIRO)
    assert resp.status_code == 403


def test_register_admin_succeeds(monkeypatch):
    client, store = _make_client(monkeypatch, "admin")
    _login(client)
    resp = client.post("/api/v1/agents/runtimes", json=_KIRO)
    assert resp.status_code == 201
    assert resp.get_json()["identifier"] == "kiro"
    assert len(store["registered"]) == 1


def test_register_invalid_returns_400(monkeypatch):
    client, _ = _make_client(monkeypatch, "admin")
    _login(client)
    resp = client.post("/api/v1/agents/runtimes", json=dict(_KIRO, version="latest"))
    assert resp.status_code == 400


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
