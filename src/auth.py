"""Authentication and SSO functionality"""
# import sqlite3  # COMMENTED OUT - Using PostgreSQL now
import secrets
import hashlib
import os
from datetime import datetime, timedelta

# Determine database type based on environment - DEFAULT TO POSTGRESQL
USE_POSTGRES = os.environ.get('USE_POSTGRES', 'true').lower() == 'true'

# Use PostgreSQL by default
from .database_postgres import db_manager

def generate_sso_token(user_id):
    """Generate a new SSO token for the user"""
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    expires_at = datetime.now() + timedelta(weeks=1)
    
    with db_manager.get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Remove existing tokens for this user
        cursor.execute('DELETE FROM auth_tokens WHERE user_id = %s', (user_id,))
        
        # Insert new token
        cursor.execute('''
            INSERT INTO auth_tokens (user_id, token_hash, expires_at)
            VALUES (%s, %s, %s)
        ''', (user_id, token_hash, expires_at))
        
        conn.commit()
    
    return token

def invalidate_sso_token(token):
    """Invalidate an SSO token"""
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    
    with db_manager.get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM auth_tokens WHERE token_hash = %s', (token_hash,))
        conn.commit()

def validate_sso_token(token):
    """Validate an SSO token and return user info"""
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    
    result = db_manager.execute_query('''
        SELECT u.id, u.username, u.email, u.first_name, u.last_name, t.expires_at
        FROM auth_tokens t
        JOIN users u ON t.user_id = u.id
        WHERE t.token_hash = %s AND t.expires_at > NOW()
    ''', (token_hash,), fetch_one=True)
    
    if result:
        return {
            'id': result[0],
            'username': result[1],
            'email': result[2],
            'first_name': result[3],
            'last_name': result[4],
            'expires_at': result[5]
        }
    return None