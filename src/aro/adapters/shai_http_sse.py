"""SHAI HTTP/SSE runtime adapter (Task 9).

Drives a SHAI agent exposed over HTTP: a POST starts a task and the response
body is a Server-Sent Events stream of incremental output. This is a distinct
protocol from the CLI adapter (separate transport, separate capability
profile), per the constraint that ACP, MCP and HTTP/SSE each need their own
adapter — an SSE connection alone does not expose the same surface as the CLI.

Capability note (documented, not faked): the HTTP transport exposes execution,
streaming and health (via a GET health endpoint). Cancellation is supported only
if the SHAI server advertises a cancel endpoint; when it does not, the adapter
reports CANCELLATION as unsupported for that deployment (so callers record the
limitation rather than assume a silent cancel). INSTALL is not applicable to a
remote HTTP endpoint and is therefore not advertised.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Iterator, List, Optional

from .base import (
    AgentRuntimeAdapter,
    Capability,
    ExecutionChunk,
    ExecutionError,
    ExecutionHandle,
    ExecutionResult,
)
from .sse_parser import SSEParser


class HttpClient:
    """Minimal injectable HTTP client interface the adapter depends on.

    A real implementation wraps ``requests``; tests inject a fake. ``stream_post``
    yields text chunks of an SSE response body; ``get`` returns ``(status, text)``.
    """

    def stream_post(self, url: str, json_body: Dict[str, Any], headers: Dict[str, str]) -> Iterator[str]:  # pragma: no cover
        raise NotImplementedError

    def get(self, url: str, headers: Dict[str, str]):  # pragma: no cover
        raise NotImplementedError

    def post(self, url: str, json_body: Dict[str, Any], headers: Dict[str, str]):  # pragma: no cover
        raise NotImplementedError


class _SSEExecutionHandle(ExecutionHandle):
    """Streams SHAI SSE events as chunks; completion on a terminal event."""

    def __init__(self, chunk_iter: Iterator[str], cancel_fn: Optional[Callable[[], bool]]):
        self._chunks = chunk_iter
        self._parser = SSEParser()
        self._cancel_fn = cancel_fn
        self._collected: List[str] = []
        self._result: Optional[ExecutionResult] = None
        self._cancelled = False

    def stream(self) -> Iterator[ExecutionChunk]:
        for raw in self._chunks:
            for event in self._parser.feed(raw):
                if event.event in ("done", "end", "complete"):
                    self._result = ExecutionResult(
                        success=True, returncode=0, output="".join(self._collected),
                    )
                    yield ExecutionChunk(data="", channel="event", done=True)
                    return
                if event.event == "error":
                    self._result = ExecutionResult(
                        success=False, returncode=1, output="".join(self._collected),
                        error=event.data,
                    )
                    yield ExecutionChunk(data=event.data, channel="stderr", done=True)
                    return
                if event.data:
                    self._collected.append(event.data)
                    yield ExecutionChunk(data=event.data, channel="stdout")
            if self._cancelled:
                break
        if self._result is None:
            self._result = ExecutionResult(
                success=not self._cancelled, returncode=0 if not self._cancelled else None,
                output="".join(self._collected),
                error="cancelled" if self._cancelled else None,
            )

    def cancel(self) -> bool:
        self._cancelled = True
        if self._cancel_fn is not None:
            return self._cancel_fn()
        return False  # deployment does not support cancel

    def result(self) -> ExecutionResult:
        if self._result is not None:
            return self._result
        return ExecutionResult(success=False, returncode=None,
                               output="".join(self._collected), error="no result")


class ShaiHttpSseAdapter(AgentRuntimeAdapter):
    """SHAI adapter speaking HTTP + SSE to a running SHAI server."""

    adapter_id = "shai-http"

    def __init__(
        self,
        base_url: str,
        http_client: HttpClient,
        *,
        api_token: Optional[str] = None,
        supports_cancel: bool = False,
    ):
        self._base = base_url.rstrip("/")
        self._http = http_client
        self._token = api_token
        self._supports_cancel = supports_cancel
        self._status = "UNKNOWN"
        self._current_task_id: Optional[str] = None

    def _headers(self) -> Dict[str, str]:
        h = {"Accept": "text/event-stream", "Content-Type": "application/json"}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    def get_capabilities(self) -> List[Capability]:
        caps = [
            Capability.START,
            Capability.STOP,
            Capability.STATUS,
            Capability.EXECUTE,
            Capability.STREAMING,
            Capability.HEALTH_CHECK,
        ]
        # Cancellation only when the deployment advertises it (no faking).
        if self._supports_cancel:
            caps.append(Capability.CANCELLATION)
        return caps

    def install(self, configuration: Dict[str, Any]) -> ExecutionResult:
        # Remote HTTP endpoint: nothing to install locally.
        self._require(Capability.INSTALL)  # will raise CapabilityError (not advertised)

    def start(self, agent_id: str, configuration: Dict[str, Any]) -> ExecutionResult:
        self._require(Capability.START)
        self._status = "RUNNING"
        return ExecutionResult(success=True, returncode=0, output="shai http session ready")

    def stop(self, agent_id: str) -> ExecutionResult:
        self._require(Capability.STOP)
        self._status = "STOPPED"
        return ExecutionResult(success=True, returncode=0, output="stopped")

    def get_status(self, agent_id: str) -> str:
        self._require(Capability.STATUS)
        return self._status

    def execute(self, agent_id: str, task: Dict[str, Any]) -> ExecutionHandle:
        self._require(Capability.EXECUTE)
        if self._status != "RUNNING":
            raise ExecutionError("adapter not started")
        prompt = str(task.get("prompt", ""))
        chunk_iter = self._http.stream_post(
            f"{self._base}/v1/chat", {"prompt": prompt, "stream": True}, self._headers()
        )
        cancel_fn = None
        if self._supports_cancel:
            def cancel_fn():  # noqa: E306
                status, _ = self._http.post(f"{self._base}/v1/cancel", {}, self._headers())
                return 200 <= int(status) < 300
        return _SSEExecutionHandle(chunk_iter, cancel_fn)

    def get_logs(self, agent_id: str, limit: int = 200) -> str:
        self._require(Capability.LOGS)  # not advertised -> CapabilityError

    def health_check(self) -> bool:
        self._require(Capability.HEALTH_CHECK)
        status, _ = self._http.get(f"{self._base}/health", self._headers())
        return 200 <= int(status) < 300
