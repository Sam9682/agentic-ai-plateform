#!/usr/bin/env python3
"""Unit/integration tests for supervisor delegation retry/timeout/cancel,
aggregation, and conflict escalation.

Feature: phase5-obs-supervisor, Task 10.4.

Validates: Requirements 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 14.3, 14.6.

These tests drive ``src.aro.supervisor.Supervisor`` end-to-end through its
injected worker/policy seams (``submit``/``execute``), the Phase 3 PDP
(``decide``), and the approval service (``request_approval``/``is_authorized``).
The Supervisor delegates children under the **real** Phase 4
``src.execution_policy.run_with_policy`` (not re-implemented), so the
transient-retry (R9.4), timeout (R9.5), and cooperative-cancel (R9.6) semantics
are the genuine policy semantics exercised through the live seam. Per R14.6
those scenarios are marked ``integration`` because they drive the live
``run_with_policy`` seam; they still need no Docker/DB/SSH — every collaborator
is a fake, and timeouts are triggered by the op reporting its own deadline
(``DeadlineExceeded``) per the policy's contract, so no wall-clock wait occurs.

Covered behaviors:
* (1) Transient failure retries under the bound then succeeds (R9.4).
* (2) Timeout trips the ``TIMED_OUT`` / ``timed_out`` child status (R9.5).
* (3) A pre-cancelled ``CancelToken`` cancels/withholds in-progress children
      (no ``execute``) and the run returns the cancelled state (R9.6).
* (4) Multiple terminal children aggregate into the parent result (R9.3).
* (5) Conflicting child conclusions escalate to a human via
      ``request_approval`` and return the ``escalated`` state (R9.7, R14.3).

Run directly:
    python3 tests/test_phase5_delegation_retry_timeout_cancel.py
Or via pytest:
    pytest tests/test_phase5_delegation_retry_timeout_cancel.py -q
"""
import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.aro.decomposition_planner import ChildTaskSpec  # noqa: E402
from src.aro.scope import Scope  # noqa: E402
from src.aro.supervisor import (  # noqa: E402
    DelegationResult,
    Role,
    Supervisor,
    detect_conflict,
)
from src.execution_policy import (  # noqa: E402
    CancelToken,
    DeadlineExceeded,
    OutcomeStatus,
)


# --------------------------------------------------------------------------- #
# Shared fakes/builders — a single Role whose capability covers every child
# operation used below, and a parent scope broad enough that intersection keeps
# the children's requested globs (so delegation reaches the execute seam).
# --------------------------------------------------------------------------- #
_ROLE = Role(
    name="Developer",
    capabilities=("task:*",),
    default_scope=("res:*",),
)
_ROLES = {"Developer": _ROLE}

_PARENT_SCOPE = Scope(actions=frozenset({"task:*"}), resources=frozenset({"res:*"}))


def _child(key, *, op=None, resource="res:thing", depends_on=()):
    """A child whose requested action is its operation and resource is in-scope."""
    operation = op or f"task:{key}"
    return ChildTaskSpec(
        key=key,
        operation=operation,
        requested_scope=Scope(
            actions=frozenset({operation}),
            resources=frozenset({resource}),
        ),
        depends_on=tuple(depends_on),
    )


def _fake_submit(tenant_id, agent_id, *, operation, payload, policy_context):
    """Record-free submit seam returning a minimal submitted-task handle."""
    return {
        "id": f"task-{payload.get('child_key')}",
        "operation": operation,
        "policy_context": policy_context,
    }


def _allow_decide(*_args, **_kwargs):
    return {"decision": "ALLOW"}


def _always_authorized(*_args, **_kwargs):
    return True


def _make_supervisor(*, execute, decide=_allow_decide, request_approval=None,
                     is_authorized=_always_authorized, max_attempts=1,
                     is_transient=None, timeout=1800.0, fan_out=4):
    """Build a Supervisor wired entirely with fakes (R14.3)."""
    approvals = {"calls": []}

    def _request_approval(tenant_id, action, **kwargs):
        approvals["calls"].append({"tenant_id": tenant_id, "action": action, **kwargs})
        return {"approval_id": "appr-1", "status": "requested"}

    sup = Supervisor(
        tenant_id=1,
        agent_id=7,
        roles=_ROLES,
        submit=_fake_submit,
        execute=execute,
        decide=decide,
        request_approval=request_approval or _request_approval,
        is_authorized=is_authorized,
        fan_out=fan_out,
        default_timeout=timeout,
        default_max_attempts=max_attempts,
        is_transient=is_transient or (lambda _e: False),
    )
    return sup, approvals


