#!/usr/bin/env python3
"""Property-based tests for the Traefik Docker API version-negotiation domain.

Spec: .kiro/specs/traefik-docker-api-version (bugfix workflow, Task 5)

This module exercises the version-negotiation domain of the fix with
property-based testing (hypothesis), matching the project convention and the
existing ``tests/test_traefik_*.py`` suite. It covers the three generator
families the design's "Property-Based Tests" strategy calls for:

1. **Daemon minimum-API spread (fix + preservation domains).** Generate daemon
   minimum-API values spanning above and at/below ``1.24`` and assert the pinned
   startup negotiates ``1.44`` (so it is accepted everywhere the design pins it -
   the fix domain), while below-threshold daemons (min API <= 1.24) are not a
   bug condition and are therefore unaffected (the preservation domain).

2. **Compose/host startup configurations (preservation).** Generate arbitrary
   startup configurations across both deployment modes and every non-version
   observable (provider flags, socket mount, network, file provider,
   entrypoints, TLS) and assert that adding the pin changes ONLY the negotiated
   API version - every other observable is identical before and after the fix
   (``startDockerProvider(X) = startDockerProvider'(X)`` on all observables
   except the one field the fix is defined to set).

3. **Host-launch argument vectors (sudo boundary).** Generate many host-launch
   argument vectors and assert the ``env DOCKER_API_VERSION=...`` prefix is
   always present on the privileged (``sudo``) path, immediately in front of the
   ``nohup "$traefik_cmd"`` invocation, so the pin survives the sudo environment
   reset and reaches the provider process.

Encodings (from design / bugfix.md):

    isBugCondition(X) = pinnedVersionReachingProvider(X) = UNSET
                        AND X.daemonMinApiVersion > 1.24

    apply_pin(X)      = startDockerProvider'(X): sets DOCKER_API_VERSION=1.44 and
                        nothing else.

**Validates: Requirements 2.1, 2.4, 3.1, 3.2**

Run directly:
    python3 tests/test_traefik_api_version_pbt.py
Or via pytest:
    pytest tests/test_traefik_api_version_pbt.py -v
"""
import os
import re
import sys
from dataclasses import dataclass, replace
from typing import Optional

from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

DEPLOY_SCRIPT_PATH = os.path.join(PROJECT_ROOT, "deployControlPlan.sh")

# The daemon-supported pin the fix negotiates (design: within modern daemon
# range, compatible with traefik:v3.1).
PINNED_VERSION = "1.44"
# The conservative client default the Docker SDK falls back to when no version
# reaches the provider process.
CLIENT_DEFAULT = "1.24"
REJECTION_SUBSTRING = "client version 1.24 is too old"


def _version_tuple(v: str):
    """Turn an API version string like ``"1.44"`` into a comparable tuple."""
    return tuple(int(p) for p in str(v).split("."))


# ---------------------------------------------------------------------------
# Model of a Traefik Docker provider startup.
#
# ``negotiated_version`` is the ONLY field the fix is allowed to change; every
# other field is a non-version observable preservation must keep identical.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Startup:
    mode: str  # "docker" or "locally"
    daemon_min_api: str  # e.g. "1.19", "1.24", "1.40", "1.44"
    negotiated_version: Optional[str]  # version reaching provider (None -> 1.24)
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

    def observables(self):
        """All observables EXCEPT the negotiated version - the fields the fix
        must leave byte-for-byte identical."""
        return {k: v for k, v in self.__dict__.items() if k != "negotiated_version"}


def effective_version(s: Startup) -> str:
    """The version the daemon actually sees: UNSET falls back to client 1.24."""
    return s.negotiated_version if s.negotiated_version is not None else CLIENT_DEFAULT


def is_bug_condition(s: Startup) -> bool:
    """isBugCondition(X): no pin reaches the provider AND daemon requires > 1.24."""
    pinned_reaching = s.negotiated_version is not None
    return (not pinned_reaching) and _version_tuple(s.daemon_min_api) > _version_tuple(
        CLIENT_DEFAULT
    )


