"""Common agent runtime adapter interface + capability model (Task 5).

Every runtime (Kiro ACP, SHAI CLI, SHAI HTTP/SSE, generic CLI/MCP) implements
:class:`AgentRuntimeAdapter`. The interface accounts for asynchronous execution,
streaming output, cancellation, errors and runtime-specific capabilities. It is
modeled on the existing ``ContainerRuntime`` ABC in
``src/serverless/container_runtime.py``.

Design choices:
* **Capabilities are explicit.** An adapter reports exactly what it supports via
  :meth:`get_capabilities`. Callers must check capability support rather than
  assuming parity; unsupported operations raise :class:`CapabilityError` so the
  platform can record the limitation instead of silently faking behavior.
* **Streaming via generators.** :meth:`execute` returns an :class:`ExecutionHandle`
  whose ``stream()`` yields :class:`ExecutionChunk` objects and whose ``cancel()``
  requests cancellation. This keeps the interface transport-agnostic (a CLI
  adapter reads subprocess stdout; an SSE adapter reads an event stream).
* **Errors are typed**, never leaked as arbitrary exceptions across the boundary.
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional


class Capability(enum.Enum):
    """Discrete capabilities a runtime adapter may support."""

    INSTALL = "install"
    START = "start"
    STOP = "stop"
    STATUS = "status"
    EXECUTE = "execute"
    STREAMING = "streaming"
    CANCELLATION = "cancellation"
    LOGS = "logs"
    HEALTH_CHECK = "health_check"


class AdapterError(Exception):
    """Base class for adapter errors surfaced to the lifecycle layer."""


class CapabilityError(AdapterError):
    """Raised when an operation is requested that the adapter does not support."""

    def __init__(self, capability: Capability):
        self.capability = capability
        super().__init__(f"runtime does not support capability: {capability.value}")


class ExecutionError(AdapterError):
    """Raised when execution fails for a runtime-specific reason."""


@dataclass
class ExecutionChunk:
    """One streamed piece of execution output."""

    data: str
    channel: str = "stdout"  # 'stdout' | 'stderr' | 'event'
    done: bool = False


@dataclass
class ExecutionResult:
    """Terminal result of an execution."""

    success: bool
    returncode: Optional[int] = None
    output: str = ""
    error: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "returncode": self.returncode,
            "output": self.output,
            "error": self.error,
            **self.extra,
        }


class ExecutionHandle(ABC):
    """Handle to a running execution: stream chunks, cancel, await result."""

    @abstractmethod
    def stream(self) -> Iterator[ExecutionChunk]:
        """Yield execution output chunks until the execution completes."""
        ...

    @abstractmethod
    def cancel(self) -> bool:
        """Request cancellation. Returns True when cancellation was initiated."""
        ...

    @abstractmethod
    def result(self) -> ExecutionResult:
        """Block until the execution finishes and return its terminal result."""
        ...


class AgentRuntimeAdapter(ABC):
    """Common interface every agent runtime adapter implements."""

    #: Human-readable adapter id, e.g. 'kiro-acp', 'shai-cli', 'shai-http'.
    adapter_id: str = "base"

    @abstractmethod
    def get_capabilities(self) -> List[Capability]:
        """Return the capabilities this adapter actually supports."""
        ...

    def supports(self, capability: Capability) -> bool:
        """Return True when ``capability`` is supported by this adapter."""
        return capability in set(self.get_capabilities())

    def _require(self, capability: Capability) -> None:
        """Raise :class:`CapabilityError` when ``capability`` is unsupported."""
        if not self.supports(capability):
            raise CapabilityError(capability)

    @abstractmethod
    def install(self, configuration: Dict[str, Any]) -> ExecutionResult:
        """Install/prepare the runtime (pinned, integrity-verified)."""
        ...

    @abstractmethod
    def start(self, agent_id: str, configuration: Dict[str, Any]) -> ExecutionResult:
        """Start the runtime for an agent in its execution environment."""
        ...

    @abstractmethod
    def stop(self, agent_id: str) -> ExecutionResult:
        """Stop the runtime for an agent."""
        ...

    @abstractmethod
    def get_status(self, agent_id: str) -> str:
        """Return a coarse runtime status string for the agent."""
        ...

    @abstractmethod
    def execute(self, agent_id: str, task: Dict[str, Any]) -> ExecutionHandle:
        """Begin executing a task; return a streaming/cancellable handle."""
        ...

    @abstractmethod
    def get_logs(self, agent_id: str, limit: int = 200) -> str:
        """Return recent logs for the agent."""
        ...

    @abstractmethod
    def health_check(self) -> bool:
        """Return True when the runtime is healthy."""
        ...


# --------------------------------------------------------------------------- #
# Test/dev adapters
# --------------------------------------------------------------------------- #
class _ListHandle(ExecutionHandle):
    """An ExecutionHandle backed by a pre-seeded list of chunks (for the fake)."""

    def __init__(self, chunks: List[ExecutionChunk], result: ExecutionResult):
        self._chunks = list(chunks)
        self._result = result
        self._cancelled = False

    def stream(self) -> Iterator[ExecutionChunk]:
        for chunk in self._chunks:
            if self._cancelled:
                yield ExecutionChunk(data="cancelled", channel="event", done=True)
                return
            yield chunk

    def cancel(self) -> bool:
        self._cancelled = True
        return True

    def result(self) -> ExecutionResult:
        if self._cancelled:
            return ExecutionResult(success=False, returncode=None,
                                   output="", error="cancelled")
        return self._result


class FakeAdapter(AgentRuntimeAdapter):
    """Deterministic adapter for unit tests and demos.

    Supports the full capability set and echoes the task prompt back as streamed
    chunks, so lifecycle/worker logic can be exercised without a real runtime.
    """

    adapter_id = "fake"

    def __init__(self, capabilities: Optional[List[Capability]] = None):
        self._caps = capabilities if capabilities is not None else list(Capability)
        self._status: Dict[str, str] = {}

    def get_capabilities(self) -> List[Capability]:
        return list(self._caps)

    def install(self, configuration):
        self._require(Capability.INSTALL)
        return ExecutionResult(success=True, returncode=0, output="installed")

    def start(self, agent_id, configuration):
        self._require(Capability.START)
        self._status[agent_id] = "RUNNING"
        return ExecutionResult(success=True, returncode=0, output="started")

    def stop(self, agent_id):
        self._require(Capability.STOP)
        self._status[agent_id] = "STOPPED"
        return ExecutionResult(success=True, returncode=0, output="stopped")

    def get_status(self, agent_id):
        self._require(Capability.STATUS)
        return self._status.get(agent_id, "UNKNOWN")

    def execute(self, agent_id, task):
        self._require(Capability.EXECUTE)
        prompt = str(task.get("prompt", ""))
        chunks = [
            ExecutionChunk(data=f"echo: {prompt}", channel="stdout"),
            ExecutionChunk(data="", channel="event", done=True),
        ]
        return _ListHandle(chunks, ExecutionResult(success=True, returncode=0, output=f"echo: {prompt}"))

    def get_logs(self, agent_id, limit=200):
        self._require(Capability.LOGS)
        return f"logs for {agent_id}"

    def health_check(self):
        self._require(Capability.HEALTH_CHECK)
        return True


class NullAdapter(AgentRuntimeAdapter):
    """Adapter that supports nothing; every operation raises CapabilityError.

    Useful to prove the capability-gating contract and to represent a runtime
    whose capabilities have not yet been established.
    """

    adapter_id = "null"

    def get_capabilities(self) -> List[Capability]:
        return []

    def install(self, configuration):
        self._require(Capability.INSTALL)

    def start(self, agent_id, configuration):
        self._require(Capability.START)

    def stop(self, agent_id):
        self._require(Capability.STOP)

    def get_status(self, agent_id):
        self._require(Capability.STATUS)

    def execute(self, agent_id, task):
        self._require(Capability.EXECUTE)

    def get_logs(self, agent_id, limit=200):
        self._require(Capability.LOGS)

    def health_check(self):
        self._require(Capability.HEALTH_CHECK)
