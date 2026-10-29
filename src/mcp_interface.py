#!/usr/bin/env python3
"""Spec-compliant MCP interface for the agentic-ai-plateform control plane.

This module exposes the platform's capabilities as a Model Context Protocol
(MCP) server over the **stdio** transport, using the official Python MCP SDK
(``mcp`` package, ``FastMCP``). It speaks the full JSON-RPC 2.0 MCP protocol
(``initialize`` handshake, ``notifications/initialized``, ``tools/list``,
``tools/call``), so it is directly compatible with any spec-compliant MCP
client — including shai (>= 0.2.2), which drives stdio MCP servers through the
Rust ``rmcp`` crate's ``TokioChildProcess`` transport.

Run it as a module so relative imports resolve::

    python -m src.mcp_interface

Registration in a shai agent config (``~/.config/shai/agents/<name>.config.json``)
under ``tools.mcp``::

    "mcp": {
      "agentic-ai-plateform": {
        "type": "stdio",
        "command": "/abs/path/.venv/bin/python",
        "args": ["-m", "src.mcp_interface"]
      }
    }

Design notes
------------
* The business logic is **not** reimplemented here. Each tool is a thin wrapper
  over the same surface-agnostic services the Dashboard / REST API / CLI use
  (``agent_control_service``, ``TemplateCatalog`` / ``TemplateDeployService``,
  ``database_postgres``), so behaviour stays consistent across every surface.
* Tools never raise across the protocol boundary: database/runtime failures are
  caught and returned as a structured ``{"error": ...}`` payload so the client
  receives a well-formed tool result instead of a transport error.
* The agent-control tool mirrors ``GET /api/agent-control/containers`` and is
  the native-tool equivalent of what ``AGENTS_CONTROL_AGENT`` polls over HTTP.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional

# Ensure the project root is importable when launched as a script or module,
# so ``src.*`` and the ``src`` package's relative imports both resolve.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from mcp.server.fastmcp import FastMCP  # noqa: E402

mcp = FastMCP("agentic-ai-plateform")


# --------------------------------------------------------------------------- #
# Lazy imports
#
# Importing the heavy platform modules (which may open DB pools) is deferred to
# call time. This keeps ``initialize`` / ``tools/list`` fast and lets the server
# start and advertise its tools even if the database is momentarily unavailable
# — individual calls then fail gracefully with a structured error.
# --------------------------------------------------------------------------- #
def _err(exc: Exception, kind: str = "error") -> Dict[str, str]:
    """Return a structured, non-raising error payload for a tool result."""
    return {kind: f"{type(exc).__name__}: {exc}"}


# Map each OPS tool to its canonical Operator_Action (tool name -> action string).
_OPS_ACTION = {
    "start": "START",
    "stop": "STOP",
    "ps": "PS",
    "logs": "LOGS",
    "backup": "BACKUP",
    "restore": "RESTORE_DATABASE",
}
_OPS_TIMEOUT = 1800  # TIMEOUT_QCHAT_OPERATOR_RUN
_DEV_TIMEOUT = 1800  # TIMEOUT_request_dev_ai_for_app_RUN


def _resolve_app_and_user(application_name: str, user_id: int):
    """Resolve the target application and user from minimal arguments.

    Queries the Applications_Table by name, the Users_Table by id, and the
    latest ``deployments.deployment_path`` for the authoritative application
    folder (falling back to the on-disk
    ``/home/{LINUX_USER_INSTALLATION}/deployments/{application_name}``
    convention when no deployment row is present). All imports are deferred to
    call time so ``tools/list`` opens no database connection.

    Args:
        application_name: The application name to resolve (``applications.name``).
        user_id: The user id to resolve (``users.id``).

    Returns:
        A 2-tuple ``(resolved, None)`` on success, where ``resolved`` is a dict
        with keys ``app_id``, ``folder``, ``user_name``, ``user_email`` and
        ``username``; or ``(None, error_payload)`` when the application or user
        is unknown. On failure the Agentic_Engine is never launched.
    """
    from src.database_postgres import db_manager
    from src.config_postgres import LINUX_USER_INSTALLATION

    app = db_manager.execute_query(
        "SELECT id FROM applications WHERE name = %s",
        (application_name,),
        fetch_one=True,
    )
    if not app:
        return None, {
            "error": "unknown application",
            "application_name": application_name,
        }

    user = db_manager.execute_query(
        "SELECT username, email, first_name, last_name FROM users WHERE id = %s",
        (user_id,),
        fetch_one=True,
    )
    if not user:
        return None, {"error": "unknown user", "user_id": user_id}

    # Prefer the authoritative deployment_path; fall back to the folder convention.
    dep = db_manager.execute_query(
        "SELECT deployment_path FROM deployments WHERE application_name = %s "
        "ORDER BY created_at DESC LIMIT 1",
        (application_name,),
        fetch_one=True,
    )
    folder = (
        dep[0]
        if dep and dep[0]
        else f"/home/{LINUX_USER_INSTALLATION}/deployments/{application_name}"
    )

    user_name = f"{user[2] or ''} {user[3] or ''}".strip() or (user[0] or "User")
    user_email = user[1] or ""
    return (
        {
            "app_id": app[0],
            "folder": folder,
            "user_name": user_name,
            "user_email": user_email,
            "username": user[0],
        },
        None,
    )


def _resolve_engine_config() -> tuple:
    """Read ``agentic_engine`` / ``agentic_command`` from the configuration table.

    Mirrors the lazy, per-call lookup the Flask routes perform in
    ``genai_routes.py``: both values come from
    ``SELECT value FROM configuration WHERE key = %s AND (parent IS NULL)``.
    Falls back to the ``AI_ENGINE`` default when no engine row exists, and to an
    empty string (no deployControlPlan command) when no command row exists.

    Returns:
        A ``(engine, command)`` tuple where ``engine`` is the configured engine
        or the ``AI_ENGINE`` default and ``command`` is the configured
        deployControlPlan command or ``""``.
    """
    from src.database_postgres import db_manager
    from src.config_postgres import AI_ENGINE

    engine_row = db_manager.execute_query(
        "SELECT value FROM configuration WHERE key = %s AND (parent IS NULL)",
        ("agentic_engine",),
        fetch_one=True,
    )
    command_row = db_manager.execute_query(
        "SELECT value FROM configuration WHERE key = %s AND (parent IS NULL)",
        ("agentic_command",),
        fetch_one=True,
    )
    engine = engine_row[0] if engine_row else AI_ENGINE
    command = command_row[0] if command_row else ""
    return engine, command


def _run_operator_action(
    action: str, application_name: str, user_id: int
) -> Dict[str, Any]:
    """Shared body for the six OPS tools (start/stop/ps/logs/backup/restore).

    Resolves the application and user, builds the prompt through the shared
    ``return_prompt_for_operator`` builder, and runs the agentic engine
    synchronously, returning a structured ``{success, returncode, output}``
    result. Never launches the engine when resolution fails, when the prompt
    builder raises, or when a recognized action has no execution context.

    Args:
        action: The canonical Operator_Action (e.g. ``"START"``, ``"BACKUP"``).
        application_name: The application to act on.
        user_id: The user commanding the action.

    Returns:
        The Engine_Result as a dict on a completed run, or an Error_Payload dict
        when resolution, prompt building, or engine resolution fails.
    """
    from src.routes.genai_routes import return_prompt_for_operator
    from src.routes.engine_runner import run_agentic_engine, EngineNotFoundError

    resolved, err = _resolve_app_and_user(application_name, user_id)
    if err:
        return err

    try:
        prompt, is_executing = return_prompt_for_operator(
            action,
            application_name,
            resolved["folder"],
            resolved["user_name"],
            resolved["user_email"],
            user_id=user_id,
        )
    except Exception as exc:  # noqa: BLE001 — R5.2: no raise across the boundary
        return _err(exc, kind="error")

    if prompt is None:  # R5.1 — recognized action, missing context file
        return {
            "error": "no execution context available for action",
            "action": action,
            "application_name": application_name,
        }
    if not is_executing:  # unrecognized / advisor fallback — OPS requires executing
        return {
            "error": "action is not an executable operator action",
            "action": action,
        }

    engine, command = _resolve_engine_config()
    try:
        result = run_agentic_engine(
            prompt,
            timeout=_OPS_TIMEOUT,
            agentic_engine=engine,
            agentic_command=command,
        )
    except EngineNotFoundError as exc:  # R5.3
        return {"error": str(exc), "engine": exc.engine, "success": False}

    if result.error and result.returncode is None:  # engine never ran
        return {
            "success": False,
            "returncode": None,
            "output": result.output,
            "error": result.error,
        }

    # Billing: START/STOP only, and only when the action executed cleanly. No
    # billing call occurs for other actions or non-zero exits (R6.1, R6.2).
    if action in ("START", "STOP") and result.success:
        try:
            from src.routes.billing_routes import record_billing_activity

            record_billing_activity(user_id, application_name, action)
        except Exception as exc:  # noqa: BLE001 — R6.3: surface, never raise
            result.extra["billing_error"] = f"{type(exc).__name__}: {exc}"

    return result.as_dict()


def _run_developer_action(
    application_name: str, user_id: int, instruction: str
) -> Dict[str, Any]:
    """Shared body for the ``modify_code`` tool (MODIFY_CODE / Developer path).

    Resolves the application and user, derives the Gitea/GitHub repository URLs
    and the modification branch name, builds the prompt through the shared
    ``return_prompt_for_developer`` builder, and runs the agentic engine
    synchronously, returning a structured ``{success, returncode, output}``
    result. Never launches the engine when resolution fails, when the prompt
    builder raises, or when the builder yields no prompt (missing context).

    On a clean engine exit, records the modification in the application's most
    recent deployment ``modification_history`` and updates ``gitea_branch_url``,
    setting ``branch_name`` on the result. Any failure in this post-processing
    is surfaced as a ``gitea_error`` field and never raised (R7.5).

    Args:
        application_name: The application whose source code to modify.
        user_id: The user commanding the modification.
        instruction: The natural-language change instruction (the ``message``
            passed to the prompt builder).

    Returns:
        The Engine_Result as a dict on a completed run, or an Error_Payload dict
        when resolution, prompt building, or engine resolution fails.
    """
    import json
    from datetime import datetime

    from src.routes.genai_routes import return_prompt_for_developer
    from src.routes.engine_runner import run_agentic_engine, EngineNotFoundError
    from src.database_postgres import db_manager

    resolved, err = _resolve_app_and_user(application_name, user_id)
    if err:
        return err

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    branch_name = f"{user_id}-automorph-{application_name}-{ts}"
    repo_github_url = f"git@github.com:Sam9682/{application_name}"
    repo_gitea_url = (
        f"http://gitadmin:password@localhost:3000/gitadmin/{branch_name}"
    )

    try:
        prompt = return_prompt_for_developer(
            "MODIFY_CODE",
            application_name,
            resolved["folder"],
            resolved["user_name"],
            resolved["user_email"],
            repo_gitea_url,
            branch_name,
            repo_github_url,
            instruction,
            user_id=user_id,
        )
    except Exception as exc:  # noqa: BLE001 — R5.2: no raise across the boundary
        return _err(exc, kind="error")

    if not prompt:  # R5.1 — missing execution context
        return {
            "error": "no execution context available for MODIFY_CODE",
            "application_name": application_name,
        }

    engine, command = _resolve_engine_config()
    try:
        result = run_agentic_engine(
            prompt,
            timeout=_DEV_TIMEOUT,
            agentic_engine=engine,
            agentic_command=command,
        )
    except EngineNotFoundError as exc:  # R5.3
        return {"error": str(exc), "engine": exc.engine, "success": False}

    if result.error and result.returncode is None:  # engine never ran
        return {
            "success": False,
            "returncode": None,
            "output": result.output,
            "error": result.error,
        }

    if result.success:  # R7.3 — Gitea branch + modification_history on clean exit
        try:
            dep = db_manager.execute_query(
                "SELECT id, modification_history FROM deployments "
                "WHERE user_id = %s AND application_name = %s "
                "ORDER BY created_at DESC LIMIT 1",
                (user_id, application_name),
                fetch_one=True,
            )
            if dep:
                dep_id, history = dep[0], dep[1] or []
                history.append({
                    "timestamp": datetime.now().isoformat(),
                    "branch_name": branch_name,
                    "gitea_url": repo_gitea_url,
                    "user": resolved["username"],
                    "message": instruction[:200],
                })
                db_manager.execute_query(
                    "UPDATE deployments SET gitea_branch_url = %s, "
                    "modification_history = %s::jsonb WHERE id = %s",
                    (repo_gitea_url, json.dumps(history), dep_id),
                )
                result.extra["branch_name"] = branch_name
            else:
                result.extra["gitea_error"] = "deployment record not found"
        except Exception as exc:  # noqa: BLE001 — R7.5: surface, never raise
            result.extra["gitea_error"] = f"{type(exc).__name__}: {exc}"

    return result.as_dict()


@mcp.tool()
def list_applications() -> List[Dict[str, Any]]:
    """List all applications registered in the platform catalog.

    Returns a list of ``{id, name, url, description}`` objects (empty list when
    none are registered), or a single ``{"error": ...}`` object on failure.
    """
    try:
        from src.database_postgres import db_manager

        rows = db_manager.execute_query(
            "SELECT id, name, git_url, description FROM applications ORDER BY name",
            fetch_all=True,
        )
        return [
            {"id": r[0], "name": r[1], "url": r[2], "description": r[3]}
            for r in (rows or [])
        ]
    except Exception as exc:  # noqa: BLE001 - surface as structured result
        return [_err(exc)]


@mcp.tool()
def add_application(name: str, url: str, description: str = "") -> Dict[str, str]:
    """Register a new application in the platform catalog.

    Args:
        name: Application name (required).
        url: Git/source URL for the application (required).
        description: Optional human-readable description.
    """
    try:
        from src.database_postgres import db_manager

        db_manager.execute_query(
            "INSERT INTO applications (name, git_url, description) VALUES (%s, %s, %s)",
            (name, url, description),
        )
        return {"message": "Application added successfully", "name": name}
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@mcp.tool()
def list_users() -> List[Dict[str, Any]]:
    """List all registered users (no sensitive fields: no passwords/secrets)."""
    try:
        from src.database_postgres import db_manager

        rows = db_manager.execute_query(
            "SELECT id, username, email, first_name, last_name, created_at FROM users",
            fetch_all=True,
        )
        return [
            {
                "id": r[0],
                "username": r[1],
                "email": r[2],
                "first_name": r[3],
                "last_name": r[4],
                "created_at": str(r[5]) if r[5] is not None else None,
            }
            for r in (rows or [])
        ]
    except Exception as exc:  # noqa: BLE001
        return [_err(exc)]


@mcp.tool()
def deploy_template(
    template_id: str, application_name: str, user_id: int
) -> Dict[str, Any]:
    """Deploy an application from a Deploy Template blueprint.

    Uses the shared ``TemplateDeployService`` so MCP deployments follow the
    exact same path as the Dashboard, CLI and REST API. An unknown template id
    returns ``{"error": "template not found", ...}`` and initiates NO deployment.
    """
    try:
        from src.template_catalog import TemplateCatalog
        from src.template_deploy import TemplateDeployService
        from src.orchestrator import orchestrator

        catalog = TemplateCatalog().load()
        if catalog.get(template_id) is None:
            return {"error": "template not found", "template_id": template_id}

        service = TemplateDeployService(catalog, orchestrator)
        result = service.deploy(template_id, application_name, user_id)

        if not result.success:
            return {
                "error": result.message or "deployment failed",
                "error_code": result.error_code,
                "template_id": template_id,
            }
        return {
            "application_id": result.application_id,
            "access_url": result.access_url,
            "template_id": template_id,
        }
    except Exception as exc:  # noqa: BLE001
        return _err(exc, kind="error")


@mcp.tool()
def agent_control_containers(
    live: bool = False,
    classification: Optional[str] = None,
    state: Optional[str] = None,
    min_confidence: float = 0.0,
) -> Dict[str, Any]:
    """Retrieve discovered containers and their agent-classification scores.

    Native-tool equivalent of ``GET /api/agent-control/containers`` used by the
    AGENTS_CONTROL watcher. Returns the stable envelope
    ``{"success", "containers": [...], "errors": [...]}`` where each container
    carries ``server_id, server_name, container_id, name, image, state,
    classification, confidence_score, classification_evidence``.

    Args:
        live: When True, run an on-demand scan across every managed server
            (adds per-server error indicators for unreachable hosts). When
            False (default), return the fast stored inventory from the DB.
        classification: Optional filter applied to the stored inventory
            ('probable_agent' or 'unclassified'). Ignored for live scans.
        state: Optional container-state filter applied to the stored inventory
            (e.g. 'running'). Ignored for live scans.
        min_confidence: Keep only containers whose ``confidence_score`` is
            greater than or equal to this threshold (0.0 keeps everything;
            0.7 mirrors the AGENTS_CONTROL alert threshold).
    """
    try:
        from src import agent_control_service as svc
        from src.runtime_monitor import runtime_monitor_repository as repo

        if live:
            from src.database_postgres import db_manager
            from src.runtime_monitor.runtime_collector import collect_server_containers
            from src.runtime_monitor.agent_classifier import classify

            rows = (
                db_manager.execute_query(
                    "SELECT id, server_ip, server_name FROM servers "
                    "WHERE server_status != 'DISABLED' ORDER BY id",
                    fetch_all=True,
                )
                or []
            )
            servers = [
                {"id": r[0], "server_ip": r[1], "server_name": r[2]} for r in rows
            ]
            payload = svc.scan_live(servers, collect_server_containers, classify)
        else:
            containers = repo.list_containers(
                classification=classification, state=state
            )
            payload = svc.build_payload(containers)

        if min_confidence and min_confidence > 0.0:
            payload = dict(payload)
            payload["containers"] = [
                c
                for c in payload.get("containers", [])
                if float(c.get("confidence_score") or 0.0) >= min_confidence
            ]
        return payload
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "containers": [], "errors": [], "error": f"{type(exc).__name__}: {exc}"}


@mcp.tool()
def start(application_name: str, user_id: int) -> Dict[str, Any]:
    """Start an application's runtime via the platform operator agent."""
    try:
        return _run_operator_action("START", application_name, user_id)
    except Exception as exc:  # noqa: BLE001 — R8.1: never raise across the protocol
        return _err(exc)


