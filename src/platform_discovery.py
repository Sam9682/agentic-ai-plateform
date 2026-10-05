"""Platform discovery and role management for multi-server SwAutoMorph"""
import requests
import socket
from typing import Optional, Dict

DISCOVERY_TIMEOUT = 5

def get_current_server_ip() -> str:
    """Get current server IP address"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

def check_remote_platform(remote_ip: str, port: int = 443) -> Optional[Dict]:
    """Check if remote IP is running SwAutoMorph and get its status"""
    try:
        url = f"https://{remote_ip}:{port}/api/platform/status"
        response = requests.get(url, timeout=DISCOVERY_TIMEOUT, verify=False)
        if response.status_code == 200:
            return response.json()
    except:
        try:
            url = f"http://{remote_ip}:{port}/api/platform/status"
            response = requests.get(url, timeout=DISCOVERY_TIMEOUT)
            if response.status_code == 200:
                return response.json()
        except:
            pass
    return None

def determine_role(current_ip: str, remote_ip: str, remote_status: Dict, db_manager) -> str:
    """Determine if current server should be PRIMARY or SECONDARY
    
    Returns: 'PRIMARY' or 'SECONDARY'
    """
    # If remote is PRIMARY, we become SECONDARY
    if remote_status.get('role') == 'PRIMARY':
        return 'SECONDARY'
    
    # Manual decision - keep current role
    current_server = db_manager.execute_query(
        'SELECT server_type FROM servers WHERE server_ip = %s',
        (current_ip,), fetch_one=True
    )
    
    if current_server:
        return current_server[0].upper()
    
    return 'PRIMARY'

def update_server_role(server_ip: str, role: str, db_manager):
    """Update server role in database"""
    db_manager.execute_query(
        'UPDATE servers SET server_type = %s WHERE server_ip = %s',
        (role, server_ip)
    )
