#!/usr/bin/env python3
"""Property test for enforcement-status routing in the OBS detection pass.

Feature: phase5-obs-supervisor, Property 7.

Validates: Requirements 3.2, 3.4.

Task 4.5 (Phase 5, Half A). The detection pass
``src.obs.detection_pass.DetectionPass`` persists each anomaly finding and then
routes it by severity (``DetectionPass._persist_and_route``):

  * a ``CRITICAL`` finding invokes the injected ``quarantine`` callable with the
    anomaly record as evidence and, on success, sets
    ``enforcement_status='quarantined'`` (R3.1);
  * a ``HIGH`` / ``MEDIUM`` / ``LOW`` / ``INFO`` finding is persisted and
    surfaced for review with ``enforcement_status='surfaced'`` and the
    quarantine callable is NOT invoked (R3.2).

Property 7 (design.md): *for any* set of findings across random severities, the
``enforcement_status`` on each persisted record is ``'quarantined'`` iff the
finding's severity is ``CRITICAL`` and quarantine succeeded, and ``'surfaced'``
for every HIGH/MEDIUM/LOW/INFO finding; furthermore the quarantine collaborator
is invoked exactly once per CRITICAL finding (with the anomaly as evidence) and
never for a non-CRITICAL finding. Requirement 3.4: the persisted enforcement
status reflects whether quarantine was invoked -- verified here against a
``set_enforcement`` spy on the mocked OBS repository.

The test drives ``DetectionPass`` with mock collaborators only: an injected
``analyze`` that returns findings of generated severities, a mocked OBS repo
(spying ``record_anomaly`` / ``set_enforcement``), and a quarantine spy. No live
Docker, PostgreSQL, SSH, or ZAF, and no LLM/ML.

Run directly:
    python3 tests/test_phase5_enforcement_status_routing.py
Or via pytest:
    pytest tests/test_phase5_enforcement_status_routing.py
"""
import os
import sys

from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.obs.detection_pass import DetectionPass  # noqa: E402
from src.obs.signal_bundle import WindowConfig  # noqa: E402


# --------------------------------------------------------------------------- #
# Strategies
# --------------------------------------------------------------------------- #
_SEVERITIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
_severity = st.sampled_from(_SEVERITIES)

NOW = 1_000_000.0


def _finding(index, severity):
    """A minimal anomaly-engine finding of the given severity."""
    return {
        "rule_id": f"rule.{index}",
        "severity": severity,
        "evidence": [f"evidence-{index}"],
    }


# --------------------------------------------------------------------------- #
# Mock collaborators
# --------------------------------------------------------------------------- #
class _FakeObsRepo:
    """Spies ``record_anomaly`` and ``set_enforcement`` with no live DB."""

    def __init__(self):
        self.records = []           # args passed to record_anomaly
        self.enforcements = []      # (db_id, status, kwargs) from set_enforcement
        self._next_id = 0

    def record_anomaly(self, tenant_id, agent_identity, rule_id, severity,
                       risk_score, evidence):
        self._next_id += 1
        self.records.append(
            {
                "db_id": self._next_id,
                "tenant_id": tenant_id,
                "agent_identity": agent_identity,
                "rule_id": rule_id,
                "severity": severity,
                "risk_score": risk_score,
                "evidence": evidence,
            }
        )
        return self._next_id

    def set_enforcement(self, tenant_id, anomaly_db_id, status, *,
                        runtime_id, session_id, recommended_action):
        self.enforcements.append(
            {
                "db_id": anomaly_db_id,
                "status": status,
                "runtime_id": runtime_id,
                "session_id": session_id,
                "recommended_action": recommended_action,
            }
        )


class _QuarantineSpy:
    """Records every quarantine invocation; succeeds by default."""

    def __init__(self):
        self.calls = []

    def __call__(self, *, evidence, agent, reason):
        self.calls.append({"evidence": evidence, "agent": agent, "reason": reason})