@mcp.tool()
def stop(application_name: str, user_id: int) -> Dict[str, Any]:
    """Stop an application's runtime via the platform operator agent."""
    try:
        return _run_operator_action("STOP", application_name, user_id)
    except Exception as exc:  # noqa: BLE001 — R8.1: never raise across the protocol
        return _err(exc)


@mcp.tool()
def ps(application_name: str, user_id: int) -> Dict[str, Any]:
    """List the running processes/containers for an application."""
    try:
        return _run_operator_action("PS", application_name, user_id)
    except Exception as exc:  # noqa: BLE001 — R8.1: never raise across the protocol
        return _err(exc)


@mcp.tool()
def logs(application_name: str, user_id: int) -> Dict[str, Any]:
    """Retrieve recent logs for an application."""
    try:
        return _run_operator_action("LOGS", application_name, user_id)
    except Exception as exc:  # noqa: BLE001 — R8.1: never raise across the protocol
        return _err(exc)


@mcp.tool()
def backup(application_name: str, user_id: int) -> Dict[str, Any]:
    """Back up an application's data via the BACKUP operator action."""
    try:
        return _run_operator_action("BACKUP", application_name, user_id)
    except Exception as exc:  # noqa: BLE001 — R8.1: never raise across the protocol
        return _err(exc)


@mcp.tool()
def restore(application_name: str, user_id: int) -> Dict[str, Any]:
    """Restore an application's database via the RESTORE_DATABASE operator action."""
    try:
        return _run_operator_action("RESTORE_DATABASE", application_name, user_id)
    except Exception as exc:  # noqa: BLE001 — R8.1: never raise across the protocol
        return _err(exc)


@mcp.tool()
def modify_code(application_name: str, user_id: int, instruction: str) -> Dict[str, Any]:
    """Modify an application's source code via the Developer agent path.

    On a clean engine exit, creates a Gitea branch name and records the change in
    the application's most recent deployment modification_history.
    """
    try:
        return _run_developer_action(application_name, user_id, instruction)
    except Exception as exc:  # noqa: BLE001 — R8.1: never raise across the protocol
        return _err(exc)


def main() -> None:
    """Run the MCP server over stdio (default transport for shai)."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()