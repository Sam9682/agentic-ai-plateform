"""Agent Control aggregation/serialization logic (surface-agnostic).

Holds the pure logic the Agent_Control_API exposes so it is unit- and
property-testable without Flask: serialize discovered containers to the
API contract and aggregate across managed servers with per-server error
indicators. Mirrors the surface-agnostic style of TemplateDeployService /
SandboxManager.

Phase 4 hardening (R5) adds two surface-agnostic capabilities alongside the
inventory logic, both with their collaborators injected so they are unit-
testable without live Docker, PostgreSQL, or SSH (R5.9):

* :func:`actuate` — live start/stop/restart of a container. It builds the
  docker argv and dispatches through the hardened ``ssh_utils`` argv transport;
  the ``ssh`` callable is injected so command-building and server-selection are
  testable with a fake runner (R5.6, R5.9).
* :func:`scan_live_parallel` — the parallel counterpart of :func:`scan_live`.
  It fans ``collect(server)`` out across a thread pool with a per-server
  deadline so one slow/unreachable server costs at most that deadline rather
  than serializing the whole scan (R5.7). The serial :func:`scan_live` is kept
  unchanged for back-compat; both share :func:`serialize_container`.
"""

from concurrent.futures import ThreadPoolExecutor

# Allowed actuation verbs and the docker argv each one builds (Req 5.6). The
# container reference is appended at dispatch time.
_ACTUATE_ACTIONS = ("start", "stop", "restart")

# Default per-container actuation timeout (seconds), matching the SSH container
# default used by the hardened ssh_utils transport (Req 5.6).
ACTUATE_TIMEOUT_DEFAULT = 120

# Parallel-scan defaults (Req 5.7). A conservative worker cap and a per-server
# deadline so one slow/unreachable server never serializes the scan.
SCAN_MAX_WORKERS_DEFAULT = 8
SCAN_PER_SERVER_DEADLINE_DEFAULT = 10.0

# Required per-container fields in the API contract (Req 4.4).
CONTAINER_FIELDS = (
    "server_id", "server_name", "container_id", "name", "image",
    "state", "classification", "confidence_score", "classification_evidence",
    "application_name", "owner",
)

# Docker Compose label carrying the project (application) name (Req 1.2, 1.3).
COMPOSE_PROJECT_LABEL = "com.docker.compose.project"


