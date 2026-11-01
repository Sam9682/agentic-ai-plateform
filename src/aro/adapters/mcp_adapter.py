"""Generic MCP runtime adapter (Task 4.1).

Drives a Model Context Protocol (MCP) server as an in-container subprocess,
speaking JSON-RPC 2.0 over stdio (newline-delimited). It is shaped on
:mod:`shai_cli` — an injectable ``popen`` spawns
``docker exec -i <container> <server_cmd>`` by default, so execution happens
inside the hardened agent container and the transport can be exercised
deterministically in tests. Remote install/logs/health go through
``src/ssh_utils.py`` exactly like the SHAI CLI adapter.

Protocol framing is delegated to the pure :mod:`mcp_protocol` module
(``encode_message`` / ``LineBuffer`` / request + helper builders); this adapter
only owns the transport, the capability gating and the typed-error boundary.

Design highlights (see design.md §2.2):

* **Capability gating (AC 2.3):** :meth:`get_capabilities` reports exactly the
  implemented set and :meth:`_require` raises :class:`CapabilityError` for
  anything outside it.
* **Bounded reads (AC 2.4):** every request/response round is bounded by
  ``read_timeout``. Reads poll the transport's stdout with ``select.select``;
  when no data arrives before the deadline the adapter raises
  :class:`ExecutionError` rather than blocking indefinitely.
* **Typed-error boundary (AC 2.11):** all failure paths are wrapped as
  :class:`AdapterError` subclasses (``ExecutionError`` / ``CapabilityError``);
  protocol/framing faults are re-raised as :class:`ExecutionError` so no raw
  exception crosses the adapter boundary.
"""

from __future__ import annotations

import select
import subprocess
import threading
import time
from typing import Any, Callable, Dict, Iterator, List, Optional

from . import mcp_protocol as mcp
from .base import (
    AgentRuntimeAdapter,
    AdapterError,
    Capability,
    CapabilityError,
    ExecutionChunk,
    ExecutionError,
    ExecutionHandle,
    ExecutionResult,
)

# The capability set this adapter actually implements. Reported verbatim by
# get_capabilities(); any operation outside it raises CapabilityError.
_MCP_CAPABILITIES = [
    Capability.INSTALL,
    Capability.START,
    Capability.STOP,
    Capability.STATUS,
    Capability.EXECUTE,
    Capability.STREAMING,
    Capability.CANCELLATION,
    Capability.LOGS,
    Capability.HEALTH_CHECK,
]


def build_server_argv(container_ref: str, server_cmd: List[str]) -> List[str]:
    """Assemble the argv to run the MCP server inside a container over stdio.

    Mirrors ``shai_cli.build_cli_argv``: ``docker exec -i`` keeps the server's
    stdin open for the JSON-RPC conversation. ``server_cmd`` is passed as
    discrete argv tokens (never shell-interpolated) to avoid injection.
    """
    return ["docker", "exec", "-i", container_ref, *server_cmd]