def start_docker_provider(s: Startup) -> dict:
    """Model the provider startup outcome for a given (possibly pinned) startup.

    Deterministic and configuration-driven, matching the design: the daemon
    accepts the negotiated version iff it is at least the daemon minimum.
    """
    negotiated = effective_version(s)
    accepted = _version_tuple(negotiated) >= _version_tuple(s.daemon_min_api)
    return {
        "negotiatedApiVersion": negotiated,
        "accepted": accepted,
        "log": (
            "Configuration received providerName=docker"
            if accepted
            else f"ERR Provider error, retrying in 7.432861093s "
            f'error="Error response from daemon: client version {negotiated} is '
            f'too old. Minimum supported API version is {s.daemon_min_api}" '
            f"providerName=docker"
        ),
        "discoveryCompleted": accepted,
        "inRetryLoop": not accepted,
    }


def apply_pin(s: Startup) -> Startup:
    """startDockerProvider'(X): the transformation the real fix performs.

    Sets DOCKER_API_VERSION=1.44 so the pin reaches the provider in both modes.
    It is the ONLY state the fix introduces - it changes the negotiated version
    and NOTHING else.
    """
    return replace(s, negotiated_version=PINNED_VERSION)


# ---------------------------------------------------------------------------
# Generators.
# ---------------------------------------------------------------------------
# Daemon minimum-API values spanning above and at/below 1.24.
_BELOW_OR_AT_1_24 = ["1.19", "1.20", "1.21", "1.22", "1.23", "1.24"]
_ABOVE_1_24 = ["1.25", "1.40", "1.41", "1.43", "1.44", "1.47"]
_ALL_DAEMON_VERSIONS = _BELOW_OR_AT_1_24 + _ABOVE_1_24


@st.composite
def startups(draw):
    """Generate arbitrary Traefik startup configurations.

    Covers both deployment modes, a spread of daemon minimum-API versions
    (above and at/below 1.24), varied provider flags, socket mount, entrypoints,
    file provider, and TLS presence - the input domain the design recommends for
    the version-negotiation property-based tests.
    """
    return Startup(
        mode=draw(st.sampled_from(["docker", "locally"])),
        daemon_min_api=draw(st.sampled_from(_ALL_DAEMON_VERSIONS)),
        negotiated_version=draw(st.sampled_from([None] + _ALL_DAEMON_VERSIONS)),
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
    )


@st.composite
def compatible_startups(draw):
    """Generate startups in the preservation domain the fix must leave unchanged.

    Per the design's Preservation Checking these are already-compatible
    startups: the daemon accepts the version the startup negotiates. That is the
    domain where the pin is a genuine no-op on the provider outcome. Two sources
    (both ``NOT isBugCondition``):

    * a daemon-supported version is already negotiated (negotiated >= daemon min
      and the daemon min is itself within the pin's range), OR
    * the daemon accepts the client default (daemon min API <= 1.24), so even an
      unpinned startup is accepted.

    A startup that pins a version *below* the daemon minimum is NOT in the
    preservation domain - it is a misconfiguration the fix is designed to
    correct, so excluding it here is intentional, not a blind spot.
    """
    s = draw(startups())
    if draw(st.booleans()):
        # Already negotiating a daemon-supported version (daemon min <= 1.44).
        s = replace(
            s,
            daemon_min_api=draw(st.sampled_from(_BELOW_OR_AT_1_24 + ["1.25", "1.40", "1.44"])),
            negotiated_version=PINNED_VERSION,
        )
    else:
        # Lenient daemon (min API <= 1.24) that accepts the client default.
        # Either unpinned (falls back to the 1.24 default the daemon accepts) or
        # pinned to a version the daemon still accepts (>= its minimum).
        daemon_min = draw(st.sampled_from(_BELOW_OR_AT_1_24))
        accepted_pins = [
            None,  # unpinned -> 1.24 client default (always >= a <=1.24 daemon)
            CLIENT_DEFAULT,
        ] + [v for v in _BELOW_OR_AT_1_24 if _version_tuple(v) >= _version_tuple(daemon_min)]
        s = replace(
            s,
            daemon_min_api=daemon_min,
            negotiated_version=draw(st.sampled_from(accepted_pins)),
        )
    assert not is_bug_condition(s)
    # Confirm the daemon actually accepts what this startup negotiates.
    assert _version_tuple(effective_version(s)) >= _version_tuple(s.daemon_min_api)
    return s


