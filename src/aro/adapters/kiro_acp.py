"""Kiro ACP runtime adapter (Task 8).

Drives a Kiro agent over the Agent Client Protocol (ACP): JSON-RPC 2.0 over the
agent subprocess's stdio, newline-delimited. The adapter:

* installs the Kiro CLI with a pinned version + integrity check (no arbitrary
  install script) inside the hardened agent container;
* starts the agent as ``kiro --acp`` (stdio) within the container;
* runs the ACP handshake (initialize -> session/new), sends ``session/prompt``
  and streams ``session/update`` notifications as :class:`ExecutionChunk`s;
* cancels via ``session/cancel``; reports health and capabilities.

The stdio transport is injected (:class:`AcpTransport`) so the protocol logic is
unit-tested against a mock endpoint; the default transport spawns a real
subprocess (``docker exec`` into the agent container, or a local process).
"""

from __future__ import annotations

import subprocess
import threading
from typing import Any, Callable, Dict, Iterator, List, Optional

from . import acp_protocol as acp
from .base import (
    AgentRuntimeAdapter,
    Capability,
    ExecutionChunk,
    ExecutionError,
    ExecutionHandle,
    ExecutionResult,
)

# Kiro capabilities over ACP. Pause is not exposed by ACP, so it is not listed
# (the platform records the limitation rather than faking it).
_KIRO_CAPABILITIES = [
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


class AcpTransport:
    """Abstract bidirectional newline-delimited byte transport for ACP."""

    def write(self, data: bytes) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def read_chunks(self) -> Iterator[bytes]:  # pragma: no cover - interface
        raise NotImplementedError

    def close(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class SubprocessAcpTransport(AcpTransport):
    """Transport backed by a spawned subprocess speaking ACP on stdio."""

    def __init__(self, argv: List[str]):
        self._proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )

    def write(self, data: bytes) -> None:
        assert self._proc.stdin is not None
        self._proc.stdin.write(data)
        self._proc.stdin.flush()

    def read_chunks(self) -> Iterator[bytes]:
        assert self._proc.stdout is not None
        while True:
            chunk = self._proc.stdout.read1(65536) if hasattr(self._proc.stdout, "read1") \
                else self._proc.stdout.read(65536)
            if not chunk:
                return
            yield chunk

    def close(self) -> None:
        try:
            if self._proc.poll() is None:
                self._proc.terminate()
        except Exception:  # noqa: BLE001
            pass


class _AcpExecutionHandle(ExecutionHandle):
    """ExecutionHandle driving one ACP session/prompt + streamed updates."""

    def __init__(self, transport: AcpTransport, session_id: str, prompt_id: int, prompt_text: str):
        self._t = transport
        self._session_id = session_id
        self._prompt_id = prompt_id
        self._prompt_text = prompt_text
        self._buffer = acp.LineBuffer()
        self._collected: List[str] = []
        self._result: Optional[ExecutionResult] = None
        self._cancelled = False
        self._lock = threading.Lock()

    def stream(self) -> Iterator[ExecutionChunk]:
        # Send the prompt, then read until the matching response arrives.
        self._t.write(acp.encode_message(
            acp.prompt_request(self._prompt_id, self._session_id, self._prompt_text)
        ))
        for raw in self._t.read_chunks():
            for msg in self._buffer.feed(raw):
                if acp.is_notification(msg):
                    for text in acp.extract_update_text(msg):
                        self._collected.append(text)
                        yield ExecutionChunk(data=text, channel="stdout")
                elif acp.is_response(msg) and msg.get("id") == self._prompt_id:
                    ok, payload = acp.response_outcome(msg)
                    self._result = ExecutionResult(
                        success=ok,
                        returncode=0 if ok else 1,
                        output="".join(self._collected),
                        error=None if ok else str(payload),
                        extra={"stop_reason": (payload or {}).get("stopReason") if ok and isinstance(payload, dict) else None},
                    )
                    yield ExecutionChunk(data="", channel="event", done=True)
                    return
        # Stream ended without a terminal response.
        if self._result is None:
            self._result = ExecutionResult(
                success=False, returncode=None,
                output="".join(self._collected), error="acp stream ended early",
            )

    def cancel(self) -> bool:
        with self._lock:
            self._cancelled = True
        try:
            self._t.write(acp.encode_message(acp.cancel_notification(self._session_id)))
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


class KiroAcpAdapter(AgentRuntimeAdapter):
    """Adapter that operates a Kiro agent over ACP inside a hardened container.

    Args:
        container_ref: The agent container name/id Kiro runs in.
        server_ip: Managed server hosting the container (for remote exec).
        version: Pinned Kiro version to install.
        sha256: Integrity digest for the pinned install artifact.
        transport_factory: Builds an :class:`AcpTransport` (injected in tests).
        remote_exec: callable(server_ip, command, timeout) -> (ok, out, err)
            used for install/start/logs/health (defaults to ssh_utils.ssh_execute).
    """

    adapter_id = "kiro-acp"

    def __init__(
        self,
        container_ref: str,
        *,
        server_ip: str = "127.0.0.1",
        version: str = "1.0.0",
        sha256: Optional[str] = None,
        transport_factory: Optional[Callable[[], AcpTransport]] = None,
        remote_exec: Optional[Callable[..., Any]] = None,
    ):
        self._container = container_ref
        self._server_ip = server_ip
        self._version = version
        self._sha256 = sha256
        self._transport_factory = transport_factory
        self._remote_exec = remote_exec
        self._transport: Optional[AcpTransport] = None
        self._session_id: Optional[str] = None
        self._req_id = 0
        self._status = "UNKNOWN"

    # -- helpers --------------------------------------------------------------
    def _exec(self, command: str, timeout: int = 120):
        fn = self._remote_exec
        if fn is None:
            from ...ssh_utils import ssh_execute
            fn = ssh_execute
        return fn(self._server_ip, command, timeout=timeout)

    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    # -- capabilities ---------------------------------------------------------
    def get_capabilities(self) -> List[Capability]:
        return list(_KIRO_CAPABILITIES)

    # -- lifecycle ------------------------------------------------------------
    def install(self, configuration: Dict[str, Any]) -> ExecutionResult:
        self._require(Capability.INSTALL)
        version = configuration.get("version", self._version)
        # Pinned install inside the container; integrity verified when a digest
        # is supplied. No arbitrary agent-supplied script is executed.
        verify = f" && echo {self._sha256}  /opt/kiro/kiro | sha256sum -c -" if self._sha256 else ""
        cmd = (
            f"docker exec {self._container} sh -lc "
            f"'install-kiro --version {version}{verify}'"
        )
        ok, out, err = self._exec(cmd)
        return ExecutionResult(success=ok, returncode=0 if ok else 1, output=out, error=None if ok else err)

    def start(self, agent_id: str, configuration: Dict[str, Any]) -> ExecutionResult:
        self._require(Capability.START)
        self._open_transport()
        try:
            self._handshake(configuration.get("cwd", "/workspace"))
        except ExecutionError as exc:
            self._status = "FAILED"
            return ExecutionResult(success=False, returncode=1, output="", error=str(exc))
        self._status = "RUNNING"
        return ExecutionResult(success=True, returncode=0, output="acp session established")

    def stop(self, agent_id: str) -> ExecutionResult:
        self._require(Capability.STOP)
        if self._transport is not None:
            try:
                self._transport.close()
            finally:
                self._transport = None
                self._session_id = None
        self._status = "STOPPED"
        return ExecutionResult(success=True, returncode=0, output="stopped")

    def get_status(self, agent_id: str) -> str:
        self._require(Capability.STATUS)
        return self._status

    def execute(self, agent_id: str, task: Dict[str, Any]) -> ExecutionHandle:
        self._require(Capability.EXECUTE)
        if self._transport is None or self._session_id is None:
            raise ExecutionError("adapter not started: no ACP session")
        prompt_text = str(task.get("prompt", ""))
        return _AcpExecutionHandle(
            self._transport, self._session_id, self._next_id(), prompt_text
        )

    def get_logs(self, agent_id: str, limit: int = 200) -> str:
        self._require(Capability.LOGS)
        ok, out, err = self._exec(f"docker logs --tail {int(limit)} {self._container}")
        return out if ok else (err or "")

    def health_check(self) -> bool:
        self._require(Capability.HEALTH_CHECK)
        ok, out, _ = self._exec(f"docker inspect -f '{{{{.State.Running}}}}' {self._container}", timeout=15)
        return ok and "true" in (out or "").lower()

    # -- ACP session ----------------------------------------------------------
    def _open_transport(self) -> None:
        if self._transport is not None:
            return
        if self._transport_factory is not None:
            self._transport = self._transport_factory()
            return
        # Default: docker exec the agent container to run Kiro in ACP stdio mode.
        argv = ["docker", "exec", "-i", self._container, "kiro", "--acp"]
        self._transport = SubprocessAcpTransport(argv)

    def _handshake(self, cwd: str) -> None:
        """Run initialize -> session/new, capturing the session id.

        Reads responses off the transport until both the initialize and
        session/new responses have been seen. Raises :class:`ExecutionError`
        when the agent returns an error for either step.
        """
        assert self._transport is not None
        init_id = self._next_id()
        self._transport.write(acp.encode_message(acp.initialize_request(init_id)))
        new_id = self._next_id()
        self._transport.write(acp.encode_message(acp.new_session_request(new_id, cwd)))

        buffer = acp.LineBuffer()
        seen_init = False
        for raw in self._transport.read_chunks():
            for msg in buffer.feed(raw):
                if not acp.is_response(msg):
                    continue
                ok, payload = acp.response_outcome(msg)
                if msg.get("id") == init_id:
                    if not ok:
                        raise ExecutionError(f"initialize failed: {payload}")
                    seen_init = True
                elif msg.get("id") == new_id:
                    if not ok:
                        raise ExecutionError(f"session/new failed: {payload}")
                    self._session_id = (payload or {}).get("sessionId")
                    if not self._session_id:
                        raise ExecutionError("session/new returned no sessionId")
                    if seen_init:
                        return
        raise ExecutionError("ACP handshake did not complete")
