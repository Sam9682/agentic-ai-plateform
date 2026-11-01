"""Shared SSH execution helper for running commands on managed servers.

Several features (MIG GPU management, Runtime Security container discovery, the
ARO/serverless connectors and the orchestrator's per-server container
operations) need to run commands on remote servers listed in the ``servers``
table. This module provides a single implementation so the behavior (host-key
handling, timeout, connection reuse, return shape) stays consistent across
features.

Phase 4 hardening (R2):

* **TOFU host-key verification** over a managed ``known_hosts`` file
  (``StrictHostKeyChecking=accept-new`` + ``UserKnownHostsFile=<managed>``)
  replaces the previous ``StrictHostKeyChecking=no`` /
  ``UserKnownHostsFile=/dev/null`` pair (R2.1, R2.2, R2.3). An unseen host's key
  is recorded and trusted on first contact; a *changed* key is rejected as a
  deterministic failure and never retried.
* **Managed known_hosts path** read from configuration
  (``ssh_managed_known_hosts``), defaulting to ``<repo>/conf/ssh/known_hosts``;
  its parent directory is created before SSH is invoked (R2.4, R2.5).
* **Container-sized connect timeout** (``SSH_CONTAINER_TIMEOUT_DEFAULT = 120``),
  larger than the former 30-second default, with a bounded
  ``ConnectTimeout`` so a dead host fails fast (R2.6).
* **Connection reuse** via ``ControlMaster=auto`` / ``ControlPersist=60s`` over
  a short multiplexing socket (R2.7).
* **Bounded transient retry** through :func:`src.execution_policy.run_with_policy`
  with the shared :func:`src.execution_policy.ssh_is_transient` classifier
  (R2.8).
* **Argv transport variant** :func:`ssh_execute_argv` that preserves safe
  quoting (R2.9) while the legacy shell-string :func:`ssh_execute` is retained
  unchanged for back-compat.
* **Local short-circuit** and the ``(success, stdout, stderr)`` tuple contract
  are preserved for every path (R2.10, R2.11, R6.4).
* **Secret hygiene**: only a redacted command summary is logged (R2.12).

The SSH login user is taken from ``LINUX_USER_INSTALLATION`` in
``conf/deploy.ini`` via :func:`src.config_postgres.ssh_target`, falling back to
``ubuntu`` if configuration cannot be read.
"""

import logging
import os
import re
import shlex
import socket
import subprocess
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# Addresses that always denote the local host.
_LOCAL_ALIASES = frozenset({"127.0.0.1", "::1", "localhost"})

# Container operations (image pulls, slow starts) need more headroom than the
# former 30-second default. 120s matches ``execution_manager.launch`` (R2.6).
SSH_CONTAINER_TIMEOUT_DEFAULT = 120

# Upper bound on the TCP connect phase so a dead host fails fast instead of
# burning the whole command budget. Clamped to the command timeout when that is
# smaller.
_CONNECT_TIMEOUT_CAP = 30

# Maximum number of SSH attempts for a single transient-classified failure. The
# retry is bounded by the policy; a deterministic failure (changed host key,
# auth, policy) is never retried regardless of this value.
_SSH_MAX_ATTEMPTS = 3

# Substrings that identify a changed/failed host-key rejection on stderr. These
# are deterministic (never retried): a key mismatch is a security event, not a
# transient network blip (R2.2).
_HOST_KEY_CHANGED_MARKERS = (
    "remote host identification has changed",
    "host key verification failed",
)

# Fragments whose *values* must never reach the logs (R2.12). Matched
# case-insensitively against argv tokens / command text.
_SECRET_KEY_HINTS = ("password", "passwd", "secret", "token", "apikey", "api_key", "key")


