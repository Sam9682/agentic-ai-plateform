#!/usr/bin/env python3
"""Property test: SSH log output never leaks secret values (Task 4.4).

Feature: phase4-runtime-execution-hardening, Property 18.

Property 18 — New logs exclude secret values: for any command that embeds a
secret as a ``KEY=VALUE`` token whose key hints at a credential (``-e
PASSWORD=...``, ``TOKEN=...``, ``API_KEY=...``, a proxy URL carrying embedded
credentials, etc.), every log line emitted by :mod:`src.ssh_utils` while
dispatching that command contains NO secret value. The ``_redact(cmd)`` helper
is the single choke point that masks the value to ``***`` before it reaches the
logger, and both the shell-string (:func:`ssh_execute`) and argv
(:func:`ssh_execute_argv`) transports — on their local short-circuit and their
remote SSH path — route their command text through it.

Validates:
* Requirements 2.12 — SSH_Utils SHALL exclude secret values from log output.
* Requirements 5.8  — (same hygiene contract applied to Phase 4 connector logs;
  the shared ``_redact`` helper under test here is the mechanism reused there).
* Requirements 8.1  — the System SHALL exclude secret values from ALL log output
  introduced in Phase 4.

No live SSH / Docker / PostgreSQL: the remote path's ``subprocess.run`` is faked
so the SSH binary is never invoked, and the local short-circuit is driven by
forcing ``is_local_server``. Every log record emitted by the module is captured
with a self-managed in-memory handler (a context manager rather than the
function-scoped ``caplog`` fixture, which Hypothesis does not reset between
generated examples) and scanned for the secret value.

Run directly:
    python3 tests/test_phase4_ssh_secret_hygiene.py
Or via pytest:
    pytest tests/test_phase4_ssh_secret_hygiene.py
"""
import logging
import os
import sys
from contextlib import contextmanager
from unittest import mock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("FLASK_ENV", "development")

from src import ssh_utils  # noqa: E402


# --------------------------------------------------------------------------- #
# Strategies
# --------------------------------------------------------------------------- #
# Keys whose name hints at a credential; ``_redact`` masks the value of any
# ``KEY=VALUE`` token whose key matches one of these hints (case-insensitively,
# including as a substring of a larger key like ``DB_PASSWORD`` or ``-e
# API_KEY``). These mirror ``ssh_utils._SECRET_KEY_HINTS``.
_SECRET_KEYS = st.sampled_from(
    [
        "PASSWORD",
        "PASSWD",
        "DB_PASSWORD",
        "SECRET",
        "CLIENT_SECRET",
        "TOKEN",
        "ACCESS_TOKEN",
        "APIKEY",
        "API_KEY",
        "SSH_KEY",
    ]
)

# A secret value with no whitespace (so it is a single ``\S+`` token that
# ``_redact`` masks as a whole) and no ``=`` (so it cannot be mistaken for a
# second KEY=VALUE boundary). Kept long enough that an accidental substring
# match against the key name is implausible, and filtered to be non-empty.
_secret_value = st.text(
    alphabet=st.characters(
        min_codepoint=33,
        max_codepoint=126,
        blacklist_characters="=",  # keep it a single KEY=VALUE token
    ),
    min_size=6,
    max_size=40,
).filter(lambda v: v.strip() == v and len(v) >= 6)

# A proxy URL embedding credentials. ``_redact`` masks the ``user:password@``
# userinfo component of any URL, so neither the user nor the password reaches
# the log even when the surrounding env key (e.g. ``HTTPS_PROXY``) is not itself
# a credential hint. The strategy yields the full URL plus its credential parts
# so the test can assert the sensitive components specifically.
_proxy_user = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=4, max_size=12
)
_proxy_pw = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
    min_size=8,
    max_size=24,
)


@st.composite
def _proxy_url(draw):
    """Return ``(url, user, password)`` for a credential-bearing proxy URL."""
    scheme = draw(st.sampled_from(["http", "https", "socks5"]))
    user = draw(_proxy_user)
    pw = draw(_proxy_pw)
    host = draw(st.sampled_from(["proxy.internal", "10.0.0.5", "gateway.corp"]))
    port = draw(st.integers(min_value=1, max_value=65535))
    return f"{scheme}://{user}:{pw}@{host}:{port}", user, pw

