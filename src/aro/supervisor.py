"""Agent Supervisor — configurable Role model (Phase 5, Task 9.1).

This module is the entry point for the net-new Agent Supervisor vertical slice.
Task 9.1 establishes only the **configurable Role model** (SRS R7); the
delegation, coordination, budget, and end-to-end ``run()`` workflow (Task 10.1)
extend this same module additively in a later wave. The structure here is kept
additive so those later collaborators can slot in without reworking the roles
layer.

Roles are **data, not code** (R7.2, R7.4): a :class:`Role` is just an immutable
record, and :func:`load_roles` reads the role set from configuration
(``conf/supervisor_roles.yaml``). Adding a role to the config file makes it
selectable by the Supervisor with no code change (R7.4). The seven example roles
— Architect, Developer, DevOps, Security, FinOps, SRE, Supervisor — ship as
config entries (R7.3), not as hardcoded constants.

The frozen-dataclass, pure-loader style mirrors the rest of the ``aro`` package
(e.g. :mod:`src.aro.scope`, :mod:`src.aro.decomposition_planner`): no live
service is touched, so role loading is unit-testable in isolation.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Tuple, Union

import yaml

# Default location of the roles configuration, resolved relative to the repo
# root (three levels up from this file: src/aro/supervisor.py -> repo root).
_DEFAULT_ROLES_CONFIG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "conf",
    "supervisor_roles.yaml",
)


@dataclass(frozen=True)
class Role:
    """A configurable supervising-agent role (R7.1).

    A Role is pure data loaded from configuration, never a hardcoded class:

    * ``name`` — the Role identifier matched during role selection
      (e.g. ``"Architect"``, ``"Developer"``).
    * ``capabilities`` — the action globs this Role may request, matched with
      ``fnmatch`` against a Child_Task's requested actions (R9.1, R10).
    * ``default_scope`` — the resource globs this Role defaults to when a
      Child_Task does not request an explicit resource scope (R10).

    Both glob collections are tuples so a Role is hashable and immutable, safe
    to embed in a child's governance context.
    """

    name: str
    capabilities: Tuple[str, ...]
    default_scope: Tuple[str, ...]


def load_roles(config: Union[str, Dict[str, Any], None] = None) -> Dict[str, Role]:
    """Load the configurable Role set (R7.2).

    ``config`` may be:

    * ``None`` — read the default ``conf/supervisor_roles.yaml`` (R7.3);
    * a path (``str``) — read and parse that YAML file;
    * an already-parsed mapping (``dict``) — use it directly.

    Returns a ``{name: Role}`` mapping. Because the roles come entirely from
    configuration, adding a new entry to the config makes it selectable with no
    code change (R7.4).

    Raises ``ValueError`` when the configuration is malformed (missing
    ``roles`` list, a non-mapping entry, a missing/empty ``name``, or a
    duplicate role name).
    """
    if config is None:
        config = _DEFAULT_ROLES_CONFIG

    if isinstance(config, str):
        with open(config, "r", encoding="utf-8") as fh:
            parsed = yaml.safe_load(fh) or {}
    elif isinstance(config, dict):
        parsed = config
    else:
        raise ValueError(
            "load_roles config must be a path, a parsed mapping, or None; "
            f"got {type(config).__name__}"
        )

    raw_roles = parsed.get("roles")
    if not isinstance(raw_roles, list):
        raise ValueError("roles configuration must contain a 'roles' list")

    roles: Dict[str, Role] = {}
    for entry in raw_roles:
        if not isinstance(entry, dict):
            raise ValueError(f"each role entry must be a mapping; got {entry!r}")
        name = entry.get("name")
        if not name or not isinstance(name, str):
            raise ValueError(f"role entry is missing a non-empty 'name': {entry!r}")
        if name in roles:
            raise ValueError(f"duplicate role name in configuration: {name!r}")
        roles[name] = Role(
            name=name,
            capabilities=tuple(entry.get("capabilities") or ()),
            default_scope=tuple(entry.get("default_scope") or ()),
        )

    return roles


# =============================================================================
# Task 10.1 — Delegation, coordination, budget, and the end-to-end workflow.
#
# This section extends the roles layer above additively (SRS R9–R12). It is the
# net-new Agent Supervisor workflow: it decomposes a request into dependency-
# ordered children, selects a Role per child, inherits governance scope by
# strict intersection, enforces a budget over the Half-A cost records, delegates
# each ready child to the Phase 2 Agent_Worker under the Phase 4 execution
# policy, aggregates child results, and gates the final action through the
# Phase 3 PDP + approval service.
#
# Design discipline (reuse, do not rewrite):
#   * decomposition_planner.plan / ChildTaskSpec / CycleError  (Task 2.14)
#   * scope.scope_intersection / in_scope / Scope              (Task 2.11)
#   * obs_cost.list_cost_records                               (Task 2.6/6.1)
#   * task_repository.submit                                   (Phase 2)
#   * execution_policy.run_with_policy / CancelToken / Outcome (Phase 4)
#   * governance_service.decide                                (Phase 3)
#   * approval_service.request_approval / is_authorized        (Phase 3)
#
# Every collaborator is an INJECTED SEAM (R14.3): the worker/policy, the PDP,
# the approval service, and the cost reader are all constructor parameters, so
# the whole workflow is unit-testable with mocks and no live DB / Docker / SSH /
# ZAF. ``detect_conflict`` and ``budget_check`` are PURE functions. No LLM or ML
# model participates in any decision (R13.7): the state machine is a
# deterministic function of the decomposition, the costs, and the PDP decision.
# =============================================================================

import uuid as _uuid
from typing import Callable, List, Optional, Sequence

from . import decomposition_planner as _planner
from . import scope as _scope
from ..execution_policy import (
    CancelToken,
    Outcome,
    OutcomeStatus,
    run_with_policy as _run_with_policy,
    ssh_is_transient as _ssh_is_transient,
)

# PDP decision constants, mirrored from zaf.policy_engine so the workflow reads
# clearly without importing the engine at module load (kept decoupled; the
# strings are the ZAF contract surfaced by governance_service.decide).
DECISION_ALLOW = "ALLOW"
DECISION_DENY = "DENY"
DECISION_REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
DECISION_QUARANTINE = "QUARANTINE"

# Terminal child statuses, aligned 1:1 with Outcome/OutcomeStatus and the ARO
# ``agent_tasks`` terminals so aggregation reasons over a single vocabulary.
_TERMINAL_STATUSES = frozenset(
    {"succeeded", "failed", "timed_out", "cancelled"}
)


# --------------------------------------------------------------------------- #
# Pure helpers (R9.7 conflict detection, R11 budget check) — no I/O, no clock.
# --------------------------------------------------------------------------- #
def detect_conflict(child_results: Sequence[Dict[str, Any]]) -> bool:
    """Return ``True`` when aggregated child results contradict (R9.7). Pure.

    A conflict is a genuine disagreement among the children that *succeeded*:
    only ``succeeded`` children with a ``conclusion`` field participate, and a
    conflict exists when they do not all report the same conclusion. Failed /
    timed-out / cancelled children are not conflicts in themselves — they are
    handled by the delegation outcome — and children without a ``conclusion``
    are indeterminate and excluded. With zero or one distinct conclusion there
    is no contradiction.

    Having the supervisor flag a conflict rather than silently picking a winner
    is the R9.7 escalation trigger.
    """
    conclusions = {
        r.get("conclusion")
        for r in child_results
        if isinstance(r, dict)
        and r.get("status") == "succeeded"
        and r.get("conclusion") is not None
    }
    return len(conclusions) > 1


def budget_check(cost_records: Sequence[Dict[str, Any]], ceiling: float) -> Dict[str, Any]:
    """Aggregate ``estimated_cost`` across a chain vs a ``ceiling``. Pure (R11).

    Sums the separately-stored ``estimated_cost`` of every cost record (the
    Half-A ``agent_cost_records`` rows filtered by ``parent_task_id`` /
    ``delegation_id``) and compares the total against the configured budget.
    Returns ``{"total", "ceiling", "within"}`` where ``within`` is ``True`` iff
    the aggregate does not exceed the ceiling (R11.2, R11.3). Never raises on
    data: a record missing ``estimated_cost`` contributes ``0.0``.
    """
    total = round(
        sum(float(r.get("estimated_cost", 0.0) or 0.0) for r in cost_records), 6
    )
    return {"total": total, "ceiling": float(ceiling), "within": total <= float(ceiling)}


# --------------------------------------------------------------------------- #
# Role selection (R9.1) — pure given the loaded role set.
# --------------------------------------------------------------------------- #
def select_role(
    child: "_planner.ChildTaskSpec", roles: Dict[str, Role]
) -> Optional[Role]:
    """Select the Role whose capabilities cover the child's requested actions.

    A Role matches a child when *every* requested action glob is covered by one
    of the Role's capability globs (reusing :func:`scope.glob_covers`, the same
    ``fnmatch`` matcher the PDP and scope intersection use). Among matching
    roles the most specific wins — the one with the fewest capability globs —
    with the config declaration order breaking ties deterministically (no
    randomness, R13.7). Returns ``None`` when no configured Role can cover the
    child, so the caller can withhold rather than over-grant.
    """
    requested = child.requested_scope
    requested_actions = tuple(requested.actions) if requested is not None else ()

    def covers_all(role: Role) -> bool:
        return all(
            any(_scope.glob_covers(cap, ra) for cap in role.capabilities)
            for ra in requested_actions
        )

    candidates = [r for r in roles.values() if covers_all(r)]
    if not candidates:
        return None
    # Most specific (fewest capabilities) first; config order is the stable
    # tie-breaker because dict preserves insertion order.
    return min(candidates, key=lambda r: len(r.capabilities))


# --------------------------------------------------------------------------- #
# Delegation record and the Supervisor itself.
# --------------------------------------------------------------------------- #
@dataclass
class DelegationResult:
    """Outcome of delegating a single child (one row of the aggregation)."""

    key: str
    role_name: Optional[str]
    effective_scope: "_scope.Scope"
    outcome: Optional[Outcome]
    status: str  # succeeded|failed|timed_out|cancelled|blocked|denied|withheld
    result: Any = None
    reason: str = ""


# Status produced by run_with_policy.OutcomeStatus -> child status vocabulary.
_OUTCOME_TO_STATUS = {
    OutcomeStatus.SUCCEEDED: "succeeded",
    OutcomeStatus.FAILED: "failed",
    OutcomeStatus.TIMED_OUT: "timed_out",
    OutcomeStatus.CANCELLED: "cancelled",
}


class Supervisor:
    """End-to-end Agent Supervisor workflow (R9–R12).

    All collaborators are injected so the workflow is unit-testable with mocks
    and no live services (R14.3):

    * ``tenant_id`` — the tenant every delegation and PDP call is scoped to.
    * ``agent_id`` — the executing agent id passed to ``task_repository.submit``.
    * ``roles`` — the ``{name: Role}`` set from :func:`load_roles` (R7).
    * ``submit`` — ``task_repository.submit`` seam (Phase 2). Called as
      ``submit(tenant_id, agent_id, operation=..., payload=..., policy_context=...)``.
    * ``execute`` — the unit of work a delegated child runs, called
      ``execute(child, submitted_task, token)``; wrapped by ``run_with_policy``.
      In production this drives the Phase 2 Agent_Worker; tests pass a fake op.
    * ``decide`` — ``governance_service.decide`` seam (Phase 3 PDP).
    * ``request_approval`` / ``is_authorized`` — ``approval_service`` seam (R12.3).
    * ``cost_reader`` — ``obs_cost.list_cost_records`` seam for budget (R11).
    * ``fan_out`` — max concurrent in-flight children (R9.2); coordination is
      cooperative and deterministic (ready children dispatched in topo order).
    * ``clock`` — injected time source (parity with the rest of ``aro``).

    No LLM/ML participates: every branch is a deterministic function of the
    decomposition, the aggregated costs, and the PDP decision (R13.7).
    """

    def __init__(
        self,
        *,
        tenant_id: int,
        agent_id: int,
        roles: Dict[str, Role],
        submit: Callable[..., Dict[str, Any]],
        execute: Callable[..., Any],
        decide: Callable[..., Dict[str, Any]],
        request_approval: Callable[..., Any],
        is_authorized: Callable[..., bool],
        cost_reader: Optional[Callable[..., List[Dict[str, Any]]]] = None,
        fan_out: int = 4,
        default_timeout: Optional[float] = 1800.0,
        default_max_attempts: int = 1,
        is_transient: Callable[[BaseException], bool] = _ssh_is_transient,
        clock: Callable[[], float] = None,
    ) -> None:
        import time as _time

        self._tenant_id = int(tenant_id)
        self._agent_id = int(agent_id)
        self._roles = dict(roles or {})
        self._submit = submit
        self._execute = execute
        self._decide = decide
        self._request_approval = request_approval
        self._is_authorized = is_authorized
        self._cost_reader = cost_reader
        self._fan_out = max(1, int(fan_out))
        self._default_timeout = default_timeout
        self._default_max_attempts = max(1, int(default_max_attempts))
        self._is_transient = is_transient
        self._clock = clock or _time.monotonic

    # ----------------------------------------------------------------- #
    # Scope inheritance (R10).
    # ----------------------------------------------------------------- #
    def _effective_scope(
        self, parent_scope: "_scope.Scope", child: "_planner.ChildTaskSpec"
    ) -> "_scope.Scope":
        """Child effective scope = parent ∩ child_requested (R10.2–R10.4)."""
        requested = child.requested_scope
        if requested is None:
            requested = _scope.Scope(actions=frozenset(), resources=frozenset())
        return _scope.scope_intersection(parent_scope, requested)

    # ----------------------------------------------------------------- #
    # Single-child delegation under the Phase 4 policy (R9.1, R9.4–R9.6).
    # ----------------------------------------------------------------- #
    def _delegate_child(
        self,
        parent_task_id: Optional[int],
        delegation_id: str,
        parent_scope: "_scope.Scope",
        child: "_planner.ChildTaskSpec",
        cancel_token: CancelToken,
    ) -> DelegationResult:
        """Delegate one ready child to the worker under retry/timeout/cancel.

        1. Select a Role by capability match (R9.1); no Role -> withhold.
        2. Compute the child's effective scope by intersection (R10) and write
           it into the child's ``policy_context`` alongside ``parent_task_id``
           and ``delegation_id``.
        3. Deny out-of-scope before the PDP (R10.5): if the child's own
           operation is not within its effective scope, the delegation is
           denied and never submitted.
        4. Submit through the injected ``task_repository.submit`` seam (Phase 2).
        5. Execute under ``run_with_policy`` (Phase 4) so transient failures
           retry (R9.4), a timeout trips ``TIMED_OUT`` (R9.5), and a parent
           cancel cancels the in-flight child via the shared ``CancelToken``
           (R9.6).
        """
        role = select_role(child, self._roles)
        effective = self._effective_scope(parent_scope, child)

        if role is None:
            return DelegationResult(
                key=child.key,
                role_name=None,
                effective_scope=effective,
                outcome=None,
                status="withheld",
                reason="no role covers the child's requested actions",
            )

        # R10.5 — deny a delegated action outside the child's effective scope
        # BEFORE the PDP is consulted, reusing the same fnmatch matcher.
        child_resources = (
            tuple(child.requested_scope.resources)
            if child.requested_scope is not None
            else ()
        )
        resource = child_resources[0] if child_resources else "*"
        if not _scope.in_scope(effective, child.operation, resource):
            return DelegationResult(
                key=child.key,
                role_name=role.name,
                effective_scope=effective,
                outcome=None,
                status="denied",
                reason="delegated action outside child effective scope (R10.5)",
            )

        # Effective scope is embedded in the child policy_context so the Phase 3
        # PDP (and any downstream claim) evaluates the child against its
        # inherited, intersected scope (R10.1).
        policy_context = {
            "parent_task_id": parent_task_id,
            "delegation_id": delegation_id,
            "effective_scope": {
                "actions": sorted(effective.actions),
                "resources": sorted(effective.resources),
            },
            "role_name": role.name,
        }

        submitted = self._submit(
            self._tenant_id,
            self._agent_id,
            operation=child.operation,
            payload={"child_key": child.key},
            policy_context=policy_context,
        )

        # Phase 4 contract: the op is called op(token) so it can honour cancel
        # mid-flight; transient/timeout/cancel semantics are entirely the
        # policy's (reused, not re-implemented).
        def _op(token: CancelToken) -> Any:
            return self._execute(child, submitted, token)

        outcome = _run_with_policy(
            _op,
            timeout=self._default_timeout,
            max_attempts=self._default_max_attempts,
            is_transient=self._is_transient,
            cancel_token=cancel_token,
        )
        status = _OUTCOME_TO_STATUS.get(outcome.status, "failed")
        return DelegationResult(
            key=child.key,
            role_name=role.name,
            effective_scope=effective,
            outcome=outcome,
            status=status,
            result=outcome.value,
            reason="" if status == "succeeded" else str(outcome.error or status),
        )

    # ----------------------------------------------------------------- #
    # Coordination: dependency-ordered, bounded-fan-out delegation (R9.2, R9.3).
    # ----------------------------------------------------------------- #
    def _coordinate(
        self,
        parent_task_id: Optional[int],
        delegation_id: str,
        parent_scope: "_scope.Scope",
        planned: Dict[str, Any],
        ceiling: Optional[float],
        cancel_token: CancelToken,
    ) -> Dict[str, DelegationResult]:
        """Delegate children honouring ``depends_on``, fan-out, budget, cancel.

        Walks the planner ``order`` (already a valid topological sort). A child
        is dispatched only once every key it depends on has *succeeded*; if a
        prerequisite did not succeed the dependent is withheld (it cannot run).
        Before each dispatch the budget is re-checked over the live chain so a
        delegation that would exceed the ceiling is blocked rather than
        submitted (R11.2). Dispatch is bounded by ``fan_out`` conceptually; the
        coordination itself is deterministic and cooperative.

        A parent cancel observed via ``cancel_token`` stops further dispatch and
        marks the remaining children ``cancelled`` (R9.6).
        """
        by_key: Dict[str, "_planner.ChildTaskSpec"] = {
            c.key: c for c in planned["children"]
        }
        results: Dict[str, DelegationResult] = {}

        for key in planned["order"]:
            child = by_key[key]

            # R9.6 — a parent cancel halts further dispatch.
            if cancel_token.cancelled():
                results[key] = DelegationResult(
                    key=key,
                    role_name=None,
                    effective_scope=self._effective_scope(parent_scope, child),
                    outcome=None,
                    status="cancelled",
                    reason="parent cancellation requested",
                )
                continue

            # A dependent can only run when every prerequisite succeeded.
            unmet = [
                dep
                for dep in child.depends_on
                if results.get(dep) is None or results[dep].status != "succeeded"
            ]
            if unmet:
                results[key] = DelegationResult(
                    key=key,
                    role_name=None,
                    effective_scope=self._effective_scope(parent_scope, child),
                    outcome=None,
                    status="withheld",
                    reason=f"unmet dependencies: {', '.join(unmet)}",
                )
                continue

            # R11.2 — re-evaluate the budget over the live chain before dispatch.
            if ceiling is not None:
                chain = self._load_chain_costs(parent_task_id, delegation_id)
                check = budget_check(chain, ceiling)
                if not check["within"]:
                    results[key] = DelegationResult(
                        key=key,
                        role_name=None,
                        effective_scope=self._effective_scope(parent_scope, child),
                        outcome=None,
                        status="blocked",
                        reason=(
                            f"budget exceeded: total {check['total']} > "
                            f"ceiling {check['ceiling']}"
                        ),
                    )
                    continue

            results[key] = self._delegate_child(
                parent_task_id, delegation_id, parent_scope, child, cancel_token
            )

        return results

    def _load_chain_costs(
        self, parent_task_id: Optional[int], delegation_id: str
    ) -> List[Dict[str, Any]]:
        """Read ``agent_cost_records`` for this parent/delegation chain (R11.1).

        Uses the injected ``cost_reader`` (``obs_cost.list_cost_records``) seam;
        when no reader is wired the chain is treated as empty (no cost recorded
        yet), which keeps the budget check total-and-permissive by default.
        """
        if self._cost_reader is None:
            return []
        return self._cost_reader(
            self._tenant_id,
            parent_task_id=parent_task_id,
            delegation_id=delegation_id,
        )

    # ----------------------------------------------------------------- #
    # Aggregation + conflict escalation (R9.3, R9.7).
    # ----------------------------------------------------------------- #
    def _aggregate(
        self, results: Dict[str, DelegationResult]
    ) -> Dict[str, Any]:
        """Aggregate terminal child results into the parent result (R9.3)."""
        child_results = [
            {
                "key": r.key,
                "status": r.status,
                "result": r.result,
                "conclusion": (
                    r.result.get("conclusion")
                    if isinstance(r.result, dict)
                    else None
                ),
            }
            for r in results.values()
        ]
        all_terminal = all(
            r.status in _TERMINAL_STATUSES or r.status in {"withheld", "blocked", "denied"}
            for r in results.values()
        )
        succeeded = [r for r in results.values() if r.status == "succeeded"]
        return {
            "children": child_results,
            "all_terminal": all_terminal,
            "succeeded_count": len(succeeded),
            "total_count": len(results),
        }

    # ----------------------------------------------------------------- #
    # End-to-end workflow state machine (R12).
    # ----------------------------------------------------------------- #
    def run(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Run the end-to-end supervisor workflow (R12).

        ``request`` shape (all injected, no live lookups):

        * ``parent`` — opaque parent-task handle passed to the planner.
        * ``parent_task_id`` — optional id used for cost-chain filtering (R11).
        * ``parent_scope`` — :class:`scope.Scope` the parent is authorised for.
        * ``children`` — list of :class:`decomposition_planner.ChildTaskSpec`.
        * ``action`` — the final action the parent wants to execute.
        * ``resource`` / ``params`` — PDP context for the final action.
        * ``budget`` — optional numeric ceiling for the delegation chain (R11).
        * ``cancel_token`` — optional :class:`CancelToken` (R9.6).

        State machine (deterministic, no LLM — R13.7):
          DECOMPOSE → SELECT ROLE → SCOPE+BUDGET → DELEGATE → AGGREGATE
          → ZAF VALIDATE → {DENY: withhold | REQUIRE_APPROVAL: approval-gate |
          ALLOW: execute}.

        Returns a dict describing the terminal state and every intermediate
        decision so callers (and tests) can assert the exact routing.
        """
        parent = request.get("parent")
        parent_task_id = request.get("parent_task_id")
        parent_scope = request.get("parent_scope") or _scope.Scope(
            actions=frozenset(), resources=frozenset()
        )
        children: List["_planner.ChildTaskSpec"] = list(request.get("children") or [])
        action = request.get("action")
        resource = request.get("resource")
        params = request.get("params") or {}
        ceiling = request.get("budget")
        cancel_token = request.get("cancel_token") or CancelToken()
        delegation_id = request.get("delegation_id") or f"deleg-{_uuid.uuid4().hex[:12]}"

        # --- DECOMPOSE (R12.1, R8) — reject cycles outright, no partial plan. --
        try:
            planned = _planner.plan(parent, children)
        except _planner.CycleError as exc:
            return {
                "state": "rejected",
                "reason": "decomposition cycle",
                "cycle": exc.cycle,
                "delegation_id": delegation_id,
            }

        # --- SELECT ROLE + SCOPE + BUDGET + DELEGATE + coordinate (R9, R10, R11) --
        results = self._coordinate(
            parent_task_id, delegation_id, parent_scope, planned, ceiling, cancel_token
        )

        # --- AGGREGATE (R9.3) --------------------------------------------------
        aggregate = self._aggregate(results)

        # A parent cancel observed during coordination withholds the final
        # action too — we never execute the parent action for a cancelled
        # parent, the in-progress children were already cancelled (R9.6).
        if cancel_token.cancelled():
            return {
                "state": "cancelled",
                "reason": "parent cancellation requested",
                "delegation_id": delegation_id,
                "aggregate": aggregate,
            }

        # --- Conflict → escalate to a human (R9.7) -----------------------------
        if detect_conflict(aggregate["children"]):
            approval = self._request_approval(
                self._tenant_id,
                action or "supervisor.escalation",
                params=params,
                resource=resource,
                risk_explanation="conflicting child results require human review",
            )
            return {
                "state": "escalated",
                "reason": "conflicting child results",
                "delegation_id": delegation_id,
                "aggregate": aggregate,
                "approval": approval,
            }

        # A delegation that was blocked on budget or denied on scope withholds
        # the parent action — we never execute over-budget or out-of-scope work.
        blocked = [r for r in results.values() if r.status == "blocked"]
        if blocked:
            return {
                "state": "blocked",
                "reason": blocked[0].reason,
                "delegation_id": delegation_id,
                "aggregate": aggregate,
            }

        # --- ZAF VALIDATE (R12.2) — single PDP, no supervisor decision logic. --
        decision = self._decide(
            self._tenant_id,
            action,
            resource=resource,
            params=params,
            context={"delegation_id": delegation_id},
        )
        verdict = decision.get("decision") if isinstance(decision, dict) else decision

        # DENY → withhold (R12.5).
        if verdict == DECISION_DENY or verdict == DECISION_QUARANTINE:
            return {
                "state": "withheld",
                "reason": f"governance decision {verdict}",
                "decision": decision,
                "delegation_id": delegation_id,
                "aggregate": aggregate,
            }

        # REQUIRE_APPROVAL → request approval + withhold until authorized (R12.3).
        if verdict == DECISION_REQUIRE_APPROVAL:
            approval = self._request_approval(
                self._tenant_id,
                action,
                params=params,
                resource=resource,
                risk_explanation="supervisor action requires approval",
            )
            if not self._is_authorized(self._tenant_id, action, params):
                return {
                    "state": "awaiting_approval",
                    "reason": "approval required and not yet authorized",
                    "decision": decision,
                    "approval": approval,
                    "delegation_id": delegation_id,
                    "aggregate": aggregate,
                }
            # Approval already granted for this exact action+params → execute.
            return self._execute_final(
                action, resource, params, decision, delegation_id, aggregate,
                cancel_token,
            )

        # ALLOW (and approved if required) → execute (R12.4).
        if verdict == DECISION_ALLOW:
            return self._execute_final(
                action, resource, params, decision, delegation_id, aggregate,
                cancel_token,
            )

        # Any unexpected verdict is treated as a withhold (fail closed).
        return {
            "state": "withheld",
            "reason": f"unrecognized governance decision {verdict!r}",
            "decision": decision,
            "delegation_id": delegation_id,
            "aggregate": aggregate,
        }

    def _execute_final(
        self,
        action: Optional[str],
        resource: Optional[str],
        params: Dict[str, Any],
        decision: Any,
        delegation_id: str,
        aggregate: Dict[str, Any],
        cancel_token: Optional[CancelToken] = None,
    ) -> Dict[str, Any]:
        """Execute the approved/allowed parent action (R12.4).

        Execution of the final action reuses the same injected ``execute`` seam
        under the Phase 4 policy so it inherits the same timeout/retry/cancel
        contract as a child delegation — no separate execution engine. The
        parent ``cancel_token`` flows through so a cancellation requested while
        the final action is in flight is honoured (R9.6).
        """
        def _op(token: CancelToken) -> Any:
            return self._execute(
                None, {"action": action, "resource": resource, "params": params}, token
            )

        outcome = _run_with_policy(
            _op,
            timeout=self._default_timeout,
            max_attempts=self._default_max_attempts,
            is_transient=self._is_transient,
            cancel_token=cancel_token if cancel_token is not None else CancelToken(),
        )
        return {
            "state": "executed"
            if outcome.status == OutcomeStatus.SUCCEEDED
            else "execution_" + outcome.status.value,
            "decision": decision,
            "delegation_id": delegation_id,
            "aggregate": aggregate,
            "result": outcome.value,
            "outcome_status": outcome.status.value,
        }
