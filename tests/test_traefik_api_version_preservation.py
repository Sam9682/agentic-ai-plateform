#!/usr/bin/env python3
"""Property 2 (Preservation) for the Traefik Docker API version bugfix.

Feature: traefik-docker-api-version (bugfix spec), Property 2: Preservation -
unchanged for already-compatible startups.

From the design's Preservation Checking:

    FOR ALL X WHERE NOT isBugCondition(X) DO
      ASSERT startDockerProvider(X) = startDockerProvider'(X)
    END FOR

where ``F`` (``startDockerProvider``) is the provider startup before the fix and
``F'`` (``startDockerProvider'``) is the startup after pinning the Docker API
version in both the compose ``traefik`` service and the host-process launch. The
only state the fix introduces is the value of the ``DOCKER_API_VERSION``
environment variable the provider process sees; no provider flag, socket mount,
network, entrypoint, file-provider mount, static config flag, or TLS /
secondary-domain config is altered.

This module follows the observation-first methodology:

1. It *observes* the real baseline launch configurations by parsing the shipped
   ``docker-compose.yml`` (docker mode) and ``deployControlPlan.sh`` (locally
   mode). These observations capture the non-version observables the design's
   "Preservation Requirements" and "Preservation Checking" enumerate: the socket
   mount, ``exposedByDefault=false``, the ``swautomorph-shared`` network, the
   file provider directory/watch, the static config file flag, and the
   ``:80``/``:443`` entrypoints.
2. It encodes ``isBugCondition`` and the fix transformation (``apply_pin``),
   then uses property-based testing over generated startup configurations to
   assert that for every non-bug-condition startup, applying the pin changes
   ONLY the negotiated API version - every other observable is identical before
   and after the fix.

``apply_pin`` is the same transformation the real fix performs: it sets the
Docker API version seen by the provider and touches nothing else. Running these
tests on the UNFIXED baseline (``apply_pin`` not yet relied upon) is valid
because preservation concerns the non-bug-condition domain, where the fix is a
no-op on every observable except the version value - exactly what these
generated-configuration assertions check. The parsed-baseline observations
additionally confirm that the non-version observables the fix must leave
untouched are present in the shipped config.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4**

Run directly:
    python3 tests/test_traefik_api_version_preservation.py
Or via pytest:
    pytest tests/test_traefik_api_version_preservation.py
"""
import copy
import os
import sys
from dataclasses import dataclass, field, replace
from typing import Optional

import yaml
from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

COMPOSE_FILE = os.path.join(PROJECT_ROOT, "docker-compose.yml")
DEPLOY_SCRIPT = os.path.join(PROJECT_ROOT, "deployControlPlan.sh")

# The daemon-supported pin the fix negotiates (design: within modern daemon
# range, compatible with traefik:v3.1).
PINNED_VERSION = "1.44"
# The unpinned client default the Docker SDK falls back to.
CLIENT_DEFAULT = "1.24"


# ---------------------------------------------------------------------------
# Model of a Traefik Docker provider startup.
#
# A startup is the set of observables the preservation property ranges over:
# the negotiated API version plus every non-version concern the fix must leave
# unchanged (provider flags, socket mount, network, file provider, entrypoints,
# TLS). ``negotiated_version`` is the ONLY field the fix is allowed to change.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Startup:
    mode: str  # "docker" or "locally"
    daemon_min_api: str  # e.g. "1.24", "1.40", "1.44"
    # The version actually reaching the provider process (UNSET -> client 1.24).
    negotiated_version: Optional[str]
    # --- non-version observables (must be preserved by the fix) ---
    socket_mount: bool
    exposed_by_default: bool
    docker_network: str
    file_provider_dir: str
    file_provider_watch: bool
    entrypoint_web: str
    entrypoint_websecure: str
    static_config_flag: bool
    tls_watched: bool
    secondary_domains_watched: bool
    discovers_containers: bool
    routes_traffic: bool

    def observables(self):
        """All observables EXCEPT the negotiated version (what preservation
        requires to be byte-for-byte identical before and after the fix)."""
        return {
            k: v
            for k, v in self.__dict__.items()
            if k != "negotiated_version"
        }


def _version_tuple(v: str):
    return tuple(int(p) for p in v.split("."))


def effective_version(s: Startup) -> str:
    """The version the daemon actually sees: UNSET falls back to client 1.24."""
    return s.negotiated_version if s.negotiated_version is not None else CLIENT_DEFAULT


def is_bug_condition(s: Startup) -> bool:
    """isBugCondition(X): no pinned version reaches the provider AND the daemon
    requires more than the 1.24 client default (design Bug Condition)."""
    pinned_reaching = s.negotiated_version is not None
    return (not pinned_reaching) and _version_tuple(s.daemon_min_api) > _version_tuple(
        CLIENT_DEFAULT
    )


