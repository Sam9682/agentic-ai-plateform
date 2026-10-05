"""Serverless Docker Execution API routes for job submission, status, results, and management."""
from flask import Blueprint, request, jsonify, session
from ..database_postgres import db_manager
from ..serverless.config import validate_image_registry, SERVERLESS_CONFIG
import json
import math
import os
import logging
import requests as http_requests

# Configure logging for serverless API activities
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Remove existing handlers to avoid duplicates
if logger.handlers:
    logger.handlers.clear()

# File handler
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
log_file = os.path.join(PROJECT_ROOT, 'logs', 'serverless_routes.log')
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

serverless_bp = Blueprint('serverless', __name__, url_prefix='/api')


# Map remote agentic-ai-plateform-serverless-brik statuses to local DB statuses
REMOTE_STATUS_MAP = {
    'success': 'completed',
    'completed': 'completed',
    'failed': 'failed',
    'error': 'failed',
    'timeout': 'timeout',
    'running': 'running',
    'pending': 'pending',
    'cancelled': 'cancelled',
}


def sync_job_from_remote(job_id, target_link):
    """Poll the remote agentic-ai-plateform-serverless-brik endpoint to get actual job status and update local DB.
    
    Returns the remote response data dict if successful, or None if the remote is unreachable.
    """
    if not target_link:
        return None

    # Build the remote URL: target_link is like https://agentic-ai-plateform.com:6133
    # The remote API is at {target_link}/jobs/{job_id}
    # But user's curl shows http://agentic-ai-plateform.com:6132/jobs/{id} - use HTTP port
    # Convert https to http and port-1 for the API endpoint, or just try as-is
    remote_url = f"{target_link}/jobs/{job_id}"
    
    # Also try HTTP variant (the remote brik typically serves on HTTP)
    http_url = remote_url.replace("https://", "http://")
    # Adjust port: if HTTPS port (e.g. 6133), the HTTP port is one less (6132)
    try:
        parts = http_url.split(":")
        if len(parts) == 3:  # http://domain:port/path
            port_and_path = parts[2]
            port_str = port_and_path.split("/")[0]
            port = int(port_str)
            http_port = port - 1  # HTTP is one below HTTPS
            http_url = f"{parts[0]}:{parts[1]}:{http_port}/{'/'.join(port_and_path.split('/')[1:])}"
    except (ValueError, IndexError):
        pass

    # Try HTTP first (as shown in user's curl example), then HTTPS
    for url in [http_url, remote_url]:
        try:
            resp = http_requests.get(url, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                remote_status = data.get('status', '')
                local_status = REMOTE_STATUS_MAP.get(remote_status, remote_status)
                exit_code = data.get('exit_code')
                
                # Update local DB if status changed from pending/running
                if local_status in ('completed', 'failed', 'timeout'):
                    try:
                        db_manager.execute_query(
                            '''UPDATE serverless_jobs 
                               SET status = %s, exit_code = %s, completed_at = CURRENT_TIMESTAMP
                               WHERE id = %s AND status IN ('pending', 'running')''',
                            (local_status, exit_code, job_id)
                        )
                        # Store stdout/stderr in job_logs if available
                        stdout = data.get('stdout', '')
                        stderr = data.get('stderr', '')
                        if stdout:
                            db_manager.execute_query(
                                '''INSERT INTO serverless_job_logs (job_id, stream, content)
                                   VALUES (%s, %s, %s)
                                   ON CONFLICT DO NOTHING''',
                                (job_id, 'stdout', stdout)
                            )
                        if stderr:
                            db_manager.execute_query(
                                '''INSERT INTO serverless_job_logs (job_id, stream, content)
                                   VALUES (%s, %s, %s)
                                   ON CONFLICT DO NOTHING''',
                                (job_id, 'stderr', stderr)
                            )
                    except Exception as e:
                        logger.warning(f"Failed to update local DB for job {job_id}: {e}")
                elif local_status == 'running':
                    try:
                        db_manager.execute_query(
                            '''UPDATE serverless_jobs 
                               SET status = %s, started_at = COALESCE(started_at, CURRENT_TIMESTAMP)
                               WHERE id = %s AND status = 'pending' ''',
                            (local_status, job_id)
                        )
                    except Exception as e:
                        logger.warning(f"Failed to update running status for job {job_id}: {e}")
                
                return data
        except Exception as e:
            logger.debug(f"Failed to reach remote endpoint {url}: {e}")
            continue
    
    return None


@serverless_bp.route('/serverless-links', methods=['GET'])
def get_serverless_links():
    """Get agentic-ai-plateform-serverless-* endpoint links that are actively running, with availability status."""
    # Auth check
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"error": "Authentication required"}), 401

    logger.info(f"GET /api/serverless-links - Request received: user_id={user_id}")

    try:
        from ..database_postgres import DOMAIN, calculate_app_ports

        result_links = []

        # Get links from user_applications for apps matching 'agentic-ai-plateform-serverless%'
        # Only include endpoints where the deployment is actually running.
        try:
            all_links = db_manager.execute_query('''
                SELECT u.username, ua.https_port, a.name
                FROM user_applications ua
                JOIN applications a ON ua.application_id = a.id
                JOIN users u ON ua.user_id = u.id
                JOIN deployments d ON d.user_id = ua.user_id
                    AND d.application_id = ua.application_id
                WHERE a.name LIKE %s
                  AND ua.https_port IS NOT NULL
                  AND UPPER(d.status) = 'RUNNING'
                ORDER BY u.username
            ''', ('opcp-serverless%',), fetch_all=True)

            if all_links:
                for row in all_links:
                    username, https_port, app_name = row
                    result_links.append({
                        "url": f"https://{DOMAIN}:{https_port}",
                        "username": username,
                        "app_name": app_name,
                    })
        except Exception as e:
            logger.warning(f"Failed to query user_applications for serverless links: {e}")

        # Fallback: if no running deployments found, try without deployment join
        # but still filter by agentic-ai-plateform-serverless* pattern
        if not result_links:
            try:
                all_links = db_manager.execute_query('''
                    SELECT u.username, ua.https_port, a.name
                    FROM user_applications ua
                    JOIN applications a ON ua.application_id = a.id
                    JOIN users u ON ua.user_id = u.id
                    WHERE a.name LIKE %s AND ua.https_port IS NOT NULL
                    ORDER BY u.username
                ''', ('opcp-serverless%',), fetch_all=True)

                if all_links:
                    for row in all_links:
                        username, https_port, app_name = row
                        result_links.append({
                            "url": f"https://{DOMAIN}:{https_port}",
                            "username": username,
                            "app_name": app_name,
                        })
            except Exception as e:
                logger.warning(f"Failed to query user_applications (fallback) for serverless links: {e}")

        # Last resort: if still empty, generate a default link for admin
        if not result_links:
            result_links.append({"url": f"https://{DOMAIN}:6133", "username": "admin", "app_name": "opcp-serverless-brik"})

        # Determine availability status for each link
        # A brik is OCCUPIED if there's a pending or running job targeting it
        for link_obj in result_links:
            link_url = link_obj["url"]
            try:
                active_job = db_manager.execute_query(
                    '''SELECT id FROM serverless_jobs
                       WHERE target_link = %s AND status IN ('pending', 'running')
                       LIMIT 1''',
                    (link_url,), fetch_one=True
                )
                if active_job:
                    link_obj["status"] = "OCCUPIED"
                else:
                    link_obj["status"] = "AVAILABLE"
            except Exception:
                link_obj["status"] = "UNKNOWN"

        # Build response: return both the structured links and a flat list for backward compat
        links_flat = [link_obj["url"] for link_obj in result_links]

        logger.info(f"Serverless links retrieved: user_id={user_id}, count={len(result_links)}")
        return jsonify({"links": links_flat, "endpoints": result_links}), 200

    except Exception as e:
        logger.error(f"Failed to retrieve serverless links: {e}")
        return jsonify({"error": "Failed to retrieve links", "links": [], "endpoints": []}), 500


