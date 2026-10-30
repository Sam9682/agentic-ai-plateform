"""Agent Control aggregation/serialization logic (surface-agnostic).

Holds the pure logic the Agent_Control_API exposes so it is unit- and
property-testable without Flask: serialize discovered containers to the
API contract and aggregate across managed servers with per-server error
indicators. Mirrors the surface-agnostic style of TemplateDeployService /
SandboxManager.
"""

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
        for obs in (observations or []):
            result = classify(obs)
            merged = dict(obs)
            merged["server_name"] = server.get("server_name")
            merged["classification"] = result["classification"]
            merged["confidence_score"] = result["score"]
            merged["classification_evidence"] = result.get("evidence", [])
            owner = owner_for(merged) if owner_for else None
            containers.append(serialize_container(merged, owner=owner))
    return {"success": True, "containers": containers, "errors": errors}


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
