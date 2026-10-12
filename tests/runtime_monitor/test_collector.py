#!/usr/bin/env python3
"""Tests for the SSH-based runtime collector.

The SSH call is mocked with captured ``docker`` output fixtures, including an
externally-launched container that carries no platform labels. No network is
used. Run directly or via pytest.
"""
import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from src.runtime_monitor import runtime_collector as rc


# --- Fixtures: captured docker command output -------------------------------

PS_JSON_LINES = "\n".join([
    json.dumps({
        "ID": "aaaa1111bbbb",
        "Names": "/coding-worker-01",
        "Image": "ghcr.io/acme/coding-agent:latest",
        "State": "running",
        "Status": "Up 3 hours",
        "Command": "python agent.py",
        "Labels": "opcp.managed=true",
    }),
    json.dumps({
        "ID": "cccc2222dddd",
        "Names": "/web-service-02",
        "Image": "nginx:1.27-alpine",
        "State": "running",
        "Status": "Up 10 minutes",
        "Command": "nginx -g daemon off;",
        "Labels": "",
    }),
    # Externally launched: no platform label, agent-like image name.
    json.dumps({
        "ID": "eeee3333ffff",
        "Names": "/task-runner-03",
        "Image": "kiro-runtime:dev",
        "State": "exited",
        "Status": "Exited (0) 2 minutes ago",
        "Command": "node index.js",
        "Labels": "maintainer=external",
    }),
])

INSPECT_JSON = json.dumps([
    {
        "Id": "aaaa1111bbbb0000000000000000000000000000000000000000000000000000",
        "Config": {
            "Image": "ghcr.io/acme/coding-agent:latest",
            "Labels": {"opcp.managed": "true"},
            "Env": ["OPENAI_API_KEY=sk-xxx", "ROLE=agent"],
        },
        "State": {"Status": "running"},
        "HostConfig": {"Runtime": "runc"},
    },
    {
        "Id": "cccc2222dddd0000000000000000000000000000000000000000000000000000",
        "Config": {
            "Image": "nginx:1.27-alpine",
            "Labels": {},
            "Env": ["NGINX_HOST=localhost"],
        },
        "State": {"Status": "running"},
        "HostConfig": {"Runtime": "runc"},
    },
    {
        "Id": "eeee3333ffff0000000000000000000000000000000000000000000000000000",
        "Config": {
            "Image": "kiro-runtime:dev",
            "Labels": {"maintainer": "external"},
            "Env": ["ANTHROPIC_API_KEY=xxx"],
        },
        "State": {"Status": "exited"},
        "HostConfig": {"Runtime": "runc"},
    },
])

TOP_OUTPUT = (
    "PID   COMMAND   COMMAND\n"
    "1234  python    python agent.py --loop\n"
    "1250  python    python -c worker\n"
)


def make_ssh(responses):
    """Build a mock ssh_execute returning scripted (ok, out, err) by command substring."""
    calls = []

    def ssh(server_ip, command, timeout=30):
        calls.append(command)
        for needle, resp in responses:
            if needle in command:
                return resp
        return (False, "", f"no mock for: {command}")

    ssh.calls = calls
    return ssh


def test_discovers_all_containers_including_external():
    ssh = make_ssh([
        ("docker ps", (True, PS_JSON_LINES, "")),
        ("docker inspect", (True, INSPECT_JSON, "")),
        ("docker top aaaa1111bbbb", (True, TOP_OUTPUT, "")),
    ])
    server = {"id": 1, "server_ip": "10.0.0.5"}
    obs, err = rc.collect_server_containers(server, ssh_execute=ssh)

    assert err is None
    assert len(obs) == 3, "all containers discovered, including the external one"
    names = {o["name"] for o in obs}
    assert names == {"coding-worker-01", "web-service-02", "task-runner-03"}

    managed = {o["name"]: o["is_platform_managed"] for o in obs}
    assert managed["coding-worker-01"] is True
    assert managed["web-service-02"] is False
    assert managed["task-runner-03"] is False  # externally launched

    print("ok test_discovers_all_containers_including_external")