@serverless_bp.route('/jobs', methods=['POST'])
def submit_job():
    """Submit a new serverless Docker execution job."""
    # Auth check
    user_id = session.get('user_id')
    if not user_id:
        logger.warning("POST /api/jobs - Authentication failed: no user_id in session")
        return jsonify({"error": "Authentication required"}), 401

    logger.info(f"POST /api/jobs - Request received: user_id={user_id}")

    # Parse request payload
    data = request.get_json()
    if not data:
        logger.warning(f"POST /api/jobs - Invalid request body: user_id={user_id}")
        return jsonify({"error": "Request body must be valid JSON"}), 400

    # Validate required fields
    image = data.get('image')
    command = data.get('command')

    if not image or not isinstance(image, str):
        return jsonify({"error": "Field 'image' is required and must be a string"}), 400

    if not command or not isinstance(command, list):
        return jsonify({"error": "Field 'command' is required and must be a list"}), 400

    # Validate optional fields
    env = data.get('env', {})
    if not isinstance(env, dict):
        return jsonify({"error": "Field 'env' must be a dictionary"}), 400

    timeout = data.get('timeout', SERVERLESS_CONFIG['default_timeout'])
    if not isinstance(timeout, int):
        return jsonify({"error": "Field 'timeout' must be an integer"}), 400

    # Validate timeout range (1-3600)
    if timeout < 1 or timeout > 3600:
        return jsonify({"error": "Field 'timeout' must be between 1 and 3600 seconds"}), 400

    # Validate target_link (required - must select a serverless endpoint)
    target_link = data.get('target_link')
    if not target_link or not isinstance(target_link, str):
        return jsonify({"error": "Field 'target_link' is required and must be a string"}), 400

    # Validate image against registry whitelist
    whitelist = SERVERLESS_CONFIG['registry_whitelist']
    if not validate_image_registry(image, whitelist):
        return jsonify({"error": "Image registry is not approved"}), 403

    # Insert job record into database
    try:
        result = db_manager.execute_query(
            '''INSERT INTO serverless_jobs (user_id, image, command, environment, timeout_seconds, status, target_link)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               RETURNING id''',
            (user_id, image, json.dumps(command), json.dumps(env), timeout, 'pending', target_link),
            fetch_one=True
        )
        job_id = str(result[0])
    except Exception as e:
        logger.error(f"Failed to insert job record: {e}")
        return jsonify({"error": "Failed to create job"}), 500

    logger.info(f"Job submitted: job_id={job_id}, user_id={user_id}, image={image}, target_link={target_link}")

    return jsonify({"job_id": job_id}), 201


