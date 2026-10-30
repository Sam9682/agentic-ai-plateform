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


def test_launch_uses_ssh(monkeypatch):
    calls = {}

    def fake_ssh(server_ip, command, timeout=30):
        calls["server_ip"] = server_ip
        calls["command"] = command
        return True, "containerid123\n", ""

    monkeypatch.setattr(em, "_ssh", lambda: fake_ssh)
    ok, out, err = em.launch(
        "10.0.0.5", "kiro:1.0", {"network_policy": "proxy"},
        name="c1", proxy_url="http://p:3128",
    )
    assert ok is True
    assert out == "containerid123"
    assert "docker run -d --name c1" in calls["command"]
    assert "--cap-drop ALL" in calls["command"]


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
