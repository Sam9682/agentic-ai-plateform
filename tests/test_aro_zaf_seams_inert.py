#!/usr/bin/env python3
"""Property 7: ZAF seams are inert in Phase 2 (task 9.13).

Feature: ARO completion — Zero-trust Agent Firewall (ZAF) integration seams.

Phase 2 defines clean ZAF integration seams but interposes NO enforcement
(enforcement is Phase 3). Each seam is a defaulted no-op callable that is
*consulted* (called) with a documented decision context, but whose RETURN VALUE
is deliberately discarded so it cannot alter behavior (inertness — Req 8.2).

This module pins that inertness as a property across the three seams that exist
in Phase 2 today:

  1. lifecycle transition — ``LifecycleService(zaf_pre_transition=...)`` consulted
     inside ``transition()`` with ``{tenant_id, agent_id, from, to, identity}``
     (task 9.12).
  2. launch — ``execution_manager.launch(..., zaf_egress=...)`` consulted before
     the remote ``docker run`` with ``{server_ip, image, network_policy,
     proxy_url, name, tenant_id}`` (task 6.8).
  3. task execution start — ``agent_worker.execute_claimed_task(..., zaf_exec=...)``
     consulted immediately before the adapter's ``execute(...)`` that starts the
     streamed execution, with ``{tenant_id, agent_id, operation, payload_keys}``
     (task 14.9).

The property under test (for each covered seam):
  * INERTNESS (Req 8.2): the persisted outcome AND the emitted events are
    IDENTICAL whether the seam callable is the default no-op OR an arbitrary
    "allow-callable" that returns True / False / None / arbitrary values. The
    seam's return value cannot change behavior.
  * CONSULTED (Req 1.12, 3.8, 8.1): the seam IS called exactly once, with the
    documented decision-input context.

Validates: Requirements 1.12, 3.8, 8.1, 8.2

The property under test for the exec seam (task 14.9):
  * INERTNESS (Req 8.2): the persisted task outcome AND the emitted events are
    IDENTICAL whether the ``zaf_exec`` seam is the default no-op or an arbitrary
    allow-callable returning True/False/None/arbitrary values.
  * CONSULTED (Req 8.1): the seam IS called exactly once, with the documented
    decision-input context ``{tenant_id, agent_id, operation, payload_keys}``.

Run directly:
    python3 tests/test_aro_zaf_seams_inert.py
Or via pytest:
    pytest tests/test_aro_zaf_seams_inert.py
"""
import os
import sys
from contextlib import contextmanager

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.aro import agent_worker as worker  # noqa: E402
from src.aro import lifecycle as lc  # noqa: E402
from src.aro import execution_manager as em  # noqa: E402
from src.aro.adapters.base import FakeAdapter  # noqa: E402
from src.aro.lifecycle_service import LifecycleService  # noqa: E402


# --------------------------------------------------------------------------- #
# Shared: a family of "allow-callables" whose return values vary wildly.
# --------------------------------------------------------------------------- #
# An inert seam must ignore ALL of these return values. Each factory returns a
# fresh recording callable that appends the context it was called with, so we
# can also assert the seam IS consulted and WITH WHAT context. The default
# no-op (``None`` -> service/manager substitutes ``lambda ctx: None``) is the
# baseline both branches are compared against.
def _recorder(return_value):
    """Build a recording seam callable that returns a fixed value."""
    calls = []

    def _seam(ctx):
        calls.append(ctx)
        return return_value

    _seam.calls = calls
    return _seam


# Arbitrary return values an enforcement-style callable might produce. In an
# inert seam NONE of these may change behavior.
_RETURN_VALUES = st.one_of(
    st.just(True),
    st.just(False),
    st.none(),
    st.integers(),
    st.text(max_size=8),
    st.lists(st.integers(), max_size=3),
    st.dictionaries(st.text(max_size=3), st.integers(), max_size=3),
)


