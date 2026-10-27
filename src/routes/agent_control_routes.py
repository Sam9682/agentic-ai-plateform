"""Agent Control dashboard API (tooling-menu-agent-control, Req 4).

Exposes ``agent_control_bp``: the authenticated Control of Agents data feed
backed by :mod:`src.runtime_monitor`. ``GET /api/agent-control/containers``
returns the discovered-container inventory and classifications as JSON.

Two data paths feed the same serialization/aggregation logic in the
surface-agnostic :mod:`src.agent_control_service` (so the correctness properties
hold regardless of source):

- Default: the stored inventory from ``runtime_containers`` via
  ``runtime_monitor_repository.list_containers()`` — fast, no SSH
  (Req 4.2, 4.4, 4.5, 4.7).
- ``?live=1``: an on-demand scan across every managed server using the
  collector + classifier, adding one per-server error indicator for each
  unreachable host (Req 4.6).

Auth follows the session pattern used across routes (``if 'user_id' not in
session: return 401``); no repository or collector call is made when
unauthenticated (Req 4.3). Messages resolve through a self-contained
``get_text()`` (EN/FR, English fallback), mirroring ``sandbox_routes.py`` /
``templates_routes.py``.
"""

import logging

from flask import Blueprint, jsonify, request, session

from ..config_postgres import TRANSLATIONS
from .. import agent_control_service as svc
from ..runtime_monitor import runtime_monitor_repository as repo

logger = logging.getLogger(__name__)

agent_control_bp = Blueprint('agent_control', __name__, url_prefix='/api')


def get_language():
    """Return the session language, defaulting to English."""
    return session.get('language', 'en')


def get_text(key):
    """Resolve a message key for the active language with an English fallback.

    Self-contained helper mirroring the pattern in ``sandbox_routes.py`` /
    ``templates_routes.py`` (reads the language from the session, looks the key
    up in ``TRANSLATIONS`` for that language, falls back to English, then to the
    key itself) so EN/FR is preserved with an English default.
    """
    try:
        lang = get_language()
        return TRANSLATIONS.get(lang, {}).get(key, TRANSLATIONS['en'].get(key, key))
    except (KeyError, AttributeError, TypeError):
        return key


@agent_control_bp.route('/agent-control/containers', methods=['GET'])
def list_containers():
    """Return discovered containers + classifications (Req 4.2, 4.4, 4.5, 4.7).

    Default: stored inventory from ``runtime_containers``. ``?live=1`` runs an
    on-demand scan across managed servers, adding per-server error indicators
    for unreachable hosts (Req 4.6). Auth required (Req 4.3): when there is no
    authenticated session we return 401 without touching the repository or the
    collector.
    """
    if 'user_id' not in session:
        return jsonify({'error': get_text('authentication_required')}), 401

    live = request.args.get('live') in ('1', 'true', 'yes')
    if not live:
        return jsonify(svc.list_stored(repo)), 200

    # Live scan: lazy imports keep module load light (route-pattern convention).
    from ..database_postgres import db_manager
    from ..runtime_monitor.runtime_collector import collect_server_containers
    from ..runtime_monitor.agent_classifier import classify

    rows = db_manager.execute_query(
        "SELECT id, server_ip, server_name FROM servers "
        "WHERE server_status != 'DISABLED' ORDER BY id",
        fetch_all=True,
    ) or []
    servers = [
        {'id': r[0], 'server_ip': r[1], 'server_name': r[2]} for r in rows
    ]
    payload = svc.scan_live(servers, collect_server_containers, classify)
    return jsonify(payload), 200
