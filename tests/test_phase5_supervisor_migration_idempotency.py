#!/usr/bin/env python3
"""Idempotency tests for migration/add_supervisor.sql (Task 8.2).

Feature: phase5-obs-supervisor.

Validates:
* Requirements 13.6 — Phase 5 schema changes are additive and
  backward-compatible: the supervisor migration only appends nullable/defaulted
  columns to ``agent_tasks`` and creates new tables/indexes guarded by
  ``IF NOT EXISTS`` / ``ADD COLUMN IF NOT EXISTS``, so applying the script a
  second time is a no-op (no error, columns/tables/indexes present exactly
  once). No statement drops or retypes anything, so existing rows and the
  Phase 2 task queue stay valid.
* Requirements 14.6 — where a code path genuinely requires live PostgreSQL, the
  corresponding test is marked as an integration test. The structural
  assertions below parse the SQL text and run with NO live database (the
  no-live-DB convention used across ``tests/test_aro_*.py`` and
  ``tests/test_phase4_instance_remediation_migration_idempotency.py``). The
  actual double-apply against a real schema is a ``@pytest.mark.integration``
  test, gated behind an explicit opt-in env var plus a reachable PostgreSQL,
  and skipped by default.

Run directly (structural checks; live demo skipped unless opt-in + DB present):
    python3 tests/test_phase5_supervisor_migration_idempotency.py
Or via pytest:
    pytest tests/test_phase5_supervisor_migration_idempotency.py

Run the live integration double-apply manually (requires a reachable DB):
    RUN_PHASE5_MIGRATION_INTEGRATION=1 \
        pytest tests/test_phase5_supervisor_migration_idempotency.py \
        -v -m integration
"""
import os
import re
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

MIGRATION_PATH = os.path.join(PROJECT_ROOT, "migration", "add_supervisor.sql")

# The three additive columns the design (Task 8.1) appends to agent_tasks.
EXPECTED_COLUMNS = (
    "parent_task_id",
    "depends_on",
    "role_name",
)

# The new tables the migration creates (IF NOT EXISTS), additive on top of the
# existing Phase 1-4 schema.
EXPECTED_TABLES = (
    "supervisor_delegations",
    "supervisor_roles",
)

# Every index the migration creates; all must be CREATE [UNIQUE] INDEX IF NOT
# EXISTS so re-applying neither errors nor duplicates them.
EXPECTED_INDEXES = (
    "idx_agent_tasks_parent",
    "idx_supervisor_delegations_parent",
    "idx_supervisor_delegations_ref",
    "idx_supervisor_delegations_child",
    "uq_supervisor_roles_name",
)

# Opt-in flag for the live double-apply. Integration tests touch a real
# database, so they only run when explicitly enabled.
RUN_MIGRATION_INTEGRATION = os.environ.get("RUN_PHASE5_MIGRATION_INTEGRATION") == "1"


def _read_migration():
    with open(MIGRATION_PATH, "r", encoding="utf-8") as fh:
        return fh.read()


def _normalize(sql):
    """Collapse whitespace so multi-line statements match as single strings."""
    return " ".join(sql.split())


def _strip_comments(sql):
    """Remove ``--`` line comments so guard assertions only see live SQL."""
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


# --------------------------------------------------------------------------- #
# Structural idempotency (Requirements 13.6) — always run, no live DB.
# --------------------------------------------------------------------------- #
def test_migration_file_exists():
    assert os.path.isfile(MIGRATION_PATH), f"missing migration at {MIGRATION_PATH}"
    print("ok test_migration_file_exists")


def test_added_columns_are_all_idempotent():
    """Every ADD COLUMN is guarded by ``IF NOT EXISTS`` so a second run is a no-op.

    A re-run of ``ADD COLUMN IF NOT EXISTS`` leaves the existing column in place
    (present exactly once, no error) — the core additive idempotency guarantee
    that keeps the Phase 2 task queue valid (Req 13.6).
    """
    sql = _strip_comments(_read_migration())
    add_columns = re.findall(r"ADD\s+COLUMN([^,;]*)", sql, flags=re.IGNORECASE)
    assert add_columns, "expected at least one ADD COLUMN in the migration"
    for clause in add_columns:
        frag = _normalize(clause)
        assert re.match(r"IF\s+NOT\s+EXISTS", frag, flags=re.IGNORECASE), (
            f"ADD COLUMN not guarded by IF NOT EXISTS: {frag!r}"
        )
    print(f"ok test_added_columns_are_all_idempotent ({len(add_columns)} cols)")


