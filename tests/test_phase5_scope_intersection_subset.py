#!/usr/bin/env python3
"""Property test for supervisor scope intersection subset/exclusion.

Feature: phase5-obs-supervisor, Property 12

Property 12: Scope intersection is a subset with out-of-scope exclusion.
The child effective scope computed by ``scope_intersection`` is always a subset
of the parent scope (never a superset), and every requested glob that is not
covered by some parent glob is excluded from the effective scope.

Validates: Requirements 10.2, 10.3, 10.4, 14.4

Run directly:
    .venv/bin/python -m pytest tests/test_phase5_scope_intersection_subset.py -q
"""
import os
import sys

from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.aro.scope import Scope, glob_covers, scope_intersection  # noqa: E402

# Token atoms kept small so random parent globs actually cover some requested
# globs (otherwise nearly every example would exercise only the exclusion path).
_ATOMS = st.sampled_from(["deploy", "read", "write", "logs", "prod", "staging", "db", "x", "y"])


def _literal_globs():
    """Plain (non-wildcard) glob tokens like ``deploy:logs`` or ``prod-db``."""
    return st.lists(_ATOMS, min_size=1, max_size=3).map(lambda parts: ":".join(parts))


def _wildcard_globs():
    """Globs that may carry a trailing ``*`` so parents can cover many children."""
    return st.builds(
        lambda base, star: base + ("*" if star else ""),
        st.lists(_ATOMS, min_size=1, max_size=2).map(lambda parts: ":".join(parts)),
        st.booleans(),
    )


def _glob_sets():
    return st.frozensets(st.one_of(_literal_globs(), _wildcard_globs()), min_size=0, max_size=6)


def _scopes():
    return st.builds(Scope, actions=_glob_sets(), resources=_glob_sets())


@settings(max_examples=200)
@given(parent=_scopes(), child=_scopes())
def test_effective_scope_is_subset_with_exclusion(parent, child):
    """Effective ⊆ parent, and uncovered requested globs are excluded."""
    effective = scope_intersection(parent, child)

    # R10.3 / R10.2: the effective scope grants no more authority than the
    # parent. Every effective glob must be covered by some parent glob, so the
    # effective scope can only narrow or drop authority, never widen it. (Note
    # the effective glob is the requested token, e.g. ``read`` admitted under a
    # parent ``read*``; it need not be a literal member of the parent set, only
    # within the parent's authority.)
    for eff in effective.actions:
        assert any(glob_covers(p, eff) for p in parent.actions), (
            f"effective action {eff!r} not covered by any parent action glob {parent.actions}"
        )
    for eff in effective.resources:
        assert any(glob_covers(p, eff) for p in parent.resources), (
            f"effective resource {eff!r} not covered by any parent resource glob {parent.resources}"
        )

    # R10.4: any requested glob not covered by some parent glob is excluded.
    for req in child.actions:
        covered = any(glob_covers(p, req) for p in parent.actions)
        if not covered:
            assert req not in effective.actions, (
                f"uncovered requested action {req!r} leaked into effective scope"
            )
    for req in child.resources:
        covered = any(glob_covers(p, req) for p in parent.resources)
        if not covered:
            assert req not in effective.resources, (
                f"uncovered requested resource {req!r} leaked into effective scope"
            )

    # Completeness of the kept set: a requested glob that the parent holds
    # verbatim must survive the intersection (subset is never over-narrowed to
    # the point of dropping an exact parent match).
    for req in child.actions & parent.actions:
        assert req in effective.actions
    for req in child.resources & parent.resources:
        assert req in effective.resources
