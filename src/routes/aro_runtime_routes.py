"""Agent runtime registry API (Task 4).

Exposes ``aro_runtime_bp`` under ``/api/v1/agents/runtimes``:

* GET    /runtimes           - list the tenant's registered runtimes
* POST   /runtimes           - register/update a runtime (admin role)
* GET    /runtimes/{id}      - runtime details
* GET    /runtimes/{id}/health - report the runtime's declared health check

Auth + tenant scoping come from :mod:`src.authz`. Registration validates the
definition through the surface-agnostic :mod:`runtime_registry_service` (pinned
versions, integrity-verified installs, no arbitrary scripts).
"""

from __future__ import annotations

import logging

from flask import Blueprint, g, jsonify

from ..authz import role_required, tenant_scoped
from ..aro import runtime_registry_repository as repo
from ..aro import runtime_registry_service as svc
from .aro_common import get_text, json_body

logger = logging.getLogger(__name__)

aro_runtime_bp = Blueprint("aro_runtime", __name__, url_prefix="/api/v1/agents")


@aro_runtime_bp.route("/runtimes", methods=["GET"])
@tenant_scoped
def list_runtimes():
    """List runtimes registered in the caller's tenant."""
    return jsonify({"runtimes": repo.list_runtimes(g.tenant_id)}), 200


@aro_runtime_bp.route("/runtimes", methods=["POST"])
@role_required("admin")
def register_runtime():
    """Register (or update) a runtime definition. Requires tenant admin."""
    try:
        definition = svc.validate_definition(json_body())
    except svc.RuntimeValidationError as exc:
        return jsonify({"error": str(exc)}), 400
    runtime_id = repo.register(g.tenant_id, definition)
    return jsonify({"id": runtime_id, "identifier": definition["identifier"]}), 201


@aro_runtime_bp.route("/runtimes/<int:runtime_id>", methods=["GET"])
@tenant_scoped
def get_runtime(runtime_id):
    """Return a single runtime's details, tenant-scoped."""
    runtime = repo.get_runtime(g.tenant_id, runtime_id)
    if runtime is None:
        return jsonify({"error": get_text("not_found")}), 404
    return jsonify(runtime), 200


@aro_runtime_bp.route("/runtimes/<int:runtime_id>/health", methods=["GET"])
@tenant_scoped
def runtime_health(runtime_id):
    """Report the runtime's declared health-check definition.

    Live probing of an installed runtime belongs to the lifecycle/adapter layer
    (Task 7+); at the registry level we surface the declared health_check so
    callers know how the runtime reports health.
    """
    runtime = repo.get_runtime(g.tenant_id, runtime_id)
    if runtime is None:
        return jsonify({"error": get_text("not_found")}), 404
    return jsonify({
        "id": runtime["id"],
        "identifier": runtime["identifier"],
        "status": runtime["status"],
        "health_check": runtime["health_check"],
    }), 200
