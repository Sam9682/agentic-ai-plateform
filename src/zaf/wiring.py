"""ZAF composition root (Phase 3, Task 7.1).

This module is the single place where the live control plane builds the three
ZAF seam enforcers **once** and hands them to the existing seam kwargs so the
inert Phase 1/2 no-ops are replaced by real enforcement — *without changing any
seam signature* (design §1.5).

The three seams and their existing injection points are:

* ``LifecycleService(..., zaf_pre_transition=...)``  (``lifecycle_service.py:52``)
* ``execution_manager.launch(..., zaf_egress=...)``   (``execution_manager.py:286``)
* ``AgentTaskWorker(..., zaf_exec=...)``               (``agent_worker.py:258``)

Each kwarg keeps its ``Optional[Callable[[dict], Any]]`` shape and its no-op
default, so any construction site that omits the kwarg (the Phase 1/2 test
suites) is unaffected (R11.3–R11.6). The composition root merely supplies the
real callable where the live process constructs these components.

Egress scoped-token injection (design §4.1, R4.1):
    At the egress seam the enforcer, once the PDP has ALLOWed the launch,
    resolves the launch's credential id and mints a **scoped token** via
    ``credential_vault.mint_scoped_token``. The token handle (never the stored
    secret) is injected into the launch's container environment as
    ``ZAF_SCOPED_TOKEN`` alongside the existing ``HTTP(S)_PROXY`` plumbing
    (``execution_manager.build_run_command``). The raw credential plaintext is
    never read here and never reaches the runtime — ``mint_scoped_token``
    returns only the token handle (R4.1, R4.6). A mint/credential failure
    fails closed by raising, which aborts the launch (mirrors
    ``infra_proxy._run``).

Audit/response hook (design §5, R5.1):
    :func:`build_response_service` constructs the automated-response service
    (:class:`response_service.ResponseService`) with its injected
    ``quarantine``/``revoke_credential``/``block_network`` collaborators. The
    worker invokes this service from its terminal handling (the ``zaf_response``
    seam on ``agent_worker.execute_claimed_task``) so a completed execution
    yields an OBS-linked audit record via ``event_service`` (the response
    service emits through ``event_service`` and opens incidents via
    ``obs_repository``). The seam defaults to inert (``None``) so Phase 1/2
    suites that never wire a response service are unaffected (R11.3-R11.6).

Requirements: 1.1, 1.2, 1.3, 1.10, 11.6, 4.1, 5.1.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Tuple

from . import credential_vault
from . import enforcement
from . import governance_service
from . import approval_service
from . import policy_engine
from . import response_service
from ..aro import event_service


# --------------------------------------------------------------------------- #
# Authenticated-identity resolver (R1.9)
# --------------------------------------------------------------------------- #
def _authenticated_identity(
    ctx: Dict[str, Any],
) -> Tuple[Optional[str], Optional[int]]:
    """Resolve the AUTHORITATIVE agent identity for an enforcement ctx.

    The identity is taken from the control-plane-held binding carried on the
    ctx (``identity``/``agent_identity`` and ``agent_db_id``), never from a
    field an agent could forge for itself (R1.9). The seams populate these from
    the agent row the control plane loaded (``lifecycle_service`` passes the
    agent's ``identity``; the worker passes ``agent_id``), so this resolver
    reads only what the control plane already holds authoritatively.

    When the ctx does not carry an identity (e.g. the egress seam, which
    identifies the launch by image/server rather than by agent), ``(None,
    None)`` is returned — the PDP then evaluates on the tenant's effective
    rules alone, still default-deny.
    """
    identity = ctx.get("agent_identity")
    if identity is None:
        identity = ctx.get("identity")
    agent_db_id = ctx.get("agent_db_id")
    return identity, agent_db_id


# --------------------------------------------------------------------------- #
# Egress scoped-token injection (design §4.1, R4.1)
# --------------------------------------------------------------------------- #
def _inject_scoped_token(
    ctx: Dict[str, Any],
    *,
    mint: Callable[..., Dict[str, Any]],
) -> None:
    """Mint a scoped token for the launch and inject it into the container env.

    Called only after the base egress enforcer ALLOWed the launch. Resolves the
    credential id for the launch from the ctx; when a credential is in play, a
    short-lived scoped token is minted via ``mint`` (``mint_scoped_token``) and
    placed into the launch's user-env dict as ``ZAF_SCOPED_TOKEN`` so
    ``build_run_command`` emits it as a ``-e`` var alongside the existing
    ``HTTP(S)_PROXY`` plumbing. The stored credential plaintext is never read
    and never handed to the runtime (R4.1, R4.6).

    Fail closed: a mint failure raises :class:`enforcement.EnforcementError`,
    which aborts the launch before any ``docker run`` is issued (mirrors the
    fail-closed mint handling in ``infra_proxy._run``).
    """
    credential_id = ctx.get("credential_id")
    if credential_id is None:
        # No credential required for this launch — nothing to inject. The
        # existing HTTP(S)_PROXY plumbing (proxy_url) still applies.
        return

    tenant_id = ctx.get("tenant_id")
    agent_identity = ctx.get("agent_identity") or ctx.get("identity")
    try:
        minted = mint(
            tenant_id,
            credential_id,
            "runtime.launch",
            ttl_seconds=120,
            agent_id=agent_identity,
        )
    except Exception as exc:  # noqa: BLE001 - fail closed on credential failure
        raise enforcement.EnforcementError(
            seam="egress",
            decision=policy_engine.DENY,
            reason="credential unavailable",
            action="runtime.launch",
            agent_identity=agent_identity,
        ) from exc

    token = minted.get("token")
    if not token:
        raise enforcement.EnforcementError(
            seam="egress",
            decision=policy_engine.DENY,
            reason="credential unavailable",
            action="runtime.launch",
            agent_identity=agent_identity,
        )

    # Inject the scoped-token HANDLE (never the raw secret) into the launch's
    # container env. The launch's `environment["env"]` dict is threaded through
    # the egress ctx as `env`; build_run_command emits it as `-e` vars. The
    # HTTP(S)_PROXY env is already set from `proxy_url` by build_run_command.
    env = ctx.get("env")
    if env is None:
        env = {}
        ctx["env"] = env
    env["ZAF_SCOPED_TOKEN"] = token


# --------------------------------------------------------------------------- #
# Composition root
# --------------------------------------------------------------------------- #
def build_enforcers(
    *,
    pdp: Callable[..., Dict[str, Any]] = governance_service.decide,
    approvals: Optional[Callable[..., bool]] = None,
    audit: Callable[..., Any] = event_service.emit,
    events_repo: Any = None,
    authenticated_identity: Callable[
        [Dict[str, Any]], Tuple[Optional[str], Optional[int]]
    ] = _authenticated_identity,
    mint_scoped_token: Callable[..., Dict[str, Any]] = credential_vault.mint_scoped_token,
    consume_approval: Callable[..., Optional[int]] = approval_service.consume_authorization,
) -> Dict[str, Callable[[Dict[str, Any]], None]]:
    """Build the three live seam enforcers once (the composition root).

    Returns ``{'pre_transition', 'egress', 'exec'}`` — the exact keys the three
    seams expect — each a ``fn(ctx: dict) -> None`` with the existing seam
    signature. ``pre_transition`` and ``exec`` are the bare enforcers from
    :func:`enforcement.build_enforcers`. ``egress`` is wrapped so that, once the
    PDP ALLOWs the launch, a scoped token is minted and injected into the
    container env (design §4.1, R4.1) before the launch proceeds.

    All collaborators default to the VERIFIED services and are injectable for
    tests. The caller passes these into the existing seam kwargs:

        enforcers = build_enforcers()
        LifecycleService(..., zaf_pre_transition=enforcers["pre_transition"])
        execution_manager.launch(..., zaf_egress=enforcers["egress"])
        AgentTaskWorker(..., zaf_exec=enforcers["exec"])
    """
    base = enforcement.build_enforcers(
        pdp=pdp,
        approvals=approvals,
        audit=audit,
        events_repo=events_repo,
        authenticated_identity=authenticated_identity,
        consume_approval=consume_approval,
    )

    base_egress = base["egress"]

    def egress(ctx: Dict[str, Any]) -> None:
        # PDP enforcement first: a DENY/QUARANTINE/unapproved REQUIRE_APPROVAL
        # raises EnforcementError here and no token is minted (R1.5).
        base_egress(ctx)
        # ALLOWed: mint + inject the scoped token into the container env (R4.1).
        _inject_scoped_token(ctx, mint=mint_scoped_token)

    return {
        "pre_transition": base["pre_transition"],
        "egress": egress,
        "exec": base["exec"],
    }


# --------------------------------------------------------------------------- #
# Audit/response hook — post-execution interposition (design §5, R5.1)
# --------------------------------------------------------------------------- #
def build_response_service(
    *,
    quarantine: Optional[Callable[[int, int, str], Any]] = None,
    revoke_credential: Optional[Callable[[int, int], Any]] = credential_vault.revoke,
    block_network: Optional[Callable[[int, str], Any]] = None,
    incident_repo: Any = None,
    events_repo: Any = None,
) -> response_service.ResponseService:
    """Construct the :class:`ResponseService` in the composition root (R5.1).

    The automated-response service is parameterized with its containment
    collaborators (``response_service.py`` ~:60-78); this composition root wires
    them to the VERIFIED services and returns a ready-to-invoke instance that
    the worker consults from its terminal handling (see
    ``agent_worker.execute_claimed_task``'s ``zaf_response`` seam). A completed
    execution produces an OBS-linked record because ``ResponseService.respond``
    emits through ``event_service`` and opens incidents via ``obs_repository``.

    Collaborator defaults (all injectable so Phase 1/2 suites that never wire a
    response service remain unaffected — the worker's ``zaf_response`` defaults
    to ``None``):

    * ``revoke_credential`` → ``credential_vault.revoke(tenant_id, cid)`` (the
      VERIFIED revoke path, which also revokes scoped tokens).
    * ``quarantine`` / ``block_network`` → ``None`` by default. These bind to
      live, stateful collaborators (a ``LifecycleService`` instance's
      ``quarantine`` and an ``execution_manager``-backed network isolation) that
      the live process supplies; ``ResponseService`` already guards each with an
      ``is not None`` check so a benign/completed execution (which plans only an
      ``alert``) never needs them.
    * ``incident_repo`` / ``events_repo`` → ``None`` lets ``ResponseService``
      fall back to the real ``obs_repository`` / ``events_repository`` so the
      record is OBS-linked.

    The decision of WHICH containment actions run for a given outcome stays in
    the VERIFIED ``response_service.plan_response`` pure function; this root only
    supplies collaborators and never duplicates that logic (R11.1/R11.2).
    """
    return response_service.ResponseService(
        quarantine=quarantine,
        revoke_credential=revoke_credential,
        block_network=block_network,
        incident_repo=incident_repo,
        events_repo=events_repo,
    )


# --------------------------------------------------------------------------- #
# Live lifecycle enforcer (finding F1, ABF Phase 2)
# --------------------------------------------------------------------------- #
#: Transitions that contain, stop or merely record health are never gated by
#: the PDP: blocking them would weaken containment (a tenant DENY rule, or a
#: dead policy store, must never prevent a quarantine or a stop).
UNGATED_TARGETS = frozenset({"QUARANTINED", "TERMINATED", "STOPPING", "STOPPED",
                             "FAILED", "UNHEALTHY"})


def is_gated_transition(from_state: Optional[str], to_state: Optional[str]) -> bool:
    """True when a lifecycle transition must be authorized by the PDP.

    Not gated: containment / stop / health targets, health recovery
    (UNHEALTHY -> RUNNING) and the human release path (QUARANTINED -> READY),
    which is authorized by the admin-only release route instead.
    """
    if to_state in UNGATED_TARGETS:
        return False
    if from_state == "UNHEALTHY" and to_state == "RUNNING":
        return False
    if from_state == "QUARANTINED" and to_state == "READY":
        return False
    return True


def build_live_pre_transition(
    *,
    pdp: Callable[..., Dict[str, Any]] = governance_service.decide,
    events_repo: Any = None,
    consume_approval: Callable[..., Optional[int]] = approval_service.consume_authorization,
) -> Callable[[Dict[str, Any]], None]:
    """Return the ``zaf_pre_transition`` callable for the live LifecycleService.

    The lifecycle ctx carries the agent's database id as ``agent_id``; it is
    mapped to ``agent_db_id`` so the PDP loads the agent's permissions and its
    control-plane status (QUARANTINED / TERMINATED are refused by the PDP).
    """
    base = build_enforcers(pdp=pdp, events_repo=events_repo,
                           consume_approval=consume_approval)["pre_transition"]

    def pre_transition(ctx: Dict[str, Any]) -> None:
        if not is_gated_transition(ctx.get("from"), ctx.get("to")):
            return
        enriched = dict(ctx)
        enriched.setdefault("agent_db_id", ctx.get("agent_id"))
        base(enriched)

    return pre_transition


def quarantine_agent(
    tenant_id: int,
    agent_db_id: int,
    *,
    reason: str,
    lifecycle_svc,
    exec_mgr=None,
    revoke_credentials: bool = False,
    events_repo: Any = None,
) -> Dict[str, Any]:
    """Quarantine an agent and cut its acting credentials (finding F6).

    Steps, all through existing services:
      1. ``governance_service.quarantine`` — state -> QUARANTINED and runtime
         stop/isolation when an execution manager is supplied; when
         ``revoke_credentials`` is true, the agent-bound base credentials are
         revoked too (irreversible: they must be rotated before release).
      2. Revoke the agent's short-lived scoped tokens (vault).
      3. Revoke the agent's MCP / firewall tokens; telemetry tokens are kept so
         the contained runtime stays observable.
    The PDP independently refuses every gated action of a QUARANTINED agent,
    so containment does not depend on steps 2-3 succeeding.
    """
    from ..aro import agent_repository as agent_repo
    from ..obs import ingest_tokens

    agent = agent_repo.get_agent(tenant_id, agent_db_id)
    if agent is None:
        raise LookupError("agent not found")
    identity = agent.get("identity")
    credential_ids = []
    if revoke_credentials:
        rows = credential_vault._get_db().execute_query(
            "SELECT id FROM agent_credentials WHERE tenant_id = %s AND agent_id = %s "
            "AND status <> 'revoked'",
            (tenant_id, identity), fetch_all=True,
        ) or []
        credential_ids = [int(r[0]) for r in rows]
    result = governance_service.quarantine(
        tenant_id, agent_db_id, identity, reason=reason,
        credential_ids=credential_ids, lifecycle_svc=lifecycle_svc, exec_mgr=exec_mgr,
    )
    revoked = {"credentials": len(credential_ids), "scoped_tokens": 0, "agent_tokens": 0}
    try:
        revoked["scoped_tokens"] = credential_vault.revoke_agent_scoped_tokens(tenant_id, identity)
    except Exception:  # noqa: BLE001 - PDP still refuses the quarantined agent
        revoked["scoped_tokens"] = None
    try:
        revoked["agent_tokens"] = ingest_tokens.revoke_acting_scopes_for_agent(tenant_id, agent_db_id)
    except Exception:  # noqa: BLE001
        revoked["agent_tokens"] = None
    if events_repo is None:
        from ..aro import events_repository as events_repo
    try:
        event_service.emit(events_repo, tenant_id, "abf.enforcement", "abf",
                           agent_id=identity,
                           action={"enforcement": "QUARANTINE", "reason": reason,
                                   "revoked": revoked},
                           decision="QUARANTINE", severity="HIGH")
    except Exception:  # noqa: BLE001
        pass
    out = dict(result) if isinstance(result, dict) else {"id": agent_db_id}
    out["revoked"] = revoked
    return out


def build_live_exec(
    *,
    pdp: Callable[..., Dict[str, Any]] = governance_service.decide,
    events_repo: Any = None,
    get_agent: Optional[Callable[[int, int], Optional[Dict[str, Any]]]] = None,
    consume_approval: Callable[..., Optional[int]] = approval_service.consume_authorization,
) -> Callable[[Dict[str, Any]], None]:
    """Return the zaf_exec callable for a live AgentTaskWorker (Phase 3 wiring).

    The worker's seam ctx carries only the agent's database id (agent_id);
    the authoritative identity is loaded from the agents table here, so the PDP
    sees the agent's permissions and its quarantine status. An agent that no
    longer exists in the tenant is denied (fail closed).
    """
    if get_agent is None:
        from ..aro import agent_repository
        get_agent = agent_repository.get_agent
    base = build_enforcers(pdp=pdp, events_repo=events_repo,
                           consume_approval=consume_approval)["exec"]

    def exec_seam(ctx: Dict[str, Any]) -> None:
        agent = get_agent(ctx.get("tenant_id"), ctx.get("agent_id"))
        if agent is None:
            raise enforcement.EnforcementError(
                seam="exec", decision=policy_engine.DENY, reason="agent not found",
                action=f"agent.exec.{ctx.get('operation')}", agent_identity=None)
        enriched = dict(ctx)
        enriched["agent_identity"] = agent.get("identity")
        enriched["agent_db_id"] = ctx.get("agent_id")
        base(enriched)

    return exec_seam
