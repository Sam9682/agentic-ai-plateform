"""Pure agent lifecycle state graph (Task 7).

Encodes the SRS lifecycle as an explicit transition graph so the lifecycle
service can validate every state change and reject illegal transitions. Kept
pure (no DB/Flask) for property testing.

States:
    REGISTERED -> INSTALLING -> INSTALLED -> CONFIGURING -> READY
    READY -> STARTING -> RUNNING -> STOPPING -> STOPPED
    STOPPED -> STARTING (restart)
Terminal/exceptional: FAILED, UNHEALTHY, QUARANTINED, TERMINATED.
Most states may transition to FAILED; RUNNING/READY may become UNHEALTHY; any
non-terminal state may be QUARANTINED (containment) or TERMINATED (delete).
"""

from __future__ import annotations

from typing import Dict, FrozenSet, Optional, Set

REGISTERED = "REGISTERED"
INSTALLING = "INSTALLING"
INSTALLED = "INSTALLED"
CONFIGURING = "CONFIGURING"
READY = "READY"
STARTING = "STARTING"
RUNNING = "RUNNING"
STOPPING = "STOPPING"
STOPPED = "STOPPED"
FAILED = "FAILED"
UNHEALTHY = "UNHEALTHY"
QUARANTINED = "QUARANTINED"
TERMINATED = "TERMINATED"

ALL_STATES: FrozenSet[str] = frozenset({
    REGISTERED, INSTALLING, INSTALLED, CONFIGURING, READY,
    STARTING, RUNNING, STOPPING, STOPPED,
    FAILED, UNHEALTHY, QUARANTINED, TERMINATED,
})

# Terminal states: no outgoing transitions (TERMINATED), or only re-entry via
# explicit recovery flows handled elsewhere.
TERMINAL_STATES: FrozenSet[str] = frozenset({TERMINATED})

# Base happy-path transitions.
_BASE: Dict[str, Set[str]] = {
    REGISTERED: {INSTALLING},
    INSTALLING: {INSTALLED, FAILED},
    INSTALLED: {CONFIGURING, FAILED},
    CONFIGURING: {READY, FAILED},
    READY: {STARTING, FAILED, UNHEALTHY},
    STARTING: {RUNNING, FAILED},
    RUNNING: {STOPPING, UNHEALTHY, FAILED},
    STOPPING: {STOPPED, FAILED},
    STOPPED: {STARTING},  # restart
    FAILED: {INSTALLING, STARTING},  # allow recovery attempts
    UNHEALTHY: {STOPPING, RUNNING},  # recover or shut down
    QUARANTINED: {READY},  # release-only exit (Req 1.1); stays out of _CONTAINMENT_SOURCES so READY is the sole legal target
    TERMINATED: set(),
}

# Any non-terminal state may be quarantined (containment) or terminated (delete).
_CONTAINMENT_SOURCES = ALL_STATES - {QUARANTINED, TERMINATED}


def allowed_transitions(state: str) -> FrozenSet[str]:
    """Return the set of states reachable in one step from ``state``."""
    if state not in ALL_STATES:
        return frozenset()
    targets = set(_BASE.get(state, set()))
    if state in _CONTAINMENT_SOURCES:
        targets.add(QUARANTINED)
        targets.add(TERMINATED)
    return frozenset(targets)


def can_transition(from_state: str, to_state: str) -> bool:
    """Return True when ``from_state`` -> ``to_state`` is a legal transition."""
    return to_state in allowed_transitions(from_state)


def is_terminal(state: str) -> bool:
    return state in TERMINAL_STATES


def reconcile_health(status: str, healthy: bool) -> Optional[str]:
    """Decide the next lifecycle state from a health probe result.

    Pure decision function (no side effects) consumed by the lifecycle
    service's health-reconcile step:

    * RUNNING + unhealthy  -> UNHEALTHY  (agent has degraded)
    * UNHEALTHY + healthy  -> RUNNING    (agent has recovered)
    * anything else        -> None       (no transition)
    """
    if status == RUNNING and not healthy:
        return UNHEALTHY
    if status == UNHEALTHY and healthy:
        return RUNNING
    return None
