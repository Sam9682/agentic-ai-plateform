"""Surface-agnostic validation for the agent runtime registry (Task 4).

Pure logic for validating and normalizing a runtime definition before it is
persisted, with no Flask/DB dependency (mirrors ``agent_control_service.py``).
Enforces the SRS security constraints at registration time:

* Versions must be pinned (no ``latest`` / empty).
* The platform must not auto-run arbitrary install scripts: an ``install_method``
  of kind ``script`` with inline shell is rejected; package/image installs must
  carry integrity material (a sha256 / digest) so installation can be verified.
* Protocols are constrained to the set the adapters implement.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

SUPPORTED_PROTOCOLS = {"acp", "cli", "http", "sse", "mcp"}
ALLOWED_INSTALL_KINDS = {"pip", "npm", "binary", "image"}


class RuntimeValidationError(ValueError):
    """Raised when a runtime definition violates a registration constraint."""


def _is_pinned(version: str) -> bool:
    v = (version or "").strip().lower()
    return bool(v) and v not in ("latest", "*", "head", "main", "master")


def validate_definition(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Validate + normalize a runtime definition. Raises on any violation.

    Returns a normalized dict with every registry field present and defaulted,
    ready for the repository. Rejects unpinned versions, unknown protocols, and
    install methods that would execute arbitrary scripts or lack integrity
    verification.
    """
    if not isinstance(payload, dict):
        raise RuntimeValidationError("runtime definition must be an object")

    identifier = (payload.get("identifier") or "").strip()
    name = (payload.get("name") or "").strip()
    version = (payload.get("version") or "").strip()
    if not identifier:
        raise RuntimeValidationError("identifier is required")
    if not name:
        raise RuntimeValidationError("name is required")
    if not _is_pinned(version):
        raise RuntimeValidationError(
            "version must be pinned (not 'latest'/'*'/empty)"
        )

    protocols = payload.get("supported_protocols") or []
    if not isinstance(protocols, list) or not protocols:
        raise RuntimeValidationError("supported_protocols must be a non-empty list")
    unknown = {p for p in protocols if p not in SUPPORTED_PROTOCOLS}
    if unknown:
        raise RuntimeValidationError(f"unsupported protocol(s): {sorted(unknown)}")

    install_method = payload.get("install_method") or {}
    if install_method:
        _validate_install_method(install_method)

    return {
        "identifier": identifier,
        "name": name,
        "version": version,
        "vendor": payload.get("vendor"),
        "install_source": payload.get("install_source"),
        "install_method": install_method,
        "supported_protocols": list(protocols),
        "dependencies": list(payload.get("dependencies") or []),
        "required_permissions": list(payload.get("required_permissions") or []),
        "execution_modes": list(payload.get("execution_modes") or []),
        "health_check": payload.get("health_check") or {},
        "config_schema": payload.get("config_schema") or {},
    }


def resolve_adapter_kind(definition: Dict[str, Any]) -> str:
    """Resolve the launchable adapter kind for a runtime definition (Req 5.1).

    Pure resolver: inspects ``definition["supported_protocols"]`` and returns the
    first protocol present using a deterministic precedence of
    ``("acp", "mcp", "http", "sse", "cli")``. Raises ``RuntimeValidationError``
    when the definition declares no launchable protocol.

    This performs no validation beyond protocol selection and does not touch the
    factory wiring (handled separately); it is safe to call on an
    already-validated definition.
    """
    protocols = definition.get("supported_protocols") or []
    for protocol in ("acp", "mcp", "http", "sse", "cli"):
        if protocol in protocols:
            return protocol
    raise RuntimeValidationError("no launchable protocol in definition")


