#!/usr/bin/env python3
"""Tests for the governed MCP gateway (Task 13).

Feature: ZAF MCP gateway enforcement (SRS §4.7).

Validates:
* unknown/disabled tool is blocked (404, DENY) without invoking.
* parameter validation blocks malformed params (400).
* rate limiting blocks beyond the per-tool limit (429).
* ALLOW invokes the underlying tool and audits it.
* DENY blocks (403) without invoking.
* REQUIRE_APPROVAL blocks (202) until an approval authorizer returns True.

Run directly:
    python3 tests/test_zaf_mcp_gateway.py
Or via pytest:
    pytest tests/test_zaf_mcp_gateway.py
"""
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.zaf import policy_engine as pe  # noqa: E402
from src.zaf.mcp_gateway import McpGateway, RateLimiter, validate_params  # noqa: E402


class CapturingEvents:
    def __init__(self):
        self.events = []

    def append_event(self, event):
        self.events.append(event)
        return dict(event, id=len(self.events))


_TOOL = {
    "tool_name": "deploy_template",
    "canonical_action": "mcp.deploy_template",
    "param_schema": {"required": ["template_id"], "properties": {"template_id": {"type": "string"}}},
    "rate_limit_per_minute": 3,
    "enabled": True,
}


def _resolver(found=True, enabled=True):
    def resolve(tenant_id, server, tool):
        if not found:
            return None
        return dict(_TOOL, enabled=enabled)
    return resolve


def _gateway(decision, *, found=True, enabled=True, authorizer=None, invoked=None, events=None):
    events = events or CapturingEvents()
    invoked = invoked if invoked is not None else []

    def invoke(server, tool, params):
        invoked.append((server, tool, params))
        return {"ok": True}

    gw = McpGateway(
        tool_resolver=_resolver(found=found, enabled=enabled),
        tool_invoker=invoke,
        decide=lambda tenant_id, action, **kw: {"decision": decision, "reason": "stub", "risk_score": 0},
        approval_authorizer=authorizer,
        rate_limiter=RateLimiter(),
        events_repo=events,
    )
    return gw, invoked, events


# --------------------------------------------------------------------------- #
# param validation
# --------------------------------------------------------------------------- #
def test_validate_params_required():
    assert validate_params({"required": ["a"]}, {}) is not None
    assert validate_params({"required": ["a"]}, {"a": 1}) is None


def test_validate_params_type():
    schema = {"properties": {"n": {"type": "integer"}}}
    assert validate_params(schema, {"n": "x"}) is not None
    assert validate_params(schema, {"n": 5}) is None


# --------------------------------------------------------------------------- #
# gateway flow
# --------------------------------------------------------------------------- #
def test_unknown_tool_blocked():
    gw, invoked, _ = _gateway(pe.ALLOW, found=False)
    res = gw.invoke(1, "srv", "nope", {"template_id": "x"})
    assert res.allowed is False and res.status_code == 404
    assert invoked == []


def test_malformed_params_blocked():
    gw, invoked, _ = _gateway(pe.ALLOW)
    res = gw.invoke(1, "srv", "deploy_template", {})  # missing template_id
    assert res.allowed is False and res.status_code == 400
    assert invoked == []


def test_allow_invokes_and_audits():
    gw, invoked, events = _gateway(pe.ALLOW)
    res = gw.invoke(1, "srv", "deploy_template", {"template_id": "flask"},
                    agent_identity="agent://default/a1")
    assert res.allowed is True
    assert invoked == [("srv", "deploy_template", {"template_id": "flask"})]
    assert any(e["event_type"] == "mcp.tool.invocation" for e in events.events)


def test_deny_blocks_without_invoking():
    gw, invoked, _ = _gateway(pe.DENY)
    res = gw.invoke(1, "srv", "deploy_template", {"template_id": "x"})
    assert res.allowed is False and res.status_code == 403
    assert invoked == []


def test_require_approval_blocks_until_authorized():
    # authorizer False -> blocked (202)
    gw, invoked, _ = _gateway(pe.REQUIRE_APPROVAL, authorizer=lambda t, a, p: False)
    res = gw.invoke(1, "srv", "deploy_template", {"template_id": "x"})
    assert res.allowed is False and res.status_code == 202
    assert invoked == []

    # authorizer True -> invoked
    gw2, invoked2, _ = _gateway(pe.REQUIRE_APPROVAL, authorizer=lambda t, a, p: True)
    res2 = gw2.invoke(1, "srv", "deploy_template", {"template_id": "x"})
    assert res2.allowed is True
    assert invoked2 == [("srv", "deploy_template", {"template_id": "x"})]


def test_rate_limit_blocks_beyond_limit():
    gw, invoked, _ = _gateway(pe.ALLOW)  # limit 3/min
    for _ in range(3):
        r = gw.invoke(1, "srv", "deploy_template", {"template_id": "x"},
                      agent_identity="a1")
        assert r.allowed is True
    r4 = gw.invoke(1, "srv", "deploy_template", {"template_id": "x"}, agent_identity="a1")
    assert r4.allowed is False and r4.status_code == 429
    assert len(invoked) == 3


def test_rate_limiter_window_resets():
    rl = RateLimiter()
    key = ("a", "t")
    assert rl.allow(key, 2, now=0.0)
    assert rl.allow(key, 2, now=1.0)
    assert not rl.allow(key, 2, now=2.0)
    # after the 60s window, allowed again
    assert rl.allow(key, 2, now=65.0)


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
