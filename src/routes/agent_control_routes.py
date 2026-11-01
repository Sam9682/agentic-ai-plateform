"""Agent Control dashboard API (tooling-menu-agent-control, Req 4).

Exposes ``agent_control_bp``: the authenticated Control of Agents data feed
backed by :mod:`src.runtime_monitor`. ``GET /api/agent-control/containers``
returns the discovered-container inventory and classifications as JSON.

Two data paths feed the same serialization/aggregation logic in the
surface-agnostic :mod:`src.agent_control_service` (so the correctness properties
hold regardless of source):

- Default: the stored inventory from ``runtime_containers`` via
  ``runtime_monitor_repository.list_containers()`` -- fast, no SSH
  (Req 4.2, 4.4, 4.5, 4.7).
- ``?live=1``: an on-demand scan across every managed server using the
  collector + classifier, adding one per-server error indicator for each
  unreachable host (Req 4.6).

Authorization converges on the deny-by-default ``role_required("admin")``
decorator from :mod:`src.authz` (phase3-zaf-enforcement R6.1, R6.3, R6.4): it
returns 401 when unauthenticated and 403 for an authenticated non-admin before
the body runs, replacing the legacy magic ``username == 'admin'`` check. No
repository or collector call is made when the request is not authorized.
Messages resolve through a self-contained ``get_text()`` (EN/FR, English
fallback), mirroring ``sandbox_routes.py`` / ``templates_routes.py``.
"""

import logging

from flask import Blueprint, jsonify, request, session

from ..authz import role_required
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
@role_required("admin")
def list_containers():
    """Return discovered containers + classifications (Req 4.2, 4.4, 4.5, 4.7).

    Default: stored inventory from ``runtime_containers``. ``?live=1`` runs an
    on-demand scan across managed servers, adding per-server error indicators
    for unreachable hosts (Req 4.6).

    Authorization is enforced by the ``role_required("admin")`` decorator
    (phase3-zaf-enforcement R6.1, R6.3, R6.4): it returns 401 for an
    unauthenticated caller and 403 for an authenticated non-admin before this
    body runs, converging on the shared deny-by-default model and replacing the
    legacy magic ``username == 'admin'`` check.
    """
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

    # Requester identity. Authorization is enforced by the
    # ``role_required("admin")`` decorator above (R6.1, R6.3, R6.4): the caller
    # is guaranteed to hold the admin role in the resolved tenant, so the legacy
    # magic ``username == 'admin'`` check is removed and admin status derives
    # from the authz decision rather than an inline username comparison.
    viewer_id = session['user_id']
    is_admin = True

    # Owner index: deployments JOIN users (excluding failed/error rows). A DB
    # failure here fails safe to an EMPTY index rather than raising: every
    # container then derives as Unowned, so admins still see all rows and
    # non-admins see none -- never leaking another user's container (Req 5.1,
    # 5.2, 5.3).
    try:
        deployment_rows = db_manager.execute_query(
            "SELECT d.user_id, u.username, d.application_name, d.deployment_path "
            "FROM deployments d JOIN users u ON u.id = d.user_id "
            "WHERE d.status NOT IN ('failed', 'error')",
            fetch_all=True,
        ) or []
        index = svc.build_deployments_index(deployment_rows)
    except Exception as exc:  # fail safe: empty index (Req 5.1, 5.2, 5.3)
        logger.error('Failed to build deployments index: %s', exc)
        index = {"by_slug": {}, "by_path": {}}

    payload = svc.scan_live(
        servers, collect_server_containers, classify,
        owner_for=lambda c: svc.derive_owner(c, index),
    )

    # Admin sees everything unchanged (Unowned + infra, preserving errors).
    # Non-admin keeps only containers they own (Req 4.1, 4.2, 5.1, 5.2, 5.3).
    if not is_admin:
        payload['containers'] = [
            c for c in payload['containers']
            if c.get('owner') and c['owner'].get('user_id') == viewer_id
        ]
    return jsonify(payload), 200
