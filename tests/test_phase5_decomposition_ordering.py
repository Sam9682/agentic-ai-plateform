#!/usr/bin/env python3
"""Property test for decomposition dependency ordering.

Feature: phase5-obs-supervisor, Property 10.

Task 2.14 added the pure planner
``decomposition_planner.plan(parent, children) -> {"order": [...],
"children": [...]}`` which fans a parent task into dependency-ordered child
tasks via Kahn's topological sort, honoring each ``ChildTaskSpec.depends_on``.

Property 10 (design.md) — *Decomposition dependency ordering*: for any
acyclic ``depends_on`` graph, every child appears in the returned ``order``
*after* all children it depends on. Formally, for each child ``c`` and each
``d in c.depends_on``, ``order.index(d) < order.index(c)``.

This test generates random acyclic DAGs — each child may only depend on
keys of *earlier-generated* children, which guarantees acyclicity by
construction — calls ``plan``, and asserts the topological invariant holds for
every dependency edge. Pure function; no live DB, worker, or service.

Validates: Requirements 8.2, 8.3, 8.4, 14.2.

Run directly:
    python3 tests/test_phase5_decomposition_ordering.py
Or via pytest:
    pytest tests/test_phase5_decomposition_ordering.py
"""
import os
import sys

from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.aro.decomposition_planner import ChildTaskSpec, plan  # noqa: E402
from src.aro.scope import Scope  # noqa: E402


# --------------------------------------------------------------------------- #
# Strategy: a random acyclic DAG of ChildTaskSpec.
#
# Children are generated in a fixed order (child_0, child_1, ...). A child may
# only depend on the keys of children generated BEFORE it, which makes a cycle
# impossible by construction while still exercising arbitrary acyclic shapes
# (chains, diamonds, fan-out/fan-in, isolated nodes).
# --------------------------------------------------------------------------- #
_SIMPLE_SCOPE = Scope(actions=frozenset({"read:*"}), resources=frozenset({"*"}))


@st.composite
def dag(draw):
    """Build a list of ChildTaskSpec forming a random acyclic dependency graph."""
    n = draw(st.integers(min_value=0, max_value=12))
    children = []
    keys = [f"child_{i}" for i in range(n)]
    for i in range(n):
        # Depend only on earlier keys -> guarantees acyclicity.
        earlier = keys[:i]
        if earlier:
            depends_on = tuple(
                draw(
                    st.lists(
                        st.sampled_from(earlier),
                        unique=True,
                        max_size=len(earlier),
                    )
                )
            )
        else:
            depends_on = ()
        children.append(
            ChildTaskSpec(
                key=keys[i],
                operation=f"op_{i}",
                requested_scope=_SIMPLE_SCOPE,
                depends_on=depends_on,
            )
        )
    # Shuffle so declaration order is not already a valid topological order;
    # the planner must derive ordering from depends_on, not input position.
    order_perm = draw(st.permutations(children))
    return list(order_perm)


# --------------------------------------------------------------------------- #
# Property 10 — every child appears after all children it depends on.
# --------------------------------------------------------------------------- #
@settings(max_examples=200)
@given(children=dag())
def test_decomposition_dependency_ordering(children):
    result = plan(parent=object(), children=children)
    order = result["order"]

    # order is a permutation of exactly the child keys.
    assert sorted(order) == sorted(c.key for c in children)

    position = {key: idx for idx, key in enumerate(order)}
    for child in children:
        for dep in child.depends_on:
            assert position[dep] < position[child.key], (
                f"{child.key!r} (index {position[child.key]}) must appear after "
                f"its dependency {dep!r} (index {position[dep]})"
            )


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