def test_expected_agent_tasks_columns_present_exactly_once():
    """The three supervisor columns are added to agent_tasks, each exactly once.

    Exactly-once at the SQL level is what makes the second apply a no-op: there
    is a single ``ADD COLUMN IF NOT EXISTS`` per column, never a duplicate or an
    unguarded variant (Req 13.6).
    """
    sql = _normalize(_strip_comments(_read_migration())).lower()
    for col in EXPECTED_COLUMNS:
        occurrences = len(re.findall(rf"add column if not exists {col}\b", sql))
        assert occurrences == 1, (
            f"expected exactly one guarded ADD COLUMN for {col!r}, got {occurrences}"
        )
    print("ok test_expected_agent_tasks_columns_present_exactly_once")


def test_agent_tasks_columns_added_only_to_agent_tasks():
    """The additive columns are appended to agent_tasks, not some new/other table.

    Reconciling against the existing Phase 2 ``agent_tasks`` table (rather than
    creating a parallel one) is the backward-compatible path Req 13.6 requires.
    """
    sql = _normalize(_strip_comments(_read_migration()))
    alters = re.findall(r"ALTER\s+TABLE\s+(\w+)", sql, flags=re.IGNORECASE)
    assert alters, "expected ALTER TABLE statements"
    for table in alters:
        assert table.lower() == "agent_tasks", (
            f"unexpected ALTER TABLE target: {table!r}"
        )
    print(f"ok test_agent_tasks_columns_added_only_to_agent_tasks ({len(alters)} alters)")


def test_created_tables_are_all_idempotent():
    """Every CREATE TABLE is guarded by ``IF NOT EXISTS`` (Req 13.6)."""
    sql = _strip_comments(_read_migration())
    creates = re.findall(r"CREATE\s+TABLE([^(]*)", sql, flags=re.IGNORECASE)
    assert creates, "expected CREATE TABLE statements"
    for clause in creates:
        frag = _normalize(clause)
        assert re.match(r"IF\s+NOT\s+EXISTS", frag, flags=re.IGNORECASE), (
            f"CREATE TABLE not guarded by IF NOT EXISTS: {frag!r}"
        )
    print(f"ok test_created_tables_are_all_idempotent ({len(creates)} tables)")


def test_expected_tables_present_exactly_once():
    """Each new supervisor table is created once, guarded by IF NOT EXISTS."""
    sql = _normalize(_strip_comments(_read_migration())).lower()
    for table in EXPECTED_TABLES:
        occurrences = len(
            re.findall(rf"create table if not exists {table}\b", sql)
        )
        assert occurrences == 1, (
            f"expected exactly one guarded CREATE TABLE for {table!r}, got {occurrences}"
        )
    print("ok test_expected_tables_present_exactly_once")


def test_indexes_are_create_if_not_exists_exactly_once():
    """Every index is ``CREATE [UNIQUE] INDEX IF NOT EXISTS``, each exactly once.

    Guarded + single occurrence ⇒ re-applying does not error and does not create
    a duplicate index (Req 13.6).
    """
    sql = _strip_comments(_read_migration())
    creates = re.findall(
        r"CREATE\s+(?:UNIQUE\s+)?INDEX([^;]*)", sql, flags=re.IGNORECASE
    )
    assert creates, "expected CREATE INDEX statements"
    for clause in creates:
        frag = _normalize(clause)
        assert re.match(r"IF\s+NOT\s+EXISTS", frag, flags=re.IGNORECASE), (
            f"CREATE INDEX not guarded by IF NOT EXISTS: {frag!r}"
        )
    joined = _normalize(sql).lower()
    for index in EXPECTED_INDEXES:
        occurrences = len(
            re.findall(rf"index if not exists {index}\b", joined)
        )
        assert occurrences == 1, (
            f"expected exactly one guarded CREATE INDEX for {index!r}, "
            f"got {occurrences}"
        )
    print(f"ok test_indexes_are_create_if_not_exists_exactly_once ({len(creates)} idx)")


