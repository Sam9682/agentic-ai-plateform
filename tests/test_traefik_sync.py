#!/usr/bin/env python3
"""Property test for Traefik sync reconciliation and idempotence.

Feature: nginx-to-traefik-migration, Property 7: Sync reconciles the route set
to exactly the database, idempotently.

For any set of applications recorded in the database, after
``src.nginx_manager.sync_all_locations(db_manager)`` the set of active per-app
route files (``app-*.yml``) equals exactly that DB set (one
``app-{user}-{app}.yml`` per DB app, and none for non-DB apps), and running
``sync_all_locations`` a second time against the same database produces the same
set. Pre-existing stale ``app-*.yml`` files are removed, and the non-app
dynamic files (``tls.yml`` / ``secondary-domains.yml``) are left untouched.

**Validates: Requirements 8.4**

Run directly:
    python3 tests/test_traefik_sync.py
Or via pytest:
    pytest tests/test_traefik_sync.py
"""
import glob
import os
import shutil
import sys
import tempfile

from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src import nginx_manager  # noqa: E402


class StubDbManager:
    """Minimal stand-in for the real db_manager.

    ``sync_all_locations`` issues a single ``execute_query(sql, fetch_all=True)``
    whose SELECT returns ``(username, name, url)`` rows. This stub ignores the
    SQL text and returns the scripted row list, so the test exercises the
    reconciliation logic without a live PostgreSQL.
    """

    def __init__(self, rows):
        self._rows = list(rows)

    def execute_query(self, sql, params=None, fetch_one=False, fetch_all=False):
        assert fetch_all, "sync_all_locations is expected to fetch_all"
        return list(self._rows)


# [a-z0-9-] identifiers for user and app names. Non-empty so the file name
# app-{user}-{app}.yml is well-formed.
_IDENT = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-", min_size=1, max_size=8)


@st.composite
def app_sets(draw):
    """Generate a list of (user, app, url) rows with unique (user, app) keys.

    Uniqueness of (user, app) makes the expected set of route files
    well-defined: exactly one app-{user}-{app}.yml per DB app. The url carries a
    host:port so the Proxy_Manager can derive the backend from it.
    """
    pairs = draw(
        st.lists(
            st.tuples(_IDENT, _IDENT),
            min_size=0,
            max_size=8,
            unique=True,
        )
    )
    rows = []
    for user, app in pairs:
        port = draw(st.integers(min_value=1025, max_value=65535))
        url = f"https://{user}-{app}:{port}"
        rows.append((user, app, url))
    return rows


def _active_app_files(dynamic_dir):
    """Return the set of basenames of active per-app route files."""
    return {
        os.path.basename(p)
        for p in glob.glob(os.path.join(dynamic_dir, "app-*.yml"))
    }


def _expected_app_files(rows):
    """Return the expected set of app-*.yml basenames for the DB rows."""
    return {f"app-{user}-{app}.yml" for user, app, _url in rows}


@settings(max_examples=150, deadline=None)
@given(rows=app_sets())
def test_sync_reconciles_to_db_and_is_idempotent(rows):
    """Property 7: sync reconciles to exactly the DB set and is idempotent."""
    # A fresh temp directory per example keeps each generated app set isolated
    # (hypothesis reuses the test function across examples, so a shared
    # function-scoped fixture would leak state between runs).
    dynamic_dir_str = tempfile.mkdtemp(prefix="traefik_dynamic_")

    # Monkeypatch the module-level dynamic directory. sync_all_locations and the
    # helpers it calls read TRAEFIK_DYNAMIC_DIR at call time, so reassigning the
    # module attribute redirects all writes/deletes/listing to the temp dir.
    original_dir = nginx_manager.TRAEFIK_DYNAMIC_DIR
    try:
        nginx_manager.TRAEFIK_DYNAMIC_DIR = dynamic_dir_str

        # Seed: a stale per-app route file that is NOT in the DB (must be
        # removed), plus two non-app dynamic files (must be left untouched).
        stale_app = os.path.join(dynamic_dir_str, "app-ghost-ghost.yml")
        tls_file = os.path.join(dynamic_dir_str, "tls.yml")
        secondary_file = os.path.join(dynamic_dir_str, "secondary-domains.yml")
        with open(stale_app, "w") as f:
            f.write("http: {routers: {}}\n")
        tls_marker = "tls:\n  stores:\n    default: {}\n"
        secondary_marker = "http:\n  routers: {}\n"
        with open(tls_file, "w") as f:
            f.write(tls_marker)
        with open(secondary_file, "w") as f:
            f.write(secondary_marker)

        db = StubDbManager(rows)

        # First sync.
        assert nginx_manager.sync_all_locations(db) is True

        expected = _expected_app_files(rows)
        active = _active_app_files(dynamic_dir_str)

        # Active app route set equals exactly the DB app set: every DB app has a
        # route, and no route exists for a non-DB app (the stale ghost file is
        # gone).
        assert active == expected
        assert "app-ghost-ghost.yml" not in active

        # Non-app dynamic files are left untouched (present and unchanged).
        assert os.path.exists(tls_file)
        assert os.path.exists(secondary_file)
        with open(tls_file) as f:
            assert f.read() == tls_marker
        with open(secondary_file) as f:
            assert f.read() == secondary_marker

        # Second sync against the same DB is idempotent: same route set.
        assert nginx_manager.sync_all_locations(db) is True
        active_again = _active_app_files(dynamic_dir_str)
        assert active_again == expected

        # And the non-app files are still untouched after the second run.
        assert os.path.exists(tls_file)
        assert os.path.exists(secondary_file)
        with open(tls_file) as f:
            assert f.read() == tls_marker
        with open(secondary_file) as f:
            assert f.read() == secondary_marker
    finally:
        nginx_manager.TRAEFIK_DYNAMIC_DIR = original_dir
        shutil.rmtree(dynamic_dir_str, ignore_errors=True)


if __name__ == "__main__":
    # Allow running as a plain script (outside pytest) for quick checks.
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
