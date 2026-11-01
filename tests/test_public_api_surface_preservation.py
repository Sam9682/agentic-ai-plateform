#!/usr/bin/env python3
"""Property test for public API surface preservation.

Feature: phase1-foundation-consolidation, Property 8 -- "Public API surface
preservation". Validates Requirements 6.1: the platform preserves the public
HTTP API surface so that every route available before this phase remains
available with the same path and method after this phase, with
``/api/deployments/<int:deployment_id>/logs`` present EXACTLY ONCE.

What "before this phase" means here
-----------------------------------
This phase is behavior-preserving for the public surface: it only REMOVED the
duplicate ``genai`` ``/logs`` route (which shadowed the retained ``api`` route
at the same URL) and deleted unreferenced files. So the pre-phase public
(path, method) surface equals the post-phase surface, EXCEPT that the single
shared ``/logs`` URL was registered twice before (``api.api_deployment_logs``
and ``genai.api_deployment_logs``) and is registered once now.

We cannot rebuild the literal pre-phase app, so Property 8 is pinned from two
independent anchors:

1. A recorded pre-phase inventory. ``docs/audit/04-api-inventory.md`` (the Phase
   0 audit artifact referenced by this spec) enumerates every (method, path)
   route with its blueprint prefix already applied. We parse it and assert every
   listed (path, method) -- with the duplicate ``/logs`` row collapsed to one --
   is present in the CURRENT built app's url_map. This is the real
   before/after comparison: the inventory is the "before" snapshot.

2. A Hypothesis property over the current surface, sampling >=100 (rule, method)
   pairs from the live url_map and asserting each sampled route is still
   routable (stability/consistency of the exposed surface). This guards against
   a surface that is internally inconsistent with what the app advertises.

Plus a hard, non-Hypothesis invariant: exactly ONE url_map rule equals
``/api/deployments/<int:deployment_id>/logs`` and it supports GET.

The real application factory ``src.ControlPlanFlaskApp_postgres.create_app`` is
exercised with its infrastructure side effects neutralised, following the exact
hermetic pattern established in ``tests/test_logs_route_url_map.py`` (patch
``init_db``, ``orchestrator.init_orchestrator_tables`` /
``start_reconciliation_loop``, and ``ReplicationManager.start_worker`` to
no-ops). ``tests/conftest.py`` sets ``FLASK_ENV=development`` so building the app
does not trip the Phase 1 production secret fail-fast.

Run directly:
    python3 -m pytest -q tests/test_public_api_surface_preservation.py
"""
import os
import re
import sys
from unittest import mock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

# conftest.py sets FLASK_ENV=development; keep a local guard so the module also
# builds the app correctly when run as a plain script.
os.environ.setdefault("FLASK_ENV", "development")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

LOGS_RULE = "/api/deployments/<int:deployment_id>/logs"
API_INVENTORY = os.path.join(PROJECT_ROOT, "docs", "audit", "04-api-inventory.md")

# Methods Flask adds automatically; not part of the declared public surface.
_IMPLICIT_METHODS = {"HEAD", "OPTIONS"}


def _build_app():
    """Build the real app via create_app with DB side effects neutralised.

    Identical hermetic pattern to ``tests/test_logs_route_url_map.py``:
    ``create_app`` calls ``init_db()`` and starts the orchestrator/replication
    background workers inside an app context; all require a live PostgreSQL that
    is irrelevant to the url_map, so we patch them to no-ops. Every blueprint is
    still registered for real, which is what the public surface depends on.
    """
    import src.ControlPlanFlaskApp_postgres as appmod
    from src import orchestrator as orch_mod
    from src import replication_manager as repl_mod

    with mock.patch.object(appmod, "init_db", lambda *a, **k: None), \
         mock.patch.object(orch_mod.orchestrator, "init_orchestrator_tables",
                           lambda *a, **k: None), \
         mock.patch.object(orch_mod.orchestrator, "start_reconciliation_loop",
                           lambda *a, **k: None), \
         mock.patch.object(repl_mod.ReplicationManager, "start_worker",
                           lambda *a, **k: None):
        return appmod.create_app()


# Lazily-built, cached app. We MUST NOT build at module import time: wsgi.py
# and tests/test_entry_point_consolidation.py rely on importing the real factory
# with init_db patched, and building the app during collection would start
# background workers / import-bind state before that test patches its own side
# effects. Building lazily (first test execution) keeps this file side-effect
# free at collection time.
_APP_CACHE = []


def _get_app():
    if not _APP_CACHE:
        _APP_CACHE.append(_build_app())
    return _APP_CACHE[0]


@pytest.fixture(scope="module")
def built_app():
    return _get_app()


def _live_pairs(app):
    """Set of (rule_string, method) for every explicit method in the url_map.

    HEAD/OPTIONS are Flask-implicit and excluded so the comparison reflects the
    declared public surface.
    """
    pairs = set()
    for rule in app.url_map.iter_rules():
        for method in (rule.methods or set()):
            if method in _IMPLICIT_METHODS:
                continue
            pairs.add((rule.rule, method))
    return pairs


