#!/usr/bin/env python3
"""Unit tests for orchestrator start/stop hardening and the crash-loop cap.

Feature: phase4-runtime-execution-hardening, Task 5.1.

Covers the behavior introduced by "Harden start/stop subprocess paths and
crash-loop cap":

* ``should_attempt_start(restart_attempts, cap)`` is a pure predicate that
  returns ``restart_attempts < cap`` (Requirements 3.3, 3.9).
* ``_run_docker_argv`` dispatches Docker commands on the instance's selected
  server via ``ssh_execute_argv`` with an explicit timeout
  (Requirements 3.1, 3.7) and routes the call through the shared execution
  policy so a transient failure retries with bounded backoff while a
  deterministic failure fails fast with no retry (Requirement 3.2).
* ``_run_docker_argv`` never shells out to a local ``docker`` directly and never
  touches nginx (Requirement 3.8).

All collaborators (``ssh_execute_argv``) are injected via ``mock.patch`` so the
tests run with no live Docker, SSH, or PostgreSQL (Requirement 3.9 / 8.2).

Run directly:
    python3 tests/test_orchestrator_start_stop_hardening.py
Or via pytest:
    pytest tests/test_orchestrator_start_stop_hardening.py
"""
import os
import sys
from unittest import mock

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("FLASK_ENV", "development")

from src import orchestrator as orch_mod  # noqa: E402
from src.orchestrator import (  # noqa: E402
    CRASH_LOOP_CAP,
    DOCKER_SUBPROCESS_TIMEOUT,
    LightOrchestrator,
    should_attempt_start,
)


# --------------------------------------------------------------------------- #
# Pure crash-loop cap predicate (R3.3, R3.9)
# --------------------------------------------------------------------------- #
def test_should_attempt_start_is_strict_less_than_cap():
    """``should_attempt_start`` returns ``restart_attempts < cap`` exactly."""
    cap = 5
    assert should_attempt_start(0, cap) is True
    assert should_attempt_start(4, cap) is True
    # At the cap we must stop attempting (R3.3).
    assert should_attempt_start(5, cap) is False
    assert should_attempt_start(6, cap) is False


def test_should_attempt_start_zero_cap_never_attempts():
    """A cap of 0 means no start is ever attempted."""
    assert should_attempt_start(0, 0) is False


# --------------------------------------------------------------------------- #
# Per-server dispatch + policy routing in _run_docker_argv (R3.1, R3.2, R3.7)
# --------------------------------------------------------------------------- #
def test_run_docker_argv_dispatches_via_ssh_with_timeout():
    """A successful docker run is dispatched to the server with a timeout.

    Asserts the argv and ``server_ip`` are forwarded to ``ssh_execute_argv``
    with the explicit container-sized timeout (R3.1, R3.7) and the trimmed
    stdout (the container id) is returned.
    """
    orchestrator = LightOrchestrator()
    argv = ["docker", "run", "-d", "--name", "svc-replica-1", "img@sha256:deadbeef"]

    with mock.patch.object(
        orch_mod, "ssh_execute_argv",
        return_value=(True, "  container-abc123\n", ""),
    ) as ssh_spy:
        result = orchestrator._run_docker_argv("10.0.0.5", argv, action="start x")

    assert result == "container-abc123"
    ssh_spy.assert_called_once_with(
        "10.0.0.5", argv, timeout=DOCKER_SUBPROCESS_TIMEOUT
    )


def test_run_docker_argv_retries_transient_then_succeeds():
    """A transient SSH/Docker failure is retried through the policy (R3.2).

    First dispatch returns a transient-looking failure (connection reset);
    the second succeeds. The policy should retry and ultimately return the
    container id. ``sleep`` is patched out so no real backoff delay is incurred.
    """
    orchestrator = LightOrchestrator()
    argv = ["docker", "run", "-d", "img"]

    side_effects = [
        (False, "", "ssh: connect to host 10.0.0.5 port 22: Connection reset by peer"),
        (True, "container-xyz\n", ""),
    ]

    with mock.patch.object(
        orch_mod, "ssh_execute_argv", side_effect=side_effects
    ) as ssh_spy, mock.patch.object(orch_mod.time, "sleep", lambda *_a, **_k: None), \
            mock.patch("src.execution_policy._time_mod.sleep", lambda *_a, **_k: None):
        result = orchestrator._run_docker_argv("10.0.0.5", argv, action="start x")

    assert result == "container-xyz"
    assert ssh_spy.call_count == 2


def test_run_docker_argv_deterministic_failure_fails_fast():
    """A deterministic docker failure is terminal with no retry (R3.2).

    A non-zero docker exit whose stderr is not transient (e.g. an image/name
    conflict) must fail after exactly one attempt and raise.
    """
    orchestrator = LightOrchestrator()
    argv = ["docker", "run", "-d", "img"]

    with mock.patch.object(
        orch_mod, "ssh_execute_argv",
        return_value=(False, "", "Conflict. The container name is already in use"),
    ) as ssh_spy:
        try:
            orchestrator._run_docker_argv("10.0.0.5", argv, action="start x")
            raised = False
        except Exception as exc:  # noqa: BLE001 - asserting the terminal raise
            raised = True
            assert "already in use" in str(exc)

    assert raised, "expected a deterministic failure to raise"
    # No retry on a deterministic failure.
    assert ssh_spy.call_count == 1


def test_run_docker_argv_never_calls_local_docker_subprocess():
    """The hardened path uses ssh_utils, never a bare local docker subprocess.

    Guards against regressing to ``subprocess.run(['docker', ...])`` in the
    start/stop path (R3.7) and confirms no nginx is touched (R3.8).
    """
    orchestrator = LightOrchestrator()

    with mock.patch.object(
        orch_mod, "ssh_execute_argv", return_value=(True, "cid\n", "")
    ), mock.patch.object(orch_mod.subprocess, "run") as subproc_spy:
        orchestrator._run_docker_argv("10.0.0.5", ["docker", "stop", "cid"],
                                      action="stop x")

    subproc_spy.assert_not_called()


if __name__ == "__main__":
    test_should_attempt_start_is_strict_less_than_cap()
    test_should_attempt_start_zero_cap_never_attempts()
    test_run_docker_argv_dispatches_via_ssh_with_timeout()
    test_run_docker_argv_retries_transient_then_succeeds()
    test_run_docker_argv_deterministic_failure_fails_fast()
    test_run_docker_argv_never_calls_local_docker_subprocess()
    print("ok")
