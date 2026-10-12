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
import subprocess
from typing import Tuple

logger = logging.getLogger(__name__)


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
