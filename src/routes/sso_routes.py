"""SSO routes"""
from flask import (
    Blueprint,
    request,
    jsonify,
    render_template,
    render_template_string,
    session,
    redirect,
    url_for,
)
from markupsafe import escape
# import sqlite3  # COMMENTED OUT - Using PostgreSQL now
import os
from ..auth import generate_sso_token, validate_sso_token
from ..zaf.mcp_gateway import RateLimiter
from werkzeug.security import check_password_hash

# Determine database type based on environment
USE_POSTGRES = os.environ.get('USE_POSTGRES', 'false').lower() == 'true'

from ..database_postgres import db_manager

sso_bp = Blueprint('sso', __name__, url_prefix='/sso')

# Per-source sliding-window limiter for SSO validation (R7.3). We reuse the same
# RateLimiter used by the MCP gateway so the sliding-window behavior is shared
# and well tested. The limiter is keyed by the request source (remote IP) so an
# abusive source cannot drown out legitimate validators. Excess requests inside
# the window are rejected with HTTP 429. The per-source limit is configurable
# via SSO_VALIDATE_RATE_PER_MINUTE (default 60/min).
_sso_validate_rate = RateLimiter()


def _sso_validate_limit():
    try:
        return max(1, int(os.environ.get('SSO_VALIDATE_RATE_PER_MINUTE', '60')))
    except (TypeError, ValueError):
        return 60