def _make_pass(findings, obs_repo, quarantine):
    """Build a DetectionPass whose injected analyze returns ``findings``."""
    agent = {
        "identity": "agent-1",
        "runtime_id": "rt-1",
        "session_id": "sess-1",
        "allowed_globs": [],
        "observations": [],
        "events": [],
    }

    def analyze(signals, thresholds):
        return {"anomalies": list(findings), "risk": {"score": 50}}

    return DetectionPass(
        tenant_id=7,
        obs_repo=obs_repo,
        rt_repo=None,
        analyze=analyze,
        score_of=None,
        quarantine=quarantine,
        cfg=WindowConfig(),
        clock=lambda: NOW,
        agents_source=lambda: [agent],
    )


# --------------------------------------------------------------------------- #
# Property
# --------------------------------------------------------------------------- #
@settings(max_examples=100, deadline=None)
@given(severities=st.lists(_severity, min_size=0, max_size=20))
def test_enforcement_status_reflects_quarantine_routing(severities):
    """enforcement_status == 'quarantined' iff CRITICAL & quarantine succeeded;
    'surfaced' for HIGH/MEDIUM/LOW/INFO; quarantine invoked iff CRITICAL.

    Validates: Requirements 3.2, 3.4.
    """
    findings = [_finding(i, sev) for i, sev in enumerate(severities)]
    obs_repo = _FakeObsRepo()
    quarantine = _QuarantineSpy()

    records = _make_pass(findings, obs_repo, quarantine).run_cycle()

    # One persisted record per finding, in order.
    assert len(records) == len(findings)

    expected_critical = sum(1 for s in severities if s == "CRITICAL")

    for finding, record in zip(findings, records):
        severity = finding["severity"]
        if severity == "CRITICAL":
            # Routed to quarantine; status reflects a successful quarantine.
            assert record["enforcement_status"] == "quarantined"
        else:
            # HIGH/MEDIUM/LOW/INFO -> surfaced, never quarantined (R3.2).
            assert record["enforcement_status"] == "surfaced"

    # Quarantine invoked exactly once per CRITICAL finding, never otherwise.
    assert len(quarantine.calls) == expected_critical
    for call in quarantine.calls:
        # Evidence passed to quarantine is the persisted anomaly record (R3.1).
        assert call["evidence"]["severity"] == "CRITICAL"

    # R3.4: the persisted enforcement status (via set_enforcement) matches the
    # routed status on every record, reflecting whether quarantine was invoked.
    assert len(obs_repo.enforcements) == len(records)
    for record, enforced in zip(records, obs_repo.enforcements):
        assert enforced["db_id"] == record["db_id"]
        assert enforced["status"] == record["enforcement_status"]
        status = enforced["status"]
        if record["severity"] == "CRITICAL":
            assert status == "quarantined"
        else:
            assert status == "surfaced"


@settings(max_examples=100, deadline=None)
@given(
    pre=st.lists(_severity, min_size=0, max_size=8),
    post=st.lists(_severity, min_size=0, max_size=8),
)
def test_non_critical_never_quarantines_around_critical(pre, post):
    """A CRITICAL finding is the ONLY severity that triggers quarantine, even
    when interleaved with non-critical findings; non-critical stay 'surfaced'.

    Validates: Requirements 3.2, 3.4.
    """
    severities = list(pre) + ["CRITICAL"] + list(post)
    findings = [_finding(i, sev) for i, sev in enumerate(severities)]
    obs_repo = _FakeObsRepo()
    quarantine = _QuarantineSpy()

    records = _make_pass(findings, obs_repo, quarantine).run_cycle()

    surfaced = [r for r in records if r["enforcement_status"] == "surfaced"]
    quarantined = [r for r in records if r["enforcement_status"] == "quarantined"]

    # Exactly the CRITICAL findings are quarantined.
    assert len(quarantined) == sum(1 for s in severities if s == "CRITICAL")
    assert all(r["severity"] == "CRITICAL" for r in quarantined)
    # Every non-critical finding is surfaced, never quarantined.
    assert all(r["severity"] != "CRITICAL" for r in surfaced)
    assert len(surfaced) == sum(1 for s in severities if s != "CRITICAL")
    # Quarantine invoked once per CRITICAL, never for a non-critical finding.
    assert len(quarantine.calls) == len(quarantined)


if __name__ == "__main__":
    test_enforcement_status_reflects_quarantine_routing()
    test_non_critical_never_quarantines_around_critical()
    print("ok")
