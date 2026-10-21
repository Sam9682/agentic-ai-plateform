#!/usr/bin/env python3
"""Tests for the Traefik control-plane route (bare-domain 404 fix).

Regression coverage for the bug where ``curl https://<domain>`` returned
Traefik's native ``404 page not found`` because no router matched the bare
domain: per-app route files only cover ``Host(...) && PathPrefix(/{user}/{app})``
and nothing routed the platform's own Flask control plane (gunicorn on
127.0.0.1:5000).

The fix adds a ``control-plane`` router matching ``Host(<domain>)`` (no path)
that forwards to the control plane, plus wiring so ``sync_all_locations`` always
(re)writes ``traefik/dynamic/control-plane.yml``.

Run directly:
    python3 tests/test_traefik_control_plane.py
Or via pytest:
    pytest tests/test_traefik_control_plane.py
"""
import os
import sys

import yaml

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src import nginx_manager as nm
from src.nginx_manager import build_control_plane_config, write_control_plane_config


def test_control_plane_router_is_bare_host_no_pathprefix():
    """The control-plane router matches the bare domain with no PathPrefix.

    A bare ``Host(...)`` rule is shorter than the per-app
    ``Host(...) && PathPrefix(...)`` rules, so Traefik's length-based priority
    keeps app routes ahead while this router catches everything else (dashboard,
    /api, /login, static) — which is exactly what the bare domain needs to stop
    returning 404.
    """
    config = build_control_plane_config("example.com")
    http = config["http"]

    routers = http["routers"]
    assert len(routers) == 1
    router = next(iter(routers.values()))
    assert router["rule"] == "Host(`example.com`)"
    assert "PathPrefix" not in router["rule"]
    assert router["entryPoints"] == ["websecure"]
    assert router["tls"] == {}


def test_control_plane_service_targets_gunicorn_backend():
    """The service load balancer points at the control-plane host:port."""
    config = build_control_plane_config("example.com", host="127.0.0.1", port=5000)
    service = next(iter(config["http"]["services"].values()))
    servers = service["loadBalancer"]["servers"]
    assert servers == [{"url": "http://127.0.0.1:5000"}]


def test_control_plane_backend_overridable():
    """Backend host/port are overridable for non-default deployments."""
    config = build_control_plane_config("d.test", host="10.0.0.5", port=8000)
    service = next(iter(config["http"]["services"].values()))
    assert service["loadBalancer"]["servers"][0]["url"] == "http://10.0.0.5:8000"


def test_write_control_plane_config_writes_valid_yaml(tmp_path):
    """write_control_plane_config writes a valid, loadable YAML route file."""
    target = tmp_path / "control-plane.yml"
    assert write_control_plane_config(domain="d.test", path=str(target)) is True
    assert target.exists()

    loaded = yaml.safe_load(target.read_text())
    router = next(iter(loaded["http"]["routers"].values()))
    assert router["rule"] == "Host(`d.test`)"


def test_sync_all_locations_writes_control_plane(tmp_path, monkeypatch):
    """sync_all_locations always (re)writes the control-plane route file.

    Even with zero deployed apps, the bare-domain route must exist so the
    dashboard is reachable.
    """
    # Point the dynamic dir at a temp location so we don't touch the real one.
    monkeypatch.setattr(nm, "TRAEFIK_DYNAMIC_DIR", str(tmp_path))

    class _DB:
        def execute_query(self, *_a, **_k):
            return []  # no apps

    assert nm.sync_all_locations(_DB()) is True

    cp = tmp_path / "control-plane.yml"
    assert cp.exists(), "control-plane.yml must be written by sync"
    loaded = yaml.safe_load(cp.read_text())
    router = next(iter(loaded["http"]["routers"].values()))
    assert "PathPrefix" not in router["rule"]


def test_sync_cleanup_preserves_control_plane(tmp_path, monkeypatch):
    """Stale-file cleanup only removes app-*.yml, never control-plane.yml."""
    monkeypatch.setattr(nm, "TRAEFIK_DYNAMIC_DIR", str(tmp_path))

    # Pre-seed a stale app route that is NOT in the (empty) DB.
    stale = tmp_path / "app-ghost-app.yml"
    stale.write_text("http: {}\n")

    class _DB:
        def execute_query(self, *_a, **_k):
            return []

    assert nm.sync_all_locations(_DB()) is True
    assert not stale.exists(), "stale app route should be removed"
    assert (tmp_path / "control-plane.yml").exists(), "control-plane must survive"


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
