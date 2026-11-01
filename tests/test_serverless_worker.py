#!/usr/bin/env python3
"""Tests for the serverless worker hardening (Phase 4, task 7.2).

Feature: phase4-runtime-execution-hardening

Covers the two behavioral changes to ``src/serverless/worker.py``:

* ``run_once`` enforces ``max_concurrent_jobs`` by deferring a claim while
  ``in_flight >= max_concurrent`` and incrementing/decrementing ``in_flight``
  around ``execute_job`` (R5.4).
* Every DB operation borrows a connection from a shared pool whose
  ``get_db_connection`` context manager returns the connection in ``finally``,
  instead of a per-op ``psycopg2.connect`` (R5.5); the claim runs through the
  shared execution policy (R1.9).

Run directly:
    python3 tests/test_serverless_worker.py
Or via pytest:
    pytest tests/test_serverless_worker.py
"""
import os
import sys
from contextlib import contextmanager

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.serverless.worker import ServerlessWorker  # noqa: E402


class _FakeCursor:
    """Minimal cursor recording executed SQL and serving scripted rows."""

    def __init__(self, rows):
        self._rows = list(rows)
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None


class _FakeConn:
    """Minimal connection whose cursor yields scripted rows."""

    def __init__(self, rows):
        self._rows = rows
        self.committed = 0
        self.rolled_back = 0

    def cursor(self, cursor_factory=None):
        return _FakeCursor(self._rows)

    def commit(self):
        self.committed += 1

    def rollback(self):
        self.rolled_back += 1


class _FakePool:
    """Pool double matching the worker's borrow/return contract.

    Records every borrow/return so a test can assert the connection is always
    returned in ``finally`` (R5.5).
    """

    def __init__(self, rows=None):
        self._rows = rows or []
        self.borrowed = 0
        self.returned = 0

    @contextmanager
    def get_db_connection(self):
        self.borrowed += 1
        conn = _FakeConn(self._rows)
        try:
            yield conn
        finally:
            self.returned += 1


def _make_worker(pool, max_concurrent=None):
    return ServerlessWorker(
        worker_id="w-test",
        runtime=object(),
        db_config={
            "host": "h", "port": 5432, "database": "d",
            "user": "u", "password": "p",
        },
        pool=pool,
        max_concurrent=max_concurrent,
    )


def test_run_once_defers_claim_at_capacity():
    """R5.4: at the cap the worker neither claims nor borrows a connection."""
    pool = _FakePool()
    worker = _make_worker(pool, max_concurrent=1)
    worker.in_flight = 1  # already at capacity

    claimed = []
    worker.claim_next_job = lambda: claimed.append(True)

    assert worker.run_once() is False
    assert claimed == []  # claim was never attempted
    assert pool.borrowed == 0  # no DB access while deferred


def test_run_once_accounts_in_flight_around_execution():
    """R5.4: in_flight is +1 during execute_job and restored to 0 after."""
    pool = _FakePool()
    worker = _make_worker(pool, max_concurrent=2)

    worker.claim_next_job = lambda: {"id": "job-1", "image": "img"}
    seen = {}

    def _exec(job):
        seen["in_flight_during"] = worker.in_flight

    worker.execute_job = _exec

    assert worker.run_once() is True
    assert seen["in_flight_during"] == 1
    assert worker.in_flight == 0  # slot freed after terminal


def test_run_once_decrements_in_flight_on_failure():
    """R5.4: the in-flight slot is freed even when execute_job raises."""
    pool = _FakePool()
    worker = _make_worker(pool, max_concurrent=2)
    worker.claim_next_job = lambda: {"id": "job-1", "image": "img"}

    def _boom(job):
        raise RuntimeError("execution blew up")

    worker.execute_job = _boom

    with pytest.raises(RuntimeError):
        worker.run_once()
    assert worker.in_flight == 0


def test_run_once_returns_false_when_queue_empty():
    """An empty queue handles nothing and never touches in_flight."""
    pool = _FakePool()
    worker = _make_worker(pool, max_concurrent=1)
    worker.claim_next_job = lambda: None
    assert worker.run_once() is False
    assert worker.in_flight == 0


def test_claim_next_job_uses_pool_and_returns_connection():
    """R5.5: claim borrows from the pool and returns the connection."""
    row = {
        "id": "job-7", "user_id": 1, "image": "docker.io/x:1",
        "command": "echo", "environment": {}, "timeout_seconds": 10,
    }
    pool = _FakePool(rows=[row])
    worker = _make_worker(pool, max_concurrent=5)

    job = worker.claim_next_job()
    assert job is not None
    assert job["id"] == "job-7"
    assert pool.borrowed == 1
    assert pool.returned == 1  # returned in finally


def test_claim_next_job_empty_queue_returns_none():
    """R5.5: an empty queue yields None and still returns the connection."""
    pool = _FakePool(rows=[])
    worker = _make_worker(pool, max_concurrent=5)
    assert worker.claim_next_job() is None
    assert pool.borrowed == 1
    assert pool.returned == 1


def test_db_ops_borrow_and_return_connection():
    """R5.5: check/store/mark operations all go through the pool."""
    pool = _FakePool(rows=[("running",)])
    worker = _make_worker(pool, max_concurrent=5)

    worker.check_cancelled("job-1")
    worker.mark_completed("job-1", 0)
    worker.mark_failed("job-2", "err")
    worker.mark_timeout("job-3")
    worker.store_result("job-4", 0, "out", "err")

    # Every op borrowed exactly one connection and returned it.
    assert pool.borrowed == 5
    assert pool.returned == 5


def test_default_max_concurrent_from_config():
    """R5.4: default cap comes from SERVERLESS_CONFIG['max_concurrent_jobs']."""
    from src.serverless.config import SERVERLESS_CONFIG

    worker = _make_worker(_FakePool())
    assert worker.max_concurrent == SERVERLESS_CONFIG["max_concurrent_jobs"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
