"""API routes"""
from flask import Blueprint, request, jsonify, session, Response, stream_with_context
from werkzeug.security import generate_password_hash
# import sqlite3  # COMMENTED OUT - Using PostgreSQL now
import os
import requests
import json
import subprocess
import shutil
import socket
import logging
from datetime import datetime
from .. import config_postgres
from ..config_postgres import DOMAIN, TIMEOUT_GITEA_HTTP_POST, TIMEOUT_SUBPROCESS_RUN, LINUX_USER_INSTALLATION, ssh_target, chown_arg, deployments_prefix, is_under_deployments

# Configure logging for API activities
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Remove existing handlers to avoid duplicates
if logger.handlers:
    logger.handlers.clear()

# Get the project root directory dynamically
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

log_file = os.path.join(PROJECT_ROOT, 'logs', 'api_routes.log')
os.makedirs(os.path.dirname(log_file), exist_ok=True)

file_handler = logging.FileHandler(log_file)
file_handler.setLevel(logging.INFO)
file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(file_formatter)
logger.addHandler(file_handler)

# Console handler
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(file_formatter)
logger.addHandler(console_handler)

# Prevent propagation to avoid duplicate logs
logger.propagate = False

def get_language():
    return session.get('language', 'en')

def get_text(key):
    try:
        lang = get_language()
        return TRANSLATIONS.get(lang, {}).get(key, TRANSLATIONS['en'].get(key, key))
    except (KeyError, AttributeError, TypeError):
        return key

# Determine database type based on environment - DEFAULT TO POSTGRESQL
USE_POSTGRES = os.environ.get('USE_POSTGRES', 'true').lower() == 'true'

# Use PostgreSQL by default
try:
    from src.database_postgres import db_manager as pg_db_manager, init_db as pg_init_db, get_runtime_type
    db_manager = pg_db_manager
    init_db = pg_init_db
    print("Using PostgreSQL database")
except Exception as e:
    print(f"Failed to initialize PostgreSQL: {e}")
    raise RuntimeError("PostgreSQL database is required but failed to initialize")

api_bp = Blueprint('api', __name__, url_prefix='/api')

from ..db_health import check_database_health, get_database_stats
from ..nginx_manager import insert_location_block, remove_location_block, sync_all_locations
from ..platform_discovery import get_current_server_ip, check_remote_platform, determine_role, update_server_role

