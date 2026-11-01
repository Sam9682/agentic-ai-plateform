#!/usr/bin/env python3
"""Property test for tenant-scoped task writes (Task 13.2).

Feature: ARO task store — tenant isolation of mutating writes.

Covers the task repository's two terminal-write entry points,
``mark_running(tenant_id, task_id)`` and
``complete(tenant_id, task_id, status, result=None)`` in
``src/aro/task_repository.py``. Both issue a single UPDATE scoped by
``WHERE tenant_id = %s AND id = %s`` and return ``bool(rows)`` — truthy when a
matching row was updated, falsy otherwise. This is the tenant-isolation
guarantee of Req 6.8: a write carrying a tenant_id that does NOT own the task
must update ZERO rows (no cross-tenant mutation), while a write carrying the
owning tenant_id updates the row.

No live DB / SSH: ``task_repo._get_db`` is monkeypatched to a fake db_manager
whose ``execute_query`` models a single-row table keyed by ``(tenant_id, id)``.
The simulated UPDATE affects the row only when BOTH tenant_id AND id match the
stored owner key, returning the affected-row list accordingly (so
``bool(rows)`` reflects real UPDATE semantics).

Run directly:
    python3 tests/test_aro_task_tenant_scope.py
Or via pytest:
    pytest tests/test_aro_task_tenant_scope.py
"""
import os
import re
import sys

from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.aro import task_repository as task_repo  # noqa: E402


# --------------------------------------------------------------------------- #
# Fake db_manager: a single-row table keyed by (tenant_id, id).
#
# The real ``mark_running`` / ``complete`` call ``execute_query(sql, params)``
# with a trailing ``(..., tenant_id, task_id)`` params tuple and WITHOUT
# fetch_one/fetch_all, expecting the affected-row list back (its truthiness is
# the return value). This fake parses the two writer SQL shapes, applies the
# ``tenant_id AND id`` scope against the stored owner key, mutates the row only
# on a full match, and returns ``[row]`` on a hit / ``[]`` on a miss — exactly
# mirroring UPDATE ... WHERE tenant_id=%s AND id=%s affected-row semantics.
# --------------------------------------------------------------------------- #
class FakeDbManager:
    def __init__(self, owner_tenant, task_id):
        # The single stored row and its owning (tenant_id, id) key.
        self.owner_tenant = owner_tenant
        self.task_id = task_id
        self.row = {
            "tenant_id": owner_tenant,
            "id": task_id,
            "status": "claimed",
            "result": None,
            "finished_at": None,
        }
        self.writes = 0  # count of UPDATEs that actually mutated the row

    def execute_query(self, sql, params=None, fetch_one=False, fetch_all=False):
        params = params or ()
        # Both writer UPDATEs scope by a trailing (tenant_id, id) pair.
        tenant_id, task_id = params[-2], params[-1]
        matched = (tenant_id == self.owner_tenant and task_id == self.task_id)
        if not matched:
            return []  # zero rows affected -> falsy -> no cross-tenant write

        # Apply the mutation that the specific UPDATE statement expresses.
        if re.search(r"SET\s+status\s*=\s*'running'", sql):
            self.row["status"] = "running"
        else:
            # complete(): SET status = %s, result = %s, finished_at = ...
            # params layout: (status, result_json, tenant_id, task_id)
            self.row["status"] = params[0]
            self.row["result"] = params[1]
            self.row["finished_at"] = "2026-01-01T00:00:00Z"
        self.writes += 1
        return [dict(self.row)]  # one affected row -> truthy


# Keep ids in a realistic positive range. The writer tenant is drawn
# independently so it matches the owner only by chance; we also always exercise
# the exact-match case explicitly below.
_IDS = st.integers(min_value=1, max_value=10_000)
_STATUS = st.sampled_from(["succeeded", "failed", "cancelled", "timed_out"])
_RESULT = st.one_of(
    st.none(),
    st.dictionaries(
        keys=st.text(min_size=1, max_size=8),
        values=st.one_of(st.integers(-1000, 1000), st.text(max_size=16), st.booleans()),
        max_size=4,
    ),
)


def _install_fake_db(owner_tenant, task_id):
    """Point task_repo._get_db at a fresh single-row fake table.

    Returns (fake, restore) where restore() puts the original factory back.
    Rebinds the module-level ``_get_db`` so every repo call in this test hits
    the fake instead of the real ``database_postgres.db_manager`` (no live DB).
    """
    fake = FakeDbManager(owner_tenant, task_id)
    original = task_repo._get_db
    task_repo._get_db = lambda: fake

    def restore():
        task_repo._get_db = original

    return fake, restore


# --------------------------------------------------------------------------- #
# Property 27: Task writes are tenant-scoped
# Validates: Requirements 6.8
# --------------------------------------------------------------------------- #
@given(
    owner_tenant=_IDS,
    task_id=_IDS,
    other_tenant=_IDS,
    status=_STATUS,
    result=_RESULT,
)
@settings(max_examples=200)
def test_task_writes_are_tenant_scoped(owner_tenant, task_id, other_tenant,
                                       status, result):
    """Feature: phase2-aro-completion, Property 27: Task writes are tenant-scoped.

    For a task owned by ``owner_tenant``, both ``mark_running`` and ``complete``
    mutate the row (and return truthy) iff the write carries the owning tenant
    id; any writer tenant that is NOT the owner updates ZERO rows (returns
    falsy) and leaves the row unchanged — the Req 6.8 cross-tenant isolation
    guarantee. The matching-tenant write is always exercised, and a derived
    mismatched tenant is always exercised, regardless of the arbitrary
    ``other_tenant`` draw.
    """
    # A tenant guaranteed NOT to own the task: use the arbitrary other_tenant
    # when it differs, otherwise a deterministic non-owner.
    mismatch_tenant = other_tenant if other_tenant != owner_tenant else owner_tenant + 1

    # --- mark_running --------------------------------------------------- #
    fake, restore = _install_fake_db(owner_tenant, task_id)
    try:
        # Mismatched tenant: zero rows -> falsy, no mutation.
        assert task_repo.mark_running(mismatch_tenant, task_id) is False
        assert fake.writes == 0
        assert fake.row["status"] == "claimed"
        # Right tenant but wrong id: zero rows -> falsy, no mutation.
        assert task_repo.mark_running(owner_tenant, task_id + 1) is False
        assert fake.writes == 0
        assert fake.row["status"] == "claimed"
        # Owning tenant + id: one row -> truthy, row mutated to running.
        assert task_repo.mark_running(owner_tenant, task_id) is True
        assert fake.writes == 1
        assert fake.row["status"] == "running"
    finally:
        restore()

    # --- complete ------------------------------------------------------- #
    fake, restore = _install_fake_db(owner_tenant, task_id)
    try:
        # Mismatched tenant: zero rows -> falsy, terminal status NOT recorded.
        assert task_repo.complete(mismatch_tenant, task_id, status, result) is False
        assert fake.writes == 0
        assert fake.row["status"] == "claimed"
        assert fake.row["finished_at"] is None
        # Right tenant but wrong id: zero rows -> falsy, no mutation.
        assert task_repo.complete(owner_tenant, task_id + 1, status, result) is False
        assert fake.writes == 0
        assert fake.row["status"] == "claimed"
        # Owning tenant + id: one row -> truthy, terminal status recorded.
        assert task_repo.complete(owner_tenant, task_id, status, result) is True
        assert fake.writes == 1
        assert fake.row["status"] == status
        assert fake.row["finished_at"] is not None
    finally:
        restore()


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
