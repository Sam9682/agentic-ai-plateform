"""Sandbox / Demo Mode dashboard API (Req 1, 2, 3).

Exposes the ``sandbox_bp`` blueprint that lets an authenticated operator
provision, reset, and tear down the sandbox demo environment from the Dashboard,
and poll its current state so the UI can render progress (Req 1.6, 2.1, 2.2, 3.3).

All work is delegated to the surface-agnostic
:class:`~src.sandbox_manager.SandboxManager`, which is also driven by the CLI and
MCP surfaces, so the Dashboard performs exactly the same provisioning steps as
the Sandbox_Command (Req 1.6).

Endpoints (JSON API, consistent with ``templates_routes.py`` /
``wizard_routes.py``):

- ``POST /api/sandbox/provision`` — provision the sandbox (Req 1.6)
- ``POST /api/sandbox/reset``     — reset to the predefined baseline (Req 2.1)
- ``POST /api/sandbox/teardown``  — remove all demo resources (Req 2.2)
- ``GET  /api/sandbox/status``    — current sandbox apps + per-app status/URL
  used for progress polling (Req 1.6, 3.3)

Progress polling contract (Req 1.6): the provision / reset / teardown actions run
synchronously and return their final report; the frontend polls
``GET /api/sandbox/status`` at intervals no longer than 5 seconds to reflect the
current state of each sandbox Sample_Application. This synchronous action + status
endpoint pairing satisfies the "update progress at intervals no longer than 5
seconds" requirement at this layer without a background job system.

Auth follows the existing session pattern (``if 'user_id' not in session:
return 401``); no sandbox action is performed when unauthenticated (Req 8.2
style). Every message is resolved through ``get_text()`` so EN/FR is preserved
with an English default (Req 8.5, 8.6).
"""

import logging

from flask import Blueprint, jsonify, session

from ..config_postgres import TRANSLATIONS
from ..sandbox_manager import (
    SandboxManager,
    SANDBOX_ACCOUNT_TYPE,
    ERROR_SANDBOX_EXISTS,
    ERROR_SEED_FAILED,
)

logger = logging.getLogger(__name__)

sandbox_bp = Blueprint('sandbox', __name__, url_prefix='/api')

# Recommended maximum polling interval (seconds) for the status endpoint; the
# frontend SHOULD poll no less frequently than this so provisioning progress is
# reflected within the required window (Req 1.6).
STATUS_POLL_INTERVAL_SECONDS = 5


def get_language():
    """Return the session language, defaulting to English (Req 8.6)."""
    return session.get('language', 'en')


def get_text(key):
    """Resolve a message key for the active language with an English fallback.

    Self-contained helper mirroring the pattern in ``templates_routes.py`` /
    ``wizard_routes.py`` (reads the language from the session, looks the key up in
    ``TRANSLATIONS`` for that language, falls back to English, then to the key
    itself) so EN/FR is preserved with an English default (Req 8.5, 8.6). This
    intentionally does NOT import ``get_text`` from ``api_routes`` (which has a
    NameError bug).
    """
    try:
        lang = get_language()
        return TRANSLATIONS.get(lang, {}).get(key, TRANSLATIONS['en'].get(key, key))
    except (KeyError, AttributeError, TypeError):
        return key


# Map a sandbox error code to (localized message key, HTTP status).
_ERROR_STATUS = {
    ERROR_SANDBOX_EXISTS: ('sandbox_already_exists', 409),
    ERROR_SEED_FAILED: ('sandbox_seed_failed', 500),
}


def _build_manager():
    """Construct a :class:`SandboxManager` bound to the orchestrator singleton.

    The orchestrator is imported lazily to keep module import light and to match
    the existing route pattern (see ``templates_routes.py``).
    """
    from ..orchestrator import orchestrator
    return SandboxManager(orchestrator=orchestrator)


def _report_payload(report):
    """Serialize a :class:`~src.sandbox_manager.SandboxReport` for a JSON response."""
    return {
        'success': report.success,
        'message': report.message,
        'error_code': report.error_code,
        'credentials': report.credentials,
        'apps': report.apps,
        'failed': report.failed,
    }


