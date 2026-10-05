"""Template Deploy REST API (Req 10).

Exposes the ``templates_bp`` blueprint that lets an authenticated API client
list the Deploy Template catalog and deploy a template through the single,
surface-agnostic :class:`~src.template_deploy.TemplateDeployService` shared by
every surface (Dashboard, CLI, MCP, REST).

Endpoints:

- ``GET  /api/templates``                     — list catalog entries (Req 10.1)
- ``POST /api/templates/<template_id>/deploy`` — deploy a template  (Req 10.2)

Auth follows the existing session pattern (``if 'user_id' not in session:
return 401``); the orchestrator is never invoked when unauthenticated
(Req 10.3, 8.2). Service outcomes are mapped to HTTP 400/404/409/502 using the
``status_code`` / ``error_code`` already produced by ``TemplateDeployService``
(Req 10.4, 10.5, 10.6, 10.7). Every message is resolved through ``get_text()``
so EN/FR is preserved with an English default (Req 8.5, 8.6).
"""

import logging

from flask import Blueprint, request, jsonify, session

from ..config_postgres import TRANSLATIONS
from ..template_catalog import TemplateCatalog
from ..template_deploy import (
    TemplateDeployService,
    ERROR_INVALID_NAME,
    ERROR_TEMPLATE_NOT_FOUND,
    ERROR_NAME_CONFLICT,
    ERROR_ORCHESTRATOR_FAILED,
)

logger = logging.getLogger(__name__)

templates_bp = Blueprint('templates', __name__, url_prefix='/api')


def get_language():
    """Return the session language, defaulting to English (Req 8.6)."""
    return session.get('language', 'en')


def get_text(key):
    """Resolve a message key for the active language with an English fallback.

    Follows the pattern from ``src/routes/api_routes.py``: read the language from
    the session, look up the key in ``TRANSLATIONS`` for that language, and fall
    back to English (then to the key itself) so EN/FR is preserved with an
    English default (Req 8.5, 8.6).
    """
    try:
        lang = get_language()
        return TRANSLATIONS.get(lang, {}).get(key, TRANSLATIONS['en'].get(key, key))
    except (KeyError, AttributeError, TypeError):
        return key

# Map a service error code to the localized message key used for the response.
_ERROR_MESSAGE_KEYS = {
    ERROR_INVALID_NAME: 'template_deploy_invalid_name',
    ERROR_TEMPLATE_NOT_FOUND: 'template_deploy_not_found',
    ERROR_NAME_CONFLICT: 'template_deploy_name_conflict',
    ERROR_ORCHESTRATOR_FAILED: 'template_deploy_failed',
}


@templates_bp.route('/templates', methods=['GET'])
def list_templates():
    """Return the validated catalog of Deploy Templates (Req 10.1).

    Each entry includes the identifier, application type, required ports, and
    resource hints. Returns an empty list when no valid templates exist. Auth is
    required (Req 10.3).
    """
    if 'user_id' not in session:
        return jsonify({'error': get_text('authentication_required')}), 401

    catalog = TemplateCatalog().load()
    entries = [
        {
            'identifier': entry.get('identifier'),
            'app_type': entry.get('app_type'),
            'ports': entry.get('ports'),
            'memory_mb': entry.get('memory_mb'),
            'cpu_cores': entry.get('cpu_cores'),
        }
        for entry in catalog.list()
    ]
    return jsonify({'templates': entries}), 200


@templates_bp.route('/templates/<template_id>/deploy', methods=['POST'])
def deploy_template(template_id):
    """Deploy ``template_id`` for the authenticated user (Req 10.2).

    Body: ``{"application_name": "..."}``. Delegates to
    ``TemplateDeployService.deploy`` and maps the outcome to
    200/400/404/409/502. The orchestrator is never invoked when unauthenticated
    (Req 10.3, 8.2) or when the guards reject the request before deployment.
    """
    if 'user_id' not in session:
        return jsonify({'error': get_text('authentication_required')}), 401

    user_id = session['user_id']
    data = request.get_json(silent=True) or request.form
    application_name = (data.get('application_name') if data else None)

    # Import the orchestrator singleton lazily, matching the existing route
    # pattern (see orchestrator_routes.py) and keeping module import light.
    from ..orchestrator import orchestrator

    catalog = TemplateCatalog().load()
    service = TemplateDeployService(catalog, orchestrator)

    result = service.deploy(template_id, application_name, user_id)

    if result.success:
        return jsonify({
            'application_id': result.application_id,
            'application_name': result.application_name,
            'access_url': result.access_url,
            'template_id': result.template_id,
            'ports': result.ports,
        }), 200

    message_key = _ERROR_MESSAGE_KEYS.get(result.error_code, 'template_deploy_failed')
    logger.info(
        "Template deploy rejected (user %s, template '%s'): %s",
        user_id, template_id, result.error_code,
    )
    return jsonify({'error': get_text(message_key)}), result.status_code
