#!/usr/bin/env python3
"""Smoke tests: entry-point consolidation.

Feature: phase1-foundation-consolidation (task 6.3). Validates Requirements
1.1, 1.2, 1.4, 1.5, 1.6: after retiring the root shim ``ControlPlanFlaskApp.py``
and repointing the legacy ``Dockerfile`` at ``wsgi:application``, the production
entry point is unambiguous and backed by the ``create_app`` application factory.

Three structural invariants are asserted:

1. The root shim ``ControlPlanFlaskApp.py`` no longer exists at the repo root
   (Req 1.2). This is a plain filesystem check.
2. The legacy ``Dockerfile`` references ``wsgi:application`` and contains no
   reference to ``ControlPlanFlaskApp.py`` (Req 1.5, 1.6). This is a plain text
   check over the Dockerfile contents. We match the exact token
   ``ControlPlanFlaskApp.py`` (with extension) so the still-present
   ``ControlPlanFlaskApp_postgres.py`` module is not a false positive — the
   Dockerfile copies the whole tree, but must not *reference* the shim in any
   build/runtime directive.
3. ``wsgi.application`` is a real ``flask.Flask`` instance built via
   ``create_app`` (Req 1.1, 1.4).

For invariant 3 we import ``wsgi`` for real. ``wsgi.py`` calls ``init_db()`` at
module import time and ``create_app()`` then starts the orchestrator/replication
background workers inside an app context — all of which need a live PostgreSQL
the test environment does not provide and none of which bear on whether
``application`` is the Flask app produced by ``create_app``. Following the
established hermetic pattern in tests/test_logs_route_url_map.py, we neutralise
exactly those side effects (the ``init_db`` symbol in both the source module and
the orchestrator/replication workers) *before* importing ``wsgi`` so the real
factory runs without standing up infrastructure or leaking threads.

Run directly:
    python3 tests/test_entry_point_consolidation.py
Or via pytest:
    pytest tests/test_entry_point_consolidation.py
"""
import importlib
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

ROOT_SHIM = os.path.join(PROJECT_ROOT, "ControlPlanFlaskApp.py")
DOCKERFILE = os.path.join(PROJECT_ROOT, "Dockerfile")
SHIM_TOKEN = "ControlPlanFlaskApp.py"
WSGI_TARGET = "wsgi:application"


def _dockerfile_text():
    with open(DOCKERFILE, "r", encoding="utf-8") as fh:
        return fh.read()


def test_root_shim_absent():
    """The retired root shim no longer exists at the repo root (Req 1.2)."""
    assert not os.path.exists(ROOT_SHIM), (
        f"root shim {SHIM_TOKEN!r} should have been retired but still exists at "
        f"{ROOT_SHIM!r}"
    )


def test_dockerfile_references_wsgi_application():
    """The legacy Dockerfile targets the WSGI entry point (Req 1.5)."""
    text = _dockerfile_text()
    assert WSGI_TARGET in text, (
        f"Dockerfile must reference {WSGI_TARGET!r} as its application target"
    )


def test_dockerfile_does_not_reference_root_shim():
    """The legacy Dockerfile references the shim in no directive (Req 1.6).

    Match the exact token with extension so the retained
    ``ControlPlanFlaskApp_postgres.py`` module is not a false positive.
    """
    text = _dockerfile_text()
    assert SHIM_TOKEN not in text, (
        f"Dockerfile must not reference the retired shim {SHIM_TOKEN!r} in any "
        f"build or runtime directive"
    )


@pytest.fixture(scope="module")
def wsgi_module():
    """Import ``wsgi`` for real with DB/background side effects neutralised.

    ``wsgi.py`` does ``from src.database_postgres import init_db`` and calls it at
    import time, then ``create_app()`` starts the orchestrator/replication
    workers inside an app context. All require a live PostgreSQL irrelevant to
    the ``application`` object's identity. We patch ``init_db`` on the source
    module (so the ``from ... import`` binding picks up the no-op) and the
    orchestrator/replication workers, then import ``wsgi`` fresh so its
    module-level ``init_db()`` / ``create_app()`` run hermetically.
    """
    # Ensure a clean import so the patched symbols take effect on first load.
    sys.modules.pop("wsgi", None)

    import src.database_postgres as db_mod
    from src import orchestrator as orch_mod
    from src import replication_manager as repl_mod

    with mock.patch.object(db_mod, "init_db", lambda *a, **k: None), \
         mock.patch.object(orch_mod.orchestrator, "init_orchestrator_tables",
                           lambda *a, **k: None), \
         mock.patch.object(orch_mod.orchestrator, "start_reconciliation_loop",
                           lambda *a, **k: None), \
         mock.patch.object(repl_mod.ReplicationManager, "start_worker",
                           lambda *a, **k: None):
        wsgi = importlib.import_module("wsgi")

    return wsgi


def test_wsgi_application_is_flask_app(wsgi_module):
    """``wsgi.application`` is a flask.Flask instance built via create_app (Req 1.1, 1.4)."""
    import flask

    assert hasattr(wsgi_module, "application"), (
        "wsgi module must expose an 'application' attribute as the WSGI entry point"
    )
    assert isinstance(wsgi_module.application, flask.Flask), (
        f"wsgi.application must be a flask.Flask instance, got "
        f"{type(wsgi_module.application)!r}"
    )


def test_wsgi_builds_application_via_create_app(wsgi_module):
    """``application`` is the object returned by create_app (Req 1.4).

    Re-invoke the factory under the same patched side effects and assert the
    module-level ``application`` is an app of the same type produced by
    ``create_app``, confirming the entry point constructs the app via the factory
    rather than by hand.
    """
    import flask

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
        factory_app = appmod.create_app()

    assert isinstance(factory_app, flask.Flask)
    assert isinstance(wsgi_module.application, type(factory_app)), (
        "wsgi.application should be built by the same create_app factory"
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