@serverless_bp.route('/jobs', methods=['GET'])
def list_jobs():
    """List jobs with pagination and optional status filter."""
    # Auth check
    user_id = session.get('user_id')
    if not user_id:
        logger.warning("GET /api/jobs - Authentication failed: no user_id in session")
        return jsonify({"error": "Authentication required"}), 401

    logger.info(f"GET /api/jobs - Request received: user_id={user_id}")

    # Parse pagination parameters
    try:
        page = int(request.args.get('page', 1))
    except (ValueError, TypeError):
        page = 1
    try:
        per_page = int(request.args.get('per_page', 20))
    except (ValueError, TypeError):
        per_page = 20

    # Clamp pagination values
    if page < 1:
        page = 1
    if per_page < 1:
        per_page = 1
    if per_page > 100:
        per_page = 100

    # Parse status filter
    status_filter = request.args.get('status')
    valid_statuses = ('pending', 'running', 'completed', 'failed', 'timeout', 'cancelled')
    if status_filter and status_filter not in valid_statuses:
        return jsonify({"error": f"Invalid status filter. Must be one of: {', '.join(valid_statuses)}"}), 400

    # Build query based on user role
    is_admin = session.get('is_admin', False)

    try:
        # Build WHERE clause
        conditions = []
        params = []

        if not is_admin:
            conditions.append("user_id = %s")
            params.append(user_id)

        if status_filter:
            conditions.append("status = %s")
            params.append(status_filter)

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        # Get total count
        count_query = f"SELECT COUNT(*) FROM serverless_jobs {where_clause}"
        count_result = db_manager.execute_query(count_query, tuple(params) if params else None, fetch_one=True)
        total = count_result[0] if count_result else 0

        # Calculate pagination
        pages = math.ceil(total / per_page) if total > 0 else 0
        offset = (page - 1) * per_page

        # Get paginated jobs
        jobs_query = f'''SELECT id, user_id, image, status, created_at, started_at, completed_at, exit_code, worker_id, target_link
                         FROM serverless_jobs {where_clause}
                         ORDER BY created_at DESC
                         LIMIT %s OFFSET %s'''
        jobs_params = list(params) + [per_page, offset]
        jobs = db_manager.execute_query(jobs_query, tuple(jobs_params), fetch_all=True)

    except Exception as e:
        logger.error(f"Failed to list jobs: {e}")
        return jsonify({"error": "Failed to retrieve jobs"}), 500

    # Build response
    jobs_list = []
    if jobs:
        for job in jobs:
            job_id_val = str(job[0])
            job_status = job[3]
            job_target_link = job[9]
            job_exit_code = job[7]

            # Sync status from remote endpoint if job is still pending or running
            if job_status in ('pending', 'running') and job_target_link:
                remote_data = sync_job_from_remote(job_id_val, job_target_link)
                if remote_data:
                    remote_status = remote_data.get('status', '')
                    job_status = REMOTE_STATUS_MAP.get(remote_status, job_status)
                    job_exit_code = remote_data.get('exit_code', job_exit_code)

            jobs_list.append({
                "job_id": job_id_val,
                "user_id": job[1],
                "image": job[2],
                "status": job_status,
                "created_at": job[4].isoformat() + 'Z' if job[4] else None,
                "started_at": job[5].isoformat() + 'Z' if job[5] else None,
                "completed_at": job[6].isoformat() + 'Z' if job[6] else None,
                "exit_code": job_exit_code,
                "worker_id": job[8],
                "target_link": job_target_link,
            })

    response_data = {
        "jobs": jobs_list,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": pages,
    }

    logger.info(f"Jobs listed: user_id={user_id}, is_admin={is_admin}, total={total}")

    return jsonify(response_data), 200


