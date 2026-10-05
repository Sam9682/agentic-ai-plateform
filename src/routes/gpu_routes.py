"""API routes for MIG Shared GPU Management"""
from flask import Blueprint, request, jsonify, session
from ..database_postgres import db_manager
import subprocess
import os
import re
import logging

# Configure logging for GPU management activities
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# File handler
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
log_file = os.path.join(PROJECT_ROOT, 'logs', 'gpu_routes.log')
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

gpu_bp = Blueprint('gpu', __name__, url_prefix='/api/servers/<int:server_id>/gpu')


def require_admin():
    """Check if user is authenticated and is an admin.
    
    Returns:
        tuple: (None, None) if authorized, or (response, status_code) on failure.
    """
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'Authentication required'}), 401

    is_admin = session.get('is_admin', False)
    if not is_admin:
        return jsonify({'error': 'Admin access required'}), 403

    return None, None


def get_server_ip(server_id):
    """Query the servers table to get the IP address for a given server ID.
    
    Args:
        server_id: Integer ID of the server.
        
    Returns:
        str: The server IP address, or None if server not found.
    """
    result = db_manager.execute_query(
        'SELECT server_ip FROM servers WHERE id = %s',
        (server_id,),
        fetch_one=True
    )
    if result:
        return result[0]
    return None


def ssh_execute(server_ip, command, timeout=30):
    """Execute a command on a remote server via SSH.
    
    Uses subprocess.run() with StrictHostKeyChecking=no and UserKnownHostsFile=/dev/null
    to avoid interactive prompts.
    
    Args:
        server_ip: IP address of the target server.
        command: Shell command string to execute remotely.
        timeout: Maximum execution time in seconds (default 30).
        
    Returns:
        tuple: (success: bool, stdout: str, stderr: str)
    """
    ssh_cmd = [
        'ssh',
        '-o', 'StrictHostKeyChecking=no',
        '-o', 'UserKnownHostsFile=/dev/null',
        f'ubuntu@{server_ip}',
        command
    ]

    logger.info(f"Executing SSH command on {server_ip}: {command}")

    try:
        result = subprocess.run(
            ssh_cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )

        if result.returncode == 0:
            logger.info(f"SSH command succeeded on {server_ip}")
            return True, result.stdout, result.stderr
        else:
            logger.warning(f"SSH command failed on {server_ip} (exit code {result.returncode}): {result.stderr[:512]}")
            return False, result.stdout, result.stderr

    except subprocess.TimeoutExpired:
        logger.error(f"SSH command timed out on {server_ip} after {timeout}s")
        return False, '', f'Command timed out after {timeout} seconds'
    except Exception as e:
        logger.error(f"SSH execution error on {server_ip}: {str(e)}")
        return False, '', str(e)


def parse_mig_instances(output):
    """Parse `nvidia-smi -L` output to extract MIG instance entries.

    Looks for lines containing MIG device UUIDs and extracts the UUID
    and associated profile name for each MIG device.

    Example input line:
      MIG 1g.10gb     Device  0: (UUID: MIG-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee)

    Args:
        output: String output from `nvidia-smi -L` command.

    Returns:
        list[dict]: List of dicts with keys 'instance_uuid' (str) and 'profile_name' (str).
    """
    instances = []
    if not output:
        return instances

    # Pattern matches MIG device lines:
    # "  MIG <profile_name>     Device  N: (UUID: MIG-<uuid>)"
    # Captures:
    #   group(1) = profile name (e.g. "1g.10gb")
    #   group(2) = full MIG UUID (e.g. "MIG-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    mig_pattern = re.compile(
        r'MIG\s+(\S+)\s+Device\s+\d+:\s+\(UUID:\s+(MIG-[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\)'
    )

    for line in output.splitlines():
        match = mig_pattern.search(line)
        if match:
            profile_name = match.group(1)
            instance_uuid = match.group(2)
            instances.append({
                'instance_uuid': instance_uuid,
                'profile_name': profile_name
            })

    return instances


def validate_profile_ids(profile_ids):
    """Validate a list of profile IDs for MIG instance creation.
    
    The list must contain between 1 and 7 entries (inclusive).
    
    Args:
        profile_ids: List of profile ID strings.
        
    Returns:
        str: Error message if validation fails, None if valid.
    """
    if not profile_ids or len(profile_ids) > 7:
        return "profile_ids must contain 1 to 7 entries"
    return None


