"""SSH-based Docker container collector for Runtime Security.

Given a managed server (a row from the ``servers`` table), this module runs
``docker ps``/``docker inspect``/``docker top`` over the shared SSH transport
and normalizes the output into plain observation dicts that the classifier,
correlator, and anomaly detector consume.

Design notes:
- SSH I/O is isolated in :func:`collect_server_containers`. The parsing helpers
  are pure functions of their string inputs, so they are unit-testable with
  captured fixtures and no network.
- Hosts without Docker, or unreachable hosts, are handled gracefully: the
  collector logs and returns an empty list plus an error string the caller can
  record on the scan run.
- Containers the platform did not launch (no platform labels) are discovered
  the same as managed ones; discovery is label-agnostic by design.
"""

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Labels that indicate the container was launched by this platform. Used only to
# set ``is_platform_managed``; it never filters discovery.
PLATFORM_LABEL_KEYS = (
    "com.agentic_ai_platform",
    "opcp.managed",
    "com.docker.compose.project",  # heuristic: our stack uses compose
)

# docker ps --format uses Go template; we request JSON lines.
PS_FORMAT = "{{json .}}"


def collect_server_containers(
    server: Dict[str, Any], ssh_execute=None, timeout: int = 30
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Discover and normalize all containers on one managed server.

    Args:
        server: A dict with at least ``id`` and ``server_ip`` (as returned from
            the ``servers`` table).
        ssh_execute: Callable ``(server_ip, command, timeout) -> (ok, out, err)``.
            Defaults to the shared SSH helper; injectable for tests.
        timeout: Per-command SSH timeout in seconds.

    Returns:
        ``(observations, error)`` where ``observations`` is a list of normalized
        container dicts and ``error`` is None on success or a short description
        of why discovery failed (host unreachable, Docker missing, etc.).
    """
    if ssh_execute is None:
        from ..ssh_utils import ssh_execute as ssh_execute  # noqa: PLW2901

    server_ip = str(server.get("server_ip"))

    ok, out, err = ssh_execute(
        server_ip,
        f"docker ps --all --no-trunc --format '{PS_FORMAT}'",
        timeout=timeout,
    )
    if not ok:
        reason = (err or "ssh/docker ps failed").strip()
        logger.warning("Container discovery failed on %s: %s", server_ip, reason)
        return [], reason

    ps_entries = parse_ps_json_lines(out)
    if not ps_entries:
        return [], None

    container_ids = [e["container_id"] for e in ps_entries if e.get("container_id")]

    # docker inspect for labels, image, runtime, state. Best-effort: if it
    # fails we still return the ps-derived basics.
    inspect_by_id: Dict[str, Dict[str, Any]] = {}
    if container_ids:
        ok_i, out_i, _ = ssh_execute(
            server_ip,
            "docker inspect " + " ".join(container_ids),
            timeout=timeout,
        )
        if ok_i:
            inspect_by_id = parse_inspect_json(out_i)

    observations: List[Dict[str, Any]] = []
    for entry in ps_entries:
        cid = entry.get("container_id")
        if not cid:
            continue
        inspect = inspect_by_id.get(cid, {})

        # docker top only works for running containers; skip for others.
        processes: List[Dict[str, str]] = []
        if entry.get("state") == "running":
            ok_t, out_t, _ = ssh_execute(
                server_ip, f"docker top {cid} -eo pid,comm,args", timeout=timeout
            )
            if ok_t:
                processes = parse_top_output(out_t)

        observations.append(
            normalize_container(server, entry, inspect, processes)
        )

    return observations, None


def parse_ps_json_lines(output: str) -> List[Dict[str, Any]]:
    """Parse ``docker ps --format '{{json .}}'`` output (one JSON object/line).

    Returns a list of dicts with keys: container_id, name, image, state,
    status, command, labels (raw string).
    """
    entries: List[Dict[str, Any]] = []
    for line in (output or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (ValueError, TypeError):
            continue
        state = (obj.get("State") or "").lower()
        if not state:
            # Older docker ps JSON omits State; infer from Status text.
            status = (obj.get("Status") or "").lower()
            state = "running" if status.startswith("up") else "exited"
        entries.append(
            {
                "container_id": obj.get("ID") or obj.get("Id"),
                "name": obj.get("Names") or obj.get("Name"),
                "image": obj.get("Image"),
                "state": state,
                "status": obj.get("Status"),
                "command": obj.get("Command"),
                "labels_raw": obj.get("Labels", ""),
            }
        )
    return entries


def parse_inspect_json(output: str) -> Dict[str, Dict[str, Any]]:
    """Parse ``docker inspect`` output (a JSON array) keyed by full container ID.

    Extracts image, runtime, state, labels, and environment variables.
    """
    result: Dict[str, Dict[str, Any]] = {}
    try:
        data = json.loads(output or "[]")
    except (ValueError, TypeError):
        return result
    if not isinstance(data, list):
        return result
    for item in data:
        cid = item.get("Id")
        if not cid:
            continue
        config = item.get("Config") or {}
        state = item.get("State") or {}
        host_config = item.get("HostConfig") or {}
        env_list = config.get("Env") or []
        env = {}
        for kv in env_list:
            if isinstance(kv, str) and "=" in kv:
                k, v = kv.split("=", 1)
                env[k] = v
        result[cid] = {
            "image": config.get("Image"),
            "runtime": host_config.get("Runtime"),
            "state": (state.get("Status") or "").lower() or None,
            "labels": config.get("Labels") or {},
            "env": env,
        }
        # Also index by the short 12-char ID so ps IDs resolve.
        result[cid[:12]] = result[cid]
    return result


def parse_top_output(output: str) -> List[Dict[str, str]]:
    """Parse ``docker top <id> -eo pid,comm,args`` into process dicts.

    The first line is a header. Each subsequent line is ``PID COMM ARGS...``.
    Returns a capped list (first 50 processes) of {pid, comm, args}.
    """
    processes: List[Dict[str, str]] = []
    lines = [ln for ln in (output or "").splitlines() if ln.strip()]
    if len(lines) <= 1:
        return processes
    for line in lines[1:51]:
        parts = line.split(None, 2)
        if not parts:
            continue
        pid = parts[0]
        comm = parts[1] if len(parts) > 1 else ""
        args = parts[2] if len(parts) > 2 else comm
        processes.append({"pid": pid, "comm": comm, "args": args})
    return processes


def _is_platform_managed(labels: Dict[str, Any]) -> bool:
    """Heuristic: does this container carry a platform label?"""
    if not labels:
        return False
    return any(key in labels for key in PLATFORM_LABEL_KEYS)


def normalize_container(
    server: Dict[str, Any],
    ps_entry: Dict[str, Any],
    inspect: Dict[str, Any],
    processes: List[Dict[str, str]],
) -> Dict[str, Any]:
    """Combine ps + inspect + top into a single normalized observation dict.

    The returned shape is the contract consumed by the classifier, correlator,
    and anomaly detector.
    """
    labels = inspect.get("labels") or {}
    env = inspect.get("env") or {}
    image = inspect.get("image") or ps_entry.get("image")
    runtime = inspect.get("runtime")
    state = inspect.get("state") or ps_entry.get("state") or "unknown"

    return {
        "server_id": server.get("id"),
        "server_ip": server.get("server_ip"),
        "container_id": ps_entry.get("container_id"),
        "name": (ps_entry.get("name") or "").lstrip("/") or None,
        "image": image,
        "runtime": runtime,
        "state": state,
        "status": ps_entry.get("status"),
        "command": ps_entry.get("command"),
        "labels": labels,
        "env": env,
        "processes": processes,
        "pids": len(processes) if processes else None,
        # cpu/memory are not available from these commands cheaply; left None
        # here and populated later if a stats collector is added.
        "cpu_percent": None,
        "memory_bytes": None,
        "network_summary": {},
        "is_platform_managed": _is_platform_managed(labels),
    }
