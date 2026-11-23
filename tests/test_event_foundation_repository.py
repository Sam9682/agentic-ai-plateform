"""ABF/AET event foundation (Phase 1): events repository.

* append_event persists the normalized columns, derives the category for legacy
  emitters, defaults provenance to control_plane, flags duplicates.
* query_events is tenant-scoped, parameterized, bounded, keyset-paginated.
"""
import os
import sys
from datetime import datetime, timezone

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.aro import event_service as es  # noqa: E402
from src.aro import events_repository as repo  # noqa: E402

TS = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)


class CaptureDb:
    def __init__(self, insert_returns=(1,), rows=None):
        self.calls = []
        self.insert_returns = insert_returns
        self.rows = rows or []

    def execute_query(self, sql, params=None, fetch_one=False, fetch_all=False):
        self.calls.append((" ".join(sql.split()), params))
        s = " ".join(sql.split()).upper()
        if s.startswith("INSERT INTO AGENT_EVENTS"):
            return self.insert_returns
        if s.startswith("SELECT ID FROM AGENT_EVENTS"):
            return (42,)
        if fetch_all:
            return self.rows
        return None


def _insert_params(db):
    sql, params = db.calls[0]
    cols = sql[sql.index("(") + 1: sql.index(")")].replace(" ", "").split(",")
    return dict(zip(cols, params))


def test_append_persists_extended_columns(monkeypatch):
    db = CaptureDb()
    monkeypatch.setattr(repo, "_get_db", lambda: db)
    ev = es.build_event(1, "telemetry.shell", "runtime-telemetry", category="SHELL",
                        trace_id="tr", task_id="t", outcome="SUCCESS", duration_ms=3,
                        ingest_source="runtime_reported", ingest_principal="ingest-token:1")
    out = repo.append_event(ev)
    cols = _insert_params(db)
    assert cols["category"] == "SHELL" and cols["trace_id"] == "tr"
    assert cols["ingest_source"] == "runtime_reported"
    assert cols["duration_ms"] == 3
    assert out["inserted"] is True and out["id"] == 1


def test_append_legacy_event_gets_derived_category_and_default_provenance(monkeypatch):
    db = CaptureDb()
    monkeypatch.setattr(repo, "_get_db", lambda: db)
    repo.append_event(es.build_event(1, "governance.decision", "zaf-pdp"))
    cols = _insert_params(db)
    assert cols["category"] == "SECURITY"
    assert cols["ingest_source"] == "control_plane"
    assert cols["trace_id"] is None


def test_append_duplicate_is_flagged(monkeypatch):
    db = CaptureDb(insert_returns=None)
    monkeypatch.setattr(repo, "_get_db", lambda: db)
    out = repo.append_event(es.build_event(1, "task.received", "worker", event_id="evt-x"))
    assert out["inserted"] is False and out["id"] == 42


def _row(i, ts=TS):
    return (i, f"evt-{i}", 1, "agent://default/a", None, "telemetry.shell",
            "runtime-telemetry", {"metadata": {}}, None, 10, "LOW", "c", ts,
            "tr", "s", "t", None, "SHELL", "exec", "ls", "SUCCESS", 5,
            "runtime_reported", "ingest-token:1")


def test_query_is_tenant_scoped_parameterized_and_bounded(monkeypatch):
    db = CaptureDb(rows=[_row(1)])
    monkeypatch.setattr(repo, "_get_db", lambda: db)
    page = repo.query_events(5, filters={"agent_id": "agent://x'; DROP TABLE x;--",
                                         "category": "SHELL", "bogus": "ignored"},
                             limit=10 ** 6)
    sql, params = db.calls[0]
    assert sql.startswith("SELECT") and "WHERE tenant_id = %s" in sql
    assert params[0] == 5
    assert "DROP TABLE" not in sql  # value bound as a parameter, never inlined
    assert "bogus" not in sql
    assert params[-1] == repo.MAX_PAGE_SIZE + 1
    ev = page["events"][0]
    assert ev["category"] == "SHELL" and ev["ingest_source"] == "runtime_reported"
    assert page["next_cursor"] is None


def test_query_pagination_cursor_roundtrip(monkeypatch):
    rows = [_row(3), _row(2), _row(1)]
    db = CaptureDb(rows=rows)
    monkeypatch.setattr(repo, "_get_db", lambda: db)
    page = repo.query_events(1, limit=2)
    assert [e["id"] for e in page["events"]] == [3, 2]
    assert page["next_cursor"] == f"{TS.isoformat()}|2"
    repo.query_events(1, limit=2, cursor=page["next_cursor"])
    sql, params = db.calls[1]
    assert "(occurred_at, id) < (%s, %s)" in sql
    assert params[1:3] == (TS.isoformat(), 2)


def test_query_ascending_uses_greater_than(monkeypatch):
    db = CaptureDb(rows=[])
    monkeypatch.setattr(repo, "_get_db", lambda: db)
    repo.query_events(1, cursor=f"{TS.isoformat()}|9", order="asc")
    sql, _ = db.calls[0]
    assert "(occurred_at, id) > (%s, %s)" in sql and "ORDER BY occurred_at ASC" in sql


def test_min_severity_and_search(monkeypatch):
    db = CaptureDb(rows=[])
    monkeypatch.setattr(repo, "_get_db", lambda: db)
    repo.query_events(1, min_severity="high", search="rm_%")
    sql, params = db.calls[0]
    assert "severity IN (%s, %s)" in sql
    assert "HIGH" in params and "CRITICAL" in params
    assert "%rm\\_\\%%" in params  # LIKE wildcards escaped


@pytest.mark.parametrize("bad", ["garbage", "notatime|3", "|3", f"{TS.isoformat()}|x"])
def test_malformed_cursor_raises(bad, monkeypatch):
    monkeypatch.setattr(repo, "_get_db", lambda: CaptureDb())
    with pytest.raises(ValueError):
        repo.query_events(1, cursor=bad)
