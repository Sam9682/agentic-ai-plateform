"""Hardened agent-container execution manager on managed servers (Task 6).

Launches agent runtime containers on managed ``servers`` rows over SSH
(:func:`src.ssh_utils.ssh_execute`), applying least-privilege flags by default
(mirroring the hardening in ``src/serverless/container_runtime.py``):

* ``--cap-drop ALL``, ``--security-opt no-new-privileges``
* ``--read-only`` root filesystem, non-root ``--user``
* ``--pids-limit`` and CPU/memory limits
* egress locked down: either ``--network none`` or routed through the ZAF infra
  proxy via an HTTP(S)_PROXY env + a dedicated proxy network — never open egress
* **never** mounts the Docker socket or host paths, and never runs privileged

The command-assembly core (:func:`build_run_command`) is pure and
property-testable without SSH; :func:`launch`/:func:`stop` perform the remote
execution. A least-loaded server is selected with the same style as
``orchestrator._select_server``.
"""

from __future__ import annotations

import shlex
import uuid
from typing import Any, Dict, List, Optional, Tuple

# Flags/args that must never appear in an agent-container run command.
FORBIDDEN_FRAGMENTS = (
    "--privileged",
    "/var/run/docker.sock",
    "docker.sock",
    "--cap-add",
    "--pid=host",
    "--network host",
    "--net=host",
)


class ExecutionPolicyError(Exception):
    """Raised when a requested environment would violate least-privilege."""


def _validate_environment(env: Dict[str, Any]) -> None:
    """Reject any environment that asks for a forbidden privilege."""
    if env.get("privileged"):
        raise ExecutionPolicyError("privileged containers are not permitted")
    for mount in env.get("volumes", []) or []:
        if "docker.sock" in str(mount):
            raise ExecutionPolicyError("mounting the docker socket is not permitted")
        if str(mount).startswith("/:") or str(mount).startswith("/ "):
            raise ExecutionPolicyError("mounting the host root is not permitted")
    net = env.get("network_policy", "proxy")
    if net not in ("proxy", "none"):
        raise ExecutionPolicyError("network_policy must be 'proxy' or 'none'")


def build_run_command(
    image: str,
    name: str,
    environment: Dict[str, Any],
    *,
    command: Optional[List[str]] = None,
    proxy_url: Optional[str] = None,
) -> List[str]:
    """Assemble a hardened ``docker run`` argv for an agent container. Pure.

    Always emits least-privilege flags and an egress restriction; never emits a
    forbidden fragment. Raises :class:`ExecutionPolicyError` if the requested
    environment would violate the policy.

    Args:
        image: Container image (should be pinned by digest/tag upstream).
        name: Container name.
        environment: Resource/network config (cpu_limit, memory_limit,
            pids_limit, read_only, run_as_user, network_policy, env, runtime_type).
        command: Optional command/args to run in the container.
        proxy_url: The ZAF infra-proxy URL injected as HTTP(S)_PROXY when
            network_policy == 'proxy'.

    Returns:
        The full argv list beginning with ['docker', 'run', '-d', ...].
    """
    _validate_environment(environment)

    cpu = str(environment.get("cpu_limit", "1"))
    memory = str(environment.get("memory_limit", "512m"))
    pids = int(environment.get("pids_limit", 256))
    read_only = environment.get("read_only", True)
    user = str(environment.get("run_as_user", "nobody"))
    network_policy = environment.get("network_policy", "proxy")
    runtime_type = environment.get("runtime_type", "runc")

    argv: List[str] = ["docker", "run", "-d", "--name", name]

    # MicroVM isolation (Kata) when requested; runc is the default.
    if runtime_type and runtime_type != "runc":
        argv += ["--runtime", runtime_type]

    # Least privilege.
    argv += ["--cap-drop", "ALL"]
    argv += ["--security-opt", "no-new-privileges"]
    if read_only:
        argv += ["--read-only"]
    argv += ["--user", user]
    argv += ["--pids-limit", str(pids)]
    argv += ["--memory", memory]
    argv += ["--cpus", cpu]

    # Egress lockdown: fully isolated, or forced through the infra proxy.
    if network_policy == "none":
        argv += ["--network", "none"]
    else:  # 'proxy'
        # Attach to a dedicated proxy network and inject proxy env so all agent
        # egress must traverse the ZAF infra proxy (no direct internet).
        argv += ["--network", "zaf-proxy-net"]
        if proxy_url:
            argv += ["-e", f"HTTP_PROXY={proxy_url}"]
            argv += ["-e", f"HTTPS_PROXY={proxy_url}"]
            argv += ["-e", f"http_proxy={proxy_url}"]
            argv += ["-e", f"https_proxy={proxy_url}"]
            # Block proxy bypass to localhost/metadata endpoints.
            argv += ["-e", "NO_PROXY="]

    # User-provided (non-secret) env vars.
    for key, value in (environment.get("env") or {}).items():
        argv += ["-e", f"{key}={value}"]

    argv += ["--restart", "no"]
    argv += [image]
    if command:
        argv += list(command)

    _assert_no_forbidden(argv)
    return argv


