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

from hypothesis import given, settings
from hypothesis import strategies as st

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


# --------------------------------------------------------------------------- #
# SHAI CLI install integrity (Property 11)
# --------------------------------------------------------------------------- #
# A 64-char lowercase hex sha256 digest.
_sha256_digest = st.text(alphabet="0123456789abcdef", min_size=64, max_size=64)


class _RecordingExec:
    """Injected remote_exec that records commands and fakes pack/install output.

    The pack command (``npm pack`` + ``sha256sum``) returns the *actual* digest
    in ``sha256sum`` form; the activating ``npm install`` command (if ever
    issued) is recorded and reported as succeeding. Recording lets the property
    assert that a mismatched install never issues the activating command.
    """

    def __init__(self, actual_digest):
        self._actual = actual_digest
        self.commands = []

    def __call__(self, ip, command, timeout=120):
        self.commands.append(command)
        if "npm pack" in command:
            # `sha256sum <path>` form: "<digest>  <path>".
            return True, f"{self._actual}  /tmp/shai-x.tgz", ""
        if "npm install" in command:
            return True, "installed", ""
        return True, "", ""

    @property
    def install_commands(self):
        return [c for c in self.commands if "npm install" in c]


@settings(max_examples=100, deadline=None)
@given(expected=_sha256_digest, actual=_sha256_digest)
def test_cli_install_integrity_verification(expected, actual):
    """Feature: phase2-aro-completion, Property 11

    install() with a configured sha256 downloads the artifact (npm pack),
    computes its sha256 (via remote sha256sum) and activates the runtime iff
    the computed digest matches the expected one. On mismatch it returns a
    FAILED ExecutionResult and never issues the activating ``npm install``
    command. Validates: Requirements 2.9.
    """
    rec = _RecordingExec(actual)
    adapter = shai_cli.ShaiCliAdapter("c1", remote_exec=rec)

    result = adapter.install({"version": "0.2.2", "sha256": expected})

    matches = expected == actual
    # success iff the computed digest matches the configured one.
    assert result.success is matches
    if matches:
        # On a match the verified tarball is installed (activating command run).
        assert rec.install_commands, "expected activating npm install on match"
    else:
        # On mismatch the runtime is never activated.
        assert result.success is False
        assert rec.install_commands == [], "install must not activate on mismatch"


@settings(max_examples=100, deadline=None)
@given(expected=_sha256_digest)
def test_cli_install_integrity_accepts_sha256_prefix(expected):
    """Feature: phase2-aro-completion, Property 11

    A configured digest carrying a ``sha256:`` prefix verifies against the bare
    hex emitted by sha256sum, and a correct match activates the runtime.
    Validates: Requirements 2.9.
    """
    rec = _RecordingExec(expected)
    adapter = shai_cli.ShaiCliAdapter("c1", remote_exec=rec)

    result = adapter.install({"version": "0.2.2", "digest": f"sha256:{expected}"})

    assert result.success is True
    assert rec.install_commands, "matching prefixed digest must activate runtime"


# --------------------------------------------------------------------------- #
# SHAI HTTP/SSE configurable terminal event recognition (Property 13)
# --------------------------------------------------------------------------- #
from src.aro.adapters.shai_http_sse import (  # noqa: E402
    DEFAULT_ERROR_EVENTS,
    DEFAULT_TERMINAL_EVENTS,
    _SSEExecutionHandle,
)

# SSE event-name token: non-empty, no newline/colon so it survives the SSE
# `event: <name>` grammar and round-trips as a single field value.
_event_name = st.text(
    alphabet=st.characters(
        min_codepoint=33,
        max_codepoint=126,
        blacklist_characters=":",
    ),
    min_size=1,
    max_size=24,
)


def _sse_chunks_for(event_name, data_lines):
    """Build an SSE response body (list of text chunks) that emits a few data
    events followed by a single terminal/error event named ``event_name``."""
    chunks = [f"data: {d}\n\n" for d in data_lines]
    chunks.append(f"event: {event_name}\ndata: boom\n\n")
    return chunks