@sandbox_bp.route('/sandbox/provision', methods=['POST'])
def provision_sandbox():
    """Provision the sandbox demo environment (Req 1.6).

    Performs the same steps as the Sandbox_Command and returns the Demo_User
    credentials plus one access URL per seeded Sample_Application on success. When
    a sandbox already exists the action changes nothing and maps to 409; other
    seeding failures map to 500 (Req 1.4, 1.5). Auth is required (Req 8.2).
    """
    if 'user_id' not in session:
        return jsonify({'error': get_text('authentication_required')}), 401

    manager = _build_manager()
    report = manager.provision()

    if report.success:
        return jsonify(_report_payload(report)), 200

    message_key, status = _ERROR_STATUS.get(
        report.error_code, ('sandbox_seed_failed', 500)
    )
    logger.info("Sandbox provision failed: %s", report.error_code)
    payload = _report_payload(report)
    payload['error'] = get_text(message_key)
    return jsonify(payload), status


@sandbox_bp.route('/sandbox/reset', methods=['POST'])
def reset_sandbox():
    """Reset the sandbox to its predefined seed baseline (Req 2.1).

    Stops and removes all sandbox-labeled Sample_Applications then re-seeds the
    baseline. If no sandbox exists an informational message is returned. Per-app
    removal failures are reported in ``failed`` (Req 2.5, 2.6). Auth is required.
    """
    if 'user_id' not in session:
        return jsonify({'error': get_text('authentication_required')}), 401

    manager = _build_manager()
    report = manager.reset()

    # reset() reports partial failures via report.failed while still succeeding
    # overall; surface a 200 with the report so the UI can render the outcome.
    return jsonify(_report_payload(report)), 200


@sandbox_bp.route('/sandbox/teardown', methods=['POST'])
def teardown_sandbox():
    """Tear down the sandbox and remove all demo resources (Req 2.2).

    Stops all apps, removes all apps, removes the Demo_User, and removes
    sandbox-specific database records, in order. If no sandbox exists an
    informational message is returned (Req 2.5). Per-app removal failures are
    reported in ``failed`` (Req 2.6). Auth is required.
    """
    if 'user_id' not in session:
        return jsonify({'error': get_text('authentication_required')}), 401

    manager = _build_manager()
    report = manager.teardown()

    return jsonify(_report_payload(report)), 200


@sandbox_bp.route('/sandbox/status', methods=['GET'])
def sandbox_status():
    """Return the current sandbox state for progress polling (Req 1.6, 3.3).

    Because provision / reset / teardown run synchronously, this endpoint reports
    the latest known state: whether a sandbox exists and, for each seeded
    Sample_Application, a deployment status in {running, stopped, failed} and its
    access URL (Req 3.3). The frontend SHOULD poll this endpoint at intervals no
    longer than :data:`STATUS_POLL_INTERVAL_SECONDS` seconds while an action is in
    progress (Req 1.6). Auth is required.
    """
    if 'user_id' not in session:
        return jsonify({'error': get_text('authentication_required')}), 401

    manager = _build_manager()

    exists = manager._sandbox_exists()
    apps = []
    if exists:
        user_id = manager._get_sandbox_user_id()
        for app in manager._list_sandbox_apps(user_id):
            apps.append({
                'application_id': app.get('application_id'),
                'application_name': app.get('application_name'),
                'status': _normalize_status(app.get('status')),
                'access_url': app.get('access_url'),
            })

    return jsonify({
        'exists': exists,
        'account_type': SANDBOX_ACCOUNT_TYPE if exists else None,
        'apps': apps,
        'poll_interval_seconds': STATUS_POLL_INTERVAL_SECONDS,
    }), 200


# Allowed per-app deployment statuses surfaced to the Dashboard (Req 3.3).
_ALLOWED_STATUSES = {'running', 'stopped', 'failed'}


def _normalize_status(status):
    """Coerce a deployment status into the {running, stopped, failed} set (Req 3.3).

    Sandbox-seeded apps start "running"; anything not in the allowed set is
    reported as "failed" so the payload always carries a valid status value.
    """
    if status in _ALLOWED_STATUSES:
        return status
    return 'failed'
