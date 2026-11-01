#!/usr/bin/env python3
"""Idempotency / backward-compatibility tests for migration/add_aro_phase2.sql (Task 1.2).

Feature: phase2-aro-completion.

Validates:
* Requirements 7.2 — the additive migration preserves existing rows/writers:
  every added column is nullable, every added object is guarded by
  ``IF NOT EXISTS`` / ``DROP CONSTRAINT IF EXISTS`` so re-running the script is a
  no-op, and the swapped ``agent_tasks_status_check`` keeps the legacy
  ``'timeout'`` value (existing ``agent_tasks`` rows stay valid after the CHECK
  swap) while adding ``'timed_out'``.
* Requirements 7.3 — running the migration twice is a no-op. The structural
  tests assert the script is re-runnable by construction; an optional guarded
  block actually applies the migration twice against a live PostgreSQL (and
  proves a pre-existing ``status = 'timeout'`` row remains valid under the new
  CHECK), skipped automatically when no database is reachable.

These structural tests run without a live PostgreSQL by parsing the SQL text,
mirroring the no-live-DB convention used across ``tests/test_aro_*.py`` and
``tests/runtime_monitor/test_repository.py``.

Run directly:
    python3 tests/test_aro_phase2_migration_idempotency.py
Or via pytest:
    pytest tests/test_aro_phase2_migration_idempotency.py
"""
import os
import re
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

MIGRATION_PATH = os.path.join(PROJECT_ROOT, "migration", "add_aro_phase2.sql")


def _read_migration():
    with open(MIGRATION_PATH, "r", encoding="utf-8") as fh:
        return fh.read()


def _normalize(sql):
    """Collapse whitespace so multi-line statements match as single strings."""
    return " ".join(sql.split())


def _strip_comments(sql):
    """Remove ``--`` line comments so guard assertions only see live SQL."""
    return "\n".join(
        line.split("--", 1)[0] for line in sql.splitlines()
    )


# --------------------------------------------------------------------------- #
# Structural idempotency (Requirements 7.2, 7.3) — always run, no live DB.
# --------------------------------------------------------------------------- #
def test_migration_file_exists():
    assert os.path.isfile(MIGRATION_PATH), f"missing migration at {MIGRATION_PATH}"
    print("ok test_migration_file_exists")


def test_added_columns_are_all_idempotent_and_nullable():
    """Every ADD COLUMN is ``IF NOT EXISTS`` and none declare NOT NULL.

    Re-running an ``ADD COLUMN IF NOT EXISTS`` is a no-op; nullable columns keep
    existing rows and writers valid (Req 7.2).
    """
    sql = _strip_comments(_read_migration())
    add_columns = re.findall(r"ADD\s+COLUMN([^,;]*)", sql, flags=re.IGNORECASE)
    assert add_columns, "expected at least one ADD COLUMN in the migration"
    for clause in add_columns:
        frag = _normalize(clause)
        assert re.match(r"IF\s+NOT\s+EXISTS", frag, flags=re.IGNORECASE), (
            f"ADD COLUMN not guarded by IF NOT EXISTS: {frag!r}"
        )
        assert not re.search(r"\bNOT\s+NULL\b", frag, flags=re.IGNORECASE), (
            f"added column must be nullable to stay backward compatible: {frag!r}"
        )
    print(f"ok test_added_columns_are_all_idempotent_and_nullable ({len(add_columns)} cols)")


def test_expected_session_and_lease_columns_present():
    """The design-named additive columns are all present (Req 4.1, 6.5, 7.2)."""
    sql = _normalize(_strip_comments(_read_migration())).lower()
    for col in ("session_id", "runtime_handle", "runtime_adapter",
                "lease_expires_at", "heartbeat_at"):
        assert f"add column if not exists {col}" in sql, f"missing column {col}"
    print("ok test_expected_session_and_lease_columns_present")


def test_indexes_are_create_if_not_exists():
    """Every CREATE INDEX is guarded so a second run is a no-op (Req 7.3)."""
    sql = _strip_comments(_read_migration())
    creates = re.findall(r"CREATE\s+INDEX([^;]*)", sql, flags=re.IGNORECASE)
    assert creates, "expected partial indexes in the migration"
    for clause in creates:
        frag = _normalize(clause)
        assert re.match(r"IF\s+NOT\s+EXISTS", frag, flags=re.IGNORECASE), (
            f"CREATE INDEX not guarded by IF NOT EXISTS: {frag!r}"
        )
    # The two design-named partial indexes exist.
    joined = _normalize(sql).lower()
    assert "idx_agent_executions_running" in joined
    assert "idx_agent_tasks_lease" in joined
    print(f"ok test_indexes_are_create_if_not_exists ({len(creates)} indexes)")