# --------------------------------------------------------------------------- #
# In-memory lifecycle fakes (mirrors tests/test_aro_lifecycle.py helpers).
# --------------------------------------------------------------------------- #
class InMemoryAgentRepo:
    """Minimal in-memory agent repo sufficient to drive transition()."""

    def __init__(self):
        self.agents = {}

    def get_agent(self, tenant_id, agent_id):
        a = self.agents.get((tenant_id, agent_id))
        return dict(a) if a else None

    def update_status(self, tenant_id, agent_id, new_status):
        a = self.agents.get((tenant_id, agent_id))
        if not a:
            return False
        a["status"] = new_status
        return True

    def seed(self, tenant_id, agent_id, status, identity="agent://default/a1"):
        self.agents[(tenant_id, agent_id)] = dict(
            id=agent_id, tenant_id=tenant_id, identity=identity, name="a1",
            runtime_id=1, status=status, configuration={}, permissions=[],
        )


class CapturingEvents:
    """Records every emitted event so two runs can be compared for equality."""

    def __init__(self):
        self.events = []

    def append_event(self, event):
        self.events.append(event)
        return dict(event, id=len(self.events))


def _normalize_events(events):
    """Project emitted events to a comparable, deterministic shape.

    Events carry per-run non-deterministic fields (ids, correlation ids,
    timestamps). The inertness property is about the SEMANTIC outcome, so we
    compare the stable fields that describe *what happened*: event type,
    source, agent id, and the action payload.
    """
    out = []
    for e in events:
        out.append((
            e.get("event_type"),
            e.get("source"),
            e.get("agent_id"),
            tuple(sorted((e.get("action") or {}).items())),
        ))
    return out


def _run_transition(zaf_callable, tenant_id, agent_id, from_state, to_state):
    """Drive a single transition with the given (or default) ZAF seam.

    Returns ``(final_status, normalized_events)`` — the persisted outcome and
    the emitted events — so the no-op branch and the allow-callable branch can
    be compared for identity.
    """
    repo_obj = InMemoryAgentRepo()
    repo_obj.seed(tenant_id, agent_id, from_state)
    events = CapturingEvents()
    svc = LifecycleService(
        events_repo=events,
        adapter_for=lambda agent: FakeAdapter(),
        agent_repo=repo_obj,
        zaf_pre_transition=zaf_callable,  # None -> service installs no-op default
    )
    svc.transition(tenant_id, agent_id, to_state)
    final_status = repo_obj.agents[(tenant_id, agent_id)]["status"]
    return final_status, _normalize_events(events.events)


# A legal (from -> to) transition pair drawn from the pure graph, so the
# transition actually mutates state (the seam sits on the mutation path).
@st.composite
def _legal_transition(draw):
    from_state = draw(st.sampled_from(sorted(lc.ALL_STATES - {lc.TERMINATED})))
    successors = sorted(lc.allowed_transitions(from_state))
    # Every non-terminal state has at least QUARANTINED/TERMINATED successors.
    to_state = draw(st.sampled_from(successors))
    return from_state, to_state


@given(
    transition=_legal_transition(),
    return_value=_RETURN_VALUES,
    tenant_id=st.integers(min_value=1, max_value=50),
    agent_id=st.integers(min_value=1, max_value=50),
)
@settings(max_examples=150)
def test_property7_lifecycle_transition_seam_is_inert(
    transition, return_value, tenant_id, agent_id
):
    """Feature: phase2-aro-completion, Property 7: ZAF seams are inert in Phase 2.

    Lifecycle transition seam (task 9.12). For any legal transition, the
    persisted final status AND the emitted events are IDENTICAL whether the
    ``zaf_pre_transition`` seam is the default no-op or an arbitrary
    allow-callable returning True/False/None/arbitrary values — the seam's
    return value cannot alter the transition (inertness, Req 8.2). The seam is
    also consulted exactly once with the documented context
    ``{tenant_id, agent_id, from, to, identity}`` (Req 1.12, 8.1).

    Validates: Requirements 1.12, 8.1, 8.2
    """
    from_state, to_state = transition

    # Baseline: default no-op seam (pass None; the service installs lambda ctx: None).
    base_status, base_events = _run_transition(
        None, tenant_id, agent_id, from_state, to_state
    )

    # Variant: an arbitrary allow-callable that records its context and returns
    # a wild value. Inertness means the outcome must be byte-for-byte identical.
    seam = _recorder(return_value)
    var_status, var_events = _run_transition(
        seam, tenant_id, agent_id, from_state, to_state
    )

    # Inertness: identical persisted outcome and identical emitted events.
    assert var_status == base_status
    assert var_events == base_events

    # Consulted exactly once, with the documented decision-input context.
    assert len(seam.calls) == 1
    ctx = seam.calls[0]
    assert ctx == {
        "tenant_id": tenant_id,
        "agent_id": agent_id,
        "from": from_state,
        "to": to_state,
        "identity": "agent://default/a1",
    }