class McpTransport:
    """Bidirectional newline-delimited byte transport for MCP over stdio.

    Abstracted so protocol logic can be unit-tested against an injected mock
    (including one that never yields data, to exercise the read-timeout path).
    The default implementation wraps a spawned subprocess.
    """

    def write(self, data: bytes) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def read_chunks(self, deadline: Optional[float] = None) -> Iterator[bytes]:  # pragma: no cover - interface
        """Yield byte chunks, honoring ``deadline`` (monotonic seconds).

        Implementations SHOULD stop and return (or raise) once ``deadline`` is
        reached so a stalled server cannot block the caller forever.
        """
        raise NotImplementedError

    def close(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class SubprocessMcpTransport(McpTransport):
    """Transport backed by a subprocess speaking MCP JSON-RPC on stdio.

    Reads are bounded with ``select.select`` so a stalled server raises an
    :class:`ExecutionError` at the configured deadline instead of hanging.
    """

    def __init__(self, proc: subprocess.Popen):
        self._proc = proc

    def write(self, data: bytes) -> None:
        stdin = self._proc.stdin
        if stdin is None:
            raise ExecutionError("mcp transport stdin unavailable")
        try:
            if isinstance(data, (bytes, bytearray)) and not getattr(stdin, "encoding", None):
                stdin.write(data)
            else:
                stdin.write(data.decode("utf-8") if isinstance(data, (bytes, bytearray)) else data)
            stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise ExecutionError(f"mcp transport write failed: {exc}") from exc

    def read_chunks(self, deadline: Optional[float] = None) -> Iterator[bytes]:
        stdout = self._proc.stdout
        if stdout is None:
            return
        fd = stdout
        while True:
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ExecutionError("mcp read timeout")
            else:
                remaining = None
            try:
                ready, _, _ = select.select([fd], [], [], remaining)
            except (OSError, ValueError) as exc:
                raise ExecutionError(f"mcp transport select failed: {exc}") from exc
            if not ready:
                raise ExecutionError("mcp read timeout")
            chunk = fd.read1(65536) if hasattr(fd, "read1") else fd.read(65536)
            if not chunk:
                return
            if isinstance(chunk, str):
                chunk = chunk.encode("utf-8")
            yield chunk

    def close(self) -> None:
        try:
            if self._proc.poll() is None:
                self._proc.terminate()
        except Exception:  # noqa: BLE001
            pass


class _McpExecutionHandle(ExecutionHandle):
    """Drives one ``tools/call`` request and streams its response.

    Writes the ``tools/call`` request then reads newline-delimited responses via
    :class:`mcp_protocol.LineBuffer`, bounded by ``read_timeout``. The matching
    response id terminates the stream; any framing fault or read-deadline expiry
    surfaces as :class:`ExecutionError`.
    """

    def __init__(
        self,
        transport: McpTransport,
        request_id: int,
        tool_name: str,
        arguments: Dict[str, Any],
        read_timeout: float,
    ):
        self._t = transport
        self._req_id = request_id
        self._tool_name = tool_name
        self._arguments = arguments
        self._read_timeout = read_timeout
        self._buffer = mcp.LineBuffer()
        self._collected: List[str] = []
        self._result: Optional[ExecutionResult] = None
        self._cancelled = False
        self._lock = threading.Lock()

    def stream(self) -> Iterator[ExecutionChunk]:
        try:
            self._t.write(mcp.encode_message(
                mcp.tools_call_request(self._req_id, self._tool_name, self._arguments)
            ))
            deadline = time.monotonic() + self._read_timeout
            for raw in self._t.read_chunks(deadline):
                for msg in self._buffer.feed(raw):
                    if mcp.is_response(msg) and msg.get("id") == self._req_id:
                        ok, payload = mcp.response_outcome(msg)
                        texts = mcp.extract_tool_output(msg) if ok else []
                        for text in texts:
                            self._collected.append(text)
                            yield ExecutionChunk(data=text, channel="stdout")
                        self._result = ExecutionResult(
                            success=ok,
                            returncode=0 if ok else 1,
                            output="".join(self._collected),
                            error=None if ok else str(payload),
                        )
                        yield ExecutionChunk(data="", channel="event", done=True)
                        return
                    if mcp.is_notification(msg):
                        # Progress / log notifications stream through as output.
                        params = msg.get("params")
                        text = ""
                        if isinstance(params, dict):
                            text = str(params.get("message", "") or params.get("text", ""))
                        if text:
                            self._collected.append(text)
                            yield ExecutionChunk(data=text, channel="stdout")
                # Refresh the deadline only resets per read in read_chunks; the
                # overall request remains bounded by the initial deadline above.
            # Stream ended with no matching response.
            if self._result is None:
                self._result = ExecutionResult(
                    success=False, returncode=None,
                    output="".join(self._collected), error="mcp stream ended before response",
                )
        except AdapterError:
            raise
        except mcp.ProtocolError as exc:
            raise ExecutionError(f"mcp framing error: {exc}") from exc
        except Exception as exc:  # noqa: BLE001 - keep the typed-error boundary
            raise ExecutionError(f"mcp execution failed: {exc}") from exc

    def cancel(self) -> bool:
        with self._lock:
            self._cancelled = True
        try:
            self._t.write(mcp.encode_message(
                mcp.notification("notifications/cancelled", {"requestId": self._req_id})
            ))
            return True
        except Exception:  # noqa: BLE001
            return False

    def result(self) -> ExecutionResult:
        if self._result is not None:
            return self._result
        if self._cancelled:
            return ExecutionResult(success=False, returncode=None,
                                   output="".join(self._collected), error="cancelled")
        return ExecutionResult(success=False, returncode=None,
                               output="".join(self._collected), error="no result")


class McpAdapter(AgentRuntimeAdapter):
    """Generic MCP adapter operating an MCP server in a hardened container.

    Args:
        container_ref: Agent container name/id the MCP server runs in.
        server_cmd: argv of the MCP server inside the container (over stdio).
        server_ip: Managed server hosting the container (for remote exec).
        read_timeout: Per-request read deadline in seconds (AC 2.4).
        popen: Injectable subprocess spawner ``(argv) -> Popen`` (mirrors
            ``shai_cli``); defaults to a stdio ``subprocess.Popen``.
        transport_factory: Optional injectable ``() -> McpTransport`` used in
            tests to simulate a stalled/mock transport; when omitted the adapter
            spawns a subprocess via ``popen`` and wraps it.
        remote_exec: ``callable(server_ip, command, timeout) -> (ok, out, err)``
            for install/logs/health (defaults to ``ssh_utils.ssh_execute``).
    """

    adapter_id = "mcp"

    def __init__(
        self,
        container_ref: str,
        *,
        server_cmd: Optional[List[str]] = None,
        server_ip: str = "127.0.0.1",
        version: str = "latest",
        read_timeout: float = 30.0,
        popen: Optional[Callable[[List[str]], subprocess.Popen]] = None,
        transport_factory: Optional[Callable[[], McpTransport]] = None,
        remote_exec: Optional[Callable[..., Any]] = None,
    ):
        self._container = container_ref
        self._server_cmd = list(server_cmd) if server_cmd else []
        self._server_ip = server_ip
        self._version = version
        self._read_timeout = float(read_timeout)
        self._popen = popen
        self._transport_factory = transport_factory
        self._remote_exec = remote_exec
        self._transport: Optional[McpTransport] = None
        self._req_id = 0
        self._status = "UNKNOWN"
        self._tools: List[str] = []

    # -- helpers --------------------------------------------------------------
    def _exec(self, command: str, timeout: int = 120):
        fn = self._remote_exec
        if fn is None:
            from ...ssh_utils import ssh_execute
            fn = ssh_execute
        return fn(self._server_ip, command, timeout=timeout)

    def _spawn(self, argv: List[str]) -> subprocess.Popen:
        if self._popen is not None:
            return self._popen(argv)
        return subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )

    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    def _open_transport(self) -> McpTransport:
        if self._transport is not None:
            return self._transport
        if self._transport_factory is not None:
            self._transport = self._transport_factory()
            return self._transport
        argv = build_server_argv(self._container, self._server_cmd)
        self._transport = SubprocessMcpTransport(self._spawn(argv))
        return self._transport

    def _read_response(self, transport: McpTransport, request_id: int) -> Dict[str, Any]:
        """Read until the response for ``request_id`` arrives, bounded by read_timeout.

        Raises :class:`ExecutionError` on deadline, framing fault, or an early
        end of stream.
        """
        buffer = mcp.LineBuffer()
        deadline = time.monotonic() + self._read_timeout
        try:
            for raw in transport.read_chunks(deadline):
                for msg in buffer.feed(raw):
                    if mcp.is_response(msg) and msg.get("id") == request_id:
                        return msg
        except AdapterError:
            raise
        except mcp.ProtocolError as exc:
            raise ExecutionError(f"mcp framing error: {exc}") from exc
        except Exception as exc:  # noqa: BLE001
            raise ExecutionError(f"mcp read failed: {exc}") from exc
        raise ExecutionError("mcp stream ended before response")

    # -- capabilities ---------------------------------------------------------
    def get_capabilities(self) -> List[Capability]:
        return list(_MCP_CAPABILITIES)

    # -- lifecycle ------------------------------------------------------------
    def install(self, configuration: Dict[str, Any]) -> ExecutionResult:
        self._require(Capability.INSTALL)
        install_cmd = configuration.get("install_command")
        if not install_cmd:
            # Nothing to install (server already present in the image).
            return ExecutionResult(success=True, returncode=0, output="mcp install: no-op")
        cmd = f"docker exec {self._container} sh -lc {_shquote(str(install_cmd))}"
        ok, out, err = self._exec(cmd)
        return ExecutionResult(success=ok, returncode=0 if ok else 1, output=out, error=None if ok else err)

    def start(self, agent_id: str, configuration: Dict[str, Any]) -> ExecutionResult:
        self._require(Capability.START)
        try:
            transport = self._open_transport()
            # Handshake: initialize -> tools/list.
            init_id = self._next_id()
            transport.write(mcp.encode_message(mcp.initialize_request(init_id)))
            init_resp = self._read_response(transport, init_id)
            ok, payload = mcp.response_outcome(init_resp)
            if not ok:
                raise ExecutionError(f"mcp initialize failed: {payload}")
            list_id = self._next_id()
            transport.write(mcp.encode_message(mcp.tools_list_request(list_id)))
            list_resp = self._read_response(transport, list_id)
            ok, payload = mcp.response_outcome(list_resp)
            if not ok:
                raise ExecutionError(f"mcp tools/list failed: {payload}")
            self._tools = _tool_names(payload)
        except AdapterError as exc:
            self._status = "FAILED"
            self._close_transport()
            return ExecutionResult(success=False, returncode=1, output="", error=str(exc))
        self._status = "RUNNING"
        return ExecutionResult(
            success=True, returncode=0, output="mcp session established",
            extra={"tools": list(self._tools)},
        )

    def stop(self, agent_id: str) -> ExecutionResult:
        self._require(Capability.STOP)
        self._close_transport()
        self._status = "STOPPED"
        return ExecutionResult(success=True, returncode=0, output="stopped")

    def _close_transport(self) -> None:
        if self._transport is not None:
            try:
                self._transport.close()
            finally:
                self._transport = None

    def get_status(self, agent_id: str) -> str:
        self._require(Capability.STATUS)
        return self._status

    def execute(self, agent_id: str, task: Dict[str, Any]) -> ExecutionHandle:
        self._require(Capability.EXECUTE)
        if self._transport is None or self._status != "RUNNING":
            raise ExecutionError("adapter not started: no MCP session")
        tool_name = str(task.get("tool") or task.get("name") or "")
        if not tool_name:
            raise ExecutionError("mcp execute requires a 'tool' name")
        arguments = task.get("arguments")
        if not isinstance(arguments, dict):
            arguments = {}
        return _McpExecutionHandle(
            self._transport, self._next_id(), tool_name, arguments, self._read_timeout
        )

    def get_logs(self, agent_id: str, limit: int = 200) -> str:
        self._require(Capability.LOGS)
        ok, out, err = self._exec(f"docker logs --tail {int(limit)} {self._container}")
        return out if ok else (err or "")

    def health_check(self) -> bool:
        self._require(Capability.HEALTH_CHECK)
        ok, out, _ = self._exec(
            f"docker inspect -f '{{{{.State.Running}}}}' {self._container}", timeout=15
        )
        return ok and "true" in (out or "").lower()


def _tool_names(list_result: Any) -> List[str]:
    """Extract tool names from a ``tools/list`` result payload."""
    if not isinstance(list_result, dict):
        return []
    tools = list_result.get("tools")
    names: List[str] = []
    if isinstance(tools, list):
        for tool in tools:
            if isinstance(tool, dict) and isinstance(tool.get("name"), str):
                names.append(tool["name"])
    return names


def _shquote(value: str) -> str:
    """Single-quote a value for a POSIX ``sh -lc`` payload."""
    import shlex
    return shlex.quote(value)
