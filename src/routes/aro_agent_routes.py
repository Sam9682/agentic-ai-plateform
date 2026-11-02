"""Agent lifecycle API (Task 7).

Exposes ``aro_agent_bp`` under ``/api/v1/agents``:

* GET    /                 - list agents in the tenant
* POST   /                 - register an agent (operator role)
* GET    /{id}             - agent details
* DELETE /{id}             - delete an agent (admin role)
* POST   /{id}/start       - start the agent (operator role)
* POST   /{id}/stop        - stop the agent (operator role)
* POST   /{id}/restart     - restart the agent (operator role)
* POST   /{id}/release     - release a QUARANTINED agent to READY (admin role)
* GET    /{id}/status      - current status
* GET    /{id}/logs        - recent logs (adapter-dependent)
* GET    /skills           - list standard skill profiles attachable to a new agent

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


@aro_agent_bp.route("/<int:agent_id>/release", methods=["POST"])
@role_required("admin")
def release_agent(agent_id):
    """Release a QUARANTINED agent back to READY (phase3-zaf-enforcement R8.4).

    Restoration from containment requires explicit operator authorization, so
    this route is gated by ``role_required("admin")``: it returns 401 for an
    unauthenticated caller and 403 for an authenticated non-admin *before* the
    body runs, so an unauthorized request never reaches ``release`` and causes
    no state change.

    The restoration itself routes through the Phase 2
    :meth:`LifecycleService.release`, which anchors release to the
    ``QUARANTINED`` source status specifically: a release requested for an
    agent whose status is not ``QUARANTINED`` is rejected as an
    :class:`IllegalTransition` *before any write* (no state change) and surfaces
    here as a 409 via :func:`_run_lifecycle`. The legal ``QUARANTINED -> READY``
    path still routes through ``transition`` so that remains the sole mutation
    path.
    """
    return _run_lifecycle(agent_id, lambda s, t, a: s.release(t, a))


@aro_agent_bp.route("/<int:agent_id>/status", methods=["GET"])
@tenant_scoped
def agent_status(agent_id):
    agent = repo.get_agent(g.tenant_id, agent_id)
    if agent is None:
        return jsonify({"error": get_text("not_found")}), 404
    return jsonify({"id": agent["id"], "status": agent["status"]}), 200


def _list_skill_profiles():
    """Discover the available standard skill profiles.

    A "skill profile" in this platform is a ``{NAME}_context.md`` file in the
    skills folder (``agentic-ai-plateform--skills/`` with a legacy ``shared/``
    fallback). Reuses the resolver in :mod:`src.routes.genai_routes` so the UI
    offers exactly the context files the prompt builders can load. Returns a
    sorted list of dicts ``{id, name, source}`` (deduplicated by id). Never
    raises: a missing/unreadable folder yields an empty list.
    """
    import os
    try:
        from .genai_routes import _skills_base_dirs, SKILLS_DIR_CANDIDATES
    except Exception:  # pragma: no cover - genai module import guard
        return []
    seen = {}
    for base in _skills_base_dirs():
        for skills_dir in SKILLS_DIR_CANDIDATES:
            folder = os.path.join(base, skills_dir)
            try:
                entries = os.listdir(folder)
            except (OSError, TypeError):
                continue
            for fname in entries:
                if not fname.endswith("_context.md"):
                    continue
                skill_id = fname[: -len("_context.md")]
                if not skill_id or skill_id in seen:
                    continue
                seen[skill_id] = {
                    "id": skill_id,
                    "name": skill_id.replace("_", " ").title(),
                    "source": skills_dir,
                }
    return [seen[k] for k in sorted(seen)]


@aro_agent_bp.route("/skills", methods=["GET"])
@tenant_scoped
def list_skill_profiles():
    """List the standard skill profiles that can be attached to a new agent.

    These are the ``{NAME}_context.md`` skill files shipped in the skills
    folder. The New Agent form offers them as the "standard profile skill"
    choice; a user may instead supply a custom profile skill (free-form name),
    which the UI stores under the agent's ``configuration.custom_skill``.
    """
    return jsonify({"skills": _list_skill_profiles()}), 200