def _coerce_application_name(labels):
    """Return the compose project name, or '' when absent (Req 1.2, 1.3).

    Returns the stripped ``com.docker.compose.project`` label value when
    ``labels`` is a dict and the value is a non-empty string; otherwise ''.
    """
    if isinstance(labels, dict):
        value = labels.get(COMPOSE_PROJECT_LABEL)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _coerce_confidence(value):
    """Coerce any confidence value to a float, defaulting to 0.0.

    Missing values, ``None``, and non-numeric/odd types all fall back to
    ``0.0`` so the serialized shape always carries a float (Req 4.4).
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _coerce_evidence(value):
    """Coerce any evidence value to a list of strings, defaulting to [].

    Missing values, ``None``, and non-list types fall back to ``[]`` so the
    serialized shape always carries a list (Req 1.3, 1.5). List entries are
    stringified so the payload is always a list of strings.
    """
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def serialize_container(row, owner=None):
    """Map a repository/collector container dict to the API contract (Req 4.4).

    Always returns every CONTAINER_FIELDS key (missing values -> None / defaults)
    so the payload shape is stable for any input row.

    ``application_name`` is the compose project label value (or '' when absent;
    Req 1.2, 1.3). ``owner`` is passed in by the caller: ``None`` marks an
    Unowned_Container (Req 2.4); otherwise a ``{"user_id", "username"}`` dict
    (Req 2.2).
    """
    row = row or {}
    return {
        "server_id": row.get("server_id"),
        "server_name": row.get("server_name"),
        "container_id": row.get("container_id"),
        "name": row.get("name"),
        "image": row.get("image"),
        "state": row.get("state") or "unknown",
        "classification": row.get("classification") or "unclassified",
        "confidence_score": _coerce_confidence(row.get("confidence_score")),
        "classification_evidence": _coerce_evidence(row.get("classification_evidence")),
        "application_name": _coerce_application_name(row.get("labels")),
        "owner": owner,
    }


def build_payload(containers, errors=None):
    """Build the full API payload (Req 4.2, 4.5, 4.6, 4.7).

    containers: iterable of container dicts (any source).
    errors: list of {"server_id", "error"} for unreachable servers.
    Preserves input order and always returns the stable envelope shape.
    """
    return {
        "success": True,
        "containers": [serialize_container(c) for c in (containers or [])],
        "errors": list(errors or []),
    }


def list_stored(repository):
    """Default path: return the stored inventory from runtime_containers
    (Req 4.2, 4.5, 4.7). No SSH; aggregation across servers is inherent to
    the table (one row per server+container)."""
    return build_payload(repository.list_containers())


def scan_live(servers, collect, classify, owner_for=None):
    """Live path: discover + classify across every managed server, aggregating
    reachable containers and recording a per-server error for each unreachable
    server (Req 4.5, 4.6).

    servers: list of server dicts ({'id','server_ip','server_name', ...}).
    collect: callable(server) -> (observations, error|None)  (collector).
    classify: callable(observation) -> {'classification','score','evidence'}.
    owner_for: optional callable(merged) -> owner dict|None used to derive the
        per-container owner (Req 2.2, 2.4). When None, every container is
        serialized with owner=None (Unowned_Container).

    Serializes each container inside the loop (passing the derived owner) and
    assembles the envelope directly from the already-serialized list, so
    containers are not double-serialized. build_payload / list_stored are left
    untouched for the default path.
    """
    containers, errors = [], []
    for server in (servers or []):
        observations, error = collect(server)
        if error:
            errors.append({"server_id": server.get("id"), "error": error})
            continue  # no containers from an unreachable server (Req 4.6)
        containers.extend(
            _serialize_observations(server, observations, classify, owner_for)
        )
    return {"success": True, "containers": containers, "errors": errors}


def _serialize_observations(server, observations, classify, owner_for):
    """Classify + serialize one server's observations (shared by both scans).

    Factored out of :func:`scan_live` so the serial and parallel paths produce
    identical per-container output from the same inputs. Returns a list of
    serialized container dicts (empty when there are no observations).
    """
    serialized = []
    for obs in (observations or []):
        result = classify(obs)
        merged = dict(obs)
        merged["server_name"] = server.get("server_name")
        merged["classification"] = result["classification"]
        merged["confidence_score"] = result["score"]
        merged["classification_evidence"] = result.get("evidence", [])
        owner = owner_for(merged) if owner_for else None
        serialized.append(serialize_container(merged, owner=owner))
    return serialized


def scan_live_parallel(
    servers,
    collect,
    classify,
    owner_for=None,
    *,
    max_workers=SCAN_MAX_WORKERS_DEFAULT,
    per_server_deadline=SCAN_PER_SERVER_DEADLINE_DEFAULT,
    executor_factory=ThreadPoolExecutor,
):
    """Parallel live scan with a per-server deadline (Req 5.7, 5.9).

    Fans ``collect(server)`` out across a thread pool and waits on each future
    with ``future.result(timeout=per_server_deadline)`` so one slow or
    unreachable server costs at most ``per_server_deadline`` rather than
    serializing the whole scan. Reachable servers' containers are aggregated;
    every server that errors, times out, or raises contributes **no** containers
    and records a ``{"server_id", "error"}`` entry — exactly the serial error
    path's contract (Req 4.6). Results are aggregated in the input server order
    so the payload is deterministic regardless of completion order.

    servers: list of server dicts ({'id','server_ip','server_name', ...}).
    collect: callable(server) -> (observations, error|None)  (collector).
    classify: callable(observation) -> {'classification','score','evidence'}.
    owner_for: optional callable(merged) -> owner dict|None (Req 2.2, 2.4).
    max_workers: thread-pool size cap.
    per_server_deadline: wall-clock budget (seconds) for a single server's
        ``collect``; exceeding it records a per-server timeout error.
    executor_factory: injected so the fan-out/deadline/aggregation is unit-
        testable with a fake executor and a fake slow collector (no SSH).

    Returns the same envelope shape as :func:`scan_live`:
    ``{"success": True, "containers": [...], "errors": [...]}``.
    """
    server_list = list(servers or [])
    if not server_list:
        return {"success": True, "containers": [], "errors": []}

    # Keep each server's slot so results aggregate in input order regardless of
    # the order futures complete. Each slot holds (containers, error_or_None).
    results = [None] * len(server_list)
    workers = max(1, min(int(max_workers), len(server_list)))

    executor = executor_factory(max_workers=workers)
    try:
        futures = {}
        for index, server in enumerate(server_list):
            futures[executor.submit(collect, server)] = index

        for future, index in futures.items():
            server = server_list[index]
            try:
                observations, error = future.result(timeout=per_server_deadline)
            except Exception as exc:  # noqa: BLE001 - any failure -> per-server error
                # A timeout or collector exception for one server is isolated:
                # it contributes no containers and records a per-server error,
                # mirroring the serial unreachable-server path (Req 4.6).
                results[index] = ([], str(exc) or exc.__class__.__name__)
                continue

            if error:
                results[index] = ([], error)
                continue

            serialized = _serialize_observations(
                server, observations, classify, owner_for
            )
            results[index] = (serialized, None)
    finally:
        # Do not block on stragglers: a server still running past its deadline
        # must not extend the total wait (the whole point of the per-server
        # deadline, R5.7). Shut the pool down without waiting and cancel any
        # not-yet-started work. ``cancel_futures`` is Python 3.9+; fall back to
        # a plain non-blocking shutdown on older runtimes.
        try:
            executor.shutdown(wait=False, cancel_futures=True)
        except TypeError:  # pragma: no cover - Python < 3.9
            executor.shutdown(wait=False)

    containers, errors = [], []
    for index, server in enumerate(server_list):
        slot = results[index]
        if slot is None:
            # Defensive: a future that never produced a slot is treated as an
            # unreachable server rather than silently dropped.
            errors.append({"server_id": server.get("id"), "error": "no result"})
            continue
        slot_containers, slot_error = slot
        if slot_error:
            errors.append({"server_id": server.get("id"), "error": slot_error})
            continue
        containers.extend(slot_containers)

    return {"success": True, "containers": containers, "errors": errors}


def actuate(server_ip, container_ref, action, *, ssh=None, timeout=ACTUATE_TIMEOUT_DEFAULT):
    """Live start/stop/restart of a container on a managed server (Req 5.6, 5.9).

    Builds the docker argv for ``action`` and dispatches it through the injected
    ``ssh`` callable (defaulting to the hardened
    :func:`src.ssh_utils.ssh_execute_argv`). ``ssh`` is injected so the
    command-building and server-selection logic is unit-testable with a fake
    runner, without live Docker or SSH (R5.9).

    server_ip: IP address of the target server.
    container_ref: container id or name to act on.
    action: one of ``"start"``, ``"stop"``, ``"restart"``.
    ssh: callable(server_ip, argv, timeout=...) -> (success, stdout, stderr).
        Defaults to :func:`src.ssh_utils.ssh_execute_argv` (resolved lazily so
        importing this module never requires the SSH stack).
    timeout: per-command timeout (seconds).

    Returns the ``(success, stdout, stderr)`` tuple from ``ssh`` so callers get
    the same contract as the rest of the remote-execution surface.

    Raises ``ValueError`` for an unsupported action or a blank container
    reference so a bad request fails fast rather than building a broken argv.
    """
    if action not in _ACTUATE_ACTIONS:
        raise ValueError(
            f"Unsupported actuation action: {action!r} "
            f"(expected one of {_ACTUATE_ACTIONS})"
        )
    ref = (container_ref or "").strip() if isinstance(container_ref, str) else container_ref
    if not ref:
        raise ValueError("container_ref must be a non-empty container id or name")

    if ssh is None:
        from .ssh_utils import ssh_execute_argv as ssh  # lazy: no SSH import cost

    argv = ["docker", action, ref]
    return ssh(server_ip, argv, timeout=timeout)


def build_deployments_index(rows):
    """Build an in-memory owner index from deployment rows (Req 2.2, 2.3).

    rows: iterable of ``(user_id, username, application_name, deployment_path)``
    tuples (typically a ``deployments`` ⋈ ``users`` join, non-failed/error rows).

    Returns ``{"by_slug": {...}, "by_path": {...}}`` where each value maps to an
    owner dict ``{"user_id", "username"}``:

    - ``by_slug`` is keyed by the application slug
      (``application_name.lower().replace(" ", "-")``) — the same slug the deploy
      flow uses for the compose project name and the on-disk directory.
    - ``by_path`` is keyed by the normalized deployment path (trailing slash
      removed).

    Blank ``application_name`` and blank ``deployment_path`` are skipped so they
    never produce empty-string keys.
    """
    by_slug, by_path = {}, {}
    for user_id, username, app_name, path in (rows or []):
        owner = {"user_id": user_id, "username": username}
        if app_name:
            by_slug[app_name.lower().replace(" ", "-")] = owner
        if path:
            by_path[str(path).rstrip("/")] = owner
    return {"by_slug": by_slug, "by_path": by_path}


def _slugify(value):
    """Slugify an application name the same way the deploy flow does.

    Lower-cases and replaces spaces with hyphens so the result matches the
    ``by_slug`` keys built by :func:`build_deployments_index` (Req 2.3).
    """
    return value.strip().lower().replace(" ", "-")


def _match_by_path(workdir, by_path):
    """Map a compose working-directory to an owner via ``by_path`` (Req 2.3).

    ``workdir`` is the ``com.docker.compose.project.working_dir`` label value,
    present only when Compose sets it (external assumption). A direct hit on the
    normalized path wins; otherwise the parent ``{username}/{app-slug}`` tail of
    each indexed path is compared so a working_dir that equals (or ends with)
    that tail still resolves. Pure: returns ``None`` on any miss.
    """
    if not isinstance(workdir, str) or not workdir.strip():
        return None
    normalized = workdir.strip().rstrip("/")
    if not normalized:
        return None

    # Direct match on the full normalized deployment path.
    owner = by_path.get(normalized)
    if owner:
        return owner

    # Fall back to the parent `{username}/{app-slug}` tail of each indexed path:
    # a working_dir that ends with that two-segment tail resolves to the owner.
    for path, candidate in by_path.items():
        tail = "/".join(path.rstrip("/").split("/")[-2:])
        if tail and (normalized == tail or normalized.endswith("/" + tail)):
            return candidate
    return None


def _match_by_base_path(base_path, index):
    """Map a ``BASE_PATH`` env value to an owner (Req 2.2, 2.3).

    ``base_path`` is injected by the platform as ``/{user_name}/{app_name}/``
    using the RAW (unslugified) app name. The leading non-empty segment is the
    primary username signal and must corroborate against a known owner in the
    index; the app segment is slugified (``lower().replace(" ", "-")``) before
    the ``by_slug`` lookup. The username match is primary — the slugified app
    segment only corroborates. Pure: returns ``None`` on any miss.
    """
    if not isinstance(base_path, str) or not base_path.strip():
        return None
    segments = [seg for seg in base_path.split("/") if seg]
    if not segments:
        return None

    username = segments[0]

    # The slugified app segment corroborates against by_slug when present.
    if len(segments) >= 2:
        slug = _slugify(segments[1])
        owner = index["by_slug"].get(slug)
        if owner and owner.get("username") == username:
            return owner

    # Username is the primary signal: confirm it against known owners in the
    # index even when the app segment is absent or does not corroborate.
    for owner in index["by_slug"].values():
        if owner.get("username") == username:
            return owner
    for owner in index["by_path"].values():
        if owner.get("username") == username:
            return owner
    return None


def derive_owner(row, index):
    """Derive the owner of a container observation by source precedence.

    Tries three sources in order and returns the first match, else ``None``
    (Unowned_Container, Req 2.4). Slug matching is case-insensitive.

    1. Deployment path — the ``com.docker.compose.project.working_dir`` label
       matched against ``by_path`` (and the parent ``{username}/{app-slug}``
       tail). Present only when Compose sets it (Req 2.3).
    2. ``BASE_PATH`` env (``/{user_name}/{app_name}/`` with the RAW app name) —
       leading segment as the primary username signal, slugified app segment
       corroborating against ``by_slug`` (Req 2.2, 2.3).
    3. Compose project label (``com.docker.compose.project``) slug against
       ``by_slug`` (Req 2.3).
    """
    row = row or {}
    labels = row.get("labels") or {}
    env = row.get("env") or {}

    # 1. deployment path (working_dir label -> by_path / tail match)
    workdir = labels.get("com.docker.compose.project.working_dir")
    owner = _match_by_path(workdir, index["by_path"])
    if owner:
        return owner

    # 2. BASE_PATH env (/{user_name}/{app_name}/, RAW app name)
    owner = _match_by_base_path(env.get("BASE_PATH"), index)
    if owner:
        return owner

    # 3. compose project label -> slug -> by_slug
    project = labels.get("com.docker.compose.project")
    if isinstance(project, str) and project.strip():
        return index["by_slug"].get(_slugify(project))

    return None  # Unowned_Container (Req 2.4)
