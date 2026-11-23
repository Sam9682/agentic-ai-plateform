"""Containment adapter contract (ABF Phase 2).

A containment adapter performs the *runtime* side of a containment decision
(stop, pause, network isolation) for one runtime kind. Each adapter declares
its capabilities explicitly; an action it cannot perform returns
``supported=False`` instead of pretending (spec: no fake functionality).

The control-plane side of containment (QUARANTINED status, PDP refusal, token
and credential revocation) does not depend on an adapter and always applies.

Adapters build commands and hand them to an injected ``run(server_ip, argv)``
executor (in production the hardened SSH executor used by
``aro.execution_manager``). Arguments are passed as an argv list, never through
a shell string, and container references are validated.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Dict, FrozenSet, List, Optional, Sequence

STOP = "stop"
PAUSE = "pause"
NETWORK_ISOLATE = "network_isolate"
ALL_CAPABILITIES = frozenset({STOP, PAUSE, NETWORK_ISOLATE})

_CONTAINER_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


@dataclass
class ContainmentResult:
    action: str
    supported: bool
    performed: bool
    detail: str = ""
    commands: List[List[str]] = field(default_factory=list)

    def as_dict(self) -> Dict[str, object]:
        return {"action": self.action, "supported": self.supported,
                "performed": self.performed, "detail": self.detail}


Runner = Callable[[str, Sequence[str]], int]


class ContainmentAdapter:
    kind = "abstract"
    capabilities: FrozenSet[str] = frozenset()

    def __init__(self, run: Optional[Runner] = None):
        self._run = run

    def contain(self, action: str, *, server_ip: Optional[str],
                container_ref: Optional[str]) -> ContainmentResult:
        if action not in self.capabilities:
            return ContainmentResult(action, False, False,
                                     f"{self.kind} adapter does not support {action}")
        if not container_ref or not _CONTAINER_REF.match(container_ref):
            return ContainmentResult(action, True, False, "invalid or missing container reference")
        if not server_ip:
            return ContainmentResult(action, True, False, "runtime location unknown")
        commands = self.commands(action, container_ref)
        if self._run is None:
            return ContainmentResult(action, True, False, "no executor configured", commands)
        for argv in commands:
            try:
                rc = self._run(server_ip, argv)
            except Exception as exc:  # noqa: BLE001
                return ContainmentResult(action, True, False,
                                         f"executor error: {type(exc).__name__}", commands)
            if rc != 0:
                return ContainmentResult(action, True, False, f"command exited {rc}", commands)
        return ContainmentResult(action, True, True, "done", commands)

    def commands(self, action: str, container_ref: str) -> List[List[str]]:
        raise NotImplementedError


class NoopContainment(ContainmentAdapter):
    """For runtimes the platform cannot reach. Declares no capability."""
    kind = "noop"
    capabilities = frozenset()

    def commands(self, action, container_ref):  # pragma: no cover - never reached
        return []


class DockerContainment(ContainmentAdapter):
    kind = "docker"
    capabilities = ALL_CAPABILITIES
    binary = "docker"

    def commands(self, action, container_ref):
        b = self.binary
        if action == STOP:
            return [[b, "stop", "--time", "10", container_ref]]
        if action == PAUSE:
            return [[b, "pause", container_ref]]
        if action == NETWORK_ISOLATE:
            # Disconnect from every network, keep the container for forensics.
            return [[b, "network", "disconnect", "--force", "bridge", container_ref]]
        raise ValueError(action)


class KataContainment(DockerContainment):
    """Kata containers driven through the same OCI CLI; pause is not supported
    by every Kata hypervisor, so it is not declared."""
    kind = "kata"
    capabilities = frozenset({STOP, NETWORK_ISOLATE})


ADAPTERS = {"noop": NoopContainment, "docker": DockerContainment, "kata": KataContainment}


def adapter_for(kind: Optional[str], run: Optional[Runner] = None) -> ContainmentAdapter:
    return ADAPTERS.get((kind or "noop").lower(), NoopContainment)(run)