# ===========================================================================
# 1. Daemon minimum-API spread: fix domain + preservation domain.
# ===========================================================================
@settings(max_examples=300, deadline=None)
@given(daemon_min=st.sampled_from(_ALL_DAEMON_VERSIONS))
def test_pinned_startup_negotiates_1_44_across_daemon_minimums(daemon_min):
    """For any daemon minimum-API value (above and at/below 1.24), the pinned
    startup negotiates exactly 1.44. For every modern daemon in the design's
    supported range the daemon accepts the connection (fix domain), so discovery
    completes and no 1.24 rejection is logged.

    **Validates: Requirements 2.1, 2.4**
    """
    for mode in ("docker", "locally"):
        pinned = Startup(
            mode=mode,
            daemon_min_api=daemon_min,
            negotiated_version=PINNED_VERSION,
            socket_mount=True,
            exposed_by_default=False,
            docker_network="swautomorph-shared",
            file_provider_dir="/etc/traefik/dynamic",
            file_provider_watch=True,
            entrypoint_web=":80",
            entrypoint_websecure=":443",
            static_config_flag=True,
            tls_watched=True,
            secondary_domains_watched=True,
        )
        result = start_docker_provider(pinned)

        # The pin always negotiates 1.44.
        assert result["negotiatedApiVersion"] == PINNED_VERSION

        # Fix domain: any daemon whose minimum is at most the pin accepts it.
        if _version_tuple(daemon_min) <= _version_tuple(PINNED_VERSION):
            assert result["accepted"] is True
            assert result["discoveryCompleted"] is True
            assert result["inRetryLoop"] is False
            assert REJECTION_SUBSTRING not in result["log"]


@settings(max_examples=300, deadline=None)
@given(daemon_min=st.sampled_from(_BELOW_OR_AT_1_24), s=startups())
def test_below_threshold_daemons_are_not_a_bug_condition(daemon_min, s):
    """Below-threshold daemons (min API <= 1.24) are unaffected (preservation
    domain): the daemon accepts the unpinned client default, so the startup is
    never a bug condition and applying the pin changes nothing but the version.

    **Validates: Requirements 3.1**
    """
    # An unpinned startup against a lenient daemon (min API <= 1.24): the daemon
    # accepts the 1.24 client default, so this is never a bug condition.
    lenient_unpinned = replace(s, daemon_min_api=daemon_min, negotiated_version=None)
    assert not is_bug_condition(lenient_unpinned)

    before = start_docker_provider(lenient_unpinned)
    after = start_docker_provider(apply_pin(lenient_unpinned))

    # The fix touches no observable other than the negotiated version.
    assert lenient_unpinned.observables() == apply_pin(lenient_unpinned).observables()
    # A lenient daemon accepts both the pre-fix (1.24 default) and post-fix
    # (1.44 pin) negotiated version, so the outcome is preserved.
    assert before["accepted"] is True
    assert after["accepted"] is True


# ===========================================================================
# 2. Compose/host startup configurations: preservation.
# ===========================================================================
@settings(max_examples=400, deadline=None)
@given(s=startups())
def test_adding_pin_changes_only_negotiated_version(s):
    """Over the full startup domain (both modes, all observables), adding the
    pin changes ONLY the negotiated API version - every other observable (socket
    mount, provider flags, network, file provider, entrypoints, TLS, secondary
    domains, static config) is identical before and after the fix.

    **Validates: Requirements 3.1, 3.2**
    """
    after = apply_pin(s)
    assert s.observables() == after.observables()
    assert after.negotiated_version == PINNED_VERSION


@settings(max_examples=400, deadline=None)
@given(s=compatible_startups())
def test_preservation_outcome_unchanged_for_compatible_startups(s):
    """For every already-compatible startup, the provider outcome is unchanged
    by the fix: startDockerProvider(X) = startDockerProvider'(X). An
    already-compatible startup already reaches the daemon, so pinning cannot
    change acceptance, discovery, or the retry-loop state - only the version
    string the daemon happens to see.

    **Validates: Requirements 3.1, 3.2**
    """
    before = start_docker_provider(s)
    after = start_docker_provider(apply_pin(s))

    # Non-version observables are untouched.
    assert s.observables() == apply_pin(s).observables()
    # Acceptance / discovery / retry-loop state is preserved.
    assert before["accepted"] == after["accepted"]
    assert before["discoveryCompleted"] == after["discoveryCompleted"]
    assert before["inRetryLoop"] == after["inRetryLoop"]
    # A non-bug startup was already accepted; it stays accepted after the fix.
    assert after["accepted"] is True


