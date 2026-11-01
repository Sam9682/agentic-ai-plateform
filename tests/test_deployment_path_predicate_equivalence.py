#!/usr/bin/env python3
"""Property-based test for deployment-path validation predicate equivalence.

Feature: phase1-foundation-consolidation, Property 2 -- "Deployment-path
validation predicate equivalence". Validates Requirements 4.2, 4.3: the retained
``src/routes/api_routes.py`` handler uses
``is_under_deployments(LINUX_USER_INSTALLATION, path)`` for path-traversal
validation, while the removed ``src/routes/genai_routes.py`` handler used the
inline hardcoded predicate
``path.startswith(f'/home/{user}/deployments/') and '..' not in path``. Removing
the duplicate route is behavior-preserving only if those two predicates yield
the SAME accept/reject decision for every (user, path).

The unit under test is the pure helper ``src.config_postgres.is_under_deployments``.
``tests/conftest.py`` sets ``FLASK_ENV=development`` so importing the config
module does not trigger the Phase 1 production secret fail-fast.
"""
import os
import sys

from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src.config_postgres import is_under_deployments  # noqa: E402


def genai_pred(user, path):
    """The removed genai_routes hardcoded predicate, reproduced verbatim.

    This is the reference oracle: the exact accept/reject logic the deleted
    ``src/routes/genai_routes.py`` handler applied before de-duplication.
    """
    return path.startswith(f'/home/{user}/deployments/') and '..' not in path


# Usernames: realistic username-ish identifiers plus a few edge cases (empty,
# unicode, dots/slashes) so the generated f-string prefix itself varies.
_users = st.one_of(
    st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789_-", min_size=1, max_size=20),
    st.sampled_from(["", "root", "a", "user.name", "a/b", "ünïcödé", "..", "deployments"]),
    st.text(min_size=0, max_size=10),
)

# Fully-arbitrary path text: covers empty strings, partial prefixes, '..'
# anywhere, unicode, control chars, etc. This mostly exercises the reject branch.
_arbitrary_paths = st.text(min_size=0, max_size=60)


@settings(max_examples=300)
@given(user=_users, path=_arbitrary_paths)
def test_predicate_equivalence_arbitrary_paths(user, path):
    """Feature: phase1-foundation-consolidation, Property 2.

    Over arbitrary (user, path), the retained ``is_under_deployments`` helper
    yields the same accept/reject decision as the removed genai predicate.
    Validates: Requirements 4.2, 4.3.
    """
    assert bool(is_under_deployments(user, path)) == bool(genai_pred(user, path))


@settings(max_examples=300)
@given(
    user=_users,
    suffix=st.text(min_size=0, max_size=40),
    # Suffix fragments that may or may not contain '..', so the composed
    # under-prefix path lands on both sides of the traversal check.
    traversal=st.sampled_from(["", "..", "a/../b", "sub/dir", "x..y", "../etc"]),
)
def test_predicate_equivalence_accept_branch(user, suffix, traversal):
    """Feature: phase1-foundation-consolidation, Property 2.

    Compose paths that start with the user's deployments prefix so the accept
    branch is meaningfully exercised (the arbitrary-text strategy almost never
    hits it). The '..' traversal fragment still drives both predicates to the
    reject branch identically. Validates: Requirements 4.2, 4.3.
    """
    path = f'/home/{user}/deployments/{suffix}{traversal}'
    assert bool(is_under_deployments(user, path)) == bool(genai_pred(user, path))
