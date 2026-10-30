"""Observability API (Task 16).

Exposes ``obs_bp`` under ``/api/v1/observability``:

* GET /events                 - tenant event stream (filterable)
* GET /metrics                - aggregate counters (events by severity/decision)
* GET /anomalies              - detected anomalies
* GET /incidents              - security incidents
* GET /agents/{identity}/timeline - an agent's event timeline
* GET /agents/{identity}/risk - an agent's latest explainable risk snapshot
"""

from __future__ import annotations

import logging
from collections import Counter

from flask import Blueprint, g, jsonify, request

from ..authz import tenant_scoped
from ..aro import events_repository as events_repo
from ..obs import obs_repository as obs_repo

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
    return jsonify({
        "total_events": len(events),
        "by_severity": dict(by_severity),
        "by_decision": dict(by_decision),
        "by_type": dict(by_type),
    }), 200


@obs_bp.route("/anomalies", methods=["GET"])
@tenant_scoped
def anomalies():
    return jsonify({"anomalies": obs_repo.list_anomalies(g.tenant_id)}), 200


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
    """Return the agent's highest recent risk from recorded anomalies.

    This reflects the deterministic, auditable risk scoring — not an LLM.
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