# Server IPs for the remote path (never local: forced below) and the local
# short-circuit.
_remote_ip = st.sampled_from(["203.0.113.7", "198.51.100.42", "192.0.2.9"])


class _ListHandler(logging.Handler):
    """A minimal handler that records every emitted record for inspection."""

    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)


@contextmanager
def _capture_logs():
    """Capture all records emitted on ``ssh_utils.logger`` for the block.

    Used instead of pytest's function-scoped ``caplog`` fixture because
    Hypothesis does not reset function-scoped fixtures between generated
    examples; a self-managed handler is reset per call explicitly.
    """
    handler = _ListHandler()
    logger = ssh_utils.logger
    prev_level = logger.level
    prev_propagate = logger.propagate
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    try:
        yield handler
    finally:
        logger.removeHandler(handler)
        logger.setLevel(prev_level)
        logger.propagate = prev_propagate


def _assert_no_leak(handler, secret_value):
    """Assert the secret value appears in no captured log record text.

    The assertion is meaningful only if the module actually logged something for
    this dispatch (otherwise absence would be vacuous), so we also require at
    least one emitted record.
    """
    records = list(handler.records)
    assert records, "expected at least one log record from the ssh dispatch"
    for rec in records:
        # Render the record exactly as a handler would (format args applied).
        text = rec.getMessage()
        assert secret_value not in text, (
            f"secret value leaked into log record: {text!r}"
        )


# --------------------------------------------------------------------------- #
# Property 18 — remote SSH path, shell-string transport (ssh_execute)
# --------------------------------------------------------------------------- #
@settings(max_examples=150, deadline=None)
@given(key=_SECRET_KEYS, value=_secret_value, server_ip=_remote_ip)
def test_ssh_execute_remote_never_logs_secret_value(key, value, server_ip):
    """Feature: phase4-runtime-execution-hardening, Property 18.

    ``ssh_execute`` dispatching a shell-string command carrying ``-e KEY=VALUE``
    to a remote host logs only the redacted summary — the secret VALUE never
    reaches any log record. Validates Requirements 2.12, 8.1.
    """
    command = f"docker run -e {key}={value} alpine:3.20 env"

    # Fake the remote subprocess so no real SSH runs; return a clean success.
    completed = mock.Mock(returncode=0, stdout="ok", stderr="")
    with mock.patch.object(ssh_utils, "is_local_server", return_value=False), \
            mock.patch.object(ssh_utils.subprocess, "run", return_value=completed), \
            _capture_logs() as handler:
        success, _stdout, _stderr = ssh_utils.ssh_execute(
            server_ip, command, timeout=5
        )

    assert success is True
    _assert_no_leak(handler, value)


# --------------------------------------------------------------------------- #
# Property 18 — remote SSH path, argv transport (ssh_execute_argv)
# --------------------------------------------------------------------------- #
@settings(max_examples=150, deadline=None)
@given(key=_SECRET_KEYS, value=_secret_value, server_ip=_remote_ip)
def test_ssh_execute_argv_remote_never_logs_secret_value(key, value, server_ip):
    """Feature: phase4-runtime-execution-hardening, Property 18.

    ``ssh_execute_argv`` dispatching an argv command carrying a secret env token
    to a remote host logs only the redacted summary. Validates Requirements
    2.12, 8.1.
    """
    argv = ["docker", "run", "-e", f"{key}={value}", "alpine:3.20", "env"]

    completed = mock.Mock(returncode=0, stdout="ok", stderr="")
    with mock.patch.object(ssh_utils, "is_local_server", return_value=False), \
            mock.patch.object(ssh_utils.subprocess, "run", return_value=completed), \
            _capture_logs() as handler:
        success, _stdout, _stderr = ssh_utils.ssh_execute_argv(
            server_ip, argv, timeout=5
        )

    assert success is True
    _assert_no_leak(handler, value)