def _current_server_ip() -> str:
    """Return the control plane's own primary IP address.

    Uses the same UDP-socket trick used elsewhere in the platform
    (``platform_discovery.get_current_server_ip``); falls back to ``127.0.0.1``
    if it cannot be determined.
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def is_local_server(server_ip: str) -> bool:
    """Return True when ``server_ip`` refers to the host running this process.

    The control plane is itself a managed server (typically a STAND_ALONE or
    PRIMARY row), so commands targeting its own IP must run locally: SSH back to
    self usually fails under ``BatchMode=yes`` (no key to self), which would
    otherwise mark the local host "unreachable". Matches a loopback alias or the
    machine's own primary IP.
    """
    ip = (server_ip or "").strip()
    if not ip:
        return False
    if ip in _LOCAL_ALIASES:
        return True
    try:
        if ip == _current_server_ip():
            return True
        # Resolve any locally-bound addresses for this host as a fallback.
        local_ips = {
            info[4][0]
            for info in socket.getaddrinfo(socket.gethostname(), None)
        }
        return ip in local_ips
    except OSError:
        return False


def _repo_root() -> str:
    """Return the repository root (the parent of this ``src`` directory).

    Mirrors the ``<repo>/conf`` convention used by
    ``configuration_writer.ConfigurationWriter`` and ``config_postgres``.
    """
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _config_value(key: str, default: str) -> str:
    """Return a configuration value for ``key`` or ``default``.

    Reads from the ``configuration`` table via
    ``database_postgres.get_config_value`` when available; any failure (no DB,
    import error, missing row) falls back to ``default`` so SSH still works in a
    bare/test environment.
    """
    try:
        from .database_postgres import get_config_value

        value = get_config_value(key, default_value=None)
        if value:
            return str(value)
    except Exception:  # noqa: BLE001 - config lookup is best-effort
        pass
    return default


# Cache of the resolved managed known_hosts path. SSH runs on a hot path, so the
# config lookup is performed once per process rather than on every invocation.
_MANAGED_KNOWN_HOSTS_CACHE: Optional[str] = None


def managed_known_hosts_path() -> str:
    """Return the managed ``known_hosts`` path for TOFU verification (R2.5).

    Resolution order:

    1. explicit config value ``ssh_managed_known_hosts`` (configuration table /
       deploy.ini), when set;
    2. default ``<repo>/conf/ssh/known_hosts``.

    The resolved value is memoized for the life of the process so repeated SSH
    calls do not re-query configuration.
    """
    global _MANAGED_KNOWN_HOSTS_CACHE
    if _MANAGED_KNOWN_HOSTS_CACHE is None:
        default = os.path.join(_repo_root(), "conf", "ssh", "known_hosts")
        _MANAGED_KNOWN_HOSTS_CACHE = _config_value(
            "ssh_managed_known_hosts", default=default
        )
    return _MANAGED_KNOWN_HOSTS_CACHE


def control_socket_dir() -> str:
    """Return the directory holding SSH connection-multiplexing sockets (R2.7).

    Defaults to ``<repo>/conf/ssh/cm``. Short ``%r@%h:%p`` socket names under
    this directory avoid the Unix-socket path-length limit.
    """
    return os.path.join(_repo_root(), "conf", "ssh", "cm")


def _ensure_parent_dir(path: str) -> None:
    """Create the parent directory of ``path`` if it does not exist (R2.4)."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _ensure_dir(path: str) -> None:
    """Create ``path`` (a directory) with private permissions if missing."""
    if path:
        os.makedirs(path, mode=0o700, exist_ok=True)


def _redact(cmd) -> str:
    """Return a log-safe summary of a command, stripping secret values (R2.12).

    Accepts either an argv list or a shell-string command. ``-e KEY=VALUE`` env
    fragments and any ``KEY=VALUE`` token whose key looks like a credential have
    their value replaced with ``***``; the whole summary is truncated so a long
    command cannot flood the log.
    """
    text = cmd if isinstance(cmd, str) else " ".join(str(c) for c in (cmd or []))

    def _mask(match: "re.Match") -> str:
        return f"{match.group(1)}=***"

    # Mask KEY=VALUE where KEY hints at a secret (handles `-e KEY=VALUE` too).
    hint = "|".join(re.escape(h) for h in _SECRET_KEY_HINTS)
    text = re.sub(
        rf"(\b\w*(?:{hint})\w*)=\S+",
        _mask,
        text,
        flags=re.IGNORECASE,
    )

    # Mask credentials embedded in any URL (``scheme://user:password@host``),
    # regardless of the surrounding key name. A proxy URL such as
    # ``HTTPS_PROXY=http://user:secret@host`` carries the secret in its userinfo
    # component, which the key-hint pass above does not catch when the key
    # (e.g. ``HTTPS_PROXY``) is not itself a credential hint (R2.12 — proxy URLs
    # must never reach the log).
    text = re.sub(
        r"([a-zA-Z][a-zA-Z0-9+.\-]*://)[^\s:/@]+:[^\s:/@]+@",
        r"\1***:***@",
        text,
    )
    text = text.strip()
    return text if len(text) <= 256 else text[:253] + "..."