@serverless_bp.route('/jobs/metrics', methods=['GET'])
def get_metrics():
    """Get aggregated job metrics. Admin-only endpoint."""
    # Auth check
    user_id = session.get('user_id')
    if not user_id:
        logger.warning("GET /api/jobs/metrics - Authentication failed: no user_id in session")
        return jsonify({"error": "Authentication required"}), 401

    logger.info(f"GET /api/jobs/metrics - Request received: user_id={user_id}")

    # Admin-only check
    is_admin = session.get('is_admin', False)
    if not is_admin:
        logger.warning(f"GET /api/jobs/metrics - Access denied: user_id={user_id} is not admin")
        return jsonify({"error": "Admin access required"}), 403

    try:
        # Get counts of pending, running, and failed jobs
        counts = db_manager.execute_query(
            '''SELECT
                   COUNT(*) FILTER (WHERE status = 'pending') AS pending_count,
                   COUNT(*) FILTER (WHERE status = 'running') AS running_count,
                   COUNT(*) FILTER (WHERE status = 'failed') AS failed_count
               FROM serverless_jobs''',
            fetch_one=True
        )

        pending_count = counts[0] if counts else 0
        running_count = counts[1] if counts else 0
        failed_count = counts[2] if counts else 0

        # Get average execution time (completed_at - started_at) for completed jobs
        avg_exec = db_manager.execute_query(
            '''SELECT AVG(EXTRACT(EPOCH FROM (completed_at - started_at)))
               FROM serverless_jobs
               WHERE status = 'completed' AND started_at IS NOT NULL AND completed_at IS NOT NULL''',
            fetch_one=True
        )
        avg_execution_time = round(avg_exec[0], 2) if avg_exec and avg_exec[0] is not None else None

        # Get average startup duration (started_at - created_at) for jobs that have started
        avg_startup = db_manager.execute_query(
            '''SELECT AVG(EXTRACT(EPOCH FROM (started_at - created_at)))
               FROM serverless_jobs
               WHERE started_at IS NOT NULL''',
            fetch_one=True
        )
        avg_startup_duration = round(avg_startup[0], 2) if avg_startup and avg_startup[0] is not None else None

    except Exception as e:
        logger.error(f"Failed to retrieve metrics: {e}")
        return jsonify({"error": "Failed to retrieve metrics"}), 500

    response_data = {
        "pending_count": pending_count,
        "running_count": running_count,
        "failed_count": failed_count,
        "avg_execution_time": avg_execution_time,
        "queue_depth": pending_count,
        "avg_startup_duration": avg_startup_duration,
    }

    logger.info(f"Metrics retrieved by admin user_id={user_id}")

    return jsonify(response_data), 200


