"""Signal-bundle builder for the OBS detection pass (Phase 5, Task 2.1).

A pure function that turns a time window of observations/events into the exact
``signals`` dict :func:`src.obs.anomaly_engine.analyze` expects. It reads from
the existing repositories only and **never collects prompts or sensitive
payloads** (R6.1, R6.2) -- the bundle carries behavioral shape, not content.

The builder is a pure function of its inputs: no randomness, no clock beyond the
injected ``now``, and no LLM/ML call (R1.6).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List


@dataclass(frozen=True)
class WindowConfig:
    """Configurable sliding-window / loop-detection parameters (R2.5)."""

    window_seconds: int = 300          # Sliding_Window duration (R2.1, R2.5)
    loop_threshold: int = 5            # Loop_Threshold -> analyze thresholds (R2.5)
    allowlist: tuple = ()              # exempt operation identifiers (R2.4, R2.5)


def build_signal_bundle(
    *,
    observations: List[Dict[str, Any]],
    events: List[Dict[str, Any]],
    allowed_globs: List[str],
    cfg: WindowConfig,
    now: float,
    clock_of: Callable[[Dict[str, Any]], float],
) -> Dict[str, Any]:
    """Build the ``analyze()`` signal bundle from an observation window. Pure.

    DOES include (behavioral shape only):
      commands[]          - operation identifiers in-window, AFTER allowlist filter
      failures            - count of failed attempts in-window
      process_lines[]     - 'comm args' lines from process_summary (command shapes)
      cpu_percent         - latest in-window cpu_percent (or None)
      memory_bytes        - latest in-window memory_bytes (or None)
      requested_actions[] - action identifiers requested in-window
      allowed_globs[]     - the agent's permission globs (passthrough)
      authz_failures      - count of DENY/authz-failure events in-window
      action, resource, decision - latest governance decision context
      frequency           - recurrence count feeding risk_scoring
    DOES NOT include (R6.1/R6.2): prompt text, message bodies, payload values,
      credentials, env values, file contents.

    Sliding window (R2.1, R2.3): only inputs ``x`` with
    ``now - clock_of(x) <= cfg.window_seconds`` contribute. Allowlist filter is
    applied BEFORE counting (R2.4) so an allowlisted operation can never be
    flagged regardless of repetition count.
    """
    def _in_window(item: Dict[str, Any]) -> bool:
        ts = clock_of(item)
        if ts is None:
            return False
        return (now - ts) <= cfg.window_seconds

    in_window_obs = [o for o in (observations or []) if _in_window(o)]
    in_window_events = [e for e in (events or []) if _in_window(e)]

    # --- commands (operation identifiers), allowlist filter BEFORE counting ---
    allowlist = set(cfg.allowlist or ())
    raw_commands: List[str] = []
    for ev in in_window_events:
        op = ev.get("action") or ev.get("operation") or ev.get("command")
        if op:
            raw_commands.append(op)
    commands = [c for c in raw_commands if c not in allowlist]

    # --- process lines (command shapes) from process_summary ----------------
    process_lines: List[str] = []
    for obs in in_window_obs:
        process_lines.extend(_process_lines_of(obs.get("process_summary")))

    # --- latest in-window resource samples ----------------------------------
    cpu_percent = None
    memory_bytes = None
    for obs in in_window_obs:  # observations are oldest-first; take the last seen
        if obs.get("cpu_percent") is not None:
            cpu_percent = obs.get("cpu_percent")
        if obs.get("memory_bytes") is not None:
            memory_bytes = obs.get("memory_bytes")

    # --- governance / authz context from events -----------------------------
    requested_actions: List[str] = []
    failures = 0
    authz_failures = 0
    action = ""
    resource = ""
    decision = "ALLOW"
    for ev in in_window_events:
        req = ev.get("action") or ev.get("operation")
        if req:
            requested_actions.append(req)
        dec = ev.get("decision")
        if dec:
            action = ev.get("action", action) or action
            resource = ev.get("resource", resource) or resource
            decision = dec
            if dec in ("DENY", "QUARANTINE"):
                authz_failures += 1
        if ev.get("authz_failure") or ev.get("decision") == "DENY":
            # counted above for DENY; explicit authz_failure flag also counts
            if ev.get("authz_failure") and ev.get("decision") != "DENY":
                authz_failures += 1
        if ev.get("failed") or ev.get("outcome") == "failure":
            failures += 1

    frequency = max([c for c in Counter(commands).values()] or [0])

    return {
        "commands": commands,
        "failures": failures,
        "process_lines": process_lines,
        "cpu_percent": cpu_percent,
        "memory_bytes": memory_bytes,
        "requested_actions": requested_actions,
        "allowed_globs": list(allowed_globs or []),
        "authz_failures": authz_failures,
        "action": action,
        "resource": resource,
        "decision": decision,
        "frequency": frequency,
    }


def analyze_thresholds(cfg: WindowConfig) -> Dict[str, int]:
    """Threshold passthrough for ``analyze`` (R2.2, R2.5)."""
    return {"repeat_command_threshold": cfg.loop_threshold}


def _process_lines_of(process_summary: Any) -> List[str]:
    """Extract behavioral 'comm args' command-shape lines from a process summary.

    Accepts a list of process dicts (``{"comm": ..., "args": ...}`` or
    ``{"cmdline": ...}``), a list of strings, or a raw string. Never reads
    payload/env/credential values -- command shape only.
    """
    if not process_summary:
        return []
    if isinstance(process_summary, str):
        return [process_summary]
    lines: List[str] = []
    if isinstance(process_summary, dict):
        process_summary = process_summary.get("processes", [])
    for proc in process_summary or []:
        if isinstance(proc, str):
            lines.append(proc)
        elif isinstance(proc, dict):
            cmdline = proc.get("cmdline")
            if cmdline:
                lines.append(cmdline if isinstance(cmdline, str) else " ".join(cmdline))
                continue
            comm = proc.get("comm") or proc.get("name") or ""
            args = proc.get("args") or ""
            if isinstance(args, (list, tuple)):
                args = " ".join(str(a) for a in args)
            line = f"{comm} {args}".strip()
            if line:
                lines.append(line)
    return lines
