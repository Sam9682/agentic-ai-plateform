"""Explainable risk scoring (Task 16). Pure, deterministic, auditable.

Computes a 0..100 risk score from weighted, named factors so every score comes
with an explanation (which factors contributed and by how much). Never uses an
LLM — the score is reproducible from the inputs alone (SRS §5.5).

Factors (each contributes points, capped at 100 total):
* action_sensitivity: how dangerous the action is (delete/drop > create > read)
* resource_criticality: criticality of the target (prod > staging > dev)
* policy_violation: a DENY/REQUIRE_APPROVAL decision
* behavioral_deviation: anomaly signals (loops, retries, out-of-scope)
* frequency: how often the action recurred in the window
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

_SEVERITIES = ("INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL")

# Action sensitivity by canonical verb substring.
_SENSITIVE_VERBS = {
    "drop": 40, "delete": 35, "destroy": 35, "shutdown": 30,
    "create": 20, "modify": 20, "write": 18, "exec": 25, "shell": 25,
    "reboot": 15, "update": 15,
}


@dataclass
class RiskExplanation:
    score: int
    severity: str
    factors: List[Tuple[str, int]] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "score": self.score,
            "severity": self.severity,
            "factors": [{"name": n, "points": p} for n, p in self.factors],
        }


def _action_sensitivity(action: str) -> int:
    action = (action or "").lower()
    best = 0
    for verb, pts in _SENSITIVE_VERBS.items():
        if verb in action:
            best = max(best, pts)
    return best


def _resource_criticality(resource: str) -> int:
    r = (resource or "").lower()
    if r.startswith("prod") or "prod-" in r:
        return 25
    if r.startswith("stag") or "staging" in r:
        return 10
    return 0


def severity_for_score(score: int) -> str:
    if score >= 85:
        return "CRITICAL"
    if score >= 60:
        return "HIGH"
    if score >= 35:
        return "MEDIUM"
    if score >= 10:
        return "LOW"
    return "INFO"


def score(
    *,
    action: str = "",
    resource: str = "",
    decision: str = "ALLOW",
    behavioral_points: int = 0,
    frequency: int = 0,
) -> RiskExplanation:
    """Compute an explainable risk score. Pure and deterministic.

    Args:
        action: canonical action being scored.
        resource: target resource (for criticality).
        decision: PDP decision (DENY/REQUIRE_APPROVAL add risk).
        behavioral_points: points contributed by anomaly detection.
        frequency: number of recent repetitions of this action.
    """
    factors: List[Tuple[str, int]] = []

    s = _action_sensitivity(action)
    if s:
        factors.append(("action_sensitivity", s))

    rc = _resource_criticality(resource)
    if rc:
        factors.append(("resource_criticality", rc))

    if decision == "DENY":
        factors.append(("policy_violation", 30))
    elif decision == "REQUIRE_APPROVAL":
        factors.append(("policy_gate", 15))
    elif decision == "QUARANTINE":
        factors.append(("containment", 40))

    if behavioral_points:
        factors.append(("behavioral_deviation", int(behavioral_points)))

    if frequency and frequency > 1:
        freq_pts = min(20, (frequency - 1) * 4)
        factors.append(("frequency", freq_pts))

    total = min(100, sum(p for _, p in factors))
    return RiskExplanation(score=total, severity=severity_for_score(total), factors=factors)
