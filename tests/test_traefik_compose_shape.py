#!/usr/bin/env python3
"""Example test: assert the root docker-compose.yml has the Traefik shape.

This is the example test for task 6.3 of the nginx-to-traefik-migration spec.
It parses the repository-root ``docker-compose.yml`` and asserts that the
nginx service is gone and that Traefik is wired as the single entrypoint with
both the Docker label provider and the file provider enabled, the standard
mounts in place, and the shared network declared as external.

Validates: Requirements 1.1, 1.2, 2.2, 4.2

Run directly:
    python3 tests/test_traefik_compose_shape.py
Or via pytest:
    pytest tests/test_traefik_compose_shape.py -v
"""
import os

import yaml

# Compose path is resolved relative to this test file: PROJECT_ROOT/docker-compose.yml
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPOSE_PATH = os.path.join(PROJECT_ROOT, "docker-compose.yml")


def _load_compose():
    with open(COMPOSE_PATH, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def test_compose_file_exists():
    assert os.path.isfile(COMPOSE_PATH), f"missing compose file at {COMPOSE_PATH}"


def test_no_nginx_service():
    """Requirement 2.2: the nginx sidecar service is removed."""
    compose = _load_compose()
    services = compose.get("services", {})
    assert "nginx" not in services, "nginx service should not exist in docker-compose.yml"


def test_traefik_service_image_and_ports():
    """Requirements 1.1: Traefik is the single :80/:443 entrypoint."""
    compose = _load_compose()
    services = compose.get("services", {})

    assert "traefik" in services, "traefik service must exist"
    traefik = services["traefik"]

    image = traefik.get("image", "")
    assert image.startswith("traefik:"), f"unexpected traefik image: {image!r}"

    # Normalize published ports (compose allows short "host:container" strings).
    published = set()
    for port in traefik.get("ports", []):
        published.add(str(port).strip().strip('"'))
    assert "80:80" in published, f"traefik must publish 80:80, got {published}"
    assert "443:443" in published, f"traefik must publish 443:443, got {published}"


def test_traefik_enables_docker_and_file_providers():
    """Requirements 1.2 and 4.2: both the Docker and file providers are on."""
    compose = _load_compose()
    traefik = compose["services"]["traefik"]
    command = traefik.get("command", [])

    assert isinstance(command, list), "traefik command should be a list of flags"

    # Docker label provider must be explicitly enabled.
    assert any(
        flag.strip() == "--providers.docker=true" for flag in command
    ), f"--providers.docker=true missing from command: {command}"

    # File provider must point at the dynamic directory and watch it.
    assert any(
        flag.strip().startswith("--providers.file.directory=") for flag in command
    ), f"--providers.file.directory=... missing from command: {command}"
    assert any(
        flag.strip() == "--providers.file.watch=true" for flag in command
    ), f"--providers.file.watch=true missing from command: {command}"


def test_traefik_mounts():
    """Requirements 2.2 and 4.2: docker socket (ro), ssl (ro), dynamic (ro)."""
    compose = _load_compose()
    traefik = compose["services"]["traefik"]
    volumes = {str(v).strip() for v in traefik.get("volumes", [])}

    assert "/var/run/docker.sock:/var/run/docker.sock:ro" in volumes, (
        f"docker socket must be mounted read-only, got {volumes}"
    )
    assert "./ssl:/etc/traefik/ssl:ro" in volumes, (
        f"ssl directory must be mounted read-only, got {volumes}"
    )
    assert "./traefik/dynamic:/etc/traefik/dynamic:ro" in volumes, (
        f"dynamic config directory must be mounted read-only, got {volumes}"
    )


def test_shared_network_is_external():
    """Requirements 1.2: swautomorph-shared is declared as an external network."""
    compose = _load_compose()
    networks = compose.get("networks", {})

    assert "swautomorph-shared" in networks, "swautomorph-shared network must be declared"
    shared = networks["swautomorph-shared"] or {}
    assert shared.get("external") is True, (
        f"swautomorph-shared must be external: true, got {shared}"
    )


if __name__ == "__main__":
    import sys

    import pytest

    sys.exit(pytest.main([os.path.abspath(__file__), "-v"]))
