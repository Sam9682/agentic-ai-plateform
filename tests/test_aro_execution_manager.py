#!/usr/bin/env python3
"""Property + unit tests for the hardened execution manager (Task 6).

Feature: ARO execution environment management (SRS §3.3, §9).

Validates (pure command-assembly, no SSH):
* every assembled run command emits least-privilege flags
  (--cap-drop ALL, no-new-privileges, non-root user, pids/memory/cpu limits);
* every assembled command restricts egress (never open): --network none or the
  dedicated proxy network with proxy env injected;
* no forbidden fragment (--privileged, docker.sock, --cap-add, host net/pid)
  can ever appear, for arbitrary env inputs;
* requesting a forbidden privilege raises ExecutionPolicyError before any run;
* launch()/stop() shell out through a stubbed ssh_execute.

Run directly:
    python3 tests/test_aro_execution_manager.py
Or via pytest:
    pytest tests/test_aro_execution_manager.py
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

from src.aro import execution_manager as em  # noqa: E402


def _has_pair(argv, flag, value):
    for i in range(len(argv) - 1):
        if argv[i] == flag and argv[i + 1] == value:
            return True
    return False


def test_least_privilege_flags_present():
    argv = em.build_run_command("img:1.0", "c1", {"network_policy": "none"})
    assert _has_pair(argv, "--cap-drop", "ALL")
    assert _has_pair(argv, "--security-opt", "no-new-privileges")
    assert "--read-only" in argv
    assert _has_pair(argv, "--user", "nobody")
    assert _has_pair(argv, "--pids-limit", "256")
    assert _has_pair(argv, "--memory", "512m")
    assert _has_pair(argv, "--cpus", "1")


def test_network_none_isolates():
    argv = em.build_run_command("img:1.0", "c1", {"network_policy": "none"})
    assert _has_pair(argv, "--network", "none")


def test_proxy_network_injects_proxy_env():
    argv = em.build_run_command(
        "img:1.0", "c1", {"network_policy": "proxy"}, proxy_url="http://zaf-proxy:3128"
    )
    assert _has_pair(argv, "--network", "zaf-proxy-net")
    joined = " ".join(argv)
    assert "HTTP_PROXY=http://zaf-proxy:3128" in joined
    assert "HTTPS_PROXY=http://zaf-proxy:3128" in joined


def test_privileged_rejected():
    try:
        em.build_run_command("img:1.0", "c1", {"privileged": True})
        assert False
    except em.ExecutionPolicyError:
        pass


def test_docker_socket_mount_rejected():
    try:
        em.build_run_command(
            "img:1.0", "c1",
            {"volumes": ["/var/run/docker.sock:/var/run/docker.sock"]},
        )
        assert False
    except em.ExecutionPolicyError:
        pass


_env_strategy = st.fixed_dictionaries({
    "cpu_limit": st.sampled_from(["1", "2", "0.5"]),
    "memory_limit": st.sampled_from(["256m", "512m", "1g"]),
    "pids_limit": st.integers(min_value=16, max_value=1024),
    "read_only": st.booleans(),
    "run_as_user": st.sampled_from(["nobody", "agent", "1000"]),
    "network_policy": st.sampled_from(["none", "proxy"]),
    "env": st.dictionaries(
        st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ_", min_size=1, max_size=8),
        st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=0, max_size=12),
        max_size=4,
    ),
})


@given(environment=_env_strategy)
@settings(max_examples=200)
def test_property_never_forbidden_and_always_restricted(environment):
    argv = em.build_run_command("img:1.0", "c1", environment, proxy_url="http://p:3128")
    joined = " ".join(argv)
    # Never a forbidden fragment.
    for frag in em.FORBIDDEN_FRAGMENTS:
        assert frag not in joined
    # Always least privilege.
    assert _has_pair(argv, "--cap-drop", "ALL")
    # Always an egress restriction (never open network).
    assert _has_pair(argv, "--network", "none") or _has_pair(argv, "--network", "zaf-proxy-net")
    # Never "--network host" / bridge default (which would allow open egress).
    assert "host" not in joined.split("--network ")[-1][:8] if "--network" in joined else True


# --------------------------------------------------------------------------- #
# Property 15 (validator portion): image-pin validation
# --------------------------------------------------------------------------- #
# A valid Docker image name component: lowercase, may include separators and a
# registry/namespace path. Kept simple but representative of real refs.
_name_strategy = st.from_regex(
    r"[a-z][a-z0-9]{0,8}(?:[/.-][a-z0-9]{1,8}){0,3}",
    fullmatch=True,
)
# A 64-char lowercase hex digest.
_digest_strategy = st.text(alphabet="0123456789abcdef", min_size=64, max_size=64)
# A mutable tag that is not "latest".
_tag_strategy = st.from_regex(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,10}", fullmatch=True).filter(
    lambda t: t.lower() != "latest"
)


@st.composite
def _pinned_refs(draw):
    """name@sha256:<64-hex>, optionally also carrying a tag (still pinned)."""
    name = draw(_name_strategy)
    digest = draw(_digest_strategy)
    with_tag = draw(st.booleans())
    if with_tag:
        tag = draw(_tag_strategy)
        return f"{name}:{tag}@sha256:{digest}"
    return f"{name}@sha256:{digest}"


@st.composite
def _unpinned_refs(draw):
    """One of: tag-less (no digest), ':latest', or a bare mutable tag."""
    name = draw(_name_strategy)
    kind = draw(st.sampled_from(("tagless", "latest", "tag")))
    if kind == "tagless":
        return name
    if kind == "latest":
        # arbitrary casing of 'latest' must still be rejected
        latest = draw(st.sampled_from(("latest", "LATEST", "Latest")))
        return f"{name}:{latest}"
    tag = draw(_tag_strategy)
    return f"{name}:{tag}"


@given(image=_pinned_refs())
@settings(max_examples=150)
def test_property15_digest_pinned_images_accepted(image):
    """Digest-pinned images pass the validator with no error.

    Feature: phase2-aro-completion, Property 15: Unpinned images are rejected
    before any remote command (validator portion).
    Validates: Requirements 3.3
    """
    # Must not raise; returns None.
    assert em.assert_image_pinned(image) is None


@given(image=_unpinned_refs())
@settings(max_examples=150)
def test_property15_unpinned_images_rejected(image):
    """Un-pinned images (tag-less, ':latest', bare tag) are rejected.

    Feature: phase2-aro-completion, Property 15: Unpinned images are rejected
    before any remote command (validator portion).
    Validates: Requirements 3.3
    """
    try:
        em.assert_image_pinned(image)
    except em.ExecutionPolicyError:
        return
    raise AssertionError(f"expected ExecutionPolicyError for unpinned ref {image!r}")


# --------------------------------------------------------------------------- #
# Property 17: Launch always emits hardening and never a forbidden fragment
# --------------------------------------------------------------------------- #
# Arbitrary *valid* image (digest-pinned or bare tag — build_run_command does
# not gate on pinning; that is assert_image_pinned's job) paired with arbitrary
# valid environments. The assembled run command must ALWAYS carry the required
# least-privilege hardening and NEVER carry any forbidden fragment.
_image_strategy = st.one_of(
    st.just("img:1.0"),
    st.builds(lambda n, d: f"{n}@sha256:{d}", _name_strategy, _digest_strategy),
    st.builds(lambda n, t: f"{n}:{t}", _name_strategy, _tag_strategy),
)


@given(image=_image_strategy, environment=_env_strategy)
@settings(max_examples=150)
def test_property17_launch_always_hardens_never_forbidden(image, environment):
    """Feature: phase2-aro-completion, Property 17: Launch always emits hardening
    and never a forbidden fragment.

    For arbitrary valid environments/images, the assembled run command ALWAYS
    contains the required least-privilege hardening flags and NEVER contains any
    forbidden fragment.
    Validates: Requirements 3.7
    """
    argv = em.build_run_command(image, "c1", environment, proxy_url="http://p:3128")
    joined = " ".join(argv)

    # Required hardening flags are always present (AC 3.7).
    assert _has_pair(argv, "--cap-drop", "ALL")
    assert _has_pair(argv, "--security-opt", "no-new-privileges")
    assert _has_pair(argv, "--pids-limit", str(int(environment["pids_limit"])))
    assert _has_pair(argv, "--memory", environment["memory_limit"])
    assert _has_pair(argv, "--cpus", environment["cpu_limit"])
    assert _has_pair(argv, "--user", environment["run_as_user"])
    # Egress is always restricted; the default bridge/host network is never used.
    assert _has_pair(argv, "--network", "none") or _has_pair(
        argv, "--network", "zaf-proxy-net"
    )

    # No forbidden fragment is ever emitted (AC 3.7).
    for frag in em.FORBIDDEN_FRAGMENTS:
        assert frag not in joined


# A strategy that injects a forbidden fragment into the environment via an env
# var key or value, or via a privileged/docker-socket request. Every one of
# these inputs would introduce a forbidden fragment and MUST be rejected.
@st.composite
def _forbidden_environments(draw):
    frag = draw(st.sampled_from(em.FORBIDDEN_FRAGMENTS))
    kind = draw(st.sampled_from(("env_value", "env_key", "privileged", "volume")))
    if kind == "privileged":
        return {"network_policy": "none", "privileged": True}
    if kind == "volume":
        return {
            "network_policy": "none",
            "volumes": ["/var/run/docker.sock:/var/run/docker.sock"],
        }
    if kind == "env_key":
        return {"network_policy": "none", "env": {frag: "x"}}
    return {"network_policy": "none", "env": {"INJECT": frag}}


@given(environment=_forbidden_environments())
@settings(max_examples=150)
def test_property17_forbidden_introducing_input_raises(environment):
    """Feature: phase2-aro-completion, Property 17: Launch always emits hardening
    and never a forbidden fragment.

    When an input would introduce a forbidden fragment (a forbidden flag smuggled
    through an env key/value, a privileged request, or a docker-socket mount),
    assembly raises ExecutionPolicyError and never returns a command.
    Validates: Requirements 3.7
    """
    try:
        em.build_run_command("img:1.0", "c1", environment, proxy_url="http://p:3128")
    except em.ExecutionPolicyError:
        return
    raise AssertionError(
        f"expected ExecutionPolicyError for forbidden-introducing env {environment!r}"
    )


# --------------------------------------------------------------------------- #
# Property 15 (launch-integration portion): no remote command on rejection
# --------------------------------------------------------------------------- #
# The validator portion (test_property15_*) proves assert_image_pinned's pure
# decision. This portion proves the integration contract from AC 3.3: launch()
# calls assert_image_pinned FIRST, so an unpinned image is rejected with
# ExecutionPolicyError and NO remote command is ever issued. A recording fake
# ssh (injected via monkeypatching em._ssh) must never be invoked.


class _RecordingSsh:
    """A fake ssh_execute that records every remote command it is asked to run.

    If launch() honors the pin gate, this is never called for an unpinned image,
    so ``commands`` stays empty and ``called`` stays False.
    """

    def __init__(self):
        self.commands = []
        self.called = False

    def __call__(self, server_ip, command, timeout=30):
        self.called = True
        self.commands.append((server_ip, command))
        # Report success so a (hypothetical) proceed path would look healthy —
        # the point is that for unpinned images we must never get here at all.
        return True, "containerid\n", ""


@contextmanager
def _patched_ssh(rec):
    """Temporarily point em._ssh at the recording fake, then restore it.

    Used in place of the function-scoped ``monkeypatch`` fixture, which
    Hypothesis rejects inside ``@given`` because it is not reset per example.
    """
    original = em._ssh
    em._ssh = lambda: rec
    try:
        yield
    finally:
        em._ssh = original


@given(image=_unpinned_refs())
@settings(max_examples=150)
def test_property15_launch_issues_no_remote_command_on_rejection(image):
    """launch() issues zero remote commands when the image is unpinned.

    Feature: phase2-aro-completion, Property 15: Unpinned images are rejected
    before any remote command (launch-integration portion).
    Validates: Requirements 3.3

    For any unpinned image reference, launch() must raise ExecutionPolicyError
    and the injected ssh_execute must never be called — proving the pin check
    runs before (and gates) any remote command.
    """
    rec = _RecordingSsh()
    with _patched_ssh(rec):
        try:
            em.launch(
                "10.0.0.5", image, {"network_policy": "proxy"},
                name="c1", proxy_url="http://p:3128",
            )
        except em.ExecutionPolicyError:
            # Expected: rejected before any remote command.
            assert rec.called is False, (
                f"ssh_execute was invoked for unpinned image {image!r}: {rec.commands}"
            )
            assert rec.commands == []
            return
    raise AssertionError(
        f"expected ExecutionPolicyError for unpinned ref {image!r}; "
        f"remote commands issued: {rec.commands}"
    )


@given(
    name=_name_strategy,
    digest=_digest_strategy,
)
@settings(max_examples=150)
def test_property15_launch_pinned_image_proceeds_to_ssh(name, digest):
    """A digest-pinned image passes the gate and launch() issues SSH.

    Feature: phase2-aro-completion, Property 15: Unpinned images are rejected
    before any remote command (launch-integration portion, sanity check).
    Validates: Requirements 3.3

    Complements the rejection property: a properly ``name@sha256:...`` image
    must NOT be gated — launch() proceeds and the injected ssh_execute is
    invoked (here: the proxy-net probe then the docker run).
    """
    rec = _RecordingSsh()
    with _patched_ssh(rec):
        pinned = f"{name}@sha256:{digest}"
        ok, out, _err = em.launch(
            "10.0.0.5", pinned, {"network_policy": "proxy"},
            name="c1", proxy_url="http://p:3128",
        )
    assert ok is True
    # The pin gate let the launch through, so at least one remote command ran.
    assert rec.called is True
    assert len(rec.commands) >= 1
    # A docker run command must have been issued for the pinned image.
    assert any("docker run -d --name c1" in cmd for _ip, cmd in rec.commands)


def test_launch_uses_ssh(monkeypatch):
    calls = {"commands": []}

    def fake_ssh(server_ip, command, timeout=30):
        calls["server_ip"] = server_ip
        calls["command"] = command
        calls["commands"].append(command)
        return True, "containerid123\n", ""

    monkeypatch.setattr(em, "_ssh", lambda: fake_ssh)
    # Image must be digest-pinned now that launch() calls assert_image_pinned()
    # first (Task 6.3 / AC 3.3). A 64-hex sha256 digest is a pinned reference;
    # the previous "kiro:1.0" bare tag is rejected before any SSH is issued.
    pinned = "kiro@sha256:" + ("a" * 64)
    ok, out, err = em.launch(
        "10.0.0.5", pinned, {"network_policy": "proxy"},
        name="c1", proxy_url="http://p:3128",
    )
    assert ok is True
    assert out == "containerid123"
    # With the proxy policy, launch first probes zaf-proxy-net, then runs docker.
    assert any("docker network inspect zaf-proxy-net" in c for c in calls["commands"])
    # SSH-command assertions preserved against the docker-run command (last call).
    assert "docker run -d --name c1" in calls["command"]
    assert "--cap-drop ALL" in calls["command"]


# --------------------------------------------------------------------------- #
# Property 16: Bounded launch retry
# --------------------------------------------------------------------------- #
# A digest-pinned image so the pin check (which runs before any remote command)
# passes and the retry loop around the docker-run is actually exercised.
_PINNED_IMAGE = "kiro@sha256:" + ("b" * 64)
# A stderr guaranteed to be classified transient by em._is_transient_failure.
_TRANSIENT_STDERR = "ssh: connect to host 10.0.0.5 port 22: Connection refused"


@given(n=st.integers(min_value=0, max_value=8))
@settings(max_examples=150)
def test_property16_bounded_retry_on_persistent_transient_failure(n):
    """A persistently transient docker-run fails after exactly 1 + N attempts.

    With a fake ssh that always returns a transient failure for the docker-run
    command, launch(max_retries=N) re-attempts the run up to N additional times
    and no more — at most 1 + N total docker-run attempts — then returns the
    last failure. network_policy='none' skips the proxy-net probe so every
    recorded ssh call is a docker-run attempt (clean counting).

    A per-example MonkeyPatch context is used (instead of the function-scoped
    monkeypatch fixture) so the ssh stub is installed and torn down cleanly for
    each Hypothesis example.

    Feature: phase2-aro-completion, Property 16: Bounded launch retry.
    Validates: Requirements 3.6
    """
    calls = {"count": 0}

    def fake_ssh(server_ip, command, timeout=30):
        calls["count"] += 1
        return False, "", _TRANSIENT_STDERR

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(em, "_ssh", lambda: fake_ssh)
        ok, _out, err = em.launch(
            "10.0.0.5",
            _PINNED_IMAGE,
            {"network_policy": "none"},
            name="c1",
            max_retries=n,
        )

    # Persistent transient failure: launch gives up and reports failure.
    assert ok is False
    assert err == _TRANSIENT_STDERR
    # Exactly 1 initial attempt + N retries = 1 + N docker-run attempts.
    assert calls["count"] == 1 + n


@given(n=st.integers(min_value=0, max_value=8))
@settings(max_examples=150)
def test_property16_policy_failure_is_never_retried(n):
    """An unpinned image raises before any remote command — zero attempts, no retry.

    A policy rejection (unpinned image) is raised by assert_image_pinned, which
    runs before the retry loop, so launch issues zero remote commands and never
    retries regardless of max_retries=N.

    Feature: phase2-aro-completion, Property 16: Bounded launch retry.
    Validates: Requirements 3.6
    """
    calls = {"count": 0}

    def fake_ssh(server_ip, command, timeout=30):
        calls["count"] += 1
        return True, "containerid\n", ""

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(em, "_ssh", lambda: fake_ssh)
        # ':latest' is unpinned -> ExecutionPolicyError before any remote command.
        try:
            em.launch(
                "10.0.0.5",
                "kiro:latest",
                {"network_policy": "none"},
                name="c1",
                max_retries=n,
            )
        except em.ExecutionPolicyError:
            # Policy failures must never reach ssh and must never be retried.
            assert calls["count"] == 0
            return
    raise AssertionError("expected ExecutionPolicyError for unpinned image")


def test_stop_uses_ssh(monkeypatch):
    seen = {}

    def fake_ssh(server_ip, command, timeout=30):
        seen["command"] = command
        return True, "", ""

    monkeypatch.setattr(em, "_ssh", lambda: fake_ssh)
    ok, _, _ = em.stop("10.0.0.5", "c1")
    assert ok is True
    assert "docker stop c1" in seen["command"]
    assert "docker rm c1" in seen["command"]


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))


# --------------------------------------------------------------------------- #
# Property 14: Server selection picks the least-loaded eligible server
# --------------------------------------------------------------------------- #
# select_server() trusts the SQL "ORDER BY load ASC, id ASC" to present
# candidates in least-loaded-then-lowest-id order, then applies the pure
# tenant_eligible() predicate and returns the first eligible row (or None).
# We mock the DB layer so execute_query returns generated (id, server_ip,
# server_name, load) rows in exactly that DB order, and drive the eligibility
# filter via a monkeypatched tenant_eligible to exercise both the
# "some eligible" and "none eligible" paths.


class _FakeDb:
    """Minimal stand-in for db_manager returning pre-ordered rows."""

    def __init__(self, rows):
        self._rows = rows

    def execute_query(self, query, params=None, fetch_all=False):
        # select_server passes fetch_all=True and expects a list of tuples.
        return list(self._rows)


# A server row as the DB would return it: (id, server_ip, server_name, load).
_server_row_strategy = st.tuples(
    st.integers(min_value=1, max_value=10_000),   # id
    st.text(alphabet="0123456789.", min_size=3, max_size=15),  # server_ip
    st.text(alphabet="abcdefghijklmnopqrstuvwxyz-", min_size=1, max_size=12),  # name
    st.integers(min_value=0, max_value=1000),     # load
)


@st.composite
def _distinct_id_rows(draw):
    """Generate rows with unique ids (ids are a PK), then order them the way
    the SQL query does: load ASC, id ASC."""
    rows = draw(st.lists(_server_row_strategy, min_size=0, max_size=8))
    # Enforce unique ids (primary key) so tie-breaking by id is well defined.
    seen = set()
    unique = []
    for r in rows:
        if r[0] in seen:
            continue
        seen.add(r[0])
        unique.append(r)
    # Mimic the DB "ORDER BY load ASC, s.id ASC".
    unique.sort(key=lambda r: (r[3], r[0]))
    return unique


def _expected_first_eligible(ordered_rows, eligible_pred):
    """Reference implementation: first eligible row in DB order, else None."""
    for r in ordered_rows:
        candidate = {"id": r[0], "server_ip": r[1], "server_name": r[2], "load": r[3]}
        if eligible_pred(candidate):
            return candidate
    return None


@given(
    rows=_distinct_id_rows(),
    tenant_id=st.one_of(st.none(), st.integers(min_value=1, max_value=50)),
)
@settings(max_examples=200)
def test_property14_selects_least_loaded_eligible(rows, tenant_id):
    """The chosen server is the eligible one with minimum load (ties by lowest id).

    Feature: phase2-aro-completion, Property 14: Server selection picks the
    least-loaded eligible server.
    Validates: Requirements 3.1, 3.2
    """
    # Use a context-managed monkeypatch so each generated example is isolated
    # (a function-scoped pytest fixture is not reset between @given examples).
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(em, "_get_db", lambda: _FakeDb(rows))
        # Default eligibility: every active server is eligible.
        mp.setattr(em, "tenant_eligible", lambda row, tid: True)

        result = em.select_server(tenant_id)

    expected = _expected_first_eligible(rows, lambda c: True)
    assert result == expected
    if expected is not None:
        # The winner must have the minimum load among all candidates, and be
        # the lowest id among those sharing that minimum load.
        min_load = min(r[3] for r in rows)
        assert result["load"] == min_load
        min_id_at_min_load = min(r[0] for r in rows if r[3] == min_load)
        assert result["id"] == min_id_at_min_load


@given(
    rows=_distinct_id_rows(),
    tenant_id=st.one_of(st.none(), st.integers(min_value=1, max_value=50)),
    # A set of ids that are eligible; everything else is excluded.
    eligible_ids=st.sets(st.integers(min_value=1, max_value=10_000), max_size=8),
)
@settings(max_examples=200)
def test_property14_eligibility_filter_and_none(rows, tenant_id, eligible_ids):
    """With an eligibility predicate, the first eligible row in DB order wins;
    when no row is eligible (or there are none), select_server returns None.

    Feature: phase2-aro-completion, Property 14: Server selection picks the
    least-loaded eligible server.
    Validates: Requirements 3.1, 3.2
    """
    pred = lambda row, tid: row["id"] in eligible_ids
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(em, "_get_db", lambda: _FakeDb(rows))
        mp.setattr(em, "tenant_eligible", pred)

        result = em.select_server(tenant_id)

    expected = _expected_first_eligible(rows, lambda c: c["id"] in eligible_ids)
    assert result == expected

    if expected is None:
        # Either no servers, or none eligible -> None (AC 3.2).
        assert result is None
    else:
        # The winner is eligible and is the least-loaded eligible row
        # (ties broken by lowest id) among eligible candidates.
        eligible = [r for r in rows if r[0] in eligible_ids]
        min_load = min(r[3] for r in eligible)
        assert result["load"] == min_load
        min_id_at_min_load = min(r[0] for r in eligible if r[3] == min_load)
        assert result["id"] == min_id_at_min_load


def test_property14_empty_returns_none(monkeypatch):
    """No candidate servers -> None (unit example for the empty path)."""
    monkeypatch.setattr(em, "_get_db", lambda: _FakeDb([]))
    assert em.select_server(7) is None
