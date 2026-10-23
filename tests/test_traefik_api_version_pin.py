#!/usr/bin/env python3
"""Unit tests for the Traefik Docker API version pin in both launch paths.

Spec: .kiro/specs/traefik-docker-api-version (bugfix workflow, Task 4)

These are focused, example-based unit tests that assert the shipped fix is
present and correct in the two real launch paths, and that the fix did NOT
touch any of the non-version observables it must leave alone. They complement
(rather than duplicate) the Property 1 exploration test
(``test_traefik_docker_api_version.py``) and the Property 2 preservation
property tests (``test_traefik_api_version_preservation.py``):

* The exploration test drives an in-memory model of the provider startup and
  reconstructs the *unfixed* launch paths to surface the bug counterexample.
* The preservation tests generate many startup configurations and assert the
  pin's blast radius is exactly one field.
* This module makes direct, dedicated assertions against the actual shipped
  ``docker-compose.yml`` and ``deployControlPlan.sh`` - the concrete "the pin
  is here, and only the pin changed" unit checks the design's "Unit Tests"
  section calls for.

Coverage (design "Unit Tests"):
  1. The compose ``traefik`` service ``environment`` includes
     ``DOCKER_API_VERSION=1.44``.
  2. ``deployControlPlan.sh`` defines
     ``TRAEFIK_DOCKER_API_VERSION=${TRAEFIK_DOCKER_API_VERSION:-"1.44"}``.
  3. The host launch prefixes ``nohup "$traefik_cmd" --configfile`` with
     ``env DOCKER_API_VERSION="$TRAEFIK_DOCKER_API_VERSION"`` on the
     ``$runner``/``sudo`` path (so the value crosses the sudo boundary).
  4. Negative/edge: the provider flags, the Docker socket mount, and the
     ``:80``/``:443`` entrypoints are NOT modified by the fix.

**Validates: Requirements 2.1, 2.4, 3.2, 3.3**

Run directly:
    python3 tests/test_traefik_api_version_pin.py
Or via pytest:
    pytest tests/test_traefik_api_version_pin.py -v
"""
import os
import re
import sys

import yaml

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

COMPOSE_PATH = os.path.join(PROJECT_ROOT, "docker-compose.yml")
DEPLOY_SCRIPT_PATH = os.path.join(PROJECT_ROOT, "deployControlPlan.sh")

# The daemon-supported pin the fix negotiates (within modern daemon range,
# compatible with traefik:v3.1).
PINNED_VERSION = "1.44"


# ---------------------------------------------------------------------------
# Helpers that read the real shipped files.
# ---------------------------------------------------------------------------
def _load_traefik_service():
    """Parse docker-compose.yml and return the ``traefik`` service mapping."""
    with open(COMPOSE_PATH, "r", encoding="utf-8") as fh:
        compose = yaml.safe_load(fh)
    return compose["services"]["traefik"]


def _traefik_environment():
    """Return the traefik service ``environment`` as a {KEY: VALUE} mapping.

    Supports both the list (``"K=V"``) and mapping (``{K: V}``) compose forms.
    """
    env = _load_traefik_service().get("environment", []) or []
    result = {}
    if isinstance(env, dict):
        result = {str(k): str(v) for k, v in env.items()}
    else:
        for item in env:
            text = str(item)
            if "=" in text:
                key, value = text.split("=", 1)
                result[key] = value
    return result


def _deploy_script_text():
    with open(DEPLOY_SCRIPT_PATH, "r", encoding="utf-8") as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# 1. docker mode: the compose service pins DOCKER_API_VERSION=1.44.
# ---------------------------------------------------------------------------
def test_compose_traefik_environment_pins_docker_api_version():
    """The compose ``traefik`` service ``environment`` includes
    ``DOCKER_API_VERSION=1.44``.

    **Validates: Requirements 2.1**
    """
    env = _traefik_environment()
    assert "DOCKER_API_VERSION" in env, (
        "traefik compose service must set DOCKER_API_VERSION in its "
        f"environment; got keys={sorted(env)}"
    )
    assert env["DOCKER_API_VERSION"] == PINNED_VERSION, (
        f"expected DOCKER_API_VERSION={PINNED_VERSION}, got "
        f"{env['DOCKER_API_VERSION']!r}"
    )


# ---------------------------------------------------------------------------
# 2. locally mode: the mirrored shell default is defined.
# ---------------------------------------------------------------------------
def test_deploy_script_defines_default_api_version_variable():
    """``deployControlPlan.sh`` defines
    ``TRAEFIK_DOCKER_API_VERSION=${TRAEFIK_DOCKER_API_VERSION:-"1.44"}``.

    The ``${VAR:-"1.44"}`` default mirrors the compose pin and keeps the value
    configurable (e.g. via conf/deploy.ini) while defaulting to the
    daemon-supported version.

    **Validates: Requirements 2.4**
    """
    script = _deploy_script_text()
    # Allow flexible whitespace, but require the :- default to exactly 1.44.
    pattern = re.compile(
        r'TRAEFIK_DOCKER_API_VERSION=\$\{TRAEFIK_DOCKER_API_VERSION:-"'
        + re.escape(PINNED_VERSION)
        + r'"\}'
    )
    assert pattern.search(script), (
        "deployControlPlan.sh must define "
        'TRAEFIK_DOCKER_API_VERSION=${TRAEFIK_DOCKER_API_VERSION:-"1.44"}'
    )


