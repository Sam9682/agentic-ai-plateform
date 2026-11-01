"""Pure Model Context Protocol (MCP) codec (Task 2.1).

This is the MCP twin of :mod:`acp_protocol`. MCP is JSON-RPC 2.0; for the
in-container stdio transport we target it is carried as **newline-delimited**
JSON (one message per line, no embedded newlines), mirroring the ACP framing so
the adapter's transport can be exercised deterministically without spawning a
process. This module holds the pure, side-effect-free framing + message helpers
(no subprocess, no SSH).

References (rephrased for licensing compliance):
* MCP is JSON-RPC 2.0; stdio transport frames each message as one line of JSON
  (https://modelcontextprotocol.io/specification).
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterator, List, Optional, Tuple

JSONRPC_VERSION = "2.0"


class ProtocolError(Exception):
    """Raised when a message cannot be framed/parsed per the MCP transport."""


def encode_message(message: Dict[str, Any]) -> bytes:
    """Serialize a JSON-RPC message to a single newline-terminated line.

    Raises :class:`ProtocolError` if the serialized form would contain an
    embedded newline (the transport forbids it).
    """
    line = json.dumps(message, separators=(",", ":"), ensure_ascii=False)
    if "\n" in line:
        raise ProtocolError("MCP message must not contain embedded newlines")
    try:
        return (line + "\n").encode("utf-8")
    except UnicodeEncodeError as exc:
        # A JSON string may contain code points that are not encodable as UTF-8
        # (e.g. lone surrogates). The transport is UTF-8 only, so surface this
        # as a typed ProtocolError rather than leaking a raw encoding error
        # across the boundary (Requirement 2.11).
        raise ProtocolError(f"MCP message is not UTF-8 encodable: {exc}") from exc


class LineBuffer:
    """Reassembles newline-delimited messages from arbitrary byte chunks.

    A transport hands bytes in chunks that do not respect message boundaries
    (one chunk may hold several messages plus a partial one). ``feed`` appends a
    chunk and yields each complete decoded JSON message.
    """

    def __init__(self) -> None:
        self._buf = b""

    def feed(self, chunk: bytes) -> Iterator[Dict[str, Any]]:
        self._buf += chunk
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line.decode("utf-8"))
            except (ValueError, UnicodeDecodeError) as exc:
                raise ProtocolError(f"invalid MCP JSON line: {exc}") from exc

    @property
    def pending(self) -> bytes:
        """Return any buffered bytes that are not yet a complete message."""
        return self._buf


def request(request_id: int, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Build a JSON-RPC request object."""
    msg: Dict[str, Any] = {"jsonrpc": JSONRPC_VERSION, "id": request_id, "method": method}
    if params is not None:
        msg["params"] = params
    return msg


def notification(method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Build a JSON-RPC notification (no id)."""
    msg: Dict[str, Any] = {"jsonrpc": JSONRPC_VERSION, "method": method}
    if params is not None:
        msg["params"] = params
    return msg


def is_response(message: Dict[str, Any]) -> bool:
    return "id" in message and ("result" in message or "error" in message)


def is_notification(message: Dict[str, Any]) -> bool:
    return "method" in message and "id" not in message


def response_outcome(message: Dict[str, Any]) -> Tuple[bool, Any]:
    """Return ``(ok, payload)`` for a response: result on success, error on fail."""
    if "error" in message:
        return False, message["error"]
    return True, message.get("result")


# --- MCP high-level method helpers -------------------------------------------
def initialize_request(
    request_id: int,
    client_name: str = "aro",
    protocol_version: str = "2024-11-05",
) -> Dict[str, Any]:
    """Build the MCP ``initialize`` handshake request."""
    return request(request_id, "initialize", {
        "protocolVersion": protocol_version,
        "capabilities": {},
        "clientInfo": {"name": client_name, "version": "1.0.0"},
    })


def tools_list_request(request_id: int) -> Dict[str, Any]:
    """Build the MCP ``tools/list`` request (enumerate available tools)."""
    return request(request_id, "tools/list", {})


def tools_call_request(request_id: int, name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Build the MCP ``tools/call`` request invoking tool ``name``."""
    return request(request_id, "tools/call", {
        "name": name,
        "arguments": arguments or {},
    })


def extract_tool_output(message: Dict[str, Any]) -> List[str]:
    """Extract human-readable text from a ``tools/call`` response.

    An MCP tool result carries a ``content`` list of typed blocks; text blocks
    have shape ``{"type": "text", "text": "..."}``. Returns a list of the text
    fragments found. Non-responses and unknown shapes yield ``[]``.
    """
    if not is_response(message):
        return []
    result = message.get("result")
    if not isinstance(result, dict):
        return []
    out: List[str] = []
    content = result.get("content")
    if isinstance(content, dict) and content.get("type") == "text":
        out.append(str(content.get("text", "")))
    elif isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                out.append(str(block.get("text", "")))
    return [t for t in out if t]
