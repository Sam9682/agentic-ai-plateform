"""Agent lifecycle API (Task 7).

Exposes ``aro_agent_bp`` under ``/api/v1/agents``:

* GET    /                 - list agents in the tenant
* POST   /                 - register an agent (operator role)
* GET    /{id}             - agent details
* DELETE /{id}             - delete an agent (admin role)
* POST   /{id}/start       - start the agent (operator role)
* POST   /{id}/stop        - stop the agent (operator role)
* POST   /{id}/restart     - restart the agent (operator role)
* GET    /{id}/status      - current status
* GET    /{id}/logs        - recent logs (adapter-dependent)

Lifecycle operations run through :class:`LifecycleService`, which validates the
transition graph and emits events. The real adapter + launcher are wired here;
illegal transitions yield 409.
"""

from __future__ import annotations

import logging

from flask import Blueprint, g, jsonify

from ..authz import role_required, tenant_scoped
from ..aro import agent_repository as repo
from ..aro import runtime_registry_repository as runtimes
from ..aro.lifecycle_service import IllegalTransition, LifecycleService
from .aro_common import get_text, json_body

logger = logging.getLogger(__name__)

aro_agent_bp = Blueprint("aro_agent", __name__, url_prefix="/api/v1/agents")


def _service() -> LifecycleService:
    """Build a LifecycleService wired to the real adapters + launcher.

    The adapter/launcher wiring is created lazily so importing this module does
    not import heavy adapter/SSH dependencies. For now the launcher is a no-op
    placeholder returning no placement; Task 8/9 provide real adapters and the
    execution manager performs the real launch.
    """
    return LifecycleService()


@aro_agent_bp.route("/", methods=["GET"])
@tenant_scoped
def list_agents():
    return jsonify({"agents": repo.list_agents(g.tenant_id)}), 200


@aro_agent_bp.route("/", methods=["POST"])
@role_required("operator")
def register_agent():
    body = json_body()
    name = (body.get("name") or "").strip()
    runtime_id = body.get("runtime_id")
    if not name or runtime_id is None:
        return jsonify({"error": "name and runtime_id are required"}), 400
    # The runtime must exist in the tenant.
    if runtimes.get_runtime(g.tenant_id, int(runtime_id)) is None:
        return jsonify({"error": "unknown runtime_id"}), 400
    try:
        agent = repo.create_agent(
            g.tenant_id, g.tenant_slug, name, int(runtime_id),
            environment_id=body.get("environment_id"),
            owner_user_id=None,
            configuration=body.get("configuration") or {},
            permissions=body.get("permissions") or [],
        )
    except Exception as exc:  # noqa: BLE001 - surface duplicate name/identity
        return jsonify({"error": f"could not create agent: {exc}"}), 409
    return jsonify(agent), 201


@aro_agent_bp.route("/<int:agent_id>", methods=["GET"])
@tenant_scoped
def get_agent(agent_id):
    agent = repo.get_agent(g.tenant_id, agent_id)
    if agent is None:
        return jsonify({"error": get_text("not_found")}), 404
    return jsonify(agent), 200


@aro_agent_bp.route("/<int:agent_id>", methods=["DELETE"])
@role_required("admin")
def delete_agent(agent_id):
    if not repo.delete_agent(g.tenant_id, agent_id):
        return jsonify({"error": get_text("not_found")}), 404
    return jsonify({"deleted": agent_id}), 200


def _run_lifecycle(agent_id, op):
    agent = repo.get_agent(g.tenant_id, agent_id)
    if agent is None:
        return jsonify({"error": get_text("not_found")}), 404
    svc = _service()
    try:
        result = op(svc, g.tenant_id, agent_id)
    except IllegalTransition as exc:
        return jsonify({"error": str(exc)}), 409
    except LookupError:
        return jsonify({"error": get_text("not_found")}), 404
    return jsonify(result), 200


@aro_agent_bp.route("/<int:agent_id>/ready", methods=["POST"])
@role_required("operator")
def ready_agent(agent_id):
    """Drive the agent to READY (install + configure)."""
    return _run_lifecycle(agent_id, lambda s, t, a: s.install_and_ready(t, a))


@aro_agent_bp.route("/<int:agent_id>/start", methods=["POST"])
@role_required("operator")
def start_agent(agent_id):
    return _run_lifecycle(agent_id, lambda s, t, a: s.start(t, a))


@aro_agent_bp.route("/<int:agent_id>/stop", methods=["POST"])
@role_required("operator")
def stop_agent(agent_id):
    return _run_lifecycle(agent_id, lambda s, t, a: s.stop(t, a))


@aro_agent_bp.route("/<int:agent_id>/restart", methods=["POST"])
@role_required("operator")
def restart_agent(agent_id):
    return _run_lifecycle(agent_id, lambda s, t, a: s.restart(t, a))


@aro_agent_bp.route("/<int:agent_id>/status", methods=["GET"])
@tenant_scoped
def agent_status(agent_id):
    agent = repo.get_agent(g.tenant_id, agent_id)
    if agent is None:
        return jsonify({"error": get_text("not_found")}), 404
    return jsonify({"id": agent["id"], "status": agent["status"]}), 200
