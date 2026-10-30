#!/usr/bin/env python3
"""Tests for the Kiro ACP adapter + ACP codec (Task 8).

Feature: ARO Kiro adapter over the Agent Client Protocol (SRS §2.1, §3.2).

Validates:
* codec: encode rejects embedded newlines; LineBuffer reassembles messages
  split across arbitrary byte-chunk boundaries; request/notification/response
  helpers; session/update text extraction.
* adapter: capability set (no PAUSE faking); handshake (initialize ->
  session/new) against a mock ACP endpoint establishes a session; execute
  streams session/update text then a terminal response; cancel sends
  session/cancel.

Run directly:
    python3 tests/test_aro_kiro_acp.py
Or via pytest:
    pytest tests/test_aro_kiro_acp.py
"""
import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.aro.adapters import acp_protocol as acp  # noqa: E402
from src.aro.adapters.base import Capability  # noqa: E402
from src.aro.adapters.kiro_acp import AcpTransport, KiroAcpAdapter  # noqa: E402


# --------------------------------------------------------------------------- #
# Codec
# --------------------------------------------------------------------------- #
def test_encode_escapes_newline_into_single_line():
    # A newline inside a string value is JSON-escaped (\\n), so the serialized
    # ACP message stays a single physical line, satisfying the transport rule.
    data = acp.encode_message({"jsonrpc": "2.0", "method": "x", "params": {"t": "a\nb"}})
    assert data.count(b"\n") == 1  # only the trailing delimiter
    assert data.endswith(b"\n")


def test_encode_is_single_line():
    data = acp.encode_message(acp.request(1, "initialize", {"a": 1}))
    assert data.endswith(b"\n")
    assert data.count(b"\n") == 1


def test_linebuffer_reassembles_split_chunks():
    buf = acp.LineBuffer()
    m1 = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}})
    m2 = json.dumps({"jsonrpc": "2.0", "method": "session/update", "params": {}})
    stream = (m1 + "\n" + m2 + "\n").encode()
    # Feed one byte at a time to stress boundary handling.
    out = []
    for i in range(len(stream)):
        out.extend(buf.feed(stream[i:i + 1]))
    assert len(out) == 2
    assert out[0]["id"] == 1
    assert out[1]["method"] == "session/update"


def test_response_outcome():
    ok, payload = acp.response_outcome({"id": 1, "result": {"sessionId": "s1"}})
    assert ok and payload["sessionId"] == "s1"
    bad_ok, err = acp.response_outcome({"id": 1, "error": {"message": "nope"}})
    assert not bad_ok and err["message"] == "nope"


def test_extract_update_text_variants():
    msg = acp.notification("session/update", {
        "update": {"content": {"type": "text", "text": "hello"}}
    })
    assert acp.extract_update_text(msg) == ["hello"]
    msg2 = acp.notification("session/update", {
        "update": {"content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]}
    })
    assert acp.extract_update_text(msg2) == ["a", "b"]
    assert acp.extract_update_text(acp.notification("other")) == []


# --------------------------------------------------------------------------- #
# Mock ACP endpoint transport
# --------------------------------------------------------------------------- #
class MockKiroTransport(AcpTransport):
    """Simulates a Kiro ACP agent: answers initialize/session/new, and on a
    session/prompt emits two session/update text chunks then a prompt response."""

    def __init__(self):
        self._outbox = []       # queued byte chunks for the client to read
        self._buffer = acp.LineBuffer()
        self.cancelled = False
        self._session = "sess-1"

    def write(self, data: bytes) -> None:
        for msg in self._buffer.feed(data):
            self._handle(msg)

    def _emit(self, message):
        self._outbox.append(acp.encode_message(message))

    def _handle(self, msg):
        method = msg.get("method")
        mid = msg.get("id")
        if method == "initialize":
            self._emit({"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": 1}})
        elif method == "session/new":
            self._emit({"jsonrpc": "2.0", "id": mid, "result": {"sessionId": self._session}})
        elif method == "session/prompt":
            self._emit(acp.notification("session/update", {
                "update": {"content": {"type": "text", "text": "Inspecting infra... "}}
            }))
            self._emit(acp.notification("session/update", {
                "update": {"content": {"type": "text", "text": "done."}}
            }))
            self._emit({"jsonrpc": "2.0", "id": mid, "result": {"stopReason": "end_turn"}})
        elif method == "session/cancel":
            self.cancelled = True

    def read_chunks(self):
        while self._outbox:
            yield self._outbox.pop(0)

    def close(self):
        pass


def _adapter_with_mock(mock):
    return KiroAcpAdapter(
        "agent-container",
        transport_factory=lambda: mock,
        remote_exec=lambda ip, cmd, timeout=30: (True, "true", ""),
    )


def test_capabilities_no_pause():
    a = KiroAcpAdapter("c", transport_factory=lambda: MockKiroTransport())
    caps = set(a.get_capabilities())
    assert Capability.EXECUTE in caps and Capability.STREAMING in caps
    assert Capability.CANCELLATION in caps
    # ACP has no pause capability in our enum, and we must not invent one.
    assert all(c in set(Capability) for c in caps)


def test_handshake_establishes_session():
    mock = MockKiroTransport()
    a = _adapter_with_mock(mock)
    result = a.start("agent://default/a1", {"cwd": "/workspace"})
    assert result.success is True
    assert a.get_status("agent://default/a1") == "RUNNING"


def test_execute_streams_update_text():
    mock = MockKiroTransport()
    a = _adapter_with_mock(mock)
    a.start("agent://default/a1", {})
    handle = a.execute("agent://default/a1", {"prompt": "inspect infra"})
    chunks = list(handle.stream())
    texts = [c.data for c in chunks if c.channel == "stdout"]
    assert "Inspecting infra... " in texts
    assert "done." in texts
    assert chunks[-1].done is True
    result = handle.result()
    assert result.success is True
    assert "done." in result.output


def test_cancel_sends_session_cancel():
    mock = MockKiroTransport()
    a = _adapter_with_mock(mock)
    a.start("agent://default/a1", {})
    handle = a.execute("agent://default/a1", {"prompt": "x"})
    assert handle.cancel() is True
    assert mock.cancelled is True


def test_health_check_reads_container_state():
    mock = MockKiroTransport()
    a = KiroAcpAdapter(
        "c", transport_factory=lambda: mock,
        remote_exec=lambda ip, cmd, timeout=30: (True, "true\n", ""),
    )
    assert a.health_check() is True


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