# --------------------------------------------------------------------------- #
# Property 18 — proxy URL with embedded credentials never leaks
# --------------------------------------------------------------------------- #
@settings(max_examples=150, deadline=None)
@given(proxy=_proxy_url(), server_ip=_remote_ip)
def test_ssh_execute_never_logs_proxy_credentials(proxy, server_ip):
    """Feature: phase4-runtime-execution-hardening, Property 18.

    A proxy URL carrying ``user:password@host`` credentials, passed under a
    non-credential-hint env key (``HTTPS_PROXY``), has its userinfo masked: the
    embedded user and password never reach any log record even though the key
    name does not hint at a secret. Validates Requirements 2.12, 5.8, 8.1.
    """
    url, user, password = proxy
    command = f"docker run -e HTTPS_PROXY={url} alpine:3.20 env"

    completed = mock.Mock(returncode=0, stdout="ok", stderr="")
    with mock.patch.object(ssh_utils, "is_local_server", return_value=False), \
            mock.patch.object(ssh_utils.subprocess, "run", return_value=completed), \
            _capture_logs() as handler:
        ssh_utils.ssh_execute(server_ip, command, timeout=5)

    # The embedded credentials (user and password) must be absent from the log.
    # The password is the robustly-unique secret (>=8 mixed chars); the user is
    # also checked. The full `user:password@` userinfo is replaced by `***:***@`.
    _assert_no_leak(handler, password)
    _assert_no_leak(handler, f"{user}:{password}")


# --------------------------------------------------------------------------- #
# Property 18 — local short-circuit path (no SSH) also redacts
# --------------------------------------------------------------------------- #
@settings(max_examples=150, deadline=None)
@given(key=_SECRET_KEYS, value=_secret_value)
def test_local_short_circuit_never_logs_secret_value(key, value):
    """Feature: phase4-runtime-execution-hardening, Property 18.

    The ``is_local_server`` short-circuit logs its command through ``_redact``
    too, so a local dispatch never leaks the secret value either (both
    transports). Validates Requirements 2.12, 8.1.
    """
    command = f"docker run -e {key}={value} alpine:3.20 env"
    argv = ["docker", "run", "-e", f"{key}={value}", "alpine:3.20", "env"]

    completed = mock.Mock(returncode=0, stdout="ok", stderr="")
    with mock.patch.object(ssh_utils, "is_local_server", return_value=True), \
            mock.patch.object(ssh_utils.subprocess, "run", return_value=completed):
        # Shell-string local path.
        with _capture_logs() as handler:
            ssh_utils.ssh_execute("127.0.0.1", command, timeout=5)
        _assert_no_leak(handler, value)

        # Argv local path.
        with _capture_logs() as handler:
            ssh_utils.ssh_execute_argv("127.0.0.1", argv, timeout=5)
        _assert_no_leak(handler, value)


# --------------------------------------------------------------------------- #
# Property 18 — failure path (non-zero exit) still redacts before logging
# --------------------------------------------------------------------------- #
@settings(max_examples=150, deadline=None)
@given(key=_SECRET_KEYS, value=_secret_value, server_ip=_remote_ip)
def test_remote_failure_path_never_logs_secret_value(key, value, server_ip):
    """Feature: phase4-runtime-execution-hardening, Property 18.

    When the remote command fails (non-zero exit), the dispatch still only logs
    the redacted summary of the command; the secret value does not leak via the
    "executing" line. Validates Requirements 2.12, 8.1.
    """
    command = f"docker run -e {key}={value} alpine:3.20 env"

    # Deterministic failure (not a transient marker) -> single attempt, fails.
    completed = mock.Mock(returncode=1, stdout="", stderr="no such image")
    with mock.patch.object(ssh_utils, "is_local_server", return_value=False), \
            mock.patch.object(ssh_utils.subprocess, "run", return_value=completed), \
            _capture_logs() as handler:
        success, _stdout, _stderr = ssh_utils.ssh_execute(
            server_ip, command, timeout=5
        )

    assert success is False
    _assert_no_leak(handler, value)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
