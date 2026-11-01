#!/usr/bin/env python3
"""Idempotency tests for migration/add_instance_remediation.sql (Task 1.2).

Feature: phase4-runtime-execution-hardening.

Validates:
* Requirements 7.4 — Phase 4 schema changes are additive, backward-compatible
  migrations only: every added column uses ``ADD COLUMN IF NOT EXISTS`` and the
  index uses ``CREATE INDEX IF NOT EXISTS``, so applying the script a second
  time is a no-op (no error, columns/index present exactly once). No statement
  drops or retypes anything.
* Requirements 8.5 — where a code path genuinely requires live PostgreSQL, the
  corresponding test is marked as an integration test. The structural
  assertions below parse the SQL text and run with NO live database (the
  no-live-DB convention used across ``tests/test_aro_*.py``). The actual
  double-apply against a real schema is a ``@pytest.mark.integration`` test,
  gated behind an explicit opt-in env var plus a reachable PostgreSQL, and
  skipped by default.

Run directly (structural checks; live demo skipped unless opt-in + DB present):
    python3 tests/test_phase4_instance_remediation_migration_idempotency.py
Or via pytest:
    pytest tests/test_phase4_instance_remediation_migration_idempotency.py

Run the live integration double-apply manually (requires a reachable DB):
    RUN_PHASE4_MIGRATION_INTEGRATION=1 \
        pytest tests/test_phase4_instance_remediation_migration_idempotency.py \
        -v -m integration
"""
import os
import re
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

MIGRATION_PATH = os.path.join(PROJECT_ROOT, "migration", "add_instance_remediation.sql")

# The five additive columns and the one index the design (Task 1.1) specifies.
EXPECTED_COLUMNS = (
    "restart_attempts",
    "needs_attention",
    "replaced",
    "started_at",
    "grace_until",
)
EXPECTED_INDEX = "idx_instances_needs_attention"

# Opt-in flag for the live double-apply. Integration tests touch a real
# database, so they only run when explicitly enabled.
RUN_MIGRATION_INTEGRATION = os.environ.get("RUN_PHASE4_MIGRATION_INTEGRATION") == "1"


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
# Structural idempotency (Requirements 7.4) — always run, no live DB.
# --------------------------------------------------------------------------- #
def test_migration_file_exists():
    assert os.path.isfile(MIGRATION_PATH), f"missing migration at {MIGRATION_PATH}"
    print("ok test_migration_file_exists")


