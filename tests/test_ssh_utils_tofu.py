#!/usr/bin/env python3
"""Property test for TOFU record-first / reject-changed in ``ssh_utils``.

Feature: phase4-runtime-execution-hardening, Property 7.

Property 7 (TOFU records first and rejects a changed key):
  * **First contact** — when a server's host key is not yet recorded, SSH
    (under ``StrictHostKeyChecking=accept-new``) records the key and proceeds,
    so ``ssh_execute``/``ssh_execute_argv`` return ``success=True`` with the
    command's stdout. The remote process is invoked exactly once (a success is
    never retried).
  * **Changed key** — when the server presents a key that differs from the
    recorded one, SSH prints a changed-key rejection
    (``REMOTE HOST IDENTIFICATION HAS CHANGED`` / ``Host key verification
    failed``). ``ssh_utils`` classifies this as a Deterministic_Failure and
    returns ``success=False`` with **no retry** — the remote process is invoked
    exactly once regardless of the transient-retry budget, because a key
    mismatch is a security event, not a transient network blip.

Both paths assert the constructed SSH argv carries
``StrictHostKeyChecking=accept-new`` and the managed ``known_hosts`` path (never
``/dev/null``) and keeps ``BatchMode=yes`` — the R2.3 replacement of the old
``StrictHostKeyChecking=no`` / ``UserKnownHostsFile=/dev/null`` pair.

Validates: Requirements 2.1, 2.2, 2.3

The test injects a **fake subprocess runner** in place of ``subprocess.run`` and
forces the target non-local, so no live SSH, Docker, or PostgreSQL is touched
(R8.2, R8.5). A live-host variant that would exercise a real key mismatch is
marked as an integration test and skipped by default.

Run directly:
    python3 tests/test_ssh_utils_tofu.py
Or via pytest:
    pytest tests/test_ssh_utils_tofu.py -v
"""
import os
import sys
from collections import namedtuple
from contextlib import contextmanager
from unittest import mock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src import ssh_utils  # noqa: E402


# A minimal stand-in for ``subprocess.CompletedProcess`` carrying exactly the
# attributes ``ssh_utils`` reads (``returncode``, ``stdout``, ``stderr``).
_Completed = namedtuple("_Completed", ["returncode", "stdout", "stderr"])


class _FakeRunner:
    """A fake ``subprocess.run`` that scripts a fixed result and counts calls.

    Each invocation records the ``argv`` it was handed (the first positional
    argument, exactly as ``ssh_utils`` passes it) so the test can assert on the
    constructed SSH options, and returns the scripted ``CompletedProcess``.
    """

    def __init__(self, returncode, stdout, stderr):
        self._result = _Completed(returncode, stdout, stderr)
        self.calls = []

    def __call__(self, argv, *args, **kwargs):
        self.calls.append(list(argv))
        return self._result


# Stderr messages a real OpenSSH client prints when the recorded key no longer
# matches the key the server presents. Matched case-insensitively by
# ``ssh_utils._stderr_is_host_key_changed``.
_CHANGED_KEY_STDERRS = [
    "@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@\n"
    "@    WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!     @\n"
    "Host key verification failed.",
    "Host key verification failed.",
    "REMOTE HOST IDENTIFICATION HAS CHANGED",
]


@contextmanager
def _patched_ssh(runner, max_attempts=None):
    """Patch ``ssh_utils`` for a hermetic SSH run (no live SSH / host resolution).

    Replaces ``subprocess.run`` with the fake ``runner``, forces the remote
    branch (``is_local_server`` -> False), and optionally overrides the
    transient-retry budget. Used as a context manager so each Hypothesis example
    gets a fresh patch (``monkeypatch`` cannot be reset per generated input).
    """
    patches = [
        mock.patch.object(ssh_utils.subprocess, "run", runner),
        mock.patch.object(ssh_utils, "is_local_server", lambda _ip: False),
        # Keep the test hermetic: the real resolver reads deploy.ini / the DB
        # pool, which is both unavailable in the unit run and slow on first
        # call. A fixed target keeps the SSH-argv assertions deterministic.
        mock.patch.object(
            ssh_utils, "_resolve_ssh_target", lambda ip: f"ubuntu@{ip}"
        ),
    ]
    if max_attempts is not None:
        patches.append(mock.patch.object(ssh_utils, "_SSH_MAX_ATTEMPTS", max_attempts))
    for p in patches:
        p.start()
    try:
        yield
    finally:
        for p in reversed(patches):
            p.stop()


def _non_local_ip():
    """Return an IP strategy that never matches the local-host short-circuit.

    Documentation-range addresses (RFC 5737 ``203.0.113.0/24``) are guaranteed
    not to be this host, so ``is_local_server`` is always False and the remote
    SSH branch is always taken.
    """
    return st.integers(min_value=1, max_value=254).map(lambda n: f"203.0.113.{n}")


