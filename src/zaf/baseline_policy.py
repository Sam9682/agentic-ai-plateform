"""Platform baseline policy (versioned, in code).

Why it exists: the PDP is default-deny, and before Phase 2 the live lifecycle
seam was an inert no-op, so every transition was effectively allowed. Wiring
the real enforcer (finding F1) without a baseline would have refused every
lifecycle operation for tenants that have no policy yet. The baseline keeps
today's lifecycle behaviour **while** making tenant DENY / REQUIRE_APPROVAL
rules, agent quarantine status and ABF risk effective.

The baseline is merged *after* the tenant's rules, and the PDP's precedence
still applies: a tenant DENY always wins; a tenant REQUIRE_APPROVAL beats a
baseline ALLOW.

Set ``ZAF_PLATFORM_BASELINE=off`` to evaluate tenant rules alone (strict
default deny). The version string is recorded with every decision so audits
can tell which baseline was in force.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

VERSION = "platform-baseline-2026.11.1"

RULES: List[Dict[str, Any]] = [
    # ABF risk escalation (context risk_level comes from ABF rule hits only).
    {"action": "*", "decision": "DENY", "condition": {"risk_level": "critical"},
     "id": "baseline.abf.critical_deny", "baseline": VERSION},
    {"action": "*", "decision": "REQUIRE_APPROVAL", "condition": {"risk_level": "high"},
     "id": "baseline.abf.high_approval", "baseline": VERSION},
    # Lifecycle operations are already role-gated at the API (operator/admin);
    # keep them allowed unless a tenant rule says otherwise.
    {"action": "agent.transition.*", "decision": "ALLOW",
     "id": "baseline.lifecycle.allow", "baseline": VERSION},
    # ABF guard requests (POST /api/v1/firewall/check): allowed unless ABF risk
    # escalates them above (critical -> DENY, high -> REQUIRE_APPROVAL), a
    # tenant rule says otherwise, or the agent is quarantined.
    {"action": "abf.*", "decision": "ALLOW",
     "id": "baseline.abf.guard_allow", "baseline": VERSION},
    # Read-only platform MCP tools are allowed for an authenticated agent;
    # mutating tools need an explicit agent permission or tenant rule.
    {"action": "mcp.platform.read.*", "decision": "ALLOW",
     "id": "baseline.mcp.read_allow", "baseline": VERSION},
]


def enabled() -> bool:
    return os.environ.get("ZAF_PLATFORM_BASELINE", "on").strip().lower() not in (
        "off", "0", "false", "no")


def rules() -> List[Dict[str, Any]]:
    return [dict(r) for r in RULES] if enabled() else []