@serverless_bp.route('/jobs/<job_id>', methods=['GET'])
def get_job_status(job_id):
    """Get the status and metadata for a specific job."""
    # Auth check
    user_id = session.get('user_id')
    if not user_id:
        logger.warning(f"GET /api/jobs/{job_id} - Authentication failed: no user_id in session")
        return jsonify({"error": "Authentication required"}), 401

    logger.info(f"GET /api/jobs/{job_id} - Request received: user_id={user_id}, job_id={job_id}")

    # Query job by ID
    try:
        job = db_manager.execute_query(
            '''SELECT id, user_id, image, status, created_at, started_at, completed_at, exit_code, worker_id, target_link
               FROM serverless_jobs WHERE id = %s''',
            (job_id,),
            fetch_one=True
        )
    except Exception as e:
        logger.error(f"Failed to query job {job_id}: {e}")
        return jsonify({"error": "Failed to retrieve job"}), 500

    # 404 if job not found
    if not job:
        return jsonify({"error": "Job not found"}), 404

    # Ownership check: must be job owner or admin
    job_user_id = job[1]
    is_admin = session.get('is_admin', False)
    if job_user_id != user_id and not is_admin:
        return jsonify({"error": "Access denied"}), 403

    job_status = job[3]
    job_exit_code = job[7]
    target_link = job[9]

    # Sync status from remote if still pending/running
    if job_status in ('pending', 'running') and target_link:
        remote_data = sync_job_from_remote(job_id, target_link)
        if remote_data:
            remote_status = remote_data.get('status', '')
            job_status = REMOTE_STATUS_MAP.get(remote_status, job_status)
            job_exit_code = remote_data.get('exit_code', job_exit_code)

    # Build response
    response_data = {
        "job_id": str(job[0]),
        "status": job_status,
        "image": job[2],
        "created_at": job[4].isoformat() + 'Z' if job[4] else None,
        "started_at": job[5].isoformat() + 'Z' if job[5] else None,
        "completed_at": job[6].isoformat() + 'Z' if job[6] else None,
        "exit_code": job_exit_code,
        "worker_id": job[8],
    }

    logger.info(f"Job status retrieved: job_id={job_id}, user_id={user_id}")

    return jsonify(response_data), 200


