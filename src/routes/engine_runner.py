"""Surface-agnostic agentic-engine runner.

This module extracts the engine-selection and subprocess-execution logic that is
currently duplicated inside the two Flask SSE generators in ``genai_routes.py``,
with no Flask/SSE dependency. Both the MCP tools and (as a follow-up) the Flask
routes can call it.

The engine-selection logic mirrors ``genai_routes`` exactly:
  * ``deployControlPlan.sh`` when ``agentic_command`` is set,
  * shai ``-p`` form when the engine is ``shai``,
  * else qchat ``chat --trust-all-tools``.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import time
from dataclasses import dataclass, field
from typing import Optional

from ..config_postgres import (
    LINUX_USER_INSTALLATION,
    PLTF_FOLDER,
    AI_ENGINE,
    TIMEOUT_CLEAN_SHUTDOWN,
    get_shai_paths,
    get_qchat_paths,
)

_ANSI = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')


class EngineNotFoundError(RuntimeError):
    """Raised when no executable can be resolved for the configured engine."""

    def __init__(self, engine: str):
        super().__init__(f"agentic engine executable not found for '{engine}'")
        self.engine = engine


@dataclass
class EngineResult:
    """Structured result of an agentic-engine run.

    ``as_dict()`` always emits ``{success, returncode, output}`` and adds optional
    keys (``error`` plus whatever ``extra`` carries, e.g. ``billing_error`` /
    ``gitea_error`` / ``branch_name``) only when they are present.
    """

    success: bool
    returncode: Optional[int]
    output: str
    error: Optional[str] = None            # set when the engine could not run
    extra: dict = field(default_factory=dict)  # billing_error / gitea_error, etc.

    def as_dict(self) -> dict:
        d = {"success": self.success, "returncode": self.returncode, "output": self.output}
        if self.error:
            d["error"] = self.error
        d.update(self.extra)
        return d


def build_engine_env() -> dict:
    """Return a copy of the environment with HOME/USER/PATH set for the platform user."""
    env = os.environ.copy()
    env.update({
        "HOME": f"/home/{LINUX_USER_INSTALLATION}",
        "USER": LINUX_USER_INSTALLATION,
        "PATH": f"/home/{LINUX_USER_INSTALLATION}/.local/bin:" + env.get("PATH", ""),
    })
    return env


def select_engine_command(prompt: str,
                          agentic_engine: Optional[str] = None,
                          agentic_command: Optional[str] = None):
    """Return ``(cmd_args, engine_label)`` or raise :class:`EngineNotFoundError`.

    Mirrors the exact selection logic in ``genai_routes``: ``deployControlPlan.sh``
    when ``agentic_command`` is set, shai ``-p`` form, else qchat
    ``chat --trust-all-tools``.
    """
    engine = (agentic_engine or AI_ENGINE)
    if agentic_command:
        script = f"/home/{LINUX_USER_INSTALLATION}/{PLTF_FOLDER}/deployControlPlan.sh"
        return [script, agentic_command], "deployControlPlan.sh"
    if engine.lower() == "shai":
        cmd = get_shai_paths()
        if not cmd:
            raise EngineNotFoundError("shai")
        return [cmd, "-p", prompt], "shai"
    cmd = get_qchat_paths()
    if not cmd:
        raise EngineNotFoundError(engine)
    return [cmd, "chat", "--trust-all-tools", prompt], engine


def run_agentic_engine(prompt: str, *, timeout: int,
                       agentic_engine: Optional[str] = None,
                       agentic_command: Optional[str] = None) -> EngineResult:
    """Launch the engine, accumulate stdout+stderr, enforce timeout, return EngineResult.

    Never raises for a timeout or a non-zero exit; it raises only
    :class:`EngineNotFoundError` (which the caller converts to an Error_Payload).
    This is the single place the Popen/kill/accumulate logic lives.
    """
    cmd_args, _label = select_engine_command(prompt, agentic_engine, agentic_command)
    env = build_engine_env()
    try:
        proc = subprocess.Popen(cmd_args, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True, bufsize=1,
                                 env=env, preexec_fn=os.setsid)
    except (OSError, subprocess.SubprocessError) as exc:
        return EngineResult(False, None, "", error=f"failed to start engine: {exc}")

    lines, start = [], time.time()
    timed_out = False
    try:
        for line in iter(proc.stdout.readline, ""):
            clean = _ANSI.sub("", line.rstrip())
            if clean and "Thinking..." not in clean:
                lines.append(clean)
            if time.time() - start > timeout:
                timed_out = True
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                time.sleep(5)
                if proc.poll() is None:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                break
        proc.wait(timeout=TIMEOUT_CLEAN_SHUTDOWN)
    except subprocess.TimeoutExpired:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        proc.returncode = -1

    output = "\n".join(lines)
    if timed_out:
        return EngineResult(False,
                            proc.returncode if proc.returncode is not None else -1,
                            output, error="engine timed out after %ds" % timeout)
    return EngineResult(proc.returncode == 0, proc.returncode, output)
