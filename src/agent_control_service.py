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
)


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


def serialize_container(row):
    """Map a repository/collector container dict to the API contract (Req 4.4).

    Always returns every CONTAINER_FIELDS key (missing values -> None / defaults)
    so the payload shape is stable for any input row.
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


def scan_live(servers, collect, classify):
    """Live path: discover + classify across every managed server, aggregating
    reachable containers and recording a per-server error for each unreachable
    server (Req 4.5, 4.6).

    servers: list of server dicts ({'id','server_ip','server_name', ...}).
    collect: callable(server) -> (observations, error|None)  (collector).
    classify: callable(observation) -> {'classification','score','evidence'}.
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
            containers.append(merged)
    return build_payload(containers, errors)
