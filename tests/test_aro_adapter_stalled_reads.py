#!/usr/bin/env python3
"""Property test for stalled MCP/ACP adapter reads (Task 4.3).

Feature: phase2-aro-completion, Property 9: Stalled adapter reads raise a typed
error within the deadline.

Validates: Requirements 2.4, 2.5, 2.11.

Both the generic MCP adapter (``src/aro/adapters/mcp_adapter.py``) and the Kiro
ACP adapter (``src/aro/adapters/kiro_acp.py``) bound every read of the agent
stream by a configured read timeout. When the agent never produces data, the
read MUST raise a typed :class:`ExecutionError` rather than blocking forever,
and it MUST do so within a bounded window of the configured deadline.

This test injects a *stalled* transport whose ``read_chunks`` never yields data
but honours the deadline (it blocks until the deadline, then raises the typed
error exactly as the real subprocess transports do). For a range of small
configured ``read_timeout`` values it asserts, for both adapters, that driving
the execution stream raises :class:`ExecutionError` and that the raise happens
within a bounded slack of the configured timeout.

Run directly:
    python3 tests/test_aro_adapter_stalled_reads.py
Or via pytest:
    pytest tests/test_aro_adapter_stalled_reads.py
"""
import os
import sys
import time
from typing import Iterator, Optional

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.aro.adapters.base import ExecutionError  # noqa: E402
from src.aro.adapters.kiro_acp import AcpTransport, KiroAcpAdapter  # noqa: E402
from src.aro.adapters.mcp_adapter import McpAdapter, McpTransport  # noqa: E402


# --------------------------------------------------------------------------- #
# Stalled transports: never yield data, but honour the configured deadline and
# then raise the typed ExecutionError — mirroring the real subprocess transports
# (which surface a read-timeout as ExecutionError once select() reports no data).
# --------------------------------------------------------------------------- #
# A hard safety cap so a bug in the deadline handling can never hang the suite:
# every stalled read is additionally bounded by this wall-clock ceiling.
_SAFETY_CEILING = 1.0


class _StalledMcpTransport(McpTransport):
    """MCP transport whose reads never produce data.

    ``read_chunks`` receives a *monotonic deadline* (as the subprocess transport
    does). It waits until that deadline, then raises :class:`ExecutionError`,
    exactly like ``SubprocessMcpTransport`` when ``select`` reports no data.
    """

    def __init__(self) -> None:
        self.writes = 0

    def write(self, data: bytes) -> None:
        self.writes += 1

    def read_chunks(self, deadline: Optional[float] = None) -> Iterator[bytes]:
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(remaining, _SAFETY_CEILING))
        raise ExecutionError("mcp read timeout")
        yield b""  # pragma: no cover - makes this a generator

    def close(self) -> None:
        pass


class _StalledAcpTransport(AcpTransport):
    """ACP transport whose reads never produce data.

    ``read_chunks`` receives a *timeout duration* (as the subprocess transport
    does). It blocks for that duration, then raises :class:`ExecutionError`,
    exactly like ``SubprocessAcpTransport`` when ``select`` reports no data.
    """

    def __init__(self) -> None:
        self.writes = 0

    def write(self, data: bytes) -> None:
        self.writes += 1

    def read_chunks(self, read_timeout: Optional[float] = None) -> Iterator[bytes]:
        if read_timeout is not None:
            time.sleep(min(read_timeout, _SAFETY_CEILING))
        raise ExecutionError(
            f"ACP read timed out after {read_timeout}s with no data from agent"
        )
        yield b""  # pragma: no cover - makes this a generator

    def close(self) -> None:
        pass


# Configured read timeouts kept small so the suite stays fast while still
# exercising a real wall-clock deadline (0.01s - 0.2s).
_read_timeouts = st.floats(min_value=0.01, max_value=0.2)

# Generous slack over the configured timeout to absorb scheduler jitter on a
# loaded CI box, while still proving the read is *bounded* (does not hang).
_SLACK = 0.75


# --------------------------------------------------------------------------- #
# Property 9: Stalled MCP adapter reads raise a typed error within the deadline
# --------------------------------------------------------------------------- #
@given(read_timeout=_read_timeouts)
@settings(max_examples=100, deadline=None)
def test_property_mcp_stalled_read_raises_within_deadline(read_timeout):
    """Feature: phase2-aro-completion, Property 9: Stalled adapter reads raise a
    typed error within the deadline.

    Validates: Requirements 2.4, 2.11.

    For any small configured ``read_timeout``, an MCP execution against a
    transport that never yields data raises :class:`ExecutionError` (not a raw
    exception, not a hang) within a bounded window of the deadline.
    """
    transport = _StalledMcpTransport()
    adapter = McpAdapter(
        "agent-container",
        server_cmd=["mcp-server"],
        read_timeout=read_timeout,
        transport_factory=lambda: transport,
    )
    # Put the adapter in the started state without any real handshake I/O, then
    # drive the streaming read path which must surface the stall as a typed error.
    adapter._transport = transport
    adapter._status = "RUNNING"

    handle = adapter.execute("agent-1", {"tool": "echo", "arguments": {}})

    start = time.monotonic()
    with pytest.raises(ExecutionError):
        list(handle.stream())
    elapsed = time.monotonic() - start

    # Bounded: the error arrives within the configured timeout plus slack, never
    # hanging past it.
    assert elapsed <= read_timeout + _SLACK


# --------------------------------------------------------------------------- #
# Property 9: Stalled ACP adapter reads raise a typed error within the deadline
# --------------------------------------------------------------------------- #
@given(read_timeout=_read_timeouts)
@settings(max_examples=100, deadline=None)
def test_property_acp_stalled_read_raises_within_deadline(read_timeout):
    """Feature: phase2-aro-completion, Property 9: Stalled adapter reads raise a
    typed error within the deadline.

    Validates: Requirements 2.5, 2.11.

    For any small configured ``read_timeout``, a Kiro ACP execution against a
    transport that never yields data raises :class:`ExecutionError` (not a raw
    exception, not a hang) within a bounded window of the deadline.
    """
    transport = _StalledAcpTransport()
    adapter = KiroAcpAdapter(
        "agent-container",
        read_timeout=read_timeout,
        transport_factory=lambda: transport,
    )
    # Place the adapter in the started state without a real handshake, then drive
    # the prompt stream which reads from the stalled transport.
    adapter._transport = transport
    adapter._session_id = "session-1"
    adapter._status = "RUNNING"

    handle = adapter.execute("agent-1", {"prompt": "hello"})

    start = time.monotonic()
    with pytest.raises(ExecutionError):
        list(handle.stream())
    elapsed = time.monotonic() - start

    assert elapsed <= read_timeout + _SLACK


if __name__ == "__main__":
    test_property_mcp_stalled_read_raises_within_deadline()
    test_property_acp_stalled_read_raises_within_deadline()
    print("OK")
