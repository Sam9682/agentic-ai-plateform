"""Infrastructure API proxy (Task 14) — ZAF enforcement point 2.

All agent infrastructure egress is forced through this proxy (agents have no
direct cloud network path; their container egress is locked to this proxy by the
execution manager). The proxy:

* maps every call to a canonical action (independent of what the agent reports),
* evaluates it through the PDP (fail-closed),
* for REQUIRE_APPROVAL, blocks unless an approval authorizes the exact
  action+params,
* mints a short-lived scoped token from the credential vault for the call,
* invokes the provider, and audits the attempt + outcome.

This gives the "hard guarantee": a server delete is authorized here even if a
compromised agent claims it only listed servers.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from . import governance_service as gov
from . import policy_engine as pe
from .providers import openstack as os_provider
from ..aro import event_service as es


class InfraProxyResult:
    def __init__(self, allowed: bool, decision: str, reason: str,
                 result: Any = None, status_code: int = 200):
        self.allowed = allowed
        self.decision = decision
        self.reason = reason
        self.result = result
        self.status_code = status_code

    def as_dict(self) -> Dict[str, Any]:
        return {
            "allowed": self.allowed, "decision": self.decision, "reason": self.reason,
            "result": self.result, "status_code": self.status_code,
        }


class InfraProxy:
    """Mediates infrastructure operations for a single provider family."""

    def __init__(
        self,
        provider: os_provider.OpenStackProviderBase,
        *,
        decide: Callable[..., Dict[str, Any]] = gov.decide,
        approval_authorizer: Optional[Callable[[int, str, Dict[str, Any]], bool]] = None,
        token_minter: Optional[Callable[..., Dict[str, Any]]] = None,
        events_repo=None,
    ):
        self._provider = provider
        self._decide = decide
        self._authorized = approval_authorizer
        self._mint = token_minter
        if events_repo is None:
            from ..aro import events_repository as _er
            events_repo = _er
        self._events = events_repo

    def call(
        self,
        tenant_id: int,
        service: str,
        verb: str,
        params: Dict[str, Any],
        *,
        agent_identity: Optional[str] = None,
        agent_db_id: Optional[int] = None,
        credential_id: Optional[int] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> InfraProxyResult:
        action = os_provider.canonical_action(service, verb)
        resource = params.get("id") or params.get("name")

        decision = self._decide(
            tenant_id, action, agent_db_id=agent_db_id, agent_identity=agent_identity,
            resource=resource, params=params, context=context or {},
        )
        verdict = decision["decision"]

        if verdict == pe.ALLOW:
            return self._run(tenant_id, service, verb, params, agent_identity, action, credential_id)

        if verdict == pe.REQUIRE_APPROVAL:
            authorized = (
                self._authorized(tenant_id, action, params)
                if self._authorized is not None else False
            )
            if authorized:
                return self._run(tenant_id, service, verb, params, agent_identity, action, credential_id)
            self._emit(tenant_id, agent_identity, action, resource,
                       pe.REQUIRE_APPROVAL, "approval required")
            return InfraProxyResult(False, pe.REQUIRE_APPROVAL,
                                    "approval required and not yet granted", status_code=202)

        self._emit(tenant_id, agent_identity, action, resource, verdict,
                   decision.get("reason", "blocked"), severity="HIGH")
        return InfraProxyResult(False, verdict, decision.get("reason", "blocked"), status_code=403)

    def _run(self, tenant_id, service, verb, params, agent_identity, action, credential_id) -> InfraProxyResult:
        # Mint a short-lived scoped token for this call (least privilege).
        if self._mint is not None and credential_id is not None:
            try:
                self._mint(tenant_id, credential_id, action, ttl_seconds=120, agent_id=agent_identity)
            except Exception as exc:  # noqa: BLE001 - fail closed on credential failure
                self._emit(tenant_id, agent_identity, action, params.get("id"),
                           pe.DENY, f"credential error: {exc}", severity="HIGH")
                return InfraProxyResult(False, pe.DENY, "credential unavailable", status_code=403)
        try:
            result = self._provider.call(service, verb, params)
        except PermissionError as exc:
            # Live-mutation guard tripped (ZAF_LIVE_OPENSTACK not set).
            self._emit(tenant_id, agent_identity, action, params.get("id"),
                       pe.DENY, str(exc), severity="HIGH")
            return InfraProxyResult(False, pe.DENY, str(exc), status_code=403)
        except Exception as exc:  # noqa: BLE001
            self._emit(tenant_id, agent_identity, action, params.get("id"),
                       pe.ALLOW, f"provider error: {exc}", severity="MEDIUM")
            return InfraProxyResult(False, pe.ALLOW, f"provider error: {exc}",
                                    result={"error": str(exc)}, status_code=502)
        self._emit(tenant_id, agent_identity, action, params.get("id"), pe.ALLOW, "executed")
        return InfraProxyResult(True, pe.ALLOW, "executed", result=result, status_code=200)

    def _emit(self, tenant_id, agent_identity, action, resource, decision, reason, severity="INFO"):
        es.emit(
            self._events, tenant_id, "infra.api.call", "zaf-infra-proxy",
            agent_id=agent_identity,
            action={"action": action, "resource": resource, "reason": reason},
            decision=decision, severity=severity,
        )
