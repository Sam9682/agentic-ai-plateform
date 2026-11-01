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
    approvals: Callable[..., bool] = approval_service.is_authorized,
    audit: Callable[..., Any] = event_service.emit,
    events_repo: Any = None,
    authenticated_identity: Callable[
        [Dict[str, Any]], Tuple[Optional[str], Optional[int]]
    ] = _authenticated_identity,
    mint_scoped_token: Callable[..., Dict[str, Any]] = credential_vault.mint_scoped_token,
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