class SSHError(Exception):
    """Base class for typed SSH failures carrying the remote ``stderr``.

    The ``stderr`` is surfaced on the attribute of the same name so
    :func:`src.execution_policy.ssh_is_transient` can classify on it exactly as
    ``execution_manager._is_transient_failure`` does.
    """

    def __init__(self, stderr: str = "", returncode: Optional[int] = None):
        super().__init__(stderr or self.__class__.__name__)
        self.stderr = stderr or ""
        self.returncode = returncode


class SSHTransientError(SSHError):
    """A transient (retryable) SSH failure — connect/timeout/reset/etc."""


class SSHDeterministicError(SSHError):
    """A deterministic (non-retryable) SSH failure — changed host key, auth."""


def local_execute(command: str, timeout: int = 30) -> Tuple[bool, str, str]:
    """Execute a shell command on the local host.

    Mirrors the return shape of :func:`ssh_execute` so callers can treat local
    and remote targets uniformly.

    Returns:
        tuple: ``(success: bool, stdout: str, stderr: str)``.
    """
    logger.info("Executing local command: %s", _redact(command))
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            return True, result.stdout, result.stderr
        logger.warning(
            "Local command failed (exit code %s): %s",
            result.returncode, (result.stderr or "")[:512],
        )
        return False, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        logger.error("Local command timed out after %ss", timeout)
        return False, "", f"Command timed out after {timeout} seconds"
    except Exception as e:  # noqa: BLE001 - surface any exec error as a failure
        logger.error("Local execution error: %s", str(e))
        return False, "", str(e)


