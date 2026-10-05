"""Security routes for password reset and two-factor authentication"""
import secrets
import hashlib
import random
import string
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, session, render_template, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash
import os
import logging

from ..database_postgres import db_manager
from ..email_service import send_password_reset_email, send_2fa_code_email

logger = logging.getLogger(__name__)

security_bp = Blueprint('security', __name__, url_prefix='/security')

# ============================================================
# PASSWORD RESET
# ============================================================

def _generate_reset_token(user_id):
    """Generate a password reset token and store its hash"""
    token = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    expires_at = datetime.now() + timedelta(hours=1)
    
    # Invalidate any existing tokens for this user
    db_manager.execute_query(
        'DELETE FROM password_reset_tokens WHERE user_id = %s',
        (user_id,)
    )
    
    # Store new token
    db_manager.execute_query('''
        INSERT INTO password_reset_tokens (user_id, token_hash, expires_at)
        VALUES (%s, %s, %s)
    ''', (user_id, token_hash, expires_at))
    
    return token


@security_bp.route('/password-reset/request', methods=['POST'])
def request_password_reset():
    """Request a password reset - admin can reset any user, user can reset their own"""
    data = request.get_json()
    
    if not data:
        return jsonify({'error': 'Invalid request'}), 400
    
    target_user_id = data.get('user_id')
    
    # Determine who is making the request
    if 'user_id' in session:
        # Logged-in user
        requesting_user = db_manager.execute_query(
            'SELECT id, username FROM users WHERE id = %s',
            (session['user_id'],), fetch_one=True
        )
        
        if not requesting_user:
            return jsonify({'error': 'Authentication required'}), 401
        
        is_admin = requesting_user[1] == 'admin'
        
        # If no target specified, reset own password
        if not target_user_id:
            target_user_id = session['user_id']
        
        # Non-admin can only reset their own password
        if not is_admin and target_user_id != session['user_id']:
            return jsonify({'error': 'You can only reset your own password'}), 403
    else:
        return jsonify({'error': 'Authentication required'}), 401
    
    # Get target user info
    target_user = db_manager.execute_query(
        'SELECT id, username, email FROM users WHERE id = %s',
        (target_user_id,), fetch_one=True
    )
    
    if not target_user:
        return jsonify({'error': 'User not found'}), 404
    
    user_id, username, email = target_user
    
    # Generate reset token
    token = _generate_reset_token(user_id)
    
    # Build reset URL
    from ..config_postgres import DOMAIN
    base_url = request.host_url.rstrip('/')
    reset_url = f"{base_url}/security/password-reset/{token}"
    
    # Send email
    email_sent = send_password_reset_email(email, username, reset_url)
    
    if email_sent:
        logger.info(f"Password reset email sent for user {username} (id={user_id})")
        return jsonify({
            'message': f'Password reset email sent to {email}',
            'email_sent': True
        }), 200
    else:
        # Even if email fails, return the token for admin use (in development)
        logger.warning(f"Failed to send password reset email for user {username}")
        return jsonify({
            'message': 'Password reset link generated but email delivery failed. Check SMTP configuration.',
            'email_sent': False,
            'reset_url': reset_url if is_admin else None
        }), 200


@security_bp.route('/password-reset/<token>', methods=['GET'])
def password_reset_page(token):
    """Show password reset form"""
    # Validate token
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    
    result = db_manager.execute_query('''
        SELECT prt.user_id, u.username, prt.expires_at, prt.used
        FROM password_reset_tokens prt
        JOIN users u ON prt.user_id = u.id
        WHERE prt.token_hash = %s
    ''', (token_hash,), fetch_one=True)
    
    if not result:
        return render_template('password_reset.html', error='Invalid reset link', token=None)
    
    user_id, username, expires_at, used = result
    
    if used:
        return render_template('password_reset.html', error='This reset link has already been used', token=None)
    
    if expires_at < datetime.now(expires_at.tzinfo) if expires_at.tzinfo else expires_at < datetime.now():
        return render_template('password_reset.html', error='This reset link has expired', token=None)
    
    return render_template('password_reset.html', token=token, username=username, error=None)


