"""Dependency-ordered task decomposition for the Agent Supervisor (Phase 5, Task 2.14).

Holds the pure planner that fans a parent task into dependency-ordered child
tasks. Mirrors the pure, injectable-collaborator style used elsewhere in the
``aro`` package (e.g. ``event_service``): this module never touches a database,
a worker, or any live service, so it is unit- and property-testable in isolation
(SRS R14.2).

Key guarantees:
* **Topological order (R8.4).** :func:`plan` returns an execution ``order`` via
  Kahn's algorithm so that every child appears after all children it depends on.
* **Cycle rejection (R8.5).** When the ``depends_on`` graph cannot drain, the
  planner raises :class:`CycleError` carrying the cycle path and returns *no*
  partial plan.
* **Determinism.** With no randomness and no clock, the same input always yields
  the same ``order``; ties are broken by the children's declared input order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Tuple

if TYPE_CHECKING:  # pragma: no cover - import kept independent of this module's logic
    from src.aro.scope import Scope


@dataclass(frozen=True)
class ChildTaskSpec:
    """A single sub-task produced by decomposition (R8.2, R8.3).

    ``key`` is the local identifier within the decomposition; ``depends_on`` are
    the keys of the prerequisite children that must complete first.
    """

    key: str
    operation: str
    requested_scope: "Scope"
    depends_on: Tuple[str, ...] = field(default=())


class CycleError(Exception):
    """Raised when the ``depends_on`` graph forms a cycle (R8.5).

    Carries the offending ``cycle`` path so the caller can report it. No partial
    plan is produced when this is raised.
    """

    def __init__(self, cycle: List[str]):
        self.cycle = list(cycle)
        super().__init__(f"dependency cycle detected: {' -> '.join(self.cycle)}")


def plan(parent: Any, children: List[ChildTaskSpec]) -> Dict[str, Any]:
    """Fan ``parent`` into dependency-ordered child tasks. Pure (R8.2, R8.4).

    Returns ``{"order": [key, ...], "children": [...]}`` where ``order`` is a
    topological sort of ``children`` honoring ``depends_on`` (each child after
    every child it depends on). ``children`` is returned reordered to match
    ``order`` for convenient downstream consumption.

    Raises :class:`CycleError` when ``depends_on`` forms a cycle, in which case
    no partial plan is returned (R8.5).
    """
    by_key: Dict[str, ChildTaskSpec] = {}
    for child in children:
        if child.key in by_key:
            raise ValueError(f"duplicate child key: {child.key!r}")
        by_key[child.key] = child

    # Validate dependency references point at real children.
    for child in children:
        for dep in child.depends_on:
            if dep not in by_key:
                raise ValueError(
                    f"child {child.key!r} depends on unknown key {dep!r}"
                )

    # Kahn's algorithm over the depends_on DAG. in_degree counts prerequisites;
    # adjacency maps a prerequisite to the children that depend on it. Input
    # order is preserved for deterministic tie-breaking.
    in_degree: Dict[str, int] = {c.key: 0 for c in children}
    adjacency: Dict[str, List[str]] = {c.key: [] for c in children}
    for child in children:
        for dep in child.depends_on:
            in_degree[child.key] += 1
            adjacency[dep].append(child.key)

    ready: List[str] = [c.key for c in children if in_degree[c.key] == 0]
    order: List[str] = []
    while ready:
        key = ready.pop(0)
        order.append(key)
        for dependent in adjacency[key]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                ready.append(dependent)

    # If the graph did not fully drain, the residual nodes form at least one
    # cycle. Report the cycle path rather than returning a partial plan (R8.5).
    if len(order) != len(children):
        residual = [c.key for c in children if in_degree[c.key] > 0]
        raise CycleError(_extract_cycle(residual, by_key))

    return {
        "order": order,
        "children": [by_key[key] for key in order],
    }


def _extract_cycle(
    residual: List[str], by_key: Dict[str, ChildTaskSpec]
) -> List[str]:
    """Trace a concrete cycle path through the residual (undrained) nodes.

    Walks ``depends_on`` edges restricted to the residual set until a node is
    revisited, then returns the closed cycle path for reporting.
    """
    residual_set = set(residual)
    seen: Dict[str, int] = {}
    path: List[str] = []
    current = residual[0]
    while current not in seen:
        seen[current] = len(path)
        path.append(current)
        next_nodes = [
            dep for dep in by_key[current].depends_on if dep in residual_set
        ]
        if not next_nodes:
            break
        current = next_nodes[0]
    start = seen.get(current, 0)
    return path[start:] + [current]
