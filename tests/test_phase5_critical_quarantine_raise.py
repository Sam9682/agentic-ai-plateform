#!/usr/bin/env python3
"""Property test for CRITICAL quarantine + raise-on-failure.

Feature: phase5-obs-supervisor, Property 6.

Validates: Requirements 3.1, 3.3.

Task 4.4 (Phase 5, Half A). The detection pass ``src.obs.detection_pass`` routes
a finding by severity in ``DetectionPass._persist_and_route``. For a CRITICAL
finding it MUST invoke the injected ``quarantine`` callable passing the just-
persisted anomaly record as ``evidence`` and the finding ``rule_id`` as
``reason`` (R3.1), and on success set ``enforcement_status='quarantined'``. If
the ``quarantine`` callable raises, the pass MUST log and re-raise the failure
as a ``DetectionError`` rather than swallow it and continue with enforcement
disabled (R3.3).

Property 6 (design.md): *for any* CRITICAL anomaly produced by the engine,

  (1) with a succeeding ``quarantine`` mock, ``run_cycle()`` calls ``quarantine``
      exactly once with the anomaly record as ``evidence`` (and the ``rule_id``
      as ``reason``), and the persisted record's ``enforcement_status`` becomes
      ``'quarantined'``; and

  (2) with a ``quarantine`` mock that raises, ``run_cycle()`` raises
      ``DetectionError`` (the failure is surfaced, never swallowed).

The module under test is driven entirely through injected collaborators (a mock
OBS repo, a mock analyze callable returning the generated CRITICAL findings, and
the quarantine mock), so there is no live DB, no ZAF, and no LLM/ML.

Run directly:
    python3 tests/test_phase5_critical_quarantine_raise.py
Or via pytest:
    pytest tests/test_phase5_critical_quarantine_raise.py
"""
import os
import sys

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.obs.detection_pass import DetectionError, DetectionPass  # noqa: E402
from src.obs.signal_bundle import WindowConfig  # noqa: E402


# --------------------------------------------------------------------------- #
# Test doubles
# --------------------------------------------------------------------------- #
class FakeObsRepo:
    """Minimal OBS repo seam: record_anomaly returns a db id, set_enforcement
    captures the final enforcement status written to the row."""

    def __init__(self):
        self.recorded = []
        self.enforcements = []
        self._next_id = 1

    def record_anomaly(self, tenant_id, agent_identity, rule_id, severity,
                        risk_score, evidence):
        db_id = self._next_id
        self._next_id += 1
        self.recorded.append(
            {
                "db_id": db_id,
                "tenant_id": tenant_id,
                "agent_identity": agent_identity,
                "rule_id": rule_id,
                "severity": severity,
                "risk_score": risk_score,
                "evidence": evidence,
            }
        )
        return db_id

    def set_enforcement(self, tenant_id, anomaly_db_id, status, *,
                        runtime_id, session_id, recommended_action):
        self.enforcements.append(
            {
                "tenant_id": tenant_id,
                "anomaly_db_id": anomaly_db_id,
                "status": status,
                "runtime_id": runtime_id,
                "session_id": session_id,
                "recommended_action": recommended_action,
            }
        )


class SpyQuarantine:
    """A succeeding quarantine coordinator seam that records its calls."""

    def __init__(self):
        self.calls = []

    def __call__(self, *, evidence, agent, reason):
        self.calls.append({"evidence": evidence, "agent": agent, "reason": reason})
        return {"status": "quarantined"}


class RaisingQuarantine:
    """A quarantine coordinator seam that always raises (containment failure)."""

    def __init__(self, exc=None):
        self.calls = []
        self._exc = exc or RuntimeError("quarantine backend unavailable")

    def __call__(self, *, evidence, agent, reason):
        self.calls.append({"evidence": evidence, "agent": agent, "reason": reason})
        raise self._exc


