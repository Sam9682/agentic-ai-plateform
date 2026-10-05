"""GenAI routes for AI-powered deployment and development operations"""
from flask import Blueprint, request, jsonify, session, stream_with_context
import os
import json
import logging
from datetime import datetime
from ..config_postgres import TIMEOUT_SUBPROCESS_RUN, TIMEOUT_request_dev_ai_for_app_RUN, TIMEOUT_CLEAN_SHUTDOWN, TIMEOUT_QCHAT_OPERATOR_RUN, AI_ENGINE, PLTF_FOLDER, LINUX_USER_INSTALLATION

# Path configuration functions
def get_logs_dir():
    """Get logs directory path"""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # retreive the parent folder of base_dir
    base_dir = os.path.dirname(base_dir)
    return os.path.join(base_dir, 'logs')

# Configure logging for genai activities
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Remove existing handlers to avoid duplicates
if logger.handlers:
    logger.handlers.clear()

# File handler
log_file = os.path.join(get_logs_dir(), 'genai_routes.log')
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

# Use PostgreSQL database manager
from ..database_postgres import db_manager

genai_bp = Blueprint('genai', __name__, url_prefix='/api')

def return_prompt_for_developer(detected_action, application_name, application_folder, user_name, user_email, repo_gitea_url='', branch_name='', repo_github_url='', message='', version='default'):
    l_prompt = ''

    if version == 'default':
        # Sanitize detected_action to prevent path traversal
        if not detected_action or not isinstance(detected_action, str):
            logger.warning(f'AI Chat Developer - Security: Invalid detected_action input rejected: {repr(detected_action)}')
            return ''
        
        # Remove any path traversal characters and limit to alphanumeric + underscore
        original_action = detected_action
        safe_action = ''.join(c for c in detected_action.upper() if c.isalnum() or c == '_')[:50]
        if not safe_action or safe_action != original_action.upper():
            logger.warning(f'AI Chat Developer - Security: Potentially malicious detected_action sanitized from "{original_action}" to "{safe_action}"')
            if not safe_action:
                return ''
        
        context_file = f"/home/{LINUX_USER_INSTALLATION}/{PLTF_FOLDER}/shared/{safe_action}_context.md"
        
        if os.path.exists(context_file):
            logger.info(f'AI Chat Developer - Loading context from {detected_action.upper()}_context.md')

            with open(context_file, 'r') as f:
                context_template = f.read()
            
            # Get application ID from database for APPLICATION_IDENTITY_NUMBER
            application_id = 0  # Default fallback
            if application_name:
                app_data = db_manager.execute_query(
                    'SELECT id FROM applications WHERE name = %s', 
                    (application_name,), fetch_one=True
                )
                if app_data:
                    application_id = app_data[0]
                    logger.info(f"Found application ID: {application_id} for {application_name}")
                else:
                    logger.warning(f"Application {application_name} not found in database, using ID 0")
            
            # Load configuration values from database_postgres.py (unused but required for context)
            from ..database_postgres import load_deploy_config
            _ = load_deploy_config()  # Load but don't unpack unused variables
            
            # Replace placeholders
            try:
                l_prompt = context_template.replace('{{USER_ID}}', str(session.get('user_id', 0)))
                l_prompt = l_prompt.replace('{{USER_NAME}}', user_name or '')
                l_prompt = l_prompt.replace('{{USER_EMAIL}}', user_email or '')
                l_prompt = l_prompt.replace('{{TAIL_LINES}}', '100')
                l_prompt = l_prompt.replace('{{APPLICATION_FOLDER}}', application_folder or '')
                l_prompt = l_prompt.replace('{{APPLICATION_NAME}}', application_name or '')
                l_prompt = l_prompt.replace('{{REPO_GITEA_URL}}', repo_gitea_url or '')
                l_prompt = l_prompt.replace('{{BRANCH_NAME}}', branch_name or '')
                l_prompt = l_prompt.replace('{{REPO_GITHUB_URL}}', repo_github_url or '')
                l_prompt = l_prompt.replace('{{MESSAGE}}', message or '')
            except (KeyError, AttributeError) as e:
                logger.error(f'AI Chat Developer - Template replacement error: {str(e)}')
                l_prompt = ''

    return l_prompt

