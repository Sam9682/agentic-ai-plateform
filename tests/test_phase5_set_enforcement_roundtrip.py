#!/usr/bin/env python3
"""Unit test for ``obs_repository.set_enforcement`` + extended ``list_anomalies``.

Feature: phase5-obs-supervisor (Task 3.2).

Validates that the additive enforcement/routing columns round-trip:
* ``record_anomaly`` inserts a row (backward-compatible path, new columns
  defaulted);
* ``set_enforcement`` populates ``enforcement_status``, ``runtime_id``,
  ``session_id`` and ``recommended_action`` on that row;
* ``list_anomalies`` surfaces those four fields back out;
* a legacy ``record_anomaly`` caller that never calls ``set_enforcement``
  still succeeds and is returned by ``list_anomalies`` with defaulted
  enforcement fields.

No live DB: a fake ``db_manager`` is injected by monkeypatching
``obs_repository._get_db``. The fake ``execute_query`` keeps an in-memory
table and interprets the INSERT / UPDATE / SELECT the repository issues,
so the real repository functions are exercised end to end.

Run directly:
    python3 tests/test_phase5_set_enforcement_roundtrip.py
Or via pytest:
    pytest tests/test_phase5_set_enforcement_roundtrip.py -q

_Requirements: 1.3, 3.4, 13.4_
"""

import datetime as _dt
import json
import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.obs import obs_repository as repo  # noqa: E402


class _FakeDb:
    """In-memory stand-in for ``database_postgres.db_manager``.

    Models just enough of ``agent_anomalies`` for the repository's three
    statements. Rows carry the additive columns with their SQL defaults
    (``enforcement_status='pending'``, the rest NULL) so that a row inserted
    by ``record_anomaly`` and never touched by ``set_enforcement`` still reads
    back with defaulted enforcement fields.
    """

    def __init__(self):
        self._seq = 0
        self.rows = []  # list of dict rows

    def execute_query(self, sql, params=None, fetch_one=False, fetch_all=False):
        s = " ".join(sql.split()).upper()
        params = params or ()

        if s.startswith("INSERT INTO AGENT_ANOMALIES"):
            tenant_id, agent_identity, rule_id, severity, risk_score, evidence = params
            self._seq += 1
            self.rows.append({
                "id": self._seq,
                "tenant_id": int(tenant_id),
                "agent_identity": agent_identity,
                "rule_id": rule_id,
                "severity": severity,
                "risk_score": int(risk_score),
                "evidence": evidence,  # JSON string, as the repo passes it
                "status": "open",
                "detected_at": _dt.datetime(2024, 1, 1, 0, 0, self._seq % 60),
                # additive columns with SQL defaults
                "enforcement_status": "pending",
                "runtime_id": None,
                "session_id": None,
                "recommended_action": None,
            })
            assert fetch_one
            return (self._seq,)

        if s.startswith("UPDATE AGENT_ANOMALIES SET ENFORCEMENT_STATUS"):
            (status, runtime_id, session_id, recommended_action,
             tenant_id, anomaly_id) = params
            updated = 0
            for r in self.rows:
                if r["tenant_id"] == int(tenant_id) and r["id"] == int(anomaly_id):
                    r["enforcement_status"] = status
                    r["runtime_id"] = runtime_id
                    r["session_id"] = session_id
                    r["recommended_action"] = recommended_action
                    updated += 1
            return updated

        if s.startswith("SELECT ID, AGENT_IDENTITY, RULE_ID"):
            tenant_id, limit = params
            matching = [r for r in self.rows if r["tenant_id"] == int(tenant_id)]
            matching.sort(key=lambda r: r["detected_at"], reverse=True)
            matching = matching[: int(limit)]
            assert fetch_all
            return [
                (r["id"], r["agent_identity"], r["rule_id"], r["severity"],
                 r["risk_score"], r["evidence"], r["status"], r["detected_at"],
                 r["enforcement_status"], r["runtime_id"], r["session_id"],
                 r["recommended_action"])
                for r in matching
            ]

        raise AssertionError(f"unexpected query: {sql}")


@pytest.fixture()
def fake_db(monkeypatch):
    fake = _FakeDb()
    monkeypatch.setattr(repo, "_get_db", lambda: fake)
    return fake


def _find(anomalies, anomaly_id):
    return next(a for a in anomalies if a["id"] == anomaly_id)


def test_set_enforcement_round_trips_through_list_anomalies(fake_db):
    tenant_id = 7
    anomaly_id = repo.record_anomaly(
        tenant_id, agent_identity="agent://alpha", rule_id="execution.loop",
        severity="CRITICAL", risk_score=95, evidence=["cmd x6"],
    )

    ok = repo.set_enforcement(
        tenant_id, anomaly_id, "quarantined",
        runtime_id="rt-123", session_id="sess-abc",
        recommended_action="QUARANTINE",
    )
    assert ok is True

    row = _find(repo.list_anomalies(tenant_id), anomaly_id)
    assert row["enforcement_status"] == "quarantined"
    assert row["runtime_id"] == "rt-123"
    assert row["session_id"] == "sess-abc"
    assert row["recommended_action"] == "QUARANTINE"
    # core fields still intact + evidence decoded back to a list
    assert row["rule_id"] == "execution.loop"
    assert row["severity"] == "CRITICAL"
    assert row["evidence"] == ["cmd x6"]


def test_legacy_record_anomaly_still_succeeds_with_defaulted_enforcement(fake_db):
    tenant_id = 7
    # A legacy caller that never calls set_enforcement.
    anomaly_id = repo.record_anomaly(
        tenant_id, agent_identity="agent://legacy", rule_id="behavior.out_of_scope",
        severity="HIGH", risk_score=60, evidence=["denied delete"],
    )
    assert isinstance(anomaly_id, int)

    row = _find(repo.list_anomalies(tenant_id), anomaly_id)
    # new columns are present but defaulted — backward compatible.
    assert row["enforcement_status"] == "pending"
    assert row["runtime_id"] is None
    assert row["session_id"] is None
    assert row["recommended_action"] is None


def test_set_enforcement_is_tenant_scoped(fake_db):
    # A row for tenant 1; a set_enforcement for the same id under tenant 2
    # must not touch it (0 rows updated).
    anomaly_id = repo.record_anomaly(
        1, "agent://t1", "execution.loop", "MEDIUM", 40, ["x"],
    )
    updated = repo.set_enforcement(
        2, anomaly_id, "surfaced",
        runtime_id="rt", session_id="s", recommended_action="SURFACE",
    )
    assert updated is False

    row = _find(repo.list_anomalies(1), anomaly_id)
    assert row["enforcement_status"] == "pending"


def test_enforcement_json_evidence_roundtrip_matches_record(fake_db):
    # Guard that record_anomaly serialized evidence and list_anomalies decodes
    # it, independent of the enforcement update path.
    evidence = ["a", "b", "c"]
    anomaly_id = repo.record_anomaly(
        3, "agent://x", "process.suspicious", "HIGH", 70, evidence,
    )
    repo.set_enforcement(
        3, anomaly_id, "surfaced",
        runtime_id="rt-9", session_id="sess-9", recommended_action="SURFACE",
    )
    row = _find(repo.list_anomalies(3), anomaly_id)
    assert row["evidence"] == evidence
    assert json.dumps(row["evidence"]) == json.dumps(evidence)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
