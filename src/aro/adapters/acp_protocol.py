"""Pure Agent Client Protocol (ACP) codec (Task 8).

ACP is JSON-RPC 2.0 over stdio with **newline-delimited** JSON: each message is
exactly one line (no embedded newlines); logs go to stderr. This module holds
the pure, side-effect-free framing + message helpers so the adapter's transport
can be exercised deterministically without spawning a process.

References (rephrased for licensing compliance):
* ACP transport is newline-delimited JSON-RPC 2.0 over stdio
  (https://agentclientprotocol.com/protocol/v2/transports).
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterator, List, Optional, Tuple

JSONRPC_VERSION = "2.0"


class ProtocolError(Exception):
    """Raised when a message cannot be framed/parsed per the ACP transport."""


def encode_message(message: Dict[str, Any]) -> bytes:
    """Serialize a JSON-RPC message to a single newline-terminated line.

    Raises :class:`ProtocolError` if the serialized form would contain an
    embedded newline (the transport forbids it).
    """
    line = json.dumps(message, separators=(",", ":"), ensure_ascii=False)
    if "\n" in line:
        raise ProtocolError("ACP message must not contain embedded newlines")
    return (line + "\n").encode("utf-8")


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
                raise ProtocolError(f"invalid ACP JSON line: {exc}") from exc

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


# --- ACP high-level method helpers -------------------------------------------
def initialize_request(request_id: int, client_name: str = "aro", protocol_version: int = 1) -> Dict[str, Any]:
    """Build the ACP ``initialize`` handshake request."""
    return request(request_id, "initialize", {
        "protocolVersion": protocol_version,
        "clientCapabilities": {},
        "clientInfo": {"name": client_name},
    })


def new_session_request(request_id: int, cwd: str = "/workspace") -> Dict[str, Any]:
    """Build the ACP ``session/new`` request."""
    return request(request_id, "session/new", {"cwd": cwd, "mcpServers": []})


def prompt_request(request_id: int, session_id: str, text: str) -> Dict[str, Any]:
    """Build the ACP ``session/prompt`` request carrying a user text block."""
    return request(request_id, "session/prompt", {
        "sessionId": session_id,
        "prompt": [{"type": "text", "text": text}],
    })


def cancel_notification(session_id: str) -> Dict[str, Any]:
    """Build the ACP ``session/cancel`` notification."""
    return notification("session/cancel", {"sessionId": session_id})


def extract_update_text(message: Dict[str, Any]) -> List[str]:
    """Extract human-readable text from a ``session/update`` notification.

    Returns a list of text fragments found in common update shapes
    (agent_message_chunk / tool_call content). Unknown shapes yield [].
    """
    if not is_notification(message) or message.get("method") != "session/update":
        return []
    params = message.get("params") or {}
    update = params.get("update") or {}
    out: List[str] = []
    content = update.get("content")
    if isinstance(content, dict) and content.get("type") == "text":
        out.append(str(content.get("text", "")))
    elif isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                out.append(str(block.get("text", "")))
    text = update.get("text")
    if isinstance(text, str):
        out.append(text)
    return [t for t in out if t]