def local_execute_argv(argv: List[str], timeout: int = 30) -> Tuple[bool, str, str]:
    """Execute a command given as an argv on the local host (no ``shell=True``).

    The argv transport counterpart of :func:`local_execute`; mirrors the
    ``(success, stdout, stderr)`` contract.
    """
    logger.info("Executing local command: %s", _redact(argv))
    try:
        result = subprocess.run(
            list(argv),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            return True, result.stdout, result.stderr
        logger.warning(
            "Local command failed (exit code %s): %s",
            result.returncode, (result.stderr or "")[:512],
        )
        return False, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        logger.error("Local command timed out after %ss", timeout)
        return False, "", f"Command timed out after {timeout} seconds"
    except Exception as e:  # noqa: BLE001 - surface any exec error as a failure
        logger.error("Local execution error: %s", str(e))
        return False, "", str(e)


def _resolve_ssh_target(server_ip: str) -> str:
    """Return the ``user@host`` SSH target for a server IP.

    Uses the configured installation user; defaults to ``ubuntu`` if the
    configuration module cannot be imported or read.
    """
    try:
        from .config_postgres import LINUX_USER_INSTALLATION, ssh_target
        return ssh_target(LINUX_USER_INSTALLATION, server_ip)
    except Exception:
        return f"ubuntu@{server_ip}"


def _ssh_base_options(timeout: int) -> List[str]:
    """Build the hardened SSH ``-o`` option list shared by both transports.

    Ensures the managed ``known_hosts`` parent and the control-socket directory
    exist (R2.4) before returning the options:

    * ``StrictHostKeyChecking=accept-new`` + managed ``UserKnownHostsFile`` —
      TOFU: record an unseen key, reject a changed one (R2.1, R2.2, R2.3).
    * ``BatchMode=yes`` — never prompt (preserved).
    * ``ConnectTimeout=min(timeout, 30)`` — fail fast on a dead host (R2.6).
    * ``ControlMaster=auto`` / ``ControlPersist=60s`` / ``ControlPath`` —
      connection reuse (R2.7).
    """
    known_hosts = managed_known_hosts_path()
    _ensure_parent_dir(known_hosts)

    cm_dir = control_socket_dir()
    try:
        _ensure_dir(cm_dir)
        control_path = os.path.join(cm_dir, "cm-%r@%h:%p")
        control_opts = [
            "-o", "ControlMaster=auto",
            "-o", "ControlPersist=60s",
            "-o", f"ControlPath={control_path}",
        ]
    except OSError:
        # If the socket directory cannot be created, proceed without reuse
        # rather than failing the command outright.
        control_opts = []

    connect_timeout = max(1, min(int(timeout), _CONNECT_TIMEOUT_CAP))

    return [
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", f"UserKnownHostsFile={known_hosts}",
        "-o", "BatchMode=yes",
        "-o", f"ConnectTimeout={connect_timeout}",
        *control_opts,
    ]


def _stderr_is_host_key_changed(stderr: str) -> bool:
    """Return True when ``stderr`` reports a changed/failed host key (R2.2)."""
    text = (stderr or "").lower()
    return any(marker in text for marker in _HOST_KEY_CHANGED_MARKERS)


def _run_ssh_with_policy(
    ssh_cmd: List[str], server_ip: str, timeout: int
) -> Tuple[bool, str, str]:
    """Run a prepared ``ssh_cmd`` under the shared execution policy (R2.8).

    The inner op raises a typed :class:`SSHTransientError` /
    :class:`SSHDeterministicError` built from the exit/stderr so
    :func:`src.execution_policy.ssh_is_transient` classifies it exactly as the
    ARO ``execution_manager`` does. A changed host key is forced deterministic
    (no retry, R2.2). Returns the ``(success, stdout, stderr)`` tuple.
    """
    from .execution_policy import (
        BackoffParams,
        Outcome,
        OutcomeStatus,
        run_with_policy,
        ssh_is_transient,
    )

    def op(_token):
        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            # A connection/command timeout is transient — eligible for retry.
            raise SSHTransientError(
                f"Command timed out after {timeout} seconds"
            ) from exc

        if result.returncode == 0:
            return (result.stdout, result.stderr)

        stderr = result.stderr or ""
        # A changed host key is a security event, never a transient blip.
        if _stderr_is_host_key_changed(stderr):
            raise SSHDeterministicError(stderr, returncode=result.returncode)
        # Let the shared classifier decide: a transient-looking stderr raises a
        # transient error (retryable); anything else is deterministic.
        if ssh_is_transient(SSHError(stderr)):
            raise SSHTransientError(stderr, returncode=result.returncode)
        raise SSHDeterministicError(stderr, returncode=result.returncode)

    outcome: Outcome = run_with_policy(
        op,
        timeout=None,  # each attempt is already bounded by subprocess timeout
        max_attempts=_SSH_MAX_ATTEMPTS,
        backoff=BackoffParams(),
        is_transient=ssh_is_transient,
    )

    if outcome.status == OutcomeStatus.SUCCEEDED:
        logger.info("SSH command succeeded on %s", server_ip)
        stdout, stderr = outcome.value
        return True, stdout, stderr

    # Any terminal non-success maps to a failed tuple with the remote stderr.
    err = outcome.error
    stderr = getattr(err, "stderr", None) or (str(err) if err else "")
    if outcome.status == OutcomeStatus.TIMED_OUT and not stderr:
        stderr = f"Command timed out after {timeout} seconds"
    logger.warning(
        "SSH command failed on %s (%s): %s",
        server_ip, outcome.status.value, (stderr or "")[:512],
    )
    return False, "", stderr


def ssh_execute(
    server_ip: str, command: str, timeout: Optional[int] = None
) -> Tuple[bool, str, str]:
    """Execute a shell-string command on a remote server via SSH (legacy API).

    Hardened in Phase 4 to use TOFU host-key verification over a managed
    ``known_hosts`` file, connection reuse, and bounded transient retry, while
    preserving the exact ``(success, stdout, stderr)`` contract and the
    ``is_local_server`` short-circuit relied on by existing callers
    (``execution_manager.launch``, GPU routes, runtime discovery) — R6.4.

    Args:
        server_ip: IP address of the target server.
        command: Shell command string to execute remotely.
        timeout: Maximum execution time in seconds. When omitted, defaults to
            :data:`SSH_CONTAINER_TIMEOUT_DEFAULT` (120s), larger than the former
            30s default (R2.6).

    Returns:
        tuple: ``(success: bool, stdout: str, stderr: str)``. On a failure,
        ``success`` is False and ``stderr`` holds the reason.
    """
    effective_timeout = SSH_CONTAINER_TIMEOUT_DEFAULT if timeout is None else int(timeout)

    # The control plane is itself a managed server. When the target is the local
    # host, run the command directly: SSH back to self fails under
    # ``BatchMode=yes`` (no self key), which would wrongly report the host as
    # unreachable and hide its containers from discovery (R2.10, R6.4).
    if is_local_server(server_ip):
        logger.info("Target %s is local; executing without SSH", server_ip)
        return local_execute(command, timeout=effective_timeout)

    ssh_cmd = [
        "ssh",
        *_ssh_base_options(effective_timeout),
        _resolve_ssh_target(server_ip),
        command,
    ]

    logger.info("Executing SSH command on %s: %s", server_ip, _redact(command))
    return _run_ssh_with_policy(ssh_cmd, server_ip, effective_timeout)


def ssh_execute_argv(
    server_ip: str, argv: List[str], timeout: Optional[int] = None
) -> Tuple[bool, str, str]:
    """Execute an argv command on a remote server, preserving safe quoting (R2.9).

    The remote command is assembled from ``argv`` with shell-safe quoting
    (:func:`src.aro.execution_manager.argv_to_shell`, i.e. ``shlex.quote`` per
    token) so a value containing spaces or metacharacters cannot break out of
    its argument. The local short-circuit runs the argv directly via
    ``subprocess.run(argv)`` with no ``shell=True`` (R2.10). Both paths return
    the ``(success, stdout, stderr)`` tuple (R2.11).

    Args:
        server_ip: IP address of the target server.
        argv: Command as an argument list, e.g. ``["docker", "restart", name]``.
        timeout: Maximum execution time in seconds; defaults to
            :data:`SSH_CONTAINER_TIMEOUT_DEFAULT`.

    Returns:
        tuple: ``(success: bool, stdout: str, stderr: str)``.
    """
    effective_timeout = SSH_CONTAINER_TIMEOUT_DEFAULT if timeout is None else int(timeout)
    argv = list(argv)

    if is_local_server(server_ip):
        logger.info("Target %s is local; executing argv without SSH", server_ip)
        return local_execute_argv(argv, timeout=effective_timeout)

    remote_command = _argv_to_shell(argv)
    ssh_cmd = [
        "ssh",
        *_ssh_base_options(effective_timeout),
        _resolve_ssh_target(server_ip),
        remote_command,
    ]

    logger.info("Executing SSH argv on %s: %s", server_ip, _redact(argv))
    return _run_ssh_with_policy(ssh_cmd, server_ip, effective_timeout)


def _argv_to_shell(argv: List[str]) -> str:
    """Quote an argv into a single shell-safe command string.

    Reuses :func:`src.aro.execution_manager.argv_to_shell` when importable
    (single source of truth); falls back to an equivalent ``shlex.quote`` join.
    """
    try:
        from .aro.execution_manager import argv_to_shell
        return argv_to_shell(argv)
    except Exception:  # noqa: BLE001 - fall back to the stdlib equivalent
        return " ".join(shlex.quote(str(a)) for a in argv)
