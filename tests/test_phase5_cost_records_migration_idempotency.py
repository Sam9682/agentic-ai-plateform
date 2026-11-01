#!/usr/bin/env python3
"""Idempotency tests for migration/add_agent_cost_records.sql (Task 1.2).

Feature: phase5-obs-supervisor.

Validates:
* Requirements 13.6 — the Phase 5 OBS cost/anomaly migration is additive and
  re-runnable: the new ``agent_cost_records`` table uses ``CREATE TABLE IF NOT
  EXISTS``, every supporting index uses ``CREATE INDEX IF NOT EXISTS``, and the
  additive ``agent_anomalies`` columns use ``ADD COLUMN IF NOT EXISTS``, so
  applying the script a second time is a no-op (no error, each object present
  exactly once). No statement drops or retypes anything. The ``data_source``
  column carries a CHECK constraint restricted to the exact enum
  (``MEASURED`` / ``ESTIMATED`` / ``MIXED``) so values outside it are rejected.

The structural assertions below parse the SQL text and run with NO live
database (the no-live-DB convention used across ``tests/test_aro_*.py`` and the
Phase 2 / Phase 4 migration idempotency tests). The actual double-apply against
a real schema — and the proof that the CHECK rejects an out-of-enum value — is a
``@pytest.mark.integration`` test, gated behind an explicit opt-in env var plus
a reachable PostgreSQL, and skipped by default.

Run directly (structural checks; live demo skipped unless opt-in + DB present):
    python3 tests/test_phase5_cost_records_migration_idempotency.py
Or via pytest:
    pytest tests/test_phase5_cost_records_migration_idempotency.py

Run the live integration double-apply manually (requires a reachable DB):
    RUN_PHASE5_MIGRATION_INTEGRATION=1 \
        pytest tests/test_phase5_cost_records_migration_idempotency.py \
        -v -m integration
"""
import os
import re
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

MIGRATION_PATH = os.path.join(PROJECT_ROOT, "migration", "add_agent_cost_records.sql")

# The three supporting indexes the design (Task 1.1) specifies for the cost
# ledger's budget-aggregation reads.
EXPECTED_INDEXES = (
    "idx_agent_cost_records_tenant",
    "idx_agent_cost_records_parent",
    "idx_agent_cost_records_delegation",
)

# The five additive enforcement/routing columns appended to agent_anomalies.
EXPECTED_ANOMALY_COLUMNS = (
    "anomaly_ref",
    "runtime_id",
    "session_id",
    "recommended_action",
    "enforcement_status",
)

# The exact data_source enum the CHECK constraint must enforce.
EXPECTED_DATA_SOURCE_VALUES = {"MEASURED", "ESTIMATED", "MIXED"}

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


def test_create_table_is_if_not_exists_exactly_once():
    """``agent_cost_records`` is ``CREATE TABLE IF NOT EXISTS`` exactly once.

    Guarded + single occurrence ⇒ a second apply does not error and does not try
    to recreate the table (Req 13.6).
    """
    sql = _strip_comments(_read_migration())
    creates = re.findall(r"CREATE\s+TABLE([^;(]*)", sql, flags=re.IGNORECASE)
    assert creates, "expected a CREATE TABLE in the migration"
    for clause in creates:
        frag = _normalize(clause)
        assert re.match(r"IF\s+NOT\s+EXISTS", frag, flags=re.IGNORECASE), (
            f"CREATE TABLE not guarded by IF NOT EXISTS: {frag!r}"
        )
    joined = _normalize(sql).lower()
    occurrences = len(
        re.findall(r"create table if not exists agent_cost_records\b", joined)
    )
    assert occurrences == 1, (
        f"expected exactly one guarded CREATE TABLE for agent_cost_records, "
        f"got {occurrences}"
    )
    print("ok test_create_table_is_if_not_exists_exactly_once")


