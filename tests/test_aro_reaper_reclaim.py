#!/usr/bin/env python3
"""Property test for the task-store reaper reclaim semantics (Task 13.6).

Feature: phase2-aro-completion, Property 26: Reaper reclaims exactly the expired
leases.
Validates: Requirements 6.6, 6.7

The function under test is ``task_repository.reap_expired_leases()``. Its SQL
selects ``claimed``/``running`` rows whose ``lease_expires_at`` is non-null and
strictly in the past (``< CURRENT_TIMESTAMP``), using ``FOR UPDATE SKIP LOCKED``,
and returns a list of dicts carrying ``id, tenant_id, attempts, max_attempts,
status`` plus ``task_ref, agent_id`` (the context the reaper uses to emit a
correlated lifecycle event, Req 6.12).

No live DB is used (project convention): ``task_repo._get_db`` is monkeypatched
to a fake ``db_manager`` whose ``get_db_connection()`` context manager yields a
fake conn/cursor. The fake cursor models the reaper's WHERE predicate against a
generated set of arbitrary task rows (varied status, lease_expires_at that is
past / future / null) and returns exactly the rows the predicate selects. The
property asserts the reaped set equals the independently-computed expected
expired set — never a pending/succeeded/failed row, never a row with null or
future lease.

It also ties Req 6.6/6.7 by applying ``reenqueue_or_finalize`` per reaped row and
asserting the bounded decision: ``attempts < max_attempts`` re-enqueues to
``pending``; ``attempts >= max_attempts`` finalizes in the terminal status.

Run directly:
    python3 tests/test_aro_reaper_reclaim.py
Or via pytest:
    pytest tests/test_aro_reaper_reclaim.py
"""
import os
import sys
from contextlib import contextmanager

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.aro import task_repository as task_repo  # noqa: E402


# --- Row generation -------------------------------------------------------
#
# A generated "task row" models the fields the reaper predicate and decision
# care about. ``lease_state`` is drawn independently of status so we exercise
# every combination (expired/future/null lease across every status), which is
# exactly where the predicate must be exact.

_STATUSES = ["pending", "claimed", "running", "succeeded", "failed", "timed_out", "cancelled"]
#: Only these statuses are eligible for reclaim (the reaper SELECT's IN list).
_REAPABLE = {"claimed", "running"}
#: Sentinel lease states: an expired (past) lease, a future lease, or NULL.
_LEASE_STATES = ["expired", "future", "null"]


@st.composite
def _task_rows(draw):
    """Generate a list of task rows with unique ids and varied status/lease.

    Each row is a dict with: id, tenant_id, attempts, max_attempts, status,
    lease_state. ids are unique (they are a PK). ``lease_state`` records whether
    the row's ``lease_expires_at`` is in the past, the future, or NULL.
    """
    n = draw(st.integers(min_value=0, max_value=12))
    ids = draw(
        st.lists(
            st.integers(min_value=1, max_value=10_000),
            min_size=n,
            max_size=n,
            unique=True,
        )
    )
    rows = []
    for rid in ids:
        max_attempts = draw(st.integers(min_value=1, max_value=5))
        attempts = draw(st.integers(min_value=1, max_value=7))
        rows.append(
            {
                "id": rid,
                "tenant_id": draw(st.integers(min_value=1, max_value=50)),
                "attempts": attempts,
                "max_attempts": max_attempts,
                "status": draw(st.sampled_from(_STATUSES)),
                "lease_state": draw(st.sampled_from(_LEASE_STATES)),
                # Context columns carried by the reap projection so the reaper
                # can emit a correlated lifecycle event (Req 6.12).
                "task_ref": f"task-{rid}",
                "agent_id": draw(st.integers(min_value=1, max_value=99)),
            }
        )
    return rows


def _is_expired(row):
    """Reference predicate mirroring the reaper SELECT's WHERE clause.

    status IN ('claimed','running') AND lease_expires_at IS NOT NULL
    AND lease_expires_at < CURRENT_TIMESTAMP.
    """
    return row["status"] in _REAPABLE and row["lease_state"] == "expired"


def _reaped_tuple(row):
    """The decision-input projection the reaper returns, as a comparable tuple.

    Compares the fields the reclaim decision depends on (id, tenant, attempts,
    bound, status); the added ``task_ref``/``agent_id`` context columns are
    exercised separately and not part of this exactness tuple.
    """
    return (row["id"], row["tenant_id"], row["attempts"], row["max_attempts"], row["status"])


# --- Fake DB --------------------------------------------------------------


