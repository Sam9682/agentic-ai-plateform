"""Governance for the platform MCP server (finding F3).

Before Phase 2, ``src/mcp_interface.py`` executed every tool for whoever could
start the stdio process: no authentication, no tenant scoping, no policy
decision, no audit. Every tool call now goes through :meth:`McpGovernance.call`:

1. **Authentication** — the agent token in ``AGENTIC_MCP_TOKEN`` must carry the
   ``mcp:invoke`` scope. It is re-verified on every call, so revocation and
   quarantine take effect immediately. The agent and tenant come from the
   token, never from tool arguments.
2. **Tenant scoping** — tools taking a ``user_id`` refuse a user who is not a
   member of the agent's tenant (no cross-tenant operation by id).
3. **ABF assessment** — the tool arguments are matched (as inert text) against
   the deterministic rule catalogue; hits raise the PDP risk context and can
   only tighten the decision.
4. **Decision** — the existing :class:`McpGateway` validates parameters,
   rate-limits per (agent, tool), asks the PDP and records the invocation.
5. **Approval** — REQUIRE_APPROVAL creates an approval bound to the exact
   arguments, the agent and this MCP session; after an admin approves it, the
   same call in the same session consumes it once.

Unauthenticated calls are refused. ``MCP_ALLOW_UNAUTHENTICATED_READS=true``
restores the legacy behaviour for the read-only tools only (explicit opt-in,
logged in every result as ``"governance": "legacy-unauthenticated-read"``).
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Mapping, Optional

from . import rules as R
from ..obs import ingest_tokens
from ..zaf import policy_engine as pe
from ..zaf.mcp_gateway import McpGateway, RateLimiter

SERVER_NAME = "platform"
TOKEN_ENV = "AGENTIC_MCP_TOKEN"
SESSION_ENV = "AGENTIC_MCP_SESSION_ID"
LEGACY_READS_ENV = "MCP_ALLOW_UNAUTHENTICATED_READS"
_STRICTNESS = {"ALLOW": 0, "REQUIRE_APPROVAL": 1, "QUARANTINE": 2, "DENY": 3}

_STR = {"type": "string"}
_INT = {"type": "integer"}


@dataclass(frozen=True)
class ToolSpec:
    action: str
    read_only: bool
    user_scoped: bool = False
    schema: Dict[str, Any] = field(default_factory=dict)
    rate_limit_per_minute: int = 10


def _app_schema(extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    props = {"application_name": _STR, "user_id": _INT}
    props.update(extra or {})
    return {"required": sorted(["application_name", "user_id"] + list(extra or {})),
            "properties": props}


TOOLS: Mapping[str, ToolSpec] = {
    "list_applications": ToolSpec("mcp.platform.read.list_applications", True,
                                  rate_limit_per_minute=60),
    "list_users": ToolSpec("mcp.platform.read.list_users", True, rate_limit_per_minute=60),
    "ps": ToolSpec("mcp.platform.read.ps", True, True, _app_schema(), 60),
    "logs": ToolSpec("mcp.platform.read.logs", True, True, _app_schema(), 60),
    "add_application": ToolSpec(
        "mcp.platform.catalog.add_application", False,
        schema={"required": ["name", "url"],
                "properties": {"name": _STR, "url": _STR, "description": _STR}}),
    "deploy_template": ToolSpec(
        "mcp.platform.app.deploy_template", False, True,
        _app_schema({"template_id": _STR})),
    "start": ToolSpec("mcp.platform.app.start", False, True, _app_schema()),
    "stop": ToolSpec("mcp.platform.app.stop", False, True, _app_schema()),
    "backup": ToolSpec("mcp.platform.app.backup", False, True, _app_schema()),
    "restore": ToolSpec("mcp.platform.app.restore", False, True, _app_schema()),
    "modify_code": ToolSpec("mcp.platform.app.modify_code", False, True,
                            _app_schema({"instruction": _STR})),
    # Cross-tenant infrastructure inventory: not a tenant read, needs a grant.
    "agent_control_containers": ToolSpec(
        "mcp.platform.infra.agent_control_containers", False, rate_limit_per_minute=30),
}


def _default_is_member(tenant_id: int, user_id: Any) -> bool:
    if not isinstance(user_id, int) or isinstance(user_id, bool):
        return False
    from ..database_postgres import db_manager
    row = db_manager.execute_query(
        "SELECT 1 FROM tenant_members WHERE tenant_id = %s AND user_id = %s",
        (tenant_id, user_id), fetch_one=True)
    return bool(row)


def _truthy(v: Optional[str]) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")


class McpGovernance:
    def __init__(
        self,
        *,
        verify_token: Callable[..., Optional[Dict[str, Any]]] = ingest_tokens.verify,
        is_tenant_member: Callable[[int, Any], bool] = _default_is_member,
        firewall: Optional[Callable[[], Any]] = None,
        decide: Optional[Callable[..., Dict[str, Any]]] = None,
        consume_approval: Optional[Callable[..., Optional[int]]] = None,
        request_approval: Optional[Callable[..., Dict[str, Any]]] = None,
        events_repo: Any = None,
        env: Optional[Mapping[str, str]] = None,
        rate_limiter: Optional[RateLimiter] = None,
    ):
        self._verify = verify_token
        self._is_member = is_tenant_member
        self._firewall = firewall
        self._decide = decide
        self._consume = consume_approval
        self._request_approval = request_approval
        self._events = events_repo
        self._env = env if env is not None else os.environ
        self._rate = rate_limiter or RateLimiter()
        self.session_id = self._env.get(SESSION_ENV) or f"mcp-{uuid.uuid4().hex[:16]}"

    # Lazy collaborators keep the MCP server startable without a DB.
    def _fw(self):
        if self._firewall is not None:
            return self._firewall()
        from .firewall import get_firewall
        return get_firewall()

    def _pdp(self):
        if self._decide is not None:
            return self._decide
        from ..zaf import governance_service
        return governance_service.decide

    def _consumer(self):
        if self._consume is not None:
            return self._consume
        from ..zaf import approval_service
        return approval_service.consume_authorization

    def _requester(self):
        if self._request_approval is not None:
            return self._request_approval
        from ..zaf import approval_service
        return approval_service.request_approval

    def _events_repo(self):
        if self._events is not None:
            return self._events
        from ..aro import events_repository
        return events_repository

    # ------------------------------------------------------------------ call
    def call(self, tool_name: str, params: Dict[str, Any],
             impl: Callable[[Optional[Dict[str, Any]]], Any]) -> Any:
        """Run ``impl(ctx)`` only if every governance step allows it. Never raises."""
        spec = TOOLS.get(tool_name)
        if spec is None:
            return {"error": "unknown tool", "decision": pe.DENY}
        token = self._env.get(TOKEN_ENV)
        try:
            binding = self._verify(token, scope=ingest_tokens.SCOPE_MCP) if token else None
        except Exception:  # noqa: BLE001 - token store down: fail closed
            binding = None
        if binding is None:
            if spec.read_only and _truthy(self._env.get(LEGACY_READS_ENV)):
                result = impl(None)
                if isinstance(result, dict):
                    result = dict(result, governance="legacy-unauthenticated-read")
                return result
            return {"error": f"unauthenticated: set {TOKEN_ENV} to a valid agent token "
                             f"with scope {ingest_tokens.SCOPE_MCP}",
                    "decision": pe.DENY}

        tenant_id = binding["tenant_id"]
        agent_db_id = binding["agent_db_id"]
        identity = binding["agent_identity"]
        ctx = {"tenant_id": tenant_id, "agent_db_id": agent_db_id, "agent_identity": identity,
               "session_id": self.session_id}

        if spec.user_scoped:
            try:
                member = self._is_member(tenant_id, params.get("user_id"))
            except Exception:  # noqa: BLE001
                member = False
            if not member:
                self._emit(tenant_id, identity, tool_name, pe.DENY,
                           "user_id is not a member of the agent's tenant")
                return {"error": "user_id is not a member of the agent's tenant",
                        "decision": pe.DENY}

        try:
            fw = self._fw()
            view = R.ActionView(category="MCP", action=tool_name,
                                resource=f"{SERVER_NAME}:{tool_name}",
                                text=R.text_from_metadata({"args": list(params.values())}),
                                tenant_slug=_slug(identity))
            hits, _risk, floor, abf_ctx = fw.assess(tenant_id, agent_db_id, view)
        except Exception:  # noqa: BLE001 - rules unavailable: fail closed for mutations
            if not spec.read_only:
                return {"error": "firewall unavailable (fail closed)", "decision": pe.DENY}
            fw, hits, floor, abf_ctx = None, [], "ALLOW", {}

        pdp = self._pdp()

        def decide_with_floor(*args, **kwargs):
            d = dict(pdp(*args, **kwargs))
            if _STRICTNESS.get(floor, 0) > _STRICTNESS.get(d.get("decision"), 3):
                d["decision"] = floor
                d["reason"] = f"ABF rule floor {floor}"
            return d

        gateway = McpGateway(
            tool_resolver=lambda _t, _s, name: {
                "canonical_action": spec.action, "param_schema": spec.schema,
                "rate_limit_per_minute": spec.rate_limit_per_minute, "enabled": True},
            tool_invoker=lambda _s, _n, _p: impl(ctx),
            decide=decide_with_floor,
            approval_consumer=self._consumer(),
            rate_limiter=self._rate,
            events_repo=self._events_repo(),
        )
        try:
            res = gateway.invoke(tenant_id, SERVER_NAME, tool_name, params,
                                 agent_identity=identity, agent_db_id=agent_db_id,
                                 context={**abf_ctx, "session_id": self.session_id})
        except Exception:  # noqa: BLE001 - PDP / audit unavailable: fail closed
            return {"error": "policy decision unavailable (fail closed)", "decision": pe.DENY}

        if hits and fw is not None:
            try:
                fw.enforce_hits(tenant_id, agent_db_id, identity, hits, pre_execution=True,
                                trace_id=None, session_id=self.session_id,
                                dedupe_suffix=f"mcp:{tool_name}:{self.session_id}")
            except Exception:  # noqa: BLE001
                pass

        if res.allowed:
            return res.result
        if res.decision == pe.REQUIRE_APPROVAL:
            try:
                approval = self._requester()(
                    tenant_id, spec.action, params=params, agent_identity=identity,
                    resource=f"{SERVER_NAME}:{tool_name}", session_id=self.session_id,
                    risk_explanation="; ".join(h.inference for h in hits) or res.reason,
                    triggering_policy={"abf_rules": [h.rule_id for h in hits]},
                    events_repo=self._events_repo())
            except Exception:  # noqa: BLE001
                approval = None
            return {"error": "approval required", "decision": pe.REQUIRE_APPROVAL,
                    "approval_id": (approval or {}).get("id"),
                    "hint": "retry the same call in this session once an admin approves it"}
        out = {"error": res.reason or "denied", "decision": res.decision}
        if res.status_code == 429:
            out["error"] = "rate limit exceeded"
        return out

    def _emit(self, tenant_id, identity, tool_name, decision, reason):
        try:
            from ..aro import event_service as es
            es.emit(self._events_repo(), tenant_id, "mcp.tool.invocation", "zaf-mcp-gateway",
                    agent_id=identity,
                    action={"tool": f"{SERVER_NAME}:{tool_name}", "reason": reason},
                    decision=decision, severity="HIGH")
        except Exception:  # noqa: BLE001
            pass


def _slug(identity: Optional[str]) -> Optional[str]:
    if identity and identity.startswith("agent://"):
        return identity[len("agent://"):].split("/", 1)[0] or None
    return None


_GOVERNANCE: Optional[McpGovernance] = None


def get_governance() -> McpGovernance:
    global _GOVERNANCE
    if _GOVERNANCE is None:
        _GOVERNANCE = McpGovernance()
    return _GOVERNANCE