def parse_mig_profiles(output):
    """Parse nvidia-smi mig -lgip output into a list of MIG profile dicts.

    Each returned dict has keys:
        - profile_id (int): The numeric profile ID
        - name (str): The MIG profile name (e.g. "MIG 1g.10gb")
        - memory_mib (int): Memory size converted from GiB to MiB

    Args:
        output: Raw string output from `nvidia-smi mig -lgip`.

    Returns:
        list[dict]: Parsed MIG profile entries. Returns empty list for empty
            or unparseable output.
    """
    if not output or not output.strip():
        return []

    profiles = []

    # Pattern matches lines like:
    # |   0  MIG 1g.10gb       9     7/7        9.50       No     16     1     0   |
    # Fields: GPU_index, Name (MIG Xg.Ygb), ID, Free/Total, Memory_GiB, ...
    pattern = re.compile(
        r'\|\s+\d+\s+'           # | followed by GPU index
        r'(MIG\s+\S+)\s+'       # capture group 1: profile name (e.g. "MIG 1g.10gb")
        r'(\d+)\s+'             # capture group 2: profile ID
        r'\d+/\d+\s+'           # Free/Total instances (e.g. "7/7")
        r'([\d.]+)\s+'          # capture group 3: memory in GiB (e.g. "9.50")
    )

    for line in output.splitlines():
        match = pattern.search(line)
        if match:
            name = match.group(1).strip()
            profile_id = int(match.group(2))
            memory_gib = float(match.group(3))
            memory_mib = int(memory_gib * 1024)

            profiles.append({
                'profile_id': profile_id,
                'name': name,
                'memory_mib': memory_mib,
            })

    return profiles


def build_mig_create_command(profile_ids):
    """Construct the nvidia-smi MIG instance creation command.
    
    Builds the command string to create MIG GPU instances from a list of profile IDs.
    The profile IDs are joined with commas in their original order.
    
    Args:
        profile_ids: List of profile ID strings (e.g., ["9", "14", "9"]).
        
    Returns:
        str: The full command string, e.g. "sudo nvidia-smi mig -cgi 9,14,9 -C"
    """
    ids_str = ','.join(profile_ids)
    return f'sudo nvidia-smi mig -cgi {ids_str} -C'


@gpu_bp.route('/profiles', methods=['GET'])
def get_profiles(server_id):
    """List available MIG profiles from the server's GPU hardware.
    
    Executes nvidia-smi mig -lgip on the target server via SSH and returns
    the parsed list of available MIG profiles.
    
    Returns:
        JSON response with list of profiles, or error on failure.
    """
    # Auth check
    auth_error, status_code = require_admin()
    if auth_error:
        return auth_error, status_code

    # Validate server exists
    server_ip = get_server_ip(server_id)
    if not server_ip:
        return jsonify({'error': 'Server not found'}), 404

    # Execute nvidia-smi mig -lgip on the remote server
    success, stdout, stderr = ssh_execute(server_ip, 'nvidia-smi mig -lgip', timeout=30)

    if not success:
        # Distinguish between server unreachable and MIG not available
        error_msg = stderr.strip() if stderr else 'Unknown error'
        if 'timed out' in error_msg.lower() or 'connection refused' in error_msg.lower() or 'no route to host' in error_msg.lower():
            logger.error(f"Server {server_id} ({server_ip}) unreachable: {error_msg}")
            return jsonify({'error': f'Server unreachable: {error_msg}'}), 500
        else:
            logger.error(f"MIG profiles query failed on server {server_id} ({server_ip}): {error_msg}")
            return jsonify({'error': error_msg}), 500

    # Parse the output
    profiles = parse_mig_profiles(stdout)

    return jsonify({'profiles': profiles}), 200