# --------------------------------------------------------------------------- #
# (1) Transient failure retries under the bound then succeeds (R9.4).
# --------------------------------------------------------------------------- #
@pytest.mark.integration
def test_transient_failure_retries_then_succeeds():
    """A transient child failure retries within ``max_attempts`` and succeeds.

    Validates: Requirements 9.4, 14.6.

    The ``execute`` seam fails transiently on its first invocation and succeeds
    on the second; with ``default_max_attempts=2`` and an ``is_transient`` that
    classifies the failure as retryable, the live ``run_with_policy`` retries
    under the bound and the child ends ``succeeded`` — then the (ALLOW) final
    action executes, so the workflow reaches the ``executed`` terminal.
    """
    calls = {"n": 0}

    def execute(child, submitted, token):
        # Only the single delegated child drives the retry; the final parent
        # action (child is None) succeeds immediately.
        if child is None:
            return {"final": True}
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient connection reset")
        return {"ok": True}

    sup, _ = _make_supervisor(
        execute=execute,
        max_attempts=2,
        is_transient=lambda _e: True,
        timeout=None,
    )

    result = sup.run(
        {
            "parent": "P",
            "parent_scope": _PARENT_SCOPE,
            "children": [_child("c1")],
            "action": "task:finalize",
            "resource": "res:thing",
        }
    )

    # The child retried once (two invocations) and succeeded; the workflow then
    # executed the allowed final action.
    assert calls["n"] == 2
    assert result["state"] == "executed"
    child_rows = {c["key"]: c for c in result["aggregate"]["children"]}
    assert child_rows["c1"]["status"] == "succeeded"
    assert result["aggregate"]["succeeded_count"] == 1


@pytest.mark.integration
def test_transient_failure_exhausts_bound_fails():
    """A transient failure that never clears within the bound ends ``failed``.

    Validates: Requirements 9.4, 14.6.

    With ``max_attempts=2`` and an op that always raises a transient error, the
    live policy exhausts the retry bound and the child terminates ``failed``;
    the parent still aggregates the terminal child.
    """
    calls = {"n": 0}

    def execute(child, submitted, token):
        if child is None:
            return {"final": True}
        calls["n"] += 1
        raise RuntimeError("transient connection timeout")

    sup, _ = _make_supervisor(
        execute=execute,
        max_attempts=2,
        is_transient=lambda _e: True,
        timeout=None,
    )

    result = sup.run(
        {
            "parent": "P",
            "parent_scope": _PARENT_SCOPE,
            "children": [_child("c1")],
            "action": "task:finalize",
            "resource": "res:thing",
        }
    )

    assert calls["n"] == 2  # exhausted the bound
    child_rows = {c["key"]: c for c in result["aggregate"]["children"]}
    assert child_rows["c1"]["status"] == "failed"


# --------------------------------------------------------------------------- #
# (2) Timeout trips the TIMED_OUT path (R9.5).
# --------------------------------------------------------------------------- #
@pytest.mark.integration
def test_timeout_yields_timed_out_child():
    """An ``execute`` that reports its deadline yields a ``timed_out`` child.

    Validates: Requirements 9.5, 14.6.

    Per the live ``run_with_policy`` contract an op that raises
    ``DeadlineExceeded`` maps to ``OutcomeStatus.TIMED_OUT``; the Supervisor
    translates that to the ``timed_out`` child status (no wall-clock wait).
    """
    seen = {"delegate": False}

    def execute(child, submitted, token):
        if child is None:
            return {"final": True}
        seen["delegate"] = True
        raise DeadlineExceeded("child exceeded its timeout budget")

    sup, _ = _make_supervisor(execute=execute, max_attempts=3, timeout=5.0)

    result = sup.run(
        {
            "parent": "P",
            "parent_scope": _PARENT_SCOPE,
            "children": [_child("c1")],
            "action": "task:finalize",
            "resource": "res:thing",
        }
    )

    assert seen["delegate"] is True
    child_rows = {c["key"]: c for c in result["aggregate"]["children"]}
    assert child_rows["c1"]["status"] == "timed_out"


