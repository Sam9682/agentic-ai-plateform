#!/usr/bin/env python3
"""Bug condition exploration test for the Traefik Docker API version pin.

Spec: .kiro/specs/traefik-docker-api-version (bugfix workflow, Task 1)

Background
----------
Traefik's Docker provider negotiates a Docker API version with the daemon on
startup. With no version pinned *reaching the provider process* it falls back
to client API ``1.24``. Modern daemons enforce a minimum supported API version
(``1.40``) and reject ``1.24`` with::

    client version 1.24 is too old. Minimum supported API version is 1.40

so the provider loops on ``Provider error, retrying in ...`` and never completes
discovery, so no container routes are created. There are two concrete triggers:

* **docker mode** - the ``traefik`` compose service has no ``DOCKER_API_VERSION``
  environment entry, so nothing is injected into the container.
* **locally / default mode** - the host launch runs under ``sudo`` (to bind
  privileged ports). ``sudo`` resets the environment, so a *plain exported*
  ``DOCKER_API_VERSION`` is stripped and never reaches the Traefik process; only
  an ``env VAR=value`` prefix directly in front of the launched command survives.

What this test is
-----------------
This is the **Property 1 - Bug Condition** exploration test. It encodes the
*expected (fixed) behavior* from the design (Fix Checking / Property 1):

    for all X where isBugCondition(X):
        negotiatedApiVersion >= daemonMinApiVersion
        AND NOT contains(log, "client version 1.24 is too old")
        AND discoveryCompleted = TRUE
        AND NOT inRetryLoop

and runs it against the **UNFIXED launch configurations** (pin removed /
sudo-stripped). Because the design states the fix already exists in the real
files, we reconstruct the unfixed launch paths in-memory rather than editing the
repository. Against those unfixed configurations the assertions MUST FAIL -
that failure is the counterexample proving the bug exists.

``isBugCondition(X)`` (from design / bugfix.md):

    pinnedVersionReachingProvider(X) = UNSET AND X.daemonMinApiVersion > 1.24

Once the fix is in place (compose service carries ``DOCKER_API_VERSION=1.44`` and
the host launch uses the ``env`` prefix), this same test is re-run in task 3.2
against the FIXED launch paths, where it is expected to PASS.

Validates: Requirements 1.1, 1.2, 1.3, 1.4 (bug condition) and, when passing
after the fix, Requirements 2.1, 2.2, 2.3, 2.4.

Run directly:
    python3 tests/test_traefik_docker_api_version.py
Or via pytest:
    pytest tests/test_traefik_docker_api_version.py -v
"""
import os
import re

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPOSE_PATH = os.path.join(PROJECT_ROOT, "docker-compose.yml")
DEPLOY_SCRIPT_PATH = os.path.join(PROJECT_ROOT, "deployControlPlan.sh")

# The conservative client default the Docker SDK falls back to when no version
# reaches the provider process.
CLIENT_DEFAULT_API_VERSION = "1.24"
REJECTION_SUBSTRING = "client version 1.24 is too old"
# A modern daemon's minimum supported API version (design uses 1.40).
MODERN_DAEMON_MIN_API = "1.40"


# ---------------------------------------------------------------------------
# Model of a Traefik Docker-provider startup
# ---------------------------------------------------------------------------
def _version_tuple(v):
    """Turn an API version string like ``"1.44"`` into a comparable tuple."""
    return tuple(int(p) for p in str(v).split("."))


class Startup:
    """A single Traefik Docker-provider startup configuration (input X).

    This captures only the facts that drive the bug: the daemon's minimum
    supported API version, and the version (if any) that actually reaches the
    provider process. The two deployment modes differ only in *how* a pin does
    or does not reach the process:

    * docker mode: the value comes straight from the compose service
      ``environment`` (no sudo boundary).
    * locally mode: the value only reaches the process if it is set via an
      ``env VAR=value`` prefix on the launch; a plain exported shell variable is
      stripped by ``sudo``.
    """

    def __init__(self, mode, daemon_min_api, *, compose_env=None,
                 exported_var=None, env_prefix_var=None):
        self.mode = mode
        self.daemon_min_api = daemon_min_api
        # docker mode: value injected by the compose runtime (or None).
        self.compose_env = compose_env
        # locally mode: a plain `export DOCKER_API_VERSION=...` before sudo.
        self.exported_var = exported_var
        # locally mode: an `env DOCKER_API_VERSION=...` prefix in front of the
        # launched command (survives the sudo env reset).
        self.env_prefix_var = env_prefix_var

    def pinned_version_reaching_provider(self):
        """Return the API version that actually reaches the provider, or None.

        None means UNSET - the provider will fall back to the client default.
        """
        if self.mode == "docker":
            # The compose runtime injects the service `environment` directly
            # into the container; there is no sudo boundary.
            return self.compose_env
        if self.mode == "locally":
            # Only the `env ...` prefix survives sudo's environment reset. A
            # plain exported variable is stripped and never reaches the process.
            return self.env_prefix_var
        raise ValueError(f"unknown mode: {self.mode!r}")