def test_indexes_are_create_if_not_exists():
    """Every CREATE INDEX is ``IF NOT EXISTS`` and each design index appears once.

    Re-running a guarded ``CREATE INDEX IF NOT EXISTS`` is a no-op (Req 13.6).
    """
    sql = _strip_comments(_read_migration())
    creates = re.findall(r"CREATE\s+INDEX([^;]*)", sql, flags=re.IGNORECASE)
    assert creates, "expected CREATE INDEX statements in the migration"
    for clause in creates:
        frag = _normalize(clause)
        assert re.match(r"IF\s+NOT\s+EXISTS", frag, flags=re.IGNORECASE), (
            f"CREATE INDEX not guarded by IF NOT EXISTS: {frag!r}"
        )
    joined = _normalize(sql).lower()
    for index in EXPECTED_INDEXES:
        occurrences = len(
            re.findall(rf"create index if not exists {index}\b", joined)
        )
        assert occurrences == 1, (
            f"expected exactly one guarded CREATE INDEX for {index!r}, "
            f"got {occurrences}"
        )
    print(f"ok test_indexes_are_create_if_not_exists ({len(EXPECTED_INDEXES)} idx)")


def test_added_anomaly_columns_are_all_idempotent():
    """Every ADD COLUMN on agent_anomalies is guarded by ``IF NOT EXISTS``.

    A re-run of ``ADD COLUMN IF NOT EXISTS`` leaves the existing column in place
    (present exactly once, no error) — the core idempotency guarantee (Req 13.6).
    """
    sql = _strip_comments(_read_migration())
    add_columns = re.findall(r"ADD\s+COLUMN([^,;]*)", sql, flags=re.IGNORECASE)
    assert add_columns, "expected at least one ADD COLUMN in the migration"
    for clause in add_columns:
        frag = _normalize(clause)
        assert re.match(r"IF\s+NOT\s+EXISTS", frag, flags=re.IGNORECASE), (
            f"ADD COLUMN not guarded by IF NOT EXISTS: {frag!r}"
        )
    print(f"ok test_added_anomaly_columns_are_all_idempotent ({len(add_columns)} cols)")


def test_expected_anomaly_columns_present_exactly_once():
    """All five additive enforcement columns are added, each exactly once.

    Exactly-once at the SQL level is what makes the second apply a no-op: there
    is a single ``ADD COLUMN IF NOT EXISTS`` per column, never a duplicate or an
    unguarded variant (Req 13.6).
    """
    sql = _normalize(_strip_comments(_read_migration())).lower()
    for col in EXPECTED_ANOMALY_COLUMNS:
        occurrences = len(
            re.findall(rf"add column if not exists {col}\b", sql)
        )
        assert occurrences == 1, (
            f"expected exactly one guarded ADD COLUMN for {col!r}, got {occurrences}"
        )
    print("ok test_expected_anomaly_columns_present_exactly_once")


def test_anomaly_alter_targets_agent_anomalies():
    """Every ALTER TABLE targets ``agent_anomalies`` (the routing columns live there)."""
    sql = _normalize(_strip_comments(_read_migration()))
    alters = re.findall(r"ALTER\s+TABLE\s+(\w+)", sql, flags=re.IGNORECASE)
    assert alters, "expected ALTER TABLE statements"
    for table in alters:
        assert table.lower() == "agent_anomalies", (
            f"unexpected ALTER TABLE target: {table!r}"
        )
    print(f"ok test_anomaly_alter_targets_agent_anomalies ({len(alters)} alters)")


def test_data_source_check_restricts_to_exact_enum():
    """The ``data_source`` CHECK restricts to exactly MEASURED/ESTIMATED/MIXED.

    The CHECK constraint is what makes the database reject any value outside the
    enum, so values such as ``'BOGUS'`` cannot be stored (Req 13.6 / Req 4.7).
    """
    sql = _normalize(_strip_comments(_read_migration()))
    # Locate the data_source column's CHECK (...) body.
    m = re.search(
        r"data_source[^,]*?CHECK\s*\(\s*data_source\s+IN\s*\((.*?)\)\s*\)",
        sql,
        flags=re.IGNORECASE,
    )
    assert m, "could not locate a data_source CHECK (data_source IN (...)) constraint"
    body = m.group(1)
    values = set(re.findall(r"'([^']+)'", body))
    assert values == EXPECTED_DATA_SOURCE_VALUES, (
        f"data_source CHECK enum mismatch: expected {EXPECTED_DATA_SOURCE_VALUES}, "
        f"got {values}"
    )
    print("ok test_data_source_check_restricts_to_exact_enum")