# --------------------------------------------------------------------------- #
# Launch seam (task 6.8): recording fake ssh + default vs allow-callable.
# --------------------------------------------------------------------------- #
class _RecordingSsh:
    """Fake ssh_execute recording every (server_ip, command) issued.

    Returns success for every command so both the proxy-net probe and the
    docker run look healthy; the point is to capture the EXACT remote commands
    so the no-op and allow-callable runs can be compared for identity.
    """

    def __init__(self):
        self.commands = []

    def __call__(self, server_ip, command, timeout=30):
        self.commands.append((server_ip, command))
        return True, "containerid\n", ""


@contextmanager
def _patched_ssh(rec):
    """Point em._ssh at the recording fake, then restore it.

    A context manager (not the function-scoped monkeypatch fixture) because
    Hypothesis re-runs the body many times within one test invocation.
    """
    original = em._ssh
    em._ssh = lambda: rec
    try:
        yield
    finally:
        em._ssh = original


def _run_launch(zaf_callable, *, server_ip, image, network_policy, proxy_url,
                name, tenant_id):
    """Run launch() with the given (or default) ZAF egress seam.

    Returns ``(result, commands)`` — the launch result tuple and the exact list
    of remote commands issued — so the no-op branch and the allow-callable
    branch can be compared for identity.
    """
    rec = _RecordingSsh()
    with _patched_ssh(rec):
        result = em.launch(
            server_ip,
            image,
            {"network_policy": network_policy},
            name=name,
            proxy_url=proxy_url,
            tenant_id=tenant_id,
            zaf_egress=zaf_callable,  # None -> launch installs lambda ctx: None
        )
    return result, list(rec.commands)


# A digest-pinned image so assert_image_pinned passes and the seam (which sits
# after the policy gates) is actually reached.
_PINNED_IMAGE = "kiro@sha256:" + ("c" * 64)


@given(
    return_value=_RETURN_VALUES,
    network_policy=st.sampled_from(["none", "proxy"]),
    tenant_id=st.one_of(st.none(), st.integers(min_value=1, max_value=50)),
)
@settings(max_examples=150)
def test_property7_launch_egress_seam_is_inert(
    return_value, network_policy, tenant_id
):
    """Feature: phase2-aro-completion, Property 7: ZAF seams are inert in Phase 2.

    Launch egress seam (task 6.8). For a policy-compliant (digest-pinned) launch,
    the result AND the exact sequence of remote commands issued over SSH are
    IDENTICAL whether the ``zaf_egress`` seam is the default no-op or an
    arbitrary allow-callable returning True/False/None/arbitrary values — the
    seam's return value cannot alter the launch (inertness, Req 8.2). The seam is
    also consulted exactly once with the documented egress-decision context
    ``{server_ip, image, network_policy, proxy_url, name, tenant_id}``
    (Req 3.8, 8.1).

    Validates: Requirements 3.8, 8.1, 8.2
    """
    server_ip = "10.0.0.5"
    proxy_url = "http://zaf-proxy:3128"
    name = "c1"

    # Baseline: default no-op seam (pass None).
    base_result, base_commands = _run_launch(
        None,
        server_ip=server_ip, image=_PINNED_IMAGE,
        network_policy=network_policy, proxy_url=proxy_url,
        name=name, tenant_id=tenant_id,
    )

    # Variant: an arbitrary allow-callable that records and returns a wild value.
    seam = _recorder(return_value)
    var_result, var_commands = _run_launch(
        seam,
        server_ip=server_ip, image=_PINNED_IMAGE,
        network_policy=network_policy, proxy_url=proxy_url,
        name=name, tenant_id=tenant_id,
    )

    # Inertness: identical launch result and identical remote commands issued.
    assert var_result == base_result
    assert var_commands == base_commands

    # Consulted exactly once, with the documented decision-input context.
    assert len(seam.calls) == 1
    ctx = seam.calls[0]
    assert ctx == {
        "server_ip": server_ip,
        "image": _PINNED_IMAGE,
        "network_policy": network_policy,
        "proxy_url": proxy_url,
        "name": name,
        "tenant_id": tenant_id,
    }


