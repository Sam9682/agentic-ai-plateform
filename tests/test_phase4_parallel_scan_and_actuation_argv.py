#!/usr/bin/env python3
"""Property tests: parallel scan per-server deadline + actuation argv (Task 7.8).

Feature: phase4-runtime-execution-hardening, Property 15.

Task 7.4 added two surface-agnostic capabilities to
``src.agent_control_service`` whose collaborators are injected so the logic is
unit-testable without live Docker, PostgreSQL, or SSH (R5.9):

* :func:`actuate(server_ip, container_ref, action, *, ssh=..., timeout=...)`
  builds the ``docker <action> <ref>`` argv and dispatches it through the
  injected ``ssh`` callable, returning the ``(success, stdout, stderr)`` tuple
  (R5.6, R5.9).
* :func:`scan_live_parallel(servers, collect, classify, owner_for=None, *,
  max_workers, per_server_deadline, executor_factory)` fans ``collect(server)``
  out across the injected ``executor_factory`` and waits on each future with
  ``future.result(timeout=per_server_deadline)`` so one slow/unreachable server
  costs at most the deadline (not the sum). Reachable servers' containers are
  aggregated in input order; every server that errors / times out / raises
  contributes no containers and records a per-server error (R5.7).

Property 15 (two halves):

* Parallel scan is bounded by the per-server deadline — with a fake slow
  collector and a fake executor, reachable servers' containers aggregate in
  input order, slow/unreachable servers are recorded as per-server errors
  (contributing no containers), and the total wait is bounded by the per-server
  deadline rather than the sum of the per-server latencies.
  Validates Requirements 5.7.
* Actuation argv building — with a fake ``ssh`` recording its argv, the docker
  argv is exactly ``[\"docker\", action, ref]`` for each action, the injected
  ``ssh`` is called with ``(server_ip, argv, timeout=timeout)``, and the ssh
  tuple is returned unchanged. Validates Requirements 5.6, 5.9.

No real threads and no real sleeping: the fake executor models each server's
future as either "done with a value" (fast/reachable) or "never done" (slow),
and ``future.result(timeout=...)`` raises ``TimeoutError`` for the slow ones
exactly as a real ``concurrent.futures`` future would once its deadline lapses.
A virtual clock tracks the bounded wait so the deadline bound is asserted
without any wall-clock sleeping.

Run directly:
    python3 tests/test_phase4_parallel_scan_and_actuation_argv.py
Or via pytest:
    pytest tests/test_phase4_parallel_scan_and_actuation_argv.py
"""
import os
import sys
from concurrent.futures import TimeoutError as FuturesTimeoutError

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.agent_control_service import (  # noqa: E402
    _ACTUATE_ACTIONS,
    actuate,
    scan_live_parallel,
)


# --------------------------------------------------------------------------- #
# Fake executor — models the per-server deadline without real threads/sleep.
#
# Each submitted ``collect(server)`` is represented by a fake future that is
# either "done" with a value (a fast/reachable server) or "never done" (a slow
# server). ``future.result(timeout=deadline)`` returns the value for a done
# future and raises ``TimeoutError`` for a slow one — exactly the contract of a
# real ``concurrent.futures`` future whose work outlives the deadline. A shared
# virtual clock accumulates the bounded wait: a done future costs its (sub-
# deadline) latency, a slow future costs exactly the deadline (the wait is
# abandoned at the deadline, never the server's full latency).
# --------------------------------------------------------------------------- #
class _FakeFuture:
    def __init__(self, clock, done, value=None, exc=None, latency=0.0):
        self._clock = clock
        self._done = done
        self._value = value
        self._exc = exc
        self._latency = latency

    def result(self, timeout=None):
        if self._done:
            # Fast server: finishes within the deadline; charge its latency.
            self._clock["t"] += min(self._latency, timeout if timeout else self._latency)
            if self._exc is not None:
                raise self._exc
            return self._value
        # Slow server: the wait is abandoned at the deadline. We charge exactly
        # the deadline (never the server's true latency) and raise, mirroring a
        # real future whose work has not completed by ``timeout``.
        self._clock["t"] += timeout if timeout else 0.0
        raise FuturesTimeoutError()