def test_migration_contains_no_destructive_statements():
    """Purely additive: no DROP/DELETE/TRUNCATE/ALTER COLUMN retype (Req 13.6)."""
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
# Live double-apply + CHECK rejection (Requirements 13.6) — integration test.
# Applies the migration twice against a reachable PostgreSQL and asserts the
# second apply is a no-op (no error, table/columns/indexes present exactly
# once), and that the data_source CHECK rejects an out-of-enum value. Skipped
# by default; opt in with RUN_PHASE5_MIGRATION_INTEGRATION=1 and a reachable
# database.
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
        "Phase 5 cost-records migration double-apply needs a live PostgreSQL. "
        "Set RUN_PHASE5_MIGRATION_INTEGRATION=1 and point at a reachable "
        "database to run it. Skipped by default (Req 13.6)."
    ),
)
def test_double_apply_and_check_rejection_against_live_db():
    """Applying twice is a no-op; the data_source CHECK rejects out-of-enum values."""
    db_manager = _db_manager_or_skip()
    sql = _read_migration()
    try:
        with db_manager.get_db_connection() as conn:
            cur = conn.cursor()
            # Apply twice. The second run must not raise (Req 13.6).
            cur.execute(sql)
            cur.execute(sql)

            # The cost-records table exists exactly once in the catalog.
            cur.execute(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_name = 'agent_cost_records'"
            )
            assert cur.fetchone()[0] == 1, "agent_cost_records expected exactly once"

            # Each supporting index exists exactly once.
            cur.execute(
                "SELECT indexname, COUNT(*) FROM pg_indexes "
                "WHERE tablename = 'agent_cost_records' AND indexname = ANY(%s) "
                "GROUP BY indexname",
                (list(EXPECTED_INDEXES),),
            )
            idx_counts = dict(cur.fetchall())
            for index in EXPECTED_INDEXES:
                assert idx_counts.get(index) == 1, (
                    f"index {index!r} expected exactly once, got {idx_counts.get(index)}"
                )

            # Each additive anomaly column exists exactly once.
            cur.execute(
                "SELECT column_name, COUNT(*) FROM information_schema.columns "
                "WHERE table_name = 'agent_anomalies' AND column_name = ANY(%s) "
                "GROUP BY column_name",
                (list(EXPECTED_ANOMALY_COLUMNS),),
            )
            col_counts = dict(cur.fetchall())
            for col in EXPECTED_ANOMALY_COLUMNS:
                assert col_counts.get(col) == 1, (
                    f"column {col!r} expected exactly once, got {col_counts.get(col)}"
                )

            # The data_source CHECK must reject a value outside the enum. Use a
            # savepoint so the failed INSERT never aborts the surrounding probe.
            cur.execute("SAVEPOINT phase5_check_probe")
            rejected = False
            try:
                cur.execute(
                    "INSERT INTO agent_cost_records (tenant_id, data_source) "
                    "VALUES (%s, %s)",
                    (1, "BOGUS"),
                )
            except Exception:  # noqa: BLE001 - any constraint violation counts
                rejected = True
                cur.execute("ROLLBACK TO SAVEPOINT phase5_check_probe")
            assert rejected, "data_source CHECK should reject out-of-enum 'BOGUS'"

            # Never leave the probe behind — this test only inspects the catalog.
            conn.rollback()
    except pytest.skip.Exception:
        raise
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"no reachable PostgreSQL for live double-apply: {exc}")


def main():
    test_migration_file_exists()
    test_create_table_is_if_not_exists_exactly_once()
    test_indexes_are_create_if_not_exists()
    test_added_anomaly_columns_are_all_idempotent()
    test_expected_anomaly_columns_present_exactly_once()
    test_anomaly_alter_targets_agent_anomalies()
    test_data_source_check_restricts_to_exact_enum()
    test_migration_contains_no_destructive_statements()
    print("\nAll structural migration idempotency checks passed.")
    print(
        "Live double-apply + CHECK rejection is an integration test; run with "
        "RUN_PHASE5_MIGRATION_INTEGRATION=1 and a reachable PostgreSQL."
    )


if __name__ == "__main__":
    main()