# --------------------------------------------------------------------------- #
# Unit anchors (concrete examples complementing the properties above).
# --------------------------------------------------------------------------- #
def test_lifecycle_seam_denying_callable_cannot_block_transition():
    """A seam returning False (a Phase-3-style DENY) still cannot block.

    In Phase 2 the return value is discarded: the legal transition completes and
    the status is persisted regardless of what the seam returns.
    """
    status_default, _ = _run_transition(
        None, 1, 1, lc.READY, lc.STARTING
    )
    status_deny, _ = _run_transition(
        _recorder(False), 1, 1, lc.READY, lc.STARTING
    )
    assert status_default == lc.STARTING
    assert status_deny == status_default


def test_launch_seam_denying_callable_cannot_block_launch():
    """A seam returning False cannot stop the docker run from being issued."""
    _, cmds_default = _run_launch(
        None, server_ip="10.0.0.5", image=_PINNED_IMAGE,
        network_policy="none", proxy_url=None, name="c1", tenant_id=7,
    )
    _, cmds_deny = _run_launch(
        _recorder(False), server_ip="10.0.0.5", image=_PINNED_IMAGE,
        network_policy="none", proxy_url=None, name="c1", tenant_id=7,
    )
    # The docker run is issued in both cases; the deny return value is ignored.
    assert any("docker run -d --name c1" in cmd for _ip, cmd in cmds_default)
    assert cmds_deny == cmds_default


# --------------------------------------------------------------------------- #
# Exec seam (task 14.9): in-memory task repo + FakeAdapter, default vs
# allow-callable consulted before adapter.execute(...).
# --------------------------------------------------------------------------- #
class InMemoryTaskRepo:
    """Minimal in-memory task store sufficient to drive execute_claimed_task.

    Models only the claim/mark_running/complete contract the worker needs for a
    happy-path execution; that is all the exec-seam inertness property exercises.
    """

    def __init__(self):
        self.tasks = {}
        self._id = 1

    def submit(self, tenant_id, agent_id, *, operation="prompt", payload=None):
        tid = self._id
        self._id += 1
        t = dict(
            id=tid, tenant_id=tenant_id, agent_id=agent_id,
            task_ref=f"task-{tid}", operation=operation, payload=payload or {},
            status="pending", attempts=0, max_attempts=1, result=None,
            cancel_requested=False,
        )
        self.tasks[tid] = t
        return dict(t)

    def mark_running(self, tenant_id, task_id):
        t = self.tasks[task_id]
        t["status"] = "running"
        return True

    def complete(self, tenant_id, task_id, status, result=None):
        t = self.tasks[task_id]
        t["status"] = status
        t["result"] = result
        return True

    def is_cancel_requested(self, task_id):
        return bool(self.tasks.get(task_id, {}).get("cancel_requested"))


def _agent_loader(tenant_id, agent_id):
    return {"id": agent_id, "tenant_id": tenant_id, "identity": "agent://default/a1"}