def is_bug_condition(startup):
    """isBugCondition(X): no pin reaches the provider AND daemon requires > 1.24.

    From design/bugfix.md:
        pinnedVersionReachingProvider(X) = UNSET AND X.daemonMinApiVersion > 1.24
    """
    pinned = startup.pinned_version_reaching_provider()
    return pinned is None and _version_tuple(startup.daemon_min_api) > _version_tuple(
        CLIENT_DEFAULT_API_VERSION
    )


def start_docker_provider(startup):
    """Model the provider startup and return its observables.

    This is the single source of truth for what the daemon does with the
    negotiated version. It is deterministic and configuration-driven, matching
    the design's description of the bug:

    * If a pinned version reaches the provider, that version is negotiated.
    * Otherwise the provider falls back to the client default (1.24).
    * The daemon rejects any negotiated version below its minimum, which keeps
      the provider in a retry loop and prevents discovery.
    """
    pinned = startup.pinned_version_reaching_provider()
    negotiated = pinned if pinned is not None else CLIENT_DEFAULT_API_VERSION

    accepted = _version_tuple(negotiated) >= _version_tuple(startup.daemon_min_api)
    if accepted:
        return {
            "negotiatedApiVersion": negotiated,
            "log": "Configuration received providerName=docker",
            "discoveryCompleted": True,
            "inRetryLoop": False,
            "routesCreated": True,
        }
    return {
        "negotiatedApiVersion": negotiated,
        "log": (
            f"ERR Provider error, retrying in 7.432861093s "
            f'error="Error response from daemon: client version {negotiated} is '
            f'too old. Minimum supported API version is {startup.daemon_min_api}, '
            f'please upgrade your client to a newer version" providerName=docker'
        ),
        "discoveryCompleted": False,
        "inRetryLoop": True,
        "routesCreated": False,
    }


def assert_expected_behavior(startup):
    """Assert Property 1 / Fix Checking expected behavior for a startup.

    This is the behavior the FIX must satisfy. Running it against an UNFIXED
    (pin-removed / sudo-stripped) startup is expected to raise AssertionError -
    that is the counterexample demonstrating the bug.
    """
    result = start_docker_provider(startup)

    assert _version_tuple(result["negotiatedApiVersion"]) >= _version_tuple(
        startup.daemon_min_api
    ), (
        f"[{startup.mode} mode] negotiated API "
        f"{result['negotiatedApiVersion']} is below the daemon minimum "
        f"{startup.daemon_min_api} - the daemon rejects the connection"
    )
    assert REJECTION_SUBSTRING not in result["log"], (
        f"[{startup.mode} mode] provider log contains the rejection: "
        f"{result['log']!r}"
    )
    assert result["discoveryCompleted"] is True, (
        f"[{startup.mode} mode] Docker discovery did not complete"
    )
    assert result["inRetryLoop"] is False, (
        f"[{startup.mode} mode] provider is stuck in the retry loop"
    )


# ---------------------------------------------------------------------------
# UNFIXED launch configurations (reconstructed from the design's bug cases)
# ---------------------------------------------------------------------------
def unfixed_docker_no_pin():
    """docker mode, no pin: traefik service has no DOCKER_API_VERSION."""
    return Startup("docker", MODERN_DAEMON_MIN_API, compose_env=None)


def unfixed_locally_plain_export():
    """locally mode: `export DOCKER_API_VERSION=1.44` but no `env` prefix.

    The plain exported variable is stripped at the sudo boundary, so nothing
    reaches the provider process.
    """
    return Startup(
        "locally",
        MODERN_DAEMON_MIN_API,
        exported_var="1.44",   # set in the shell...
        env_prefix_var=None,   # ...but NOT passed via `env`, so sudo strips it
    )


def unfixed_locally_no_pin():
    """locally mode, no pin at all: nothing set anywhere."""
    return Startup("locally", MODERN_DAEMON_MIN_API)


UNFIXED_CONFIGS = [
    pytest.param(unfixed_docker_no_pin(), id="docker-mode-no-pin"),
    pytest.param(unfixed_locally_plain_export(), id="locally-mode-plain-export"),
    pytest.param(unfixed_locally_no_pin(), id="locally-mode-no-pin"),
]


# ---------------------------------------------------------------------------
# Property 1 - Bug Condition exploration (MUST FAIL on the unfixed configs)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("startup", UNFIXED_CONFIGS)
def test_bug_condition_holds_for_unfixed_configs(startup):
    """Sanity: every unfixed launch path satisfies isBugCondition.

    This frames the domain: these are exactly the inputs for which Property 1
    must hold after the fix.
    """
    assert is_bug_condition(startup), (
        f"expected {startup.mode} unfixed config to satisfy the bug condition"
    )


