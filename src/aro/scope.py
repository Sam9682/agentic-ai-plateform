"""Governance scope inheritance by strict intersection (Phase 5, Task 2.11).

The security core of supervisor delegation: a Child_Task can never gain
permissions its Parent_Task does not already hold. All logic here is pure so it
is unit- and property-testable without a live governance service (R14.4),
mirroring the collaborator-free style of :mod:`event_service`.

Key guarantees:
* **Subset only (R10.2, R10.3).** :func:`scope_intersection` keeps a requested
  glob only when some parent glob covers it, so the effective scope is always a
  subset of the parent — it can narrow or drop, never widen.
* **Out-of-scope exclusion (R10.4).** A requested action/resource glob outside
  every parent glob is dropped from the effective scope.
* **Out-of-scope deny (R10.5).** :func:`in_scope` is the execution-time matcher
  used to deny a delegated action/resource that the effective scope does not
  cover, before the Phase 3 PDP is consulted — the same ``fnmatch`` matcher
  ``anomaly_engine.detect_out_of_scope`` uses.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from typing import FrozenSet, Iterable


@dataclass(frozen=True)
class Scope:
    """An authorization scope expressed as action and resource globs.

    Both fields are glob sets, e.g. ``actions={"deploy:*", "read:logs"}`` and
    ``resources={"prod-*", "staging-db"}``. Frozen so scopes are hashable and
    safe to embed in a child's immutable ``policy_context``.
    """

    actions: FrozenSet[str]
    resources: FrozenSet[str]


def glob_covers(parent_glob: str, requested_glob: str) -> bool:
    """True iff ``requested_glob`` falls within ``parent_glob``'s authority.

    Covered when the two are identical or when the parent glob matches the
    requested token under ``fnmatch`` (the same matcher
    ``anomaly_engine.detect_out_of_scope`` uses). A requested glob the parent
    does not cover is never admitted.
    """
    return parent_glob == requested_glob or fnmatch.fnmatchcase(
        requested_glob, parent_glob
    )


def scope_intersection(parent: Scope, child_requested: Scope) -> Scope:
    """Child effective scope = parent ∩ child_requested (R10.2, R10.3).

    For each requested action glob ``ra`` it is kept iff some parent action glob
    ``pa`` satisfies :func:`glob_covers`; resources are filtered the same way. A
    requested glob outside every parent glob is EXCLUDED (R10.4) — never
    widened. The result is therefore always a subset of ``parent`` (R10.3): it
    can only ever drop or narrow, never add a glob the parent lacks.
    """

    def covered(requested: Iterable[str], parent_globs: FrozenSet[str]) -> FrozenSet[str]:
        return frozenset(
            r for r in requested if any(glob_covers(p, r) for p in parent_globs)
        )

    return Scope(
        actions=covered(child_requested.actions, parent.actions),
        resources=covered(child_requested.resources, parent.resources),
    )


def in_scope(scope: Scope, action: str, resource: str) -> bool:
    """True iff ``action`` and ``resource`` are both within ``scope`` (R10.5).

    Used at execution time to deny a delegated action/resource that the
    effective scope does not cover, before the Phase 3 PDP is consulted.
    """
    return any(fnmatch.fnmatchcase(action, g) for g in scope.actions) and any(
        fnmatch.fnmatchcase(resource, g) for g in scope.resources
    )