def _assert_hardened_argv(argv):
    """Assert a constructed SSH argv uses the hardened TOFU options (R2.3)."""
    joined = " ".join(argv)
    assert "StrictHostKeyChecking=accept-new" in argv, argv
    # The managed known_hosts file is used, never the old /dev/null sink.
    khp = ssh_utils.managed_known_hosts_path()
    assert f"UserKnownHostsFile={khp}" in argv, argv
    assert "UserKnownHostsFile=/dev/null" not in joined, argv
    assert "StrictHostKeyChecking=no" not in joined, argv
    assert "BatchMode=yes" in argv, argv


@given(
    server_ip=_non_local_ip(),
    stdout=st.text(max_size=64),
    command=st.text(
        alphabet="abcdefghijklmnopqrstuvwxyz -_/.", min_size=1, max_size=40
    ),
)
@settings(max_examples=150, deadline=None)
def test_first_contact_records_and_proceeds(server_ip, stdout, command):
    """First contact (no recorded key) records the key and proceeds (R2.1).

    Feature: phase4-runtime-execution-hardening, Property 7.
    Validates: Requirements 2.1, 2.3

    ``StrictHostKeyChecking=accept-new`` records an unseen key and lets the
    connection through, so a returncode-0 remote command yields
    ``success=True`` with its stdout, invoked exactly once (success is never
    retried). The constructed argv carries the hardened TOFU options.
    """
    runner = _FakeRunner(returncode=0, stdout=stdout, stderr="")
    with _patched_ssh(runner):
        success, out, err = ssh_utils.ssh_execute(server_ip, command, timeout=30)

    assert success is True
    assert out == stdout
    assert len(runner.calls) == 1, "a successful first contact is not retried"
    argv = runner.calls[0]
    assert argv[0] == "ssh"
    _assert_hardened_argv(argv)


@given(
    server_ip=_non_local_ip(),
    changed_stderr=st.sampled_from(_CHANGED_KEY_STDERRS),
    max_attempts=st.integers(min_value=1, max_value=5),
    command=st.text(
        alphabet="abcdefghijklmnopqrstuvwxyz -_/.", min_size=1, max_size=40
    ),
)
@settings(max_examples=150, deadline=None)
def test_changed_key_is_deterministic_failure_no_retry(
    server_ip, changed_stderr, max_attempts, command
):
    """A changed host key => deterministic failure, no retry (R2.2).

    Feature: phase4-runtime-execution-hardening, Property 7.
    Validates: Requirements 2.2, 2.3

    When SSH rejects the connection because the presented key differs from the
    recorded one, ``ssh_utils`` returns ``success=False`` and invokes the remote
    process **exactly once** — a key mismatch is a Deterministic_Failure and is
    never retried, no matter how large the transient-retry budget is.
    """
    runner = _FakeRunner(returncode=255, stdout="", stderr=changed_stderr)
    # Even with a generous retry budget, a changed key must not be retried.
    with _patched_ssh(runner, max_attempts=max_attempts):
        success, out, err = ssh_utils.ssh_execute(server_ip, command, timeout=30)

    assert success is False
    assert len(runner.calls) == 1, (
        "a changed-key rejection is deterministic and must not be retried"
    )
    # The rejection reason is surfaced in stderr.
    assert err
    argv = runner.calls[0]
    _assert_hardened_argv(argv)


@given(
    server_ip=_non_local_ip(),
    stdout=st.text(max_size=64),
)
@settings(max_examples=150, deadline=None)
def test_argv_transport_first_contact_and_hardened_options(server_ip, stdout):
    """The argv transport proceeds on first contact with hardened options.

    Feature: phase4-runtime-execution-hardening, Property 7.
    Validates: Requirements 2.1, 2.3

    ``ssh_execute_argv`` builds the same hardened SSH argv (TOFU + managed
    known_hosts, never ``/dev/null``) and returns ``success=True`` on a
    returncode-0 first contact, invoked exactly once.
    """
    runner = _FakeRunner(returncode=0, stdout=stdout, stderr="")
    with _patched_ssh(runner):
        success, out, err = ssh_utils.ssh_execute_argv(
            server_ip, ["docker", "ps", "-a"], timeout=30
        )

    assert success is True
    assert out == stdout
    assert len(runner.calls) == 1
    argv = runner.calls[0]
    assert argv[0] == "ssh"
    _assert_hardened_argv(argv)


@pytest.mark.integration
@pytest.mark.skip(reason="integration: requires a real SSH host with a changed key")
def test_live_host_changed_key_rejected():
    """Live-host variant of Property 7 (integration only).

    Feature: phase4-runtime-execution-hardening, Property 7.
    Validates: Requirements 2.1, 2.2, 2.3

    Against a real server whose recorded key has been rotated, ``ssh_execute``
    must return ``success=False`` without retrying. Requires live SSH and a
    pre-seeded managed known_hosts file, so it is marked as an integration test
    (R8.5) and skipped in the unit run.
    """
    raise AssertionError("integration-only; not executed in the unit run")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