# Auto-submitting POST form template (R7.2). The SSO token is carried in the
# POST body rather than in a redirect query string, so it never appears in a
# URL, browser history, Referer header, or server access log. The form posts
# itself on load; a manual "Continue" button is provided as a no-JS fallback.
# All interpolated values are HTML-escaped at the call site via markupsafe.
_SSO_POST_FORM_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Signing you in...</title>
</head>
<body onload="document.forms[0].submit()">
<noscript><p>JavaScript is disabled. Click the button to continue.</p></noscript>
<form method="POST" action="{action}">
{fields}
<button type="submit">Continue</button>
</form>
</body>
</html>"""


# Token-bearing field names that MUST NOT appear in any redirect query string
# (R7.2). These are transmitted via the auto-submitting POST form body instead.
_SSO_TOKEN_FIELDS = ('sso_token', 'token', 'access_token', 'id_token', 'code')


def _render_sso_post_form(action_url, fields):
    """Render an auto-submitting POST form that transmits SSO fields in the body.

    ``action_url`` is the client callback URL (no token in its query string).
    ``fields`` is an ordered mapping of form field name -> value; every name and
    value is HTML-escaped so neither the token nor any attacker-influenced value
    can break out of the attribute context (R7.2).
    """
    hidden_inputs = []
    for name, value in fields.items():
        if value is None:
            continue
        hidden_inputs.append(
            f'<input type="hidden" name="{escape(str(name))}" '
            f'value="{escape(str(value))}">'
        )
    html = _SSO_POST_FORM_TEMPLATE.format(
        action=escape(action_url),
        fields="\n".join(hidden_inputs),
    )
    return render_template_string(html)


@sso_bp.route('/validate', methods=['POST'])
def sso_validate():
    """SSO endpoint for applications to validate tokens"""
    # Log validation request
    remote_ip = request.environ.get('HTTP_X_FORWARDED_FOR', request.remote_addr)
    user_agent = request.headers.get('User-Agent', 'Unknown')

    # Per-source sliding-window rate limit (R7.3). Enforced before any token
    # work so a flood of validation attempts from one source is shed with 429.
    rate_key = (remote_ip or 'unknown', 'sso.validate')
    if not _sso_validate_rate.allow(rate_key, _sso_validate_limit()):
        print(f"[SSO VALIDATE] RATE LIMITED - {remote_ip}")
        return jsonify({'error': 'rate limit exceeded'}), 429

    data = request.get_json()
    token = data.get('token') if data else None
    
    print(f"[SSO VALIDATE] IP: {remote_ip}, User-Agent: {user_agent}, Token: {'Present' if token else 'Missing'}")
    
    if not token:
        print(f"[SSO VALIDATE] FAILED - No token provided from {remote_ip}")
        return jsonify({'error': 'Token required'}), 400
    
    user_info = validate_sso_token(token)
    
    if user_info:
        print(f"[SSO VALIDATE] SUCCESS - User: {user_info['username']} from {remote_ip}")
        return jsonify({
            'valid': True,
            'user': user_info
        }), 200
    else:
        print(f"[SSO VALIDATE] FAILED - Invalid token from {remote_ip}")
        return jsonify({'valid': False}), 401

@sso_bp.route('/app/<app_name>')
def sso_app_login(app_name):
    """SSO login endpoint that redirects to application with token"""
    if 'user_id' not in session or 'sso_token' not in session:
        return redirect(url_for('main.index'))
    
    # Get application URL and user info
    app = db_manager.execute_query(
        'SELECT url FROM applications WHERE name = ?', 
        (app_name,), fetch_one=True
    )
    
    user = db_manager.execute_query(
        'SELECT username, email, first_name, last_name FROM users WHERE id = ?', 
        (session['user_id'],), fetch_one=True
    )
    
    if not app:
        return jsonify({'error': 'Application not found'}), 404
    
    app_url = app[0]
    sso_token = session['sso_token']

    # Transmit all SSO parameters via an auto-submitting POST form (R7.2).
    # None of the token-bearing fields (sso_token/token/access_token/id_token/
    # code) are placed in the callback URL's query string; the non-token fields
    # (user/scope/state) ride in the same POST body so the callback still
    # receives the full context it expects.
    fields = {
        'sso_token': sso_token,
        'token': sso_token,
        'access_token': sso_token,
        'id_token': sso_token,
        'user': user[0] if user else '',
        'scope': 'read write',
        'state': 'success',
        'code': sso_token[:16],  # Short code version
    }

    return _render_sso_post_form(app_url, fields)

@sso_bp.route('/auth')
def sso_auth():
    """SSO authentication endpoint - redirects to login if not authenticated"""
    redirect_uri = request.args.get('redirect_uri')
    client_id = request.args.get('client_id', 'ai-haccp')
    
    if not redirect_uri:
        return jsonify({'error': 'redirect_uri parameter required'}), 400
    
    # Store SSO request in session
    session['sso_redirect_uri'] = redirect_uri
    session['sso_client_id'] = client_id
    
    # If user is already authenticated, hand the token back to the client via
    # an auto-submitting POST form instead of a query-string redirect (R7.2).
    if 'user_id' in session and 'sso_token' in session:
        return _render_sso_post_form(
            redirect_uri,
            {'token': session['sso_token'], 'state': 'success'},
        )

    # Otherwise redirect to login page
    return redirect(url_for('sso.sso_login_page'))

@sso_bp.route('/login')
def sso_login_page():
    """SSO login page"""
    redirect_uri = session.get('sso_redirect_uri')
    if not redirect_uri:
        return redirect(url_for('main.index'))
    
    return render_template('sso_login.html', redirect_uri=redirect_uri)

@sso_bp.route('/authenticate', methods=['POST'])
def sso_authenticate():
    """SSO authentication handler"""
    from ..config_postgres import TRANSLATIONS
    
    username = request.form.get('username')
    password = request.form.get('password')
    redirect_uri = session.get('sso_redirect_uri')
    lang = session.get('language', 'en')
    
    if not all([username, password, redirect_uri]):
        error_msg = TRANSLATIONS.get(lang, {}).get('invalid_credentials', 'Missing credentials')
        return render_template('sso_login.html', 
                             error=error_msg, 
                             redirect_uri=redirect_uri)
    
    # Authenticate user
    user = db_manager.execute_query(
        'SELECT id, password_hash, suspended FROM users WHERE username = ?', 
        (username,), fetch_one=True
    )
    
    if not user:
        # User doesn't exist
        error_msg = TRANSLATIONS.get(lang, {}).get('invalid_credentials', 'Invalid credentials')
        return render_template('sso_login.html', 
                             error=error_msg, 
                             redirect_uri=redirect_uri)
    
    # Check if password is correct
    if not check_password_hash(user[1], password):
        # Wrong password
        error_msg = TRANSLATIONS.get(lang, {}).get('invalid_credentials', 'Invalid credentials')
        return render_template('sso_login.html', 
                             error=error_msg, 
                             redirect_uri=redirect_uri)
    
    # Check if user is suspended
    if user[2]:
        # User is suspended
        error_msg = TRANSLATIONS.get(lang, {}).get('account_pending_activation', 
            'Your account is pending activation. Please wait for the administration team to activate your account and try again later.')
        return render_template('sso_login.html', 
                             error=error_msg, 
                             redirect_uri=redirect_uri)
    
    # User exists, password is correct, and not suspended - allow login
    # Generate SSO token
    session['user_id'] = user[0]
    token = generate_sso_token(user[0])
    session['sso_token'] = token
    
    # Clear SSO session data
    session.pop('sso_redirect_uri', None)
    session.pop('sso_client_id', None)

    # Hand the token back to the client via an auto-submitting POST form so the
    # token never appears in the redirect query string (R7.2).
    return _render_sso_post_form(
        redirect_uri,
        {'token': token, 'state': 'success'},
    )