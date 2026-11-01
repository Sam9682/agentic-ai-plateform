#!/usr/bin/env python3
"""Property test for orchestrator reconcile-loop behavior preservation.

Feature: phase1-foundation-consolidation, Property 1: Reconcile loop preserves
per-service reconciliation with no reverse-proxy generation side effect.

Over arbitrary sets of running services/instances, this asserts that ONE
reconcile iteration reconciles each service exactly as before (one
``_reconcile_service(name, user_id)`` call per service row, one
``health_check_instances()`` call) and performs NO nginx config generation or
reload (``generate_nginx_config`` and ``reload_nginx`` are never invoked by the
loop).

Validates: Requirements 3.3, 3.4

Run directly:
    python3 tests/test_orchestrator_reconcile_no_nginx.py
Or via pytest:
    pytest tests/test_orchestrator_reconcile_no_nginx.py
"""
import os
import sys
from contextlib import contextmanager
from unittest import mock

from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src import orchestrator as orch_mod  # noqa: E402
from src.orchestrator import LightOrchestrator  # noqa: E402


# A service row as the reconcile loop reads it: (name, user_id). The loop does
# ``SELECT name, user_id FROM services`` and then calls
# ``_reconcile_service(service[0], service[1])`` per row, so we generate exactly
# that tuple shape. Names are arbitrary non-empty-ish text; user_ids arbitrary
# ints. Lists include the empty set (min_size=0) to cover "no services".
_SERVICE_NAME = st.text(min_size=0, max_size=24)
_USER_ID = st.integers(min_value=0, max_value=10_000)
_SERVICE_ROW = st.tuples(_SERVICE_NAME, _USER_ID)
_SERVICE_SETS = st.lists(_SERVICE_ROW, min_size=0, max_size=12)


def _make_fake_db(service_rows):
    """Build a fake db_manager whose get_db_connection() context manager yields a
    connection whose cursor.fetchall() returns the generated service rows."""

    class _FakeCursor:
        def __init__(self, rows):
            self._rows = rows
            self.executed = []
            self._last_sql = ""

        def execute(self, sql, *args):
            self.executed.append(sql)
            self._last_sql = sql

        def fetchone(self):
            # The reconcile loop wraps each pass in a non-blocking advisory lock
            # (pg_try_advisory_lock) and releases it (pg_advisory_unlock); both
            # issue a single-row SELECT. Return a truthy acquired result so the
            # fake process always "wins" the try-lock and runs the pass.
            if "pg_try_advisory_lock" in self._last_sql:
                return (True,)
            return (1,)

        def fetchall(self):
            # The reconcile loop issues a single SELECT then fetchall(); return
            # the generated rows regardless of the exact SQL text.
            return list(self._rows)

    class _FakeConn:
        def __init__(self, rows):
            self._cursor = _FakeCursor(rows)

        def cursor(self):
            return self._cursor

        def commit(self):
            pass

    class _FakeDbManager:
        def __init__(self, rows):
            self._rows = rows

        @contextmanager
        def get_db_connection(self):
            yield _FakeConn(self._rows)

    return _FakeDbManager(service_rows)


def _run_one_iteration(orchestrator):
    """Drive EXACTLY ONE reconcile iteration without the real background cadence.

    The loop body lives inside the ``reconcile_loop`` closure created by
    ``start_reconciliation_loop`` and is only reachable via the thread's
    ``while self._running`` loop. We do not modify src/ to expose it. Instead we
    patch ``src.orchestrator.time.sleep`` so its first call flips ``_running`` to
    False: the loop therefore executes its body once, reaches the trailing
    ``time.sleep(interval)``, and exits before a second iteration. The daemon
    thread is started and joined with a short timeout.
    """

    def _sleep_once(_interval):
        orchestrator._running = False

    with mock.patch.object(orch_mod.time, "sleep", side_effect=_sleep_once):
        orchestrator.start_reconciliation_loop(interval=0)
        thread = orchestrator._reconcile_thread
        thread.join(timeout=5)
        assert not thread.is_alive(), "reconcile thread did not complete one iteration"


@settings(max_examples=150, deadline=None)
@given(service_rows=_SERVICE_SETS)
def test_reconcile_loop_reconciles_each_service_without_nginx(service_rows):
    """Feature: phase1-foundation-consolidation, Property 1.

    One reconcile iteration over an arbitrary service set:
    - calls health_check_instances() exactly once,
    - calls _reconcile_service(name, user_id) exactly once per service row, and
    - NEVER calls generate_nginx_config() or reload_nginx() (no reverse-proxy
      generation side effect).
    """
    orchestrator = LightOrchestrator()
    fake_db = _make_fake_db(service_rows)

    with mock.patch.object(orch_mod, "db_manager", fake_db), \
         mock.patch.object(LightOrchestrator, "health_check_instances") as health_spy, \
         mock.patch.object(LightOrchestrator, "_reconcile_service") as reconcile_spy, \
         mock.patch.object(LightOrchestrator, "generate_nginx_config") as nginx_gen_spy, \
         mock.patch.object(LightOrchestrator, "reload_nginx") as nginx_reload_spy:

        _run_one_iteration(orchestrator)

        # Per-service reconciliation preserved: one call per generated row, in
        # order, with the exact (name, user_id) arguments.
        assert reconcile_spy.call_count == len(service_rows)
        expected_calls = [mock.call(name, user_id) for (name, user_id) in service_rows]
        assert reconcile_spy.call_args_list == expected_calls

        # Health check still runs exactly once per iteration.
        assert health_spy.call_count == 1

        # No reverse-proxy generation side effect (Requirements 3.3, 3.4).
        assert nginx_gen_spy.call_count == 0
        assert nginx_reload_spy.call_count == 0


def test_reconcile_loop_empty_service_set_still_no_nginx():
    """Feature: phase1-foundation-consolidation, Property 1 (example/edge case).

    With no services, one iteration performs the health check, no per-service
    reconciliation, and still no nginx generation or reload.
    """
    orchestrator = LightOrchestrator()
    fake_db = _make_fake_db([])

    with mock.patch.object(orch_mod, "db_manager", fake_db), \
         mock.patch.object(LightOrchestrator, "health_check_instances") as health_spy, \
         mock.patch.object(LightOrchestrator, "_reconcile_service") as reconcile_spy, \
         mock.patch.object(LightOrchestrator, "generate_nginx_config") as nginx_gen_spy, \
         mock.patch.object(LightOrchestrator, "reload_nginx") as nginx_reload_spy:

        _run_one_iteration(orchestrator)

        assert reconcile_spy.call_count == 0
        assert health_spy.call_count == 1
        assert nginx_gen_spy.call_count == 0
        assert nginx_reload_spy.call_count == 0


if __name__ == "__main__":
    test_reconcile_loop_reconciles_each_service_without_nginx()
    test_reconcile_loop_empty_service_set_still_no_nginx()
    print("ok")
