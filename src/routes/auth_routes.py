"""Authentication routes"""
from flask import Blueprint, request, jsonify, render_template, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash
import os
from ..auth import generate_sso_token, invalidate_sso_token, validate_sso_token

# Use PostgreSQL by default
from ..database_postgres import db_manager
from ..config_postgres import DOMAIN, PLTF_NAME, APP_VERSION

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        data = request.get_json() if request.is_json else request.form
        
        username = data.get('username')
        email = data.get('email')
        password = data.get('password')
        first_name = data.get('first_name', '')
        last_name = data.get('last_name', '')
        
        if not all([username, email, password]):
            return jsonify({'error': 'Missing required fields'}), 400
        
        try:
            password_hash = generate_password_hash(password)
            db_manager.execute_query('''INSERT INTO users (username, email, password_hash, first_name, last_name, suspended)
                VALUES (%s, %s, %s, %s, %s, %s)
            ''', (username, email, password_hash, first_name, last_name, True))
            
            # Queue replication event
            from src.replication_manager import queue_replication_event
            queue_replication_event('users', 'INSERT', {
                'username': username, 'email': email, 'password_hash': password_hash,
                'first_name': first_name, 'last_name': last_name, 'suspended': True
            })
            
            if request.is_json:
                return jsonify({'message': 'User registered successfully'}), 201
            return redirect(url_for('main.index'))
            
        except Exception as e:
            if 'already exists' in str(e).lower() or 'unique' in str(e).lower():
                return jsonify({'error': 'Username or email already exists'}), 409
            return jsonify({'error': f'Database error: {str(e)}'}), 500
    
    return render_template('register.html', DOMAIN=DOMAIN, PLTF_NAME=PLTF_NAME, APP_VERSION=APP_VERSION)

@auth_bp.route('/login', methods=['POST'])
def login():
    from ..config_postgres import TRANSLATIONS
    
    data = request.get_json() if request.is_json else request.form
    username = data.get('username')
    password = data.get('password')
    
    if not all([username, password]):
        lang = session.get('language', 'en')
        error_msg = TRANSLATIONS.get(lang, {}).get('invalid_credentials', 'Missing credentials')
        return jsonify({'error': error_msg}), 400
    
    user = db_manager.execute_query(
        'SELECT id, password_hash, suspended, totp_enabled, twofa_email_enabled FROM users WHERE username = %s', 
        (username,), fetch_one=True
    )
    
    if not user:
        # User doesn't exist
        lang = session.get('language', 'en')
        error_msg = TRANSLATIONS.get(lang, {}).get('invalid_credentials', 'Invalid credentials')
        return jsonify({'error': error_msg}), 401
    
    # Check if password is correct
    if not check_password_hash(user[1], password):
        # Wrong password
        lang = session.get('language', 'en')
        error_msg = TRANSLATIONS.get(lang, {}).get('invalid_credentials', 'Invalid credentials')
        return jsonify({'error': error_msg}), 401
    
    # Check if user is suspended
    if user[2]:
        # User is suspended
        lang = session.get('language', 'en')
        error_msg = TRANSLATIONS.get(lang, {}).get('account_pending_activation', 
            'Your account is pending activation. Please wait for the administration team to activate your account and try again later.')
        return jsonify({'error': error_msg}), 403
    
    # Check if 2FA is enabled
    totp_enabled = user[3] if len(user) > 3 else False
    email_2fa_enabled = user[4] if len(user) > 4 else False
    
    if totp_enabled or email_2fa_enabled:
        # Store user_id in session for 2FA verification
        session['pending_2fa_user_id'] = user[0]
        session['pending_2fa_username'] = username
        
        # Determine available 2FA methods
        methods = []
        if totp_enabled:
            methods.append('totp')
        if email_2fa_enabled:
            methods.append('email')
        
        return jsonify({
            'requires_2fa': True,
            'methods': methods,
            'user_id': user[0],
            'message': 'Two-factor authentication required'
        }), 200
    
    # User exists, password is correct, not suspended, no 2FA - allow login
    session['user_id'] = user[0]
    
    # Generate SSO token
    token = generate_sso_token(user[0])
    session['sso_token'] = token
    
    # Log login event
    db_manager.execute_query(
        'INSERT INTO users_logs (user_id, username, action) VALUES (%s, %s, %s)',
        (user[0], username, 'login')
    )
    
    if request.is_json:
        return jsonify({'message': 'Login successful', 'sso_token': token}), 200
    return redirect(url_for('main.dashboard'))

@auth_bp.route('/logout')
def logout():
    # Log logout event
    if 'user_id' in session:
        user = db_manager.execute_query(
            'SELECT username FROM users WHERE id = %s',
            (session['user_id'],), fetch_one=True
        )
        if user:
            db_manager.execute_query(
                'INSERT INTO users_logs (user_id, username, action) VALUES (%s, %s, %s)',
                (session['user_id'], user[0], 'logout')
            )
    
    # Invalidate SSO token
    if 'sso_token' in session:
        invalidate_sso_token(session['sso_token'])
    
    session.pop('user_id', None)
    session.pop('sso_token', None)
    return redirect(url_for('main.index'))

@auth_bp.route('/auth/sso', methods=['POST'])
def auth_sso():
    """SSO authentication endpoint for external applications"""
    data = request.get_json()
    sso_token = data.get('sso_token') if data else None
    
    if not sso_token:
        return jsonify({'detail': 'SSO token required'}), 400
    
    user_info = validate_sso_token(sso_token)
    
    if user_info:
        # Return format expected by React AuthContext
        return jsonify({
            'access_token': sso_token,
            'user': {
                'id': user_info['id'],
                'email': user_info['email'],
                'username': user_info['username'],
                'first_name': user_info['first_name'],
                'last_name': user_info['last_name']
            }
        }), 200
    else:
        return jsonify({'detail': 'Invalid or expired SSO token'}), 401