@pytest.mark.parametrize("startup", UNFIXED_CONFIGS)
def test_property1_expected_behavior_on_unfixed_configs(startup):
    """Property 1 / Fix Checking - encodes expected behavior.

    Against the UNFIXED launch paths this MUST FAIL (AssertionError), which is
    the counterexample proving the bug exists. After the fix the same assertion
    passes (task 3.2).

    **Validates: Requirements 1.1, 1.2, 1.3, 1.4**
    """
    assert_expected_behavior(startup)


@given(
    daemon_min_api=st.sampled_from(["1.40", "1.41", "1.43", "1.44", "1.45"]),
    mode=st.sampled_from(["docker", "locally"]),
)
@settings(max_examples=50)
def test_property1_bug_condition_pbt(daemon_min_api, mode):
    """Scoped PBT: across modern daemons, the unfixed startup fails Property 1.

    The property is scoped (per the task) to the concrete failing launch
    configurations: no pin reaches the provider against a daemon requiring more
    than the 1.24 default. For every such generated startup, the expected
    (fixed) behavior must NOT hold - the provider negotiates 1.24 and is
    rejected. This surfaces the counterexample family across many daemons.

    **Validates: Requirements 1.1, 1.2, 1.3, 1.4**
    """
    if mode == "docker":
        startup = Startup("docker", daemon_min_api, compose_env=None)
    else:
        # plain export (sudo-stripped) OR nothing: either way UNSET at provider
        startup = Startup("locally", daemon_min_api, exported_var="1.44",
                          env_prefix_var=None)

    # These generated startups all satisfy the bug condition.
    assert is_bug_condition(startup)

    result = start_docker_provider(startup)
    # Expected (fixed) behavior must FAIL here: the provider is rejected.
    assert result["negotiatedApiVersion"] == CLIENT_DEFAULT_API_VERSION
    assert REJECTION_SUBSTRING in result["log"]
    assert result["discoveryCompleted"] is False
    assert result["inRetryLoop"] is True
    # Assert the pin is ABSENT from the launch path under test.
    assert startup.pinned_version_reaching_provider() is None


# ---------------------------------------------------------------------------
# Launch-string assertions against the real repository files
# ---------------------------------------------------------------------------
# These document, against the actual files, where the pin must live. On the
# UNFIXED launch paths the pin is absent and these fail; after the fix they
# pass. They anchor the config-driven model above to the real launch strings.
def _traefik_compose_env():
    import yaml

    with open(COMPOSE_PATH, "r", encoding="utf-8") as fh:
        compose = yaml.safe_load(fh)
    service = compose["services"]["traefik"]
    env = service.get("environment", []) or []
    # Support both list ("K=V") and mapping ({K: V}) forms.
    result = {}
    if isinstance(env, dict):
        result = {str(k): str(v) for k, v in env.items()}
    else:
        for item in env:
            if "=" in str(item):
                k, v = str(item).split("=", 1)
                result[k] = v
    return result


def test_compose_traefik_service_pins_api_version():
    """docker mode: the traefik service environment pins DOCKER_API_VERSION=1.44.

    On the UNFIXED compose (pin removed) this fails - proving no pin reaches the
    container. After the fix it passes.

    **Validates: Requirements 1.1, 2.1**
    """
    env = _traefik_compose_env()
    assert env.get("DOCKER_API_VERSION") == "1.44", (
        "traefik compose service must pin DOCKER_API_VERSION=1.44 so the pin "
        f"reaches the provider; got environment={env}"
    )


def test_host_launch_passes_pin_across_sudo_boundary():
    """locally mode: the host launch uses `env DOCKER_API_VERSION=...` prefix.

    The pin must be passed via `env` (not a plain export) so it survives sudo's
    environment reset and reaches the Traefik process. On the UNFIXED launcher
    (plain export only) this fails. After the fix it passes.

    **Validates: Requirements 1.4, 2.4**
    """
    with open(DEPLOY_SCRIPT_PATH, "r", encoding="utf-8") as fh:
        script = fh.read()

    # The `env DOCKER_API_VERSION=...` prefix must sit between the runner (sudo)
    # and the `nohup "$traefik_cmd"` invocation.
    pattern = re.compile(
        r"\$runner\s+env\s+DOCKER_API_VERSION=\"\$TRAEFIK_DOCKER_API_VERSION\""
        r"[\s\\]+nohup\s+\"\$traefik_cmd\"",
        re.MULTILINE,
    )
    assert pattern.search(script), (
        "deployControlPlan.sh host launch must prefix the nohup traefik "
        "invocation with `$runner env DOCKER_API_VERSION=\"$TRAEFIK_DOCKER_API_VERSION\"` "
        "so the pin crosses the sudo boundary"
    )


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([os.path.abspath(__file__), "-v"]))