@serverless_bp.route('/jobs/<job_id>/result', methods=['GET'])
def get_job_result(job_id):
    """Get the result of a completed job including stdout, stderr, and structured result."""
    # Auth check
    user_id = session.get('user_id')
    if not user_id:
        logger.warning(f"GET /api/jobs/{job_id}/result - Authentication failed: no user_id in session")
        return jsonify({"error": "Authentication required"}), 401

    logger.info(f"GET /api/jobs/{job_id}/result - Request received: user_id={user_id}, job_id={job_id}")

    # Query job by ID
    try:
        job = db_manager.execute_query(
            '''SELECT id, user_id, status, exit_code, target_link
               FROM serverless_jobs WHERE id = %s''',
            (job_id,),
            fetch_one=True
        )
    except Exception as e:
        logger.error(f"Failed to query job {job_id}: {e}")
        return jsonify({"error": "Failed to retrieve job"}), 500

    # 404 if job not found
    if not job:
        return jsonify({"error": "Job not found"}), 404

    # Ownership check: must be job owner or admin
    job_user_id = job[1]
    is_admin = session.get('is_admin', False)
    if job_user_id != user_id and not is_admin:
        return jsonify({"error": "Access denied"}), 403

    job_status = job[2]
    target_link = job[4]

    # If job is still pending/running locally, try syncing from remote first
    if job_status in ('pending', 'running') and target_link:
        remote_data = sync_job_from_remote(job_id, target_link)
        if remote_data:
            remote_status = remote_data.get('status', '')
            job_status = REMOTE_STATUS_MAP.get(remote_status, job_status)
            # If remote shows completed, return the result directly from remote data
            if job_status in ('completed', 'failed', 'timeout'):
                response_data = {
                    "exit_code": remote_data.get('exit_code'),
                    "stdout": remote_data.get('stdout', ''),
                    "stderr": remote_data.get('stderr', ''),
                    "result": None,
                }
                logger.info(f"Job result retrieved from remote: job_id={job_id}, user_id={user_id}")
                return jsonify(response_data), 200

    # Verify job is in terminal state
    terminal_states = ('completed', 'failed', 'timeout', 'cancelled')
    if job_status not in terminal_states:
        return jsonify({"error": "Job is still in progress"}), 409

    # Try fetching result from remote endpoint first
    if target_link:
        remote_data = sync_job_from_remote(job_id, target_link)
        if remote_data and remote_data.get('stdout') is not None:
            response_data = {
                "exit_code": remote_data.get('exit_code', job[3]),
                "stdout": remote_data.get('stdout', ''),
                "stderr": remote_data.get('stderr', ''),
                "result": None,
            }
            logger.info(f"Job result retrieved from remote: job_id={job_id}, user_id={user_id}")
            return jsonify(response_data), 200

    # Fallback: Query local job logs (stdout and stderr) ordered by created_at
    try:
        logs = db_manager.execute_query(
            '''SELECT stream, content FROM serverless_job_logs
               WHERE job_id = %s ORDER BY created_at ASC''',
            (job_id,),
            fetch_all=True
        )
    except Exception as e:
        logger.error(f"Failed to query job logs for {job_id}: {e}")
        logs = []

    # Concatenate stdout and stderr separately
    stdout_parts = []
    stderr_parts = []
    if logs:
        for log_entry in logs:
            stream = log_entry[0]
            content = log_entry[1]
            if stream == 'stdout':
                stdout_parts.append(content)
            elif stream == 'stderr':
                stderr_parts.append(content)

    # Query job result (JSONB)
    try:
        result_row = db_manager.execute_query(
            '''SELECT result FROM serverless_job_results WHERE job_id = %s''',
            (job_id,),
            fetch_one=True
        )
    except Exception as e:
        logger.error(f"Failed to query job result for {job_id}: {e}")
        result_row = None

    # Build response
    response_data = {
        "exit_code": job[3],
        "stdout": ''.join(stdout_parts),
        "stderr": ''.join(stderr_parts),
        "result": result_row[0] if result_row else None,
    }

    logger.info(f"Job result retrieved: job_id={job_id}, user_id={user_id}")

    return jsonify(response_data), 200


@serverless_bp.route('/jobs/<job_id>/cancel', methods=['POST'])
def cancel_job(job_id):
    """Cancel a pending or running job."""
    # Auth check
    user_id = session.get('user_id')
    if not user_id:
        logger.warning(f"POST /api/jobs/{job_id}/cancel - Authentication failed: no user_id in session")
        return jsonify({"error": "Authentication required"}), 401

    logger.info(f"POST /api/jobs/{job_id}/cancel - Request received: user_id={user_id}, job_id={job_id}")

    # Query job by ID
    try:
        job = db_manager.execute_query(
            '''SELECT id, user_id, status
               FROM serverless_jobs WHERE id = %s''',
            (job_id,),
            fetch_one=True
        )
    except Exception as e:
        logger.error(f"Failed to query job {job_id}: {e}")
        return jsonify({"error": "Failed to retrieve job"}), 500

    # 404 if job not found
    if not job:
        return jsonify({"error": "Job not found"}), 404

    # Ownership check: must be job owner or admin
    job_user_id = job[1]
    is_admin = session.get('is_admin', False)
    if job_user_id != user_id and not is_admin:
        return jsonify({"error": "Access denied"}), 403

    # Check if job is in a cancellable state
    job_status = job[2]
    cancellable_states = ('pending', 'running')
    if job_status not in cancellable_states:
        return jsonify({"error": "Job cannot be cancelled"}), 409

    # Update job status to cancelled
    try:
        db_manager.execute_query(
            '''UPDATE serverless_jobs SET status = %s, completed_at = CURRENT_TIMESTAMP
               WHERE id = %s''',
            ('cancelled', job_id)
        )
    except Exception as e:
        logger.error(f"Failed to cancel job {job_id}: {e}")
        return jsonify({"error": "Failed to cancel job"}), 500

    logger.info(f"Job cancelled: job_id={job_id}, user_id={user_id}")

    return jsonify({"message": "Job cancelled", "job_id": str(job[0])}), 200