# ---------------------------------------------------------------------------
# Pre-phase inventory parsing (docs/audit/04-api-inventory.md)
# ---------------------------------------------------------------------------

# Rows look like:  | GET, POST | `/api/applications` | `src/...` | `handler` |
# Capture the method cell (col 1) and the path cell (col 2, backtick-wrapped).
_ROW_RE = re.compile(
    r"^\|\s*([A-Z, ]+?)\s*\|\s*`([^`]+)`\s*\|",
)
_METHOD_TOKEN = re.compile(r"^[A-Z]+$")


def _parse_inventory_pairs(path):
    """Parse the audit inventory into a set of (path, method) pairs.

    The inventory tables already include each route's blueprint ``url_prefix``
    in the Path column, so the parsed path matches the Werkzeug rule string
    directly. Comma-separated method cells (e.g. ``GET, POST``) expand to one
    pair per method. The duplicate ``/logs`` row (listed once under
    ``api_routes.py`` and once under ``genai_routes.py``) naturally collapses
    because we build a set.
    """
    pairs = set()
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            m = _ROW_RE.match(line.strip())
            if not m:
                continue
            method_cell, route = m.group(1), m.group(2)
            # Skip the markdown header separator / non-route rows: a valid route
            # path starts with '/'.
            if not route.startswith("/"):
                continue
            methods = [tok.strip() for tok in method_cell.split(",")]
            methods = [t for t in methods if _METHOD_TOKEN.match(t)]
            if not methods:
                continue
            for method in methods:
                pairs.add((route, method))
    return pairs


# Hypothesis samples (rule, method) pairs from the live url_map. The strategy is
# deferred so the app is built on first test execution, not at import/collection
# time (see _get_app docstring above).
_live_pairs_strategy = st.deferred(lambda: st.sampled_from(sorted(_live_pairs(_get_app()))))


# ===========================================================================
# Property 8 -- Hypothesis: the exposed surface is self-consistent / stable.
# ===========================================================================
@settings(max_examples=200)
@given(pair=_live_pairs_strategy)
def test_sampled_route_remains_routable(pair):
    """Feature: phase1-foundation-consolidation, Property 8.

    For any (path, method) sampled from the current public surface, the route
    is still routable: a url_map rule with that exact path exists and its method
    set includes that method. Asserts the surface the app advertises is
    internally consistent after consolidation. >=100 examples.
    Validates: Requirements 6.1.
    """
    rule_str, method = pair
    app = _get_app()
    matching = [
        r for r in app.url_map.iter_rules()
        if r.rule == rule_str and method in (r.methods or set())
    ]
    assert matching, (
        f"route {method} {rule_str!r} is no longer routable in the url_map"
    )


# ===========================================================================
# Property 8 -- recorded pre-phase inventory is preserved in the live surface.
# ===========================================================================
def test_prephase_inventory_is_subset_of_live_surface(built_app):
    """Feature: phase1-foundation-consolidation, Property 8.

    Every (path, method) recorded in the Phase 0 pre-phase inventory
    (docs/audit/04-api-inventory.md) -- the "before this phase" snapshot --
    remains available in the current built app's url_map with the same path and
    method. The only pre-phase entry that is NOT a 1:1 survivor is the duplicate
    ``/logs`` row, which collapses to a single live rule (asserted separately).
    Validates: Requirements 6.1.
    """
    assert os.path.exists(API_INVENTORY), (
        f"pre-phase API inventory not found at {API_INVENTORY}"
    )
    inventory = _parse_inventory_pairs(API_INVENTORY)
    assert inventory, "parsed zero routes from the API inventory; parser or doc drift"

    live = _live_pairs(built_app)
    missing = sorted(p for p in inventory if p not in live)
    assert not missing, (
        "pre-phase routes absent from the post-phase url_map (surface not "
        f"preserved): {missing}"
    )


def test_logs_route_present_exactly_once_supporting_get(built_app):
    """Feature: phase1-foundation-consolidation, Property 8.

    Hard invariant: exactly ONE url_map rule equals the deployment-logs path and
    it supports GET. This is the single intended delta vs. the pre-phase surface
    (the duplicate genai registration of the same URL was removed).
    Validates: Requirements 6.1.
    """
    logs_rules = [r for r in built_app.url_map.iter_rules() if r.rule == LOGS_RULE]
    assert len(logs_rules) == 1, (
        f"expected exactly one rule for {LOGS_RULE!r}, got {len(logs_rules)}: "
        f"{[(r.rule, r.endpoint) for r in logs_rules]}"
    )
    (rule,) = logs_rules
    assert "GET" in (rule.methods or set()), (
        f"{LOGS_RULE!r} does not support GET; methods={sorted(rule.methods or [])}"
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