def _run_exec(zaf_callable, *, tenant_id, agent_id, operation, payload):
    """Run execute_claimed_task with the given (or default) ZAF exec seam.

    Returns ``(terminal_status, persisted_status, normalized_events)`` — the
    task's terminal outcome, the status persisted on the task row, and the
    emitted events — so the no-op branch and the allow-callable branch can be
    compared for identity.
    """
    repo = InMemoryTaskRepo()
    repo.submit(tenant_id, agent_id, operation=operation, payload=payload)
    task = dict(repo.tasks[1])
    events = CapturingEvents()
    out = worker.execute_claimed_task(
        task,
        adapter_for=lambda agent: FakeAdapter(),
        agent_loader=_agent_loader,
        events_repo=events,
        repo=repo,
        zaf_exec=zaf_callable,  # None -> worker installs lambda ctx: None
    )
    return out["status"], repo.tasks[1]["status"], _normalize_events(events.events)


# Small payloads with arbitrary top-level string keys so ``payload_keys`` (the
# documented shape input) varies across examples while values stay irrelevant.
_PAYLOADS = st.dictionaries(
    st.text(min_size=1, max_size=5), st.integers(), max_size=4
)


@given(
    return_value=_RETURN_VALUES,
    tenant_id=st.integers(min_value=1, max_value=50),
    agent_id=st.integers(min_value=1, max_value=50),
    operation=st.sampled_from(["prompt", "tools/call", "install", "stop"]),
    payload=_PAYLOADS,
)
@settings(max_examples=150)
def test_property7_exec_seam_is_inert(
    return_value, tenant_id, agent_id, operation, payload
):
    """Feature: phase2-aro-completion, Property 7: ZAF seams are inert in Phase 2.

    Task execution-start seam (task 14.9). For a happy-path execution, the
    terminal status, the persisted task status, AND the emitted events are
    IDENTICAL whether the ``zaf_exec`` seam is the default no-op or an arbitrary
    allow-callable returning True/False/None/arbitrary values — the seam's
    return value cannot alter execution (inertness, Req 8.2). The seam is also
    consulted exactly once, immediately before ``adapter.execute(...)``, with
    the documented decision-input context
    ``{tenant_id, agent_id, operation, payload_keys}`` (Req 8.1).

    Validates: Requirements 8.1, 8.2
    """
    # Baseline: default no-op seam (pass None; the worker installs lambda ctx: None).
    base_term, base_persisted, base_events = _run_exec(
        None, tenant_id=tenant_id, agent_id=agent_id,
        operation=operation, payload=payload,
    )

    # Variant: an arbitrary allow-callable that records its context and returns
    # a wild value. Inertness means the outcome must be identical.
    seam = _recorder(return_value)
    var_term, var_persisted, var_events = _run_exec(
        seam, tenant_id=tenant_id, agent_id=agent_id,
        operation=operation, payload=payload,
    )

    # Inertness: identical terminal status, persisted status, and events.
    assert var_term == base_term
    assert var_persisted == base_persisted
    assert var_events == base_events

    # Consulted exactly once, with the documented decision-input context. Note
    # ``payload_keys`` is the payload SHAPE (sorted top-level keys), never values.
    assert len(seam.calls) == 1
    ctx = seam.calls[0]
    assert ctx == {
        "tenant_id": tenant_id,
        "agent_id": agent_id,
        "operation": operation,
        "payload_keys": sorted(list(payload.keys())),
    }


def test_exec_seam_denying_callable_cannot_block_execution():
    """A seam returning False (a Phase-3-style DENY) still cannot block.

    In Phase 2 the return value is discarded: the task still executes to its
    normal terminal status regardless of what the seam returns.
    """
    term_default, persisted_default, _ = _run_exec(
        None, tenant_id=1, agent_id=1, operation="prompt", payload={"prompt": "x"},
    )
    term_deny, persisted_deny, _ = _run_exec(
        _recorder(False), tenant_id=1, agent_id=1, operation="prompt",
        payload={"prompt": "x"},
    )
    assert term_default == "succeeded"
    assert term_deny == term_default
    assert persisted_deny == persisted_default


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
