#!/usr/bin/env python3
"""Property test for out-of-scope delegated-action denial.

Feature: phase5-obs-supervisor, Property 13.

Task 2.11 added the pure execution-time matcher
``scope.in_scope(scope, action, resource) -> bool`` (``src/aro/scope.py``) used
to deny a delegated action/resource that a Child_Task's effective
Governance_Scope does not cover, before the Phase 3 PDP is consulted. A scope is
authorized iff the action matches some scope action glob AND the resource
matches some scope resource glob under ``fnmatch`` (the same matcher
``anomaly_engine.detect_out_of_scope`` uses).

Property 13 (design.md): *for any* effective scope and *any* action/resource
pair, ``in_scope`` returns True iff the action is covered by some action glob
AND the resource is covered by some resource glob; consequently an action or a
resource outside the scope is denied (returns False).

This test encodes the acceptance criterion as an independent pure oracle
(:func:`oracle`) derived directly from R10.5 — it does NOT call ``in_scope`` —
and asserts the live matcher agrees with the oracle across random scopes and
random action/resource pairs. It also deliberately constructs out-of-scope
tokens (an action outside every action glob, a resource outside every resource
glob) and asserts each is denied. Pure function; no live governance service.

Validates: Requirements 10.5.

Run directly:
    python3 tests/test_phase5_out_of_scope_denial.py
Or via pytest:
    pytest tests/test_phase5_out_of_scope_denial.py
"""
import fnmatch
import os
import sys

from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.aro.scope import Scope, in_scope  # noqa: E402


# --------------------------------------------------------------------------- #
# Independent oracle — a token is covered iff some glob matches it under
# fnmatch; the scope authorizes iff BOTH the action and the resource are
# covered. Derived purely from R10.5, NOT from in_scope.
# --------------------------------------------------------------------------- #
def _covered(token, globs):
    return any(fnmatch.fnmatchcase(token, g) for g in globs)


def oracle(scope, action, resource):
    """Expected :func:`in_scope` result for the given inputs (R10.5)."""
    return _covered(action, scope.actions) and _covered(resource, scope.resources)


# --------------------------------------------------------------------------- #
# Generators — token segments and globs over a small alphabet so collisions
# (both matches and non-matches) occur frequently within the input space.
# --------------------------------------------------------------------------- #
_SEGMENT = st.text(alphabet="abcd:-", min_size=1, max_size=5)


@st.composite
def _glob(draw):
    """A token segment optionally made into a wildcard glob."""
    base = draw(_SEGMENT)
    kind = draw(st.integers(min_value=0, max_value=2))
    if kind == 0:
        return base            # exact token
    if kind == 1:
        return base + "*"      # prefix glob
    return "*" + base          # suffix glob


_globset = st.frozensets(_glob(), min_size=0, max_size=5)
_scopes = st.builds(Scope, actions=_globset, resources=_globset)
_tokens = st.text(alphabet="abcd:-", min_size=1, max_size=6)


# --------------------------------------------------------------------------- #
# Property 13 (iff half) — in_scope agrees with the oracle across random
# scopes and random action/resource pairs.
# --------------------------------------------------------------------------- #
@settings(max_examples=200)
@given(scope=_scopes, action=_tokens, resource=_tokens)
def test_in_scope_matches_oracle(scope, action, resource):
    assert in_scope(scope, action, resource) == oracle(scope, action, resource)


# --------------------------------------------------------------------------- #
# Property 13 (denial half) — a scope with non-empty globs denies any token
# that is outside every glob. We synthesize an out-of-scope action and an
# out-of-scope resource and assert each independently forces denial.
# --------------------------------------------------------------------------- #
def _outside(globs):
    """Return a token matched by none of ``globs``, growing it until unique."""
    candidate = "z"
    while any(fnmatch.fnmatchcase(candidate, g) for g in globs):
        candidate += "z"
    return candidate


@settings(max_examples=200)
@given(scope=_scopes, action=_tokens, resource=_tokens)
def test_out_of_scope_token_is_denied(scope, action, resource):
    # An action outside every action glob => denied regardless of resource.
    out_action = _outside(scope.actions)
    assert in_scope(scope, out_action, resource) is False

    # A resource outside every resource glob => denied regardless of action.
    out_resource = _outside(scope.resources)
    assert in_scope(scope, action, out_resource) is False

    # Both out of scope => denied.
    assert in_scope(scope, out_action, out_resource) is False


if __name__ == "__main__":
    test_in_scope_matches_oracle()
    test_out_of_scope_token_is_denied()
    print("phase5 Property 13 (out-of-scope denial) tests passed")