# --------------------------------------------------------------------------- #
# protocol -> concrete adapter factory (Task 8.1, Req 5.1, 5.2)
# --------------------------------------------------------------------------- #
#
# ``resolve_adapter_kind`` (above) is a pure resolver returning one of
# ``acp / mcp / http / sse / cli``. The thin factory below binds that kind to a
# concrete :class:`~src.aro.adapters.base.AgentRuntimeAdapter` implementation:
#
#     mcp        -> McpAdapter          (adapters/mcp_adapter.py)
#     acp        -> KiroAcpAdapter      (adapters/kiro_acp.py)
#     cli        -> ShaiCliAdapter      (adapters/shai_cli.py)
#     http / sse -> ShaiHttpSseAdapter  (adapters/shai_http_sse.py)
#
# This is the "thin factory in the service/lifecycle layer" described in
# design.md §5.1. It exists so the lifecycle ``adapter_for(agent)`` callable can
# build the right adapter for a runtime definition, which is what finally makes
# a ``protocol: mcp`` registration *launchable* (AC 5.2) — the registry already
# accepted ``mcp`` at registration time but had no way to construct an adapter
# for it.
#
# The adapter modules pull in subprocess / ssh_utils machinery, so they are
# imported lazily inside the factory rather than at module import time. This
# keeps ``resolve_adapter_kind`` and ``validate_definition`` pure and
# dependency-free for callers (and tests) that only need validation/resolution.

# Constructors differ per adapter; this maps each adapter kind to the runtime
# context keys it accepts beyond the leading positional argument, so callers can
# pass a single ``**runtime_context`` bag and the factory forwards only the keys
# each adapter understands.
_STDIO_CONTEXT_KEYS = ("server_ip", "version", "read_timeout", "popen",
                       "transport_factory", "remote_exec")
_ACP_CONTEXT_KEYS = ("server_ip", "version", "sha256", "transport_factory",
                     "remote_exec", "read_timeout", "cancel_ack_timeout")
_CLI_CONTEXT_KEYS = ("server_ip", "version", "agent_config", "popen", "remote_exec")
_HTTP_CONTEXT_KEYS = ("api_token", "supports_cancel", "terminal_events", "error_events")


def _filtered(context: Dict[str, Any], keys: Tuple[str, ...]) -> Dict[str, Any]:
    """Keep only the context entries a given adapter constructor accepts."""
    return {k: context[k] for k in keys if k in context and context[k] is not None}


def resolve_adapter(
    definition: Dict[str, Any],
    container_ref: Optional[str] = None,
    **runtime_context: Any,
):
    """Build the concrete runtime adapter for a runtime ``definition`` (Req 5.1, 5.2).

    Resolves the launchable kind via :func:`resolve_adapter_kind`, then
    constructs the matching :class:`AgentRuntimeAdapter` subclass. ``container_ref``
    is the agent container name/id the stdio/CLI adapters run their subprocess in
    (required for ``mcp`` / ``acp`` / ``cli``). The HTTP/SSE adapter instead
    needs a ``base_url`` and ``http_client`` supplied via ``runtime_context``.

    Extra keyword arguments (e.g. ``server_ip``, ``version``, ``read_timeout``,
    ``server_cmd``, ``sha256``, ``agent_config``, ``base_url``, ``http_client``,
    ``api_token``) are forwarded to the chosen adapter's constructor; only the
    keys a given adapter accepts are passed through, so a single shared context
    bag is safe to hand to this factory.

    Raises :class:`RuntimeValidationError` when the definition declares no
    launchable protocol (propagated from :func:`resolve_adapter_kind`).
    """
    kind = resolve_adapter_kind(definition)

    if kind == "mcp":
        from .adapters.mcp_adapter import McpAdapter
        if container_ref is None:
            raise RuntimeValidationError("mcp adapter requires a container_ref")
        kwargs = _filtered(runtime_context, _STDIO_CONTEXT_KEYS)
        server_cmd = runtime_context.get("server_cmd")
        if server_cmd is not None:
            kwargs["server_cmd"] = server_cmd
        return McpAdapter(container_ref, **kwargs)

    if kind == "acp":
        from .adapters.kiro_acp import KiroAcpAdapter
        if container_ref is None:
            raise RuntimeValidationError("acp adapter requires a container_ref")
        return KiroAcpAdapter(container_ref, **_filtered(runtime_context, _ACP_CONTEXT_KEYS))

    if kind == "cli":
        from .adapters.shai_cli import ShaiCliAdapter
        if container_ref is None:
            raise RuntimeValidationError("cli adapter requires a container_ref")
        return ShaiCliAdapter(container_ref, **_filtered(runtime_context, _CLI_CONTEXT_KEYS))

    # http / sse share the SHAI HTTP/SSE adapter (SSE is HTTP's event transport).
    if kind in ("http", "sse"):
        from .adapters.shai_http_sse import ShaiHttpSseAdapter
        base_url = runtime_context.get("base_url")
        http_client = runtime_context.get("http_client")
        if not base_url or http_client is None:
            raise RuntimeValidationError(
                "http/sse adapter requires 'base_url' and 'http_client' in runtime_context"
            )
        return ShaiHttpSseAdapter(
            base_url, http_client, **_filtered(runtime_context, _HTTP_CONTEXT_KEYS)
        )

    # resolve_adapter_kind only ever returns a kind handled above; this guards
    # against the precedence list and this factory drifting out of sync.
    raise RuntimeValidationError(f"no adapter bound for kind: {kind}")  # pragma: no cover


