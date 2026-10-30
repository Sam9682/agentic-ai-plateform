#!/usr/bin/env python3
"""Tests for the SHAI CLI + HTTP/SSE adapters (Task 9).

Feature: ARO SHAI adapters (SRS §2.1, §3.2); ACP/CLI/HTTP-SSE are distinct.

Validates:
* SSE parser: reassembles events across chunk boundaries; joins multi-line
  data; ignores comments; dispatches on blank line.
* CLI adapter: argv assembly passes the prompt as a single arg; streams stdout
  lines via a fake Popen; cancel terminates.
* HTTP/SSE adapter: streams SSE 'message' events then stops on 'done'; health
  via GET; capability matrix differs from CLI (no INSTALL/LOGS; CANCELLATION
  only when the deployment advertises it).

Run directly:
    python3 tests/test_aro_shai_adapters.py
Or via pytest:
    pytest tests/test_aro_shai_adapters.py
"""
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.aro.adapters.base import Capability, CapabilityError  # noqa: E402
from src.aro.adapters.sse_parser import SSEParser  # noqa: E402
from src.aro.adapters import shai_cli  # noqa: E402
from src.aro.adapters.shai_http_sse import HttpClient, ShaiHttpSseAdapter  # noqa: E402


# --------------------------------------------------------------------------- #
# SSE parser
# --------------------------------------------------------------------------- #
def test_sse_single_event():
    p = SSEParser()
    events = list(p.feed("data: hello\n\n"))
    assert len(events) == 1
    assert events[0].data == "hello"


def test_sse_multiline_data_joined():
    p = SSEParser()
    events = list(p.feed("data: a\ndata: b\n\n"))
    assert events[0].data == "a\nb"


def test_sse_event_type_and_comment_ignored():
    p = SSEParser()
    out = list(p.feed(": keep-alive\nevent: done\ndata: x\n\n"))
    assert out[0].event == "done"
    assert out[0].data == "x"


def test_sse_split_across_chunks():
    p = SSEParser()
    collected = []
    for ch in ["data: hel", "lo\n", "\n", "event: done\n", "data: y\n\n"]:
        collected.extend(p.feed(ch))
    assert collected[0].data == "hello"
    assert collected[1].event == "done"


# --------------------------------------------------------------------------- #
# SHAI CLI adapter
# --------------------------------------------------------------------------- #
def test_cli_argv_passes_prompt_as_single_arg():
    argv = shai_cli.build_cli_argv("c1", "inspect; rm -rf /", agent_config="infra")
    assert argv[:5] == ["docker", "exec", "-i", "c1", "shai"]
    assert "--prompt" in argv
    # The dangerous string is a single argv element, not shell-interpolated.
    assert argv[argv.index("--prompt") + 1] == "inspect; rm -rf /"


class FakePopen:
    """Fake subprocess.Popen streaming canned stdout lines."""

    def __init__(self, lines, returncode=0):
        import io
        self.stdout = io.StringIO("".join(l + "\n" for l in lines))
        self._rc = returncode
        self._terminated = False

    def poll(self):
        return self._rc

    def wait(self):
        return self._rc

    def terminate(self):
        self._terminated = True


def test_cli_streams_stdout(monkeypatch):
    a = shai_cli.ShaiCliAdapter(
        "c1",
        popen=lambda argv: FakePopen(["line one", "line two"]),
        remote_exec=lambda ip, cmd, timeout=30: (True, "true", ""),
    )
    a.start("agent://default/a1", {})
    handle = a.execute("agent://default/a1", {"prompt": "hi"})
    chunks = list(handle.stream())
    texts = [c.data for c in chunks if c.channel == "stdout"]
    assert texts == ["line one", "line two"]
    assert chunks[-1].done is True
    assert handle.result().success is True


def test_cli_cancel_terminates(monkeypatch):
    fake = FakePopen(["x"])
    fake.poll = lambda: None  # model a still-running process
    a = shai_cli.ShaiCliAdapter("c1", popen=lambda argv: fake,
                                remote_exec=lambda ip, cmd, timeout=30: (True, "true", ""))
    a.start("agent://default/a1", {})
    handle = a.execute("agent://default/a1", {"prompt": "hi"})
    assert handle.cancel() is True
    assert fake._terminated is True


def test_cli_full_capability_set():
    a = shai_cli.ShaiCliAdapter("c1")
    caps = set(a.get_capabilities())
    assert Capability.INSTALL in caps
    assert Capability.LOGS in caps
    assert Capability.CANCELLATION in caps


# --------------------------------------------------------------------------- #
# SHAI HTTP/SSE adapter
# --------------------------------------------------------------------------- #
class FakeHttp(HttpClient):
    def __init__(self, sse_chunks, health_status=200):
        self._sse = sse_chunks
        self._health = health_status
        self.cancelled = False

    def stream_post(self, url, json_body, headers):
        for ch in self._sse:
            yield ch

    def get(self, url, headers):
        return self._health, "ok"

    def post(self, url, json_body, headers):
        self.cancelled = True
        return 200, "cancelled"


def test_http_streams_until_done():
    http = FakeHttp(["data: hello\n\n", "data: world\n\n", "event: done\ndata: \n\n"])
    a = ShaiHttpSseAdapter("http://shai:8080", http)
    a.start("agent://default/a1", {})
    handle = a.execute("agent://default/a1", {"prompt": "x"})
    chunks = list(handle.stream())
    texts = [c.data for c in chunks if c.channel == "stdout"]
    assert texts == ["hello", "world"]
    assert chunks[-1].done is True
    assert handle.result().success is True


def test_http_health_via_get():
    a = ShaiHttpSseAdapter("http://shai:8080", FakeHttp([], health_status=200))
    assert a.health_check() is True
    b = ShaiHttpSseAdapter("http://shai:8080", FakeHttp([], health_status=503))
    assert b.health_check() is False


def test_http_capability_matrix_differs_from_cli():
    a = ShaiHttpSseAdapter("http://shai:8080", FakeHttp([]))
    caps = set(a.get_capabilities())
    # No INSTALL/LOGS over HTTP; and no CANCELLATION unless advertised.
    assert Capability.INSTALL not in caps
    assert Capability.LOGS not in caps
    assert Capability.CANCELLATION not in caps
    # Unsupported operations raise rather than fake success.
    try:
        a.install({})
        assert False
    except CapabilityError:
        pass


def test_http_cancel_only_when_advertised():
    http = FakeHttp(["data: a\n\n"])
    a = ShaiHttpSseAdapter("http://shai:8080", http, supports_cancel=True)
    assert Capability.CANCELLATION in set(a.get_capabilities())
    a.start("agent://default/a1", {})
    handle = a.execute("agent://default/a1", {"prompt": "x"})
    assert handle.cancel() is True
    assert http.cancelled is True


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
