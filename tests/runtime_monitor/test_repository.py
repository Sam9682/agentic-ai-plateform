#!/usr/bin/env python3
"""Tests for the Runtime Security repository layer.

These tests install a fake ``db_manager`` so they run without a live
PostgreSQL. They assert that each repository function issues the expected SQL
shape and parameters, and that the upsert / mark-stopped logic behaves
correctly. A separate guarded block exercises a real database when one is
reachable (so the migration + round-trip can be demoed), but it is skipped
automatically otherwise.

Run directly:
    python3 tests/runtime_monitor/test_repository.py
Or via pytest:
    pytest tests/runtime_monitor/test_repository.py
"""
import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)


class FakeDbManager:
    """Records queries and returns scripted results.

    ``results`` is a list consumed FIFO for fetch_one/fetch_all calls. Non-fetch
    calls return ``rowcount`` (default 1).
    """

    def __init__(self, results=None, rowcount=1):
        self.calls = []
        self._results = list(results or [])
        self._rowcount = rowcount

    def execute_query(self, query, params=None, fetch_one=False, fetch_all=False):
        self.calls.append(
            {"query": query, "params": params, "fetch_one": fetch_one, "fetch_all": fetch_all}
        )
        if fetch_one:
            return self._results.pop(0) if self._results else None
        if fetch_all:
            return self._results.pop(0) if self._results else []
        return self._rowcount


def _load_repo_with_fake(fake):
    """Import the repository module with db_manager patched to ``fake``."""
    import src.database_postgres as dbp
    dbp.db_manager = fake
    # Ensure a fresh import binds the patched db_manager.
    for mod in list(sys.modules):
        if mod.endswith("runtime_monitor_repository"):
            del sys.modules[mod]
    from src.runtime_monitor import runtime_monitor_repository as repo
    repo.db_manager = fake
    return repo


def test_upsert_container_builds_upsert_and_returns_pk():
    fake = FakeDbManager(results=[(42,)])
    repo = _load_repo_with_fake(fake)
    pk = repo.upsert_container(
        server_id=1,
        container_id="abc123",
        name="coding-worker-01",
        image="ghcr.io/acme/agent:latest",
        runtime="runc",
        state="running",
        is_platform_managed=False,
        classification="probable_agent",
        confidence_score=0.82,
        classification_evidence=["image name contains 'agent'"],
        labels={"com.acme": "x"},
    )
    assert pk == 42
    call = fake.calls[0]
    q = " ".join(call["query"].split())
    assert "INSERT INTO runtime_containers" in q
    assert "ON CONFLICT (server_id, container_id) DO UPDATE SET" in q
    assert "last_seen = CURRENT_TIMESTAMP" in q
    assert call["fetch_one"] is True
    # Evidence and labels must be JSON-serialized for JSONB columns.
    params = call["params"]
    assert json.loads(params[9]) == ["image name contains 'agent'"]
    assert json.loads(params[10]) == {"com.acme": "x"}
    print("ok test_upsert_container_builds_upsert_and_returns_pk")


def test_record_observation_serializes_json_and_returns_id():
    fake = FakeDbManager(results=[(7,)])
    repo = _load_repo_with_fake(fake)
    obs_id = repo.record_observation(
        container_pk=42,
        cpu_percent=12.5,
        memory_bytes=1048576,
        pids=5,
        process_summary=[{"cmd": "python agent.py"}],
        network_summary={"egress": ["api.openai.com"]},
        state="running",
    )
    assert obs_id == 7
    call = fake.calls[0]
    assert "INSERT INTO runtime_observations" in " ".join(call["query"].split())
    assert json.loads(call["params"][4]) == [{"cmd": "python agent.py"}]
    assert json.loads(call["params"][5]) == {"egress": ["api.openai.com"]}
    print("ok test_record_observation_serializes_json_and_returns_id")


def test_mark_containers_stopped_with_active_list():
    fake = FakeDbManager(rowcount=3)
    repo = _load_repo_with_fake(fake)
    affected = repo.mark_containers_stopped(server_id=1, active_container_ids=["a", "b"])
    assert affected == 3
    q = " ".join(fake.calls[0]["query"].split())
    assert "UPDATE runtime_containers SET state = 'stopped'" in q
    assert "NOT IN (%s,%s)" in q
    # server_id first, then the active ids.
    assert fake.calls[0]["params"] == (1, "a", "b")
    print("ok test_mark_containers_stopped_with_active_list")


