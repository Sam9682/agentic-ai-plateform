"""ZAF policy decision point — pure evaluator (Task 11).

Evaluates a protected action against a tenant's policy rule set + the agent's
explicit permissions and returns one of ALLOW / DENY / REQUIRE_APPROVAL /
QUARANTINE, with an explanation. Pure and side-effect-free so it is fully
property-testable; the DB-backed service layer loads rules and records
decisions.

Enforcement guarantees (SRS §4.4, §9):
* **Deny precedence.** If any matching rule denies, the decision is DENY,
  regardless of allow rules.
* **Quarantine precedence over allow/approval** (a containment signal), but
  explicit DENY still wins over QUARANTINE.
* **Fail closed.** Evaluating with no decision service / no rules yields DENY for
  any action not explicitly covered by a permission + allow — i.e. default deny.
* RBAC/ABAC: rules may carry conditions on context attributes (risk_level, time
  window, resource prefix); a rule matches only when all its conditions hold.

A rule is a dict::

    {"action": "openstack.server.*", "decision": "REQUIRE_APPROVAL",
     "condition": {"risk_level": "high"}}

``action`` supports ``*`` glob matching. ``condition`` keys supported:
  risk_level (min threshold), resource_prefix, not_before/not_after (HH:MM UTC),
  min_risk_score / max_risk_score.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

ALLOW = "ALLOW"
DENY = "DENY"
REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
QUARANTINE = "QUARANTINE"

VALID_DECISIONS = (ALLOW, DENY, REQUIRE_APPROVAL, QUARANTINE)

# Decision precedence when multiple rules match (higher wins), EXCEPT that an
# explicit DENY always wins. We special-case DENY in the resolver.
_PRECEDENCE = {ALLOW: 0, REQUIRE_APPROVAL: 1, QUARANTINE: 2, DENY: 3}

_RISK_LEVELS = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


@dataclass
class Decision:
    decision: str
    reason: str
    matched_rule: Optional[Dict[str, Any]] = None
    risk_score: int = 0
    extra: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "decision": self.decision,
            "reason": self.reason,
            "matched_rule": self.matched_rule,
            "risk_score": self.risk_score,
            **self.extra,
        }


def _condition_matches(condition: Dict[str, Any], context: Dict[str, Any]) -> bool:
    """Return True when every clause of a rule condition holds in ``context``."""
    if not condition:
        return True
    ctx_risk = _RISK_LEVELS.get(str(context.get("risk_level", "info")).lower(), 0)

    if "risk_level" in condition:
        required = _RISK_LEVELS.get(str(condition["risk_level"]).lower(), 0)
        if ctx_risk < required:
            return False
    if "min_risk_score" in condition:
        if int(context.get("risk_score", 0)) < int(condition["min_risk_score"]):
            return False
    if "max_risk_score" in condition:
        if int(context.get("risk_score", 0)) > int(condition["max_risk_score"]):
            return False
    if "resource_prefix" in condition:
        resource = str(context.get("resource", ""))
        if not resource.startswith(str(condition["resource_prefix"])):
            return False
    if "not_before" in condition or "not_after" in condition:
        now_hhmm = context.get("time_hhmm")
        if now_hhmm is None:
            return False  # fail closed: time-bound rule with no clock -> no match
        if "not_before" in condition and now_hhmm < condition["not_before"]:
            return False
        if "not_after" in condition and now_hhmm > condition["not_after"]:
            return False
    return True


def _action_matches(pattern: str, action: str) -> bool:
    return fnmatch.fnmatchcase(action, pattern)


def _permission_allows(action: str, permissions: List[str]) -> bool:
    """Return True when any granted permission glob matches the action."""
    return any(fnmatch.fnmatchcase(action, p) for p in (permissions or []))


def evaluate(
    action: str,
    *,
    rules: Optional[List[Dict[str, Any]]] = None,
    permissions: Optional[List[str]] = None,
    context: Optional[Dict[str, Any]] = None,
) -> Decision:
    """Evaluate ``action`` and return a :class:`Decision`. Pure, fail-closed.

    Resolution:
      1. Collect every rule whose action glob + condition match.
      2. If any matched rule is DENY -> DENY (deny precedence).
      3. Else pick the highest-precedence matched decision
         (QUARANTINE > REQUIRE_APPROVAL > ALLOW).
      4. If no rule matched: ALLOW only when a granted permission covers the
         action; otherwise DENY (default deny / fail closed).
    """
    context = dict(context or {})
    rules = rules or []
    permissions = permissions or []
    risk_score = int(context.get("risk_score", 0))

    matched = [
        r for r in rules
        if isinstance(r, dict)
        and r.get("decision") in VALID_DECISIONS
        and _action_matches(str(r.get("action", "")), action)
        and _condition_matches(r.get("condition") or {}, context)
    ]

    if matched:
        # Deny precedence: any matching DENY wins outright.
        deny = next((r for r in matched if r["decision"] == DENY), None)
        if deny is not None:
            return Decision(DENY, "explicit deny rule matched", deny, risk_score)
        best = max(matched, key=lambda r: _PRECEDENCE[r["decision"]])
        return Decision(best["decision"], "matched policy rule", best, risk_score)

    # No rule matched -> default deny unless an explicit permission allows it.
    if _permission_allows(action, permissions):
        return Decision(ALLOW, "granted by agent permission", None, risk_score)
    return Decision(DENY, "default deny: no matching rule or permission", None, risk_score)


def evaluate_fail_closed(
    action: str,
    *,
    rules: Optional[List[Dict[str, Any]]] = None,
    permissions: Optional[List[str]] = None,
    context: Optional[Dict[str, Any]] = None,
    service_available: bool = True,
) -> Decision:
    """Evaluate, but DENY unconditionally when the decision service is down.

    The infra proxy / MCP gateway call this with ``service_available=False`` when
    the PDP (or its backing store) is unreachable, so protected actions fail
    closed rather than defaulting open.
    """
    if not service_available:
        return Decision(DENY, "policy decision service unavailable (fail closed)",
                        None, int((context or {}).get("risk_score", 0)))
    return evaluate(action, rules=rules, permissions=permissions, context=context)