def create_gitea_user(username, email, password, first_name='', last_name=''):
    """Create user in Gitea server"""
    try:
        # Gitea API endpoint
        gitea_url = 'http://localhost:3000/api/v1/admin/users'
        
        # Get admin token for Gitea API
        admin_token = get_gitea_admin_token()
        
        if not admin_token:
            logger.warning(f"[GITEA] Failed to get admin token for user creation: {username}")
            return False
        
        # User data for Gitea
        full_name = ''
        if first_name or last_name:
            full_name = f"{first_name} {last_name}".strip()
        
        user_data = {
            'username': username,
            'email': email,
            'password': password,
            'full_name': full_name,
            'must_change_password': False,
            'send_notify': False
        }
        
        headers = {
            'Authorization': f'token {admin_token}',
            'Content-Type': 'application/json'
        }
        
        response = requests.post(gitea_url, json=user_data, headers=headers, timeout=TIMEOUT_GITEA_HTTP_POST)
        
        if response.status_code == 201:
            logger.info(f"[GITEA] User {username} created successfully")
            return True
        else:
            logger.error(f"[GITEA] Failed to create user {username}: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"[GITEA] Error creating user {username}: {str(e)}")
        return False

def get_gitea_admin_token():
    """Get or create admin token for Gitea API access"""
    try:
        # Try to get existing token from file
        token_file = '/tmp/gitea_admin_token'
        if os.path.exists(token_file):
            try:
                with open(token_file, 'r') as f:
                    return f.read().strip()
            except (IOError, OSError) as e:
                logger.error(f"[GITEA] Error reading token file: {str(e)}")
                return None
        
        # If no token file, return None (manual setup required)
        logger.info("[GITEA] No admin token found. Manual Gitea setup required.")
        return None
        
    except Exception as e:
        logger.error(f"[GITEA] Error getting admin token: {str(e)}")
        return None

@api_bp.route('/auth/status')
def auth_status():
    return jsonify({
        'authenticated': 'user_id' in session,
        'sso_token': session.get('sso_token', '')
    })

@api_bp.route('/health/database')
def database_health():
    """Database health check endpoint"""
    if 'user_id' not in session:
        return jsonify({'error': 'Authentication required'}), 401
    
    # Check if user is admin
    user = db_manager.execute_query(
        'SELECT username FROM users WHERE id = %s', 
        (session['user_id'],), fetch_one=True
    )
    
    if not user or user[0] != 'admin':
        return jsonify({'error': 'Admin access required'}), 403
    
    health_status = check_database_health()
    db_stats = get_database_stats()
    
    return jsonify({
        'health': health_status,
        'statistics': db_stats
    })

@api_bp.route('/applications', methods=['GET', 'POST'])
def api_applications():
    if request.method == 'GET':
        apps_data = db_manager.execute_query(
            '''SELECT id, name, url, description, git_url, git_repo_size, 
                      docker_build_duration, docker_start_duration, docker_stop_duration, docker_ps_duration 
               FROM applications ORDER BY name''',
            fetch_all=True
        )
        apps = [{
            'id': row[0], 
            'name': row[1], 
            'url': row[2],
            'description': row[3], 
            'git_url': row[4], 
            'git_repo_size': row[5] or 50,
            'docker_build_duration': row[6],
            'docker_start_duration': row[7],
            'docker_stop_duration': row[8],
            'docker_ps_duration': row[9]
        } for row in apps_data]
        return jsonify(apps)
    
    elif request.method == 'POST':
        if 'user_id' not in session:
            return jsonify({'error': 'Authentication required'}), 401
        
        # Check if user is admin
        user = db_manager.execute_query(
            'SELECT username FROM users WHERE id = %s', 
            (session['user_id'],), fetch_one=True
        )
        
        if not user or user[0] != 'admin':
            return jsonify({'error': 'Admin access required'}), 403
        
        data = request.get_json()
        name = data.get('name')
        description = data.get('description', '')
        
        if not name:
            return jsonify({'error': 'Name required'}), 400
        
        git_url = data.get('git_url', '')
        git_repo_size = data.get('git_repo_size', 50)
        app_id = db_manager.execute_query(
            'INSERT INTO applications (name, description, git_url, git_repo_size) VALUES (%s, %s, %s, %s)',
            (name, description, git_url, git_repo_size)
        )
        
        # Queue replication event
        from src.replication_manager import queue_replication_event
        queue_replication_event('applications', 'INSERT', {
            'name': name, 'description': description, 'git_url': git_url, 'git_repo_size': git_repo_size
        })
        
        # Assign new application to all existing users with URLs
        from ..database_postgres import assign_app_to_all_users
        assign_app_to_all_users(app_id, name)
        
        return jsonify({'message': 'Application added successfully'}), 201

@api_bp.route('/applications/pdf-data', methods=['GET'])
def api_applications_pdf_data():
    """Endpoint to get application data for PDF generation"""
    if 'user_id' not in session:
        return jsonify({'error': 'Authentication required'}), 401
    
    # Check if user is admin
    user = db_manager.execute_query(
        'SELECT username FROM users WHERE id = %s', 
        (session['user_id'],), fetch_one=True
    )

    if not user or user[0] != 'admin':
        return jsonify({'error': 'Admin access required'}), 403
    
    try:
        apps_data = db_manager.execute_query(
            'SELECT id, name, description, git_url, git_repo_size FROM applications ORDER BY name',
            fetch_all=True
        )
        apps = [
            {
                'id': row[0], 
                'name': row[1], 
                'description': row[2], 
                'git_url': row[3], 
                'git_repo_size': row[4] or 50
            } 
            for row in apps_data
        ]
        
        from ..config_postgres import DOMAIN
        
        return jsonify({
            'applications': apps,
            'domain': DOMAIN
        })
    except Exception as e:
        logger.error(f"Error fetching PDF data: {e}")
        return jsonify({'error': str(e)}), 500

@api_bp.route('/applications/available', methods=['GET'])
def api_available_applications():
    """Get applications that are NOT assigned to the current user"""
    if 'user_id' not in session:
        return jsonify({'error': 'Authentication required'}), 401
    
    try:
        # Get all applications that are NOT in user_applications for this user
        available_apps_data = db_manager.execute_query('''
            SELECT a.id, a.name, a.description, a.git_url, a.git_repo_size
            FROM applications a
            WHERE a.id NOT IN (
                SELECT application_id 
                FROM user_applications 
                WHERE user_id = %s
            )
            ORDER BY a.name
        ''', (session['user_id'],), fetch_all=True)
        
        available_apps = [
            {
                'id': row[0],
                'name': row[1],
                'description': row[2] or 'No description',
                'git_url': row[3],
                'git_repo_size': row[4] or 50
            }
            for row in available_apps_data
        ]
        
        return jsonify(available_apps)
    except Exception as e:
        logger.error(f"Error fetching available applications: {str(e)}")
        return jsonify({'error': str(e)}), 500

@api_bp.route('/applications/<int:app_id>', methods=['PUT', 'DELETE'])
def api_application_actions(app_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Authentication required'}), 401
    
    # Check if user is admin
    user = db_manager.execute_query(
        'SELECT username FROM users WHERE id = %s', 
        (session['user_id'],), fetch_one=True
    )
    
    if not user or user[0] != 'admin':
        return jsonify({'error': 'Admin access required'}), 403
    
    try:
        if request.method == 'PUT':
            data = request.get_json()
            name = data.get('name')
            url = data.get('url', '')
            description = data.get('description', '')
            new_id = data.get('new_id')
            
            if not name:
                return jsonify({'error': 'Name required'}), 400
            
            target_id = int(new_id) if new_id is not None else app_id
            
            # If new_id is provided and different from current, check uniqueness
            if target_id != app_id:
                existing = db_manager.execute_query(
                    'SELECT id FROM applications WHERE id = %s',
                    (target_id,), fetch_one=True
                )
                if existing:
                    return jsonify({'error': f'Application ID {target_id} already exists. Please choose a unique ID.'}), 400
            
            # Propagate the edited link to the per-user user_applications.url
            # rows ONLY when the link actually changed. Read the currently
            # stored applications.url so we can tell a real link edit from a
            # non-link edit that merely re-submits the existing (or empty) url:
            #   - non-link edit (url unchanged, incl. empty) -> leave
            #     user_applications.url untouched (preservation Req 3.1)
            #   - genuine link change -> propagate to user_applications.url
            #     (Req 2.1/2.2/2.3), for both ID-unchanged and ID-changing paths
            current_app = db_manager.execute_query(
                'SELECT url FROM applications WHERE id = %s',
                (app_id,), fetch_one=True
            )
            current_url = current_app[0] if current_app else None
            link_changed = (url or '') != (current_url or '')

            git_url = data.get('git_url', '')
            git_repo_size = data.get('git_repo_size', 50)
            docker_build_duration = data.get('docker_build_duration')
            docker_start_duration = data.get('docker_start_duration')
            docker_stop_duration = data.get('docker_stop_duration')
            docker_ps_duration = data.get('docker_ps_duration')
            
            if target_id != app_id:
                # ID is changing - run all updates in a single transaction with deferred constraints
                with db_manager.get_db_connection() as conn:
                    with conn.cursor() as cursor:
                        cursor.execute('SET CONSTRAINTS ALL DEFERRED')
                        cursor.execute('''UPDATE applications SET id = %s, name = %s, url = %s, description = %s, git_url = %s, git_repo_size = %s,
                                   docker_build_duration = %s, docker_start_duration = %s, docker_stop_duration = %s, docker_ps_duration = %s
                            WHERE id = %s
                        ''', (target_id, name, url, description, git_url, git_repo_size, docker_build_duration, docker_start_duration, docker_stop_duration, docker_ps_duration, app_id))
                        cursor.execute('UPDATE user_applications SET application_id = %s WHERE application_id = %s', (target_id, app_id))
                        if link_changed:
                            cursor.execute('UPDATE user_applications SET url = %s WHERE application_id = %s', (url, target_id))
                        cursor.execute('UPDATE deployments SET application_id = %s WHERE application_id = %s', (target_id, app_id))
                        cursor.execute('UPDATE application_costs SET application_id = %s WHERE application_id = %s', (target_id, app_id))
                        cursor.execute('UPDATE billing_activities SET application_id = %s WHERE application_id = %s', (target_id, app_id))
                    conn.commit()
            else:
                # ID unchanged - simple update
                db_manager.execute_query('''UPDATE applications SET name = %s, url = %s, description = %s, git_url = %s, git_repo_size = %s,
                           docker_build_duration = %s, docker_start_duration = %s, docker_stop_duration = %s, docker_ps_duration = %s
                    WHERE id = %s
                ''', (name, url, description, git_url, git_repo_size, docker_build_duration, docker_start_duration, docker_stop_duration, docker_ps_duration, app_id))
                if link_changed:
                    db_manager.execute_query('UPDATE user_applications SET url = %s WHERE application_id = %s', (url, app_id))
            
            return jsonify({'message': 'Application updated successfully'})
        
        elif request.method == 'DELETE':
            db_manager.execute_query('DELETE FROM applications WHERE id = %s', (app_id,))
            return jsonify({'message': 'Application deleted successfully'})
            
    except Exception as e:
        return jsonify({'error': f'Database error: {str(e)}'}), 500

@api_bp.route('/users', methods=['GET', 'POST'])
def api_users():
    if 'user_id' not in session:
        return jsonify({'error': 'Authentication required'}), 401
    
    try:
        # Check if user is admin
        user = db_manager.execute_query(
            'SELECT username FROM users WHERE id = %s', 
            (session['user_id'],), fetch_one=True
        )
        
        if not user or user[0] != 'admin':
            return jsonify({'error': 'Admin access required'}), 403
    
        if request.method == 'GET':
            # Get all users
            users_data = db_manager.execute_query(
                'SELECT id, username, email, first_name, last_name, suspended, created_at, totp_enabled, twofa_email_enabled FROM users ORDER BY username',
                fetch_all=True
            )
            users = [{
                'id': row[0],
                'username': row[1], 
                'email': row[2],
                'first_name': row[3],
                'last_name': row[4],
                'suspended': bool(row[5]),
                'created_at': row[6],
                'totp_enabled': bool(row[7]) if len(row) > 7 and row[7] is not None else False,
                'email_2fa_enabled': bool(row[8]) if len(row) > 8 and row[8] is not None else False
            } for row in users_data]
            return jsonify(users)
        
        elif request.method == 'POST':
            # Add new user
            data = request.get_json()
            username = data.get('username')
            email = data.get('email')
            password = data.get('password')
            first_name = data.get('first_name', '')
            last_name = data.get('last_name', '')
            
            if not all([username, email, password]):
                return jsonify({'error': 'Username, email and password required'}), 400
            
            try:
                password_hash = generate_password_hash(password)
                user_id = db_manager.execute_query('''INSERT INTO users (username, email, password_hash, first_name, last_name)
                    VALUES (%s, %s, %s, %s, %s)
                ''', (username, email, password_hash, first_name, last_name))
                
                # Assign default applications to new user
                try:
                    from ..database_postgres import assign_default_apps_to_user
                    assign_default_apps_to_user(user_id)
                except Exception as e:
                    logger.warning(f"Warning: Failed to assign default apps to user {user_id}: {str(e)}")
                
                # Create user in Gitea
                create_gitea_user(username, email, password, first_name, last_name)
                
                return jsonify({'message': 'User created successfully'}), 201
            except Exception as e:
                logger.error(f"Warning: Failed to create user {user_id}: {str(e)}")
                if 'already exists' in str(e).lower() or 'unique' in str(e).lower():
                    return jsonify({'error': 'Username or email already exists'}), 409
                return jsonify({'error': f'Database error: {str(e)}'}), 500
                
    except Exception as e:
        logger.error(f"Warning: Failed to GET/POST user {user_id} in DB: {str(e)}")
        return jsonify({'error': f'Server error: {str(e)}'}), 500

@api_bp.route('/users/<int:user_id>', methods=['PUT', 'DELETE'])
def api_user_actions(user_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Authentication required'}), 401
    
    try:
        # Check if user is admin
        user = db_manager.execute_query(
            'SELECT username FROM users WHERE id = %s', 
            (session['user_id'],), fetch_one=True
        )
        
        if not user or user[0] != 'admin':
            return jsonify({'error': 'Admin access required'}), 403
    
        if request.method == 'PUT':
            data = request.get_json()
            action = data.get('action')
            
            if action == 'suspend':
                db_manager.execute_query('UPDATE users SET suspended = TRUE WHERE id = %s', (user_id,))
            elif action == 'unsuspend':
                db_manager.execute_query('UPDATE users SET suspended = FALSE WHERE id = %s', (user_id,))
            elif action == 'update':
                username = data.get('username')
                email = data.get('email')
                first_name = data.get('first_name', '')
                last_name = data.get('last_name', '')
                
                if not all([username, email]):
                    return jsonify({'error': 'Username and email required'}), 400
                
                try:
                    db_manager.execute_query('''UPDATE users SET username = %s, email = %s, first_name = %s, last_name = %s
                        WHERE id = %s
                    ''', (username, email, first_name, last_name, user_id))
                except Exception as e:
                    if 'already exists' in str(e).lower() or 'unique' in str(e).lower():
                        return jsonify({'error': 'Username or email already exists'}), 409
                    raise
            
            return jsonify({'message': 'User updated successfully'})
        
        elif request.method == 'DELETE':
            db_manager.execute_query('DELETE FROM users WHERE id = %s', (user_id,))
            return jsonify({'message': 'User deleted successfully'})
            
    except Exception as e:
        logger.error(f"Warning: Failed to PUT/DELETE user {user_id}: {str(e)}")
        return jsonify({'error': f'Database error: {str(e)}'}), 500

@api_bp.route('/users/<int:user_id>/applications', methods=['GET', 'POST', 'DELETE'])
def api_user_applications(user_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Authentication required'}), 401
    
    # Check if user is admin
    user = db_manager.execute_query(
        'SELECT username FROM users WHERE id = %s', 
        (session['user_id'],), fetch_one=True
    )
    
    if not user or user[0] != 'admin':
        return jsonify({'error': 'Admin access required'}), 403
    
    try:
        if request.method == 'GET':
            # Get assigned applications for user
            assigned_data = db_manager.execute_query('''SELECT a.id, a.name, a.git_url, a.git_repo_size FROM applications a
                JOIN user_applications ua ON a.id = ua.application_id
                WHERE ua.user_id = %s
            ''', (user_id,), fetch_all=True)
            assigned = [{'id': row[0], 'name': row[1], 'git_url': row[2], 'git_repo_size': row[3]} for row in assigned_data]
            
            # Get all applications with git_url and git_repo_size
            all_apps_data = db_manager.execute_query(
                'SELECT id, name, git_url, git_repo_size FROM applications ORDER BY name',
                fetch_all=True
            )
            all_apps = [{'id': row[0], 'name': row[1], 'git_url': row[2], 'git_repo_size': row[3]} for row in all_apps_data]
            
            return jsonify({'assigned': assigned, 'all': all_apps})
        
        elif request.method == 'POST':
            data = request.get_json()
            app_id = data.get('application_id')
            
            if not app_id:
                return jsonify({'error': 'Application ID required'}), 400
            
            try:
                # Calculate ports for the user and application
                from ..database_postgres import calculate_app_ports, APP_PORT_COLUMNS_SQL, APP_PORT_PLACEHOLDERS_SQL
                app_ports = calculate_app_ports(user_id, app_id)
                
                # Get application name for URL generation
                app_result = db_manager.execute_query(
                    'SELECT name FROM applications WHERE id = %s', 
                    (app_id,), fetch_one=True
                )
                if not app_result:
                    return jsonify({'error': 'Application not found'}), 404
                
                app_name = app_result[0]
                url = f'https://{DOMAIN}:{app_ports[1]}'
                
                db_manager.execute_query(
                    f'INSERT INTO user_applications (user_id, application_id, url, {APP_PORT_COLUMNS_SQL}) VALUES (%s, %s, %s, {APP_PORT_PLACEHOLDERS_SQL})',
                    (user_id, app_id, url, *app_ports)
                )
                
                # Update nginx configuration with dynamic location
                try:
                    # Get username for nginx location
                    user_result = db_manager.execute_query(
                        'SELECT username FROM users WHERE id = %s',
                        (user_id,), fetch_one=True
                    )
                    user_name = user_result[0] if user_result else f'user_{user_id}'
                    insert_location_block(user_name, app_name, url, url)
                    logger.info(f"Nginx location added for user {user_name} app {app_name}")
                except Exception as e:
                    logger.warning(f"Failed to update nginx config: {e}")
                
                return jsonify({'message': 'Application assigned successfully'})
            except Exception as e:
                if 'already exists' in str(e).lower() or 'unique' in str(e).lower():
                    return jsonify({'error': 'Application already assigned'}), 409
                raise
        
        elif request.method == 'DELETE':
            data = request.get_json()
            app_id = data.get('application_id')
            
            if not app_id:
                return jsonify({'error': 'Application ID required'}), 400
            
            # Get app name before deletion
            app_result = db_manager.execute_query(
                'SELECT name FROM applications WHERE id = %s', 
                (app_id,), fetch_one=True
            )
            
            db_manager.execute_query(
                'DELETE FROM user_applications WHERE user_id = %s AND application_id = %s',
                (user_id, app_id)
            )
            
            # Remove nginx location
            if app_result:
                try:
                    # Get username for nginx location
                    user_result = db_manager.execute_query(
                        'SELECT username FROM users WHERE id = %s',
                        (user_id,), fetch_one=True
                    )
                    user_name = user_result[0] if user_result else f'user_{user_id}'
                    remove_location_block(user_name, app_result[0])
                    logger.info(f"Nginx location removed for user {user_name} app {app_result[0]}")
                except Exception as e:
                    logger.warning(f"Failed to remove nginx location: {e}")
            
            return jsonify({'message': 'Application unassigned successfully'})
            
    except Exception as e:
        return jsonify({'error': f'Database error: {str(e)}'}), 500



@api_bp.route('/database/tables/<table_name>', methods=['GET', 'POST'])
def api_database_table(table_name):
    """Database table management endpoint"""
    if 'user_id' not in session:
        return jsonify({'error': 'Authentication required'}), 401
    
    # Check if user is admin
    user = db_manager.execute_query(
        'SELECT username FROM users WHERE id = %s', 
        (session['user_id'],), fetch_one=True
    )
    
    if not user or user[0] != 'admin':
        return jsonify({'error': 'Admin access required'}), 403
    
    # Validate table name to prevent SQL injection
    allowed_tables = [
        'users', 'applications', 'auth_tokens', 'user_applications', 
        'deployments', 'servers', 'instances', 'services',
        'application_costs', 'billing_activities', 'users_logs',
        'payment_modes', 'invoicing'
    ]
    
    if table_name not in allowed_tables:
        return jsonify({'error': 'Invalid table name'}), 400
    
    if request.method == 'GET':
        try:
            if USE_POSTGRES:
                # PostgreSQL: Get table structure from information_schema
                columns_data = db_manager.execute_query('''SELECT column_name FROM information_schema.columns 
                    WHERE table_name = %s AND table_schema = 'public'
                    ORDER BY ordinal_position
                ''', (table_name,), fetch_all=True)
                columns = [col[0] for col in columns_data]
            else:
                # SQLite: Use PRAGMA table_info
                columns_data = db_manager.execute_query(
                    f'PRAGMA table_info({table_name})', fetch_all=True
                )
                columns = [col[1] for col in columns_data]  # col[1] is the column name
            
            # Get table data
            rows = db_manager.execute_query(
                f'SELECT * FROM {table_name} ORDER BY id DESC LIMIT 100', fetch_all=True
            )
            
            return jsonify({
                'columns': columns,
                'rows': rows
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    elif request.method == 'POST':
        try:
            data = request.get_json()
            if not data or not isinstance(data, dict):
                return jsonify({'error': 'Invalid JSON data'}), 400
            
            if not data.keys():
                return jsonify({'error': 'No data provided'}), 400
            
            # Build INSERT query dynamically
            columns = list(data.keys())
            placeholders = ', '.join(['%s' for _ in columns])
            column_names = ', '.join(columns)
            values = [data[col] for col in columns]
            
            query = f'INSERT INTO {table_name} ({column_names}) VALUES ({placeholders})'
            db_manager.execute_query(query, values)
            
            return jsonify({'message': 'Record added successfully'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

@api_bp.route('/platform/status')
def platform_status():
    """Platform status endpoint for server discovery"""
    try:
        current_ip = get_current_server_ip()
        server = db_manager.execute_query(
            'SELECT server_type, server_name FROM servers WHERE server_ip = %s',
            (current_ip,), fetch_one=True
        )
        
        if server:
            role = server[0].upper()
            name = server[1]
        else:
            role = 'PRIMARY'
            name = 'unknown'
        
        # Get all servers
        servers = db_manager.execute_query(
            'SELECT server_ip, server_name, server_type FROM servers ORDER BY id',
            fetch_all=True
        )
        
        response = jsonify({
            'platform': 'SwAutoMorph',
            'version': '1.0',
            'role': role,
            'server_ip': current_ip,
            'server_name': name,
            'servers': [{'ip': s[0], 'name': s[1], 'type': s[2]} for s in servers]
        })
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Accept'
        return response
    except Exception as e:
        response = jsonify({'error': str(e)})
        response.headers['Access-Control-Allow-Origin'] = '*'
        return response, 500

@api_bp.route('/platform/servers/add', methods=['POST'])
def platform_servers_add():
    """Public endpoint to add server record (no authentication required for cross-platform sync)"""
    try:
        logger.info("[PLATFORM_SERVERS_ADD] Received request")
        data = request.get_json()
        logger.info(f"[PLATFORM_SERVERS_ADD] Request data: {data}")
        
        if not data or not isinstance(data, dict):
            logger.error("[PLATFORM_SERVERS_ADD] Invalid JSON data")
            return jsonify({'error': 'Invalid JSON data'}), 400
        
        required_fields = ['SERVER_IP', 'SERVER_NAME', 'SERVER_CAPACITY_USER_MAX', 
                          'SERVER_CAPACITY_APPLI_MAX', 'SERVER_STATUS', 'SERVER_TYPE']
        
        if not all(field in data for field in required_fields):
            logger.error(f"[PLATFORM_SERVERS_ADD] Missing required fields. Received: {list(data.keys())}")
            return jsonify({'error': 'Missing required fields'}), 400
        
        # Check if server already exists
        logger.info(f"[PLATFORM_SERVERS_ADD] Checking if server {data['SERVER_IP']} exists")
        existing = db_manager.execute_query(
            'SELECT id FROM servers WHERE server_ip = %s',
            (data['SERVER_IP'],), fetch_one=True
        )
        
        if existing:
            logger.info(f"[PLATFORM_SERVERS_ADD] Server {data['SERVER_IP']} already exists with id {existing[0]}")
            return jsonify({'message': 'Server already exists', 'server_id': existing[0]}), 200
        
        # Insert new server
        logger.info(f"[PLATFORM_SERVERS_ADD] Inserting new server: {data['SERVER_NAME']} ({data['SERVER_IP']})")
        db_manager.execute_query('''INSERT INTO servers (server_ip, server_name, server_capacity_user_max, 
                               server_capacity_appli_max, server_status, server_type)
            VALUES (%s, %s, %s, %s, %s, %s)
        ''', (data['SERVER_IP'], data['SERVER_NAME'], data['SERVER_CAPACITY_USER_MAX'],
              data['SERVER_CAPACITY_APPLI_MAX'], data['SERVER_STATUS'], data['SERVER_TYPE']))
        
        logger.info(f"[PLATFORM_SERVERS_ADD] Server {data['SERVER_IP']} added successfully")
        return jsonify({'message': 'Server added successfully'}), 201
        
    except Exception as e:
        logger.error(f"[PLATFORM_SERVERS_ADD] Error adding server: {str(e)}")
        return jsonify({'error': str(e)}), 500

@api_bp.route('/servers/discover', methods=['POST'])
def api_servers_discover():
    """Proxy endpoint to discover remote servers (avoids CORS issues)"""
    if 'user_id' not in session:
        return jsonify({'error': 'Authentication required'}), 401
    
    user = db_manager.execute_query(
        'SELECT username FROM users WHERE id = %s', 
        (session['user_id'],), fetch_one=True
    )
    
    if not user or user[0] != 'admin':
        return jsonify({'error': 'Admin access required'}), 403
    
    try:
        data = request.get_json()
        remote_ip = data.get('remote_ip')
        
        if not remote_ip:
            return jsonify({'error': 'Remote IP required'}), 400
        
        # Use check_remote_platform which handles SSL verification
        remote_status = check_remote_platform(remote_ip)
        
        if remote_status and remote_status.get('platform') == 'SwAutoMorph':
            return jsonify(remote_status)
        else:
            return jsonify({'error': 'No SwAutoMorph platform detected'}), 404
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_bp.route('/servers/add-remote', methods=['POST'])
def api_servers_add_remote():
    """Add reciprocal server record on remote SwAutoMorph instance (server-side proxy)"""
    if 'user_id' not in session:
        return jsonify({'error': 'Authentication required'}), 401
    
    user = db_manager.execute_query(
        'SELECT username FROM users WHERE id = %s', 
        (session['user_id'],), fetch_one=True
    )
    
    if not user or user[0] != 'admin':
        return jsonify({'error': 'Admin access required'}), 403
    
    try:
        data = request.get_json()
        remote_ip = data.get('remote_ip')
        
        if not remote_ip:
            return jsonify({'error': 'Remote IP required'}), 400
        
        # Get current PRIMARY server details from local database
        current_ip = get_current_server_ip()
        primary_server = db_manager.execute_query(
            'SELECT server_ip, server_name, server_type, server_capacity_user_max, server_capacity_appli_max, server_status FROM servers WHERE server_type = %s LIMIT 1',
            ('PRIMARY',), fetch_one=True
        )
        
        if not primary_server:
            return jsonify({'error': 'No PRIMARY server found in local database'}), 400
        
        # Use PRIMARY server details
        server_ip = primary_server[0]
        server_name = primary_server[1]
        server_type = primary_server[2]
        capacity_user = primary_server[3]
        capacity_appli = primary_server[4]
        server_status = primary_server[5]
        
        # Prepare data to send to remote server (send PRIMARY server info)
        remote_data = {
            'SERVER_IP': server_ip,
            'SERVER_NAME': server_name,
            'SERVER_CAPACITY_USER_MAX': capacity_user,
            'SERVER_CAPACITY_APPLI_MAX': capacity_appli,
            'SERVER_STATUS': server_status,
            'SERVER_TYPE': server_type
        }
        
        # Call remote server's /api/platform/servers/add endpoint (public endpoint)
        remote_url = f"https://{remote_ip}/api/platform/servers/add"
        
        response = requests.post(
            remote_url,
            json=remote_data,
            timeout=10,
            verify=False
        )
        
        if response.status_code in [200, 201]:
            return jsonify({'message': 'Reciprocal server record added successfully'})
        else:
            return jsonify({'error': f'Remote server returned {response.status_code}: {response.text}'}), 500
            
    except requests.exceptions.RequestException as e:
        return jsonify({'error': f'Failed to connect to remote server: {str(e)}'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_bp.route('/servers', methods=['GET', 'POST'])
def api_servers():
    """Server management endpoint with discovery"""
    if 'user_id' not in session:
        return jsonify({'error': 'Authentication required'}), 401
    
    # Check if user is admin
    user = db_manager.execute_query(
        'SELECT username FROM users WHERE id = %s', 
        (session['user_id'],), fetch_one=True
    )
    
    if not user or user[0] != 'admin':
        return jsonify({'error': 'Admin access required'}), 403
    
    if request.method == 'GET':
        servers = db_manager.execute_query('''SELECT id, server_ip, server_name, server_capacity_user_max, 
                   server_capacity_appli_max, server_status, server_type, created_at
            FROM servers ORDER BY id
        ''', fetch_all=True)
        
        local_ip = get_current_server_ip()
        
        servers_list = [{
            'id': row[0],
            'SERVER_IP': row[1],
            'SERVER_NAME': row[2],
            'SERVER_CAPACITY_USER_MAX': row[3],
            'SERVER_CAPACITY_APPLI_MAX': row[4],
            'SERVER_STATUS': row[5],
            'SERVER_TYPE': row[6],
            'created_at': row[7]
        } for row in servers]
        
        return jsonify({'servers': servers_list, 'local_ip': local_ip})
    
    elif request.method == 'POST':
        data = request.get_json()
        
        if not data or not isinstance(data, dict):
            return jsonify({'error': 'Invalid JSON data'}), 400
        
        required_fields = ['SERVER_IP', 'SERVER_NAME', 'SERVER_CAPACITY_USER_MAX', 
                          'SERVER_CAPACITY_APPLI_MAX', 'SERVER_STATUS']
        
        if not all(field in data for field in required_fields):
            return jsonify({'error': 'Missing required fields'}), 400
        
        try:
            remote_ip = data['SERVER_IP']
            current_ip = get_current_server_ip()
            
            # Discovery: Check if remote IP is running SwAutoMorph
            remote_status = check_remote_platform(remote_ip)
            
            if remote_status and remote_status.get('platform') == 'SwAutoMorph':
                # Remote is SwAutoMorph - determine roles
                our_role = determine_role(current_ip, remote_ip, remote_status, db_manager)
                
                # Update current server role
                update_server_role(current_ip, our_role, db_manager)
                
                # Set remote server type based on their role
                server_type = remote_status.get('role', 'PRIMARY')
                
                logger.info(f"[DISCOVERY] Remote SwAutoMorph detected at {remote_ip} (role: {server_type}), setting local role to {our_role}")
            else:
                # Not SwAutoMorph or no response - use provided type or default
                server_type = data.get('SERVER_TYPE', 'SECONDARY')
                logger.info(f"[DISCOVERY] No SwAutoMorph detected at {remote_ip}, adding as {server_type}")
            
            # Insert new server
            db_manager.execute_query('''INSERT INTO servers (server_ip, server_name, server_capacity_user_max, 
                                   server_capacity_appli_max, server_status, server_type)
                VALUES (%s, %s, %s, %s, %s, %s)
            ''', (remote_ip, data['SERVER_NAME'], data['SERVER_CAPACITY_USER_MAX'],
                  data['SERVER_CAPACITY_APPLI_MAX'], data['SERVER_STATUS'], server_type))
            
            return jsonify({
                'message': 'Server created successfully',
                'discovered': remote_status is not None,
                'server_type': server_type
            }), 201
        except Exception as e:
            return jsonify({'error': str(e)}), 500

@api_bp.route('/servers/<int:server_id>', methods=['PUT', 'DELETE'])
def api_server_actions(server_id):
    """Server update/delete endpoint"""
    if 'user_id' not in session:
        return jsonify({'error': 'Authentication required'}), 401
    
    # Check if user is admin
    user = db_manager.execute_query(
        'SELECT username FROM users WHERE id = %s', 
        (session['user_id'],), fetch_one=True
    )
    
    if not user or user[0] != 'admin':
        return jsonify({'error': 'Admin access required'}), 403
    
    if request.method == 'PUT':
        try:
            data = request.get_json()
            if not data or not isinstance(data, dict):
                return jsonify({'error': 'Invalid JSON data'}), 400
            
            required_fields = ['SERVER_IP', 'SERVER_NAME', 'SERVER_CAPACITY_USER_MAX', 
                             'SERVER_CAPACITY_APPLI_MAX', 'SERVER_STATUS', 'SERVER_TYPE']
            if not all(field in data for field in required_fields):
                return jsonify({'error': 'Missing required fields'}), 400
            
            db_manager.execute_query('''UPDATE servers SET server_ip = %s, server_name = %s, 
                                 server_capacity_user_max = %s, server_capacity_appli_max = %s,
                                 server_status = %s, server_type = %s
                WHERE id = %s
            ''', (data['SERVER_IP'], data['SERVER_NAME'], data['SERVER_CAPACITY_USER_MAX'],
                  data['SERVER_CAPACITY_APPLI_MAX'], data['SERVER_STATUS'], data['SERVER_TYPE'], server_id))
            
            return jsonify({'message': 'Server updated successfully'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    elif request.method == 'DELETE':
        try:
            # Check if server is ACTIVE
            server = db_manager.execute_query(
                'SELECT server_status FROM servers WHERE id = %s', 
                (server_id,), fetch_one=True
            )
            
            if not server:
                return jsonify({'error': 'Server not found'}), 404
            
            if server[0] == 'ACTIVE':
                return jsonify({'error': 'Cannot delete ACTIVE server'}), 400
            
            db_manager.execute_query('DELETE FROM servers WHERE id = %s', (server_id,))
            return jsonify({'message': 'Server deleted successfully'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

@api_bp.route('/servers/<int:server_id>/promote', methods=['POST'])
def api_server_promote(server_id):
    """Promote server to PRIMARY if no PRIMARY exists"""
    if 'user_id' not in session:
        return jsonify({'error': 'Authentication required'}), 401
    
    user = db_manager.execute_query(
        'SELECT username FROM users WHERE id = %s', 
        (session['user_id'],), fetch_one=True
    )
    
    if not user or user[0] != 'admin':
        return jsonify({'error': 'Admin access required'}), 403
    
    try:
        # Check if PRIMARY already exists
        primary = db_manager.execute_query(
            'SELECT id FROM servers WHERE server_type = %s',
            ('PRIMARY',), fetch_one=True
        )
        
        if primary:
            return jsonify({'error': 'PRIMARY server already exists'}), 400
        
        # Promote to PRIMARY
        db_manager.execute_query(
            'UPDATE servers SET server_type = %s WHERE id = %s',
            ('PRIMARY', server_id)
        )
        
        return jsonify({'message': 'Server promoted to PRIMARY successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_bp.route('/servers/<int:server_id>/promote-secondary', methods=['POST'])
def api_server_promote_secondary(server_id):
    """Promote STAND_ALONE server to SECONDARY"""
    if 'user_id' not in session:
        return jsonify({'error': 'Authentication required'}), 401
    
    user = db_manager.execute_query(
        'SELECT username FROM users WHERE id = %s', 
        (session['user_id'],), fetch_one=True
    )
    
    if not user or user[0] != 'admin':
        return jsonify({'error': 'Admin access required'}), 403
    
    try:
        db_manager.execute_query(
            'UPDATE servers SET server_type = %s WHERE id = %s',
            ('SECONDARY', server_id)
        )
        return jsonify({'message': 'Server promoted to SECONDARY successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_bp.route('/servers/<int:server_id>/sync', methods=['POST'])
def api_server_sync(server_id):
    """Synchronize SECONDARY server with PRIMARY server"""
    if 'user_id' not in session:
        return jsonify({'error': 'Authentication required'}), 401
    
    user = db_manager.execute_query(
        'SELECT username FROM users WHERE id = %s', 
        (session['user_id'],), fetch_one=True
    )
    
    if not user or user[0] != 'admin':
        return jsonify({'error': 'Admin access required'}), 403
    
    try:
        # Get server details
        server = db_manager.execute_query(
            'SELECT server_type, server_ip, server_name FROM servers WHERE id = %s',
            (server_id,), fetch_one=True
        )
        
        if not server:
            return jsonify({'error': 'Server not found'}), 404
        
        server_type, server_ip, server_name = server
        
        if server_type != 'SECONDARY':
            return jsonify({'error': 'Only SECONDARY servers can be synchronized'}), 400
        
        # Get PRIMARY server
        primary = db_manager.execute_query(
            'SELECT server_ip FROM servers WHERE server_type = %s',
            ('PRIMARY',), fetch_one=True
        )
        
        if not primary:
            return jsonify({'error': 'No PRIMARY server found'}), 404
        
        primary_ip = primary[0]
        
        # Trigger replication sync from PRIMARY to SECONDARY
        try:
            from src.replication_manager import trigger_full_sync
            trigger_full_sync(primary_ip, server_ip)
            logger.info(f"Synchronization triggered for server {server_name} ({server_ip}) from PRIMARY {primary_ip}")
            return jsonify({'message': f'Synchronization completed for server {server_name}'})
        except Exception as sync_error:
            logger.error(f"Synchronization failed for server {server_name}: {str(sync_error)}")
            return jsonify({'error': f'Synchronization failed: {str(sync_error)}'}), 500
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_bp.route('/server/allocate', methods=['POST'])
def api_server_allocate():
    """Allocate server for deployment based on capacity constraints"""
    if 'user_id' not in session:
        return jsonify({'error': 'Authentication required'}), 401
    
    try:
        data = request.get_json()
        application_name = data.get('application_name')
        
        if not application_name:
            return jsonify({'error': 'Application name required'}), 400
        
        # Find available server based on capacity constraints with usage counts
        servers = db_manager.execute_query('''SELECT s.id, COALESCE(s.server_capacity_user_max, 100) AS server_capacity_user_max, COALESCE(s.server_capacity_appli_max, 100) AS server_capacity_appli_max,
                   COALESCE(user_counts.user_count, 0) as current_users,
                   COALESCE(app_counts.app_count, 0) as current_apps
            FROM servers s
            LEFT JOIN (
                SELECT server_id, COUNT(DISTINCT user_id) as user_count
                FROM deployments
                WHERE server_id IS NOT NULL
                GROUP BY server_id
            ) user_counts ON s.id = user_counts.server_id
            LEFT JOIN (
                SELECT server_id, COUNT(DISTINCT application_name) as app_count
                FROM deployments
                WHERE server_id IS NOT NULL
                GROUP BY server_id
            ) app_counts ON s.id = app_counts.server_id
            WHERE s.server_status = 'STAND_BY' OR s.server_status = 'ACTIVE'
            ORDER BY s.server_status ASC
        ''', fetch_all=True)
        
        if not servers:
            return jsonify({'error': 'No standby servers available'}), 503
        
        for server in servers:
            try:
                server_id, user_max, appli_max, user_count, appli_count = server
                
                # Check if server has capacity
                if user_count < user_max and appli_count < appli_max:
                    # Update server status to ACTIVE only if currently STAND_BY
                    db_manager.execute_query('''UPDATE servers SET server_status = 'ACTIVE' 
                        WHERE id = %s AND server_status = 'STAND_BY'
                    ''', (server_id,))
                    
                    return jsonify({'server_id': server_id})
            except Exception as server_error:
                # A problematic candidate server must not abort evaluation of the
                # remaining servers; log and skip to the next candidate.
                logger.warning(f"[SERVER ALLOCATE] Skipping server {server} due to evaluation error: {str(server_error)}")
                continue
        
        return jsonify({'error': 'All servers at capacity'}), 503
        
    except Exception as e:
        return jsonify({'error': f'Server allocation failed: {str(e)}'}), 500

@api_bp.route('/database/tables/<table_name>/<record_id>', methods=['PUT', 'DELETE'])
def api_database_record(table_name, record_id):
    """Database record management endpoint"""
    if 'user_id' not in session:
        return jsonify({'error': 'Authentication required'}), 401
    
    # Check if user is admin
    user = db_manager.execute_query(
        'SELECT username FROM users WHERE id = %s', 
        (session['user_id'],), fetch_one=True
    )
    
    if not user or user[0] != 'admin':
        return jsonify({'error': 'Admin access required'}), 403
    
    # Validate table name
    allowed_tables = [
        'users', 'applications', 'auth_tokens', 'user_applications', 
        'deployments', 'servers', 'instances', 'services',
        'application_costs', 'billing_activities', 'users_logs',
        'payment_modes', 'invoicing'
    ]
    
    if table_name not in allowed_tables:
        return jsonify({'error': 'Invalid table name'}), 400
    
    if request.method == 'PUT':
        try:
            data = request.get_json()
            if not data or not isinstance(data, dict):
                return jsonify({'error': 'Invalid JSON data'}), 400
            
            # Build UPDATE query dynamically
            set_clauses = []
            values = []
            
            try:
                for column, value in data.items():
                    if column.lower() != 'id':  # Don't update ID
                        set_clauses.append(f'{column} = %s')
                        values.append(value)
            except (AttributeError, TypeError) as e:
                return jsonify({'error': 'Invalid data format'}), 400
            
            if not set_clauses:
                return jsonify({'error': 'No fields to update'}), 400
            
            values.append(record_id)  # Add ID for WHERE clause
            set_clause = ', '.join(set_clauses)
            query = f'UPDATE {table_name} SET {set_clause} WHERE id = %s'
            
            db_manager.execute_query(query, values)
            
            return jsonify({'message': 'Record updated successfully'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    elif request.method == 'DELETE':
        try:
            db_manager.execute_query(f'DELETE FROM {table_name} WHERE id = %s', (record_id,))
            return jsonify({'message': 'Record deleted successfully'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

def _handle_clone_action(user_id, app_name, git_url, server_id, deployment_path, data):
    """Handle clone deployment action"""
    if not git_url:
        logger.error(f"[DEPLOYMENT API] CLONE - FAILED - No git_url provided for user {user_id}")
        return jsonify({'error': 'Git URL required for clone action'}), 400
    
    if not server_id:
        logger.error(f"[DEPLOYMENT API] CLONE - FAILED - No server_id provided for user {user_id}")
        return jsonify({'error': 'Server ID required for clone action'}), 400
    
    logger.info(f"[DEPLOYMENT API] CLONE/SWITCH - Starting clone from {git_url} to {deployment_path}")
    
    # Get current and target server IPs
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        current_server_ip = s.getsockname()[0]
        s.close()
    except (OSError, socket.error) as e:
        logger.warning(f"[DEPLOYMENT API] CLONE - Warning: Failed to get current server IP: {str(e)}")
        current_server_ip = "127.0.0.1"
    
    target_server = db_manager.execute_query(
        'SELECT server_ip FROM servers WHERE id = %s', 
        (server_id,), fetch_one=True
    )
    
    if not target_server:
        logger.error(f"[DEPLOYMENT API] CLONE - FAILED - Server {server_id} not found")
        return jsonify({'error': f'Server {server_id} not found'}), 400
    
    target_server_ip = target_server[0]

    # Req 4.1: reject a resolved-but-unusable server IP before any command is built
    if target_server_ip is None or (isinstance(target_server_ip, str) and not target_server_ip.strip()):
        logger.error(f"[DEPLOYMENT API] CLONE - FAILED - Server {server_id} has no usable IP address")
        return jsonify({'error': f'Server {server_id} has no usable IP address'}), 400

    is_local_server = (target_server_ip == current_server_ip or target_server_ip == "127.0.0.1" or target_server_ip == "localhost")
    
    # Determine if git_url is GitHub or Gitea/localhost
    is_github = 'github.com' in git_url.lower()
    
    # Execute clone operation
    git_env = os.environ.copy()
    git_env.update({'GIT_CONFIG_NOSYSTEM': '1', 'HOME': f'/home/{LINUX_USER_INSTALLATION}', 'USER': LINUX_USER_INSTALLATION})
    
    if is_local_server:
        if is_github:
            # GitHub: Fresh clone (delete and clone)
            if os.path.exists(deployment_path):
                shutil.rmtree(deployment_path)
            os.makedirs(deployment_path, exist_ok=True)
            result = subprocess.run(['git', 'clone', '--recurse-submodules', git_url, deployment_path], 
                                  capture_output=True, text=True, timeout=TIMEOUT_SUBPROCESS_RUN, env=git_env)
            logger.info(f"[DEPLOYMENT API] CLONE - GitHub: git clone --recurse-submodules {git_url} {deployment_path}")
        else:
            # Gitea/localhost: Use fetch and switch
            if os.path.exists(deployment_path):
                result = subprocess.run(['git', 'fetch', '--all'], cwd=deployment_path,
                                      capture_output=True, text=True, timeout=TIMEOUT_SUBPROCESS_RUN, env=git_env)
                if result.returncode == 0:
                    result = subprocess.run(['git', 'remote', 'set-url', 'origin', git_url], cwd=deployment_path,
                                          capture_output=True, text=True, timeout=TIMEOUT_SUBPROCESS_RUN, env=git_env)
                    logger.info(f"[DEPLOYMENT API] GIT SWITCH - Gitea/localhost: git remote set-url origin {git_url}")

                    if result.returncode == 0:
                        result = subprocess.run(['git', 'checkout', '-B', 'main', 'origin/main'], cwd=deployment_path,
                                              capture_output=True, text=True, timeout=TIMEOUT_SUBPROCESS_RUN, env=git_env)
                        logger.info(f"[DEPLOYMENT API] GIT SWITCH - Gitea/localhost: git checkout -B main origin/main")
            else:
                os.makedirs(deployment_path, exist_ok=True)
                result = subprocess.run(['git', 'clone', '--recurse-submodules', git_url, deployment_path], 
                                      capture_output=True, text=True, timeout=TIMEOUT_SUBPROCESS_RUN, env=git_env)
                logger.info(f"[DEPLOYMENT API] GIT CLONE - Gitea/localhost: Initial git clone {git_url} {deployment_path}")
    else:
        if is_github:
            # GitHub: Fresh clone (delete and clone)
            ssh_commands = [
                f"rm -rf {deployment_path}",
                f"mkdir -p {deployment_path}",
                f"cd {os.path.dirname(deployment_path)} && git clone --recurse-submodules {git_url} {os.path.basename(deployment_path)}"
            ]
            ssh_command = f"ssh -o StrictHostKeyChecking=no {ssh_target(LINUX_USER_INSTALLATION, target_server_ip)} '{'; '.join(ssh_commands)}'"
            result = subprocess.run(ssh_command, shell=True, capture_output=True, text=True, timeout=TIMEOUT_SUBPROCESS_RUN)
            logger.info(f"[DEPLOYMENT API] CLONE - GitHub remote: git clone --recurse-submodules {git_url} {deployment_path}")
        else:
            # Gitea/localhost: Use fetch and switch
            ssh_command = f"ssh -o StrictHostKeyChecking=no {ssh_target(LINUX_USER_INSTALLATION, target_server_ip)} 'if [ -d {deployment_path} ]; then cd {deployment_path} && git fetch --all && git remote set-url origin {git_url} && git checkout -B main origin/main; else mkdir -p {deployment_path} && git clone --recurse-submodules {git_url} {deployment_path}; fi'"
            result = subprocess.run(ssh_command, shell=True, capture_output=True, text=True, timeout=TIMEOUT_SUBPROCESS_RUN)
            logger.info(f"[DEPLOYMENT API] CLONE - Gitea/localhost remote: git fetch and switch to {git_url}")
    
    # Handle result
    output_parts = []
    if result.stdout and result.stdout.strip():
        output_parts.append(f"\n{result.stdout}")
    #if result.stderr and result.stderr.strip():
    #    output_parts.append(f"STDERR:\n{result.stderr}")
    #command_output = "\n\n".join(output_parts) if output_parts else "No output"
    
    if result.returncode == 0:
        status = 'cloned'
        
        # Get username for nginx location and swautomorph_url
        user_result = db_manager.execute_query(
            'SELECT username FROM users WHERE id = %s',
            (user_id,), fetch_one=True
        )
        user_name = user_result[0] if user_result else f'user_{user_id}'
        
        # Update nginx configuration after successful clone
        try:
            user_app = db_manager.execute_query(
                'SELECT url FROM user_applications WHERE user_id = %s AND application_id = (SELECT id FROM applications WHERE name = %s)',
                (user_id, app_name), fetch_one=True
            )
            if user_app and user_app[0]:
                insert_location_block(user_name, app_name, user_app[0], user_app[0])
                logger.info(f"Nginx location updated for user {user_name} app {app_name}")
        except Exception as e:
            logger.warning(f"Failed to update nginx after clone: {e}")
        
        # Copy SSL certificates after successful clone
        ssl_env = os.environ.copy()
        ssl_env['USER'] = LINUX_USER_INSTALLATION
        
        if is_local_server:
            ssl_command = f"mkdir -p {deployment_path}/ssl && if [ -f {PROJECT_ROOT}/ssl/fullchain_domain.crt ] && [ -f {PROJECT_ROOT}/ssl/privateKey_domain.key ]; then cp {PROJECT_ROOT}/ssl/fullchain_domain.crt {deployment_path}/ssl/fullchain.pem && cp {PROJECT_ROOT}/ssl/privateKey_domain.key {deployment_path}/ssl/privkey.pem && chmod 600 {deployment_path}/ssl/*.pem; elif command -v certbot > /dev/null 2>&1; then sudo certbot certonly --standalone -d www.{DOMAIN} --email admin@{DOMAIN} --agree-tos --non-interactive --quiet && sudo cp /etc/letsencrypt/live/www.{DOMAIN}/fullchain.pem {deployment_path}/ssl/ && sudo cp /etc/letsencrypt/live/www.{DOMAIN}/privkey.pem {deployment_path}/ssl/ && sudo chown -R {chown_arg(LINUX_USER_INSTALLATION)} {deployment_path}/ssl/ && chmod 600 {deployment_path}/ssl/*.pem; fi"
        else:
            ssl_command = f"ssh -o StrictHostKeyChecking=no {ssh_target(LINUX_USER_INSTALLATION, target_server_ip)} 'mkdir -p {deployment_path}/ssl && if [ -f {PROJECT_ROOT}/ssl/fullchain_domain.crt ] && [ -f {PROJECT_ROOT}/ssl/privateKey_domain.key ]; then cp {PROJECT_ROOT}/ssl/fullchain_domain.crt {deployment_path}/ssl/fullchain.pem && cp {PROJECT_ROOT}/ssl/privateKey_domain.key {deployment_path}/ssl/privkey.pem && chmod 600 {deployment_path}/ssl/*.pem; elif command -v certbot > /dev/null 2>&1; then sudo systemctl stop nginx 2>/dev/null || true && sudo certbot certonly --standalone -d www.{DOMAIN} --email admin@{DOMAIN} --agree-tos --non-interactive --quiet && sudo cp /etc/letsencrypt/live/www.{DOMAIN}/fullchain.pem {deployment_path}/ssl/ && sudo cp /etc/letsencrypt/live/www.{DOMAIN}/privkey.pem {deployment_path}/ssl/ && sudo chown -R {chown_arg(LINUX_USER_INSTALLATION)} {deployment_path}/ssl/ && chmod 600 {deployment_path}/ssl/*.pem; fi'"

        ssl_result = subprocess.run(ssl_command, shell=True, capture_output=True, text=True, env=ssl_env)
        logger.info(f"[DEPLOYMENT API] CLONE - SSL setup result: {ssl_result.returncode}, stdout: {ssl_result.stdout}, stderr: {ssl_result.stderr}")
        
        # Record deployment
        swautomorph_url = f"https://{DOMAIN}/{user_name}/{app_name}"
        
        # Get application_id from database
        app_result = db_manager.execute_query(
            'SELECT id FROM applications WHERE name = %s',
            (app_name,), fetch_one=True
        )
        application_id = app_result[0] if app_result else None
        
        existing_record = db_manager.execute_query(
            'SELECT id FROM deployments WHERE user_id = %s AND application_name = %s AND server_id = %s',
            (user_id, app_name, server_id), fetch_one=True
        )
        
        if existing_record:
            db_manager.execute_query(
                'UPDATE deployments SET status = %s, deployment_path = %s, git_url = %s, gitea_branch_url = %s, swautomorph_url = %s, application_id = %s, updated_at = CURRENT_TIMESTAMP WHERE user_id = %s AND application_name = %s AND server_id = %s',
                (status, deployment_path, git_url, git_url, swautomorph_url, application_id, user_id, app_name, server_id)
            )
        else:
            db_manager.execute_query(
                'INSERT INTO deployments (user_id, application_id, application_name, status, deployment_path, git_url, gitea_branch_url, server_id, swautomorph_url) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)',
                (user_id, application_id, app_name, status, deployment_path, git_url, git_url, server_id, swautomorph_url)
            )
        
        if data.get('stream', False):
            def generate_clone_response():
                yield f"data: {json.dumps({'chunk': f'Clone completed successfully for {app_name}'})}\n\n"
                yield f"data: {json.dumps({'chunk': f'Repository cloned to: {deployment_path}'})}\n\n"
                yield f"data: {json.dumps({'chunk': ssl_result.stdout})}\n\n"
                yield f"data: {json.dumps({'done': True, 'success': True})}\n\n"
            return Response(stream_with_context(generate_clone_response()), mimetype='text/event-stream',
                           headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
    else:
        status = 'failed'
        # test if is_github then display CLONE else SWITCH in the error message
        error_msg = f'Git {"clone" if is_github else "switch"} failed: {result.stderr}'
        logger.error(f"[DEPLOYMENT API] GIT - FAILED - {error_msg}")
        logger.error(f"[DEPLOYMENT API] GIT - CMD = {ssh_command}")
        return jsonify({'error': error_msg, 'logs': ssl_result.stdout}), 400
    
    return jsonify({'message': f'Clone completed for {app_name}', 'status': status, 'logs': ssl_result.stdout}), 202

def _handle_app_action(user_id, app_name, action, data):
    """Handle application lifecycle actions (start, stop, restart, ps, logs)"""
    # Check if deployment exists
    deployment = db_manager.execute_query(
        'SELECT deployment_path FROM deployments WHERE user_id = %s AND application_name = %s AND status NOT IN (%s, %s) ORDER BY updated_at DESC LIMIT 1',
        (user_id, app_name, 'failed', 'error'), fetch_one=True
    )
    
    if not deployment:
        #logger.error(f"[DEPLOYMENT API] {action.upper()} - FAILED - No deployment found for app '{app_name}' for user {user_id}")
        return jsonify({'error': 'Application not deployed. Clone it first.'}), 202
    
    deploy_path = str(deployment[0]) if isinstance(deployment, (list, tuple)) else str(deployment)
    deploy_script = os.path.join(deploy_path, 'deployApp.sh')
    
    if not os.path.exists(deploy_script):
        # if action is PS then display treat the message as a WARNIN else treat it as an ERROR
        if action.upper() == 'PS':
            logger.warning(f"[DEPLOYMENT API] PS - WARNING - deployApp.sh not found at {deploy_script} for user {user_id}")
        else:
            logger.error(f"[DEPLOYMENT API] {action.upper()} - ERROR - deployApp.sh not found at {deploy_script} for user {user_id}")
        return jsonify({'error': f'deployApp.sh not found in {deploy_script}'}), 202
    
    # Get user details
    user_details = db_manager.execute_query(
        'SELECT username, email, first_name, last_name FROM users WHERE id = %s', 
        (user_id,), fetch_one=True
    )
    user_name = f"{user_details[2] or ''} {user_details[3] or ''}" if user_details else 'User'
    user_email = user_details[1] if user_details else 'user@example.com'
    
    # Resolve the configured container runtime ('runc' or 'kata'). It is passed
    # to deployApp.sh both as a trailing positional arg and as the RUNTIME_TYPE
    # env var so per-app scripts can run `docker run --runtime "$RUNTIME_TYPE"`.
    # Scripts that ignore the extra arg/env continue to work unchanged.
    runtime_type = get_runtime_type()
    deploy_env = {**os.environ, 'RUNTIME_TYPE': runtime_type}

    # Execute action
    if data.get('stream', False):
        def generate():
            import re
            ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
            try:
                process = subprocess.Popen(
                    [deploy_script, action, str(session['user_id']), user_name, user_email, runtime_type],
                    cwd=deploy_path, env=deploy_env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1
                )
                for line in iter(process.stdout.readline, ''):
                    if line:
                        clean_line = ansi_escape.sub('', line.rstrip())
                        if clean_line:
                            yield f"data: {json.dumps({'chunk': clean_line})}\n\n"
                process.wait()
                status = 'running' if action.upper() == 'START' else 'STOPPED' if action.upper() == 'STOP' else 'COMPLETED'
                db_manager.execute_query(
                    'UPDATE deployments SET status = %s, updated_at = CURRENT_TIMESTAMP WHERE user_id = %s AND application_name = %s',
                    (status, user_id, app_name)
                )
                if action.upper() in ['START', 'STOP'] and process.returncode == 0:
                    from .billing_routes import record_billing_activity
                    record_billing_activity(user_id, app_name, action)
                yield f"data: {json.dumps({'done': True, 'success': process.returncode == 0})}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
        return Response(stream_with_context(generate()), mimetype='text/event-stream',
                       headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
    else:
        result = subprocess.run([deploy_script, action, str(session['user_id']), user_name, user_email, runtime_type], 
                              cwd=deploy_path, env=deploy_env, capture_output=True, text=True, timeout=TIMEOUT_SUBPROCESS_RUN)
        
        output_parts = []
        if result.stdout and result.stdout.strip():
            output_parts.append(f"STDOUT:\n{result.stdout}")
        if result.stderr and result.stderr.strip():
            output_parts.append(f"STDERR:\n{result.stderr}")
        command_output = "\n\n".join(output_parts) if output_parts else "No output"
        
        status = 'RUNNING' if action.upper() == 'START' else 'STOPPED' if action.upper() == 'STOP' else 'COMPLETED'
        db_manager.execute_query(
            'UPDATE deployments SET status = %s, updated_at = CURRENT_TIMESTAMP WHERE user_id = %s AND application_name = %s',
            (status, session['user_id'], app_name)
        )
        
        if action.upper() in ['START', 'STOP'] and result.returncode == 0:
            from .billing_routes import record_billing_activity
            record_billing_activity(session['user_id'], app_name, action)
        
        return jsonify({
            'message': f'{action.upper()} completed for {app_name}',
            'status': status,
            'logs': command_output
        }), 200

@api_bp.route('/deployments', methods=['GET', 'POST'])
def api_deployments():
    # Log API call
    user_id = session.get('user_id', 'anonymous')
    method = request.method
    remote_ip = request.environ.get('HTTP_X_FORWARDED_FOR', request.remote_addr)
    user_agent = request.headers.get('User-Agent', 'Unknown')
    
    #log_with_timestamp(f"[DEPLOYMENT API] {method} /api/deployments - User: {user_id}, IP: {remote_ip}, UA: {user_agent[:50]}")
    
    if 'user_id' not in session:
        logger.warning(f"[DEPLOYMENT API] FAILED - Authentication required from {remote_ip}")
        return jsonify({'error': 'Authentication required'}), 401
    
    if request.method == 'GET':
        logger.info(f"[DEPLOYMENT API] GET - Fetching deployments for user {user_id}")
        deployments_data = db_manager.execute_query('''SELECT id, application_id, application_name, status, deployment_path, git_url, created_at, updated_at, server_id
            FROM deployments WHERE user_id = %s ORDER BY updated_at DESC
        ''', (session['user_id'],), fetch_all=True)
        
        deployments = [{
            'id': row[0], 'application_id': row[1], 'application_name': row[2], 'status': row[3], 'deployment_path': row[4],
            'git_url': row[5], 'created_at': row[6], 'updated_at': row[7], 'server_id': row[8]
        } for row in deployments_data]
        
        logger.info(f"[DEPLOYMENT API] GET - Returning {len(deployments)} deployments for user {user_id}")
        return jsonify(deployments)
    
    elif request.method == 'POST':
        data = request.get_json()
        action = data.get('action')
        app_name = data.get('application_name')
        git_url = data.get('git_url')
        server_id = data.get('server_id')
        target_user_id = data.get('target_user_id')  # Optional: for admin to deploy for other users
        
        # log_with_timestamp(f"[DEPLOYMENT API] POST - User {user_id} requesting action '{action}' for app '{app_name}'")
        
        if not all([action, app_name]):
            logger.error(f"[DEPLOYMENT API] POST - FAILED - Missing action or app_name for user {user_id}")
            return jsonify({'error': 'Action and application name required'}), 400
        
        # Determine the target user for deployment
        # If target_user_id is provided, verify admin privileges
        if target_user_id:
            admin_user = db_manager.execute_query(
                'SELECT username FROM users WHERE id = %s', 
                (session['user_id'],), fetch_one=True
            )
            if not admin_user or admin_user[0] != 'admin':
                logger.error(f"[DEPLOYMENT API] POST - FAILED - Non-admin user {user_id} tried to deploy for user {target_user_id}")
                return jsonify({'error': 'Admin access required to deploy for other users'}), 403
            
            # Use target user for deployment
            deployment_user_id = target_user_id
            user = db_manager.execute_query(
                'SELECT username FROM users WHERE id = %s', 
                (target_user_id,), fetch_one=True
            )
            if not user:
                return jsonify({'error': f'Target user {target_user_id} not found'}), 404
            username = user[0]
            logger.info(f"[DEPLOYMENT API] POST - Admin {session['user_id']} deploying for user {target_user_id} ({username})")
        else:
            # Use current session user for deployment
            deployment_user_id = session['user_id']
            user = db_manager.execute_query(
                'SELECT username FROM users WHERE id = %s', 
                (session['user_id'],), fetch_one=True
            )
            username = user[0] if user else f'user_{session["user_id"]}'
        
        deployment_path = f'{deployments_prefix(LINUX_USER_INSTALLATION)}{username}/{app_name.lower().replace(" ", "-")}'
        
        try:
            if action == 'clone':
                return _handle_clone_action(deployment_user_id, app_name, git_url, server_id, deployment_path, data)
            elif action.upper() in ['START', 'STOP', 'RESTART', 'PS', 'LOGS']:
                return _handle_app_action(deployment_user_id, app_name, action, data)
            else:
                return jsonify({'error': f'Unknown action: {action}'}), 400
                
        except subprocess.TimeoutExpired:
            logger.error(f"[DEPLOYMENT API] POST - TIMEOUT - Action '{action}' timed out for app '{app_name}' by user {user_id}")
            return jsonify({'error': 'Operation timed out'}), 408
        except Exception as e:
            logger.error(f"[DEPLOYMENT API] POST - ERROR - Action '{action}' failed for app '{app_name}' by user {user_id}: {str(e)}")
            return jsonify({'error': str(e)}), 500

@api_bp.route('/deployments/<int:deployment_id>/logs')
def api_deployment_logs(deployment_id):
    # Log API call
    user_id = session.get('user_id', 'anonymous')
    remote_ip = request.environ.get('HTTP_X_FORWARDED_FOR', request.remote_addr)
    
    logger.info(f"[DEPLOYMENT LOGS] GET /api/deployments/{deployment_id}/logs - User: {user_id}, IP: {remote_ip}")
    
    if 'user_id' not in session:
        logger.warning(f"[DEPLOYMENT LOGS] FAILED - Authentication required from {remote_ip}")
        return jsonify({'error': 'Authentication required'}), 401
    
    deployment = db_manager.execute_query('''SELECT deployment_path FROM deployments 
        WHERE id = %s AND user_id = %s
    ''', (deployment_id, session['user_id']), fetch_one=True)
    
    if not deployment:
        logger.warning(f"[DEPLOYMENT LOGS] FAILED - Deployment {deployment_id} not found for user {user_id}")
        return jsonify({'error': 'Deployment not found'}), 404
    
    # Extract deployment path safely
    deploy_path = str(deployment[0] if isinstance(deployment, (list, tuple)) else deployment)
    
    # Validate deployment path to prevent path traversal
    if not deploy_path or not is_under_deployments(LINUX_USER_INSTALLATION, deploy_path):
        logger.warning(f"[DEPLOYMENT LOGS] SECURITY - Invalid deployment path: {deploy_path} for user {user_id}")
        return jsonify({'error': 'Invalid deployment path'}), 400
    
    log_file = os.path.join(deploy_path, 'deployment.log')
    
    # Additional security check for log file path
    if not is_under_deployments(LINUX_USER_INSTALLATION, log_file):
        logger.warning(f"[DEPLOYMENT LOGS] SECURITY - Invalid log file path: {log_file} for user {user_id}")
        return jsonify({'error': 'Invalid log file path'}), 400
    
    try:
        if os.path.exists(log_file):
            with open(log_file, 'r') as f:
                logs = f.read()
        else:
            logs = 'No logs available'
        
        logger.info(f"[DEPLOYMENT LOGS] SUCCESS - Returned logs for deployment {deployment_id} to user {user_id}")
        return jsonify({'logs': logs})
    except Exception as e:
        logger.error(f"[DEPLOYMENT LOGS] ERROR - Failed to read logs for deployment {deployment_id} by user {user_id}: {str(e)}")
        return jsonify({'error': f'Failed to read logs: {str(e)}'}), 500

@api_bp.route('/nginx/sync', methods=['POST'])
def api_nginx_sync():
    """Sync all nginx locations from database"""
    if 'user_id' not in session:
        return jsonify({'error': 'Authentication required'}), 401
    
    user = db_manager.execute_query(
        'SELECT username FROM users WHERE id = %s', 
        (session['user_id'],), fetch_one=True
    )
    
    if not user or user[0] != 'admin':
        return jsonify({'error': 'Admin access required'}), 403
    
    try:
        if sync_all_locations(db_manager):
            return jsonify({'message': 'Nginx locations synced successfully'})
        else:
            return jsonify({'error': 'Failed to sync nginx locations'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_bp.route('/replication/queue', methods=['GET'])
def api_replication_queue():
    """Get replication sync queue status"""
    if 'user_id' not in session:
        return jsonify({'error': 'Authentication required'}), 401
    
    user = db_manager.execute_query(
        'SELECT username FROM users WHERE id = %s', 
        (session['user_id'],), fetch_one=True
    )
    
    if not user or user[0] != 'admin':
        return jsonify({'error': 'Admin access required'}), 403
    
    try:
        from src.replication_manager import sync_queue, pending_events, pending_events_lock
        
        # Get current queue size (pending events)
        queue_size = sync_queue.qsize()
        
        # Get pending events from dictionary (thread-safe)
        with pending_events_lock:
            events = list(pending_events.values())[-10:]  # Last 10 pending events
        
        return jsonify({
            'queue_size': queue_size,
            'events': events
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_bp.route('/configuration', methods=['GET', 'POST'])
def api_configuration():
    """Configuration parameters management endpoint"""
    if 'user_id' not in session:
        return jsonify({'error': 'Authentication required'}), 401
    
    # Check if user is admin
    user = db_manager.execute_query(
        'SELECT username FROM users WHERE id = %s', 
        (session['user_id'],), fetch_one=True
    )
    
    if not user or user[0] != 'admin':
        return jsonify({'error': 'Admin access required'}), 403
    
    if request.method == 'GET':
        try:
            configs = db_manager.execute_query(
                'SELECT param_id, parent, key, value FROM configuration ORDER BY param_id',
                fetch_all=True
            )
            
            config_list = [{
                'param_id': row[0],
                'parent': row[1],
                'key': row[2],
                'value': row[3]
            } for row in configs]
            
            return jsonify(config_list)
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    elif request.method == 'POST':
        try:
            data = request.get_json()
            if not data or not isinstance(data, dict):
                return jsonify({'error': 'Invalid JSON data'}), 400
            
            parent = data.get('parent')
            key = data.get('key')
            value = data.get('value')
            
            if not key or not value:
                return jsonify({'error': 'Key and value are required'}), 400
            
            db_manager.execute_query(
                'INSERT INTO configuration (parent, key, value) VALUES (%s, %s, %s)',
                (parent, key, value)
            )
            
            return jsonify({'message': 'Configuration parameter added successfully'}), 201
        except Exception as e:
            return jsonify({'error': str(e)}), 500

@api_bp.route('/configuration/<int:param_id>', methods=['PUT', 'DELETE'])
def api_configuration_actions(param_id):
    """Configuration parameter update/delete endpoint"""
    if 'user_id' not in session:
        return jsonify({'error': 'Authentication required'}), 401
    
    # Check if user is admin
    user = db_manager.execute_query(
        'SELECT username FROM users WHERE id = %s', 
        (session['user_id'],), fetch_one=True
    )
    
    if not user or user[0] != 'admin':
        return jsonify({'error': 'Admin access required'}), 403
    
    if request.method == 'PUT':
        try:
            data = request.get_json()
            if not data or not isinstance(data, dict):
                return jsonify({'error': 'Invalid JSON data'}), 400
            
            parent = data.get('parent')
            key = data.get('key')
            value = data.get('value')
            
            if not key or not value:
                return jsonify({'error': 'Key and value are required'}), 400
            
            db_manager.execute_query(
                'UPDATE configuration SET parent = %s, key = %s, value = %s WHERE param_id = %s',
                (parent, key, value, param_id)
            )
            
            return jsonify({'message': 'Configuration parameter updated successfully'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    elif request.method == 'DELETE':
        try:
            db_manager.execute_query('DELETE FROM configuration WHERE param_id = %s', (param_id,))
            return jsonify({'message': 'Configuration parameter deleted successfully'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

@api_bp.route('/deployments/all', methods=['GET'])
def api_deployments_all():
    """Get all deployments (admin only)"""
    user_id = session.get('user_id', 'anonymous')
    remote_ip = request.environ.get('HTTP_X_FORWARDED_FOR', request.remote_addr)
    
    logger.info(f"[DEPLOYMENTS_ALL] GET request from user {user_id}, IP: {remote_ip}")
    
    if 'user_id' not in session:
        logger.warning(f"[DEPLOYMENTS_ALL] Authentication required from {remote_ip}")
        return jsonify({'error': 'Authentication required'}), 401
    
    user = db_manager.execute_query(
        'SELECT username FROM users WHERE id = %s', 
        (session['user_id'],), fetch_one=True
    )
    
    if not user or user[0] != 'admin':
        logger.warning(f"[DEPLOYMENTS_ALL] Admin access denied for user {user_id}")
        return jsonify({'error': 'Admin access required'}), 403
    
    try:
        deployments_data = db_manager.execute_query('''SELECT id, user_id, application_id, application_name, status, deployment_path, 
                   git_url, server_id, swautomorph_url, modification_history, backups_history, created_at, updated_at
            FROM deployments ORDER BY updated_at DESC
        ''', fetch_all=True)
        
        deployments = [{
            'id': row[0], 'user_id': row[1], 'application_id': row[2], 'application_name': row[3],
            'status': row[4], 'deployment_path': row[5], 'git_url': row[6], 'server_id': row[7],
            'swautomorph_url': row[8], 'modification_history': row[9], 'backups_history': row[10],
            'created_at': row[11], 'updated_at': row[12]
        } for row in deployments_data]
        
        logger.info(f"[DEPLOYMENTS_ALL] Returning {len(deployments)} deployments to user {user_id}")
        return jsonify(deployments)
    except Exception as e:
        logger.error(f"[DEPLOYMENTS_ALL] Error for user {user_id}: {str(e)}")
        return jsonify({'error': str(e)}), 500

@api_bp.route('/deployments/<int:deployment_id>', methods=['DELETE'])
def api_deployment_delete(deployment_id):
    """Delete a deployment (admin only)"""
    user_id = session.get('user_id', 'anonymous')
    remote_ip = request.environ.get('HTTP_X_FORWARDED_FOR', request.remote_addr)
    
    logger.info(f"[DEPLOYMENT_DELETE] DELETE request for deployment {deployment_id} from user {user_id}, IP: {remote_ip}")
    
    if 'user_id' not in session:
        logger.warning(f"[DEPLOYMENT_DELETE] Authentication required from {remote_ip}")
        return jsonify({'error': 'Authentication required'}), 401
    
    user = db_manager.execute_query(
        'SELECT username FROM users WHERE id = %s', 
        (session['user_id'],), fetch_one=True
    )
    
    if not user or user[0] != 'admin':
        logger.warning(f"[DEPLOYMENT_DELETE] Admin access denied for user {user_id}")
        return jsonify({'error': 'Admin access required'}), 403
    
    try:
        # Check if deployment exists
        deployment = db_manager.execute_query(
            'SELECT application_name FROM deployments WHERE id = %s',
            (deployment_id,), fetch_one=True
        )
        
        if not deployment:
            logger.warning(f"[DEPLOYMENT_DELETE] Deployment {deployment_id} not found")
            return jsonify({'error': 'Deployment not found'}), 404
        
        # Delete the deployment
        db_manager.execute_query('DELETE FROM deployments WHERE id = %s', (deployment_id,))
        
        logger.info(f"[DEPLOYMENT_DELETE] Successfully deleted deployment {deployment_id} ({deployment[0]}) by user {user_id}")
        return jsonify({'message': f'Deployment deleted successfully'}), 200
        
    except Exception as e:
        logger.error(f"[DEPLOYMENT_DELETE] Error deleting deployment {deployment_id}: {str(e)}")
        return jsonify({'error': str(e)}), 500

@api_bp.route('/nginx/update-deployment', methods=['POST'])
def api_nginx_update_deployment():
    """Update nginx configuration for a specific deployment"""
    session_user_id = session.get('user_id', 'anonymous')
    remote_ip = request.environ.get('HTTP_X_FORWARDED_FOR', request.remote_addr)
    
    logger.info(f"[NGINX_UPDATE] POST request from user {session_user_id}, IP: {remote_ip}")
    
    if 'user_id' not in session:
        logger.warning(f"[NGINX_UPDATE] Authentication required from {remote_ip}")
        return jsonify({'error': 'Authentication required'}), 401
    
    user = db_manager.execute_query(
        'SELECT username FROM users WHERE id = %s', 
        (session['user_id'],), fetch_one=True
    )
    
    if not user or user[0] != 'admin':
        logger.warning(f"[NGINX_UPDATE] Admin access denied for user {session_user_id}")
        return jsonify({'error': 'Admin access required'}), 403
    
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        app_name = data.get('app_name')
        deployment_url = data.get('deployment_url')
        user_appli_url = data.get('user_appli_url')

        user_name = db_manager.execute_query(
            'SELECT username FROM users WHERE id = %s', 
            (user_id,), fetch_one=True
        )

        logger.info(f"[NGINX_UPDATE] Request for user_name={user_name}, app={app_name}, url={deployment_url}")
        
        if not all([user_name, app_name, deployment_url]):
            logger.error(f"[NGINX_UPDATE] Missing parameters: user_name={user_name}, app={app_name}, url={deployment_url}")
            return jsonify({'error': 'user_name, app_name, and deployment_url are required'}), 400
        
        # Check if nginx location already exists and update/insert
        if insert_location_block(user_name, app_name, deployment_url, user_appli_url):
            logger.info(f"[NGINX_UPDATE] SUCCESS - Nginx updated for user {user_name}, app {app_name}")
            return jsonify({'message': f'Nginx configuration updated for {app_name}'})
        else:
            logger.error(f"[NGINX_UPDATE] FAILED - Could not update nginx for user {user_name}, app {app_name}")
            return jsonify({'error': 'Failed to update nginx configuration'}), 500
    except Exception as e:
        logger.error(f"[NGINX_UPDATE] Exception for user {session_user_id}: {str(e)}")
        return jsonify({'error': str(e)}), 500

@api_bp.route('/deployments/<app_name>/gitea', methods=['GET'])
def api_deployment_gitea(app_name):
    """Get Gitea branch info and modification history for application"""
    if 'user_id' not in session:
        return jsonify({'error': 'Authentication required'}), 401
    
    try:
        deployment = db_manager.execute_query(
            'SELECT gitea_branch_url, modification_history FROM deployments WHERE user_id = %s AND application_name = %s ORDER BY updated_at DESC LIMIT 1',
            (session['user_id'], app_name), fetch_one=True
        )
        
        if not deployment:
            return jsonify({'gitea_branch_url': None, 'modification_history': []})
        
        return jsonify({
            'gitea_branch_url': deployment[0],
            'modification_history': deployment[1] if deployment[1] else []
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_bp.route('/deployments/<app_name>/gitea/branch', methods=['POST'])
def api_deployment_gitea_branch(app_name):
    """Update Gitea branch for application deployment"""
    if 'user_id' not in session:
        return jsonify({'error': 'Authentication required'}), 401
    
    try:
        data = request.get_json()
        branch_url = data.get('branch_url')
        
        if not branch_url:
            return jsonify({'error': 'Branch URL required'}), 400
        
        db_manager.execute_query(
            'UPDATE deployments SET gitea_branch_url = %s, updated_at = CURRENT_TIMESTAMP WHERE user_id = %s AND application_name = %s',
            (branch_url, session['user_id'], app_name)
        )
        
        return jsonify({'message': 'Gitea branch updated successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_bp.route('/deployments/<int:deployment_id>/backup', methods=['POST'])
def api_deployment_add_backup(deployment_id):
    """Add a backup entry to deployment's backups_history"""
    user_id = session.get('user_id', 'anonymous')
    remote_ip = request.environ.get('HTTP_X_FORWARDED_FOR', request.remote_addr)
    
    logger.info(f"[DEPLOYMENT_BACKUP] POST request for deployment {deployment_id} from user {user_id}, IP: {remote_ip}")
    
    if 'user_id' not in session:
        logger.warning(f"[DEPLOYMENT_BACKUP] Authentication required from {remote_ip}")
        return jsonify({'error': 'Authentication required'}), 401
    
    try:
        data = request.get_json()
        backup_file = data.get('backup_file')
        s3_location = data.get('s3_location')
        backup_size = data.get('backup_size')
        backup_date = data.get('backup_date')
        server_ip = data.get('server_ip')
        
        if not backup_file or not s3_location:
            return jsonify({'error': 'backup_file and s3_location are required'}), 400
        
        # Verify deployment belongs to user or user is admin
        deployment = db_manager.execute_query(
            'SELECT user_id FROM deployments WHERE id = %s',
            (deployment_id,), fetch_one=True
        )
        
        if not deployment:
            return jsonify({'error': 'Deployment not found'}), 404
        
        user = db_manager.execute_query(
            'SELECT username FROM users WHERE id = %s',
            (session['user_id'],), fetch_one=True
        )
        
        if deployment[0] != session['user_id'] and (not user or user[0] != 'admin'):
            logger.warning(f"[DEPLOYMENT_BACKUP] Access denied for user {user_id} to deployment {deployment_id}")
            return jsonify({'error': 'Access denied'}), 403
        
        # Create backup entry
        backup_entry = {
            'backup_file': backup_file,
            's3_location': s3_location,
            'backup_size': backup_size,
            'backup_date': backup_date or datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'server_ip': server_ip,
            'created_by': user_id
        }
        
        # Append to backups_history using PostgreSQL JSONB operations
        db_manager.execute_query('''
            UPDATE deployments 
            SET backups_history = COALESCE(backups_history, '[]'::jsonb) || %s::jsonb,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        ''', (json.dumps(backup_entry), deployment_id))
        
        logger.info(f"[DEPLOYMENT_BACKUP] Added backup entry to deployment {deployment_id} by user {user_id}")
        return jsonify({'message': 'Backup entry added successfully', 'backup_entry': backup_entry})
    
    except Exception as e:
        logger.error(f"[DEPLOYMENT_BACKUP] Error for deployment {deployment_id} by user {user_id}: {str(e)}")
        return jsonify({'error': str(e)}), 500

@api_bp.route('/deployments/<int:deployment_id>/backups', methods=['GET'])
def api_deployment_get_backups(deployment_id):
    """Get backups history for a deployment"""
    user_id = session.get('user_id', 'anonymous')
    remote_ip = request.environ.get('HTTP_X_FORWARDED_FOR', request.remote_addr)
    
    logger.info(f"[DEPLOYMENT_BACKUPS] GET request for deployment {deployment_id} from user {user_id}, IP: {remote_ip}")
    
    if 'user_id' not in session:
        logger.warning(f"[DEPLOYMENT_BACKUPS] Authentication required from {remote_ip}")
        return jsonify({'error': 'Authentication required'}), 401
    
    try:
        # Verify deployment belongs to user or user is admin
        deployment = db_manager.execute_query(
            'SELECT user_id, backups_history FROM deployments WHERE id = %s',
            (deployment_id,), fetch_one=True
        )
        
        if not deployment:
            return jsonify({'error': 'Deployment not found'}), 404
        
        user = db_manager.execute_query(
            'SELECT username FROM users WHERE id = %s',
            (session['user_id'],), fetch_one=True
        )
        
        if deployment[0] != session['user_id'] and (not user or user[0] != 'admin'):
            logger.warning(f"[DEPLOYMENT_BACKUPS] Access denied for user {user_id} to deployment {deployment_id}")
            return jsonify({'error': 'Access denied'}), 403
        
        backups_history = deployment[1] if deployment[1] else []
        
        logger.info(f"[DEPLOYMENT_BACKUPS] Returning {len(backups_history) if isinstance(backups_history, list) else 0} backups for deployment {deployment_id}")
        return jsonify({'backups_history': backups_history})
    
    except Exception as e:
        logger.error(f"[DEPLOYMENT_BACKUPS] Error for deployment {deployment_id} by user {user_id}: {str(e)}")
        return jsonify({'error': str(e)}), 500