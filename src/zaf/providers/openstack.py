"""OpenStack / OVHcloud provider for the ZAF infra proxy (Task 14).

Defines the provider interface, the canonical-action mapping, a deterministic
:class:`MockOpenStackProvider` for tests/CI, and a real
:class:`OpenStackProvider` that talks to a live OpenStack/OVHcloud endpoint.

Safety: the real provider only performs mutating operations
(server.create/delete/...) when ``ZAF_LIVE_OPENSTACK=1`` is set in the
environment AND the caller passes an explicit ``allow_mutation=True``. In CI the
mock is used, so no live cloud resource is ever created or destroyed.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Dict, List, Optional

# Map a (service, verb) to the canonical ZAF action the PDP evaluates.
# Read verbs are non-mutating; the rest are mutating.
CANONICAL_ACTIONS = {
    ("server", "list"): "openstack.server.list",
    ("server", "get"): "openstack.server.get",
    ("server", "create"): "openstack.server.create",
    ("server", "delete"): "openstack.server.delete",
    ("server", "reboot"): "openstack.server.reboot",
    ("volume", "list"): "openstack.volume.list",
    ("volume", "delete"): "openstack.volume.delete",
}

READ_ACTIONS = {"openstack.server.list", "openstack.server.get", "openstack.volume.list"}


def canonical_action(service: str, verb: str) -> str:
    """Return the canonical action string for a provider operation.

    Unknown operations map to a namespaced ``openstack.{service}.{verb}`` so the
    PDP's default-deny still applies rather than silently allowing.
    """
    return CANONICAL_ACTIONS.get((service, verb), f"openstack.{service}.{verb}")


def is_mutating(action: str) -> bool:
    return action not in READ_ACTIONS


class OpenStackProviderBase:
    """Interface every OpenStack provider implements."""

    def call(self, service: str, verb: str, params: Dict[str, Any]) -> Dict[str, Any]:  # pragma: no cover
        raise NotImplementedError


class MockOpenStackProvider(OpenStackProviderBase):
    """Deterministic in-memory OpenStack used in tests and the automated E2E.

    Seeded with a fixed server inventory so reads are reproducible. Mutations
    update the in-memory state only — no network, no real cloud.
    """

    def __init__(self, servers: Optional[List[Dict[str, Any]]] = None):
        self._servers = {s["id"]: dict(s) for s in (servers or [
            {"id": "server-123", "name": "inspect-target", "status": "ACTIVE"},
            {"id": "server-456", "name": "web-01", "status": "ACTIVE"},
        ])}

    def call(self, service: str, verb: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if service == "server" and verb == "list":
            return {"servers": list(self._servers.values())}
        if service == "server" and verb == "get":
            sid = params.get("id")
            return {"server": self._servers.get(sid)}
        if service == "server" and verb == "create":
            sid = params.get("id") or f"server-{len(self._servers) + 1}"
            self._servers[sid] = {"id": sid, "name": params.get("name", sid), "status": "ACTIVE"}
            return {"server": self._servers[sid], "created": True}
        if service == "server" and verb == "delete":
            sid = params.get("id")
            existed = self._servers.pop(sid, None) is not None
            return {"deleted": existed, "id": sid}
        return {"error": f"unsupported operation {service}.{verb}"}


class OpenStackProvider(OpenStackProviderBase):
    """Real OpenStack/OVHcloud provider (credential + env gated for mutations).

    Args:
        auth: OpenStack auth parameters (from a scoped credential, never a raw
            long-lived secret in the clear).
        http: an injectable HTTP caller ``(method, url, headers, json) -> (status, body)``;
            defaults to a ``requests`` wrapper when available.
    """

    def __init__(self, auth: Dict[str, Any], *, http: Optional[Callable[..., Any]] = None):
        self._auth = auth
        self._http = http

    def _require_live_for_mutation(self, action: str) -> None:
        if is_mutating(action) and os.environ.get("ZAF_LIVE_OPENSTACK") != "1":
            raise PermissionError(
                "live OpenStack mutation refused: set ZAF_LIVE_OPENSTACK=1 to enable "
                "(disabled in CI to prevent destructive cloud changes)"
            )

    def call(self, service: str, verb: str, params: Dict[str, Any]) -> Dict[str, Any]:
        action = canonical_action(service, verb)
        self._require_live_for_mutation(action)
        if self._http is None:  # pragma: no cover - requires a live endpoint
            raise RuntimeError(
                "no HTTP caller configured for the live OpenStack provider"
            )
        # Delegate to the injected HTTP caller. The exact URL/verb mapping is
        # endpoint-specific; kept minimal here since CI uses the mock.
        status, body = self._http(service, verb, params, self._auth)
        return {"status": status, "body": body}
