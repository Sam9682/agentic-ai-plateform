"""ZAF governance API (Task 11).

Exposes ``zaf_governance_bp`` under ``/api/v1/governance``:

* POST   /policies         - create a policy version (admin); accepts JSON rules
                             or an SRS-style YAML document via {"yaml": "..."}
* GET    /policies         - list policies
* PUT    /policies/{id}    - enable/disable a policy (admin)
* POST   /evaluate         - evaluate an action (returns the decision)
* GET    /decisions        - list recorded decisions (audit)

Evaluation runs through :mod:`governance_service`, which records the decision
and emits an audit event.
"""

from __future__ import annotations

import logging

from flask import Blueprint, g, jsonify

from flask import session

from ..authz import role_required, tenant_scoped
from ..zaf import approval_service as approvals
from ..zaf import governance_service as gov
from ..zaf import policy_repository as repo
from .aro_common import get_text, json_body

logger = logging.getLogger(__name__)

zaf_governance_bp = Blueprint("zaf_governance", __name__, url_prefix="/api/v1/governance")


@zaf_governance_bp.route("/policies", methods=["POST"])
@role_required("admin")
def create_policy():
    body = json_body()
    try:
        if "yaml" in body:
            parsed = repo.parse_policy_yaml(body["yaml"])
            name, rules, scope = parsed["name"], parsed["rules"], parsed["scope"]
        else:
            name = (body.get("name") or "").strip()
            rules = body.get("rules")
            scope = body.get("scope", "tenant")
            if not name or not isinstance(rules, list):
                return jsonify({"error": "name and rules[] are required"}), 400
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    policy_id = repo.create_policy(g.tenant_id, name, rules, scope=scope)
    return jsonify({"id": policy_id, "name": name}), 201


@zaf_governance_bp.route("/policies", methods=["GET"])
@tenant_scoped
def list_policies():
    return jsonify({"policies": repo.list_policies(g.tenant_id)}), 200


@zaf_governance_bp.route("/evaluate", methods=["POST"])
@tenant_scoped
def evaluate():
    body = json_body()
    action = (body.get("action") or "").strip()
    if not action:
        return jsonify({"error": "action is required"}), 400
    decision = gov.decide(
        g.tenant_id, action,
        agent_db_id=body.get("agent_db_id"),
        agent_identity=body.get("agent_identity"),
        resource=body.get("resource"),
        params=body.get("params") or {},
        context=body.get("context") or {},
    )
    return jsonify(decision), 200


@zaf_governance_bp.route("/decisions", methods=["GET"])
@tenant_scoped
def list_decisions():
    return jsonify({"decisions": repo.list_decisions(g.tenant_id)}), 200


@zaf_governance_bp.route("/approvals", methods=["GET"])
@tenant_scoped
def list_approvals():
    return jsonify({"approvals": approvals.list_pending(g.tenant_id)}), 200


@zaf_governance_bp.route("/approvals/<int:approval_id>/approve", methods=["POST"])
@role_required("admin")
def approve_request(approval_id):
    result = approvals.approve(g.tenant_id, approval_id, session["user_id"])
    if result is None:
        return jsonify({"error": "approval not pending or not found"}), 404
    return jsonify(result), 200


@zaf_governance_bp.route("/approvals/<int:approval_id>/reject", methods=["POST"])
@role_required("admin")
def reject_request(approval_id):
    result = approvals.reject(g.tenant_id, approval_id, session["user_id"])
    if result is None:
        return jsonify({"error": "approval not pending or not found"}), 404
    return jsonify(result), 200