class _FakeExecutor:
    """Executor stand-in that calls ``collect`` eagerly and wraps the outcome.

    It does not spawn threads: ``submit`` decides immediately whether the
    server is fast (``collect`` is invoked now and the result captured) or slow
    (``collect`` is NOT invoked — the future simply never completes). This lets
    us model slowness without any sleeping while keeping ``collect`` honest for
    the reachable servers.
    """

    def __init__(self, clock, slow_servers, latency_for, max_workers=None):
        self._clock = clock
        self._slow_servers = slow_servers
        self._latency_for = latency_for
        self.max_workers = max_workers
        self.shutdown_calls = []

    def submit(self, fn, server):
        sid = server.get("id")
        if sid in self._slow_servers:
            # Slow/hung server: no eager call; the future never completes.
            return _FakeFuture(self._clock, done=False,
                               latency=self._latency_for(sid))
        # Fast/reachable server: run the collector now and capture its outcome.
        try:
            value = fn(server)
            return _FakeFuture(self._clock, done=True, value=value,
                               latency=self._latency_for(sid))
        except Exception as exc:  # noqa: BLE001 - propagate via future.result()
            return _FakeFuture(self._clock, done=True, exc=exc,
                               latency=self._latency_for(sid))

    def shutdown(self, wait=True, cancel_futures=False):
        self.shutdown_calls.append((wait, cancel_futures))


# --------------------------------------------------------------------------- #
# Collector / classifier doubles
# --------------------------------------------------------------------------- #
def _classify(_obs):
    """Trivial classifier: a stable, pure classification for any observation."""
    return {"classification": "managed", "score": 1.0, "evidence": ["fake"]}


def _make_collect(reachable_obs, collector_errors, raising_servers):
    """Build a ``collect(server) -> (observations, error|None)`` double.

    ``reachable_obs``: {server_id: [observation dicts]} for reachable servers.
    ``collector_errors``: {server_id: "error string"} for servers that the
        collector reports unreachable (returns ``(None, error)``).
    ``raising_servers``: set of server ids whose collector raises (modelling an
        exception rather than a clean error return).
    """
    def collect(server):
        sid = server.get("id")
        if sid in raising_servers:
            raise RuntimeError(f"collector boom for {sid}")
        if sid in collector_errors:
            return (None, collector_errors[sid])
        return (reachable_obs.get(sid, []), None)

    return collect


# --------------------------------------------------------------------------- #
# Strategies
# --------------------------------------------------------------------------- #
def _server(i):
    return {"id": i, "server_ip": f"10.0.0.{i}", "server_name": f"srv-{i}"}


@st.composite
def _scan_scenario(draw):
    """Draw a scan scenario: N servers each classified fast / slow / error / raise.

    Returns ``(servers, slow_ids, collector_errors, raising_ids,
    reachable_obs, deadline, latency_for)``.
    """
    n = draw(st.integers(min_value=1, max_value=6))
    servers = [_server(i) for i in range(n)]
    deadline = draw(st.floats(min_value=0.5, max_value=5.0))

    slow_ids = set()
    collector_errors = {}
    raising_ids = set()
    reachable_obs = {}
    latencies = {}

    for s in servers:
        sid = s["id"]
        kind = draw(st.sampled_from(["fast", "fast", "slow", "error", "raise"]))
        if kind == "slow":
            slow_ids.add(sid)
            # A slow server's true latency exceeds the deadline — but the wait
            # must be charged the deadline, not this latency.
            latencies[sid] = draw(st.floats(min_value=deadline * 2,
                                             max_value=deadline * 10))
        elif kind == "error":
            collector_errors[sid] = draw(st.sampled_from(
                ["connection refused", "unreachable", "ssh: handshake failed"]
            ))
            latencies[sid] = draw(st.floats(min_value=0.0, max_value=deadline))
        elif kind == "raise":
            raising_ids.add(sid)
            latencies[sid] = draw(st.floats(min_value=0.0, max_value=deadline))
        else:  # fast reachable
            k = draw(st.integers(min_value=0, max_value=3))
            reachable_obs[sid] = [
                {"container_id": f"c{sid}-{j}", "name": f"ct-{sid}-{j}",
                 "image": "img", "state": "running"}
                for j in range(k)
            ]
            latencies[sid] = draw(st.floats(min_value=0.0, max_value=deadline))

    def latency_for(sid):
        return latencies[sid]

    return (servers, slow_ids, collector_errors, raising_ids,
            reachable_obs, deadline, latency_for)