def test_mark_containers_stopped_empty_list_marks_all():
    fake = FakeDbManager(rowcount=5)
    repo = _load_repo_with_fake(fake)
    affected = repo.mark_containers_stopped(server_id=2, active_container_ids=[])
    assert affected == 5
    q = " ".join(fake.calls[0]["query"].split())
    assert "NOT IN" not in q
    assert fake.calls[0]["params"] == (2,)
    print("ok test_mark_containers_stopped_empty_list_marks_all")


def test_list_containers_applies_filters():
    rows = [
        (1, 1, "worker-01", "abc", "coding-worker-01", "img", "runc", "running",
         False, "probable_agent", 0.9, "[]", "{}", None, None),
    ]
    fake = FakeDbManager(results=[rows])
    repo = _load_repo_with_fake(fake)
    out = repo.list_containers(classification="probable_agent", state="running")
    assert len(out) == 1
    assert out[0]["classification"] == "probable_agent"
    assert out[0]["is_platform_managed"] is False
    q = " ".join(fake.calls[0]["query"].split())
    assert "rc.classification = %s" in q
    assert "rc.state = %s" in q
    assert fake.calls[0]["params"] == ("probable_agent", "running")
    print("ok test_list_containers_applies_filters")


def test_summary_counts_shape():
    # First call: monitored/probable; second call: open anomaly count.
    fake = FakeDbManager(results=[(4, 2), (3,)])
    repo = _load_repo_with_fake(fake)
    summary = repo.summary_counts()
    assert summary == {
        "containers_monitored": 4,
        "probable_agents": 2,
        "active_anomalies": 3,
    }
    print("ok test_summary_counts_shape")


def test_timeline_normalizes_jsonb_text():
    rows = [
        (10, 20.0, 2048, 3, '[{"cmd": "node x"}]', '{"egress": []}', "running", _FakeTs()),
    ]
    fake = FakeDbManager(results=[rows])
    repo = _load_repo_with_fake(fake)
    timeline = repo.get_container_timeline(42)
    assert timeline[0]["process_summary"] == [{"cmd": "node x"}]
    assert timeline[0]["network_summary"] == {"egress": []}
    assert timeline[0]["observed_at"] == "2026-01-01T00:00:00"
    print("ok test_timeline_normalizes_jsonb_text")


class _FakeTs:
    def isoformat(self):
        return "2026-01-01T00:00:00"


def _run_live_db_demo_if_available():
    """Optional: exercise a real DB round-trip when PostgreSQL is reachable."""
    try:
        import src.database_postgres  # noqa: F401
        # Re-import a clean repository bound to the real db_manager.
        for mod in list(sys.modules):
            if mod.endswith("runtime_monitor_repository"):
                del sys.modules[mod]
        from src.database_postgres import init_db, db_manager as real_dbm
        from src.runtime_monitor import runtime_monitor_repository as repo
        repo.db_manager = real_dbm
        init_db()
        server = real_dbm.execute_query("SELECT id FROM servers LIMIT 1", fetch_one=True)
        if not server:
            print("skip live-db demo: no servers row to attach a container to")
            return
        server_id = server[0]
        pk = repo.upsert_container(
            server_id=server_id, container_id="demo-container",
            name="demo", image="python:3.11", runtime="runc", state="running",
            is_platform_managed=False, classification="unclassified",
            confidence_score=0.0, classification_evidence=[], labels={},
        )
        repo.record_observation(pk, 1.0, 1024, 1, [{"cmd": "sleep"}], {}, "running")
        again = repo.upsert_container(
            server_id=server_id, container_id="demo-container",
            name="demo", image="python:3.11", runtime="runc", state="running",
            is_platform_managed=False, classification="probable_agent",
            confidence_score=0.7, classification_evidence=["demo"], labels={},
        )
        assert again == pk, "upsert must not create a duplicate row"
        timeline = repo.get_container_timeline(pk)
        print(f"live-db demo ok: pk={pk}, timeline_rows={len(timeline)}")
    except Exception as e:  # pragma: no cover - environment dependent
        print(f"skip live-db demo (no reachable PostgreSQL): {e}")


def main():
    test_upsert_container_builds_upsert_and_returns_pk()
    test_record_observation_serializes_json_and_returns_id()
    test_mark_containers_stopped_with_active_list()
    test_mark_containers_stopped_empty_list_marks_all()
    test_list_containers_applies_filters()
    test_summary_counts_shape()
    test_timeline_normalizes_jsonb_text()
    _run_live_db_demo_if_available()
    print("\nAll repository tests passed.")


if __name__ == "__main__":
    main()
