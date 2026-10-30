"""Governed MCP gateway (Task 13) — ZAF enforcement point 1.

Every agent MCP tool invocation is mediated here: the gateway authenticates the
agent (scoped token), resolves the tool to a canonical action, evaluates it
through the PDP, validates parameters, enforces a per-tool rate limit, honors
REQUIRE_APPROVAL (blocking until an approval exists), blocks unauthorized tools,
and records the invocation + result as events. Only when the decision is ALLOW
(or an approval authorizes a REQUIRE_APPROVAL action) is the underlying tool
actually invoked.

The core (:class:`McpGateway`) depends on injected collaborators (a tool
resolver, the governance ``decide`` function, an approval authorizer, a rate
limiter and the tool invoker) so it is fully unit-testable without a live DB or
a real MCP server. Direct agent->MCP connections that skip this gateway are a
documented reduced-governance mode.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Any, Callable, Deque, Dict, Optional, Tuple

from . import governance_service as gov
from . import policy_engine as pe
from ..aro import event_service as es


class RateLimiter:
    """Simple in-process sliding-window rate limiter keyed by (agent, tool)."""

    def __init__(self):
        self._hits: Dict[Tuple[str, str], Deque[float]] = defaultdict(deque)

    def allow(self, key: Tuple[str, str], limit_per_minute: int, now: Optional[float] = None) -> bool:
        now = now if now is not None else time.monotonic()
        window = 60.0
        dq = self._hits[key]
        while dq and dq[0] <= now - window:
            dq.popleft()
        if len(dq) >= max(1, int(limit_per_minute)):
            return False
        dq.append(now)
        return True


class GatewayResult:
    """Outcome of a gateway invocation."""

    def __init__(self, allowed: bool, decision: str, reason: str,
                 result: Any = None, status_code: int = 200):
        self.allowed = allowed
        self.decision = decision
        self.reason = reason
        self.result = result
        self.status_code = status_code

    def as_dict(self) -> Dict[str, Any]:
        return {
            "allowed": self.allowed,
            "decision": self.decision,
            "reason": self.reason,
            "result": self.result,
            "status_code": self.status_code,
        }


def validate_params(param_schema: Dict[str, Any], params: Dict[str, Any]) -> Optional[str]:
    """Validate params against a minimal schema. Returns an error string or None.

    Schema shape: ``{"required": ["a", "b"], "properties": {"a": {"type": "string"}}}``
    Only presence of required keys and primitive type checks are enforced — enough
    to block malformed/injected tool parameters at the boundary.
    """
    required = param_schema.get("required", []) or []
    for key in required:
        if key not in params:
            return f"missing required parameter: {key}"
    props = param_schema.get("properties", {}) or {}
    type_map = {"string": str, "integer": int, "number": (int, float),
                "boolean": bool, "object": dict, "array": list}
    for key, spec in props.items():
        if key in params and "type" in spec:
            expected = type_map.get(spec["type"])
            if expected and not isinstance(params[key], expected):
                return f"parameter {key} must be of type {spec['type']}"
    return None


class McpGateway:
    """Mediates MCP tool invocations with ZAF enforcement."""

    def __init__(
        self,
        *,
        tool_resolver: Callable[[int, str, str], Optional[Dict[str, Any]]],
        tool_invoker: Callable[[str, str, Dict[str, Any]], Any],
        decide: Callable[..., Dict[str, Any]] = gov.decide,
        approval_authorizer: Optional[Callable[[int, str, Dict[str, Any]], bool]] = None,
        rate_limiter: Optional[RateLimiter] = None,
        events_repo=None,
    ):
        self._resolve = tool_resolver
        self._invoke = tool_invoker
        self._decide = decide
        self._authorized = approval_authorizer
        self._rate = rate_limiter or RateLimiter()
        if events_repo is None:
            from ..aro import events_repository as _er
            events_repo = _er
        self._events = events_repo

    def invoke(
        self,
        tenant_id: int,
        server_name: str,
        tool_name: str,
        params: Dict[str, Any],
        *,
        agent_identity: Optional[str] = None,
        agent_db_id: Optional[int] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> GatewayResult:
        """Mediate one tool invocation end-to-end."""
        tool = self._resolve(tenant_id, server_name, tool_name)
        if tool is None or not tool.get("enabled", True):
            self._emit(tenant_id, agent_identity, server_name, tool_name,
                       "DENY", "unknown or disabled tool")
            return GatewayResult(False, pe.DENY, "unknown or disabled tool", status_code=404)

        # Parameter validation (block malformed/injected params).
        err = validate_params(tool.get("param_schema") or {}, params or {})
        if err:
            self._emit(tenant_id, agent_identity, server_name, tool_name, "DENY", err)
            return GatewayResult(False, pe.DENY, err, status_code=400)

        # Rate limiting per (agent, tool).
        key = (agent_identity or "anonymous", f"{server_name}:{tool_name}")
        if not self._rate.allow(key, tool.get("rate_limit_per_minute", 60)):
            self._emit(tenant_id, agent_identity, server_name, tool_name,
                       "DENY", "rate limit exceeded")
            return GatewayResult(False, pe.DENY, "rate limit exceeded", status_code=429)

        action = tool["canonical_action"]
        decision = self._decide(
            tenant_id, action, agent_db_id=agent_db_id, agent_identity=agent_identity,
            resource=f"{server_name}:{tool_name}", params=params, context=context or {},
        )
        verdict = decision["decision"]

        if verdict == pe.ALLOW:
            return self._run(tenant_id, agent_identity, server_name, tool_name, params, decision)

        if verdict == pe.REQUIRE_APPROVAL:
            authorized = (
                self._authorized(tenant_id, action, params)
                if self._authorized is not None else False
            )
            if authorized:
                return self._run(tenant_id, agent_identity, server_name, tool_name, params, decision)
            return GatewayResult(False, pe.REQUIRE_APPROVAL,
                                 "approval required and not yet granted", status_code=202)

        # DENY / QUARANTINE -> blocked.
        return GatewayResult(False, verdict, decision.get("reason", "blocked"), status_code=403)

    def _run(self, tenant_id, agent_identity, server_name, tool_name, params, decision) -> GatewayResult:
        try:
            result = self._invoke(server_name, tool_name, params)
        except Exception as exc:  # noqa: BLE001 - never raise across the boundary
            self._emit(tenant_id, agent_identity, server_name, tool_name,
                       "ALLOW", f"tool error: {exc}", severity="MEDIUM")
            return GatewayResult(False, pe.ALLOW, f"tool error: {exc}",
                                 result={"error": str(exc)}, status_code=500)
        self._emit(tenant_id, agent_identity, server_name, tool_name, "ALLOW", "invoked")
        return GatewayResult(True, pe.ALLOW, "invoked", result=result, status_code=200)

    def _emit(self, tenant_id, agent_identity, server_name, tool_name, decision, reason,
              severity="INFO"):
        es.emit(
            self._events, tenant_id, "mcp.tool.invocation", "zaf-mcp-gateway",
            agent_id=agent_identity,
            action={"tool": f"{server_name}:{tool_name}", "reason": reason},
            decision=decision, severity=severity,
        )