@gpu_bp.route('/instances', methods=['GET'])
def get_instances(server_id):
    """List active MIG instances for a server from the database.
    
    Queries the mig_instances table for the given server and returns
    instances ordered by creation timestamp.
    
    Requirements: 5.1, 11.2
    """
    # Auth check
    auth_error, status_code = require_admin()
    if auth_error:
        return auth_error, status_code

    # Validate server exists
    server_ip = get_server_ip(server_id)
    if not server_ip:
        return jsonify({'error': 'Server not found'}), 404

    # Query mig_instances table for this server
    rows = db_manager.execute_query(
        'SELECT instance_uuid, profile_name, gpu_memory_mb, created_at '
        'FROM mig_instances WHERE server_id = %s ORDER BY created_at',
        (server_id,)
    )

    instances = []
    if rows:
        for row in rows:
            instance_uuid, profile_name, gpu_memory_mb, created_at = row
            instances.append({
                'instance_uuid': instance_uuid,
                'profile_name': profile_name,
                'gpu_memory_mb': gpu_memory_mb,
                'created_at': created_at.isoformat() if created_at else None
            })

    return jsonify({'instances': instances}), 200


@gpu_bp.route('/instances', methods=['POST'])
def create_instances(server_id):
    """Create MIG GPU instances from a list of profile IDs.
    
    Validates server exists and has shared_gpu_enabled=true, validates
    profile_ids (1-7 entries), then executes the MIG creation command
    via SSH. On success, retrieves instance details with nvidia-smi -L,
    parses UUIDs, and persists to the mig_instances table.
    
    Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 11.3, 11.9
    """
    # Auth check
    auth_error, status_code = require_admin()
    if auth_error:
        return auth_error, status_code

    # Validate server exists
    server_ip = get_server_ip(server_id)
    if not server_ip:
        return jsonify({'error': 'Server not found'}), 404

    # Check shared_gpu_enabled is true
    result = db_manager.execute_query(
        'SELECT shared_gpu_enabled FROM servers WHERE id = %s',
        (server_id,),
        fetch_one=True
    )
    if not result or not result[0]:
        return jsonify({'error': 'Shared GPU must be enabled first'}), 400

    # Get profile_ids from request body
    data = request.get_json(silent=True)
    if not data or 'profile_ids' not in data:
        return jsonify({'error': 'profile_ids must contain 1 to 7 entries'}), 400

    profile_ids = data['profile_ids']

    # Validate profile_ids
    validation_error = validate_profile_ids(profile_ids)
    if validation_error:
        return jsonify({'error': validation_error}), 400

    # Build and execute MIG creation command
    command = build_mig_create_command(profile_ids)
    success, stdout, stderr = ssh_execute(server_ip, command, timeout=30)

    if not success:
        error_msg = stderr[:4096] if stderr else 'MIG instance creation failed'
        logger.error(f"MIG creation failed on server {server_id} ({server_ip}): {error_msg}")
        return jsonify({'error': error_msg}), 500

    # On success, execute nvidia-smi -L to get instance details
    success_l, stdout_l, stderr_l = ssh_execute(server_ip, 'nvidia-smi -L', timeout=30)

    if not success_l:
        error_msg = stderr_l[:4096] if stderr_l else 'Detail retrieval failed'
        logger.error(f"nvidia-smi -L failed on server {server_id} ({server_ip}): {error_msg}")
        return jsonify({
            'error': 'Instances created but detail retrieval failed',
            'output': error_msg
        }), 500

    # Parse MIG instances from nvidia-smi -L output
    instances = parse_mig_instances(stdout_l)

    # Persist each instance to the mig_instances table
    created_instances = []
    for instance in instances:
        db_manager.execute_query(
            'INSERT INTO mig_instances (server_id, instance_uuid, profile_name, gpu_memory_mb) '
            'VALUES (%s, %s, %s, %s)',
            (server_id, instance['instance_uuid'], instance['profile_name'], 0)
        )
        created_instances.append({
            'instance_uuid': instance['instance_uuid'],
            'profile_name': instance['profile_name'],
            'gpu_memory_mb': 0
        })

    logger.info(f"Created {len(created_instances)} MIG instances on server {server_id}")

    return jsonify({
        'message': 'MIG instances created successfully',
        'instances': created_instances
    }), 201


