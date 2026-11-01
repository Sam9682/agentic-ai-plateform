#!/usr/bin/env python3
"""Property test for ACP cancel force-close on ack timeout (Task 4.5).

Feature: phase2-aro-completion, Property 10: ACP cancel force-closes the
transport on ack timeout.

Validates: Requirements 2.6.

``_AcpExecutionHandle.cancel()`` writes ``session/cancel`` and waits up to
``cancel_ack_timeout`` for an acknowledgement. When the agent never acks (the
transport yields no terminal response for the prompt id), ``cancel()`` must:

* force-close the underlying transport (observable here via a ``closed`` flag on
  the mock transport), and
* return ``True`` to report that cancellation was initiated,
* within a bounded multiple of ``cancel_ack_timeout`` (no indefinite hang).

Run directly:
    python3 tests/test_aro_acp_cancel_force_close.py
Or via pytest:
    pytest tests/test_aro_acp_cancel_force_close.py
"""
import os
import sys
import time

from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.aro.adapters import acp_protocol as acp  # noqa: E402
from src.aro.adapters.base import ExecutionError  # noqa: E402
from src.aro.adapters.kiro_acp import AcpTransport, _AcpExecutionHandle  # noqa: E402


class NeverAcksTransport(AcpTransport):
    """Mock ACP transport that accepts writes but never acknowledges a cancel.

    ``read_chunks`` models an agent that goes silent: it blocks for the full
    read deadline and then raises ``ExecutionError`` (mirroring the real
    ``SubprocessAcpTransport`` deadline behavior) without ever yielding a
    terminal response for the prompt. ``close()`` records that the transport was
    force-closed so the property can observe the release.
    """

    def __init__(self):
        self.writes = []
        self.closed = False
        self.read_calls = 0

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    def read_chunks(self, read_timeout=None):
        self.read_calls += 1
        # Simulate a stalled agent: wait out the deadline, then surface the
        # typed timeout error exactly like the real transport does. No bytes are
        # ever yielded, so the cancel ack never arrives.
        if read_timeout:
            time.sleep(min(read_timeout, 0.05))
        raise ExecutionError("stalled: no data from agent")
        yield b""  # pragma: no cover - keeps this a generator

    def close(self) -> None:
        self.closed = True


@given(
    cancel_ack_timeout=st.floats(min_value=0.001, max_value=0.05),
    session_id=st.text(min_size=1, max_size=12),
    prompt_id=st.integers(min_value=1, max_value=10_000),
)
@settings(max_examples=150, deadline=None)
def test_acp_cancel_force_closes_on_ack_timeout(cancel_ack_timeout, session_id, prompt_id):
    """Feature: phase2-aro-completion, Property 10: ACP cancel force-closes the
    transport on ack timeout.

    Validates: Requirements 2.6.
    """
    transport = NeverAcksTransport()
    handle = _AcpExecutionHandle(
        transport,
        session_id,
        prompt_id,
        "do work",
        read_timeout=cancel_ack_timeout,
        cancel_ack_timeout=cancel_ack_timeout,
    )

    start = time.monotonic()
    returned = handle.cancel()
    elapsed = time.monotonic() - start

    # Req 2.6: cancellation was initiated (True) and the transport was
    # force-closed because the ack never arrived.
    assert returned is True
    assert transport.closed is True

    # The session/cancel notification was actually written before the wait.
    assert len(transport.writes) >= 1
    assert transport.writes[0] == acp.encode_message(
        acp.cancel_notification(session_id)
    )

    # Bounded time: cancel must not hang; it returns within a small multiple of
    # the configured ack timeout rather than blocking forever.
    assert elapsed <= cancel_ack_timeout + 2.0


def test_acp_cancel_force_close_example():
    """Concrete anchor: a silent agent triggers a force-close and True return."""
    transport = NeverAcksTransport()
    handle = _AcpExecutionHandle(
        transport, "sess-1", 7, "x",
        read_timeout=0.01, cancel_ack_timeout=0.01,
    )
    assert handle.cancel() is True
    assert transport.closed is True


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