def make_adapter_for(
    definition: Dict[str, Any],
    *,
    container_ref_of: Optional[Callable[[Dict[str, Any]], Optional[str]]] = None,
    **runtime_context: Any,
) -> Callable[[Dict[str, Any]], Any]:
    """Return an ``adapter_for(agent)`` callable bound to ``definition``.

    This adapts :func:`resolve_adapter` to the shape the lifecycle service and
    task worker expect (``adapter_for: callable(agent) -> AgentRuntimeAdapter``).
    ``container_ref_of`` derives the per-agent container reference from the agent
    dict (defaults to the agent's ``container_id`` / ``identity``); any remaining
    ``runtime_context`` is forwarded to :func:`resolve_adapter`.

    So wiring ``LifecycleService(adapter_for=make_adapter_for(defn, ...))`` makes
    a ``protocol: mcp`` runtime resolve to :class:`McpAdapter` and launch through
    it (AC 5.2).
    """
    def _container_ref(agent: Dict[str, Any]) -> Optional[str]:
        if container_ref_of is not None:
            return container_ref_of(agent)
        return agent.get("container_id") or agent.get("container_ref") or agent.get("identity")

    def adapter_for(agent: Dict[str, Any]):
        return resolve_adapter(definition, _container_ref(agent), **runtime_context)

    return adapter_for


def _validate_install_method(install_method: Dict[str, Any]) -> None:
    """Enforce integrity + no-arbitrary-script rules on an install method."""
    if not isinstance(install_method, dict):
        raise RuntimeValidationError("install_method must be an object")
    kind = (install_method.get("kind") or "").strip().lower()
    if kind not in ALLOWED_INSTALL_KINDS:
        raise RuntimeValidationError(
            f"install_method.kind must be one of {sorted(ALLOWED_INSTALL_KINDS)}; "
            "arbitrary install scripts are not permitted"
        )
    # Require integrity material so installation can be verified (SRS §3.1).
    integrity = install_method.get("sha256") or install_method.get("digest")
    if not integrity:
        raise RuntimeValidationError(
            "install_method must carry integrity material (sha256 or digest)"
        )


def validate_many(payloads: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Validate a batch, returning (normalized_ok, error_messages)."""
    ok: List[Dict[str, Any]] = []
    errors: List[str] = []
    for p in payloads or []:
        try:
            ok.append(validate_definition(p))
        except RuntimeValidationError as exc:
            errors.append(str(exc))
    return ok, errors