# --------------------------------------------------------------------------- #
# Property 15a — parallel scan bounded by the per-server deadline
# --------------------------------------------------------------------------- #
@settings(max_examples=200, deadline=None)
@given(scenario=_scan_scenario())
def test_property15_parallel_scan_bounded_by_deadline(scenario):
    """Feature: phase4-runtime-execution-hardening, Property 15.

    With a fake slow collector and a fake executor:
      * reachable servers' containers are aggregated in input order,
      * slow / error / raising servers contribute NO containers and each
        records exactly one ``{server_id, error}`` entry, and
      * the total wait is bounded by (max_workers waves of) the per-server
        deadline — never the sum of the servers' true latencies.

    Validates Requirements 5.7.
    """
    (servers, slow_ids, collector_errors, raising_ids,
     reachable_obs, deadline, latency_for) = scenario

    clock = {"t": 0.0}
    collect = _make_collect(reachable_obs, collector_errors, raising_ids)

    def factory(max_workers=None):
        return _FakeExecutor(clock, slow_ids, latency_for, max_workers=max_workers)

    result = scan_live_parallel(
        servers, collect, _classify,
        max_workers=8,
        per_server_deadline=deadline,
        executor_factory=factory,
    )

    assert result["success"] is True

    # --- reachable servers aggregate their containers IN INPUT ORDER --------- #
    expected_ids = []
    for s in servers:
        sid = s["id"]
        if sid in slow_ids or sid in collector_errors or sid in raising_ids:
            continue
        for obs in reachable_obs.get(sid, []):
            expected_ids.append(obs["container_id"])

    actual_ids = [c["container_id"] for c in result["containers"]]
    assert actual_ids == expected_ids, (
        f"containers not aggregated in input order: {actual_ids} != {expected_ids}"
    )

    # --- every slow / error / raising server is recorded as a per-server error #
    error_sids = [e["server_id"] for e in result["errors"]]
    expected_error_sids = sorted(slow_ids | set(collector_errors) | raising_ids)
    assert sorted(error_sids) == expected_error_sids
    # No server is recorded twice, and no container came from an errored server.
    assert len(error_sids) == len(set(error_sids))

    # --- the TOTAL wait is bounded by the deadline, never the sum ------------ #
    # The fake clock charged each server's wait: a fast server its (<=deadline)
    # latency, every slow server exactly the deadline. So the accumulated wait
    # can never exceed (number_of_servers * deadline), and crucially it never
    # includes any slow server's true (super-deadline) latency.
    assert clock["t"] <= len(servers) * deadline + 1e-6
    # If any server is slow, its real latency (> deadline) must NOT have been
    # paid: the whole point of the per-server deadline (R5.7).
    for sid in slow_ids:
        assert latency_for(sid) > deadline  # scenario invariant
    sum_true_latencies = sum(latency_for(s["id"]) for s in servers)
    if slow_ids:
        # With at least one slow server, the bounded wait is strictly below the
        # serial sum of true latencies — slowness did not serialize the scan.
        assert clock["t"] < sum_true_latencies


@settings(max_examples=150, deadline=None)
@given(
    n=st.integers(min_value=1, max_value=6),
    deadline=st.floats(min_value=0.5, max_value=5.0),
)
def test_property15_all_slow_servers_all_errors_no_containers(n, deadline):
    """Feature: phase4-runtime-execution-hardening, Property 15.

    When every server is slow/hung, the scan yields zero containers and one
    per-server error for each server, and the bounded wait is at most
    ``n * deadline`` — the sum of the servers' true (super-deadline) latencies
    is never paid. Validates Requirements 5.7.
    """
    servers = [_server(i) for i in range(n)]
    slow_ids = {s["id"] for s in servers}
    latencies = {s["id"]: deadline * 5 for s in servers}
    clock = {"t": 0.0}

    collect = _make_collect({}, {}, set())  # never actually invoked for slow ids

    def factory(max_workers=None):
        return _FakeExecutor(clock, slow_ids, lambda sid: latencies[sid],
                             max_workers=max_workers)

    result = scan_live_parallel(
        servers, collect, _classify,
        max_workers=8, per_server_deadline=deadline, executor_factory=factory,
    )

    assert result["containers"] == []
    assert sorted(e["server_id"] for e in result["errors"]) == [s["id"] for s in servers]
    assert clock["t"] <= n * deadline + 1e-6
    assert clock["t"] < sum(latencies.values())  # never the serial sum


def test_empty_servers_short_circuits():
    """No servers -> empty envelope, executor never constructed."""
    calls = {"n": 0}

    def factory(max_workers=None):
        calls["n"] += 1
        return None

    result = scan_live_parallel(
        [], _make_collect({}, {}, set()), _classify,
        max_workers=4, per_server_deadline=1.0, executor_factory=factory,
    )
    assert result == {"success": True, "containers": [], "errors": []}
    assert calls["n"] == 0