# --------------------------------------------------------------------------- #
# (3) Parent cancel cancels/withholds in-progress children (R9.6).
# --------------------------------------------------------------------------- #
@pytest.mark.integration
def test_parent_cancel_cancels_children_and_run():
    """A pre-cancelled token cancels children without executing and the run
    returns the cancelled state.

    Validates: Requirements 9.6, 14.6.

    A ``CancelToken`` already cancelled before ``run`` is passed in the request.
    Coordination observes the cancel before dispatching any child, so the
    ``execute`` seam is never called and every child is marked ``cancelled``;
    ``run`` returns ``state == "cancelled"`` and never executes the parent
    action.
    """
    executed = {"n": 0}

    def execute(child, submitted, token):
        executed["n"] += 1
        return {"ok": True}

    sup, _ = _make_supervisor(execute=execute, timeout=None)

    token = CancelToken()
    token.cancel()

    result = sup.run(
        {
            "parent": "P",
            "parent_scope": _PARENT_SCOPE,
            "children": [_child("c1"), _child("c2")],
            "action": "task:finalize",
            "resource": "res:thing",
            "cancel_token": token,
        }
    )

    assert executed["n"] == 0  # no child (and no final action) ran
    assert result["state"] == "cancelled"
    statuses = {c["key"]: c["status"] for c in result["aggregate"]["children"]}
    assert statuses == {"c1": "cancelled", "c2": "cancelled"}


# --------------------------------------------------------------------------- #
# (4) Multiple terminal children aggregate into the parent result (R9.3).
# --------------------------------------------------------------------------- #
def test_multiple_terminal_children_aggregate():
    """Several terminal children aggregate into the parent result.

    Validates: Requirements 9.3.

    Three independent children all succeed; the aggregate lists every child,
    reports ``all_terminal`` true, and counts the successes. The workflow then
    reaches the ``executed`` terminal under an ALLOW decision.
    """
    def execute(child, submitted, token):
        if child is None:
            return {"final": True}
        return {"ok": child.key}

    sup, _ = _make_supervisor(execute=execute, timeout=None)

    result = sup.run(
        {
            "parent": "P",
            "parent_scope": _PARENT_SCOPE,
            "children": [_child("c1"), _child("c2"), _child("c3")],
            "action": "task:finalize",
            "resource": "res:thing",
        }
    )

    agg = result["aggregate"]
    assert agg["total_count"] == 3
    assert agg["succeeded_count"] == 3
    assert agg["all_terminal"] is True
    assert {c["key"] for c in agg["children"]} == {"c1", "c2", "c3"}
    assert result["state"] == "executed"


# --------------------------------------------------------------------------- #
# (5) Conflicting child results escalate to a human (R9.7, R14.3).
# --------------------------------------------------------------------------- #
def test_conflicting_children_escalate_to_human():
    """Children with differing conclusions escalate via ``request_approval``.

    Validates: Requirements 9.7, 14.3.

    Two children succeed but report contradictory ``conclusion`` values;
    ``detect_conflict`` is true, so the Supervisor requests human approval and
    returns ``state == "escalated"`` rather than proceeding to the final action.
    """
    def execute(child, submitted, token):
        if child is None:
            return {"final": True}
        # Each child reaches a different conclusion -> genuine disagreement.
        return {"conclusion": "approve" if child.key == "c1" else "reject"}

    sup, approvals = _make_supervisor(execute=execute, timeout=None)

    result = sup.run(
        {
            "parent": "P",
            "parent_scope": _PARENT_SCOPE,
            "children": [_child("c1"), _child("c2")],
            "action": "task:finalize",
            "resource": "res:thing",
        }
    )

    assert result["state"] == "escalated"
    assert result["reason"] == "conflicting child results"
    # A human-review approval was requested exactly once.
    assert len(approvals["calls"]) == 1
    assert "approval" in result


def test_detect_conflict_pure_contract():
    """Pure ``detect_conflict`` flags only genuine succeeded-conclusion disagreement.

    Validates: Requirements 9.7.

    Only ``succeeded`` children carrying a ``conclusion`` participate; agreement
    (or a single distinct conclusion) is no conflict, and non-succeeded children
    are ignored.
    """
    # Disagreement among succeeded children -> conflict.
    assert detect_conflict(
        [
            {"status": "succeeded", "conclusion": "a"},
            {"status": "succeeded", "conclusion": "b"},
        ]
    )
    # Agreement -> no conflict.
    assert not detect_conflict(
        [
            {"status": "succeeded", "conclusion": "a"},
            {"status": "succeeded", "conclusion": "a"},
        ]
    )
    # A failed dissenter is not a conflict by itself.
    assert not detect_conflict(
        [
            {"status": "succeeded", "conclusion": "a"},
            {"status": "failed", "conclusion": "b"},
        ]
    )
    # Fewer than two distinct conclusions -> no conflict.
    assert not detect_conflict([{"status": "succeeded", "conclusion": "a"}])
    assert not detect_conflict([])


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