def _make_pass(findings, quarantine, obs_repo=None):
    """Build a DetectionPass whose single agent yields the given findings.

    ``analyze`` is a mock that returns the generated CRITICAL findings for the
    one monitored agent. The agent entry pre-loads empty observations/events so
    the pass never touches a live runtime-monitor repo.
    """
    obs_repo = obs_repo or FakeObsRepo()
    agent = {
        "identity": "agent-x",
        "runtime_id": "rt-1",
        "session_id": "sess-1",
        "allowed_globs": [],
        "observations": [],
        "events": [],
    }

    def analyze(signals, thresholds):
        return {"anomalies": list(findings), "risk": {"score": 90}}

    return DetectionPass(
        tenant_id=7,
        obs_repo=obs_repo,
        rt_repo=None,
        analyze=analyze,
        score_of=None,
        quarantine=quarantine,
        cfg=WindowConfig(window_seconds=300, loop_threshold=5, allowlist=()),
        clock=lambda: 1_000_000.0,
        agents_source=lambda: [agent],
    )


# --------------------------------------------------------------------------- #
# Strategies: CRITICAL findings
# --------------------------------------------------------------------------- #
_RULE_IDS = st.sampled_from(
    ["execution.loop", "authz.repeat_failure", "resource.spike", "process.anomaly"]
)

# Evidence as a list of behavioral-shape strings (what the engine emits); kept
# small and non-sensitive.
_EVIDENCE = st.lists(
    st.sampled_from(["op_a", "op_b", "op_c", "cmd_x", "cmd_y"]),
    min_size=0,
    max_size=6,
)


def _critical_finding(rule_id, evidence):
    return {"severity": "CRITICAL", "rule_id": rule_id, "evidence": evidence}


# --------------------------------------------------------------------------- #
# Property 6
# --------------------------------------------------------------------------- #
@settings(max_examples=100, deadline=None)
@given(rule_id=_RULE_IDS, evidence=_EVIDENCE)
def test_critical_triggers_quarantine_with_anomaly_evidence(rule_id, evidence):
    """A CRITICAL finding quarantines with the anomaly record as evidence and
    marks enforcement_status 'quarantined'.

    Validates: Requirements 3.1, 3.3.
    """
    quarantine = SpyQuarantine()
    obs_repo = FakeObsRepo()
    passer = _make_pass(
        [_critical_finding(rule_id, evidence)], quarantine, obs_repo=obs_repo
    )

    records = passer.run_cycle()

    # Exactly one finding persisted and routed.
    assert len(records) == 1
    record = records[0]

    # Quarantine invoked exactly once ...
    assert len(quarantine.calls) == 1
    call = quarantine.calls[0]

    # ... with the anomaly record as evidence (R3.1) ...
    assert call["evidence"] is record
    assert call["evidence"]["severity"] == "CRITICAL"
    assert call["evidence"]["rule_id"] == rule_id

    # ... and the rule_id as the quarantine reason.
    assert call["reason"] == rule_id

    # Enforcement status reflects a successful quarantine, on the record and in
    # the persisted set_enforcement call (R3.4 linkage of this success path).
    assert record["enforcement_status"] == "quarantined"
    assert obs_repo.enforcements[-1]["status"] == "quarantined"
    assert record["recommended_action"] == "QUARANTINE"


@settings(max_examples=100, deadline=None)
@given(rule_id=_RULE_IDS, evidence=_EVIDENCE)
def test_raising_quarantine_is_reraised_as_detection_error(rule_id, evidence):
    """A quarantine that raises is logged and re-raised as DetectionError;
    the failure is never swallowed.

    Validates: Requirements 3.1, 3.3.
    """
    quarantine = RaisingQuarantine()
    passer = _make_pass([_critical_finding(rule_id, evidence)], quarantine)

    with pytest.raises(DetectionError):
        passer.run_cycle()

    # The quarantine was actually attempted for the CRITICAL finding before the
    # failure propagated (so the raise comes from the quarantine path, R3.1/3.3).
    assert len(quarantine.calls) == 1
    assert quarantine.calls[0]["reason"] == rule_id


if __name__ == "__main__":
    test_critical_triggers_quarantine_with_anomaly_evidence()
    test_raising_quarantine_is_reraised_as_detection_error()
    print("ok")