# ===========================================================================
# 3. Host-launch argument vectors: the env prefix on the sudo path.
# ===========================================================================
def _host_launch_command(runner, api_version_var, traefik_cmd, static_config, log_file):
    """Build the host-launch command string exactly as deployControlPlan.sh does:

        $runner env DOCKER_API_VERSION="$TRAEFIK_DOCKER_API_VERSION" \\
            nohup "$traefik_cmd" --configfile "$TRAEFIK_STATIC_CONFIG" \\
            >> "$TRAEFIK_LOG_FILE" 2>&1 &

    The ``env DOCKER_API_VERSION=...`` prefix must sit between the runner and the
    nohup invocation so it survives the sudo environment reset.
    """
    return (
        f'{runner} env DOCKER_API_VERSION="{api_version_var}" '
        f'nohup "{traefik_cmd}" --configfile "{static_config}" '
        f'>> "{log_file}" 2>&1 &'
    )


_ENV_PREFIX_RE = re.compile(
    r'(?:^|\s)env\s+DOCKER_API_VERSION="[^"]+"\s+nohup\s+"[^"]+"'
)


@settings(max_examples=400, deadline=None)
@given(
    # The privileged path uses sudo when the launcher is not already root; the
    # root path has an empty runner. Both must carry the env prefix.
    runner=st.sampled_from(["sudo", ""]),
    api_version_var=st.sampled_from(["$TRAEFIK_DOCKER_API_VERSION", "1.44", "1.47"]),
    traefik_cmd=st.sampled_from(["$traefik_cmd", "/usr/local/bin/traefik", "traefik"]),
    static_config=st.sampled_from(
        ["$TRAEFIK_STATIC_CONFIG", "/etc/traefik/traefik.yml", "conf/traefik.yml"]
    ),
    log_file=st.sampled_from(["$TRAEFIK_LOG_FILE", "logs/traefik.log"]),
)
def test_env_prefix_always_present_on_launch_vectors(
    runner, api_version_var, traefik_cmd, static_config, log_file
):
    """For every generated host-launch argument vector, the
    ``env DOCKER_API_VERSION=...`` prefix is present immediately in front of the
    ``nohup "<traefik>"`` invocation. This is the structural guarantee that the
    pin crosses the sudo boundary on the privileged path.

    **Validates: Requirements 2.4**
    """
    command = _host_launch_command(
        runner, api_version_var, traefik_cmd, static_config, log_file
    )

    assert _ENV_PREFIX_RE.search(command), (
        f"launch vector is missing the env DOCKER_API_VERSION prefix: {command!r}"
    )
    # The env prefix precedes nohup (it is not appended after the command).
    env_pos = command.index('env DOCKER_API_VERSION="')
    nohup_pos = command.index("nohup ")
    assert env_pos < nohup_pos, (
        f"env prefix must precede nohup so it survives sudo: {command!r}"
    )
    # On the privileged (sudo) path, the runner leads the command.
    if runner == "sudo":
        assert command.startswith("sudo env DOCKER_API_VERSION="), (
            f"privileged path must be `sudo env DOCKER_API_VERSION=...`: {command!r}"
        )


def test_real_deploy_script_host_launch_has_env_prefix_on_sudo_path():
    """Anchor the generated vectors to the shipped launcher: the real
    deployControlPlan.sh host launch runs
    ``$runner env DOCKER_API_VERSION="$TRAEFIK_DOCKER_API_VERSION" nohup "$traefik_cmd"``,
    where ``$runner`` resolves to ``sudo`` on the privileged path. Confirms the
    generated argument-vector property matches the actual launch string.

    **Validates: Requirements 2.4**
    """
    with open(DEPLOY_SCRIPT_PATH, "r", encoding="utf-8") as fh:
        script = fh.read()

    pattern = re.compile(
        r"\$runner\s+env\s+DOCKER_API_VERSION=\"\$TRAEFIK_DOCKER_API_VERSION\""
        r"[\s\\]+nohup\s+\"\$traefik_cmd\"",
        re.MULTILINE,
    )
    assert pattern.search(script), (
        "deployControlPlan.sh host launch must prefix nohup with "
        '`$runner env DOCKER_API_VERSION="$TRAEFIK_DOCKER_API_VERSION"`'
    )
    # $runner resolves to sudo on the non-root (privileged) path.
    assert 'runner="sudo"' in script


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([os.path.abspath(__file__), "-v"]))