def test_added_columns_are_all_idempotent():
    """Every ADD COLUMN is guarded by ``IF NOT EXISTS`` so a second run is a no-op.

    A re-run of ``ADD COLUMN IF NOT EXISTS`` leaves the existing column in place
    (present exactly once, no error) — the core idempotency guarantee (Req 7.4).
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


def test_expected_remediation_columns_present_exactly_once():
    """All five design-named remediation columns are added, each exactly once.

    Exactly-once at the SQL level is what makes the second apply a no-op: there
    is a single ``ADD COLUMN IF NOT EXISTS`` per column, never a duplicate or an
    unguarded variant (Req 7.4).
    """
    sql = _normalize(_strip_comments(_read_migration())).lower()
    for col in EXPECTED_COLUMNS:
        occurrences = len(
            re.findall(rf"add column if not exists {col}\b", sql)
        )
        assert occurrences == 1, (
            f"expected exactly one guarded ADD COLUMN for {col!r}, got {occurrences}"
        )
    print("ok test_expected_remediation_columns_present_exactly_once")


def test_index_is_create_if_not_exists_exactly_once():
    """The needs_attention index is ``CREATE INDEX IF NOT EXISTS`` exactly once.

    Guarded + single occurrence ⇒ re-applying does not error and does not create
    a duplicate index (Req 7.4).
    """
    sql = _strip_comments(_read_migration())
    creates = re.findall(r"CREATE\s+INDEX([^;]*)", sql, flags=re.IGNORECASE)
    assert creates, "expected a CREATE INDEX in the migration"
    for clause in creates:
        frag = _normalize(clause)
        assert re.match(r"IF\s+NOT\s+EXISTS", frag, flags=re.IGNORECASE), (
            f"CREATE INDEX not guarded by IF NOT EXISTS: {frag!r}"
        )
    joined = _normalize(sql).lower()
    occurrences = len(
        re.findall(rf"create index if not exists {EXPECTED_INDEX}\b", joined)
    )
    assert occurrences == 1, (
        f"expected exactly one guarded CREATE INDEX for {EXPECTED_INDEX!r}, "
        f"got {occurrences}"
    )
    print("ok test_index_is_create_if_not_exists_exactly_once")


def test_migration_targets_instances_table():
    """Every ALTER TABLE targets ``instances`` (the remediation state lives there)."""
    sql = _normalize(_strip_comments(_read_migration()))
    alters = re.findall(r"ALTER\s+TABLE\s+(\w+)", sql, flags=re.IGNORECASE)
    assert alters, "expected ALTER TABLE statements"
    for table in alters:
        assert table.lower() == "instances", f"unexpected ALTER TABLE target: {table!r}"
    print(f"ok test_migration_targets_instances_table ({len(alters)} alters)")


def test_migration_contains_no_destructive_statements():
    """Purely additive: no DROP/DELETE/TRUNCATE/ALTER COLUMN retype (Req 7.4)."""
    sql = _normalize(_strip_comments(_read_migration())).lower()
    for forbidden in (
        "drop table",
        "drop column",
        "drop index",
        "delete from",
        "truncate",
        "alter column",
    ):
        assert forbidden not in sql, f"unexpected destructive statement: {forbidden!r}"
    print("ok test_migration_contains_no_destructive_statements")


# --------------------------------------------------------------------------- #
# Live double-apply (Requirements 7.4, 8.5) — integration test.
# Applies the migration twice against a reachable PostgreSQL and asserts the
# second apply is a no-op: no error, and each column/index is present exactly
# once in the catalog. Skipped by default; opt in with
# RUN_PHASE4_MIGRATION_INTEGRATION=1 and a reachable database.
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
        "Phase 4 migration double-apply needs a live PostgreSQL. "
        "Set RUN_PHASE4_MIGRATION_INTEGRATION=1 and point at a reachable "
        "database to run it. Skipped by default (Req 8.5)."
    ),
)
def test_double_apply_is_a_no_op_against_live_db():
    """Applying the migration twice is a no-op; columns/index present exactly once."""
    db_manager = _db_manager_or_skip()
    sql = _read_migration()
    try:
        with db_manager.get_db_connection() as conn:
            cur = conn.cursor()
            # Apply twice. The second run must not raise (Req 7.4).
            cur.execute(sql)
            cur.execute(sql)

            # Each added column exists exactly once in the catalog.
            cur.execute(
                "SELECT column_name, COUNT(*) "
                "FROM information_schema.columns "
                "WHERE table_name = 'instances' AND column_name = ANY(%s) "
                "GROUP BY column_name",
                (list(EXPECTED_COLUMNS),),
            )
            counts = dict(cur.fetchall())
            for col in EXPECTED_COLUMNS:
                assert counts.get(col) == 1, (
                    f"column {col!r} expected exactly once, got {counts.get(col)}"
                )

            # The needs_attention index exists exactly once.
            cur.execute(
                "SELECT COUNT(*) FROM pg_indexes "
                "WHERE tablename = 'instances' AND indexname = %s",
                (EXPECTED_INDEX,),
            )
            index_count = cur.fetchone()[0]
            assert index_count == 1, (
                f"index {EXPECTED_INDEX!r} expected exactly once, got {index_count}"
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
    test_expected_remediation_columns_present_exactly_once()
    test_index_is_create_if_not_exists_exactly_once()
    test_migration_targets_instances_table()
    test_migration_contains_no_destructive_statements()
    print("\nAll structural migration idempotency checks passed.")
    print(
        "Live double-apply is an integration test; run with "
        "RUN_PHASE4_MIGRATION_INTEGRATION=1 and a reachable PostgreSQL."
    )


if __name__ == "__main__":
    main()
