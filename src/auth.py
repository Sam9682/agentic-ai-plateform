"""Authentication and SSO functionality"""
# import sqlite3  # COMMENTED OUT - Using PostgreSQL now
import secrets
import hashlib
import hmac
import os
from datetime import datetime, timedelta

# Determine database type based on environment - DEFAULT TO POSTGRESQL
USE_POSTGRES = os.environ.get('USE_POSTGRES', 'true').lower() == 'true'

# Use PostgreSQL by default
from .database_postgres import db_manager

# Environment variable holding the server-side SSO MAC key (R7.1). This key is a
# server-side secret used to compute a keyed MAC over the stored SSO token hash;
# it is never sent to clients.
_SSO_MAC_KEY_ENV = 'SSO_MAC_KEY'


def _get_sso_mac_key():
    """Return the server-side SSO MAC key as bytes, failing closed if unset.

    The key authenticates the stored Token_Hash so a hash tampered with directly
    in the database fails the MAC check on validation (R7.1).
    """
    key = os.environ.get(_SSO_MAC_KEY_ENV)
    if not key:
        raise RuntimeError(
            f"{_SSO_MAC_KEY_ENV} is not set; refusing to issue/verify SSO tokens"
        )
    return key.encode('utf-8')


def _compute_token_mac(token_hash):
    """Compute the keyed HMAC-SHA256 over the stored token hash (R7.1).

    ``token_hash`` is the hex-encoded SHA-256 of the clear token. The MAC is
    taken over that hash string (not the clear token), so the clear token is
    never required to verify integrity of the stored row.
    """
    return hmac.new(
        _get_sso_mac_key(), token_hash.encode('utf-8'), hashlib.sha256
    ).hexdigest()


# --------------------------------------------------------------------------- #
# Failure audit for SSO validation (R7.4).
# --------------------------------------------------------------------------- #
# On ANY failed SSO validation, emit a structured ``sso.validate.failed`` audit
# event. The event carries NO token value (not the clear token, not the hash) —
# only a non-secret ``reason`` identifier. The helper is module-level and
# injectable so tests can capture emitted events without a live DB, and imports
# are deferred so importing ``auth`` never opens a DB pool (mirrors the authz
# tenant-switch audit shim).
def _default_sso_validate_failed_audit(reason):
    """Emit an ``sso.validate.failed`` audit event. No token value (R7.4).

    The validation context has no resolved tenant (a failed validation never
    produced an authenticated user), so the event is keyed to tenant ``0`` with
    only a non-secret ``reason`` describing why validation failed. Routed
    through :func:`event_service.emit`, which additionally redacts the payload
    before persistence. Auditing is best-effort: a logging/DB hiccup must never
    turn a failed validation into a raised exception for the caller.
    """
    try:
        from .aro import event_service
        from .aro import events_repository as events_repo

        event_service.emit(
            events_repo,
            0,
            "sso.validate.failed",
            "sso",
            action={"reason": reason},
            decision="DENY",
            severity="MEDIUM",
        )
    except Exception:
        pass


# Injectable so tests can capture emitted events without a live DB.
sso_validate_failed_audit = _default_sso_validate_failed_audit


def generate_sso_token(user_id):
    """Generate a new SSO token for the user"""
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    token_mac = _compute_token_mac(token_hash)
    expires_at = datetime.now() + timedelta(weeks=1)
    
    with db_manager.get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Remove existing tokens for this user
        cursor.execute('DELETE FROM auth_tokens WHERE user_id = %s', (user_id,))
        
        # Insert new token with a keyed MAC over the stored hash (R7.1)
        cursor.execute('''
            INSERT INTO auth_tokens (user_id, token_hash, token_mac, expires_at)
            VALUES (%s, %s, %s, %s)
        ''', (user_id, token_hash, token_mac, expires_at))
        
        conn.commit()
    
    # Return the clear token exactly once; only the hash (and its MAC) are stored (R7.5)
    return token

def invalidate_sso_token(token):
    """Invalidate an SSO token"""
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    
    with db_manager.get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM auth_tokens WHERE token_hash = %s', (token_hash,))
        conn.commit()

def validate_sso_token(token):
    """Validate an SSO token and return user info.

    On ANY failed validation path (missing row, expired token, or a stored hash
    whose keyed MAC does not verify), a token-free ``sso.validate.failed`` audit
    event is emitted (R7.4) before returning ``None``. The event never carries
    the clear token or the token hash.
    """
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    
    # Preserve the SQL-level expiry predicate (R7.5). Fetch the stored MAC so we
    # can verify the integrity of the stored hash before accepting (R7.1).
    result = db_manager.execute_query('''
        SELECT u.id, u.username, u.email, u.first_name, u.last_name, t.expires_at, t.token_mac
        FROM auth_tokens t
        JOIN users u ON t.user_id = u.id
        WHERE t.token_hash = %s AND t.expires_at > NOW()
    ''', (token_hash,), fetch_one=True)
    
    if not result:
        # No matching, unexpired token row (R7.4 failure audit; no token value).
        sso_validate_failed_audit("no_matching_token")
        return None

    stored_mac = result[6]
    if stored_mac is not None:
        # Recompute the keyed MAC over the stored hash and verify in constant
        # time before accepting (R7.1). A hash tampered with in the DB will not
        # match the recomputed MAC and is rejected.
        expected_mac = _compute_token_mac(token_hash)
        if not hmac.compare_digest(str(stored_mac), expected_mac):
            # Integrity check failed (R7.4 failure audit; no token value).
            sso_validate_failed_audit("mac_mismatch")
            return None
    # else: pre-existing token with NULL token_mac is accepted during the grace
    # window (per design) and will carry a MAC on its next issuance.

    return {
        'id': result[0],
        'username': result[1],
        'email': result[2],
        'first_name': result[3],
        'last_name': result[4],
        'expires_at': result[5]
    }
