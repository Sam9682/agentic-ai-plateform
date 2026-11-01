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
from typing import Any, Callable, Dict, List, Optional, Tuple

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


def assert_image_pinned(image: str) -> None:
    """Reject container images that are not pinned by digest. Pure.

    A pinned reference carries an explicit ``@sha256:...`` digest, which makes
    the image immutable regardless of tag movement. Everything else is
    rejected before any remote command runs:

    * ``name@sha256:...``                -> OK (digest-pinned)
    * ``name`` (tag-less, no digest)     -> rejected
    * ``name:latest`` (no digest)        -> rejected (``latest`` is mutable)
    * ``name:<tag>`` (no digest)         -> rejected (tags are mutable)

    Raises:
        ExecutionPolicyError: when ``image`` is not digest-pinned.
    """
    ref = image.strip()
    if "@sha256:" in ref:
        return  # digest-pinned: OK
    name, _, tag = ref.rpartition(":")
    if not name or not tag:
        raise ExecutionPolicyError("image tag-less without digest")
    if tag.lower() == "latest":
        raise ExecutionPolicyError("image tag 'latest' is not pinned")
    raise ExecutionPolicyError("image must be digest-pinned (name@sha256:...)")


def argv_to_shell(argv: List[str]) -> str:
    """Quote an argv into a single shell command string for ssh_execute."""
    return " ".join(shlex.quote(a) for a in argv)


# Lowercase substrings that mark a launch failure as a *transient* SSH/launch
# problem (connection refused, timed out, host unreachable, temporary name
# resolution failure, broken pipe). These are safe to re-attempt. Anything not
# matched here is treated as non-transient and is NOT retried.
_TRANSIENT_MARKERS = (
    "timed out",
    "timeout",
    "connection refused",
    "connection reset",
    "connection closed",
    "connection timed out",
    "no route to host",
    "host unreachable",
    "network is unreachable",
    "temporary failure in name resolution",
    "broken pipe",
    "ssh: connect",
    "kex_exchange_identification",
    "operation timed out",
)


def _is_transient_failure(stderr: str) -> bool:
    """Classify a failed launch's stderr as transient (retryable) or not. Pure.

    A launch is retryable only when the failure looks like a transient SSH or
    network problem (connection refused/reset, timeout, host/route unreachable,
    temporary DNS failure, broken pipe). Every other failure — including an
    empty or unrecognized message — is treated as permanent and is not retried.

    Note: policy violations raise :class:`ExecutionPolicyError` and so never
    reach this classifier; they propagate immediately and are never retried.

    Args:
        stderr: The stderr text returned by the failed ``ssh_execute`` call.

    Returns:
        ``True`` when the failure is transient and the launch may be re-attempted.
    """
    text = (stderr or "").lower()
    return any(marker in text for marker in _TRANSIENT_MARKERS)


# --------------------------------------------------------------------------- #
# Remote execution (SSH)
# --------------------------------------------------------------------------- #
def _ssh():
    from ..ssh_utils import ssh_execute
    return ssh_execute


def _get_db():
    from ..database_postgres import db_manager
    return db_manager


def tenant_eligible(server_row: Dict[str, Any], tenant_id: Optional[int]) -> bool:
    """Pure tenant-eligibility predicate for a candidate server. Pure.

    The ``servers`` table has no per-server ``tenant_id`` column (verified
    against ``scripts/postgresql_schema.sql``), so eligibility is expressed as a
    pure rule applied in Python rather than a SQL join: an active server is
    eligible for a tenant unless an exclusion rule says otherwise. With no
    exclusion mapping present, every active server is eligible for every tenant
    (the default). This keeps the design additive — no schema change to
    ``servers`` is required — while giving Phase 3 a single, well-defined place
    to interpose per-tenant placement restrictions.

    Args:
        server_row: A candidate server dict (``id``/``server_ip``/``server_name``/``load``).
        tenant_id: The tenant the selection is being made for (may be ``None``).

    Returns:
        ``True`` when the server is eligible for ``tenant_id`` (default).
    """
    return True


