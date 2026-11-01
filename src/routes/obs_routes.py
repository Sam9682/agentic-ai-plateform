"""Observability API (Task 16).

Exposes ``obs_bp`` under ``/api/v1/observability``:

* GET /events                 - tenant event stream (filterable)
* GET /metrics                - aggregate counters (events by severity/decision),
                                plus an opportunistic ``infra`` block (CPU/mem/IO)
                                where an infra collector is wired (R5.1)
* GET /anomalies              - detected anomalies, including the Detection_Pass
                                findings and their enforcement/routing fields (R1.4)
* GET /costs                  - OBS cost records with measured-vs-estimated
                                provenance (R4.8); distinct from billing (R4.9)
* GET /incidents              - security incidents
* GET /agents/{identity}/timeline - an agent's event timeline
* GET /agents/{identity}/risk - an agent's latest explainable risk snapshot (R1.5)
"""

from __future__ import annotations

import logging
from collections import Counter

from flask import Blueprint, g, jsonify, request

from ..authz import tenant_scoped
from ..aro import events_repository as events_repo
from ..obs import obs_cost
from ..obs import obs_repository as obs_repo
from ..obs.infra_metrics import select_collector

logger = logging.getLogger(__name__)

obs_bp = Blueprint("obs", __name__, url_prefix="/api/v1/observability")


@obs_bp.route("/events", methods=["GET"])
@tenant_scoped
def list_events():
    events = events_repo.list_events(
        g.tenant_id,
        agent_id=request.args.get("agent_id"),
        event_type=request.args.get("event_type"),
        severity=request.args.get("severity"),
        limit=int(request.args.get("limit", 200)),
    )
    return jsonify({"events": events}), 200


@obs_bp.route("/metrics", methods=["GET"])
@tenant_scoped
def metrics():
    events = events_repo.list_events(g.tenant_id, limit=2000)
    by_severity = Counter(e["severity"] for e in events)
    by_decision = Counter(e["decision"] for e in events if e["decision"])
    by_type = Counter(e["event_type"] for e in events)
    payload = {
        "total_events": len(events),
        "by_severity": dict(by_severity),
        "by_decision": dict(by_decision),
        "by_type": dict(by_type),
    }
    # Opportunistic infra block (R5.1): include CPU/mem/IO only where an infra
    # collector is wired for this request. Absent a wired collector, omit the
    # block rather than failing — metrics stay opportunistic by design (R5.3).
    infra = _infra_block()
    if infra is not None:
        payload["infra"] = infra
    return jsonify(payload), 200


def _infra_block():
    """Return an ``infra`` metrics block when a collector is wired, else None.

    A collector is considered wired only when a target is supplied on the
    request (``pid`` or ``container``); without a target there is nothing to
    sample, so the block is omitted rather than reported as empty. The
    non-eBPF fallback is always available, so a wired target never fails the
    endpoint (R5.2, R5.3). Any collection error degrades to omission.
    """
    target = {}
    pid = request.args.get("pid")
    container = request.args.get("container") or request.args.get("container_id")
    if pid:
        try:
            target["pid"] = int(pid)
        except (TypeError, ValueError):
            return None
    if container:
        target["container_id"] = container
    if not target:
        return None
    try:
        collector = select_collector()
        sample = collector.sample(target)
    except Exception:  # pragma: no cover - opportunistic, never fail /metrics
        logger.debug("infra metrics sample failed", exc_info=True)
        return None
    return {
        "collector": type(collector).__name__,
        "cpu_percent": sample.get("cpu_percent"),
        "memory_bytes": sample.get("memory_bytes"),
        "io_bytes": sample.get("io_bytes"),
    }


@obs_bp.route("/anomalies", methods=["GET"])
@tenant_scoped
def anomalies():
    """Return detected anomalies for the tenant (newest first).

    ``list_anomalies`` returns Detection_Pass findings alongside any
    pre-recorded rows (R1.4), each carrying the enforcement/routing fields
    (``enforcement_status``, ``runtime_id``, ``session_id``,
    ``recommended_action``) populated by the detection pass.
    """
    return jsonify({"anomalies": obs_repo.list_anomalies(g.tenant_id)}), 200


@obs_bp.route("/costs", methods=["GET"])
@tenant_scoped
def costs():
    """Return OBS cost records with measured-vs-estimated provenance (R4.8).

    Each record surfaces the measured ``usage`` dimensions, the separately
    stored ``estimated_cost``, and the ``data_source`` label
    (MEASURED / ESTIMATED / MIXED) so the measured-vs-estimated distinction is
    visible. This lives on ``obs_bp`` and is strictly distinct from the
    platform billing surface (R4.9). Optionally filtered by ``parent_task_id``
    / ``delegation_id`` for budget aggregation over a delegation chain.
    """
    parent_task_id = request.args.get("parent_task_id")
    try:
        parent_task_id = int(parent_task_id) if parent_task_id else None
    except (TypeError, ValueError):
        parent_task_id = None
    records = obs_cost.list_cost_records(
        g.tenant_id,
        limit=int(request.args.get("limit", 200)),
        parent_task_id=parent_task_id,
        delegation_id=request.args.get("delegation_id"),
    )
    return jsonify({"costs": records}), 200


@obs_bp.route("/incidents", methods=["GET"])
@tenant_scoped
def incidents():
    return jsonify({"incidents": obs_repo.list_incidents(g.tenant_id)}), 200


@obs_bp.route("/agents/<path:identity>/timeline", methods=["GET"])
@tenant_scoped
def agent_timeline(identity):
    timeline = events_repo.get_agent_timeline(g.tenant_id, identity,
                                              limit=int(request.args.get("limit", 200)))
    return jsonify({"agent_identity": identity, "timeline": timeline}), 200


@obs_bp.route("/agents/<path:identity>/risk", methods=["GET"])
@tenant_scoped
def agent_risk(identity):
    """Return the agent's live risk snapshot over current windows (R1.5).

    The snapshot is the top Risk_Scoring result across the anomalies the
    Detection_Pass has persisted for the agent, filtered by identity. This
    reflects the deterministic, auditable risk scoring — not an LLM.
    """
    anomalies = [a for a in obs_repo.list_anomalies(g.tenant_id)
                 if a["agent_identity"] == identity]
    top = max((a["risk_score"] for a in anomalies), default=0)
    return jsonify({
        "agent_identity": identity,
        "risk_score": top,
        "anomaly_count": len(anomalies),
        "anomalies": anomalies[:20],
    }), 200
