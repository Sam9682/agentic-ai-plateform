#!/usr/bin/env python3
"""Property test for Decomposition_Planner cycle rejection.

Feature: phase5-obs-supervisor, Property 11: Cycle rejection.

Property 11 (design.md): for any set of Child_Task dependency references that
forms a cycle, the Decomposition_Planner rejects the decomposition and reports
the cycle, returning no partial plan.

This test generates random dependency graphs that are guaranteed to contain at
least one cycle, calls ``decomposition_planner.plan``, and asserts that:

* ``plan`` raises :class:`CycleError` (the decomposition is rejected),
* the raised error carries a non-empty ``cycle`` list (the cycle is reported),
* no plan / partial result is returned (``pytest.raises`` catches the raise, so
  no value escapes).

The planner is a pure function over the spec list, so no live Agent_Worker,
Docker, PostgreSQL, or SSH is needed (R14.2).

Validates: Requirements 8.5

Run directly:
    python3 tests/test_phase5_cycle_rejection.py
Or via pytest:
    pytest tests/test_phase5_cycle_rejection.py
"""
import os
import sys

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.aro.decomposition_planner import (  # noqa: E402
    ChildTaskSpec,
    CycleError,
    plan,
)
from src.aro.scope import Scope  # noqa: E402


# A minimal, valid requested scope. The planner never inspects scope contents
# (cycle rejection is purely topological), so any concrete Scope works.
_SCOPE = Scope(actions=frozenset({"op:*"}), resources=frozenset({"*"}))


def _spec(key: str, depends_on):
    """Build a ChildTaskSpec for ``key`` depending on the given keys."""
    return ChildTaskSpec(
        key=key,
        operation=f"operation-{key}",
        requested_scope=_SCOPE,
        depends_on=tuple(depends_on),
    )


# --------------------------------------------------------------------------- #
# Strategy: a random graph that is GUARANTEED to contain at least one cycle.
#
# Build ``n`` nodes k0..k(n-1). Give each node a (possibly empty) set of
# dependencies drawn only from the other node keys (no self-loops, no unknown
# refs, so the planner reaches cycle detection rather than a ValueError). Then
# force a cycle by picking a length-L subset of distinct nodes and wiring a
# closed ring k_a -> k_b -> ... -> k_a through their ``depends_on`` edges. The
# forced ring makes the overall graph cyclic regardless of the random edges.
# --------------------------------------------------------------------------- #
@st.composite
def cyclic_graphs(draw):
    n = draw(st.integers(min_value=2, max_value=8))
    keys = [f"k{i}" for i in range(n)]

    # Random base edges: each node may depend on any subset of the *other* keys.
    deps = {k: set() for k in keys}
    for k in keys:
        others = [o for o in keys if o != k]
        chosen = draw(
            st.lists(st.sampled_from(others), max_size=len(others), unique=True)
        )
        deps[k].update(chosen)

    # Force at least one cycle over a ring of L distinct nodes (2 <= L <= n).
    ring_len = draw(st.integers(min_value=2, max_value=n))
    ring = draw(
        st.lists(
            st.sampled_from(keys),
            min_size=ring_len,
            max_size=ring_len,
            unique=True,
        )
    )
    # Wire the closed ring: ring[i] depends on ring[i-1], and ring[0] depends on
    # ring[-1], closing the loop so the subgraph cannot drain.
    for i, node in enumerate(ring):
        prev = ring[i - 1]
        deps[node].add(prev)

    # Shuffle declaration order so cycle detection cannot rely on input order.
    order = draw(st.permutations(keys))
    specs = [_spec(k, sorted(deps[k])) for k in order]
    return specs, set(ring)


_PARENT = {"key": "parent", "operation": "root"}


@settings(max_examples=200, deadline=None)
@given(cyclic_graphs())
def test_cyclic_dependency_graph_is_rejected(graph):
    """Feature: phase5-obs-supervisor, Property 11: Cycle rejection.

    Any dependency graph containing a cycle is rejected: ``plan`` raises
    ``CycleError``, the error reports a non-empty cycle, and no partial plan is
    returned.

    Validates: Requirements 8.5
    """
    specs, ring = graph

    with pytest.raises(CycleError) as exc_info:
        # If plan returned a (partial) result instead of raising, pytest.raises
        # would fail the test — so a non-raising "partial plan" is caught here.
        plan(_PARENT, specs)

    err = exc_info.value

    # The cycle is reported.
    assert err.cycle, "CycleError must carry a non-empty cycle path"
    assert isinstance(err.cycle, list)

    # Every reported cycle node is a real child key.
    valid_keys = {s.key for s in specs}
    assert set(err.cycle).issubset(valid_keys)

    # The reported cycle is actually cyclic: it is a closed path whose first and
    # last nodes coincide, and every consecutive edge is a real depends_on edge.
    # The planner reports the path as [a, b, ..., a], so following the edges
    # returns to the start.
    by_key = {s.key: s for s in specs}
    path = err.cycle
    assert len(path) >= 2, "a cycle path spans at least two edges"
    assert path[0] == path[-1], "reported cycle must close back to its start"
    for i in range(len(path) - 1):
        assert path[i + 1] in by_key[path[i]].depends_on, (
            f"reported cycle edge {path[i]} -> {path[i + 1]} is not a real "
            "depends_on edge"
        )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
