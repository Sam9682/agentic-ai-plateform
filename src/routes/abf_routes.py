"""Agent Behavioral Firewall API (Phase 2).

``abf_bp`` under ``/api/v1``:

Agent-authenticated (bearer agent token with scope ``firewall:check``):
* POST /firewall/check                         pre-execution decision for an action

User-authenticated (session + tenant membership):
* GET  /agents/{id}/alerts                     ABF alerts of the agent
* POST /agents/{id}/alerts/{aid}/acknowledge   (operator)
* POST /agents/{id}/alerts/{aid}/resolve       (operator)
* GET  /agents/{id}/rules                      built-in catalogue + customisations
* POST /agents/{id}/rules                      add override / threshold rule (admin)
* PATCH /agents/{id}/rules/{rid}               change a customisation (admin)
* POST /agents/{id}/quarantine                 contain the agent (operator)
* GET  /agents/{id}/baseline                   stored baselines
* POST /agents/{id}/baseline/refresh           recompute baselines (operator)
* POST /agents/{id}/baseline/reset             clear baselines (admin)
* GET  /governance/audit/verify                verify the tenant's event hash chain (admin)
* POST /governance/audit/seal                  seal pending events into the chain (admin)
* GET  /approvals, GET /approvals/{id},
  POST /approvals/{id}/approve|reject          aliases of /api/v1/governance/approvals*

Release from quarantine stays ``POST /api/v1/agents/{id}/release`` (admin only).
Every agent id is resolved inside the caller's tenant: an id of another tenant
is a 404, never a cross-tenant read or write.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from flask import Blueprint, g, jsonify, request, session

from ..abf import audit_chain
from ..abf import baseline as B
from ..abf import repository as abf_repo
from ..abf import rules as R
from ..abf.firewall import GuardRequest, get_firewall
from ..aro import agent_repository as agent_repo
from ..aro import event_service as es
from ..authz import role_required, tenant_scoped
from ..obs import behavior_events as be
from ..obs import ingest_tokens
from ..zaf import approval_service
from ..zaf.mcp_gateway import RateLimiter
from .aro_common import json_body

logger = logging.getLogger(__name__)

abf_bp = Blueprint("abf", __name__, url_prefix="/api/v1")

FIREWALL_CHECKS_PER_MINUTE = 300
MAX_COMMAND_LENGTH = 8192
_check_limiter = RateLimiter()
_ALERT_STATUSES = {"acknowledge": "acknowledged", "resolve": "resolved"}
_GUARD_CATEGORIES = tuple(sorted(set(es.VALID_CATEGORIES) - be.CONTROL_PLANE_ONLY_CATEGORIES))


def _tenant_agent(agent_id):
    return agent_repo.get_agent(g.tenant_id, agent_id)


def _bearer_token():
    scheme, _, value = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()


def _audit(agent, event_type, action, severity="MEDIUM"):
    try:
        es.emit(_events(), g.tenant_id, event_type, "abf-api",
                agent_id=agent.get("identity") if agent else None, action=action,
                severity=severity, category="SECURITY")
    except Exception:  # noqa: BLE001
        logger.exception("ABF audit emit failed")


def _events():
    from ..aro import events_repository
    return events_repository


# --------------------------------------------------------------------------- #
# Agent-authenticated pre-execution check
# --------------------------------------------------------------------------- #
@abf_bp.route("/firewall/check", methods=["POST"])
def firewall_check():
    token = _bearer_token()
    binding = ingest_tokens.verify(token, scope=ingest_tokens.SCOPE_FIREWALL) if token else None
    if binding is None:
        return jsonify({"error": "invalid, expired or insufficiently scoped agent token"}), 401
    if not _check_limiter.allow((f"agent-token:{binding['token_id']}", "firewall"),
                                FIREWALL_CHECKS_PER_MINUTE):
        return jsonify({"error": "rate limit exceeded"}), 429, {"Retry-After": "60"}
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "body must be a JSON object"}), 400
    category = str(body.get("category") or "").upper()
    if category not in _GUARD_CATEGORIES:
        return jsonify({"error": "invalid category", "allowed": list(_GUARD_CATEGORIES)}), 400
    try:
        action = be.normalize_action(body.get("action"))
    except be.ValidationError as exc:
        return jsonify({"error": str(exc)}), 400
    command = body.get("command") or ""
    resource = body.get("resource") or ""
    params = body.get("params") or {}
    if not isinstance(command, str) or len(command) > MAX_COMMAND_LENGTH:
        return jsonify({"error": f"command must be a string of at most {MAX_COMMAND_LENGTH} chars"}), 400
    if not isinstance(resource, str) or len(resource) > 1024:
        return jsonify({"error": "resource must be a string of at most 1024 chars"}), 400
    if not isinstance(params, dict):
        return jsonify({"error": "params must be an object"}), 400
    ids = {}
    for key in ("session_id", "trace_id", "task_id"):
        val = body.get(key)
        if val is not None and not (isinstance(val, str) and be._ID_RE.match(val)):
            return jsonify({"error": f"invalid {key}"}), 400
        ids[key] = val
    if ids["task_id"] is not None:
        from ..aro import task_repository
        if task_repository.get_task_agent_by_ref(binding["tenant_id"], ids["task_id"]) != binding["agent_db_id"]:
            return jsonify({"error": "task_id does not belong to this agent"}), 400

    result = get_firewall().guard(GuardRequest(
        tenant_id=binding["tenant_id"], agent_db_id=binding["agent_db_id"],
        category=category, action=action, resource=resource, command=command,
        params=params, **ids))
    ingest_tokens.touch(binding["token_id"])
    payload = result.as_dict()
    # The agent learns the decision and the approval reference, not the internal
    # rule matching details (it must not be able to tune around the rules).
    payload.pop("rule_hits", None)
    payload["rules_matched"] = len(result.rule_hits)
    if payload.get("approval"):
        payload["approval"] = {"id": payload["approval"].get("id"),
                               "status": payload["approval"].get("status"),
                               "expires_at": payload["approval"].get("expires_at")}
    headers = {"Retry-After": "60"} if result.status_code == 429 else {}
    return jsonify(payload), result.status_code, headers


# --------------------------------------------------------------------------- #
# Alerts
# --------------------------------------------------------------------------- #
@abf_bp.route("/agents/<int:agent_id>/alerts", methods=["GET"])
@tenant_scoped
def list_alerts(agent_id):
    agent = _tenant_agent(agent_id)
    if agent is None:
        return jsonify({"error": "agent not found"}), 404
    try:
        limit = int(request.args.get("limit", 100))
    except ValueError:
        return jsonify({"error": "limit must be an integer"}), 400
    alerts = abf_repo.list_alerts(
        g.tenant_id, agent_db_id=agent_id, agent_identity=agent.get("identity"),
        status=request.args.get("status") or None,
        min_severity=(request.args.get("min_severity") or "").upper() or None, limit=limit)
    return jsonify({"agent_id": agent_id, "alerts": alerts}), 200


@abf_bp.route("/agents/<int:agent_id>/alerts/<int:alert_id>/<op>", methods=["POST"])
@role_required("operator")
def change_alert(agent_id, alert_id, op):
    if op not in _ALERT_STATUSES:
        return jsonify({"error": "unknown operation"}), 404
    agent = _tenant_agent(agent_id)
    if agent is None:
        return jsonify({"error": "agent not found"}), 404
    owned = abf_repo.list_alerts(g.tenant_id, agent_db_id=agent_id,
                                 agent_identity=agent.get("identity"), limit=500)
    if not any(a["id"] == alert_id for a in owned):
        return jsonify({"error": "alert not found"}), 404
    abf_repo.set_alert_status(g.tenant_id, alert_id, _ALERT_STATUSES[op])
    _audit(agent, f"abf.alert.{_ALERT_STATUSES[op]}",
           {"alert_ref": alert_id, "actor_user_id": session.get("user_id")}, "INFO")
    return jsonify({"id": alert_id, "status": _ALERT_STATUSES[op]}), 200


# --------------------------------------------------------------------------- #
# Rules
# --------------------------------------------------------------------------- #
@abf_bp.route("/agents/<int:agent_id>/rules", methods=["GET"])
@tenant_scoped
def list_rules(agent_id):
    if _tenant_agent(agent_id) is None:
        return jsonify({"error": "agent not found"}), 404
    return jsonify({
        "catalog_version": R.CATALOG_VERSION,
        "builtin": R.catalog(),
        "customisations": abf_repo.list_rules(g.tenant_id, agent_id),
    }), 200


def _validate_rule(body, *, partial=False):
    """Return (spec, error). Rules are data only: no pattern or code accepted."""
    spec = {}
    if not partial:
        kind = body.get("kind", "override")
        if kind not in ("override", "threshold"):
            return None, "kind must be 'override' or 'threshold'"
        spec["kind"] = kind
        key = str(body.get("rule_key") or "").strip()
        if kind == "override" and key not in R.BUILTIN_RULE_IDS:
            return None, "override rule_key must be a built-in rule id"
        if kind == "threshold" and not be._ID_RE.match(key or "-"):
            return None, "threshold rule_key must match [A-Za-z0-9_.:-]{1,128}"
        spec["rule_key"] = key
    if "enabled" in body:
        if not isinstance(body["enabled"], bool):
            return None, "enabled must be a boolean"
        spec["enabled"] = body["enabled"]
    if body.get("risk_level") is not None:
        if body["risk_level"] not in R.RISK_LEVELS:
            return None, f"risk_level must be one of {list(R.RISK_LEVELS)}"
        spec["risk_level"] = body["risk_level"]
    if body.get("enforcement_action") is not None:
        if body["enforcement_action"] not in R.ENFORCEMENT_ACTIONS:
            return None, f"enforcement_action must be one of {list(R.ENFORCEMENT_ACTIONS)}"
        spec["enforcement_action"] = body["enforcement_action"]
    for key, lo, hi in (("threshold", 1, 100000), ("window_seconds", 1, 86400)):
        if body.get(key) is not None:
            v = body[key]
            if not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi:
                return None, f"{key} must be an integer in [{lo}, {hi}]"
            spec[key] = v
    if body.get("category") is not None:
        cat = str(body["category"]).upper()
        if cat not in es.VALID_CATEGORIES:
            return None, "invalid category"
        spec["category"] = cat
    if body.get("matcher") is not None:
        m = body["matcher"]
        if not isinstance(m, dict) or set(m) - {"category", "action_glob", "outcome", "resource_prefix"}:
            return None, "matcher accepts only category, action_glob, outcome, resource_prefix"
        if any(not isinstance(v, str) or len(v) > 256 for v in m.values()):
            return None, "matcher values must be strings of at most 256 chars"
        spec["matcher"] = m
    if body.get("description") is not None:
        spec["description"] = str(body["description"])[:1000]
    if not partial and spec["kind"] == "threshold" and not (
            spec.get("threshold") and spec.get("window_seconds")):
        return None, "threshold rules need threshold and window_seconds"
    return spec, None


@abf_bp.route("/agents/<int:agent_id>/rules", methods=["POST"])
@role_required("admin")
def create_rule(agent_id):
    agent = _tenant_agent(agent_id)
    if agent is None:
        return jsonify({"error": "agent not found"}), 404
    body = json_body()
    spec, err = _validate_rule(body)
    if err:
        return jsonify({"error": err}), 400
    scope = body.get("scope", "agent")
    if scope not in ("agent", "tenant"):
        return jsonify({"error": "scope must be 'agent' or 'tenant'"}), 400
    spec["agent_id"] = agent_id if scope == "agent" else None
    rid = abf_repo.create_rule(g.tenant_id, spec, created_by_user_id=session.get("user_id"))
    _audit(agent, "abf.rule.created", {"rule_ref": rid, "rule_key": spec["rule_key"],
                                       "kind": spec["kind"], "scope": scope,
                                       "actor_user_id": session.get("user_id")})
    return jsonify(abf_repo.get_rule(g.tenant_id, rid)), 201


@abf_bp.route("/agents/<int:agent_id>/rules/<int:rule_id>", methods=["PATCH"])
@role_required("admin")
def update_rule(agent_id, rule_id):
    agent = _tenant_agent(agent_id)
    if agent is None:
        return jsonify({"error": "agent not found"}), 404
    rule = abf_repo.get_rule(g.tenant_id, rule_id)
    if rule is None or rule["agent_id"] not in (None, agent_id):
        return jsonify({"error": "rule not found"}), 404
    spec, err = _validate_rule(json_body(), partial=True)
    if err:
        return jsonify({"error": err}), 400
    if not spec:
        return jsonify({"error": "no changes"}), 400
    abf_repo.update_rule(g.tenant_id, rule_id, spec)
    _audit(agent, "abf.rule.updated", {"rule_ref": rule_id, "changes": sorted(spec),
                                       "actor_user_id": session.get("user_id")})
    return jsonify(abf_repo.get_rule(g.tenant_id, rule_id)), 200


# --------------------------------------------------------------------------- #
# Quarantine
# --------------------------------------------------------------------------- #
@abf_bp.route("/agents/<int:agent_id>/quarantine", methods=["POST"])
@role_required("operator")
def quarantine(agent_id):
    from ..aro.lifecycle_service import IllegalTransition, LifecycleService
    from ..zaf import wiring
    agent = _tenant_agent(agent_id)
    if agent is None:
        return jsonify({"error": "agent not found"}), 404
    body = json_body()
    reason = str(body.get("reason") or "manual quarantine").strip()[:500]
    svc = LifecycleService(zaf_pre_transition=wiring.build_live_pre_transition())
    try:
        result = wiring.quarantine_agent(
            g.tenant_id, agent_id, reason=f"manual: {reason}", lifecycle_svc=svc,
            revoke_credentials=bool(body.get("revoke_credentials", False)))
    except IllegalTransition as exc:
        return jsonify({"error": str(exc)}), 409
    except LookupError:
        return jsonify({"error": "agent not found"}), 404
    _audit(agent, "abf.quarantine.manual", {"reason": reason,
                                            "actor_user_id": session.get("user_id"),
                                            "revoked": result.get("revoked")}, "HIGH")
    return jsonify(result), 200


# --------------------------------------------------------------------------- #
# Baselines
# --------------------------------------------------------------------------- #
BASELINE_LOOKBACK = timedelta(days=7)


@abf_bp.route("/agents/<int:agent_id>/baseline", methods=["GET"])
@tenant_scoped
def get_baseline(agent_id):
    if _tenant_agent(agent_id) is None:
        return jsonify({"error": "agent not found"}), 404
    return jsonify({"agent_id": agent_id,
                    "baselines": abf_repo.list_baselines(g.tenant_id, agent_id),
                    "min_samples": B.MIN_SAMPLES}), 200


@abf_bp.route("/agents/<int:agent_id>/baseline/refresh", methods=["POST"])
@role_required("operator")
def refresh_baseline(agent_id):
    agent = _tenant_agent(agent_id)
    if agent is None:
        return jsonify({"error": "agent not found"}), 404
    window = B.DEFAULT_WINDOW_SECONDS
    now = datetime.now(timezone.utc)
    end = datetime.fromtimestamp((int(now.timestamp()) // window) * window, tz=timezone.utc)
    start = end - BASELINE_LOOKBACK
    reset_at = abf_repo.baseline_reset_at(g.tenant_id, agent_id)
    if reset_at is not None:
        reset_at = reset_at if reset_at.tzinfo else reset_at.replace(tzinfo=timezone.utc)
        aligned = datetime.fromtimestamp(-(-int(reset_at.timestamp()) // window) * window,
                                         tz=timezone.utc)
        start = max(start, aligned)
    rows = abf_repo.aggregated_event_rows(g.tenant_id, agent["identity"], since=start,
                                          until=end, window_seconds=window)
    out = []
    for metric in B.METRICS:
        b = B.compute(metric, rows, start=start, end=end, window_seconds=window)
        abf_repo.upsert_baseline(g.tenant_id, agent_id, b)
        out.append(b.as_dict())
    return jsonify({"agent_id": agent_id, "from": start.isoformat(), "to": end.isoformat(),
                    "baselines": out}), 200


@abf_bp.route("/agents/<int:agent_id>/baseline/reset", methods=["POST"])
@role_required("admin")
def reset_baseline(agent_id):
    agent = _tenant_agent(agent_id)
    if agent is None:
        return jsonify({"error": "agent not found"}), 404
    n = abf_repo.reset_baselines(g.tenant_id, agent_id, session.get("user_id"))
    _audit(agent, "abf.baseline.reset", {"metrics_reset": n,
                                         "actor_user_id": session.get("user_id")})
    return jsonify({"agent_id": agent_id, "metrics_reset": n}), 200


# --------------------------------------------------------------------------- #
# Audit chain
# --------------------------------------------------------------------------- #
@abf_bp.route("/governance/audit/verify", methods=["GET"])
@role_required("admin")
def verify_audit_chain():
    return jsonify(audit_chain.verify(g.tenant_id)), 200


@abf_bp.route("/governance/audit/seal", methods=["POST"])
@role_required("admin")
def seal_audit_chain():
    try:
        result = audit_chain.seal(g.tenant_id)
    except Exception:  # noqa: BLE001
        logger.exception("audit chain seal failed")
        return jsonify({"error": "seal failed"}), 503
    return jsonify(result), 200


# --------------------------------------------------------------------------- #
# Approval aliases (no duplicated logic: same view functions)
# --------------------------------------------------------------------------- #
def register_approval_aliases(bp: Blueprint) -> None:
    from . import zaf_governance_routes as zg
    bp.add_url_rule("/approvals", "approvals_list", zg.list_approvals, methods=["GET"])
    bp.add_url_rule("/approvals/<int:approval_id>/approve", "approvals_approve",
                    zg.approve_request, methods=["POST"])
    bp.add_url_rule("/approvals/<int:approval_id>/reject", "approvals_reject",
                    zg.reject_request, methods=["POST"])


@abf_bp.route("/approvals/<int:approval_id>", methods=["GET"])
@tenant_scoped
def get_approval(approval_id):
    approval = approval_service.get_approval(g.tenant_id, approval_id)
    if approval is None:
        return jsonify({"error": "approval not found"}), 404
    return jsonify(approval), 200


register_approval_aliases(abf_bp)
