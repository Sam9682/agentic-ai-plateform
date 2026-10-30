"""SHAI headless CLI runtime adapter (Task 9).

Drives SHAI (OVHcloud's CLI agent) in headless mode as a subprocess inside the
hardened agent container, streaming stdout line-by-line. SHAI is already wired
to the platform's MCP server (``python -m src.mcp_interface``) over stdio, so
this adapter reuses that registration rather than defining a new tool surface.

Capability note (documented, not faked): the headless CLI exposes execution,
streaming, cancellation (process signal) and logs, but does NOT provide a
structured health endpoint — health is inferred from the container state, so
HEALTH_CHECK is supported via the container inspector, while a fine-grained
STATUS beyond RUNNING/STOPPED is not available from the CLI itself.
"""

from __future__ import annotations

import shlex
import subprocess
import threading
from typing import Any, Callable, Dict, Iterator, List, Optional

from .base import (
    AgentRuntimeAdapter,
    Capability,
    ExecutionChunk,
    ExecutionError,
    ExecutionHandle,
    ExecutionResult,
)

_SHAI_CLI_CAPABILITIES = [
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


def build_cli_argv(
    container_ref: str,
    prompt: str,
    *,
    agent_config: Optional[str] = None,
    extra_args: Optional[List[str]] = None,
) -> List[str]:
    """Assemble the argv to run a one-shot SHAI headless prompt in a container.

    Uses ``docker exec`` so execution happens inside the hardened container. The
    prompt is passed as a single argument (not shell-interpolated) to avoid
    injection.
    """
    argv = ["docker", "exec", "-i", container_ref, "shai", "--headless"]
    if agent_config:
        argv += ["--agent", agent_config]
    if extra_args:
        argv += list(extra_args)
    argv += ["--prompt", prompt]
    return argv


class _ProcessHandle(ExecutionHandle):
    """Streams a subprocess's stdout as chunks; cancel terminates the process."""

    def __init__(self, proc: subprocess.Popen):
        self._proc = proc
        self._lines: List[str] = []
        self._cancelled = False
        self._lock = threading.Lock()

    def stream(self) -> Iterator[ExecutionChunk]:
        assert self._proc.stdout is not None
        for raw in iter(self._proc.stdout.readline, ""):
            line = raw.rstrip("\n")
            self._lines.append(line)
            yield ExecutionChunk(data=line, channel="stdout")
            with self._lock:
                if self._cancelled:
                    break
        self._proc.wait()
        yield ExecutionChunk(data="", channel="event", done=True)

    def cancel(self) -> bool:
        with self._lock:
            self._cancelled = True
        try:
            if self._proc.poll() is None:
                self._proc.terminate()
            return True
        except Exception:  # noqa: BLE001
            return False

    def result(self) -> ExecutionResult:
        rc = self._proc.poll()
        if self._cancelled:
            return ExecutionResult(success=False, returncode=rc, output="\n".join(self._lines), error="cancelled")
        return ExecutionResult(success=(rc == 0), returncode=rc, output="\n".join(self._lines),
                               error=None if rc == 0 else "non-zero exit")


class ShaiCliAdapter(AgentRuntimeAdapter):
    """SHAI headless CLI adapter running inside a hardened container."""

    adapter_id = "shai-cli"

    def __init__(
        self,
        container_ref: str,
        *,
        server_ip: str = "127.0.0.1",
        version: str = "0.2.2",
        agent_config: Optional[str] = None,
        popen: Optional[Callable[[List[str]], subprocess.Popen]] = None,
        remote_exec: Optional[Callable[..., Any]] = None,
    ):
        self._container = container_ref
        self._server_ip = server_ip
        self._version = version
        self._agent_config = agent_config
        self._popen = popen
        self._remote_exec = remote_exec
        self._status = "UNKNOWN"

    def _exec(self, command: str, timeout: int = 120):
        fn = self._remote_exec
        if fn is None:
            from ...ssh_utils import ssh_execute
            fn = ssh_execute
        return fn(self._server_ip, command, timeout=timeout)

    def _spawn(self, argv: List[str]) -> subprocess.Popen:
        if self._popen is not None:
            return self._popen(argv)
        return subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, bufsize=1)

    def get_capabilities(self) -> List[Capability]:
        return list(_SHAI_CLI_CAPABILITIES)

    def install(self, configuration: Dict[str, Any]) -> ExecutionResult:
        self._require(Capability.INSTALL)
        version = configuration.get("version", self._version)
        cmd = f"docker exec {self._container} sh -lc 'npm install -g @ovhcloud/shai@{shlex.quote(version)}'"
        ok, out, err = self._exec(cmd)
        return ExecutionResult(success=ok, returncode=0 if ok else 1, output=out, error=None if ok else err)

    def start(self, agent_id: str, configuration: Dict[str, Any]) -> ExecutionResult:
        self._require(Capability.START)
        # Headless CLI has no long-lived daemon; "start" marks the adapter ready
        # to spawn one-shot prompt processes.
        self._status = "RUNNING"
        return ExecutionResult(success=True, returncode=0, output="shai cli ready")

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
        argv = build_cli_argv(self._container, prompt, agent_config=self._agent_config)
        return _ProcessHandle(self._spawn(argv))

    def get_logs(self, agent_id: str, limit: int = 200) -> str:
        self._require(Capability.LOGS)
        ok, out, err = self._exec(f"docker logs --tail {int(limit)} {self._container}")
        return out if ok else (err or "")

    def health_check(self) -> bool:
        self._require(Capability.HEALTH_CHECK)
        ok, out, _ = self._exec(f"docker inspect -f '{{{{.State.Running}}}}' {self._container}", timeout=15)
        return ok and "true" in (out or "").lower()
