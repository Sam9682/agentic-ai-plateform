"""Unit tests for Phase 5 OBS route response shapes (Task 6.2).

Feature: phase5-obs-supervisor — exercises the extended ``obs_bp`` routes in
``src/routes/obs_routes.py`` behind the real ``@tenant_scoped`` decorator,
with the repository / cost / infra-collector seams mocked so no DB, SSH, or
eBPF tooling is required.

Asserts:
  * ``/anomalies`` items carry the enforcement/routing fields
    (``enforcement_status``, ``runtime_id``, ``session_id``,
    ``recommended_action``).                                        (R1.4)
  * ``/agents/<id>/risk`` returns the live risk snapshot shape
    (``risk_score``, ``anomaly_count``, ``anomalies``).             (R1.5)
  * ``/costs`` is registered on ``obs_bp`` (under
    ``/api/v1/observability``) and surfaces the measured-vs-estimated
    distinction (``usage`` + ``estimated_cost`` + ``data_source``). (R4.8, R4.9)
  * ``/metrics`` includes an ``infra`` block when a pid/container target is
    supplied and omits it when no target is given.                 (R5.1)
"""

from __future__ import annotations

import pytest
from flask import Flask


# --------------------------------------------------------------------------- #
# Test app wiring: real blueprint + real @tenant_scoped, mocked data seams.
# --------------------------------------------------------------------------- #
def _make_client(monkeypatch, *, anomalies=None, cost_records=None,
                 events=None, collector=None, role="operator"):
    from src import authz
    from src.routes import obs_routes
    from src.aro import events_repository as events_repo

    # Resolve a default tenant membership so @tenant_scoped sets g.tenant_id.
    monkeypatch.setattr(
        authz, "membership_loader",
        lambda uid: [{"tenant_id": 1, "tenant_slug": "default",
                      "role": role, "is_default": True}],
    )

    # Repository / cost seams (module-level references inside obs_routes).
    monkeypatch.setattr(
        obs_routes.obs_repo, "list_anomalies",
        lambda tid, *a, **k: list(anomalies or []),
    )
    monkeypatch.setattr(
        obs_routes.obs_cost, "list_cost_records",
        lambda tid, *a, **k: list(cost_records or []),
    )
    # /metrics reads the event stream; stub it so no DB is touched.
    monkeypatch.setattr(
        events_repo, "list_events",
        lambda tid, *a, **k: list(events or []),
    )

    # select_collector is imported by name into obs_routes; patch there.
    if collector is not None:
        monkeypatch.setattr(obs_routes, "select_collector", lambda *a, **k: collector)

    app = Flask(__name__)
    app.secret_key = "t"
    app.register_blueprint(obs_routes.obs_bp)
    return app.test_client()


def _login(client, uid=1):
    with client.session_transaction() as sess:
        sess["user_id"] = uid


class _StubCollector:
    """Minimal infra collector returning a fixed CPU/mem/IO sample."""

    def __init__(self, sample):
        self._sample = sample

    def sample(self, target):  # noqa: D401 - test double
        return dict(self._sample)


# --------------------------------------------------------------------------- #
# /anomalies — enforcement/routing fields present (R1.4)
# --------------------------------------------------------------------------- #
def _anomaly_row(**over):
    row = {
        "id": 1,
        "agent_identity": "agent-a",
        "rule_id": "execution.loop",
        "severity": "HIGH",
        "risk_score": 72,
        "evidence": {"commands": ["ls", "ls"]},
        "status": "open",
        "detected_at": "2024-01-01T00:00:00Z",
        "enforcement_status": "surfaced",
        "runtime_id": "rt-1",
        "session_id": "sess-9",
        "recommended_action": "notify",
    }
    row.update(over)
    return row


def test_anomalies_items_include_enforcement_fields(monkeypatch):
    client = _make_client(monkeypatch, anomalies=[_anomaly_row()])
    _login(client)

    resp = client.get("/api/v1/observability/anomalies")
    assert resp.status_code == 200
    items = resp.get_json()["anomalies"]
    assert len(items) == 1
    item = items[0]
    for field in ("enforcement_status", "runtime_id", "session_id",
                  "recommended_action"):
        assert field in item, f"missing enforcement/routing field: {field}"
    assert item["enforcement_status"] == "surfaced"
    assert item["runtime_id"] == "rt-1"
    assert item["session_id"] == "sess-9"
    assert item["recommended_action"] == "notify"


def test_anomalies_requires_auth(monkeypatch):
    client = _make_client(monkeypatch, anomalies=[_anomaly_row()])
    assert client.get("/api/v1/observability/anomalies").status_code == 401