def select_server(tenant_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """Pick the least-loaded active server eligible for ``tenant_id``.

    Candidate servers are active (``STAND_BY``/``ACTIVE``) and ordered by current
    load ascending (the joined count of ``instances`` rows referencing the
    server) then by ``id`` ascending as a stable tie-breaker. The pure
    :func:`tenant_eligible` predicate then filters the ordered candidates; the
    first eligible server wins.

    Args:
        tenant_id: The tenant the selection is being made for (may be ``None``).

    Returns:
        ``{id, server_ip, server_name, load}`` for the chosen server, or ``None``
        when no active server is eligible for ``tenant_id`` (AC 3.2).
    """
    rows = _get_db().execute_query(
        """
        SELECT s.id, s.server_ip, s.server_name, COALESCE(i.cnt, 0) AS load
        FROM servers s
        LEFT JOIN (
            SELECT server_id, COUNT(*) AS cnt
            FROM instances
            GROUP BY server_id
        ) i ON i.server_id = s.id
        WHERE s.server_status IN ('STAND_BY', 'ACTIVE')
        ORDER BY load ASC, s.id ASC
        """,
        fetch_all=True,
    ) or []
    for r in rows:
        candidate = {
            "id": r[0],
            "server_ip": r[1],
            "server_name": r[2],
            "load": r[3],
        }
        if tenant_eligible(candidate, tenant_id):
            return candidate
    return None


def launch(
    server_ip: str,
    image: str,
    environment: Dict[str, Any],
    *,
    name: Optional[str] = None,
    command: Optional[List[str]] = None,
    proxy_url: Optional[str] = None,
    timeout: int = 120,
    max_retries: int = 0,
    tenant_id: Optional[int] = None,
    zaf_egress: Optional[Any] = None,
) -> Tuple[bool, str, str]:
    """Launch a hardened agent container on ``server_ip`` via SSH.

    Returns ``(success, container_id_or_stdout, stderr)``.

    Policy gates run **before** any remote command (AC 3.3, 3.4):

    1. :func:`assert_image_pinned` rejects an unpinned image reference first, so
       no SSH is issued for a ``latest``/tag-less/bare-tag image.
    2. The run command is assembled by :func:`build_run_command`, which enforces
       least-privilege hardening and the forbidden-fragment checks on every
       launch (AC 3.7); a policy violation raises before any remote command.
    3. WHERE the ``proxy`` network policy is used, the dedicated
       ``zaf-proxy-net`` network must already exist on the target server; its
       absence rejects the launch with :class:`ExecutionPolicyError` before the
       ``docker run`` (AC 3.4).

    Bounded retry (AC 3.6): when the ``docker run`` fails *transiently* (an SSH
    connect/timeout-style failure, per :func:`_is_transient_failure`), the launch
    is re-attempted up to ``max_retries`` additional times — at most
    ``1 + max_retries`` total attempts — returning the last failure once the
    bound is reached. A non-transient ``docker run`` failure returns immediately.
    A policy failure raises :class:`ExecutionPolicyError` and is **never**
    retried: the pin check and the proxy-net check sit outside the retry loop, so
    they run exactly once and propagate on rejection. With the default
    ``max_retries=0`` the behavior is identical to a single attempt.

    ZAF egress seam (AC 3.8, 8.1, 8.2, 8.3): ``zaf_egress`` is an injectable
    callable consulted once at launch, after the pin/proxy-net policy gates and
    the command assembly but immediately before the ``docker run`` is issued
    over SSH. It receives the Phase 3 egress-decision context

        ``{server_ip, image, network_policy, proxy_url, name, tenant_id}``

    — the target server, the (pinned) image reference, the effective network
    policy, the infra-proxy URL, the resolved container name, and the owning
    tenant. In Phase 2 the seam is **inert**: the default is a no-op
    (``lambda ctx: None``) and the callable's return value is discarded, so no
    egress decision can alter the launch (AC 8.2). ``tenant_id`` is optional and
    carried only to populate this context; it does not change any launch
    behavior. Phase 3 will interpose real egress enforcement at this seam.
    """
    # (1) Image pinning is checked first, before any remote command (AC 3.3).
    #     A policy rejection raises here and is never retried.
    assert_image_pinned(image)

    container_name = name or f"aro-agent-{uuid.uuid4().hex[:12]}"
    # (2) Pure assembly: enforces hardening + forbidden-fragment checks (AC 3.7).
    argv = build_run_command(
        image, container_name, environment, command=command, proxy_url=proxy_url
    )

    ssh_execute = _ssh()

    # (3) Proxy-net existence check before the docker run (AC 3.4). Run only when
    # the proxy policy is in effect; '--network none' needs no proxy network.
    # A missing network raises ExecutionPolicyError and is never retried.
    if environment.get("network_policy", "proxy") == "proxy":
        ok, _out, _err = ssh_execute(
            server_ip, "docker network inspect zaf-proxy-net", timeout=15
        )
        if not ok:
            raise ExecutionPolicyError(
                "zaf-proxy-net not present on target server"
            )

    # (3b) Inert ZAF egress seam (AC 3.8, 8.1, 8.2). Consulted once after the
    #      policy gates and before the docker run. The default is a no-op and
    #      the return value is intentionally discarded: in Phase 2 no egress
    #      decision may alter the launch. Phase 3 enforcement hooks in here.
    zaf = zaf_egress or (lambda ctx: None)
    zaf(
        {
            "server_ip": server_ip,
            "image": image,
            "network_policy": environment.get("network_policy", "proxy"),
            "proxy_url": proxy_url,
            "name": container_name,
            "tenant_id": tenant_id,
        }
    )

    # (4) Bounded retry around the docker run only (AC 3.6). At most
    #     1 + max_retries attempts; stop early on success or a non-transient
    #     failure. max_retries is clamped at 0 so a negative bound is a no-op.
    run_cmd = argv_to_shell(argv)
    attempts_remaining = max(0, max_retries)
    while True:
        ok, stdout, stderr = ssh_execute(server_ip, run_cmd, timeout=timeout)
        if ok:
            return ok, stdout.strip(), stderr
        if attempts_remaining > 0 and _is_transient_failure(stderr):
            attempts_remaining -= 1
            continue
        return ok, stdout, stderr


def cancel_launch(
    server_ip: str, name: str, *, timeout: int = 60
) -> Tuple[bool, str, str]:
    """Cancel an in-flight launch: stop and force-remove the partial container.

    Mirrors the :func:`stop` command shape but force-removes by name so a
    partially launched (possibly still-created) container is torn down cleanly
    (AC 3.5). Runs ``docker stop <name>; docker rm -f <name>`` over SSH — the
    ``;`` (not ``&&``) ensures the remove runs even if ``stop`` fails because the
    container never fully started, and ``-f`` removes a running/created
    container. The container ``name`` is shell-quoted.

    Returns:
        The ``(success, stdout, stderr)`` tuple from the remote teardown command,
        reporting the cancellation outcome.
    """
    quoted = shlex.quote(name)
    cmd = f"docker stop {quoted}; docker rm -f {quoted}"
    return _ssh()(server_ip, cmd, timeout=timeout)


def stop(server_ip: str, container_ref: str, *, timeout: int = 60) -> Tuple[bool, str, str]:
    """Stop and remove an agent container on ``server_ip`` via SSH."""
    cmd = f"docker stop {shlex.quote(container_ref)} && docker rm {shlex.quote(container_ref)}"
    return _ssh()(server_ip, cmd, timeout=timeout)


# --------------------------------------------------------------------------- #
# Session durability — startup reconnect (Req 4.2, 4.3, 4.4, 4.5)
# --------------------------------------------------------------------------- #
def _lifecycle_service():
    from .lifecycle_service import LifecycleService
    return LifecycleService


def reconnect_running_sessions(
    tenant_id: int,
    *,
    adapter_for: Optional[Callable[[Dict[str, Any]], Any]] = None,
    probe: Callable[[Dict[str, Any]], bool],
    lifecycle_service: Optional[Any] = None,
    agent_repo: Optional[Any] = None,
    events_repo: Optional[Any] = None,
) -> Dict[str, List[int]]:
    """Reconnect (or close out) every RUNNING session after a control-plane restart.

    Invoked **once** at worker/service startup. It loads every ``agent_executions``
    row whose status is ``RUNNING`` (via :func:`agent_repository.list_running_executions`)
    and, for each, re-attaches to the already-running remote runtime recorded on
    the row rather than launching a new one:

    * ``probe(row)`` reports whether the recorded remote runtime (e.g. the
      ``container_id`` inspected over SSH, or the ACP/MCP session handle) is still
      reachable. It is injected so the routine is unit-testable without SSH/DB.
    * **Reachable** (``probe`` returns truthy): re-attach by leaving the row and
      the agent in RUNNING — **no new runtime is launched** (AC 4.2). The session
      simply resumes under the restarted control plane.
    * **Unreachable** (``probe`` returns falsy): the recorded runtime is gone, so
      the agent is transitioned to ``UNHEALTHY`` (AC 4.3) and the Execution_Row is
      closed out as ``UNHEALTHY`` with ``ended=True`` (records ``ended_at``,
      AC 4.3/4.4). The ``RUNNING -> UNHEALTHY`` agent edge is already graph-legal.
      The agent transition is guarded: if the agent is **not** currently RUNNING
      (the row is RUNNING but the agent status has drifted, e.g. already STOPPING
      or UNHEALTHY), the illegal transition is swallowed and the row is still
      closed out, so a stale row never leaves a half-open session.

    Every state change is recorded through the existing event service
    (:func:`event_service.emit` -> ``events_repository.append_event``) using the
    canonical ``build_event`` shape — no schema change (AC 4.5). An
    ``agent.unhealthy`` event (source ``reconnect``) is emitted for each
    unreachable session that is closed out.

    Dependencies are injected (``adapter_for``, ``probe``, and the
    ``lifecycle_service``/``agent_repo``/``events_repo`` collaborators) mirroring
    the :class:`~src.aro.lifecycle_service.LifecycleService` injection style, so the
    routine runs in a unit test with fakes and no DB or SSH. ``adapter_for`` is
    accepted for parity with the lifecycle service and so a ``probe`` built on the
    runtime adapter can be derived by the caller; the routine itself drives
    reachability solely through ``probe``.

    Args:
        tenant_id: Tenant whose RUNNING sessions are reconnected.
        adapter_for: Optional ``callable(agent) -> AgentRuntimeAdapter`` passed
            through to the lifecycle service (and available to a caller building
            ``probe`` from the adapter).
        probe: ``callable(row) -> bool`` reporting whether the recorded remote
            runtime for an execution row is still reachable.
        lifecycle_service: Optional pre-built lifecycle service; when omitted a
            :class:`LifecycleService` is constructed with the injected
            ``adapter_for``/``events_repo``/``agent_repo``.
        agent_repo: Optional agent repository module/object (defaults to
            :mod:`agent_repository`).
        events_repo: Optional events repository (defaults to
            :mod:`events_repository`).

    Returns:
        A summary ``{"reconnected": [exec_id, ...], "closed_out": [exec_id, ...]}``
        listing the Execution_Row ids that were re-attached vs. closed out.
    """
    if agent_repo is None:
        from . import agent_repository as agent_repo
    if events_repo is None:
        from . import events_repository as events_repo
    if lifecycle_service is None:
        lifecycle_service = _lifecycle_service()(
            events_repo=events_repo,
            adapter_for=adapter_for,
            agent_repo=agent_repo,
        )

    # Import here to avoid a module-level dependency cycle and to read the
    # canonical UNHEALTHY state name from the pure graph.
    from . import event_service as es
    from . import lifecycle

    reconnected: List[int] = []
    closed_out: List[int] = []

    for row in agent_repo.list_running_executions(tenant_id):
        if probe(row):
            # Reachable: re-attach in place. Keep the row (and agent) RUNNING and
            # launch NOTHING new (AC 4.2).
            reconnected.append(row["id"])
            continue

        # Unreachable: the recorded remote runtime is gone. Transition the agent
        # to UNHEALTHY (AC 4.3) and close out the row (AC 4.3/4.4).
        agent_pk = row["agent_id"]
        try:
            lifecycle_service.transition(tenant_id, agent_pk, lifecycle.UNHEALTHY)
        except Exception:  # noqa: BLE001
            # The row is RUNNING but the agent status has drifted off RUNNING, so
            # RUNNING -> UNHEALTHY is no longer legal. Swallow the illegal
            # transition and still close out the stale row below so no half-open
            # session survives the restart.
            pass
        agent_repo.set_execution_status(
            tenant_id, row["id"], lifecycle.UNHEALTHY, ended=True
        )
        # Record the close-out through the existing event service with the
        # canonical schema (AC 4.5); no schema change.
        es.emit(
            events_repo,
            tenant_id,
            "agent.unhealthy",
            "reconnect",
            execution_id=str(row["id"]),
            action={
                "reason": "remote runtime unreachable after control-plane restart",
                "execution_ref": row.get("execution_ref"),
                "runtime_handle": row.get("runtime_handle"),
            },
        )
        closed_out.append(row["id"])

    return {"reconnected": reconnected, "closed_out": closed_out}
