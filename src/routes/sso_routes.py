"""SSO routes"""
from flask import Blueprint, request, jsonify, render_template, session, redirect, url_for
# import sqlite3  # COMMENTED OUT - Using PostgreSQL now
import os
from ..auth import generate_sso_token, validate_sso_token
from werkzeug.security import check_password_hash

# Determine database type based on environment
USE_POSTGRES = os.environ.get('USE_POSTGRES', 'false').lower() == 'true'

from ..database_postgres import db_manager

sso_bp = Blueprint('sso', __name__, url_prefix='/sso')

@sso_bp.route('/validate', methods=['POST'])
def sso_validate():
    """SSO endpoint for applications to validate tokens"""
    # Log validation request
    remote_ip = request.environ.get('HTTP_X_FORWARDED_FOR', request.remote_addr)
    user_agent = request.headers.get('User-Agent', 'Unknown')
    
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
    
    # Build comprehensive SSO parameters
    params = {
        'sso_token': sso_token,
        'token': sso_token,
        'access_token': sso_token,
        'id_token': sso_token,
        'user': user[0] if user else '',
        'scope': 'read write',
        'state': 'success',
        'code': sso_token[:16]  # Short code version
    }
    
    # Build URL with all parameters
    param_string = '&'.join([f"{k}={v}" for k, v in params.items()])
    redirect_url = f"{app_url}?{param_string}"
    
    return redirect(redirect_url)

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
    
    # If user is already authenticated, redirect back with token
    if 'user_id' in session and 'sso_token' in session:
        return redirect(f"{redirect_uri}?token={session['sso_token']}&state=success")
    
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
    
    # Redirect back to client with token
    return redirect(f"{redirect_uri}?token={token}&state=success")