def _make_fake_db(rows):
    """Build a fake ``db_manager`` for ``task_repository``.

    * ``get_db_connection()`` yields a conn whose cursor models the reaper
      SELECT: on ``execute`` it applies ``_is_expired`` to the generated rows
      and stashes the 5-column projection for ``fetchall``.
    * ``execute_query`` models the two statements ``reenqueue_or_finalize``
      issues: the ``SELECT attempts, max_attempts ...`` read and the subsequent
      UPDATE (which mutates the shared ``rows`` so re-decision would be stable).
    """

    by_id = {r["id"]: r for r in rows}

    class _FakeCursor:
        def __init__(self):
            self._result = []
            self.executed = []

        def execute(self, sql, params=None):
            self.executed.append(sql)
            # The reaper issues exactly one SELECT ... FOR UPDATE SKIP LOCKED.
            # Model its predicate over the generated rows.
            self._result = [
                (r["id"], r["tenant_id"], r["attempts"], r["max_attempts"],
                 r["status"], r["task_ref"], r["agent_id"])
                for r in rows
                if _is_expired(r)
            ]

        def fetchall(self):
            return list(self._result)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    class _FakeConn:
        def __init__(self):
            self._cursor = _FakeCursor()

        def cursor(self):
            return self._cursor

        def commit(self):
            pass

    class _FakeDbManager:
        @contextmanager
        def get_db_connection(self):
            yield _FakeConn()

        def execute_query(self, sql, params=None, fetch_one=False, fetch_all=False):
            s = " ".join(sql.split())
            # reenqueue_or_finalize's read: SELECT attempts, max_attempts ...
            if s.startswith("SELECT attempts, max_attempts"):
                tenant_id, task_id = params
                row = by_id.get(task_id)
                if row is None or row["tenant_id"] != tenant_id:
                    return None
                return (row["attempts"], row["max_attempts"])
            # reenqueue_or_finalize's re-enqueue UPDATE (-> pending).
            if "SET status = 'pending'" in s:
                return 1
            # reenqueue_or_finalize's finalize UPDATE (-> terminal_status).
            if s.startswith("UPDATE agent_tasks SET status = %s"):
                return 1
            return None

    return _FakeDbManager()


# --- Property 26 ----------------------------------------------------------


@given(rows=_task_rows())
@settings(max_examples=150)
def test_property26_reaper_reclaims_exactly_expired_leases(rows):
    """reap_expired_leases returns exactly the expired claimed/running rows.

    Feature: phase2-aro-completion, Property 26: Reaper reclaims exactly the
    expired leases.
    Validates: Requirements 6.6, 6.7
    """
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(task_repo, "_get_db", lambda: _make_fake_db(rows))
        reaped = task_repo.reap_expired_leases()

    reaped_ids = {r["id"] for r in reaped}
    expected = [r for r in rows if _is_expired(r)]
    expected_ids = {r["id"] for r in expected}

    # Exactness: the reaped set equals the expected expired set — no extra, none missing.
    assert reaped_ids == expected_ids

    # Nothing outside claimed/running, and nothing with a future or null lease,
    # ever appears in the reaped set.
    for r in reaped:
        assert r["status"] in _REAPABLE
    for row in rows:
        if row["status"] not in _REAPABLE or row["lease_state"] in ("future", "null"):
            assert row["id"] not in reaped_ids

    # The projection carries the decision inputs for Req 6.6/6.7.
    assert {_reaped_tuple(r) for r in expected} == {
        (r["id"], r["tenant_id"], r["attempts"], r["max_attempts"], r["status"]) for r in reaped
    }


@given(rows=_task_rows())
@settings(max_examples=150)
def test_property26_reaped_rows_follow_bounded_decision(rows):
    """Each reaped row re-enqueues (attempts<max) or finalizes (attempts>=max).

    Ties the reaper to the bounded re-enqueue-vs-finalize decision: for every
    reclaimed row, reenqueue_or_finalize yields ``pending`` when
    ``attempts < max_attempts`` (Req 6.6) and the terminal lease-expiry status
    when ``attempts >= max_attempts`` (Req 6.7).

    Feature: phase2-aro-completion, Property 26: Reaper reclaims exactly the
    expired leases.
    Validates: Requirements 6.6, 6.7
    """
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(task_repo, "_get_db", lambda: _make_fake_db(rows))
        reaped = task_repo.reap_expired_leases()

        for r in reaped:
            outcome = task_repo.reenqueue_or_finalize(
                r["tenant_id"], r["id"], "failed", reason="lease-expired"
            )
            if r["attempts"] < r["max_attempts"]:
                assert outcome["outcome"] == "reenqueued"
                assert outcome["status"] == "pending"
            else:
                assert outcome["outcome"] == "finalized"
                assert outcome["status"] == "failed"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