# Inventory of recognized executable operator actions. Mirrors the operator
# dropdown in templates/dashboard.html. MODIFY_CODE is intentionally excluded
# because it is redirected to the Developer agent before prompt building.
RECOGNIZED_OPERATOR_ACTIONS = {'START', 'STOP', 'LOGS', 'PS', 'SPECIFY', 'RESTORE_DATABASE'}

def _is_recognized_operator_action(safe_action):
    """Return True if the given action is a recognized executable operator action.

    Sanitizes the action the same way as return_prompt_for_operator (upper-case,
    alphanumeric + underscore, max 50 chars) and checks membership in
    RECOGNIZED_OPERATOR_ACTIONS. Returns False for empty/None/non-string input.
    """
    if not safe_action or not isinstance(safe_action, str):
        return False
    normalized = ''.join(c for c in safe_action.upper() if c.isalnum() or c == '_')[:50]
    return normalized in RECOGNIZED_OPERATOR_ACTIONS

def _create_fallback_prompt(message):
    """Create fallback Q&A prompt for invalid actions"""
    return f"""You are a helpful Virtual Advisor assistant. Answer the user's question clearly and concisely.
Do not execute any commands or modify any files. Just provide helpful information and guidance.
User Question: {message}
Provide a helpful and informative response.
"""

def return_prompt_for_operator(detected_action, application_name, application_folder, user_name, user_email, version='default'):
    """Resolve the operator prompt for a detected action.

    Returns a tuple ``(l_prompt, is_executing)`` where ``is_executing`` is True
    only when a real ``{SAFE_ACTION}_context.md`` file was loaded and the
    executing prompt was built. For a recognized executable action whose context
    file is missing, this returns an explicit failure ``(None, False)`` instead
    of silently degrading to the advisor fallback. Genuinely invalid/empty
    actions still receive the advisor fallback with ``is_executing == False``.
    """
    l_prompt = ''

    if version == 'default':
        # Sanitize detected_action to prevent path traversal
        if not detected_action or not isinstance(detected_action, str):
            logger.warning('AI Chat Operator - Context file not found: invalid action, using default Q&A mode')
            return _create_fallback_prompt(detected_action), False
        
        # Remove any path traversal characters and limit to alphanumeric + underscore
        safe_action = ''.join(c for c in detected_action.upper() if c.isalnum() or c == '_')[:50]
        if not safe_action:
            logger.warning('AI Chat Operator - Context file not found: invalid action, using default Q&A mode')
            return _create_fallback_prompt(detected_action), False
        
        context_file = f"/home/{LINUX_USER_INSTALLATION}/{PLTF_FOLDER}/shared/{safe_action}_context.md"
                
        if os.path.exists(context_file):
            logger.info(f'AI Chat Operator - Loading context from {detected_action.upper()}_context.md')
            
            with open(context_file, 'r') as f:
                context_template = f.read()
            
            # Get application ID from database for APPLICATION_IDENTITY_NUMBER
            application_id = 0  # Default fallback
            if application_name:
                app_data = db_manager.execute_query(
                    'SELECT id FROM applications WHERE name = %s', 
                    (application_name,), fetch_one=True
                )
                if app_data:
                    application_id = app_data[0]
                    logger.info(f"Found application ID: {application_id} for {application_name}")
                else:
                    logger.warning(f"Application {application_name} not found in database, using ID 0")

            # Load configuration values from database_postgres.py (unused but required for context)
            from ..database_postgres import load_deploy_config
            _ = load_deploy_config()  # Load but don't unpack unused variables
            
            # Replace placeholders
            try:
                l_prompt = context_template.replace('{{USER_ID}}', str(session.get('user_id', 0)))
                l_prompt = l_prompt.replace('{{USER_NAME}}', user_name or '')
                l_prompt = l_prompt.replace('{{USER_EMAIL}}', user_email or '')
                l_prompt = l_prompt.replace('{{TAIL_LINES}}', '100')
                l_prompt = l_prompt.replace('{{APPLICATION_FOLDER}}', application_folder or '')
                l_prompt = l_prompt.replace('{{APPLICATION_NAME}}', application_name or '')
            except (KeyError, AttributeError) as e:
                logger.error(f'AI Chat Operator - Template replacement error: {str(e)}')
                l_prompt = ''
            return l_prompt, True
        else:
            # Context file is missing. Distinguish a recognized executable
            # operator action (missing context is an error, not a reason to
            # chat) from a genuinely invalid/empty action.
            if _is_recognized_operator_action(safe_action):
                logger.error(
                    f'AI Chat Operator - Missing context file for recognized action '
                    f'{safe_action}: {context_file}. Refusing to degrade to advisor '
                    f'mode; reporting explicit failure.'
                )
                return None, False
            logger.warning(f'AI Chat Operator - Context file not found: {context_file}, using default Q&A mode')
            l_prompt = _create_fallback_prompt(detected_action)
            logger.info(f'AI Chat Operator - (Context {context_file} not found) Prompt : {l_prompt[:120]}')
            return l_prompt, False

    return l_prompt, False