# --------------------------------------------------------------------------- #
# /agents/<id>/risk — live risk snapshot shape (R1.5)
# --------------------------------------------------------------------------- #
def test_agent_risk_snapshot_shape(monkeypatch):
    rows = [
        _anomaly_row(id=1, agent_identity="agent-a", risk_score=40),
        _anomaly_row(id=2, agent_identity="agent-a", risk_score=88),
        _anomaly_row(id=3, agent_identity="other", risk_score=99),
    ]
    client = _make_client(monkeypatch, anomalies=rows)
    _login(client)

    resp = client.get("/api/v1/observability/agents/agent-a/risk")
    assert resp.status_code == 200
    snap = resp.get_json()

    assert snap["agent_identity"] == "agent-a"
    # Snapshot is the top risk across this agent's anomalies only.
    assert snap["risk_score"] == 88
    assert snap["anomaly_count"] == 2
    assert isinstance(snap["anomalies"], list)
    assert all(a["agent_identity"] == "agent-a" for a in snap["anomalies"])


def test_agent_risk_defaults_when_no_anomalies(monkeypatch):
    client = _make_client(monkeypatch, anomalies=[])
    _login(client)

    resp = client.get("/api/v1/observability/agents/ghost/risk")
    assert resp.status_code == 200
    snap = resp.get_json()
    assert snap["risk_score"] == 0
    assert snap["anomaly_count"] == 0
    assert snap["anomalies"] == []


# --------------------------------------------------------------------------- #
# /costs — on obs_bp, measured-vs-estimated distinction (R4.8, R4.9)
# --------------------------------------------------------------------------- #
def test_costs_registered_on_obs_bp_url():
    """The /costs route lives under /api/v1/observability (obs_bp), not billing."""
    from src.routes import obs_routes

    assert obs_routes.obs_bp.url_prefix == "/api/v1/observability"
    # Register on a throwaway app to inspect the URL map concretely.
    app = Flask(__name__)
    app.register_blueprint(obs_routes.obs_bp)
    cost_rules = [r.rule for r in app.url_map.iter_rules()
                  if r.endpoint == "obs.costs"]
    assert cost_rules == ["/api/v1/observability/costs"]


def test_costs_surfaces_measured_vs_estimated(monkeypatch):
    records = [
        {
            "id": 1,
            "agent_identity": "agent-a",
            "usage": {"tokens": 1200, "cpu_seconds": 3.5},
            "estimated_cost": "0.042000",
            "data_source": "MEASURED",
        },
        {
            "id": 2,
            "agent_identity": "agent-b",
            "usage": {"tokens": 0},
            "estimated_cost": "0.000000",
            "data_source": "ESTIMATED",
        },
    ]
    client = _make_client(monkeypatch, cost_records=records)
    _login(client)

    resp = client.get("/api/v1/observability/costs")
    assert resp.status_code == 200
    costs = resp.get_json()["costs"]
    assert len(costs) == 2
    for rec in costs:
        # The measured-vs-estimated distinction must be visible: usage and the
        # separately stored estimated_cost plus the data_source provenance.
        assert "usage" in rec
        assert "estimated_cost" in rec
        assert rec["data_source"] in ("MEASURED", "ESTIMATED", "MIXED")
    sources = {rec["data_source"] for rec in costs}
    assert sources == {"MEASURED", "ESTIMATED"}


def test_costs_requires_auth(monkeypatch):
    client = _make_client(monkeypatch, cost_records=[])
    assert client.get("/api/v1/observability/costs").status_code == 401


# --------------------------------------------------------------------------- #
# /metrics — infra block present with a target, omitted without one (R5.1)
# --------------------------------------------------------------------------- #
def test_metrics_includes_infra_when_target_supplied(monkeypatch):
    collector = _StubCollector({
        "cpu_percent": 12.5,
        "memory_bytes": 1048576,
        "io_bytes": 2048,
    })
    client = _make_client(monkeypatch, events=[], collector=collector)
    _login(client)

    resp = client.get("/api/v1/observability/metrics?pid=4321")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert "infra" in payload, "infra block should be present when a target is wired"
    infra = payload["infra"]
    assert infra["cpu_percent"] == 12.5
    assert infra["memory_bytes"] == 1048576
    assert infra["io_bytes"] == 2048
    assert infra["collector"] == "_StubCollector"


def test_metrics_omits_infra_when_no_target(monkeypatch):
    # Collector is wired but no pid/container target → nothing to sample → omit.
    collector = _StubCollector({"cpu_percent": 1.0})
    client = _make_client(monkeypatch, events=[], collector=collector)
    _login(client)

    resp = client.get("/api/v1/observability/metrics")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert "infra" not in payload, "infra block must be omitted without a target"
    # Base aggregate shape still present.
    assert "total_events" in payload
    assert "by_severity" in payload


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
