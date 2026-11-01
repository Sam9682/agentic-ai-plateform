#!/usr/bin/env python3
"""Example test: the built app's url_map has a single /logs rule.

Feature: phase1-foundation-consolidation (task 4.4). Validates Requirements 4.1
and 4.4: after de-duplicating the shadowed deployment-logs route, the Flask
application built by ``create_app`` exposes
``/api/deployments/<int:deployment_id>/logs`` exactly once, bound to the
``api_routes`` definition (endpoint ``api.api_deployment_logs``), and the removed
``genai`` duplicate (endpoint ``genai.api_deployment_logs``) is absent from the
whole url_map.

The real application factory ``src.ControlPlanFlaskApp_postgres.create_app`` is
exercised so the assertion reflects actual blueprint registration, not a
hand-rolled app. The factory's only hard external dependency for *building* the
url_map is the ``init_db()`` call (and the orchestrator/replication background
workers) it runs inside ``app.app_context()``; those need a live PostgreSQL and
are irrelevant to the route map. Following the established pattern in this repo
of stubbing infrastructure side effects (e.g. ``StubDbManager`` in
tests/test_traefik_sync.py), we neutralise exactly those side effects so the
factory runs hermetically while every blueprint is registered for real.

Run directly:
    python3 tests/test_logs_route_url_map.py
Or via pytest:
    pytest tests/test_logs_route_url_map.py
"""
import os
import sys
from unittest import mock

import pytest

# conftest.py sets FLASK_ENV=development; keep a local guard so the module also
# builds the app correctly when run as a plain script.
os.environ.setdefault("FLASK_ENV", "development")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

LOGS_RULE = "/api/deployments/<int:deployment_id>/logs"
API_ENDPOINT = "api.api_deployment_logs"
GENAI_ENDPOINT = "genai.api_deployment_logs"


@pytest.fixture(scope="module")
def built_app():
    """Build the real app via create_app with DB side effects neutralised.

    ``create_app`` calls ``init_db()`` and starts the orchestrator/replication
    background workers inside an app context; all of those require a live
    PostgreSQL that the test environment does not provide and that has no bearing
    on the url_map. We patch them to no-ops so the factory runs its real
    blueprint registration (which is what Requirements 4.1/4.4 constrain) without
    standing up infrastructure or leaking background threads.
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
        app = appmod.create_app()

    return app


def _logs_rules(app):
    return [r for r in app.url_map.iter_rules() if r.rule == LOGS_RULE]


def test_logs_route_defined_exactly_once(built_app):
    """Exactly one url_map rule matches the deployment-logs path (Req 4.1)."""
    matches = _logs_rules(built_app)
    assert len(matches) == 1, (
        f"expected exactly one rule for {LOGS_RULE!r}, got {len(matches)}: "
        f"{[(r.rule, r.endpoint) for r in matches]}"
    )


def test_logs_route_endpoint_is_api_routes(built_app):
    """The single /logs rule is the api_routes definition (Req 4.1)."""
    (rule,) = _logs_rules(built_app)
    assert rule.rule == LOGS_RULE
    assert rule.endpoint == API_ENDPOINT, (
        f"expected endpoint {API_ENDPOINT!r}, got {rule.endpoint!r}"
    )


def test_no_genai_logs_endpoint_anywhere(built_app):
    """The removed genai duplicate endpoint is absent from the whole map (Req 4.4)."""
    endpoints = {r.endpoint for r in built_app.url_map.iter_rules()}
    assert GENAI_ENDPOINT not in endpoints, (
        f"unexpected {GENAI_ENDPOINT!r} still present in url_map"
    )
    # Sanity: the retained endpoint is the one present.
    assert API_ENDPOINT in endpoints


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
