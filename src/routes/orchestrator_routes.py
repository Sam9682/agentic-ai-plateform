"""API routes for App Orchestrator"""
from flask import Blueprint, request, jsonify, session
from ..database_postgres import db_manager
import json
import subprocess
import os
import socket
import logging
from .. import config_postgres

# Configure logging for API activities
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# File handler
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
log_file = os.path.join(PROJECT_ROOT, 'logs', 'orchestrator_routes.log')
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

orchestrator_bp = Blueprint('orchestrator', __name__, url_prefix='/api/orchestrator')

def require_auth():
    """Check if user is authenticated"""
    if 'user_id' not in session:
        return False
    return True

def require_admin():
    """Check if user is admin"""
    if not require_auth():
        return False
    
    user = db_manager.execute_query(
        'SELECT username FROM users WHERE id = ?', 
        (session['user_id'],), fetch_one=True
    )
    
    return user and user[0] == 'admin'

@orchestrator_bp.route('/user-applications', methods=['GET'])
def get_user_applications():
    """Get applications assigned to current user"""
    if not require_auth():
        return jsonify({'error': 'Authentication required'}), 401
    
    try:
        user_id = session['user_id']
        with db_manager.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT DISTINCT a.name
                FROM applications a
                JOIN user_applications ua ON a.id = ua.application_id
                WHERE ua.user_id = %s
                ORDER BY a.name
            ''', (user_id,))
            apps = [{'name': row[0]} for row in cursor.fetchall()]
        return jsonify(apps)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@orchestrator_bp.route('/git-urls', methods=['GET'])
def get_git_urls():
    """Get all git URLs from deployments table"""
    if not require_auth():
        return jsonify({'error': 'Authentication required'}), 401
    
    try:
        user_id = session['user_id']
        urls = set()
        
        with db_manager.get_db_connection() as conn:
            cursor = conn.cursor()
            # Get gitea_branch_url from deployments
            cursor.execute('''
                SELECT DISTINCT gitea_branch_url
                FROM deployments
                WHERE user_id = %s AND gitea_branch_url IS NOT NULL
            ''', (user_id,))
            for row in cursor.fetchall():
                if row[0]:
                    urls.add(row[0])
            
            # Get modification_history from deployments
            cursor.execute('''
                SELECT modification_history
                FROM deployments
                WHERE user_id = %s AND modification_history IS NOT NULL
            ''', (user_id,))
            for row in cursor.fetchall():
                if row[0]:
                    try:
                        history = json.loads(row[0]) if isinstance(row[0], str) else row[0]
                        if isinstance(history, list):
                            for entry in history:
                                if isinstance(entry, dict) and 'gitea_url' in entry:
                                    urls.add(entry['gitea_url'])
                    except:
                        pass
        
        return jsonify(sorted(list(urls)))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@orchestrator_bp.route('/services', methods=['GET'])
def list_services():
    """List all services and their status"""
    if not require_auth():
        return jsonify({'error': 'Authentication required'}), 401
    
    try:
        from ..orchestrator import orchestrator
        user_id = session.get('user_id')
        services = orchestrator.get_service_status(user_id=user_id)
        return jsonify(services)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@orchestrator_bp.route('/services/<service_name>', methods=['GET'])
def get_service(service_name):
    """Get specific service status"""
    if not require_auth():
        return jsonify({'error': 'Authentication required'}), 401
    
    try:
        from ..orchestrator import orchestrator
        user_id = session.get('user_id')
        services = orchestrator.get_service_status(service_name, user_id)
        if not services:
            return jsonify({'error': 'Service not found'}), 404
        return jsonify(services[0])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@orchestrator_bp.route('/services', methods=['POST'])
def create_service():
    """Create a new service"""
    if not require_admin():
        return jsonify({'error': 'Admin access required'}), 403
    
    try:
        from ..orchestrator import orchestrator
        data = request.get_json()
        logger.info(f"Received service creation request: {data}")
        
        # Validate required fields
        required_fields = ['name', 'image']
        for field in required_fields:
            if field not in data:
                logger.error(f"Missing required field: {field}")
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        # Extract parameters
        name = data['name']
        image = data['image']  # This is now git_url
        user_id = session['user_id']
        desired_replicas = data.get('desired_replicas', 1)
        ports = data.get('ports', {})
        environment = data.get('environment', {})
        volumes = data.get('volumes', [])
        health_check_path = data.get('health_check_path', '/health')
        
        logger.info(f"Creating service '{name}' for user_id={user_id}, replicas={desired_replicas}")
        
        # Create service in database
        orchestrator.create_service(
            name=name,
            image=image,
            user_id=user_id,
            desired_replicas=desired_replicas,
            ports=ports,
            environment=environment,
            volumes=volumes,
            health_check_path=health_check_path
        )
        
        logger.info(f"Service '{name}' created in database")
        
        # Get user info
        with db_manager.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT username FROM users WHERE id = %s', (user_id,))
            username = cursor.fetchone()[0]
            logger.info(f"Username: {username}")
            
            # Get server assignment
            cursor.execute('''
                SELECT s.server_ip, s.id
                FROM servers s
                LEFT JOIN instances i ON s.id = i.server_id AND i.status = 'running'
                WHERE s.server_status IN ('STAND_BY', 'ACTIVE')
                  AND s.server_capacity_appli_max IS NOT NULL
                GROUP BY s.id, s.server_capacity_appli_max
                HAVING COUNT(i.id) < s.server_capacity_appli_max
                ORDER BY COUNT(i.id) ASC
                LIMIT 1
            ''')
            server_result = cursor.fetchone()
            
            if not server_result:
                logger.error("No available server found")
                return jsonify({'error': 'No available server'}), 500
            
            server_ip, server_id = server_result
            logger.info(f"Selected server: {server_ip} (id={server_id})")
        
        # Deploy application using deployApp.sh
        try:
            app_dir = f'/home/{config_postgres.LINUX_USER_INSTALLATION}/deployments/{username}/{name.lower().replace(" ", "-")}'
            deploy_script = f'{app_dir}/deployApp.sh'
            
            logger.info(f"App directory: {app_dir}")
            logger.info(f"Deploy script: {deploy_script}")
            
            # SSH command with StrictHostKeyChecking disabled
            ssh_cmd = [
                'ssh',
                '-o', 'StrictHostKeyChecking=no',
                '-o', 'UserKnownHostsFile=/dev/null',
                f'{config_postgres.LINUX_USER_INSTALLATION}@{server_ip}',
                f'cd {app_dir} && {deploy_script} start {user_id} {username}'
            ]
            
            logger.info(f"Executing SSH command: {' '.join(ssh_cmd)}")
            
            # Execute deployment
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                timeout=300
            )
            
            logger.info(f"SSH command return code: {result.returncode}")
            logger.info(f"SSH stdout: {result.stdout}")
            if result.stderr:
                logger.warning(f"SSH stderr: {result.stderr}")
            
            if result.returncode != 0:
                logger.error(f"Deployment failed for service '{name}'")
                return jsonify({
                    'message': f'Service {name} created but deployment failed',
                    'error': result.stderr
                }), 500
            
            logger.info(f"Service '{name}' deployed successfully")
            
            # Create instance record after successful deployment
            try:
                with db_manager.get_db_connection() as conn:
                    cursor = conn.cursor()
                    
                    # Find available port for the instance
                    cursor.execute('''
                        SELECT port FROM instances 
                        WHERE server_id = %s AND status = 'running' AND port IS NOT NULL
                        ORDER BY port
                    ''', (server_id,))
                    used_ports = {row[0] for row in cursor.fetchall() if row[0]}
                    port = 8000
                    while port in used_ports:
                        port += 1
                    
                    # Create instance record for each desired replica
                    for i in range(desired_replicas):
                        instance_id = f"{name}-replica-{i+1}"
                        cursor.execute('''
                            INSERT INTO instances 
                            (service_name, instance_id, server_id, status, port, health_status)
                            VALUES (%s, %s, %s, 'running', %s, 'healthy')
                        ''', (name, instance_id, server_id, port + i))
                    
                    conn.commit()
                    logger.info(f"Created {desired_replicas} instance record(s) for service '{name}'")
                    
                    # Record billing activity for START action
                    from .billing_routes import record_billing_activity
                    record_billing_activity(user_id, name, 'START')
                    logger.info(f"Recorded billing activity for service '{name}' START")
                    
            except Exception as e:
                logger.error(f"Failed to create instance records: {str(e)}")
            
        except Exception as e:
            logger.error(f"Exception during deployment: {str(e)}")
            return jsonify({
                'message': f'Service {name} created but deployment failed',
                'error': str(e)
            }), 500
        
        return jsonify({'message': f'Service {name} created and deployed successfully'}), 201
        
    except Exception as e:
        logger.error(f"Exception in create_service: {str(e)}")
        return jsonify({'error': str(e)}), 500

@orchestrator_bp.route('/services/<service_name>', methods=['PUT'])
def update_service(service_name):
    """Update service configuration"""
    if not require_admin():
        return jsonify({'error': 'Admin access required'}), 403
    
    try:
        from ..orchestrator import orchestrator
        data = request.get_json()
        
        # For now, only support scaling
        if 'desired_replicas' in data:
            replicas = data['desired_replicas']
            if not isinstance(replicas, int) or replicas < 0:
                return jsonify({'error': 'desired_replicas must be a non-negative integer'}), 400
            
            orchestrator.scale_service(service_name, replicas)
            return jsonify({'message': f'Service {service_name} scaled to {replicas} replicas'})
        
        return jsonify({'error': 'No valid update parameters provided'}), 400
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@orchestrator_bp.route('/services/<service_name>/scale', methods=['POST'])
def scale_service(service_name):
    """Scale a service"""
    if not require_admin():
        return jsonify({'error': 'Admin access required'}), 403
    
    try:
        from ..orchestrator import orchestrator
        data = request.get_json()
        replicas = data.get('replicas')
        user_id = session['user_id']
        
        if replicas is None:
            return jsonify({'error': 'Missing replicas parameter'}), 400
        
        if not isinstance(replicas, int) or replicas < 0:
            return jsonify({'error': 'replicas must be a non-negative integer'}), 400
        
        orchestrator.scale_service(service_name, user_id, replicas)
        return jsonify({'message': f'Service {service_name} scaled to {replicas} replicas'})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@orchestrator_bp.route('/services/<service_name>', methods=['DELETE'])
def delete_service(service_name):
    """Delete a service and all its instances"""
    if not require_admin():
        return jsonify({'error': 'Admin access required'}), 403
    
    try:
        from ..orchestrator import orchestrator
        user_id = session['user_id']
        orchestrator.delete_service(service_name, user_id)
        return jsonify({'message': f'Service {service_name} deleted successfully'})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@orchestrator_bp.route('/health-check', methods=['POST'])
def trigger_health_check():
    """Manually trigger health check for all instances"""
    if not require_admin():
        return jsonify({'error': 'Admin access required'}), 403
    
    try:
        from ..orchestrator import orchestrator
        orchestrator.health_check_instances()
        return jsonify({'message': 'Health check completed'})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@orchestrator_bp.route('/nginx/config', methods=['GET'])
def get_nginx_config():
    """Get generated Nginx upstream configuration"""
    if not require_admin():
        return jsonify({'error': 'Admin access required'}), 403
    
    try:
        from ..orchestrator import orchestrator
        config = orchestrator.generate_nginx_config()
        return jsonify({'config': config})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@orchestrator_bp.route('/nginx/reload', methods=['POST'])
def reload_nginx():
    """Reload Nginx configuration"""
    if not require_admin():
        return jsonify({'error': 'Admin access required'}), 403
    
    try:
        from ..orchestrator import orchestrator
        success = orchestrator.reload_nginx()
        if success:
            return jsonify({'message': 'Nginx reloaded successfully'})
        else:
            return jsonify({'error': 'Failed to reload Nginx'}), 500
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@orchestrator_bp.route('/reconcile', methods=['POST'])
def trigger_reconciliation():
    """Manually trigger reconciliation for all services"""
    if not require_admin():
        return jsonify({'error': 'Admin access required'}), 403
    
    try:
        from ..orchestrator import orchestrator
        
        with db_manager.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT name, user_id FROM services')
            services = cursor.fetchall()
            
            for service in services:
                orchestrator._reconcile_service(service[0], service[1])
        
        return jsonify({'message': 'Reconciliation completed'})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@orchestrator_bp.route('/status', methods=['GET'])
def orchestrator_status():
    """Get orchestrator status and statistics"""
    if not require_auth():
        return jsonify({'error': 'Authentication required'}), 401
    
    try:
        with db_manager.get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Count services
            cursor.execute('SELECT COUNT(*) FROM services')
            total_services = cursor.fetchone()[0]
            
            # Count instances by status
            cursor.execute('''
                SELECT status, COUNT(*) 
                FROM instances 
                GROUP BY status
            ''')
            instance_stats = dict(cursor.fetchall())
            
            # Count healthy vs unhealthy instances
            cursor.execute('''
                SELECT health_status, COUNT(*) 
                FROM instances 
                WHERE status = 'running'
                GROUP BY health_status
            ''')
            health_stats = dict(cursor.fetchall())
            
            # Server utilization
            cursor.execute('''
                SELECT s.server_name, s.server_capacity_appli_max, COUNT(i.id) as current_instances
                FROM servers s
                LEFT JOIN instances i ON s.id = i.server_id AND i.status = 'running'
                GROUP BY s.id, s.server_name, s.server_capacity_appli_max
            ''')
            server_stats = []
            for row in cursor.fetchall():
                server_stats.append({
                    'name': row[0],
                    'capacity': row[1],
                    'current_instances': row[2],
                    'utilization': round((row[2] / row[1]) * 100, 2) if row[1] > 0 else 0
                })
        
        from ..orchestrator import orchestrator
        return jsonify({
            'total_services': total_services,
            'instance_stats': instance_stats,
            'health_stats': health_stats,
            'server_stats': server_stats,
            'reconciliation_running': orchestrator._running
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@orchestrator_bp.route('/services/multi-user-deploy', methods=['POST'])
def multi_user_deploy():
    """Deploy a service by creating multiple user environments on the current server.
    
    Steps:
    1. Create N replica users named '{APP_NAME}{i}' for i in 1..replicas
    2. Assign the application to each replica user (user_applications)
    3. Clone the application into each user's deployment folder
    4. Start the Docker container in each user's environment
    """
    if not require_admin():
        return jsonify({'error': 'Admin access required'}), 403
    
    try:
        data = request.get_json()
        app_name = data.get('name')
        git_url = data.get('image')  # 'image' field holds the git_url in this form
        desired_replicas = data.get('desired_replicas', 1)
        environment = data.get('environment', {})
        health_check_path = data.get('health_check_path', '/health')
        
        if not app_name:
            return jsonify({'error': 'Application name is required'}), 400
        if not git_url:
            return jsonify({'error': 'Git URL is required'}), 400
        if desired_replicas < 1 or desired_replicas > 10:
            return jsonify({'error': 'Replicas must be between 1 and 10'}), 400
        
        logger.info(f"[MULTI-USER DEPLOY] Starting multi-user deployment for '{app_name}' with {desired_replicas} replicas")
        
        # Get application info
        app_result = db_manager.execute_query(
            'SELECT id, name FROM applications WHERE name = %s',
            (app_name,), fetch_one=True
        )
        if not app_result:
            return jsonify({'error': f'Application "{app_name}" not found'}), 404
        
        application_id = app_result[0]
        
        # Get the current server (first available or local)
        server_result = db_manager.execute_query('''
            SELECT id, server_ip FROM servers 
            WHERE server_status IN ('STAND_BY', 'ACTIVE')
            ORDER BY id ASC LIMIT 1
        ''', fetch_one=True)
        
        if not server_result:
            return jsonify({'error': 'No available server found'}), 500
        
        server_id = server_result[0]
        server_ip = server_result[1]
        
        DOMAIN = config_postgres.DOMAIN
        from ..database_postgres import calculate_app_ports, APP_PORT_COLUMNS_SQL, APP_PORT_PLACEHOLDERS_SQL
        from werkzeug.security import generate_password_hash
        
        created_users = []
        
        # Sanitize app name for username generation (lowercase, no spaces)
        app_name_sanitized = app_name.lower().replace(' ', '-').replace('_', '-')
        
        for i in range(1, desired_replicas + 1):
            replica_username = f"{app_name_sanitized}{i}"
            replica_email = f"{replica_username}@{DOMAIN}"
            
            logger.info(f"[MULTI-USER DEPLOY] Processing replica user '{replica_username}' ({i}/{desired_replicas})")
            
            user_status = 'created'
            
            try:
                # Step 1: Create the replica user (if not exists)
                existing_user = db_manager.execute_query(
                    'SELECT id FROM users WHERE username = %s',
                    (replica_username,), fetch_one=True
                )
                
                if existing_user:
                    replica_user_id = existing_user[0]
                    logger.info(f"[MULTI-USER DEPLOY] User '{replica_username}' already exists (id={replica_user_id})")
                    user_status = 'existing'
                else:
                    # Create user with a generated password (not meant for login, just for system use)
                    password_hash = generate_password_hash(f"replica_{replica_username}_auto")
                    replica_user_id = db_manager.execute_query(
                        '''INSERT INTO users (username, email, password_hash, first_name, last_name, suspended)
                           VALUES (%s, %s, %s, %s, %s, %s) RETURNING id''',
                        (replica_username, replica_email, password_hash, app_name, f'Replica {i}', False),
                        fetch_one=True
                    )
                    if replica_user_id:
                        replica_user_id = replica_user_id[0]
                    else:
                        logger.error(f"[MULTI-USER DEPLOY] Failed to create user '{replica_username}'")
                        created_users.append({'username': replica_username, 'status': 'failed_create'})
                        continue
                    
                    logger.info(f"[MULTI-USER DEPLOY] Created user '{replica_username}' (id={replica_user_id})")
                
                # Step 2: Assign application to the replica user (user_applications)
                existing_assignment = db_manager.execute_query(
                    'SELECT id FROM user_applications WHERE user_id = %s AND application_id = %s',
                    (replica_user_id, application_id), fetch_one=True
                )
                
                if not existing_assignment:
                    app_ports = calculate_app_ports(replica_user_id, application_id)
                    url = f"https://www.{DOMAIN}/{replica_username}/{app_name}"
                    
                    db_manager.execute_query(
                        f'''INSERT INTO user_applications (user_id, application_id, url, {APP_PORT_COLUMNS_SQL})
                           VALUES (%s, %s, %s, {APP_PORT_PLACEHOLDERS_SQL})
                           ON CONFLICT (user_id, application_id) DO NOTHING''',
                        (replica_user_id, application_id, url, *app_ports)
                    )
                    logger.info(f"[MULTI-USER DEPLOY] Assigned app '{app_name}' to user '{replica_username}'")
                else:
                    logger.info(f"[MULTI-USER DEPLOY] App '{app_name}' already assigned to user '{replica_username}'")
                
                # Step 3: Clone the application into the user's deployment folder
                deployment_path = f'/home/{config_postgres.LINUX_USER_INSTALLATION}/deployments/{replica_username}/{app_name.lower().replace(" ", "-")}'
                
                # Determine if local or remote
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    s.connect(("8.8.8.8", 80))
                    current_server_ip = s.getsockname()[0]
                    s.close()
                except (OSError, socket.error):
                    current_server_ip = "127.0.0.1"
                
                is_local = (str(server_ip) == current_server_ip or str(server_ip) in ["127.0.0.1", "localhost"])
                
                git_env = os.environ.copy()
                git_env.update({'GIT_CONFIG_NOSYSTEM': '1', 'HOME': f'/home/{config_postgres.LINUX_USER_INSTALLATION}', 'USER': config_postgres.LINUX_USER_INSTALLATION})
                
                if is_local:
                    # Local clone
                    if not os.path.exists(deployment_path):
                        os.makedirs(deployment_path, exist_ok=True)
                        clone_result = subprocess.run(
                            ['git', 'clone', '--recurse-submodules', git_url, deployment_path],
                            capture_output=True, text=True, timeout=300, env=git_env
                        )
                    else:
                        # Already exists, do a pull/fetch
                        clone_result = subprocess.run(
                            ['git', '-C', deployment_path, 'pull', '--recurse-submodules'],
                            capture_output=True, text=True, timeout=300, env=git_env
                        )
                else:
                    # Remote clone via SSH
                    ssh_cmd = f"ssh -o StrictHostKeyChecking=no {config_postgres.LINUX_USER_INSTALLATION}@{server_ip} 'mkdir -p {deployment_path} && if [ -d {deployment_path}/.git ]; then cd {deployment_path} && git pull --recurse-submodules; else git clone --recurse-submodules {git_url} {deployment_path}; fi'"
                    clone_result = subprocess.run(
                        ssh_cmd, shell=True, capture_output=True, text=True, timeout=300
                    )
                
                if clone_result.returncode != 0:
                    logger.error(f"[MULTI-USER DEPLOY] Clone failed for '{replica_username}': {clone_result.stderr}")
                    created_users.append({'username': replica_username, 'status': 'clone_failed'})
                    continue
                
                logger.info(f"[MULTI-USER DEPLOY] Cloned app to {deployment_path}")
                
                # Record deployment in deployments table
                swautomorph_url = f"https://{DOMAIN}/{replica_username}/{app_name}"
                existing_deployment = db_manager.execute_query(
                    'SELECT id FROM deployments WHERE user_id = %s AND application_name = %s AND server_id = %s',
                    (replica_user_id, app_name, server_id), fetch_one=True
                )
                
                if existing_deployment:
                    db_manager.execute_query(
                        '''UPDATE deployments SET status = %s, deployment_path = %s, git_url = %s, 
                           gitea_branch_url = %s, swautomorph_url = %s, application_id = %s, 
                           updated_at = CURRENT_TIMESTAMP 
                           WHERE user_id = %s AND application_name = %s AND server_id = %s''',
                        ('cloned', deployment_path, git_url, git_url, swautomorph_url, application_id,
                         replica_user_id, app_name, server_id)
                    )
                else:
                    db_manager.execute_query(
                        '''INSERT INTO deployments (user_id, application_id, application_name, status, deployment_path, git_url, gitea_branch_url, server_id, swautomorph_url)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)''',
                        (replica_user_id, application_id, app_name, 'cloned', deployment_path, git_url, git_url, server_id, swautomorph_url)
                    )
                
                # Step 4: Start the Docker container in the user's environment
                deploy_script = os.path.join(deployment_path, 'deployApp.sh')
                
                if is_local:
                    if os.path.exists(deploy_script):
                        start_result = subprocess.run(
                            [deploy_script, 'start', str(replica_user_id), replica_username],
                            cwd=deployment_path, capture_output=True, text=True, timeout=300
                        )
                    else:
                        logger.warning(f"[MULTI-USER DEPLOY] deployApp.sh not found at {deploy_script}")
                        start_result = type('Result', (), {'returncode': 1, 'stderr': 'deployApp.sh not found'})()
                else:
                    ssh_start_cmd = [
                        'ssh', '-o', 'StrictHostKeyChecking=no', '-o', 'UserKnownHostsFile=/dev/null',
                        f'{config_postgres.LINUX_USER_INSTALLATION}@{server_ip}',
                        f'cd {deployment_path} && ./deployApp.sh start {replica_user_id} {replica_username}'
                    ]
                    start_result = subprocess.run(
                        ssh_start_cmd, capture_output=True, text=True, timeout=300
                    )
                
                if start_result.returncode != 0:
                    logger.warning(f"[MULTI-USER DEPLOY] Start failed for '{replica_username}': {getattr(start_result, 'stderr', 'unknown error')}")
                    user_status = 'cloned_but_start_failed' if user_status != 'existing' else 'existing_start_failed'
                else:
                    logger.info(f"[MULTI-USER DEPLOY] Docker started for '{replica_username}'")
                    user_status = 'deployed' if user_status != 'existing' else 'existing_redeployed'
                    
                    # Update deployment status
                    db_manager.execute_query(
                        'UPDATE deployments SET status = %s, updated_at = CURRENT_TIMESTAMP WHERE user_id = %s AND application_name = %s',
                        ('running', replica_user_id, app_name)
                    )
                
                created_users.append({'username': replica_username, 'user_id': replica_user_id, 'status': user_status})
                
            except Exception as e:
                logger.error(f"[MULTI-USER DEPLOY] Error processing replica '{replica_username}': {str(e)}")
                created_users.append({'username': replica_username, 'status': f'error: {str(e)}'})
                continue
        
        # Create the service record in services table for tracking only.
        # Set desired_replicas=0 so that the orchestrator's reconciliation loop
        # does NOT try to `docker run` the git_url as an image — multi_user_deploy
        # already handles cloning and starting containers via deployApp.sh.
        from ..orchestrator import orchestrator
        orchestrator.create_service(
            name=app_name,
            image=git_url,
            user_id=session['user_id'],
            desired_replicas=0,
            ports=data.get('ports', {}),
            environment=environment,
            volumes=data.get('volumes', []),
            health_check_path=health_check_path
        )
        # Now update the service record to reflect the actual desired replicas
        # without triggering reconciliation (which would try docker run with the git URL)
        db_manager.execute_query(
            'UPDATE services SET desired_replicas = %s, updated_at = CURRENT_TIMESTAMP WHERE name = %s AND user_id = %s',
            (desired_replicas, app_name, session['user_id'])
        )
        
        successful = sum(1 for u in created_users if 'deployed' in u.get('status', '') or 'redeployed' in u.get('status', ''))
        
        logger.info(f"[MULTI-USER DEPLOY] Completed: {successful}/{desired_replicas} replicas deployed successfully")
        
        return jsonify({
            'message': f'Multi-user deployment completed for {app_name}',
            'total_replicas': desired_replicas,
            'successful_deploys': successful,
            'created_users': created_users
        }), 201
        
    except Exception as e:
        logger.error(f"[MULTI-USER DEPLOY] Exception: {str(e)}")
        return jsonify({'error': str(e)}), 500