@settings(max_examples=100, deadline=None)
@given(
    terminal_events=st.sets(_event_name, min_size=1, max_size=6),
    picked_index=st.integers(min_value=0, max_value=5),
    data_lines=st.lists(st.text(alphabet="abc", min_size=0, max_size=4), max_size=4),
)
def test_sse_recognizes_any_configured_terminal_event(terminal_events, picked_index, data_lines):
    """Feature: phase2-aro-completion, Property 13

    For any configured ``terminal_events`` set and any event name drawn from it,
    a stream containing that event marks the handle done: the final
    ExecutionChunk has ``done=True`` and the terminal ExecutionResult reports
    success. Preceding data events stream as stdout before the terminal.
    Validates: Requirements 2.10.
    """
    names = sorted(terminal_events)
    event_name = names[picked_index % len(names)]
    # The drawn terminal name must never also be an error name (disjoint sets).
    error_events = frozenset(DEFAULT_ERROR_EVENTS) - frozenset(terminal_events)

    handle = _SSEExecutionHandle(
        iter(_sse_chunks_for(event_name, data_lines)),
        cancel_fn=None,
        terminal_events=frozenset(terminal_events),
        error_events=error_events,
    )
    chunks = list(handle.stream())

    assert chunks, "a terminal event must produce at least one chunk"
    assert chunks[-1].done is True
    # Exactly one chunk is terminal and it is the last one.
    assert [c.done for c in chunks].count(True) == 1
    # Data events before the terminal are streamed as stdout in order.
    streamed = [c.data for c in chunks if c.channel == "stdout"]
    assert streamed == [d for d in data_lines if d]
    result = handle.result()
    assert result.success is True
    assert result.returncode == 0


@settings(max_examples=100, deadline=None)
@given(
    error_events=st.sets(_event_name, min_size=1, max_size=6),
    picked_index=st.integers(min_value=0, max_value=5),
    data_lines=st.lists(st.text(alphabet="abc", min_size=0, max_size=4), max_size=4),
)
def test_sse_recognizes_any_configured_error_event(error_events, picked_index, data_lines):
    """Feature: phase2-aro-completion, Property 13

    For any configured ``error_events`` set and any event name drawn from it, a
    stream containing that event produces a failed terminal: the final
    ExecutionChunk has ``done=True`` on the ``stderr`` channel and the terminal
    ExecutionResult reports failure. Validates: Requirements 2.10.
    """
    names = sorted(error_events)
    event_name = names[picked_index % len(names)]
    # The drawn error name must never also be a terminal name (disjoint sets).
    terminal_events = frozenset(DEFAULT_TERMINAL_EVENTS) - frozenset(error_events)

    handle = _SSEExecutionHandle(
        iter(_sse_chunks_for(event_name, data_lines)),
        cancel_fn=None,
        terminal_events=terminal_events,
        error_events=frozenset(error_events),
    )
    chunks = list(handle.stream())

    assert chunks, "an error event must produce at least one chunk"
    assert chunks[-1].done is True
    assert chunks[-1].channel == "stderr"
    assert [c.done for c in chunks].count(True) == 1
    result = handle.result()
    assert result.success is False
    assert result.returncode == 1


@settings(max_examples=100, deadline=None)
@given(
    terminal_events=st.sets(_event_name, min_size=1, max_size=6),
    picked_index=st.integers(min_value=0, max_value=5),
)
def test_adapter_passes_configured_terminal_events_through_execute(terminal_events, picked_index):
    """Feature: phase2-aro-completion, Property 13

    The configured terminal-event set wired into ``ShaiHttpSseAdapter`` is
    honored end-to-end: a task whose stream ends on any configured terminal
    name completes the handle produced by ``execute()``. Validates:
    Requirements 2.10.
    """
    names = sorted(terminal_events)
    event_name = names[picked_index % len(names)]
    error_events = frozenset(DEFAULT_ERROR_EVENTS) - frozenset(terminal_events)

    http = FakeHttp(_sse_chunks_for(event_name, ["one", "two"]))
    adapter = ShaiHttpSseAdapter(
        "http://shai:8080",
        http,
        terminal_events=frozenset(terminal_events),
        error_events=error_events,
    )
    adapter.start("agent://default/a1", {})
    handle = adapter.execute("agent://default/a1", {"prompt": "x"})
    chunks = list(handle.stream())

    assert chunks[-1].done is True
    assert [c.data for c in chunks if c.channel == "stdout"] == ["one", "two"]
    assert handle.result().success is True


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))