@genai_bp.route('/deployments/<int:deployment_id>/logs')
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
    if not deploy_path or '..' in deploy_path or not deploy_path.startswith(f'/home/{LINUX_USER_INSTALLATION}/deployments/'):
        logger.warning(f"[DEPLOYMENT LOGS] SECURITY - Invalid deployment path: {deploy_path} for user {user_id}")
        return jsonify({'error': 'Invalid deployment path'}), 400
    
    log_file = os.path.join(deploy_path, 'deployment.log')
    
    # Additional security check for log file path
    if not log_file.startswith(f'/home/{LINUX_USER_INSTALLATION}/deployments/') or '..' in log_file:
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

@genai_bp.route('/request_dev_ai_for_app', methods=['POST'])
def api_request_dev_ai_for_app():
    from flask import Response, stream_with_context
    import subprocess
    import re
    
    user_id = session.get('user_id', '0')
    
    if 'user_id' not in session:
        return jsonify({'error': 'Authentication required'}), 401
    
    data = request.get_json()
    message = data.get('message', '').strip()
    application_name = data.get('application_name', '')
    application_folder = data.get('application_folder', '')
    detected_action = data.get('action_operation', '')
    agentic_engine = data.get('agentic_engine')
    if not agentic_engine:
        # Get from PostgreSQL database
        config_result = db_manager.execute_query(
            'SELECT value FROM configuration WHERE key = %s AND (parent IS NULL)',
            ('agentic_engine',), fetch_one=True
        )
        agentic_engine = config_result[0] if config_result else AI_ENGINE
    
    agentic_command = data.get('agentic_command')
    if not agentic_command:
        # Get from PostgreSQL database
        config_result = db_manager.execute_query(
            'SELECT value FROM configuration WHERE key = %s AND (parent IS NULL)',
            ('agentic_command',), fetch_one=True
        )
        agentic_command = config_result[0] if config_result else ''

    if not message:
        return jsonify({'error': 'Message required'}), 400
    
    user_details = db_manager.execute_query(
        'SELECT username, email, first_name, last_name FROM users WHERE id = %s', 
        (session['user_id'],), fetch_one=True
    )
    
    username = user_details[0] if user_details else 'user'
    user_email = user_details[1] if user_details else 'user@example.com'
    user_name = f"{user_details[2] or ''} {user_details[3] or ''}" if user_details else 'User'
    description = f"Application: {application_name}, Path: {application_folder}" if application_name else ''

    logger.info(f"AI Chat Developer - User: {username}, Email: {user_email}, App: {application_name}, Folder: {application_folder}")
    logger.info(f"AI Chat Developer - Message: {message[:120]}")

    def generate():
        try:
            yield f"data: {json.dumps({'chunk': 'Starting Agentic AI Developer session...'})}\n\n"
            
            # Build prompt directly here
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            branch_name = f"{session['user_id']}-automorph-{application_name}-{timestamp}"

            logger.info(f'AI Chat Developer - Detected action: {detected_action}')
            yield f"data: {json.dumps({'chunk': f'AI Chat Developer - Detected action: {detected_action}'})}\n\n"

            # Use provided app folder or default REPO_DIR
            repo_dir = application_folder if application_folder else f"/home/{LINUX_USER_INSTALLATION}/deployments/"
            repo_github_url = f"git@github.com:Sam9682/{application_name}" if application_name else "git@github.com:Sam9682/"
            repo_gitea_url = f"http://gitadmin:password@localhost:3000/gitadmin/{branch_name}"
            
            yield f"data: {json.dumps({'chunk': f'App: {application_name}, Folder: {repo_gitea_url}'})}\n\n"
            
            # 🧠 Prompt complet envoyé à Agentic AI
            l_prompt = return_prompt_for_developer(detected_action, application_name, application_folder, user_name, user_email,  repo_gitea_url, branch_name, repo_github_url, message)

            # dump the value of l_prompt to a file (append to the file). Be aware that l_prompt is a variable composed of multiple lines
            prompt_file_path = os.path.join(get_logs_dir(), 'dev_prompt_generated.txt')
            try:
                with open(prompt_file_path, 'a') as f:
                    f.write(l_prompt+"\n")
            except (IOError, OSError) as e:
                yield f"data: {json.dumps({'chunk': f'Warning: Failed to write prompt to file: {str(e)}'})}\n\n"

            engine_env = os.environ.copy()
            engine_env.update({'HOME': f'/home/{LINUX_USER_INSTALLATION}', 'USER': LINUX_USER_INSTALLATION, 'PATH': f'/home/{LINUX_USER_INSTALLATION}/.local/bin:' + engine_env.get('PATH', '')})

            # Use agentic_command if provided, otherwise use qchat
            if agentic_command:
                # Execute deployControlPlan.sh with agentic_command
                cmd_args = [f'/home/{LINUX_USER_INSTALLATION}/{PLTF_FOLDER}/deployControlPlan.sh', agentic_command]
                yield f"data: {json.dumps({'chunk': f'Executing deployControlPlan.sh with command: {agentic_command}'})}\n\n"

            elif agentic_engine.lower() == 'shai':
                # Find engine command
                from ..config_postgres import get_shai_paths
                engine_cmd = get_shai_paths()
                
                if not engine_cmd:
                    yield f"data: {json.dumps({'error': f'{agentic_engine} not found for SHAI '})}\n\n"
                    return

                # Use shai engine (placeholder for future implementation)
                cmd_args = [agentic_engine, 'chat', '--trust-all-tools', l_prompt]

            else:
                # Default to qchat
                from ..config_postgres import get_qchat_paths
                engine_cmd = get_qchat_paths()
                
                if not engine_cmd:
                    yield f"data: {json.dumps({'error': f'{agentic_engine} not found for Q/Kiro-cli '})}\n\n"
                    return

                cmd_args = [engine_cmd, 'chat', '--trust-all-tools', l_prompt]

            yield f"data: {json.dumps({'chunk': f'Found {agentic_engine} at: {engine_cmd}'})}\n\n"

            # Start process with longer timeout and better error handling
            try:
                process = subprocess.Popen(cmd_args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
                                          text=True, bufsize=1, env=engine_env, preexec_fn=os.setsid)
            except (OSError, subprocess.SubprocessError) as e:
                yield f"data: {json.dumps({'error': f'Failed to start Agentic AI process: {str(e)}'})}\n\n"
                return
            
            ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
            
            import signal
            import time
            
            # Set a longer timeout for Agentic AI operations (30 minutes)
            timeout_seconds = TIMEOUT_request_dev_ai_for_app_RUN
            start_time = time.time()
            
            try:
                for line in iter(process.stdout.readline, ''):
                    if line:
                        clean_line = ansi_escape.sub('', line.rstrip())
                        if clean_line and 'Thinking...' not in clean_line:
                            yield f"data: {json.dumps({'chunk': clean_line})}\n\n"
                    
                    # Check timeout
                    if time.time() - start_time > timeout_seconds:
                        yield f"data: {json.dumps({'chunk': 'WARNING: Agentic AI operation timeout reached (30 minutes), terminating...'})}\n\n"
                        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                        time.sleep(5)
                        if process.poll() is None:
                            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                        break
                
                process.wait(timeout=TIMEOUT_CLEAN_SHUTDOWN)  # Wait up to 1 minute for clean shutdown
                
            except subprocess.TimeoutExpired:
                yield f"data: {json.dumps({'chunk': 'Agentic AI process cleanup timeout, forcing termination...'})}\n\n"
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                process.returncode = -1
            
            # After MODIFY_CODE completion, create Gitea branch and update database
            if process.returncode == 0 and detected_action == 'MODIFY_CODE' and application_name:
                try:
                    yield f"data: {json.dumps({'chunk': 'Creating Gitea branch and updating database...'})}\n\n"
                    
                    # Get deployment record
                    deployment = db_manager.execute_query(
                        'SELECT id, modification_history FROM deployments WHERE user_id = %s AND application_name = %s ORDER BY created_at DESC LIMIT 1',
                        (session['user_id'], application_name), fetch_one=True
                    )
                    
                    if deployment:
                        deployment_id, history = deployment[0], deployment[1] or []
                        
                        # Add new modification to history
                        new_mod = {
                            'timestamp': datetime.now().isoformat(),
                            'branch_name': branch_name,
                            'gitea_url': repo_gitea_url,
                            'user': username,
                            'message': message[:200]
                        }
                        history.append(new_mod)
                        
                        # Update deployment with Gitea URL and history
                        db_manager.execute_query(
                            'UPDATE deployments SET gitea_branch_url = %s, modification_history = %s::jsonb WHERE id = %s',
                            (repo_gitea_url, json.dumps(history), deployment_id)
                        )
                        yield f"data: {json.dumps({'chunk': f'Database updated with Gitea branch: {branch_name}'})}\n\n"
                    else:
                        yield f"data: {json.dumps({'chunk': 'Warning: Deployment record not found'})}\n\n"
                        
                except Exception as e:
                    yield f"data: {json.dumps({'chunk': f'Warning: Failed to update Gitea/database: {str(e)}'})}\n\n"
            
            yield f"data: {json.dumps({'done': True, 'success': process.returncode == 0, 'returncode': process.returncode})}\n\n"
            
        except Exception as e:
            yield f"data: {json.dumps({'error': f'Exception in generate(): {str(e)}'})}\n\n"
    
    return Response(stream_with_context(generate()), mimetype='text/event-stream',
                   headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

@genai_bp.route('/request_ops_ai_for_app', methods=['POST'])
def api_request_ops_ai_for_app():
    from flask import Response, stream_with_context
    import subprocess
    import re
    
    user_id = session.get('user_id', 'anonymous')
    
    if 'user_id' not in session:
        return jsonify({'error': 'Authentication required'}), 401
    
    data = request.get_json()
    message = data.get('message', '').strip()
    application_name = data.get('application_name', '')
    application_folder = data.get('application_folder', '')
    detected_action = data.get('action_operation', '')
    agentic_engine = data.get('agentic_engine')
    if not agentic_engine:
        # Get from PostgreSQL database
        config_result = db_manager.execute_query(
            'SELECT value FROM configuration WHERE key = %s AND (parent IS NULL)',
            ('agentic_engine',), fetch_one=True
        )
        agentic_engine = config_result[0] if config_result else AI_ENGINE
    
    agentic_command = data.get('agentic_command')
    if not agentic_command:
        # Get from PostgreSQL database
        config_result = db_manager.execute_query(
            'SELECT value FROM configuration WHERE key = %s AND (parent IS NULL)',
            ('agentic_command',), fetch_one=True
        )
        agentic_command = config_result[0] if config_result else ''
    
    if not message:
        return jsonify({'error': 'Message required'}), 400
    
    user_details = db_manager.execute_query(
        'SELECT username, email, first_name, last_name FROM users WHERE id = %s', 
        (session['user_id'],), fetch_one=True
    )
    
    username = user_details[0] if user_details else 'user'
    user_email = user_details[1] if user_details else 'user@example.com'
    user_name = f"{user_details[2] or ''} {user_details[3] or ''}" if user_details else 'User'
    description = f"Application: {application_name}, Path: {application_folder}" if application_name else ''

    logger.info(f"AI Chat Operator - User: {username}, Email: {user_email}, App: {application_name}, Folder: {application_folder}")
    logger.info(f"AI Chat Operator - Message: {message[:120]}")

    def generate():
        import os
        
        try:
            yield f"data: {json.dumps({'chunk': 'Starting agentic AI DevOps session...'})}\n\n"
            
            # Build prompt directly here instead of calling process_qchat_devops
            # Detect application management actions
            
            if detected_action:
                # Map complete sentences to actions
                if 'MODIFY_CODE' in detected_action:
                    l_msg = f"[VIRTUAL OPERATIONS] ERROR : asking to modify the code, should be sent to Developer agent"
                    yield f"data: {json.dumps({'error': l_msg})}\n\n"
                    return

                yield f"data: {json.dumps({'chunk': f'Detected complete sentence action: {detected_action}'})}\n\n"

                # 🧠 Prompt complet envoyé à Agentic AI
                try:
                    l_prompt, is_executing = return_prompt_for_operator(detected_action, application_name, application_folder, user_name, user_email)
                except Exception as e:
                    yield f"data: {json.dumps({'error': f'Failed to generate prompt: {str(e)}'})}\n\n"
                    return

                # Recognized action with a missing context resolves to an
                # explicit failure: surface a clear error, report failure, and
                # do not launch the engine for this action.
                if l_prompt is None:
                    l_msg = (f"[VIRTUAL OPERATIONS] ERROR: no execution context available for "
                             f"action '{detected_action}'; the action was not launched.")
                    logger.error(l_msg)
                    yield f"data: {json.dumps({'error': l_msg})}\n\n"
                    yield f"data: {json.dumps({'done': True, 'success': False, 'returncode': None})}\n\n"
                    return

                logger.info(f'AI Chat Operator - Prompt : {l_prompt[:120]}')

            else:
                # Simple prompt for Q&A without code execution
                is_executing = False
                l_prompt = f"""You are a helpful Virtual Advisor assistant. Answer the user's question clearly and concisely.
Do not execute any commands or modify any files. Just provide helpful information and guidance.
User Question: {message}. Provide a helpful and informative response."""
                logger.info(f'AI Chat Operator - (Simple Q&A) Prompt : {l_prompt[:120]}')

            # dump the value of l_prompt to a file. Be aware that l_prompt is a variable composed of multiple lines
            prompt_file_path = os.path.join(get_logs_dir(), 'ope_prompts_generated.log')
            try:
                with open(prompt_file_path, 'a') as f:
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    f.write(f"----------------- Generated Prompt for Virtual Operator at {timestamp}: \n")
                    f.write(l_prompt+"\n")
            except (IOError, OSError) as e:
                yield f"data: {json.dumps({'chunk': f'Warning: Failed to write prompt to file: {str(e)}'})}\n\n"

            # dump the value of l_prompt to a file. Be aware that l_prompt is a variable composed of multiple lines
            prompt_file_path = os.path.join(get_logs_dir(), 'dev_prompt_generated.txt')
            try:
                with open(prompt_file_path, 'a') as f:
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    f.write(f"----------------- Generated Prompt for Virtual Operator at {timestamp}: \n")
                    f.write(l_prompt+"\n")
            except (IOError, OSError) as e:
                yield f"data: {json.dumps({'chunk': f'Warning: Failed to write prompt to file: {str(e)}'})}\n\n"

            engine_env = os.environ.copy()
            engine_env.update({'HOME': f'/home/{LINUX_USER_INSTALLATION}', 'USER': LINUX_USER_INSTALLATION, 'PATH': f'/home/{LINUX_USER_INSTALLATION}/.local/bin:' + engine_env.get('PATH', '')})

            # Use agentic_command if provided, otherwise use qchat
            if agentic_command:
                # Execute deployControlPlan.sh with agentic_command
                cmd_args = [f'/home/{LINUX_USER_INSTALLATION}/{PLTF_FOLDER}/deployControlPlan.sh', agentic_command]
                yield f"data: {json.dumps({'chunk': f'Executing deployControlPlan.sh with command: {agentic_command}'})}\n\n"

            elif agentic_engine.lower() == 'shai':
                # Find engine command
                from ..config_postgres import get_shai_paths
                engine_cmd = get_shai_paths()
                
                if not engine_cmd:
                    yield f"data: {json.dumps({'error': f'{agentic_engine} not found for SHAI '})}\n\n"
                    return

                # Use shai engine (placeholder for future implementation)
                cmd_args = [agentic_engine, 'chat', '--trust-all-tools', l_prompt]

            else:
                # Default to qchat
                from ..config_postgres import get_qchat_paths
                engine_cmd = get_qchat_paths()
                
                if not engine_cmd:
                    yield f"data: {json.dumps({'error': f'{agentic_engine} not found for Q/Kiro-cli '})}\n\n"
                    return

                cmd_args = [engine_cmd, 'chat', '--trust-all-tools', l_prompt]

            yield f"data: {json.dumps({'chunk': f'Found {agentic_engine} at: {engine_cmd}'})}\n\n"
            
            # Start process with longer timeout and better error handling
            try:
                process = subprocess.Popen(cmd_args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
                                          text=True, bufsize=1, env=engine_env, preexec_fn=os.setsid)
            except (OSError, subprocess.SubprocessError) as e:
                yield f"data: {json.dumps({'error': f'Failed to start Agentic AI process: {str(e)}'})}\n\n"
                return
            
            ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
            
            import signal
            import time
            
            # Set a longer timeout for Agentic AI operations (30 minutes)
            timeout_seconds = TIMEOUT_QCHAT_OPERATOR_RUN
            start_time = time.time()
            
            try:
                for line in iter(process.stdout.readline, ''):
                    if line:
                        clean_line = ansi_escape.sub('', line.rstrip())
                        if clean_line and 'Thinking...' not in clean_line:
                            yield f"data: {json.dumps({'chunk': clean_line})}\n\n"
                    
                    # Check timeout
                    if time.time() - start_time > timeout_seconds:
                        yield f"data: {json.dumps({'chunk': 'WARNING: Agentic AI operation timeout reached (30 minutes), terminating...'})}\n\n"
                        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                        time.sleep(5)
                        if process.poll() is None:
                            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                        break
                
                process.wait(timeout=TIMEOUT_CLEAN_SHUTDOWN)  # Wait up to 1 minute for clean shutdown
                
            except subprocess.TimeoutExpired:
                yield f"data: {json.dumps({'chunk': 'Agentic AI process cleanup timeout, forcing termination...'})}\n\n"
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                process.returncode = -1
            
            # Record billing activity for START and STOP actions only when the
            # action was genuinely executed (an executing prompt built from a
            # real context file), the engine exited cleanly, and an application
            # is targeted. When is_executing is False (advisor / non-execution
            # path) billing is skipped entirely, so a non-action is never
            # billed even if the engine returns 0.
            if is_executing and (detected_action.upper() == 'START' or detected_action.upper() == 'STOP') and process.returncode == 0 and application_name:
                try:
                    from .billing_routes import record_billing_activity
                    record_billing_activity(session['user_id'], application_name, detected_action)
                    yield f"data: {json.dumps({'chunk': f'Billing activity recorded for {detected_action} action on {application_name}'})}\n\n"
                except Exception as billing_error:
                    yield f"data: {json.dumps({'chunk': f'Warning: Failed to record billing activity: {str(billing_error)}'})}\n\n"
            
            yield f"data: {json.dumps({'chunk': f'=== Agentic AI Session Completed ==='})}\n\n"
            yield f"data: {json.dumps({'done': True, 'success': process.returncode == 0, 'returncode': process.returncode})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': f'Exception in generate(): {str(e)}'})}\n\n"
    
    return Response(stream_with_context(generate()), mimetype='text/event-stream',
                   headers={
                       'Cache-Control': 'no-cache',
                       'X-Accel-Buffering': 'no',
                       'Connection': 'keep-alive'
                   })