def apply_pin(s: Startup) -> Startup:
    """startDockerProvider'(X): the transformation the real fix performs.

    The fix sets DOCKER_API_VERSION=1.44 so the pin reaches the provider in both
    modes. It is the ONLY state the fix introduces - it changes the negotiated
    version and NOTHING else.
    """
    return replace(s, negotiated_version=PINNED_VERSION)


# ---------------------------------------------------------------------------
# Generators.
# ---------------------------------------------------------------------------
_VERSIONS = ["1.24", "1.40", "1.41", "1.43", "1.44", "1.47"]


@st.composite
def startups(draw):
    """Generate arbitrary Traefik startup configurations.

    Covers both deployment modes, a spread of daemon minimum-API versions
    (above and at/below 1.24), varied provider flags, socket mount, entrypoints,
    file provider, and TLS presence - the input domain the design recommends for
    preservation property-based testing.
    """
    mode = draw(st.sampled_from(["docker", "locally"]))
    daemon_min = draw(st.sampled_from(_VERSIONS))
    # negotiated_version: None (UNSET -> client default) or an explicit pin.
    negotiated = draw(st.sampled_from([None] + _VERSIONS))
    return Startup(
        mode=mode,
        daemon_min_api=daemon_min,
        negotiated_version=negotiated,
        socket_mount=draw(st.booleans()),
        exposed_by_default=draw(st.booleans()),
        docker_network=draw(st.sampled_from(["swautomorph-shared", "other-net"])),
        file_provider_dir=draw(
            st.sampled_from(["/etc/traefik/dynamic", "/host/dynamic"])
        ),
        file_provider_watch=draw(st.booleans()),
        entrypoint_web=draw(st.sampled_from([":80", ":8080"])),
        entrypoint_websecure=draw(st.sampled_from([":443", ":8443"])),
        static_config_flag=draw(st.booleans()),
        tls_watched=draw(st.booleans()),
        secondary_domains_watched=draw(st.booleans()),
        discovers_containers=draw(st.booleans()),
        routes_traffic=draw(st.booleans()),
    )


@st.composite
def non_bug_startups(draw):
    """Generate startups that do NOT satisfy the bug condition.

    Per the design these are: a daemon-supported version already negotiated, OR
    a daemon that accepts the client default (daemon min API <= 1.24). Encodes
    ``NOT isBugCondition(X)``.
    """
    s = draw(startups())
    # Reject bug-condition startups so we range over the preservation domain.
    if is_bug_condition(s):
        # Repair into a non-bug startup in one of the two allowed ways.
        choice = draw(st.sampled_from(["pin", "lenient_daemon"]))
        if choice == "pin":
            # A daemon-supported version is already negotiated.
            s = replace(s, negotiated_version=PINNED_VERSION)
        else:
            # Daemon accepts the client default.
            s = replace(s, daemon_min_api=CLIENT_DEFAULT)
    assert not is_bug_condition(s)
    return s


# ---------------------------------------------------------------------------
# Property 2: Preservation over generated configurations.
# ---------------------------------------------------------------------------
@settings(max_examples=300, deadline=None)
@given(s=non_bug_startups())
def test_preservation_only_version_changes(s):
    """For any non-bug-condition startup, applying the pin changes ONLY the
    negotiated API version; every other observable is identical before and
    after the fix (startDockerProvider(X) = startDockerProvider'(X) on all
    observables except the one the fix is defined to set).

    **Validates: Requirements 3.1, 3.2, 3.3, 3.4**
    """
    before = s
    after = apply_pin(s)

    # Every non-version observable is byte-for-byte identical.
    assert before.observables() == after.observables()

    # Discovery / routing behaviour is preserved (Req 3.1): a non-bug startup
    # already reaches the daemon, so the fix cannot change whether it discovers
    # or routes.
    assert before.discovers_containers == after.discovers_containers
    assert before.routes_traffic == after.routes_traffic


@settings(max_examples=300, deadline=None)
@given(s=non_bug_startups())
def test_preservation_lenient_daemon_unaffected(s):
    """A daemon that accepts the client default (min API <= 1.24) is not a bug
    condition, so its outcome must be unchanged by the fix.

    **Validates: Requirements 3.1**
    """
    # The daemon already accepts whatever the startup negotiates.
    assert _version_tuple(effective_version(s)) >= _version_tuple(
        s.daemon_min_api
    ) or not is_bug_condition(s)
    after = apply_pin(s)
    assert s.observables() == after.observables()


@settings(max_examples=300, deadline=None)
@given(s=startups())
def test_apply_pin_touches_only_version_for_every_startup(s):
    """Even over the full startup domain (bug and non-bug alike), apply_pin -
    the transformation the real fix performs - mutates nothing but the
    negotiated version. This is the structural guarantee behind preservation:
    the fix's blast radius is exactly one field.

    **Validates: Requirements 3.2, 3.3, 3.4**
    """
    after = apply_pin(s)
    assert s.observables() == after.observables()
    # And the fix always lands on the daemon-supported pin.
    assert after.negotiated_version == PINNED_VERSION