@security_bp.route('/password-reset/<token>', methods=['POST'])
def password_reset_submit(token):
    """Process password reset form submission"""
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    
    result = db_manager.execute_query('''
        SELECT prt.id, prt.user_id, prt.expires_at, prt.used
        FROM password_reset_tokens prt
        WHERE prt.token_hash = %s
    ''', (token_hash,), fetch_one=True)
    
    if not result:
        return render_template('password_reset.html', error='Invalid reset link', token=None)
    
    token_id, user_id, expires_at, used = result
    
    if used:
        return render_template('password_reset.html', error='This reset link has already been used', token=None)
    
    if expires_at < datetime.now(expires_at.tzinfo) if expires_at.tzinfo else expires_at < datetime.now():
        return render_template('password_reset.html', error='This reset link has expired', token=None)
    
    # Get new password from form
    data = request.form if request.form else request.get_json()
    new_password = data.get('new_password')
    confirm_password = data.get('confirm_password')
    
    if not new_password or not confirm_password:
        return render_template('password_reset.html', error='Both password fields are required', token=token)
    
    if new_password != confirm_password:
        return render_template('password_reset.html', error='Passwords do not match', token=token)
    
    if len(new_password) < 6:
        return render_template('password_reset.html', error='Password must be at least 6 characters', token=token)
    
    # Update password
    password_hash = generate_password_hash(new_password)
    db_manager.execute_query(
        'UPDATE users SET password_hash = %s WHERE id = %s',
        (password_hash, user_id)
    )
    
    # Mark token as used
    db_manager.execute_query(
        'UPDATE password_reset_tokens SET used = TRUE WHERE id = %s',
        (token_id,)
    )
    
    # Log the event
    user = db_manager.execute_query('SELECT username FROM users WHERE id = %s', (user_id,), fetch_one=True)
    if user:
        db_manager.execute_query(
            'INSERT INTO users_logs (user_id, username, action) VALUES (%s, %s, %s)',
            (user_id, user[0], 'password_reset')
        )
    
    logger.info(f"Password reset completed for user_id={user_id}")
    return render_template('password_reset.html', success=True, token=None, error=None)


@security_bp.route('/change-password', methods=['POST'])
def change_password():
    """Change password for logged-in user (requires current password)"""
    if 'user_id' not in session:
        return jsonify({'error': 'Authentication required'}), 401
    
    data = request.get_json()
    current_password = data.get('current_password')
    new_password = data.get('new_password')
    
    if not current_password or not new_password:
        return jsonify({'error': 'Current password and new password are required'}), 400
    
    if len(new_password) < 6:
        return jsonify({'error': 'New password must be at least 6 characters'}), 400
    
    # Verify current password
    user = db_manager.execute_query(
        'SELECT id, username, password_hash FROM users WHERE id = %s',
        (session['user_id'],), fetch_one=True
    )
    
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    if not check_password_hash(user[2], current_password):
        return jsonify({'error': 'Current password is incorrect'}), 401
    
    # Update password
    password_hash = generate_password_hash(new_password)
    db_manager.execute_query(
        'UPDATE users SET password_hash = %s WHERE id = %s',
        (password_hash, session['user_id'])
    )
    
    # Log the event
    db_manager.execute_query(
        'INSERT INTO users_logs (user_id, username, action) VALUES (%s, %s, %s)',
        (session['user_id'], user[1], 'password_changed')
    )
    
    return jsonify({'message': 'Password changed successfully'}), 200


# ============================================================
# TWO-FACTOR AUTHENTICATION (TOTP)
# ============================================================

@security_bp.route('/2fa/setup', methods=['POST'])
def setup_2fa():
    """Initialize 2FA setup - generate TOTP secret"""
    if 'user_id' not in session:
        return jsonify({'error': 'Authentication required'}), 401
    
    try:
        import pyotp
    except ImportError:
        return jsonify({'error': '2FA module not available. Install pyotp: pip install pyotp'}), 500
    
    user = db_manager.execute_query(
        'SELECT id, username, email, totp_enabled FROM users WHERE id = %s',
        (session['user_id'],), fetch_one=True
    )
    
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    user_id, username, email, totp_enabled = user
    
    # Generate new TOTP secret
    secret = pyotp.random_base32()
    
    # Store secret (not yet enabled)
    db_manager.execute_query(
        'UPDATE users SET totp_secret = %s WHERE id = %s',
        (secret, user_id)
    )
    
    # Generate provisioning URI for QR code
    from ..config_postgres import PLTF_NAME
    totp = pyotp.TOTP(secret)
    provisioning_uri = totp.provisioning_uri(
        name=username,
        issuer_name=PLTF_NAME
    )
    
    return jsonify({
        'secret': secret,
        'provisioning_uri': provisioning_uri,
        'message': 'Scan the QR code with your authenticator app, then verify with a code'
    }), 200


