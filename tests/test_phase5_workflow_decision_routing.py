#!/usr/bin/env python3
"""Property test for supervisor workflow decision routing.

Feature: phase5-obs-supervisor, Property 15

Property 15: Workflow decision routing.
The end-to-end ``Supervisor.run`` state machine gates the final parent action on
the Phase 3 PDP verdict, deterministically and with no LLM in the decision path:

* ALLOW (and approved where approval is required) → the final action is executed
  (terminal state ``executed`` and the ``execute`` seam is invoked for it).
* DENY → the action is withheld (terminal state ``withheld``) and the final
  action is never executed.
* REQUIRE_APPROVAL → ``request_approval`` is invoked and execution is withheld
  (terminal state ``awaiting_approval``) until ``is_authorized`` reports the
  exact action approved; once ``is_authorized`` is True the action executes.

Validates: Requirements 12.2, 12.3, 12.4, 12.5

Run directly:
    .venv/bin/python -m pytest tests/test_phase5_workflow_decision_routing.py -q
"""
import os
import sys

from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.aro.decomposition_planner import ChildTaskSpec  # noqa: E402
from src.aro.scope import Scope  # noqa: E402
from src.aro.supervisor import (  # noqa: E402
    DECISION_ALLOW,
    DECISION_DENY,
    DECISION_QUARANTINE,
    DECISION_REQUIRE_APPROVAL,
    Role,
    Supervisor,
)

# --------------------------------------------------------------------------- #
# Generators — vary the final action/resource/params (and, where applicable,
# the verdict) over the whole input space while keeping the single child's
# requested scope within the parent scope so delegation always succeeds and the
# workflow actually reaches the ZAF-validate / routing stage.
# --------------------------------------------------------------------------- #
_ACTIONS = st.sampled_from(
    ["deploy", "read", "write", "scale", "restart", "delete", "patch"]
)
_RESOURCES = st.sampled_from(
    ["prod-db", "staging-web", "logs", "cluster-a", "svc-x", "svc-y"]
)
_PARAMS = st.dictionaries(
    keys=st.sampled_from(["env", "region", "replicas", "tag"]),
    values=st.one_of(st.text(max_size=6), st.integers(min_value=0, max_value=10)),
    max_size=3,
)


def _make_supervisor(*, decide_verdict, authorized, recorder):
    """Build a Supervisor over mock seams wired to a fixed PDP verdict.

    ``recorder`` is a mutable dict the seams write into so the test can assert
    which seams fired (execute / request_approval / is_authorized) and with
    what arguments. The single child's requested scope is a subset of the
    parent scope and its operation is in scope, so delegation succeeds and the
    workflow reaches the final-action routing every time.
    """

    def submit(tenant_id, agent_id, **kwargs):
        recorder.setdefault("submitted", []).append(kwargs)
        return {"task_id": 1, **kwargs}

    def execute(child, task, token):
        # Child delegation returns a value → run_with_policy → SUCCEEDED.
        # The final action passes child=None; record that invocation so the
        # test can assert execute fired for the final action specifically.
        if child is None:
            recorder["final_executed"] = True
            recorder["final_task"] = task
        return {"ok": True}

    def decide(tenant_id, action, *, resource=None, params=None, context=None):
        recorder.setdefault("decided", []).append(
            {"action": action, "resource": resource, "params": params}
        )
        return {"decision": decide_verdict}

    def request_approval(tenant_id, action, *, params=None, resource=None,
                         risk_explanation=None):
        recorder.setdefault("approvals", []).append(
            {"action": action, "params": params, "resource": resource}
        )
        return {"approval_id": "appr-1", "action": action}

    def is_authorized(tenant_id, action, params):
        recorder.setdefault("authz_checks", []).append(
            {"action": action, "params": params}
        )
        return authorized

    roles = {
        "Operator": Role(
            name="Operator",
            capabilities=("*",),
            default_scope=("*",),
        )
    }

    return Supervisor(
        tenant_id=1,
        agent_id=7,
        roles=roles,
        submit=submit,
        execute=execute,
        decide=decide,
        request_approval=request_approval,
        is_authorized=is_authorized,
        cost_reader=None,
    )


