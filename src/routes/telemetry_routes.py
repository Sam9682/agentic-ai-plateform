"""Telemetry ingestion + agent behavior API (ABF/AET event foundation, Phase 1).

Exposes ``telemetry_bp`` under ``/api/v1``:

* POST /telemetry/events
      Runtime-reported events. Authenticated by a per-agent ingest token
      (``Authorization: Bearer aig_...``); no browser session is used or
      accepted. Identity/tenant come from the token.
* POST /agents/{id}/telemetry-tokens                    (admin)
      Issue an ingest token for an agent. The clear token is returned once.
* GET  /agents/{id}/telemetry-tokens                    (operator)
      List an agent's tokens (metadata only).
* POST /agents/{id}/telemetry-tokens/{token_id}/revoke  (admin)
* GET  /agents/{id}/behavior                            (viewer)
      The agent's normalized behavior events, keyset-paginated and filterable
      (category, min_severity, outcome, ingest_source, trace_id, session_id,
      task_id, since, until, q, cursor, limit, order).

All session-authenticated routes are tenant-scoped through ``src.authz``; an
agent id from another tenant resolves to 404 (no cross-tenant existence leak).
Token issue/revoke are audited as SECURITY events (never containing the token).
"""

from __future__ import annotations

import logging

from flask import Blueprint, g, jsonify, request, session

from ..authz import role_required, tenant_scoped
from ..aro import agent_repository as agent_repo
from ..aro import event_service
from ..aro import events_repository as events_repo
from ..obs import ingest_tokens
from ..obs.telemetry_ingest import TelemetryIngestService
from .aro_common import json_body

logger = logging.getLogger(__name__)

telemetry_bp = Blueprint("telemetry", __name__, url_prefix="/api/v1")

# 2 MiB request cap for ingestion (500 events x 16 KiB metadata worst case is
# larger, but realistic batches are far smaller; oversize requests get 413).
MAX_INGEST_BODY_BYTES = 2 * 1024 * 1024

_service = None


def get_ingest_service() -> TelemetryIngestService:
    """Process-wide ingestion service (holds the per-token rate limiter)."""
    global _service
    if _service is None:
        from ..abf import audit_chain
        from ..abf.firewall import get_firewall

        def _inspect(tenant_id, agent_db_id, identity, events):
            return get_firewall().inspect(tenant_id, agent_db_id, identity, events)

        _service = TelemetryIngestService(inspector=_inspect, sealer=audit_chain.safe_seal)
    return _service


def _bearer_token():
    header = request.headers.get("Authorization", "")
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()


@telemetry_bp.route("/telemetry/events", methods=["POST"])
def ingest_events():
    if request.content_length is not None and request.content_length > MAX_INGEST_BODY_BYTES:
        return jsonify({"error": "request body too large"}), 413
    token = _bearer_token()
    if token is None:
        return jsonify({"error": "missing bearer ingest token"}), 401
    body = request.get_json(silent=True)
    result = get_ingest_service().ingest(token, body)
    response = jsonify(result.payload)
    for name, value in result.headers.items():
        response.headers[name] = value
    return response, result.status_code


def _tenant_agent(agent_id: int):
    """Load an agent within the caller's tenant (None -> 404)."""
    return agent_repo.get_agent(g.tenant_id, agent_id)


def _audit(agent, event_type: str, action: dict) -> None:
    try:
        event_service.emit(
            events_repo, g.tenant_id, event_type, "telemetry-admin",
            agent_id=agent["identity"], action=action, severity="LOW",
        )
    except Exception:  # noqa: BLE001 - audit failure must not break the call
        logger.exception("failed to audit %s", event_type)


@telemetry_bp.route("/agents/<int:agent_id>/telemetry-tokens", methods=["POST"])
@role_required("admin")
def issue_token(agent_id):
    agent = _tenant_agent(agent_id)
    if agent is None:
        return jsonify({"error": "agent not found"}), 404
    if agent.get("status") == "TERMINATED":
        return jsonify({"error": "agent is terminated"}), 409
    body = json_body()
    try:
        scope = ingest_tokens.normalize_scopes(body.get("scopes"))
    except ValueError as exc:
        return jsonify({"error": str(exc),
                        "allowed_scopes": list(ingest_tokens.ALLOWED_SCOPES)}), 400
    if agent.get("status") == "QUARANTINED" and any(
            sc in ingest_tokens.ACTING_SCOPES for sc in scope.split()):
        return jsonify({"error": "agent is quarantined: only telemetry tokens can be issued"}), 409
    issued = ingest_tokens.issue(
        g.tenant_id, agent_id,
        ttl_seconds=body.get("ttl_seconds", ingest_tokens.DEFAULT_TTL_SECONDS),
        created_by_user_id=session.get("user_id"),
        scopes=scope.split(),
    )
    _audit(agent, "security.ingest_token.issued", {
        "ingest_ref": issued["id"], "display_prefix": issued["token_prefix"],
        "expires_at": issued["expires_at"], "actor_user_id": session.get("user_id"),
        "granted_scopes": issued["scope"],
    })
    return jsonify(issued), 201


@telemetry_bp.route("/agents/<int:agent_id>/telemetry-tokens", methods=["GET"])
@role_required("operator")
def list_tokens(agent_id):
    if _tenant_agent(agent_id) is None:
        return jsonify({"error": "agent not found"}), 404
    return jsonify({"tokens": ingest_tokens.list_for_agent(g.tenant_id, agent_id)}), 200


@telemetry_bp.route("/agents/<int:agent_id>/telemetry-tokens/<int:token_id>/revoke",
                    methods=["POST"])
@role_required("admin")
def revoke_token(agent_id, token_id):
    agent = _tenant_agent(agent_id)
    if agent is None:
        return jsonify({"error": "agent not found"}), 404
    if not ingest_tokens.revoke(g.tenant_id, agent_id, token_id):
        return jsonify({"error": "token not found or already revoked"}), 404
    _audit(agent, "security.ingest_token.revoked", {
        "ingest_ref": token_id, "actor_user_id": session.get("user_id"),
    })
    return jsonify({"id": token_id, "revoked": True}), 200


_BEHAVIOR_FILTERS = ("category", "outcome", "ingest_source", "trace_id",
                     "session_id", "task_id", "event_type")


@telemetry_bp.route("/agents/<int:agent_id>/behavior", methods=["GET"])
@tenant_scoped
def agent_behavior(agent_id):
    agent = _tenant_agent(agent_id)
    if agent is None:
        return jsonify({"error": "agent not found"}), 404
    filters = {k: request.args.get(k) for k in _BEHAVIOR_FILTERS if request.args.get(k)}
    if "category" in filters:
        filters["category"] = filters["category"].upper()
    if "outcome" in filters:
        filters["outcome"] = filters["outcome"].upper()
    filters["agent_id"] = agent["identity"]
    try:
        limit = int(request.args.get("limit", 100))
    except (TypeError, ValueError):
        return jsonify({"error": "limit must be an integer"}), 400
    try:
        page = events_repo.query_events(
            g.tenant_id,
            filters=filters,
            min_severity=request.args.get("min_severity"),
            since=request.args.get("since"),
            until=request.args.get("until"),
            search=request.args.get("q"),
            cursor=request.args.get("cursor"),
            limit=limit,
            order=request.args.get("order", "desc"),
        )
    except ValueError:
        return jsonify({"error": "invalid cursor"}), 400
    return jsonify({
        "agent_id": agent_id,
        "agent_identity": agent["identity"],
        "events": page["events"],
        "next_cursor": page["next_cursor"],
    }), 200