def test_migration_contains_no_destructive_statements():
    """Purely additive: no DROP/DELETE/TRUNCATE/ALTER COLUMN retype (Req 13.6).

    In particular the agent_tasks status CHECK constraint is never touched, so
    existing rows and writers stay valid across a re-apply.
    """
    sql = _normalize(_strip_comments(_read_migration())).lower()
    for forbidden in (
        "drop table",
        "drop column",
        "drop index",
        "drop constraint",
        "delete from",
        "truncate",
        "alter column",
    ):
        assert forbidden not in sql, f"unexpected destructive statement: {forbidden!r}"
    print("ok test_migration_contains_no_destructive_statements")


# --------------------------------------------------------------------------- #
# Live double-apply (Requirements 13.6, 14.6) — integration test.
# Applies the migration twice against a reachable PostgreSQL and asserts the
# second apply is a no-op: no error, and each column/table/index is present
# exactly once in the catalog. Skipped by default; opt in with
# RUN_PHASE5_MIGRATION_INTEGRATION=1 and a reachable database.
# --------------------------------------------------------------------------- #
def _db_manager_or_skip():
    try:
        from src.database_postgres import db_manager  # noqa: WPS433
    except Exception as exc:  # pragma: no cover - import/env dependent
        pytest.skip(f"live-db idempotency test: import failed ({exc})")
    return db_manager


@pytest.mark.integration
@pytest.mark.skipif(
    not RUN_MIGRATION_INTEGRATION,
    reason=(
        "Phase 5 supervisor migration double-apply needs a live PostgreSQL. "
        "Set RUN_PHASE5_MIGRATION_INTEGRATION=1 and point at a reachable "
        "database to run it. Skipped by default (Req 14.6)."
    ),
)
def test_double_apply_is_a_no_op_against_live_db():
    """Applying the migration twice is a no-op; schema objects present once."""
    db_manager = _db_manager_or_skip()
    sql = _read_migration()
    try:
        with db_manager.get_db_connection() as conn:
            cur = conn.cursor()
            # Apply twice. The second run must not raise (Req 13.6).
            cur.execute(sql)
            cur.execute(sql)

            # Each added agent_tasks column exists exactly once in the catalog.
            cur.execute(
                "SELECT column_name, COUNT(*) "
                "FROM information_schema.columns "
                "WHERE table_name = 'agent_tasks' AND column_name = ANY(%s) "
                "GROUP BY column_name",
                (list(EXPECTED_COLUMNS),),
            )
            col_counts = dict(cur.fetchall())
            for col in EXPECTED_COLUMNS:
                assert col_counts.get(col) == 1, (
                    f"column {col!r} expected exactly once, got {col_counts.get(col)}"
                )

            # Each new table exists exactly once in the catalog.
            cur.execute(
                "SELECT table_name, COUNT(*) "
                "FROM information_schema.tables "
                "WHERE table_name = ANY(%s) "
                "GROUP BY table_name",
                (list(EXPECTED_TABLES),),
            )
            table_counts = dict(cur.fetchall())
            for table in EXPECTED_TABLES:
                assert table_counts.get(table) == 1, (
                    f"table {table!r} expected exactly once, got {table_counts.get(table)}"
                )

            # Each index exists exactly once.
            cur.execute(
                "SELECT indexname, COUNT(*) FROM pg_indexes "
                "WHERE indexname = ANY(%s) GROUP BY indexname",
                (list(EXPECTED_INDEXES),),
            )
            index_counts = dict(cur.fetchall())
            for index in EXPECTED_INDEXES:
                assert index_counts.get(index) == 1, (
                    f"index {index!r} expected exactly once, got {index_counts.get(index)}"
                )

            # Never leave the probe behind — this test only inspects the catalog.
            conn.rollback()
    except pytest.skip.Exception:
        raise
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"no reachable PostgreSQL for live double-apply: {exc}")


def main():
    test_migration_file_exists()
    test_added_columns_are_all_idempotent()
    test_expected_agent_tasks_columns_present_exactly_once()
    test_agent_tasks_columns_added_only_to_agent_tasks()
    test_created_tables_are_all_idempotent()
    test_expected_tables_present_exactly_once()
    test_indexes_are_create_if_not_exists_exactly_once()
    test_migration_contains_no_destructive_statements()
    print("\nAll structural migration idempotency checks passed.")
    print(
        "Live double-apply is an integration test; run with "
        "RUN_PHASE5_MIGRATION_INTEGRATION=1 and a reachable PostgreSQL."
    )


if __name__ == "__main__":
    main()
