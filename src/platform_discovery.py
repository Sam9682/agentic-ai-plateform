"""Platform discovery and role management for multi-server SwAutoMorph"""
import requests
import socket
from typing import Optional, Dict

DISCOVERY_TIMEOUT = 5

# --- Reconciliation remediation health inputs (Phase 4, R4.1/R4.6/R8.4) ---
# These constants expose the retry + grace inputs that the orchestrator's
# remediation state machine consumes. They are plain values so the health
# evaluation stays pure and unit-testable without live Docker/PostgreSQL.

# Healthy iff the probe returned HTTP 200.
HEALTHY_STATUS_CODE = 200
# Bounded retry for the HTTP health probe (consumed by run_with_policy in the
# orchestrator). A short bound keeps a single reconcile pass fast.
HEALTH_PROBE_MAX_ATTEMPTS = 3
# Default grace window (seconds) applied after an instance's started_at before
# a failing probe is allowed to trigger remediation (R4.1/R4.6).
HEALTH_GRACE_PERIOD_SECONDS = 60


def evaluate_health(status_code: Optional[int], now: float,
                    grace_until: Optional[float]) -> Dict[str, bool]:
    """Pure health evaluation for reconciliation remediation.

    Pure and unit-testable without live Docker/PostgreSQL (R8.4). Given a probe
    ``status_code``, the current time ``now``, and an optional ``grace_until``
    deadline, return the two inputs the remediation state machine needs:

      * ``healthy`` — the probe succeeded (HTTP 200).
      * ``within_grace`` — ``now`` is still inside the grace window, so a
        failing probe must NOT remediate yet (R4.1).

    Returns ``{'healthy': bool, 'within_grace': bool}``.
    """
    healthy = status_code == HEALTHY_STATUS_CODE
    within_grace = grace_until is not None and now < grace_until
    return {"healthy": healthy, "within_grace": within_grace}

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
