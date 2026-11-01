#!/usr/bin/env python3
"""Property test for the SSH local short-circuit and tuple contract.

Feature: phase4-runtime-execution-hardening, Property 8.

Property 8: Local short-circuit and tuple contract preserved.
  * WHEN the target is the local host (``is_local_server`` is True), the command
    runs LOCALLY — SSH_Utils never spawns the ``ssh`` binary; the first argv
    token handed to ``subprocess.run`` is the command/shell, never ``ssh``
    (Requirement 2.10).
  * BOTH the local and the remote paths return a ``(success, stdout, stderr)``
    3-tuple whose element types are ``(bool, str, str)`` (Requirements 2.11,
    6.4).

Validates: Requirements 2.10, 2.11, 6.4

The test injects a fake ``subprocess.run`` that records every invocation and
returns a scripted ``CompletedProcess`` — no real process, no live SSH, and no
network is ever touched. ``is_local_server`` is patched per-example so the
local/remote branch is the single variable under test, and the execution policy
is stripped of real sleeping so the remote retry path never blocks.

Both transports are exercised:
  * ``ssh_execute``       — the legacy shell-string API (R2.10 local branch runs
    ``subprocess.run(command, shell=True)``);
  * ``ssh_execute_argv``  — the argv API (R2.10 local branch runs
    ``subprocess.run(argv)`` with no ``shell=True``).

Run directly:
    python3 tests/test_ssh_utils_local_shortcircuit_tuple.py
Or via pytest:
    pytest tests/test_ssh_utils_local_shortcircuit_tuple.py
"""
import os
import subprocess
import sys
from unittest import mock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src import ssh_utils  # noqa: E402


# --------------------------------------------------------------------------- #
# Fakes / helpers
# --------------------------------------------------------------------------- #
class _FakeRunner:
    """A fake ``subprocess.run`` recording every call and scripting its result.

    Mirrors the subset of ``subprocess.run`` that ``ssh_utils`` relies on:
    positional ``args`` (argv list or shell string), the ``shell`` keyword, and
    a ``CompletedProcess`` carrying ``returncode``/``stdout``/``stderr``.
    """

    def __init__(self, returncode, stdout, stderr):
        self._returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self.calls = []  # list of (args, shell)

    def __call__(self, args, *_a, **kwargs):
        self.calls.append((args, kwargs.get("shell", False)))
        return subprocess.CompletedProcess(
            args=args,
            returncode=self._returncode,
            stdout=self._stdout,
            stderr=self._stderr,
        )

    @property
    def last_args(self):
        return self.calls[-1][0]

    @property
    def last_shell(self):
        return self.calls[-1][1]


def _assert_tuple_contract(result):
    """Assert ``result`` is a ``(bool, str, str)`` 3-tuple (R2.11, R6.4)."""
    assert isinstance(result, tuple), f"expected a tuple, got {type(result)!r}"
    assert len(result) == 3, f"expected a 3-tuple, got length {len(result)}"
    success, stdout, stderr = result
    assert isinstance(success, bool), f"success must be bool, got {type(success)!r}"
    assert isinstance(stdout, str), f"stdout must be str, got {type(stdout)!r}"
    assert isinstance(stderr, str), f"stderr must be str, got {type(stderr)!r}"


# Non-local IPs used for the remote branch. ``is_local_server`` is patched, so
# the value only needs to be a plausible address string.
_remote_ips = st.sampled_from(["10.0.0.5", "192.168.1.50", "172.16.0.9", "203.0.113.7"])
_local_ips = st.sampled_from(["127.0.0.1", "::1", "localhost", "10.0.0.5"])

# Arbitrary shell-string commands and argv lists.
_commands = st.text(
    alphabet=st.characters(blacklist_categories=("Cs", "Cc")),
    min_size=1,
    max_size=40,
)
_argvs = st.lists(
    st.text(
        alphabet=st.characters(blacklist_categories=("Cs", "Cc")),
        min_size=1,
        max_size=20,
    ),
    min_size=1,
    max_size=6,
)
_returncodes = st.sampled_from([0, 1, 2, 125, 127, 255])
_streams = st.text(
    alphabet=st.characters(blacklist_categories=("Cs", "Cc")),
    max_size=40,
)