# --------------------------------------------------------------------------- #
# SHAI CLI result()/cancel() behavior (Task 4.8)
#
# Validates: Requirements 2.7, 2.8
#   2.7 result() blocks until the underlying execution has finished before
#       returning the ExecutionResult.
#   2.8 cancel() stops the in-container child processes it spawned (the
#       container-side `docker exec <c> pkill -TERM -f shai`, with a
#       `docker stop <c>` fallback when pkill reports nothing to signal).
# --------------------------------------------------------------------------- #
class WaitRecordingPopen:
    """Fake Popen whose returncode only becomes readable after wait().

    Models a still-running process: ``poll()`` returns None until ``wait()``
    has been called, after which both ``wait()`` and ``poll()`` report the
    finished return code. Records that ``wait()`` was observed and the order
    relative to the first ``poll()`` that saw a finished code.
    """

    def __init__(self, returncode=0):
        import io
        self.stdout = io.StringIO("")
        self._rc = returncode
        self.wait_called = False
        self.wait_timeout_arg = "unset"
        self._terminated = False

    def poll(self):
        # Premature reads (before wait finished) must not expose the code.
        return self._rc if self.wait_called else None

    def wait(self, timeout=None):
        self.wait_called = True
        self.wait_timeout_arg = timeout
        return self._rc

    def terminate(self):
        self._terminated = True


def test_result_waits_before_reading_returncode():
    # result() must call wait() before it reads returncode via poll().
    proc = WaitRecordingPopen(returncode=0)
    handle = shai_cli._ProcessHandle(proc)
    # Before result(), the process looks unfinished (poll() -> None).
    assert proc.poll() is None
    assert proc.wait_called is False

    res = handle.result()

    # result() blocked on wait() first, so the returncode is now the finished
    # value rather than a premature None.
    assert proc.wait_called is True
    assert res.returncode == 0
    assert res.success is True


def test_result_passes_timeout_to_wait():
    proc = WaitRecordingPopen(returncode=0)
    handle = shai_cli._ProcessHandle(proc)
    handle.result(timeout=5.0)
    assert proc.wait_timeout_arg == 5.0


def test_result_reports_nonzero_exit_as_failure():
    proc = WaitRecordingPopen(returncode=3)
    handle = shai_cli._ProcessHandle(proc)
    res = handle.result()
    assert proc.wait_called is True
    assert res.returncode == 3
    assert res.success is False


def test_cancel_issues_container_child_kill_command():
    # cancel() must issue the container-side child kill through remote_exec.
    calls = []

    def fake_remote_exec(ip, cmd, timeout=30):
        calls.append(cmd)
        return True, "", ""  # pkill succeeds -> no fallback

    a = shai_cli.ShaiCliAdapter(
        "c1",
        popen=lambda argv: WaitRecordingPopen(),
        remote_exec=fake_remote_exec,
    )
    a.start("agent://default/a1", {})
    handle = a.execute("agent://default/a1", {"prompt": "hi"})

    assert handle.cancel() is True

    # The container-child kill command was issued (quoted container ref).
    assert any("pkill -TERM -f shai" in c for c in calls)
    assert any(c == "docker exec c1 pkill -TERM -f shai" for c in calls)
    # pkill succeeded, so no docker stop fallback was issued.
    assert not any("docker stop" in c for c in calls)


def test_cancel_falls_back_to_docker_stop_when_pkill_nonzero():
    # When the container-side pkill reports nothing to signal (non-zero),
    # cancel() falls back to `docker stop <c>`.
    calls = []

    def fake_remote_exec(ip, cmd, timeout=30):
        calls.append(cmd)
        if "pkill" in cmd:
            return False, "", "no process found"  # nothing to signal
        return True, "", ""

    a = shai_cli.ShaiCliAdapter(
        "c1",
        popen=lambda argv: WaitRecordingPopen(),
        remote_exec=fake_remote_exec,
    )
    a.start("agent://default/a1", {})
    handle = a.execute("agent://default/a1", {"prompt": "hi"})

    assert handle.cancel() is True
    assert any(c == "docker exec c1 pkill -TERM -f shai" for c in calls)
    assert any(c == "docker stop c1" for c in calls)