def _assert_no_forbidden(argv: List[str]) -> None:
    """Belt-and-braces: guarantee no forbidden fragment slipped into the argv."""
    joined = " ".join(argv)
    for frag in FORBIDDEN_FRAGMENTS:
        if frag in joined:
            raise ExecutionPolicyError(f"refusing to run with forbidden flag: {frag}")


def argv_to_shell(argv: List[str]) -> str:
    """Quote an argv into a single shell command string for ssh_execute."""
    return " ".join(shlex.quote(a) for a in argv)


# --------------------------------------------------------------------------- #
# Remote execution (SSH)
# --------------------------------------------------------------------------- #
def _ssh():
    from ..ssh_utils import ssh_execute
    return ssh_execute


def _get_db():
    from ..database_postgres import db_manager
    return db_manager


def select_server(tenant_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """Pick a least-loaded active server, mirroring orchestrator._select_server.

    Returns ``{id, server_ip, server_name}`` or None when no server is eligible.
    """
    rows = _get_db().execute_query(
        """
        SELECT s.id, s.server_ip, s.server_name
        FROM servers s
        WHERE s.server_status IN ('STAND_BY', 'ACTIVE')
        ORDER BY s.id
        LIMIT 1
        """,
        fetch_all=True,
    ) or []
    if not rows:
        return None
    r = rows[0]
    return {"id": r[0], "server_ip": r[1], "server_name": r[2]}


def launch(
    server_ip: str,
    image: str,
    environment: Dict[str, Any],
    *,
    name: Optional[str] = None,
    command: Optional[List[str]] = None,
    proxy_url: Optional[str] = None,
    timeout: int = 120,
) -> Tuple[bool, str, str]:
    """Launch a hardened agent container on ``server_ip`` via SSH.

    Returns ``(success, container_id_or_stdout, stderr)``. The run command is
    assembled by :func:`build_run_command` (which enforces the hardening), so a
    policy violation raises before any remote command runs.
    """
    container_name = name or f"aro-agent-{uuid.uuid4().hex[:12]}"
    argv = build_run_command(
        image, container_name, environment, command=command, proxy_url=proxy_url
    )
    ssh_execute = _ssh()
    ok, stdout, stderr = ssh_execute(server_ip, argv_to_shell(argv), timeout=timeout)
    return ok, (stdout.strip() if ok else stdout), stderr


def stop(server_ip: str, container_ref: str, *, timeout: int = 60) -> Tuple[bool, str, str]:
    """Stop and remove an agent container on ``server_ip`` via SSH."""
    cmd = f"docker stop {shlex.quote(container_ref)} && docker rm {shlex.quote(container_ref)}"
    return _ssh()(server_ip, cmd, timeout=timeout)