@security_bp.route('/2fa/verify-setup', methods=['POST'])
def verify_2fa_setup():
    """Verify TOTP code to complete 2FA setup"""
    if 'user_id' not in session:
        return jsonify({'error': 'Authentication required'}), 401
    
    try:
        import pyotp
    except ImportError:
        return jsonify({'error': '2FA module not available'}), 500
    
    data = request.get_json()
    code = data.get('code')
    
    if not code:
        return jsonify({'error': 'Verification code required'}), 400
    
    user = db_manager.execute_query(
        'SELECT id, username, totp_secret FROM users WHERE id = %s',
        (session['user_id'],), fetch_one=True
    )
    
    if not user or not user[2]:
        return jsonify({'error': 'No 2FA setup in progress'}), 400
    
    user_id, username, totp_secret = user
    
    # Verify the code
    totp = pyotp.TOTP(totp_secret)
    if not totp.verify(code, valid_window=1):
        return jsonify({'error': 'Invalid verification code'}), 400
    
    # Generate backup codes
    backup_codes = [secrets.token_hex(4) for _ in range(8)]
    backup_codes_str = ','.join(backup_codes)
    
    # Enable 2FA
    db_manager.execute_query(
        'UPDATE users SET totp_enabled = TRUE, totp_backup_codes = %s WHERE id = %s',
        (backup_codes_str, user_id)
    )
    
    # Log the event
    db_manager.execute_query(
        'INSERT INTO users_logs (user_id, username, action) VALUES (%s, %s, %s)',
        (user_id, username, '2fa_enabled_totp')
    )
    
    logger.info(f"2FA (TOTP) enabled for user {username}")
    
    return jsonify({
        'message': '2FA enabled successfully',
        'backup_codes': backup_codes
    }), 200


@security_bp.route('/2fa/disable', methods=['POST'])
def disable_2fa():
    """Disable 2FA for the current user or admin can disable for any user"""
    if 'user_id' not in session:
        return jsonify({'error': 'Authentication required'}), 401
    
    data = request.get_json()
    target_user_id = data.get('user_id', session['user_id'])
    
    # Check permissions
    requesting_user = db_manager.execute_query(
        'SELECT username FROM users WHERE id = %s',
        (session['user_id'],), fetch_one=True
    )
    
    is_admin = requesting_user and requesting_user[0] == 'admin'
    
    if target_user_id != session['user_id'] and not is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    
    # For non-admin, require password verification
    if not is_admin:
        password = data.get('password')
        if not password:
            return jsonify({'error': 'Password required to disable 2FA'}), 400
        
        user = db_manager.execute_query(
            'SELECT password_hash FROM users WHERE id = %s',
            (session['user_id'],), fetch_one=True
        )
        if not user or not check_password_hash(user[0], password):
            return jsonify({'error': 'Invalid password'}), 401
    
    # Disable 2FA
    db_manager.execute_query('''
        UPDATE users SET totp_enabled = FALSE, totp_secret = NULL, 
               totp_backup_codes = NULL, twofa_email_enabled = FALSE 
        WHERE id = %s
    ''', (target_user_id,))
    
    # Log the event
    target_user = db_manager.execute_query(
        'SELECT username FROM users WHERE id = %s',
        (target_user_id,), fetch_one=True
    )
    if target_user:
        db_manager.execute_query(
            'INSERT INTO users_logs (user_id, username, action) VALUES (%s, %s, %s)',
            (target_user_id, target_user[0], '2fa_disabled')
        )
    
    return jsonify({'message': '2FA disabled successfully'}), 200


@security_bp.route('/2fa/enable-email', methods=['POST'])
def enable_2fa_email():
    """Enable email-based 2FA"""
    if 'user_id' not in session:
        return jsonify({'error': 'Authentication required'}), 401
    
    user = db_manager.execute_query(
        'SELECT id, username, email FROM users WHERE id = %s',
        (session['user_id'],), fetch_one=True
    )
    
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    user_id, username, email = user
    
    # Enable email 2FA
    db_manager.execute_query(
        'UPDATE users SET twofa_email_enabled = TRUE WHERE id = %s',
        (user_id,)
    )
    
    # Log the event
    db_manager.execute_query(
        'INSERT INTO users_logs (user_id, username, action) VALUES (%s, %s, %s)',
        (user_id, username, '2fa_enabled_email')
    )
    
    return jsonify({
        'message': f'Email-based 2FA enabled. Codes will be sent to {email}'
    }), 200


