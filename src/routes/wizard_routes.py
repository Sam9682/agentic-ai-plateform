"""Guided Setup Wizard REST/JSON routes for the Onboarding Experience (Req 4, 5, 6).

Exposes the ``wizard_bp`` blueprint that drives the browser-based, step-by-step
Setup Wizard. The heavy lifting lives in reusable, Flask-independent components:

- :class:`~src.wizard.SetupWizard` — owns the ordered steps
  (``STEP_ORDER = ["domain", "email", "gitea_version", "ssl", "admin_user",
  "database"]``), the per-field validators, and the ``advance`` transition that
  persists collected values into the session and reports per-field errors while
  retaining prior values (Req 4.1, 4.2, 4.6, 4.8).
- :class:`~src.wizard.SslConfigurator` — the SSL step's automatic-generation and
  manual-upload sub-flows (Req 5.1, 5.2, 5.3, 5.4, 5.5, 5.6).
- :class:`~src.configuration_writer.ConfigurationWriter` — safe, atomic,
  backup-protected persistence of the collected values on final completion
  (Req 6.1).

Design notes:

- This is an *installer* flow: there may be no Admin_User yet, so the routes do
  NOT require a ``user_id`` session (unlike the other blueprints). The wizard
  state itself lives in ``flask.session`` under the wizard engine's own key.
- Every label/message is resolved through the self-contained ``get_text()``
  below (English default), following the pattern established in
  ``src/routes/templates_routes.py`` (Req 4.5). We deliberately do NOT import
  ``get_text`` from ``api_routes`` (it has a NameError bug there).
- Responses are JSON keyed for the frontend, consistent with the other
  blueprints; the frontend renders each ordered step from the returned
  ``step``/``values``/``errors`` payload.
"""

import logging

from flask import Blueprint, request, jsonify, session

from ..config_postgres import TRANSLATIONS
from ..wizard import SetupWizard, STEP_ORDER, SslConfigurator
from ..configuration_writer import ConfigurationWriter

logger = logging.getLogger(__name__)

wizard_bp = Blueprint('wizard', __name__, url_prefix='/api/wizard')


def get_language():
    """Return the session language, defaulting to English (Req 4.5)."""
    return session.get('language', 'en')


def get_text(key):
    """Resolve a message key for the active language with an English fallback.

    Follows the self-contained pattern from ``src/routes/templates_routes.py``:
    read the language from the session, look up the key in ``TRANSLATIONS`` for
    that language, and fall back to English (then to the key itself) so EN/FR is
    preserved with an English default (Req 4.5).
    """
    try:
        lang = get_language()
        return TRANSLATIONS.get(lang, {}).get(key, TRANSLATIONS['en'].get(key, key))
    except (KeyError, AttributeError, TypeError):
        return key


def _localize_errors(errors):
    """Best-effort localize a ``field -> message`` error map (Req 4.5).

    The wizard engine returns English messages keyed by field. We attempt to
    resolve a translation key of the form ``wizard_error_<field>``; when no such
    key exists ``get_text`` falls back to the engine's original message so the
    caller always receives a human-readable string.
    """
    localized = {}
    for field_name, message in (errors or {}).items():
        localized[field_name] = get_text(f"wizard_error_{field_name}") or message
        # get_text returns the key itself when unknown; prefer the engine text then.
        if localized[field_name] == f"wizard_error_{field_name}":
            localized[field_name] = message
    return localized


def _wizard():
    """Construct a :class:`SetupWizard` bound to the live Flask session."""
    return SetupWizard(session=session)


def _step_payload(wizard, *, step=None, errors=None, extra=None):
    """Build the standard JSON payload describing the wizard's current position.

    Includes the ordered step list, the step the wizard now sits on, the
    accumulated retained values (Req 4.2), any per-field errors (Req 4.6), and a
    completion flag (Req 4.8). ``extra`` merges additional keys (e.g. SSL job
    state) into the payload.
    """
    payload = {
        'steps': list(STEP_ORDER),
        'step': step if step is not None else wizard.current_step,
        'values': wizard.values,
        'errors': _localize_errors(errors) if errors else {},
        'complete': wizard.is_complete(),
    }
    if extra:
        payload.update(extra)
    return payload


@wizard_bp.route('/steps', methods=['GET'])
def get_steps():
    """Return the ordered step list for the wizard (Req 4.1)."""
    wizard = _wizard()
    return jsonify(_step_payload(wizard)), 200


@wizard_bp.route('/state', methods=['GET'])
def get_state():
    """Return the current wizard step, retained values, and completion state.

    Renders the current step server-side from session-held state (Req 4.2, 4.5).
    """
    wizard = _wizard()
    return jsonify(_step_payload(wizard)), 200


