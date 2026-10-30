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

from typing import Any, Dict, List, Tuple

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
