"""Agent task API (Task 10).

Exposes ``aro_task_bp`` under ``/api/v1/agents/tasks``:

* POST   /tasks            - submit a task (operator role); idempotent on
                             an optional ``idempotency_key``
* GET    /tasks/{id}       - task status + result
* POST   /tasks/{id}/cancel- request cancellation
* GET    /tasks/{id}/events- SSE stream of the task's events (no polling)

Execution is performed by the out-of-process :class:`AgentTaskWorker`; the API
only enqueues, reports, cancels and streams events. The SSE endpoint replays the
task's events and closes when a terminal task event is seen.
"""

from __future__ import annotations

import json
import logging
import time

from flask import Blueprint, Response, g, jsonify, stream_with_context

from ..authz import role_required, tenant_scoped
from ..aro import agent_repository as agent_repo
from ..aro import events_repository as events_repo
from ..aro import task_repository as repo
from .aro_common import get_text, json_body

logger = logging.getLogger(__name__)

aro_task_bp = Blueprint("aro_task", __name__, url_prefix="/api/v1/agents")

_TERMINAL_TASK_EVENTS = {"task.succeeded", "task.failed", "task.cancelled"}


@aro_task_bp.route("/tasks", methods=["POST"])
@role_required("operator")
def submit_task():
    body = json_body()
    agent_id = body.get("agent_id")
    if agent_id is None:
        return jsonify({"error": "agent_id is required"}), 400
    agent = agent_repo.get_agent(g.tenant_id, int(agent_id))
    if agent is None:
        return jsonify({"error": "unknown agent_id"}), 400
    task = repo.submit(
        g.tenant_id, int(agent_id),
        operation=body.get("operation", "prompt"),
        payload=body.get("payload") or {},
        priority=int(body.get("priority", 100)),
        max_attempts=int(body.get("max_attempts", 1)),
        timeout_seconds=int(body.get("timeout_seconds", 1800)),
        idempotency_key=body.get("idempotency_key"),
        policy_context=body.get("policy_context") or {},
    )
    return jsonify(task), 201


@aro_task_bp.route("/tasks/<int:task_id>", methods=["GET"])
@tenant_scoped
def get_task(task_id):
    task = repo.get_task(g.tenant_id, task_id)
    if task is None:
        return jsonify({"error": get_text("not_found")}), 404
    return jsonify(task), 200


@aro_task_bp.route("/tasks/<int:task_id>/cancel", methods=["POST"])
@role_required("operator")
def cancel_task(task_id):
    if not repo.request_cancel(g.tenant_id, task_id):
        return jsonify({"error": get_text("not_found")}), 404
    return jsonify({"task_id": task_id, "cancel_requested": True}), 200


@aro_task_bp.route("/tasks/<int:task_id>/events", methods=["GET"])
@tenant_scoped
def task_events(task_id):
    """Stream a task's events as SSE until a terminal task event is emitted."""
    task = repo.get_task(g.tenant_id, task_id)
    if task is None:
        return jsonify({"error": get_text("not_found")}), 404

    tenant_id = g.tenant_id
    correlation_id = f"task-{task['task_ref']}"

    @stream_with_context
    def generate():
        seen = set()
        # Bounded loop so a never-finishing task can't hold the worker forever.
        for _ in range(600):  # ~up to 600 polls
            events = events_repo.list_events(
                tenant_id, correlation_id=correlation_id, limit=200
            )
            # events are newest-first; replay oldest-first.
            for ev in reversed(events):
                if ev["id"] in seen:
                    continue
                seen.add(ev["id"])
                yield f"event: {ev['event_type']}\ndata: {json.dumps(ev)}\n\n"
                if ev["event_type"] in _TERMINAL_TASK_EVENTS:
                    return
            time.sleep(0.5)

    return Response(generate(), mimetype="text/event-stream")