@wizard_bp.route('/step/<step>', methods=['POST'])
def submit_step(step):
    """Validate and advance a single wizard step server-side (Req 4.2, 4.6, 4.8).

    Body is the step's field inputs (JSON or form). Delegates to
    ``SetupWizard.advance``:

    - On invalid inputs: HTTP 400 with the same step re-rendered, per-field
      errors, and the retained (already-collected) values (Req 4.6).
    - On valid non-final step: HTTP 200 advancing to the next step with retained
      values (Req 4.2).
    - On valid final step (``database``): persist all collected values via
      ``ConfigurationWriter.write`` and signal completion (Req 4.8, 6.1).
    """
    if step not in STEP_ORDER:
        return jsonify({'error': get_text('wizard_unknown_step')}), 404

    wizard = _wizard()
    data = request.get_json(silent=True)
    if data is None:
        data = request.form.to_dict() if request.form else {}
    inputs = dict(data) if data else {}

    result = wizard.advance(step, inputs)

    if not result.ok:
        # Invalid: stay on the step, retain values, report each invalid field.
        return jsonify(_step_payload(
            wizard,
            step=result.next_step,
            errors=result.errors,
        )), 400

    is_final = result.next_step is None
    if is_final:
        # Final step completed with all values valid: persist safely (Req 4.8, 6.1).
        return _complete(wizard)

    # Valid non-final step: advance, retaining prior values (Req 4.2).
    return jsonify(_step_payload(wizard, step=result.next_step)), 200


def _complete(wizard):
    """Persist the accumulated wizard values and signal completion (Req 4.8, 6.1).

    Invokes ``ConfigurationWriter().write(wizard.values)``. On success returns
    HTTP 200 with a completion flag; on a backup/write failure returns the
    ``failure_type`` and message so the installer can act (Req 6.3, 6.4).
    """
    values = wizard.values
    try:
        result = ConfigurationWriter().write(values)
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Configuration write raised: %s", exc)
        return jsonify({
            'complete': False,
            'error': get_text('wizard_write_failed'),
            'failure_type': 'write',
            'message': str(exc),
        }), 500

    if result.success:
        logger.info("Setup wizard completed; configuration written (backup=%s)", result.backup_path)
        return jsonify(_step_payload(
            wizard,
            step='database',
            extra={
                'complete': True,
                'message': get_text('wizard_complete'),
                'backup_path': result.backup_path,
            },
        )), 200

    # Persistence failed: surface the failure type/message (Req 6.3, 6.4).
    logger.warning(
        "Setup wizard completion failed (%s): %s", result.failure_type, result.message
    )
    return jsonify({
        'complete': False,
        'error': get_text('wizard_write_failed'),
        'failure_type': result.failure_type,
        'message': result.message,
        'backup_path': result.backup_path,
    }), 500


@wizard_bp.route('/ssl/generate', methods=['POST'])
def ssl_generate():
    """Kick off automatic SSL certificate generation for the wizard (Req 5.1, 5.2).

    Uses the domain/email already collected in the wizard (falling back to the
    request body). Returns the SSL job status so the frontend can show progress
    and, on failure/timeout, offer retry-or-switch-to-upload (Req 5.6).
    """
    wizard = _wizard()
    values = wizard.values
    data = request.get_json(silent=True) or (request.form.to_dict() if request.form else {}) or {}

    domain = data.get('domain') or values.get('domain')
    email = data.get('email') or values.get('email') or values.get('admin_email')

    if not domain or not email:
        return jsonify({'error': get_text('wizard_ssl_missing_domain_email')}), 400

    job = SslConfigurator().generate(domain, email)
    return jsonify({
        'status': job.status,
        'in_progress': job.in_progress,
        'succeeded': job.succeeded,
        'can_retry': job.can_retry,
        'reason': job.reason,
        'domain': job.domain,
    }), 200 if job.succeeded else 202 if job.in_progress else 400


@wizard_bp.route('/ssl/upload', methods=['POST'])
def ssl_upload():
    """Validate an uploaded SSL certificate + key pair for the wizard (Req 5.3, 5.4, 5.5).

    Accepts the PEM certificate and private key from an uploaded file
    (``certificate``/``private_key`` file fields) or from a JSON body
    (``cert_pem``/``key_pem``). On any mismatch the previously configured
    certificate state is left unchanged (Req 5.4, 5.5).
    """
    wizard = _wizard()
    values = wizard.values

    cert_pem = None
    key_pem = None

    # File upload form (preferred for real certificate files).
    if request.files:
        cert_file = request.files.get('certificate') or request.files.get('cert')
        key_file = request.files.get('private_key') or request.files.get('key')
        if cert_file is not None:
            cert_pem = cert_file.read()
        if key_file is not None:
            key_pem = key_file.read()

    # JSON / form fallback.
    if cert_pem is None or key_pem is None:
        data = request.get_json(silent=True) or (request.form.to_dict() if request.form else {}) or {}
        cert_pem = cert_pem if cert_pem is not None else data.get('cert_pem') or data.get('certificate')
        key_pem = key_pem if key_pem is not None else data.get('key_pem') or data.get('private_key')

    domain = (request.form.get('domain') if request.form else None) or values.get('domain')
    if not domain:
        return jsonify({'error': get_text('wizard_ssl_missing_domain_email')}), 400

    result = SslConfigurator().upload(cert_pem, key_pem, domain)
    if result.accepted:
        return jsonify({
            'accepted': True,
            'reason': result.reason,
            'best_effort': result.best_effort,
        }), 200

    return jsonify({
        'accepted': False,
        'reason': result.reason,
        'best_effort': result.best_effort,
    }), 400


@wizard_bp.route('/reset', methods=['POST'])
def reset():
    """Clear all wizard state to start over (fresh install run)."""
    wizard = _wizard()
    wizard.reset()
    return jsonify(_step_payload(wizard)), 200