@gpu_bp.route('/enabled', methods=['PUT'])
def set_shared_gpu_enabled(server_id):
    """Toggle the shared_gpu_enabled flag for a server.
    
    When enabling (enabled=true): updates the DB flag, then executes
    `sudo nvidia-smi -mig 1` on the server via SSH. If the MIG command
    fails, reverts the DB flag to false and returns an error.
    
    When disabling (enabled=false): only updates the DB flag (no CLI command).
    
    Requirements: 3.2, 3.3, 3.4, 10.7, 10.8, 10.9, 11.5
    """
    # Check admin authentication
    auth_error, status_code = require_admin()
    if auth_error:
        return auth_error, status_code

    # Validate request body
    data = request.get_json(silent=True)
    if data is None or 'enabled' not in data or not isinstance(data['enabled'], bool):
        return jsonify({'error': "Field 'enabled' must be a boolean"}), 400

    enabled = data['enabled']

    # Check server exists
    server_ip = get_server_ip(server_id)
    if not server_ip:
        return jsonify({'error': 'Server not found'}), 404

    # Update the shared_gpu_enabled column
    db_manager.execute_query(
        'UPDATE servers SET shared_gpu_enabled = %s WHERE id = %s',
        (enabled, server_id)
    )

    # When enabling, execute MIG mode command on the server
    if enabled:
        success, stdout, stderr = ssh_execute(server_ip, 'sudo nvidia-smi -mig 1', timeout=30)
        if not success:
            # Revert the DB flag to false
            db_manager.execute_query(
                'UPDATE servers SET shared_gpu_enabled = %s WHERE id = %s',
                (False, server_id)
            )
            error_msg = stderr.strip() if stderr else 'Unknown error'
            logger.error(f"Server {server_id}: MIG mode enable failed, reverted shared_gpu_enabled to false: {error_msg}")
            return jsonify({'error': f'MIG mode could not be enabled: {error_msg}'}), 500

    logger.info(f"Server {server_id}: shared_gpu_enabled set to {enabled}")

    return jsonify({
        'server_id': server_id,
        'shared_gpu_enabled': enabled
    }), 200


@gpu_bp.route('/instances', methods=['DELETE'])
def delete_instances(server_id):
    """Destroy all MIG instances on a server.
    
    Executes `sudo nvidia-smi mig -dci` then `sudo nvidia-smi mig -dgi` via SSH.
    Only removes DB records if both commands succeed. If -dci succeeds but -dgi fails,
    returns an error without modifying DB records (state is inconsistent).
    
    Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 11.4
    """
    # Auth check
    auth_error, status_code = require_admin()
    if auth_error:
        return auth_error, status_code

    # Validate server exists
    server_ip = get_server_ip(server_id)
    if not server_ip:
        return jsonify({'error': 'Server not found'}), 404

    # Check that MIG instances exist for this server
    result = db_manager.execute_query(
        'SELECT COUNT(*) FROM mig_instances WHERE server_id = %s',
        (server_id,),
        fetch_one=True
    )
    instance_count = result[0] if result else 0

    if instance_count == 0:
        return jsonify({'error': 'No MIG instances configured on this server'}), 400

    # Step 1: Destroy compute instances
    success, stdout, stderr = ssh_execute(server_ip, 'sudo nvidia-smi mig -dci', timeout=30)
    if not success:
        error_msg = stderr[:4096] if stderr else 'Unknown error'
        logger.error(f"Server {server_id}: -dci failed: {error_msg}")
        return jsonify({'error': f'Failed to destroy compute instances: {error_msg}'}), 500

    # Step 2: Destroy GPU instances
    success, stdout, stderr = ssh_execute(server_ip, 'sudo nvidia-smi mig -dgi', timeout=30)
    if not success:
        error_msg = stderr[:4096] if stderr else 'Unknown error'
        logger.error(f"Server {server_id}: -dgi failed after -dci succeeded (inconsistent state): {error_msg}")
        return jsonify({'error': f'Compute instances destroyed but GPU instance destruction failed (inconsistent state): {error_msg}'}), 500

    # Both commands succeeded — remove DB records
    db_manager.execute_query(
        'DELETE FROM mig_instances WHERE server_id = %s',
        (server_id,)
    )

    logger.info(f"Server {server_id}: all {instance_count} MIG instances destroyed successfully")

    return jsonify({
        'message': 'All MIG instances destroyed',
        'count': instance_count
    }), 200
