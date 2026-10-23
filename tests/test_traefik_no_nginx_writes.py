#!/usr/bin/env python3
"""Property test — Property 5: Proxy operations never write nginx files.

Feature: nginx-to-traefik-migration, Property 5
Validates: Requirements 2.5

Over randomly generated sequences of ``insert_location_block`` /
``remove_location_block`` / ``sync_all_locations`` calls — with every
filesystem write monitored — NO write may target the retired nginx config
directories ``/etc/nginx/sites-available`` or ``/etc/nginx/sites-enabled``.

How writes are monitored
-------------------------
We wrap the low-level filesystem entry points the module uses to create or
replace files and record every path argument they receive:

* ``builtins.open`` (catches ``os.fdopen`` is NOT needed — the module opens the
  mkstemp fd via ``os.fdopen``, but the *path* it would write to is the temp
  file created by ``tempfile.mkstemp``, which we also record),
* ``os.replace`` (the atomic rename onto the final target),
* ``os.remove`` (temp-file cleanup and route deletion),
* ``os.makedirs`` (directory creation),
* ``tempfile.mkstemp`` (temp-file creation — returns the path we record).

After each generated operation sequence we assert that none of the recorded
absolute paths begins with either forbidden nginx directory prefix.

Isolation
---------
``frontend_manager.TRAEFIK_DYNAMIC_DIR`` is monkeypatched to a throwaway temp
directory so the real ``traefik/dynamic`` tree is never touched and the
reconcile step of ``sync_all_locations`` only ever operates inside the temp
dir.

Complementary static assertion
------------------------------
As a belt-and-suspenders check (not the core property), we also assert the
module source contains no ``subprocess``/``docker``/``nginx`` reload shell-outs
to nginx. The write-monitoring property above is the authoritative guarantee.
"""
import builtins
import contextlib
import os
import re
import shutil
import sys
import tempfile

from hypothesis import given, settings, strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import src.frontend_manager as frontend_manager  # noqa: E402


# --- forbidden nginx locations --------------------------------------------
_FORBIDDEN_PREFIXES = (
    "/etc/nginx/sites-available",
    "/etc/nginx/sites-enabled",
)


def _record_path(recorded, path):
    """Record a path-like argument as an absolute path string."""
    if path is None:
        return
    try:
        p = os.fspath(path)
    except TypeError:
        return
    if not isinstance(p, str):
        try:
            p = p.decode("utf-8", "replace")
        except Exception:
            return
    recorded.append(os.path.abspath(p))


class _WriteMonitor:
    """Wrap filesystem write entry points to record every path touched."""

    def __init__(self):
        self.paths = []
        self._orig = {}

    def __enter__(self):
        rec = self.paths

        self._orig["open"] = builtins.open
        self._orig["replace"] = os.replace
        self._orig["remove"] = os.remove
        self._orig["makedirs"] = os.makedirs
        self._orig["mkstemp"] = tempfile.mkstemp

        orig_open = self._orig["open"]
        orig_replace = self._orig["replace"]
        orig_remove = self._orig["remove"]
        orig_makedirs = self._orig["makedirs"]
        orig_mkstemp = self._orig["mkstemp"]

        def wrapped_open(file, *a, **k):
            _record_path(rec, file)
            return orig_open(file, *a, **k)

        def wrapped_replace(src, dst, *a, **k):
            _record_path(rec, src)
            _record_path(rec, dst)
            return orig_replace(src, dst, *a, **k)

        def wrapped_remove(path, *a, **k):
            _record_path(rec, path)
            return orig_remove(path, *a, **k)

        def wrapped_makedirs(name, *a, **k):
            _record_path(rec, name)
            return orig_makedirs(name, *a, **k)

        def wrapped_mkstemp(*a, **k):
            fd, path = orig_mkstemp(*a, **k)
            _record_path(rec, path)
            return fd, path

        builtins.open = wrapped_open
        os.replace = wrapped_replace
        os.remove = wrapped_remove
        os.makedirs = wrapped_makedirs
        tempfile.mkstemp = wrapped_mkstemp
        return self

    def __exit__(self, *exc):
        builtins.open = self._orig["open"]
        os.replace = self._orig["replace"]
        os.remove = self._orig["remove"]
        os.makedirs = self._orig["makedirs"]
        tempfile.mkstemp = self._orig["mkstemp"]
        return False

    def assert_no_nginx_writes(self):
        for path in self.paths:
            norm = path.replace("\\", "/")
            for forbidden in _FORBIDDEN_PREFIXES:
                assert not norm.startswith(forbidden), (
                    f"proxy operation wrote to forbidden nginx path {path!r} "
                    f"(prefix {forbidden!r})"
                )