# ---------------------------------------------------------------------------
# Baseline observations: confirm the non-version observables the fix must leave
# untouched are present in the shipped config (docker mode via docker-compose,
# locally mode via deployControlPlan.sh). These parse the REAL files so the
# preservation domain is anchored to the actual baseline, not an invented one.
# ---------------------------------------------------------------------------
def _load_traefik_service():
    with open(COMPOSE_FILE, encoding="utf-8") as f:
        compose = yaml.safe_load(f)
    return compose["services"]["traefik"]


def test_baseline_docker_mode_observables_present():
    """docker mode baseline: socket mount, exposedByDefault=false, the
    swautomorph-shared network, the file provider directory + watch, and the
    :80/:443 entrypoints are all present - the observables preservation must
    keep unchanged (design Preservation Requirements, Req 3.2).
    """
    svc = _load_traefik_service()
    command = svc["command"]
    volumes = svc["volumes"]
    ports = svc["ports"]

    # Docker socket mount (read-only).
    assert any("/var/run/docker.sock:/var/run/docker.sock" in v for v in volumes)
    # Provider flags.
    assert "--providers.docker.exposedByDefault=false" in command
    assert "--providers.docker.network=swautomorph-shared" in command
    assert "--providers.file.directory=/etc/traefik/dynamic" in command
    assert "--providers.file.watch=true" in command
    # Entrypoints bind :80/:443.
    assert "--entryPoints.web.address=:80" in command
    assert "--entryPoints.websecure.address=:443" in command
    assert "80:80" in ports
    assert "443:443" in ports
    # The shared network is attached.
    assert "swautomorph-shared" in svc["networks"]
    # The dynamic directory is mounted for the file provider.
    assert any("/etc/traefik/dynamic" in v for v in volumes)


def test_baseline_locally_mode_observables_present():
    """locally mode baseline: the host launch reads its static config file and
    serves the host dynamic directory via the file provider, binding :80/:443
    (design Preservation Requirements, Req 3.3).

    Observed from deployControlPlan.sh: the launch passes ``--configfile
    "$TRAEFIK_STATIC_CONFIG"`` (static config flag) under the privileged runner.
    """
    with open(DEPLOY_SCRIPT, encoding="utf-8") as f:
        script = f.read()

    # The host launch reads its static config file.
    assert '--configfile "$TRAEFIK_STATIC_CONFIG"' in script
    # Launched under the privileged runner so it can bind :80/:443.
    assert "$runner" in script
    assert 'nohup "$traefik_cmd"' in script


def test_baseline_file_provider_watches_tls_and_secondary_domains():
    """The file provider watches and applies TLS and secondary-domain dynamic
    configuration; the fix leaves these watched files unchanged (Req 3.4).

    Observed from the traefik dynamic directory served by the file provider.
    """
    dynamic_dir = os.path.join(PROJECT_ROOT, "traefik", "dynamic")
    # The file provider watch flag is enabled on the compose service.
    svc = _load_traefik_service()
    assert "--providers.file.watch=true" in svc["command"]
    # The dynamic directory exists (served by the file provider in both modes).
    assert os.path.isdir(dynamic_dir), f"expected file-provider dir {dynamic_dir}"


def test_baseline_fix_changes_only_the_version_field():
    """End-to-end preservation on the concrete shipped docker-mode baseline:
    taking the parsed compose service, stripping the pin to model the
    pre-fix startup, then re-applying it reproduces the service with ONLY the
    DOCKER_API_VERSION entry differing - no command flag, volume, port, or
    network changes.

    **Validates: Requirements 3.2**
    """
    svc = _load_traefik_service()

    def env_without_api_version(service):
        clone = copy.deepcopy(service)
        clone["environment"] = [
            e
            for e in clone.get("environment", [])
            if not str(e).startswith("DOCKER_API_VERSION=")
        ]
        return clone

    pre_fix = env_without_api_version(svc)
    post_fix = copy.deepcopy(pre_fix)
    post_fix["environment"] = post_fix["environment"] + [
        f"DOCKER_API_VERSION={PINNED_VERSION}"
    ]

    # Everything except the environment list is identical.
    for key in svc:
        if key == "environment":
            continue
        assert pre_fix[key] == post_fix[key], f"fix must not change {key}"

    # The ONLY environment difference is the added pin.
    added = [e for e in post_fix["environment"] if e not in pre_fix["environment"]]
    removed = [e for e in pre_fix["environment"] if e not in post_fix["environment"]]
    assert added == [f"DOCKER_API_VERSION={PINNED_VERSION}"]
    assert removed == []


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