# ---------------------------------------------------------------------------
# 3. locally mode: the pin crosses the sudo boundary via `env`.
# ---------------------------------------------------------------------------
def test_host_launch_prefixes_nohup_with_env_pin_on_runner_path():
    """The host launch prefixes ``nohup "$traefik_cmd" --configfile`` with
    ``env DOCKER_API_VERSION="$TRAEFIK_DOCKER_API_VERSION"`` on the
    ``$runner``/``sudo`` path.

    ``env VAR=value`` sets the variable directly in the launched process
    environment, so it survives ``sudo``'s default env reset (which a plain
    ``export`` would not) and reaches the Docker provider.

    **Validates: Requirements 2.4**
    """
    script = _deploy_script_text()

    # The order matters: $runner (sudo) -> env DOCKER_API_VERSION=... -> nohup
    # "$traefik_cmd" --configfile. Allow line-continuations / whitespace between
    # the tokens.
    pattern = re.compile(
        r"\$runner\s+env\s+DOCKER_API_VERSION=\"\$TRAEFIK_DOCKER_API_VERSION\""
        r"[\s\\]+nohup\s+\"\$traefik_cmd\"\s+--configfile",
        re.MULTILINE,
    )
    assert pattern.search(script), (
        "the host launch must read "
        '`$runner env DOCKER_API_VERSION="$TRAEFIK_DOCKER_API_VERSION" '
        'nohup "$traefik_cmd" --configfile ...` so the pin crosses the sudo '
        "boundary and reaches the provider process"
    )


def test_pin_uses_env_prefix_not_plain_export_for_host_launch():
    """Edge: the pin reaches the launch via the ``env`` prefix, not a plain
    ``export DOCKER_API_VERSION=...`` that ``sudo`` would strip.

    A plain ``export DOCKER_API_VERSION=`` line would be a regression back into
    the bug (the exported var is stripped at the sudo boundary), so assert it is
    NOT how the value is delivered.

    **Validates: Requirements 2.4**
    """
    script = _deploy_script_text()
    # No bare `export DOCKER_API_VERSION=...` statement delivering the pin.
    assert not re.search(r"^\s*export\s+DOCKER_API_VERSION=", script, re.MULTILINE), (
        "the pin must be delivered via the `env` prefix, not a plain export "
        "that sudo strips"
    )


# ---------------------------------------------------------------------------
# 4. Negative / edge: the fix does NOT modify provider flags, the socket
#    mount, or the entrypoints.
# ---------------------------------------------------------------------------
def test_provider_flags_not_modified_by_fix():
    """The Docker/file provider flags are unchanged by the version pin.

    The fix only sets an environment variable; it must not add, remove, or alter
    any provider command flag.

    **Validates: Requirements 3.2**
    """
    command = _load_traefik_service()["command"]
    assert "--providers.docker=true" in command
    assert "--providers.docker.exposedByDefault=false" in command
    assert "--providers.docker.network=swautomorph-shared" in command
    assert "--providers.file.directory=/etc/traefik/dynamic" in command
    assert "--providers.file.watch=true" in command


def test_docker_socket_mount_not_modified_by_fix():
    """The read-only Docker socket mount is unchanged by the version pin.

    **Validates: Requirements 3.2**
    """
    volumes = _load_traefik_service()["volumes"]
    assert any(
        "/var/run/docker.sock:/var/run/docker.sock" in str(v) for v in volumes
    ), f"expected the Docker socket mount to be present; got volumes={volumes}"
    # And it remains read-only (``:ro``).
    assert any(
        str(v).startswith("/var/run/docker.sock:/var/run/docker.sock")
        and str(v).endswith(":ro")
        for v in volumes
    ), "the Docker socket mount must remain read-only (:ro)"


def test_entrypoints_not_modified_by_fix():
    """The ``:80``/``:443`` entrypoints (command flags and published ports) are
    unchanged by the version pin.

    **Validates: Requirements 3.2, 3.3**
    """
    svc = _load_traefik_service()
    command = svc["command"]
    ports = [str(p) for p in svc["ports"]]

    assert "--entryPoints.web.address=:80" in command
    assert "--entryPoints.websecure.address=:443" in command
    assert "80:80" in ports
    assert "443:443" in ports


def test_fix_touches_only_the_environment_pin():
    """Structural negative check: the compose service carries the single pin
    entry and the non-version sections (command, volumes, ports, networks) are
    the concrete shipped values the fix must leave alone.

    This is the docker-mode counterpart to the host-launch assertions: the only
    state the fix introduces is the DOCKER_API_VERSION entry.

    **Validates: Requirements 3.2, 3.3**
    """
    svc = _load_traefik_service()
    env = _traefik_environment()

    # The pin is the only DOCKER_API_VERSION entry, set once, to 1.44.
    docker_api_entries = [k for k in env if k == "DOCKER_API_VERSION"]
    assert docker_api_entries == ["DOCKER_API_VERSION"]
    assert env["DOCKER_API_VERSION"] == PINNED_VERSION

    # The image is still the version-compatible traefik:v3.1 (the pin value is
    # chosen to be compatible with it).
    assert svc["image"] == "traefik:v3.1"

    # The shared network remains attached (unchanged observable).
    assert "swautomorph-shared" in svc["networks"]


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([os.path.abspath(__file__), "-v"]))
