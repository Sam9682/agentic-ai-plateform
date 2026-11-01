#!/usr/bin/env python3
"""Property test for MCP JSON-RPC framing round-trip (Task 2.2).

Feature: phase2-aro-completion, Property 12: MCP protocol framing round-trips.

Validates: Requirements 2.2, 2.11.

The module under test is :mod:`src.aro.adapters.mcp_protocol`. MCP stdio
transport frames each JSON-RPC message as a single newline-delimited line.
This test asserts that for any JSON-RPC message containing no embedded newline,
encoding it with ``encode_message`` and then feeding the encoded bytes through
``LineBuffer.feed`` split at arbitrary chunk boundaries reproduces the original
message.

Run directly:
    python3 tests/test_aro_mcp_protocol.py
Or via pytest:
    pytest tests/test_aro_mcp_protocol.py
"""
import os
import sys

from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.aro.adapters import mcp_protocol as mcp  # noqa: E402


# --------------------------------------------------------------------------- #
# JSON-RPC message strategy
# --------------------------------------------------------------------------- #
# JSON scalar/structured values that survive a json round-trip. Text is drawn
# from the full unicode range but with newline characters excluded so the
# message is a legal single-line MCP frame (the transport forbids embedded
# newlines). dict keys are likewise newline-free strings.
# The surrogate category ("Cs") is excluded: a lone surrogate round-trips
# through json.dumps(..., ensure_ascii=False) but is not UTF-8 encodable, so it
# falls outside the encodable domain for which the round-trip property holds.
_no_newline_text = st.text(
    alphabet=st.characters(blacklist_characters="\n\r", blacklist_categories=("Cs",)),
    max_size=40,
)

_json_values = st.recursive(
    st.one_of(
        st.none(),
        st.booleans(),
        st.integers(min_value=-(10 ** 12), max_value=10 ** 12),
        st.floats(allow_nan=False, allow_infinity=False, width=32),
        _no_newline_text,
    ),
    lambda children: st.one_of(
        st.lists(children, max_size=4),
        st.dictionaries(_no_newline_text, children, max_size=4),
    ),
    max_leaves=10,
)


@st.composite
def _jsonrpc_messages(draw):
    """Generate representative JSON-RPC messages (requests, notifications,
    responses) plus arbitrary-but-newline-free payloads."""
    kind = draw(st.sampled_from(["request", "notification", "response", "arbitrary"]))
    if kind == "request":
        msg = mcp.request(
            draw(st.integers(min_value=0, max_value=10 ** 9)),
            draw(_no_newline_text.filter(lambda s: s != "")),
            draw(st.one_of(st.none(), st.dictionaries(_no_newline_text, _json_values, max_size=4))),
        )
    elif kind == "notification":
        msg = mcp.notification(
            draw(_no_newline_text.filter(lambda s: s != "")),
            draw(st.one_of(st.none(), st.dictionaries(_no_newline_text, _json_values, max_size=4))),
        )
    elif kind == "response":
        msg = {"jsonrpc": mcp.JSONRPC_VERSION, "id": draw(st.integers(0, 10 ** 9))}
        if draw(st.booleans()):
            msg["result"] = draw(_json_values)
        else:
            msg["error"] = {"code": draw(st.integers(-32768, 32767)), "message": draw(_no_newline_text)}
    else:
        msg = draw(st.dictionaries(_no_newline_text, _json_values, max_size=5))
    return msg


def _split_at_boundaries(data, boundaries):
    """Split ``data`` (bytes) into chunks at the sorted unique ``boundaries``."""
    cuts = sorted({b for b in boundaries if 0 < b < len(data)})
    chunks = []
    prev = 0
    for c in cuts:
        chunks.append(data[prev:c])
        prev = c
    chunks.append(data[prev:])
    return chunks or [data]


# --------------------------------------------------------------------------- #
# Property 12: MCP protocol framing round-trips
# --------------------------------------------------------------------------- #
@given(
    messages=st.lists(_jsonrpc_messages(), min_size=1, max_size=5),
    boundaries=st.lists(st.integers(min_value=0, max_value=4096), max_size=12),
)
@settings(max_examples=200)
def test_property_mcp_framing_round_trips(messages, boundaries):
    """Feature: phase2-aro-completion, Property 12: MCP protocol framing
    round-trips.

    Validates: Requirements 2.2, 2.11.

    For any batch of JSON-RPC messages with no embedded newline, decoding the
    newline-delimited encoding, split across arbitrary chunk boundaries,
    reproduces the original messages in order.
    """
    # Encode all messages into one newline-delimited byte stream. encode_message
    # must never raise here because the generators exclude embedded newlines.
    encoded = b"".join(mcp.encode_message(m) for m in messages)

    buf = mcp.LineBuffer()
    decoded = []
    for chunk in _split_at_boundaries(encoded, boundaries):
        decoded.extend(buf.feed(chunk))

    # Every complete frame is consumed (the stream is newline-terminated) and
    # the decoded sequence reproduces the originals in order.
    assert buf.pending == b""
    assert decoded == messages


# --------------------------------------------------------------------------- #
# Explicit example: non-UTF-8-encodable payload is a typed ProtocolError
# --------------------------------------------------------------------------- #
def test_encode_message_lone_surrogate_raises_protocol_error():
    """A lone surrogate is not UTF-8 encodable; ``encode_message`` must raise a
    typed ``ProtocolError`` rather than leaking a raw ``UnicodeEncodeError``
    (Requirement 2.11)."""
    import pytest

    with pytest.raises(mcp.ProtocolError):
        mcp.encode_message({"jsonrpc": "2.0", "method": "\ud800"})


if __name__ == "__main__":
    test_property_mcp_framing_round_trips()
    print("OK")
