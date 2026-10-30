#!/usr/bin/env python3
"""Tests for the runtime observability scanner (Task 15).

Feature: ARO runtime scanner wiring the runtime_monitor repository (SRS §5.2, §5.3).

Validates:
* scan_server persists inventory (upsert_container) + an observation per
  container, marks disappeared containers stopped, and records a scan-run.
* an unreachable server records the scan-run error and persists nothing.
* missing resource metrics are stored as None (not faked) and recorded as a
  limitation event rather than fabricating data.
* record_agent_activity emits the expected event.

Run directly:
    python3 tests/test_aro_runtime_scanner.py
Or via pytest:
    pytest tests/test_aro_runtime_scanner.py
"""
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.aro import runtime_scanner as scanner  # noqa: E402


class CapturingEvents:
    def __init__(self):
        self.events = []

    def append_event(self, event):
        self.events.append(event)
        return dict(event, id=len(self.events))


class FakeRepo:
    """Captures calls to the runtime_monitor repository writer contract."""

    def __init__(self):
        self.scan_runs = []
        self.finished = []
        self.upserts = []
        self.observations = []
        self.stopped = []
        self._pk = 1
        self._run = 1

    def start_scan_run(self, server_id):
        rid = self._run
        self._run += 1
        self.scan_runs.append((rid, server_id))
        return rid

    def finish_scan_run(self, scan_run_id, containers_seen, error=None):
        self.finished.append((scan_run_id, containers_seen, error))

    def upsert_container(self, **kw):
        pk = self._pk
        self._pk += 1
        self.upserts.append(kw)
        return pk

    def record_observation(self, **kw):
        self.observations.append(kw)
        return len(self.observations)

    def mark_containers_stopped(self, server_id, active_ids):
        self.stopped.append((server_id, list(active_ids)))
        return 0


def _classify(obs):
    return {"classification": "probable_agent", "score": 0.8, "evidence": ["kiro"]}


def test_scan_persists_inventory_and_observations():
    repo = FakeRepo()
    server = {"id": 1, "server_ip": "10.0.0.1"}

    def collect(srv):
        return ([
            {"container_id": "c1", "name": "kiro", "image": "kiro:1.0", "state": "running",
             "cpu_percent": 12.5, "memory_bytes": 1024, "pids": 7},
            {"container_id": "c2", "name": "web", "image": "nginx", "state": "running",
             "cpu_percent": 1.0, "memory_bytes": 2048, "pids": 3},
        ], None)

    summary = scanner.scan_server(server, collect, _classify, repo)
    assert summary["containers_seen"] == 2
    assert len(repo.upserts) == 2
    assert len(repo.observations) == 2
    assert repo.stopped == [(1, ["c1", "c2"])]
    assert repo.finished[-1] == (1, 2, None)


def test_unreachable_server_records_error_and_persists_nothing():
    repo = FakeRepo()
    server = {"id": 2, "server_ip": "10.0.0.2"}

    def collect(srv):
        return ([], "ssh timeout")

    summary = scanner.scan_server(server, collect, _classify, repo)
    assert summary["error"] == "ssh timeout"
    assert repo.upserts == []
    assert repo.finished[-1] == (1, 0, "ssh timeout")


def test_missing_metrics_recorded_as_limitation_not_faked():
    repo = FakeRepo()
    events = CapturingEvents()
    server = {"id": 3, "server_ip": "10.0.0.3"}

    def collect(srv):
        return ([
            {"container_id": "c9", "name": "agent", "image": "x", "state": "running",
             "cpu_percent": None, "memory_bytes": None, "pids": None},
        ], None)

    summary = scanner.scan_server(server, collect, _classify, repo,
                                  tenant_id=1, events_repo=events)
    # Observation stored with None metrics (not faked).
    assert repo.observations[0]["cpu_percent"] is None
    assert repo.observations[0]["memory_bytes"] is None
    assert any("no resource metrics" in lim for lim in summary["limitations"])
    assert any(e["event_type"] == "observability.limitation" for e in events.events)


def test_record_agent_activity():
    events = CapturingEvents()
    scanner.record_agent_activity(events, 1, "agent://default/a1", "agent.tool.selected",
                                  {"tool": "openstack.server.list"})
    assert events.events[0]["event_type"] == "agent.tool.selected"
    assert events.events[0]["agent_id"] == "agent://default/a1"


def test_scanner_scan_once_iterates_servers():
    repo = FakeRepo()
    servers = [{"id": 1, "server_ip": "a"}, {"id": 2, "server_ip": "b"}]
    s = scanner.RuntimeScanner(
        servers_loader=lambda: servers,
        collect=lambda srv: ([{"container_id": "c", "state": "running"}], None),
        classify=_classify, repo=repo,
    )
    summaries = s.scan_once()
    assert len(summaries) == 2
    assert {x["server_id"] for x in summaries} == {1, 2}


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