# --------------------------------------------------------------------------- #
# Property 8 — ssh_execute (shell-string transport)
# --------------------------------------------------------------------------- #
@given(
    server_ip=_local_ips,
    command=_commands,
    returncode=_returncodes,
    stdout=_streams,
    stderr=_streams,
)
@settings(max_examples=150, deadline=None)
def test_ssh_execute_local_runs_locally_and_returns_tuple(
    server_ip, command, returncode, stdout, stderr
):
    """Feature: phase4-runtime-execution-hardening, Property 8.

    Validates: Requirements 2.10, 2.11, 6.4

    A local target short-circuits ``ssh_execute`` to a local shell: the ``ssh``
    binary is never spawned, ``shell=True`` is used, and the result honors the
    ``(bool, str, str)`` tuple contract.
    """
    runner = _FakeRunner(returncode, stdout, stderr)
    with mock.patch.object(ssh_utils, "is_local_server", return_value=True), \
            mock.patch.object(ssh_utils.subprocess, "run", runner):
        result = ssh_utils.ssh_execute(server_ip, command, timeout=30)

    _assert_tuple_contract(result)
    # Ran locally: exactly one subprocess call, via the shell, and NOT ssh.
    assert len(runner.calls) == 1
    assert runner.last_shell is True
    assert runner.last_args == command
    assert "ssh" not in str(runner.last_args).split(" ")[:1], (
        "local short-circuit must not invoke the ssh binary"
    )
    # success tracks the exit code.
    assert result[0] is (returncode == 0)


@given(
    server_ip=_remote_ips,
    command=_commands,
    returncode=_returncodes,
    stdout=_streams,
    stderr=_streams,
)
@settings(max_examples=150, deadline=None)
def test_ssh_execute_remote_returns_tuple(
    server_ip, command, returncode, stdout, stderr
):
    """Feature: phase4-runtime-execution-hardening, Property 8.

    Validates: Requirements 2.11, 6.4

    A remote target drives the ``ssh`` binary but still honors the
    ``(bool, str, str)`` tuple contract. The first argv token is ``ssh``.
    """
    runner = _FakeRunner(returncode, stdout, stderr)
    with mock.patch.object(ssh_utils, "is_local_server", return_value=False), \
            mock.patch.object(ssh_utils.subprocess, "run", runner), \
            mock.patch("src.execution_policy._time_mod.sleep", lambda *_a, **_k: None):
        result = ssh_utils.ssh_execute(server_ip, command, timeout=30)

    _assert_tuple_contract(result)
    # Remote path shells out to the ssh binary (never shell=True) at least once.
    assert runner.calls, "remote path must invoke subprocess.run"
    first_argv, shell = runner.calls[0]
    assert shell is False, "remote ssh must not use shell=True"
    assert isinstance(first_argv, list) and first_argv[0] == "ssh"


# --------------------------------------------------------------------------- #
# Property 8 — ssh_execute_argv (argv transport)
# --------------------------------------------------------------------------- #
@given(
    server_ip=_local_ips,
    argv=_argvs,
    returncode=_returncodes,
    stdout=_streams,
    stderr=_streams,
)
@settings(max_examples=150, deadline=None)
def test_ssh_execute_argv_local_runs_locally_and_returns_tuple(
    server_ip, argv, returncode, stdout, stderr
):
    """Feature: phase4-runtime-execution-hardening, Property 8.

    Validates: Requirements 2.10, 2.11, 6.4

    A local target short-circuits ``ssh_execute_argv`` to a local argv run: the
    argv is executed directly (no ``shell=True``, no ``ssh`` binary) and the
    result honors the ``(bool, str, str)`` tuple contract.
    """
    runner = _FakeRunner(returncode, stdout, stderr)
    with mock.patch.object(ssh_utils, "is_local_server", return_value=True), \
            mock.patch.object(ssh_utils.subprocess, "run", runner):
        result = ssh_utils.ssh_execute_argv(server_ip, argv, timeout=30)

    _assert_tuple_contract(result)
    assert len(runner.calls) == 1
    # Local argv path: no shell, argv passed through verbatim, never ssh.
    assert runner.last_shell is False
    assert runner.last_args == argv
    assert runner.last_args[0] != "ssh", (
        "local short-circuit must not invoke the ssh binary"
    )
    assert result[0] is (returncode == 0)


@given(
    server_ip=_remote_ips,
    argv=_argvs,
    returncode=_returncodes,
    stdout=_streams,
    stderr=_streams,
)
@settings(max_examples=150, deadline=None)
def test_ssh_execute_argv_remote_returns_tuple(
    server_ip, argv, returncode, stdout, stderr
):
    """Feature: phase4-runtime-execution-hardening, Property 8.

    Validates: Requirements 2.11, 6.4

    A remote argv target drives the ``ssh`` binary (argv is quoted into the
    remote shell command) but still honors the ``(bool, str, str)`` tuple
    contract, with ``ssh`` as the first argv token.
    """
    runner = _FakeRunner(returncode, stdout, stderr)
    with mock.patch.object(ssh_utils, "is_local_server", return_value=False), \
            mock.patch.object(ssh_utils.subprocess, "run", runner), \
            mock.patch("src.execution_policy._time_mod.sleep", lambda *_a, **_k: None):
        result = ssh_utils.ssh_execute_argv(server_ip, argv, timeout=30)

    _assert_tuple_contract(result)
    assert runner.calls, "remote path must invoke subprocess.run"
    first_argv, shell = runner.calls[0]
    assert shell is False, "remote ssh must not use shell=True"
    assert isinstance(first_argv, list) and first_argv[0] == "ssh"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
