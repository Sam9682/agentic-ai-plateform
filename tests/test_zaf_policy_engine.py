#!/usr/bin/env python3
"""Tests for the ZAF policy engine + governance (Task 11).

Feature: ZAF policy decision point (SRS §4.4, §9).

Validates (pure engine):
* deny precedence: a matching DENY beats any ALLOW/REQUIRE_APPROVAL/QUARANTINE.
* default deny: an action with no matching rule and no permission is DENIED.
* permission allow: an action covered by a granted glob is ALLOWED when no rule
  matches.
* fail closed: when the decision service is unavailable, every action is DENIED.
* conditions: risk_level / resource_prefix gate rule matching.
* SRS example: list -> ALLOW, delete -> REQUIRE_APPROVAL, database.drop -> DENY.
* YAML loader parses the SRS policy document.
* route: /evaluate returns the decision with stubbed repo.

Run directly:
    python3 tests/test_zaf_policy_engine.py
Or via pytest:
    pytest tests/test_zaf_policy_engine.py
"""
import os
import sys

from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.zaf import policy_engine as pe  # noqa: E402
from src.zaf import policy_repository as prepo  # noqa: E402


_SRS_RULES = [
    {"action": "openstack.server.list", "decision": "ALLOW"},
    {"action": "openstack.server.create", "decision": "REQUIRE_APPROVAL"},
    {"action": "openstack.server.delete", "decision": "REQUIRE_APPROVAL"},
    {"action": "database.drop", "decision": "DENY"},
    {"action": "shell.command", "decision": "REQUIRE_APPROVAL",
     "condition": {"risk_level": "high"}},
]


def test_srs_example_decisions():
    assert pe.evaluate("openstack.server.list", rules=_SRS_RULES).decision == pe.ALLOW
    assert pe.evaluate("openstack.server.delete", rules=_SRS_RULES).decision == pe.REQUIRE_APPROVAL
    assert pe.evaluate("database.drop", rules=_SRS_RULES).decision == pe.DENY


def test_default_deny_without_rule_or_permission():
    assert pe.evaluate("openstack.server.reboot", rules=_SRS_RULES).decision == pe.DENY


def test_permission_allows_when_no_rule_matches():
    d = pe.evaluate("openstack.server.get", rules=_SRS_RULES,
                    permissions=["openstack.server.*"])
    assert d.decision == pe.ALLOW


def test_deny_precedence_over_allow():
    rules = [
        {"action": "x.*", "decision": "ALLOW"},
        {"action": "x.danger", "decision": "DENY"},
    ]
    assert pe.evaluate("x.danger", rules=rules).decision == pe.DENY
    assert pe.evaluate("x.safe", rules=rules).decision == pe.ALLOW


def test_quarantine_beats_allow_and_approval():
    rules = [
        {"action": "x.*", "decision": "ALLOW"},
        {"action": "x.*", "decision": "REQUIRE_APPROVAL"},
        {"action": "x.*", "decision": "QUARANTINE"},
    ]
    assert pe.evaluate("x.y", rules=rules).decision == pe.QUARANTINE


def test_condition_risk_level_gates_rule():
    rules = [{"action": "shell.command", "decision": "REQUIRE_APPROVAL",
              "condition": {"risk_level": "high"}}]
    # low risk -> rule doesn't match -> default deny
    assert pe.evaluate("shell.command", rules=rules,
                       context={"risk_level": "low"}).decision == pe.DENY
    # high risk -> rule matches
    assert pe.evaluate("shell.command", rules=rules,
                       context={"risk_level": "high"}).decision == pe.REQUIRE_APPROVAL


def test_resource_prefix_condition():
    rules = [{"action": "openstack.server.delete", "decision": "DENY",
              "condition": {"resource_prefix": "prod-"}}]
    assert pe.evaluate("openstack.server.delete", rules=rules,
                       context={"resource": "prod-db-1"}).decision == pe.DENY
    # non-prod resource: rule doesn't match -> default deny (still deny, but not by the prod rule)
    d = pe.evaluate("openstack.server.delete", rules=rules,
                    context={"resource": "dev-1"})
    assert d.decision == pe.DENY
    assert d.matched_rule is None  # matched by default-deny, not the prod rule


def test_fail_closed_when_service_unavailable():
    d = pe.evaluate_fail_closed("openstack.server.list", rules=_SRS_RULES,
                                permissions=["openstack.*"], service_available=False)
    assert d.decision == pe.DENY
    assert "fail closed" in d.reason


# Property: DENY precedence is absolute whenever a DENY rule matches.
@given(
    allow_first=st.booleans(),
    extra=st.sampled_from(["ALLOW", "REQUIRE_APPROVAL", "QUARANTINE"]),
)
@settings(max_examples=100)
def test_property_deny_always_wins(allow_first, extra):
    rules = [
        {"action": "act.*", "decision": extra},
        {"action": "act.x", "decision": "DENY"},
    ]
    if allow_first:
        rules.reverse()
    assert pe.evaluate("act.x", rules=rules).decision == pe.DENY


# --------------------------------------------------------------------------- #
# YAML loader
# --------------------------------------------------------------------------- #
def test_parse_policy_yaml():
    text = """
policy:
  name: infrastructure-protection
  scope: tenant
  rules:
    - action: openstack.server.list
      decision: ALLOW
    - action: openstack.server.delete
      decision: REQUIRE_APPROVAL
"""
    parsed = prepo.parse_policy_yaml(text)
    assert parsed["name"] == "infrastructure-protection"
    assert parsed["scope"] == "tenant"
    assert len(parsed["rules"]) == 2


def test_parse_policy_yaml_rejects_missing_name():
    try:
        prepo.parse_policy_yaml("policy:\n  rules: []\n")
        assert False
    except ValueError:
        pass


# --------------------------------------------------------------------------- #
# Route-level /evaluate
# --------------------------------------------------------------------------- #
def test_route_evaluate(monkeypatch):
    from src import authz
    from src.routes import zaf_governance_routes as routes
    from src.zaf import governance_service as gov
    from flask import Flask

    monkeypatch.setattr(
        authz, "membership_loader",
        lambda uid: [{"tenant_id": 1, "tenant_slug": "default", "role": "operator", "is_default": True}],
    )
    # Stub the governance service decide() so no DB is touched.
    monkeypatch.setattr(
        routes.gov, "decide",
        lambda tenant_id, action, **kw: {"decision": "ALLOW", "reason": "stub",
                                         "risk_score": 0, "params_hash": "h"},
    )

    app = Flask(__name__)
    app.secret_key = "t"
    app.register_blueprint(routes.zaf_governance_bp)
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 1

    resp = client.post("/api/v1/governance/evaluate", json={"action": "openstack.server.list"})
    assert resp.status_code == 200
    assert resp.get_json()["decision"] == "ALLOW"

    assert client.post("/api/v1/governance/evaluate", json={}).status_code == 400


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
