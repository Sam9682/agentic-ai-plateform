"""Shared ZAF enforcement primitives (Phase 3, Task 6.1).

This module owns the thin, dependency-injected glue that turns the VERIFIED
Policy Decision Point (``governance_service.decide`` over the pure
``policy_engine``) and the approval authorizer (``approval_service.is_authorized``)
into the three seam callables the live ARO flow already runs:

* ``pre_transition`` — consulted by ``LifecycleService.transition``
* ``egress``         — consulted by ``execution_manager.launch``
* ``exec``           — consulted by ``agent_worker.execute_claimed_task``

The guiding constraint is **wiring, not rewriting**: the PDP and approval
service are reused behind their existing interfaces and are never re-implemented
here. This module imports only ``governance_service`` / ``approval_service`` /
``policy_engine`` / ``event_service`` — never an LLM or any external decision
engine (R10.2).

Each seam callable keeps its existing ``fn(ctx: dict) -> None`` signature. A
decision maps to its hard-deny effect by *raising* ``EnforcementError``, because
each seam already runs the callable at a point where an exception blocks the
protected operation (the status write, the ``docker run``, or ``adapter.execute``).

Design references: design.md §1.1 (EnforcementError), §1.2 (_enforce dispatch +
factory), §1.4 (per-seam normalize_request mapping), Data Models (PdpRequest).
Requirements: 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 8.2, 10.2, 12.2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Tuple

from . import governance_service
from . import approval_service
from . import policy_engine
from .credential_vault import SecretWrapper
from ..aro import event_service

# Sentinel written in place of any secret-shaped value that reaches the audit
# path. Mirrors event_service's own marker so an emitted ZAF_Audit_Event never
# carries a scoped-token plaintext or a SecretWrapper value (R4.6, R12.3).
_AUDIT_REDACTED = "***REDACTED***"


def _safe_audit_field(value: Any) -> Any:
    """Return ``value`` sanitized so no secret can enter a ZAF_Audit_Event.

    This is a defensive guard layered *in front of* ``event_service``'s own
    redaction: any :class:`SecretWrapper` (which may hold a minted scoped-token
    plaintext, R4.6) is replaced with ``***REDACTED***`` before it is ever
    handed to the audit emitter, and containers are sanitized recursively so a
    wrapper nested inside a dict/list/tuple cannot slip through. A
    ``SecretWrapper`` refuses serialization anyway, but replacing it here keeps
    the emit call from failing *and* guarantees the value never leaves this
    module (R4.6, R5.4, R12.3).
    """
    if isinstance(value, SecretWrapper):
        return _AUDIT_REDACTED
    if isinstance(value, dict):
        return {k: _safe_audit_field(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_audit_field(v) for v in value]
    return value


# --------------------------------------------------------------------------- #
# Typed enforcement error (design §1.1, R12.2)
# --------------------------------------------------------------------------- #
class EnforcementError(Exception):
    """Hard-deny signal raised at a ZAF seam.

    Carries NON-SECRET context only. The message interpolates solely the
    ``action``, ``seam``, and policy ``reason`` — never params values or
    credentials (R12.2). Raising this from a seam is what produces the
    seam-specific hard-deny effect (R1.4/1.5/1.6, R8.2).
    """

    def __init__(
        self,
        *,
        seam: str,
        decision: str,
        reason: str,
        action: str,
        agent_identity: Optional[str],
    ):
        self.seam = seam                 # 'pre_transition' | 'egress' | 'exec'
        self.decision = decision         # DENY | QUARANTINE (or REQUIRE_APPROVAL w/o binding)
        self.reason = reason             # policy reason string (never a secret)
        self.action = action
        self.agent_identity = agent_identity
        super().__init__(f"ZAF {seam} denied {action}: {reason}")


# --------------------------------------------------------------------------- #
# Normalized PDP request (design Data Models)
# --------------------------------------------------------------------------- #
@dataclass
class PdpRequest:
    """Uniform PDP request mapped from a seam ctx dict.

    ``agent_identity``/``agent_db_id`` are resolved from the authenticated
    context (never the agent's self-report, R1.9).
    """

    tenant_id: Optional[int]
    action: str
    agent_identity: Optional[str]      # from authenticated_identity, not self-report
    agent_db_id: Optional[int]
    resource: Optional[str]
    params: Dict[str, Any]
    environment: Dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Per-seam request normalization (design §1.4, R1.9)
# --------------------------------------------------------------------------- #
def normalize_request(
    seam: str,
    ctx: Dict[str, Any],
    authenticated_identity: Callable[[Dict[str, Any]], Tuple[Optional[str], Optional[int]]],
) -> PdpRequest:
    """Map a seam ctx dict into a uniform :class:`PdpRequest`.

    The agent identity and db id are **always** taken from
    ``authenticated_identity(ctx)`` (resolved from the runtime/session binding
    the control plane holds), never from any agent-supplied field in ``ctx``
    (R1.9). The action is derived from control-plane-held fields (``to`` /
    ``image`` / ``operation``) rather than a field the agent could forge, which
    is the basis for R8.2. For the ``exec`` seam, ``payload_keys`` are carried
    as keys only — never values.

    Raises:
        ValueError: when ``seam`` is not one of the three known seams.
    """
    agent_identity, agent_db_id = authenticated_identity(ctx)
    tenant_id = ctx.get("tenant_id")

    if seam == "pre_transition":
        # ctx: {tenant_id, agent_id, from, to, identity}  (lifecycle_service.py:138-144)
        to_state = ctx.get("to")
        from_state = ctx.get("from")
        return PdpRequest(
            tenant_id=tenant_id,
            action=f"agent.transition.{to_state}",
            agent_identity=agent_identity,
            agent_db_id=agent_db_id,
            resource=f"agent:{ctx.get('agent_id')}",
            params={"from": from_state, "to": to_state},
            environment={},
        )

    if seam == "egress":
        # ctx: {server_ip, image, network_policy, proxy_url, name, tenant_id}
        #      (execution_manager.py:419-427)
        image = ctx.get("image")
        return PdpRequest(
            tenant_id=tenant_id,
            action="runtime.launch",
            agent_identity=agent_identity,
            agent_db_id=agent_db_id,
            resource=f"image:{image}",
            params={
                "network_policy": ctx.get("network_policy"),
                "image": image,
            },
            environment={"server_ip": ctx.get("server_ip")},
        )

    if seam == "exec":
        # ctx: {tenant_id, agent_id, operation, payload_keys}  (agent_worker.py:261-266)
        operation = ctx.get("operation")
        return PdpRequest(
            tenant_id=tenant_id,
            action=f"agent.exec.{operation}",
            agent_identity=agent_identity,
            agent_db_id=agent_db_id,
            resource=ctx.get("agent_id"),
            params={
                "operation": operation,
                # keys only, never values — the seam already passes sorted key names
                "payload_keys": list(ctx.get("payload_keys") or []),
            },
            environment={},
        )

    raise ValueError(f"unknown ZAF seam: {seam!r}")


# --------------------------------------------------------------------------- #
# Default authenticated-identity resolver
# --------------------------------------------------------------------------- #
def _default_authenticated_identity(
    ctx: Dict[str, Any],
) -> Tuple[Optional[str], Optional[int]]:
    """Fallback identity resolver used when none is injected.

    The composition root (``src/zaf/wiring.py``) injects a resolver that reads
    the AUTHORITATIVE identity from the runtime/session binding the control
    plane holds. This default is intentionally minimal and must never trust an
    agent self-report; it exposes no agent-supplied identity, so enforcement
    stays independent of self-report (R1.9).
    """
    return (None, None)


# --------------------------------------------------------------------------- #
# The factory + seam callables (design §1.2)
# --------------------------------------------------------------------------- #
def build_enforcers(
    *,
    pdp: Callable[..., Dict[str, Any]] = governance_service.decide,
    approvals: Callable[..., bool] = approval_service.is_authorized,
    audit: Callable[..., Any] = event_service.emit,
    events_repo: Any = None,
    authenticated_identity: Callable[
        [Dict[str, Any]], Tuple[Optional[str], Optional[int]]
    ] = _default_authenticated_identity,
) -> Dict[str, Callable[[Dict[str, Any]], None]]:
    """Build the three seam callables, each closing over the same collaborators.

    Returns ``{'pre_transition': fn, 'egress': fn, 'exec': fn}`` where each
    ``fn(ctx: dict) -> None`` has the exact existing seam signature.

    Dispatch per decision:

    * ``ALLOW``            -> return (proceed, R1.8)
    * ``REQUIRE_APPROVAL`` -> return iff a bound approval exists (R1.7),
      else audit + raise
    * ``DENY`` / ``QUARANTINE`` -> audit + raise (R1.4/1.5/1.6, R8.2)

    ``pdp`` / ``approvals`` / ``audit`` default to the VERIFIED services and are
    injectable for tests. ``authenticated_identity(ctx) -> (agent_identity,
    agent_db_id)`` resolves the authoritative identity (R1.9).
    """

    def _audit(seam: str, req: PdpRequest, decision: Dict[str, Any]) -> None:
        """Emit a structured, secret-free ``zaf.deny`` event on a seam deny.

        Emitted on EVERY seam deny — DENY, QUARANTINE, and an unapproved
        REQUIRE_APPROVAL — with the PDP ``decision`` recorded (R5.2). Only
        non-secret identifiers are placed in the event: the ``seam``, the
        action string, and the policy ``reason`` (never ``req.params`` values,
        credentials, or a minted scoped token).

        Three layers keep secrets out of the ``ZAF_Audit_Event`` (R4.6, R5.4,
        R12.3):

        1. The payload is built from a curated allow-list of non-secret fields;
           ``req.params`` (which may name parameters) is deliberately excluded.
        2. Every field is first passed through :func:`_safe_audit_field`, so any
           ``SecretWrapper`` — the only type that could carry a scoped-token
           plaintext — is replaced with ``***REDACTED***`` before emission, even
           if nested in a container. This guarantees the Credential_Broker's
           scoped-token plaintext can never enter an emitted event (R4.6).
        3. ``event_service.build_event`` additionally runs its own key/value
           redaction over the ``action`` payload.

        Audit failures must never mask the deny, so emission errors are
        swallowed — the subsequent raise still blocks the operation.
        """
        verdict = decision.get("decision")
        try:
            action_payload = _safe_audit_field(
                {
                    "seam": seam,
                    "action": req.action,
                    "reason": decision.get("reason", "blocked"),
                }
            )
            audit(
                events_repo,
                req.tenant_id,
                "zaf.deny",
                "zaf-enforcement",
                agent_id=_safe_audit_field(req.agent_identity),
                action=action_payload,
                decision=verdict,
                severity="HIGH",
            )
        except Exception:  # noqa: BLE001 - audit must not mask the deny
            pass

    def _enforce(seam: str, ctx: Dict[str, Any]) -> None:
        req = normalize_request(seam, ctx, authenticated_identity)
        decision = pdp(
            req.tenant_id,
            req.action,
            agent_db_id=req.agent_db_id,
            agent_identity=req.agent_identity,
            resource=req.resource,
            params=req.params,
            context=req.environment,
        )
        verdict = decision.get("decision")

        if verdict == policy_engine.ALLOW:
            return  # proceed (R1.8)

        if verdict == policy_engine.REQUIRE_APPROVAL:
            if approvals(req.tenant_id, req.action, req.params):
                return  # bound approval exists (R1.7)
            _audit(seam, req, decision)
            raise EnforcementError(
                seam=seam,
                decision=verdict,
                reason=decision.get("reason", "approval required"),
                action=req.action,
                agent_identity=req.agent_identity,
            )

        # DENY, QUARANTINE, or anything else (default-deny, R10.3) -> hard deny
        _audit(seam, req, decision)
        raise EnforcementError(
            seam=seam,
            decision=verdict or policy_engine.DENY,
            reason=decision.get("reason", "blocked"),
            action=req.action,
            agent_identity=req.agent_identity,
        )

    return {
        "pre_transition": lambda ctx: _enforce("pre_transition", ctx),
        "egress": lambda ctx: _enforce("egress", ctx),
        "exec": lambda ctx: _enforce("exec", ctx),
    }