class _StubDbManager:
    """Minimal db_manager stub for sync_all_locations.

    ``sync_all_locations`` only calls ``execute_query(sql, fetch_all=True)`` and
    expects a list of ``(username, name, url)`` rows.
    """

    def __init__(self, rows):
        self._rows = rows

    def execute_query(self, query, fetch_all=False, **kwargs):
        return list(self._rows)


# --- Generators -----------------------------------------------------------
_DNS_LABEL = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789-", min_size=1, max_size=16
)
_URL = st.builds(
    lambda host, port: f"https://{host}:{port}",
    st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-", min_size=1, max_size=20),
    st.integers(min_value=2, max_value=65535),
)

# A single operation is one of the three public calls with generated args.
_INSERT = st.builds(
    lambda u, a, url: ("insert", u, a, url),
    _DNS_LABEL, _DNS_LABEL, _URL,
)
_REMOVE = st.builds(
    lambda u, a: ("remove", u, a),
    _DNS_LABEL, _DNS_LABEL,
)
_SYNC = st.builds(
    lambda rows: ("sync", rows),
    st.lists(
        st.builds(lambda u, a, url: (u, a, url), _DNS_LABEL, _DNS_LABEL, _URL),
        min_size=0, max_size=5,
    ),
)
_OPERATION = st.one_of(_INSERT, _REMOVE, _SYNC)


def _run_operation(op):
    kind = op[0]
    if kind == "insert":
        _, user, app, url = op
        frontend_manager.insert_location_block(user, app, url, url)
    elif kind == "remove":
        _, user, app = op
        frontend_manager.remove_location_block(user, app)
    elif kind == "sync":
        _, rows = op
        frontend_manager.sync_all_locations(_StubDbManager(rows))


@contextlib.contextmanager
def _isolated_dynamic_dir():
    """Point ``TRAEFIK_DYNAMIC_DIR`` at a throwaway temp dir for one example.

    Used instead of pytest's function-scoped ``monkeypatch``/``tmp_path``
    fixtures, which hypothesis (correctly) refuses to reset between the many
    inputs a single ``@given`` test generates. This context manager gives every
    generated operation sequence a fresh, isolated dynamic directory and always
    restores the original attribute.
    """
    original = frontend_manager.TRAEFIK_DYNAMIC_DIR
    dynamic_dir = tempfile.mkdtemp(prefix="traefik_dynamic_")
    frontend_manager.TRAEFIK_DYNAMIC_DIR = dynamic_dir
    try:
        yield dynamic_dir
    finally:
        frontend_manager.TRAEFIK_DYNAMIC_DIR = original
        shutil.rmtree(dynamic_dir, ignore_errors=True)


# --- Property 5 -----------------------------------------------------------
@settings(max_examples=150, deadline=None)
@given(operations=st.lists(_OPERATION, min_size=1, max_size=8))
def test_proxy_operations_never_write_nginx_files(operations):
    """Feature: nginx-to-traefik-migration, Property 5.

    Validates: Requirements 2.5.
    """
    # Isolate the dynamic directory so real traefik/dynamic is never touched.
    with _isolated_dynamic_dir():
        with _WriteMonitor() as monitor:
            for op in operations:
                _run_operation(op)

        monitor.assert_no_nginx_writes()


# --- Complementary static assertion (not the core property) ---------------
def test_module_source_has_no_nginx_shellouts():
    """Belt-and-suspenders: the module source no longer shells out to nginx.

    The write-monitoring property above is the authoritative guarantee; this
    guards against a regression that reintroduces an nginx reload/subprocess
    path that a pure write monitor on this process might not exercise.
    """
    source_path = os.path.join(PROJECT_ROOT, "src", "frontend_manager.py")
    with open(source_path, "r", encoding="utf-8") as f:
        source = f.read()

    assert "subprocess" not in source, "module reintroduced a subprocess shell-out"
    assert "sites-available" not in source, "module references nginx sites-available"
    assert "sites-enabled" not in source, "module references nginx sites-enabled"
    # No `nginx -s reload` / `nginx -t` style shell-outs.
    assert not re.search(r"nginx\s+-[ts]\b", source), "module shells out to nginx"


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
