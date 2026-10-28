"""Shared SSH execution helper for running commands on managed servers.

Several features (MIG GPU management, Runtime Security container discovery) need
to run commands on remote servers listed in the ``servers`` table. This module
provides a single implementation so the behavior (host-key handling, timeout,
return shape) stays consistent across features.

The SSH login user is taken from ``LINUX_USER_INSTALLATION`` in
``conf/deploy.ini`` via :func:`src.config_postgres.ssh_target`, falling back to
``ubuntu`` if configuration cannot be read.
"""

import logging
import socket
import subprocess
from typing import Tuple

logger = logging.getLogger(__name__)

# Addresses that always denote the local host.
_LOCAL_ALIASES = frozenset({"127.0.0.1", "::1", "localhost"})


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


def local_execute(command: str, timeout: int = 30) -> Tuple[bool, str, str]:
    """Execute a shell command on the local host.

    Mirrors the return shape of :func:`ssh_execute` so callers can treat local
    and remote targets uniformly.

    Returns:
        tuple: ``(success: bool, stdout: str, stderr: str)``.
    """
    logger.info("Executing local command: %s", command)
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


def ssh_execute(server_ip: str, command: str, timeout: int = 30) -> Tuple[bool, str, str]:
    """Execute a command on a remote server via SSH.

    Uses ``StrictHostKeyChecking=no`` and ``UserKnownHostsFile=/dev/null`` to
    avoid interactive prompts, matching the platform's existing remote-exec
    behavior.

    Args:
        server_ip: IP address of the target server.
        command: Shell command string to execute remotely.
        timeout: Maximum execution time in seconds (default 30).

    Returns:
        tuple: ``(success: bool, stdout: str, stderr: str)``. On timeout or an
        unexpected error, ``success`` is False and ``stderr`` holds the reason.
    """
    # The control plane is itself a managed server. When the target is the local
    # host, run the command directly: SSH back to self fails under
    # ``BatchMode=yes`` (no self key), which would wrongly report the host as
    # unreachable and hide its containers from discovery.
    if is_local_server(server_ip):
        logger.info("Target %s is local; executing without SSH", server_ip)
        return local_execute(command, timeout=timeout)

    ssh_cmd = [
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", "BatchMode=yes",
        _resolve_ssh_target(server_ip),
        command,
    ]

    logger.info("Executing SSH command on %s: %s", server_ip, command)

    try:
        result = subprocess.run(
            ssh_cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            logger.info("SSH command succeeded on %s", server_ip)
            return True, result.stdout, result.stderr
        logger.warning(
            "SSH command failed on %s (exit code %s): %s",
            server_ip, result.returncode, (result.stderr or "")[:512],
        )
        return False, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        logger.error("SSH command timed out on %s after %ss", server_ip, timeout)
        return False, "", f"Command timed out after {timeout} seconds"
    except Exception as e:  # noqa: BLE001 - surface any exec error as a failure
        logger.error("SSH execution error on %s: %s", server_ip, str(e))
        return False, "", str(e)