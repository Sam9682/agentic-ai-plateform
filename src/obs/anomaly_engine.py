"""Rule-based anomaly detection (Task 16). Pure and deterministic.

Each detector is a pure function over a window of recent agent events /
observations, returning zero or more :class:`Anomaly` findings with explainable
evidence. Detectors cover the SRS scenarios: execution loops, excessive retries,
suspicious process creation / privilege escalation / control-socket access,
resource anomalies, and out-of-scope / repeated-authorization-failure behavior.

No LLM is involved; findings are reproducible from the inputs (SRS §5.4, §5.5).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List

from . import risk_scoring


@dataclass
class Anomaly:
    rule_id: str
    severity: str
    evidence: List[str] = field(default_factory=list)
    behavioral_points: int = 0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "evidence": list(self.evidence),
            "behavioral_points": self.behavioral_points,
        }


# Default thresholds (overridable by the caller).
DEFAULTS = {
    "repeat_command_threshold": 5,
    "retry_threshold": 4,
    "authz_failure_threshold": 3,
}

_SUSPICIOUS_PROCESS_TOKENS = ("nc ", "ncat", "/bin/sh", "bash -i", "curl ", "wget ")
_PRIVILEGE_TOKENS = ("sudo", "setuid", "chmod +s", "capsh", "--privileged")
_SOCKET_TOKENS = ("docker.sock", "/var/run/docker.sock", "containerd.sock")


def detect_repeated_commands(commands: List[str], threshold: int = 5) -> List[Anomaly]:
    """Detect a command (or MCP call) repeated >= threshold times (a loop)."""
    out: List[Anomaly] = []
    counts = Counter(commands or [])
    for cmd, n in counts.items():
        if n >= threshold:
            out.append(Anomaly(
                "execution.loop", "MEDIUM",
                [f"command repeated {n} times: {cmd}"], behavioral_points=15,
            ))
    return out


def detect_excessive_retries(failures: int, threshold: int = 4) -> List[Anomaly]:
    if failures >= threshold:
        return [Anomaly("execution.excessive_retries", "MEDIUM",
                        [f"{failures} failed attempts"], behavioral_points=12)]
    return []


def detect_suspicious_processes(process_lines: List[str]) -> List[Anomaly]:
    out: List[Anomaly] = []
    for line in process_lines or []:
        low = line.lower()
        if any(tok in low for tok in _SUSPICIOUS_PROCESS_TOKENS):
            out.append(Anomaly("process.suspicious", "HIGH",
                               [f"suspicious process: {line}"], behavioral_points=25))
        if any(tok in low for tok in _PRIVILEGE_TOKENS):
            out.append(Anomaly("process.privilege_escalation", "HIGH",
                               [f"privilege escalation attempt: {line}"], behavioral_points=30))
        if any(tok in low for tok in _SOCKET_TOKENS):
            out.append(Anomaly("process.control_socket_access", "CRITICAL",
                               [f"control socket access attempt: {line}"], behavioral_points=40))
    return out


def detect_resource_anomaly(cpu_percent: float, memory_bytes: int,
                            cpu_limit: float = 90.0, mem_limit: int = 1 << 30) -> List[Anomaly]:
    out: List[Anomaly] = []
    if cpu_percent is not None and cpu_percent >= cpu_limit:
        out.append(Anomaly("resource.cpu_spike", "MEDIUM",
                           [f"cpu {cpu_percent}% >= {cpu_limit}%"], behavioral_points=10))
    if memory_bytes is not None and memory_bytes >= mem_limit:
        out.append(Anomaly("resource.memory_exhaustion", "MEDIUM",
                           [f"memory {memory_bytes} >= {mem_limit}"], behavioral_points=10))
    return out


def detect_out_of_scope(requested_actions: List[str], allowed_globs: List[str]) -> List[Anomaly]:
    """Detect actions outside the agent's assigned scope (its permission globs)."""
    import fnmatch
    out: List[Anomaly] = []
    for action in requested_actions or []:
        if not any(fnmatch.fnmatchcase(action, g) for g in (allowed_globs or [])):
            out.append(Anomaly("behavior.out_of_scope", "HIGH",
                               [f"action outside assigned scope: {action}"],
                               behavioral_points=20))
    return out


def detect_authz_failures(failures: int, threshold: int = 3) -> List[Anomaly]:
    if failures >= threshold:
        return [Anomaly("behavior.repeated_authz_failure", "HIGH",
                        [f"{failures} authorization failures"], behavioral_points=20)]
    return []


def analyze(signals: Dict[str, Any], thresholds: Dict[str, int] = None) -> Dict[str, Any]:
    """Run all detectors over a signal bundle; return findings + aggregate risk.

    ``signals`` may contain: commands[], failures(int), process_lines[],
    cpu_percent, memory_bytes, requested_actions[], allowed_globs[],
    authz_failures(int), action(str), resource(str), decision(str).
    """
    t = dict(DEFAULTS)
    t.update(thresholds or {})
    anomalies: List[Anomaly] = []
    anomalies += detect_repeated_commands(signals.get("commands", []), t["repeat_command_threshold"])
    anomalies += detect_excessive_retries(signals.get("failures", 0), t["retry_threshold"])
    anomalies += detect_suspicious_processes(signals.get("process_lines", []))
    anomalies += detect_resource_anomaly(signals.get("cpu_percent"), signals.get("memory_bytes"))
    anomalies += detect_out_of_scope(signals.get("requested_actions", []), signals.get("allowed_globs", []))
    anomalies += detect_authz_failures(signals.get("authz_failures", 0), t["authz_failure_threshold"])

    behavioral_points = sum(a.behavioral_points for a in anomalies)
    risk = risk_scoring.score(
        action=signals.get("action", ""),
        resource=signals.get("resource", ""),
        decision=signals.get("decision", "ALLOW"),
        behavioral_points=behavioral_points,
        frequency=max([signals.get("frequency", 0)] +
                      [c for c in Counter(signals.get("commands", [])).values()] or [0]),
    )
    return {
        "anomalies": [a.as_dict() for a in anomalies],
        "risk": risk.as_dict(),
    }