def _request(action, resource, params):
    """A one-child request whose child scope ⊆ parent scope so it succeeds."""
    parent_scope = Scope(actions=frozenset({"*"}), resources=frozenset({"*"}))
    child = ChildTaskSpec(
        key="c1",
        operation="read",
        requested_scope=Scope(
            actions=frozenset({"read"}), resources=frozenset({"logs"})
        ),
    )
    return {
        "parent": "root",
        "parent_task_id": 100,
        "parent_scope": parent_scope,
        "children": [child],
        "action": action,
        "resource": resource,
        "params": params,
    }


# --------------------------------------------------------------------------- #
# ALLOW → execute (R12.4).
# --------------------------------------------------------------------------- #
@settings(max_examples=100, deadline=None)
@given(action=_ACTIONS, resource=_RESOURCES, params=_PARAMS)
def test_allow_executes_final_action(action, resource, params):
    """ALLOW routes to execution: terminal ``executed`` and execute fired."""
    recorder = {}
    sup = _make_supervisor(
        decide_verdict=DECISION_ALLOW, authorized=True, recorder=recorder
    )
    result = sup.run(_request(action, resource, params))

    assert result["state"] == "executed"
    assert recorder.get("final_executed") is True
    # The final action executed is exactly the one submitted to the PDP.
    assert recorder["final_task"]["action"] == action
    assert recorder["final_task"]["resource"] == resource


# --------------------------------------------------------------------------- #
# DENY (and QUARANTINE) → withhold (R12.5).
# --------------------------------------------------------------------------- #
@settings(max_examples=100, deadline=None)
@given(
    action=_ACTIONS,
    resource=_RESOURCES,
    params=_PARAMS,
    verdict=st.sampled_from([DECISION_DENY, DECISION_QUARANTINE]),
)
def test_deny_withholds_without_executing(action, resource, params, verdict):
    """DENY/QUARANTINE routes to withhold: never executes the final action."""
    recorder = {}
    sup = _make_supervisor(
        decide_verdict=verdict, authorized=True, recorder=recorder
    )
    result = sup.run(_request(action, resource, params))

    assert result["state"] == "withheld"
    assert recorder.get("final_executed") is None
    # Denial never consults the approval service for the final action.
    assert "approvals" not in recorder


# --------------------------------------------------------------------------- #
# REQUIRE_APPROVAL, not yet authorized → request approval + withhold (R12.3).
# --------------------------------------------------------------------------- #
@settings(max_examples=100, deadline=None)
@given(action=_ACTIONS, resource=_RESOURCES, params=_PARAMS)
def test_require_approval_unauthorized_awaits_and_withholds(
    action, resource, params
):
    """REQUIRE_APPROVAL + is_authorized False → approval requested, withheld."""
    recorder = {}
    sup = _make_supervisor(
        decide_verdict=DECISION_REQUIRE_APPROVAL,
        authorized=False,
        recorder=recorder,
    )
    result = sup.run(_request(action, resource, params))

    assert result["state"] == "awaiting_approval"
    # Approval was requested for the exact final action.
    assert recorder.get("approvals")
    assert recorder["approvals"][-1]["action"] == action
    # is_authorized was consulted for that exact action+params and gated it.
    assert recorder.get("authz_checks")
    assert recorder["authz_checks"][-1]["action"] == action
    assert recorder["authz_checks"][-1]["params"] == params
    # Withheld: the final action never executed.
    assert recorder.get("final_executed") is None


# --------------------------------------------------------------------------- #
# REQUIRE_APPROVAL, authorized for the exact action → execute (R12.3, R12.4).
# --------------------------------------------------------------------------- #
@settings(max_examples=100, deadline=None)
@given(action=_ACTIONS, resource=_RESOURCES, params=_PARAMS)
def test_require_approval_authorized_executes(action, resource, params):
    """REQUIRE_APPROVAL + is_authorized True → executes the final action."""
    recorder = {}
    sup = _make_supervisor(
        decide_verdict=DECISION_REQUIRE_APPROVAL,
        authorized=True,
        recorder=recorder,
    )
    result = sup.run(_request(action, resource, params))

    assert result["state"] == "executed"
    # Authorization was checked for the exact action approved before executing.
    assert recorder.get("authz_checks")
    assert recorder["authz_checks"][-1]["action"] == action
    assert recorder["authz_checks"][-1]["params"] == params
    assert recorder.get("final_executed") is True
    assert recorder["final_task"]["action"] == action