# --------------------------------------------------------------------------- #
# Property 15b — actuation argv building (fake ssh, no SSH)
# --------------------------------------------------------------------------- #
class _FakeSSH:
    """Records every ``(server_ip, argv, timeout)`` and returns a fixed tuple."""

    def __init__(self, ret=(True, "ok", "")):
        self.calls = []
        self._ret = ret

    def __call__(self, server_ip, argv, timeout=None):
        self.calls.append({"server_ip": server_ip, "argv": argv, "timeout": timeout})
        return self._ret


# A container reference strategy: ids and names (and refs with surrounding
# whitespace that ``actuate`` strips).
_container_ref = st.one_of(
    st.text(alphabet="abcdef0123456789", min_size=1, max_size=20),
    st.sampled_from(["my-app", "web_1", "svc.worker", "a1b2c3d4e5f6"]),
    st.builds(lambda s: f"  {s}  ",
              st.text(alphabet="abcdef0123456789", min_size=1, max_size=12)),
)

_server_ip = st.builds(
    lambda a, b: f"{a}.{b}.0.1",
    a=st.integers(min_value=1, max_value=255),
    b=st.integers(min_value=0, max_value=255),
)


@settings(max_examples=200, deadline=None)
@given(
    server_ip=_server_ip,
    container_ref=_container_ref,
    action=st.sampled_from(_ACTUATE_ACTIONS),
    timeout=st.integers(min_value=1, max_value=600),
)
def test_property15_actuation_argv_building(server_ip, container_ref, action, timeout):
    """Feature: phase4-runtime-execution-hardening, Property 15.

    For each action (start/stop/restart) and any server_ip / container_ref /
    timeout, ``actuate`` builds exactly ``[\"docker\", action, ref]`` (ref the
    stripped reference), dispatches it through the injected ``ssh`` with
    ``(server_ip, argv, timeout=timeout)``, and returns the ssh tuple
    unchanged. Server-selection and command-building are thus asserted without
    any real SSH. Validates Requirements 5.6, 5.9.
    """
    fake_ssh = _FakeSSH(ret=(True, "stdout-sentinel", "stderr-sentinel"))

    ret = actuate(server_ip, container_ref, action, ssh=fake_ssh, timeout=timeout)

    # Exactly one dispatch through the injected transport.
    assert len(fake_ssh.calls) == 1
    call = fake_ssh.calls[0]

    # Server-selection: the actuation targets the given server_ip.
    assert call["server_ip"] == server_ip
    # Command-building: docker <action> <stripped-ref>, argv form (no shell).
    expected_ref = container_ref.strip()
    assert call["argv"] == ["docker", action, expected_ref]
    # The configured timeout is propagated to the transport.
    assert call["timeout"] == timeout
    # The ssh tuple is returned unchanged (same contract as the rest of the
    # remote-execution surface).
    assert ret == (True, "stdout-sentinel", "stderr-sentinel")


@settings(max_examples=100, deadline=None)
@given(
    server_ip=_server_ip,
    container_ref=st.sampled_from(["c1", "web", "a1b2c3"]),
    action=st.text(min_size=0, max_size=8).filter(lambda a: a not in _ACTUATE_ACTIONS),
)
def test_property15_unsupported_action_rejected_before_dispatch(
    server_ip, container_ref, action
):
    """Feature: phase4-runtime-execution-hardening, Property 15.

    An unsupported action is rejected with ``ValueError`` before any dispatch:
    the injected ``ssh`` is never called, so no command is built or run.
    Validates Requirements 5.6, 5.9.
    """
    fake_ssh = _FakeSSH()
    with pytest.raises(ValueError):
        actuate(server_ip, container_ref, action, ssh=fake_ssh)
    assert fake_ssh.calls == []


@settings(max_examples=100, deadline=None)
@given(
    server_ip=_server_ip,
    action=st.sampled_from(_ACTUATE_ACTIONS),
    blank=st.sampled_from(["", "   ", "\t", "\n"]),
)
def test_property15_blank_container_ref_rejected_before_dispatch(
    server_ip, action, blank
):
    """Feature: phase4-runtime-execution-hardening, Property 15.

    A blank/whitespace-only container reference is rejected with ``ValueError``
    before any dispatch: the injected ``ssh`` is never called.
    Validates Requirements 5.6, 5.9.
    """
    fake_ssh = _FakeSSH()
    with pytest.raises(ValueError):
        actuate(server_ip, blank, action, ssh=fake_ssh)
    assert fake_ssh.calls == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
