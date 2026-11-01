#!/usr/bin/env python3
"""Property test for anomaly field completeness.

Feature: phase5-obs-supervisor, Property 2.

Validates: Requirements 1.2, 1.3.

Task 4.3 (Phase 5, Half A). The OBS detection pass
``src.obs.detection_pass.DetectionPass`` persists *each* finding returned by the
anomaly engine for an observation window (R1.2) and records every persisted
Anomaly with a complete field set (R1.3): an ``anomaly_id``, an ``agent_id``, a
``runtime_id``, a ``session_id``, a ``severity``, a ``rule_id``, ``evidence``, a
detection timestamp (``detected_at``), a ``recommended_action``, and an
``enforcement_status`` (plus the ``db_id`` of the inserted row).

Property 2 (design.md): *for any* set of engine findings across every severity
(including ``CRITICAL`` routed through a quarantine that succeeds), running one
detection cycle returns exactly one persisted record per finding, and every
returned/persisted record carries all required fields present and non-``None``.
Routing fields (``runtime_id``/``session_id``/``recommended_action``) are also
propagated to the OBS repository via ``set_enforcement``.

The test drives ``DetectionPass`` with injected mock collaborators only (no live
DB, no live ZAF, no LLM/ML): an ``analyze`` stub returns the generated findings,
the OBS repo records the ``db_id`` and captures ``set_enforcement`` calls, and
the quarantine callable succeeds. ``runtime_id``/``session_id`` come from the
agent entry, so they are supplied per the module contract.

Run directly:
    python3 tests/test_phase5_anomaly_field_completeness.py
Or via pytest:
    pytest tests/test_phase5_anomaly_field_completeness.py
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
# Required field set the Detection_Pass must put on every persisted record
# (R1.3). ``db_id`` is the inserted row id and is also required by the module
# contract.
# --------------------------------------------------------------------------- #
_REQUIRED_FIELDS = (
    "anomaly_id",
    "db_id",
    "agent_id",
    "runtime_id",
    "session_id",
    "severity",
    "rule_id",
    "evidence",
    "detected_at",
    "recommended_action",
    "enforcement_status",
)

_SEVERITIES = st.sampled_from(["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"])

# Evidence is a list of behavioral-shape strings (never prompts/secrets).
_evidence_strategy = st.lists(
    st.text(min_size=1, max_size=40), min_size=0, max_size=5
)


def _finding(rule_id, severity, evidence):
    return {"rule_id": rule_id, "severity": severity, "evidence": evidence}


# A list of engine findings; each has a non-empty rule_id, a severity drawn
# across the full enum, and some evidence.
_findings_strategy = st.lists(
    st.builds(
        _finding,
        rule_id=st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz._",
            min_size=1,
            max_size=24,
        ),
        severity=_SEVERITIES,
        evidence=_evidence_strategy,
    ),
    min_size=0,
    max_size=12,
)


class _FakeObsRepo:
    """Captures ``record_anomaly`` inserts and ``set_enforcement`` calls."""

    def __init__(self):
        self._next_id = 1
        self.enforcement_calls = []

    def record_anomaly(self, tenant_id, identity, rule_id, severity, score, evidence):
        db_id = self._next_id
        self._next_id += 1
        return db_id

    def set_enforcement(
        self,
        tenant_id,
        anomaly_db_id,
        status,
        *,
        runtime_id,
        session_id,
        recommended_action,
    ):
        self.enforcement_calls.append(
            {
                "tenant_id": tenant_id,
                "anomaly_db_id": anomaly_db_id,
                "status": status,
                "runtime_id": runtime_id,
                "session_id": session_id,
                "recommended_action": recommended_action,
            }
        )


@settings(max_examples=100, deadline=None)
@given(
    findings=_findings_strategy,
    runtime_id=st.text(min_size=1, max_size=20),
    session_id=st.text(min_size=1, max_size=20),
    identity=st.text(min_size=1, max_size=20),
)
def test_anomaly_field_completeness(findings, runtime_id, session_id, identity):
    """Every persisted record carries all required, non-None fields, and the
    routing fields reach ``set_enforcement``.

    Validates: Requirements 1.2, 1.3.
    """
    obs_repo = _FakeObsRepo()
    quarantine_calls = []

    def analyze(signals, thresholds):
        # Return the generated findings verbatim; a benign risk snapshot.
        return {"anomalies": list(findings), "risk": {"score": 10}}

    def quarantine(**kwargs):
        # CRITICAL routing path: succeeds (records the call).
        quarantine_calls.append(kwargs)
        return {"quarantined": True}

    # runtime_id/session_id come from the agent entry (module contract).
    agent = {
        "identity": identity,
        "runtime_id": runtime_id,
        "session_id": session_id,
        "allowed_globs": [],
        "observations": [],
        "events": [],
    }

    pass_ = DetectionPass(
        tenant_id=7,
        obs_repo=obs_repo,
        rt_repo=None,
        analyze=analyze,
        score_of=None,
        quarantine=quarantine,
        cfg=WindowConfig(),
        clock=lambda: 1_000_000.0,
        agents_source=lambda: [agent],
    )

    records = pass_.run_cycle()

    # R1.2: exactly one persisted record per engine finding.
    assert len(records) == len(findings)
    # One set_enforcement call per persisted record (R3.4 persistence of routing).
    assert len(obs_repo.enforcement_calls) == len(findings)

    critical_count = 0
    for rec, finding, call in zip(records, findings, obs_repo.enforcement_calls):
        # R1.3: every required field present and non-None.
        for field in _REQUIRED_FIELDS:
            assert field in rec, f"missing field {field!r} in {rec!r}"
            assert rec[field] is not None, f"field {field!r} is None in {rec!r}"

        # Fields carry the expected provenance.
        assert rec["agent_id"] == identity
        assert rec["runtime_id"] == runtime_id   # from the agent entry
        assert rec["session_id"] == session_id   # from the agent entry
        assert rec["severity"] == finding["severity"]
        assert rec["rule_id"] == finding["rule_id"]
        assert isinstance(rec["anomaly_id"], str) and rec["anomaly_id"]
        assert isinstance(rec["db_id"], int)
        # detected_at is an ISO-8601 detection timestamp string.
        assert isinstance(rec["detected_at"], str) and rec["detected_at"]

        # set_enforcement received the routing fields for this record (R3.4).
        assert call["anomaly_db_id"] == rec["db_id"]
        assert call["runtime_id"] == runtime_id
        assert call["session_id"] == session_id
        assert call["recommended_action"] == rec["recommended_action"]
        assert call["status"] == rec["enforcement_status"]

        if (finding["severity"] or "").upper() == "CRITICAL":
            critical_count += 1
            assert rec["enforcement_status"] == "quarantined"
        else:
            assert rec["enforcement_status"] == "surfaced"

    # Every CRITICAL finding routed through the (succeeding) quarantine.
    assert len(quarantine_calls) == critical_count


if __name__ == "__main__":
    test_anomaly_field_completeness()
    print("ok")