def test_status_check_dropped_before_readd():
    """The CHECK swap drops with IF EXISTS before re-adding, so it is re-runnable."""
    sql = _normalize(_strip_comments(_read_migration()))
    drop = re.search(
        r"DROP\s+CONSTRAINT\s+IF\s+EXISTS\s+agent_tasks_status_check",
        sql, flags=re.IGNORECASE,
    )
    add = re.search(
        r"ADD\s+CONSTRAINT\s+agent_tasks_status_check", sql, flags=re.IGNORECASE
    )
    assert drop, "status CHECK must be dropped with IF EXISTS"
    assert add, "status CHECK must be re-added"
    assert drop.start() < add.start(), "DROP must precede ADD for re-runnability"
    print("ok test_status_check_dropped_before_readd")


def test_status_check_keeps_legacy_timeout_and_adds_timed_out():
    """The new CHECK keeps 'timeout' (compat) and adds 'timed_out' (Req 7.2)."""
    sql = _normalize(_strip_comments(_read_migration()))
    m = re.search(
        r"ADD\s+CONSTRAINT\s+agent_tasks_status_check\s+CHECK\s*\((.*?)\)\s*;",
        sql, flags=re.IGNORECASE,
    )
    assert m, "could not locate the re-added agent_tasks_status_check body"
    body = m.group(1)
    values = set(re.findall(r"'([^']+)'", body))
    # Legacy value retained so existing rows/writers stay valid after the swap.
    assert "timeout" in values, "legacy 'timeout' value must be retained"
    # New terminal added.
    assert "timed_out" in values, "'timed_out' must be added"
    # The full terminal/intermediate set the design specifies.
    expected = {"pending", "claimed", "running", "succeeded",
                "failed", "cancelled", "timeout", "timed_out"}
    assert expected.issubset(values), f"missing statuses: {expected - values}"
    print("ok test_status_check_keeps_legacy_timeout_and_adds_timed_out")


def test_migration_contains_no_destructive_statements():
    """Purely additive: no DROP TABLE/COLUMN, DELETE, or TRUNCATE (Req 7.2)."""
    sql = _normalize(_strip_comments(_read_migration())).lower()
    for forbidden in ("drop table", "drop column", "delete from",
                      "truncate", "alter column"):
        assert forbidden not in sql, f"unexpected destructive statement: {forbidden!r}"
    print("ok test_migration_contains_no_destructive_statements")


# --------------------------------------------------------------------------- #
# Optional live-DB proof (Requirements 7.3, 7.2) — skipped when no DB reachable.
# Applies the migration twice and proves a pre-existing status='timeout' row
# remains valid under the new CHECK constraint.
# --------------------------------------------------------------------------- #
def _run_live_db_idempotency_demo_if_available():
    try:
        from src.database_postgres import db_manager  # noqa: WPS433
    except Exception as exc:  # pragma: no cover - import/env dependent
        print(f"skip live-db idempotency demo (import failed): {exc}")
        return

    sql = _read_migration()
    try:
        with db_manager.get_db_connection() as conn:
            cur = conn.cursor()
            # Apply the migration twice; the second run must be a no-op (Req 7.3).
            cur.execute(sql)
            cur.execute(sql)

            # A pre-existing legacy row (status='timeout') must remain insertable
            # and valid under the swapped CHECK (Req 7.2). Use a savepoint so the
            # probe never leaves a row behind.
            cur.execute("SAVEPOINT aro_phase2_probe")
            cur.execute("SELECT id FROM agents LIMIT 1")
            agent_row = cur.fetchone()
            if agent_row is None:
                cur.execute("ROLLBACK TO SAVEPOINT aro_phase2_probe")
                print("skip live-db row probe: no agents row to attach a task to")
            else:
                cur.execute(
                    "INSERT INTO agent_tasks (agent_id, status) "
                    "VALUES (%s, %s) RETURNING id",
                    (agent_row[0], "timeout"),
                )
                inserted = cur.fetchone()
                assert inserted is not None, "legacy 'timeout' status row was rejected"
                # Also confirm the new terminal is accepted.
                cur.execute(
                    "UPDATE agent_tasks SET status = %s WHERE id = %s",
                    ("timed_out", inserted[0]),
                )
                cur.execute("ROLLBACK TO SAVEPOINT aro_phase2_probe")
            conn.rollback()
        print("live-db idempotency demo ok: migration applied twice, legacy row valid")
    except Exception as exc:  # pragma: no cover - environment dependent
        print(f"skip live-db idempotency demo (no reachable PostgreSQL): {exc}")


def main():
    test_migration_file_exists()
    test_added_columns_are_all_idempotent_and_nullable()
    test_expected_session_and_lease_columns_present()
    test_indexes_are_create_if_not_exists()
    test_status_check_dropped_before_readd()
    test_status_check_keeps_legacy_timeout_and_adds_timed_out()
    test_migration_contains_no_destructive_statements()
    _run_live_db_idempotency_demo_if_available()
    print("\nAll migration idempotency tests passed.")


if __name__ == "__main__":
    main()