def test_running_container_has_processes_exited_does_not():
    ssh = make_ssh([
        ("docker ps", (True, PS_JSON_LINES, "")),
        ("docker inspect", (True, INSPECT_JSON, "")),
        ("docker top aaaa1111bbbb", (True, TOP_OUTPUT, "")),
    ])
    server = {"id": 1, "server_ip": "10.0.0.5"}
    obs, _ = rc.collect_server_containers(server, ssh_execute=ssh)
    by_name = {o["name"]: o for o in obs}

    assert by_name["coding-worker-01"]["pids"] == 2
    assert by_name["coding-worker-01"]["processes"][0]["args"].startswith("python agent.py")
    # exited container: docker top never called, no processes
    assert by_name["task-runner-03"]["processes"] == []
    assert "docker top eeee3333ffff" not in " ".join(ssh.calls)

    print("ok test_running_container_has_processes_exited_does_not")


def test_inspect_env_and_runtime_merged():
    ssh = make_ssh([
        ("docker ps", (True, PS_JSON_LINES, "")),
        ("docker inspect", (True, INSPECT_JSON, "")),
        ("docker top aaaa1111bbbb", (True, TOP_OUTPUT, "")),
    ])
    server = {"id": 1, "server_ip": "10.0.0.5"}
    obs, _ = rc.collect_server_containers(server, ssh_execute=ssh)
    agent = next(o for o in obs if o["name"] == "coding-worker-01")
    assert agent["runtime"] == "runc"
    assert agent["env"].get("OPENAI_API_KEY") == "sk-xxx"
    assert agent["env"].get("ROLE") == "agent"
    print("ok test_inspect_env_and_runtime_merged")


def test_ssh_failure_returns_empty_with_error():
    ssh = make_ssh([("docker ps", (False, "", "ssh: connect to host timed out"))])
    server = {"id": 2, "server_ip": "10.0.0.9"}
    obs, err = rc.collect_server_containers(server, ssh_execute=ssh)
    assert obs == []
    assert err is not None and "timed out" in err
    print("ok test_ssh_failure_returns_empty_with_error")


def test_no_containers_returns_empty_no_error():
    ssh = make_ssh([("docker ps", (True, "", ""))])
    server = {"id": 3, "server_ip": "10.0.0.1"}
    obs, err = rc.collect_server_containers(server, ssh_execute=ssh)
    assert obs == []
    assert err is None
    print("ok test_no_containers_returns_empty_no_error")


def test_inspect_failure_still_returns_ps_basics():
    ssh = make_ssh([
        ("docker ps", (True, PS_JSON_LINES, "")),
        ("docker inspect", (False, "", "inspect boom")),
        ("docker top aaaa1111bbbb", (True, TOP_OUTPUT, "")),
    ])
    server = {"id": 1, "server_ip": "10.0.0.5"}
    obs, err = rc.collect_server_containers(server, ssh_execute=ssh)
    assert err is None
    assert len(obs) == 3
    # Falls back to ps image/state when inspect is unavailable.
    web = next(o for o in obs if o["name"] == "web-service-02")
    assert web["image"] == "nginx:1.27-alpine"
    assert web["labels"] == {}
    print("ok test_inspect_failure_still_returns_ps_basics")


def test_parse_top_output_caps_and_parses():
    procs = rc.parse_top_output(TOP_OUTPUT)
    assert len(procs) == 2
    assert procs[0] == {"pid": "1234", "comm": "python", "args": "python agent.py --loop"}
    print("ok test_parse_top_output_caps_and_parses")


def main():
    test_discovers_all_containers_including_external()
    test_running_container_has_processes_exited_does_not()
    test_inspect_env_and_runtime_merged()
    test_ssh_failure_returns_empty_with_error()
    test_no_containers_returns_empty_no_error()
    test_inspect_failure_still_returns_ps_basics()
    test_parse_top_output_caps_and_parses()
    print("\nAll collector tests passed.")


if __name__ == "__main__":
    main()
