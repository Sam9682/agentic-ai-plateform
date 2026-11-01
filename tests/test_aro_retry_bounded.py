#!/usr/bin/env python3
"""Property test for bounded retry / re-enqueue in the ARO task store (Task 13.4).

Feature: phase2-aro-completion.

Validates:
* Property 24: Retry is bounded by max_attempts — ``reenqueue_or_finalize``
  re-enqueues (status ``pending``, outcome ``"reenqueued"``) iff
  ``attempts < max_attempts``, and finalizes (status == ``terminal_status``,
  outcome ``"finalized"``, recording ``reason``) iff ``attempts >= max_attempts``.

No live DB: a fake db_manager is injected by monkeypatching
``task_repository._get_db``. The fake ``execute_query`` answers the
``SELECT attempts, max_attempts`` with the generated values and records the
subsequent ``UPDATE`` so the test can assert which branch ran.

Run directly:
    python3 tests/test_aro_retry_bounded.py
Or via pytest:
    pytest tests/test_aro_retry_bounded.py
"""
import json
import os
import sys

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.aro import task_repository as task_repo  # noqa: E402


class _FakeDb:
    """Minimal db_manager stub for ``reenqueue_or_finalize``.

    ``reenqueue_or_finalize`` issues exactly two ``execute_query`` calls:
      1. a ``SELECT attempts, max_attempts ...`` (``fetch_one=True``) — we
         return the generated ``(attempts, max_attempts)`` tuple;
      2. an ``UPDATE agent_tasks SET ...`` — we record it so the test can tell
         which branch (re-enqueue vs finalize) ran and with what params.

    When ``row`` is None the SELECT returns no row (the ``"noop"`` path).
    """

    def __init__(self, row):
        self._row = row
        self.updates = []  # list of (sql, params) for UPDATE statements

    def execute_query(self, sql, params=None, fetch_one=False, fetch_all=False):
        stripped = sql.strip().upper()
        if stripped.startswith("SELECT"):
            assert fetch_one, "the attempts/max_attempts read uses fetch_one"
            return self._row
        if stripped.startswith("UPDATE"):
            self.updates.append((sql, params))
            return 1  # rowcount-like truthy result
        raise AssertionError(f"unexpected query: {sql!r}")


# attempts in [0..N], max_attempts in [1..N]; terminal_status in the two
# non-success terminals the reaper/worker use for this path.
_N = 50
_TERMINAL = st.sampled_from(["failed", "timed_out"])


@given(
    attempts=st.integers(min_value=0, max_value=_N),
    max_attempts=st.integers(min_value=1, max_value=_N),
    terminal_status=_TERMINAL,
    tenant_id=st.integers(min_value=1, max_value=10_000),
    task_id=st.integers(min_value=1, max_value=10_000),
    reason=st.one_of(st.none(), st.text(max_size=40)),
)
@settings(max_examples=200)
def test_property24_retry_bounded_by_max_attempts(
    attempts, max_attempts, terminal_status, tenant_id, task_id, reason
):
    """Re-enqueue iff attempts < max_attempts, else finalize to terminal_status.

    Feature: phase2-aro-completion, Property 24: Retry is bounded by
    max_attempts.
    Validates: Requirements 6.3, 6.4
    """
    fake = _FakeDb((attempts, max_attempts))
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(task_repo, "_get_db", lambda: fake)
        result = task_repo.reenqueue_or_finalize(
            tenant_id, task_id, terminal_status, reason
        )

    # Exactly one UPDATE is issued (either the re-enqueue or the finalize).
    assert len(fake.updates) == 1
    update_sql, update_params = fake.updates[0]

    # The attempts/max_attempts are echoed back unchanged in every case.
    assert result["attempts"] == attempts
    assert result["max_attempts"] == max_attempts

    if attempts < max_attempts:
        # Re-enqueue branch: returned to the pending queue for another attempt.
        assert result["outcome"] == "reenqueued"
        assert result["status"] == "pending"
        assert "'PENDING'" in update_sql.upper() or "= 'PENDING'" in update_sql.upper()
        # Tenant-scoped write (Req 6.8): the UPDATE carries the tenant + task id.
        assert tenant_id in update_params
        assert task_id in update_params
    else:
        # Finalize branch (attempts >= max_attempts): left in terminal_status.
        assert result["outcome"] == "finalized"
        assert result["status"] == terminal_status
        # terminal_status is bound as a parameter of the finalizing UPDATE.
        assert terminal_status in update_params
        assert tenant_id in update_params
        assert task_id in update_params
        # The reason is recorded in the result payload when provided. It is
        # stored as a JSON string param (json.dumps({"reason": reason})), so
        # decode the JSON params and confirm the reason round-trips faithfully.
        if reason is not None:
            decoded_reasons = []
            for p in update_params:
                if not isinstance(p, str):
                    continue
                try:
                    obj = json.loads(p)
                except (TypeError, ValueError):
                    continue
                if isinstance(obj, dict) and "reason" in obj:
                    decoded_reasons.append(obj["reason"])
            assert reason in decoded_reasons, (
                "reason must be recorded in the finalizing UPDATE's result payload"
            )


@given(
    boundary=st.integers(min_value=1, max_value=_N),
    terminal_status=_TERMINAL,
)
@settings(max_examples=200)
def test_property24_boundary_at_max_attempts(boundary, terminal_status):
    """The flip happens exactly at attempts == max_attempts (the iff boundary).

    attempts == max_attempts - 1  -> reenqueued
    attempts == max_attempts      -> finalized

    Feature: phase2-aro-completion, Property 24: Retry is bounded by
    max_attempts.
    Validates: Requirements 6.3, 6.4
    """
    # Just below the bound -> re-enqueue.
    below = _FakeDb((boundary - 1, boundary))
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(task_repo, "_get_db", lambda: below)
        r_below = task_repo.reenqueue_or_finalize(1, 1, terminal_status, "r")
    assert r_below["outcome"] == "reenqueued"
    assert r_below["status"] == "pending"

    # At the bound -> finalize.
    at = _FakeDb((boundary, boundary))
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(task_repo, "_get_db", lambda: at)
        r_at = task_repo.reenqueue_or_finalize(1, 1, terminal_status, "r")
    assert r_at["outcome"] == "finalized"
    assert r_at["status"] == terminal_status


def test_property24_missing_task_is_noop():
    """When the task row is absent the function is a no-op (no UPDATE issued).

    Feature: phase2-aro-completion, Property 24: Retry is bounded by
    max_attempts.
    Validates: Requirements 6.3, 6.4
    """
    fake = _FakeDb(None)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(task_repo, "_get_db", lambda: fake)
        result = task_repo.reenqueue_or_finalize(1, 1, "failed", "gone")
    assert result["outcome"] == "noop"
    assert result["status"] is None
    assert fake.updates == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