@security_bp.route('/2fa/send-email-code', methods=['POST'])
def send_2fa_email_code():
    """Send a 2FA code via email (used during login)"""
    data = request.get_json()
    user_id = data.get('user_id') or session.get('pending_2fa_user_id')
    
    if not user_id:
        return jsonify({'error': 'User identification required'}), 400
    
    user = db_manager.execute_query(
        'SELECT id, username, email FROM users WHERE id = %s',
        (user_id,), fetch_one=True
    )
    
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    user_id, username, email = user
    
    # Generate 6-digit code
    code = ''.join(random.choices(string.digits, k=6))
    expires_at = datetime.now() + timedelta(minutes=5)
    
    # Invalidate previous codes
    db_manager.execute_query(
        'DELETE FROM twofa_email_codes WHERE user_id = %s',
        (user_id,)
    )
    
    # Store code
    db_manager.execute_query('''
        INSERT INTO twofa_email_codes (user_id, code, expires_at)
        VALUES (%s, %s, %s)
    ''', (user_id, code, expires_at))
    
    # Send email
    email_sent = send_2fa_code_email(email, username, code)
    
    if email_sent:
        return jsonify({'message': f'Verification code sent to {email}'}), 200
    else:
        return jsonify({'error': 'Failed to send verification code. Check SMTP configuration.'}), 500


@security_bp.route('/2fa/verify-login', methods=['POST'])
def verify_2fa_login():
    """Verify 2FA code during login"""
    data = request.get_json()
    code = data.get('code')
    method = data.get('method', 'totp')  # 'totp' or 'email'
    user_id = session.get('pending_2fa_user_id')
    
    if not user_id:
        return jsonify({'error': 'No pending 2FA verification'}), 400
    
    if not code:
        return jsonify({'error': 'Verification code required'}), 400
    
    user = db_manager.execute_query(
        'SELECT id, username, totp_secret, totp_backup_codes FROM users WHERE id = %s',
        (user_id,), fetch_one=True
    )
    
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    user_id, username, totp_secret, backup_codes_str = user
    verified = False
    
    if method == 'totp':
        try:
            import pyotp
            totp = pyotp.TOTP(totp_secret)
            if totp.verify(code, valid_window=1):
                verified = True
        except ImportError:
            return jsonify({'error': '2FA module not available'}), 500
        
        # Check backup codes if TOTP failed
        if not verified and backup_codes_str:
            backup_codes = backup_codes_str.split(',')
            if code in backup_codes:
                verified = True
                # Remove used backup code
                backup_codes.remove(code)
                db_manager.execute_query(
                    'UPDATE users SET totp_backup_codes = %s WHERE id = %s',
                    (','.join(backup_codes), user_id)
                )
    
    elif method == 'email':
        result = db_manager.execute_query('''
            SELECT id FROM twofa_email_codes 
            WHERE user_id = %s AND code = %s AND expires_at > NOW() AND used = FALSE
        ''', (user_id, code), fetch_one=True)
        
        if result:
            verified = True
            db_manager.execute_query(
                'UPDATE twofa_email_codes SET used = TRUE WHERE id = %s',
                (result[0],)
            )
    
    if verified:
        # Complete login
        from ..auth import generate_sso_token
        session['user_id'] = user_id
        session.pop('pending_2fa_user_id', None)
        
        token = generate_sso_token(user_id)
        session['sso_token'] = token
        
        # Log login event
        db_manager.execute_query(
            'INSERT INTO users_logs (user_id, username, action) VALUES (%s, %s, %s)',
            (user_id, username, 'login_2fa')
        )
        
        return jsonify({'message': 'Login successful', 'sso_token': token, 'redirect': '/dashboard'}), 200
    else:
        return jsonify({'error': 'Invalid verification code'}), 401


@security_bp.route('/2fa/status', methods=['GET'])
def get_2fa_status():
    """Get 2FA status for the current user"""
    if 'user_id' not in session:
        return jsonify({'error': 'Authentication required'}), 401
    
    user = db_manager.execute_query(
        'SELECT totp_enabled, twofa_email_enabled FROM users WHERE id = %s',
        (session['user_id'],), fetch_one=True
    )
    
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    return jsonify({
        'totp_enabled': bool(user[0]),
        'email_enabled': bool(user[1]),
        'any_enabled': bool(user[0]) or bool(user[1])
    }), 200


@security_bp.route('/2fa/admin-status/<int:user_id>', methods=['GET'])
def get_2fa_admin_status(user_id):
    """Get 2FA status for any user (admin only)"""
    if 'user_id' not in session:
        return jsonify({'error': 'Authentication required'}), 401
    
    # Check admin
    admin_check = db_manager.execute_query(
        'SELECT username FROM users WHERE id = %s',
        (session['user_id'],), fetch_one=True
    )
    if not admin_check or admin_check[0] != 'admin':
        return jsonify({'error': 'Admin access required'}), 403
    
    user = db_manager.execute_query(
        'SELECT totp_enabled, twofa_email_enabled FROM users WHERE id = %s',
        (user_id,), fetch_one=True
    )
    
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    return jsonify({
        'totp_enabled': bool(user[0]),
        'email_enabled': bool(user[1]),
        'any_enabled': bool(user[0]) or bool(user[1])
    }), 200
