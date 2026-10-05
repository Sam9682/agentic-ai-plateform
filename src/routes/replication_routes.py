"""
Replication API Routes
Handles incoming replication events from peer servers
"""
from flask import Blueprint, request, jsonify
import logging, os
from datetime import datetime
from src.replication_manager import apply_replication_event, SYNC_SECRET

# Configure logging for activities
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# File handler
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
log_file = os.path.join(PROJECT_ROOT, 'logs', 'replication_routes.log')
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

replication_bp = Blueprint('replication', __name__)

# Will be set by main app
db_manager = None

def init_replication_routes(database_manager, sync_secret):
    """Initialize replication routes with database manager"""
    global db_manager, SYNC_SECRET
    db_manager = database_manager
    SYNC_SECRET = sync_secret

@replication_bp.route('/api/sync/replicate', methods=['POST'])
def receive_replication():
    """Receive and apply replication event from peer server"""
    # Authenticate request
    token = request.headers.get('X-Sync-Token')
    if not token or token != SYNC_SECRET:
        logger.warning(f"[REPLICATION] Unauthorized sync attempt from {request.remote_addr}")
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        event = request.get_json()
        
        # Validate event structure
        required_fields = ['event_id', 'timestamp', 'table', 'operation', 'data']
        if not all(field in event for field in required_fields):
            return jsonify({'error': 'Invalid event structure'}), 400
        
        # Apply event to local database
        success = apply_replication_event(db_manager, event)
        
        if success:
            return jsonify({
                'status': 'applied',
                'event_id': event['event_id']
            }), 200
        else:
            return jsonify({
                'status': 'skipped',
                'event_id': event['event_id']
            }), 200
            
    except Exception as e:
        logger.error(f"[REPLICATION] Error processing event: {e}")
        return jsonify({'error': str(e)}), 500

@replication_bp.route('/api/sync/health', methods=['GET'])
def sync_health():
    """Check replication health status"""
    try:
        # Get sync statistics
        from src.replication_manager import sync_queue
        
        return jsonify({
            'status': 'healthy',
            'queue_size': sync_queue.qsize(),
            'timestamp': datetime.utcnow().isoformat()
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@replication_bp.route('/api/sync/status', methods=['GET'])
def sync_status():
    """Get detailed replication status"""
    try:
        # Get peer servers
        peers = db_manager.execute_query(
            "SELECT server_ip, server_name, server_type FROM servers WHERE server_status != 'DISABLED'",
            fetch_all=True
        )
        
        from src.replication_manager import sync_queue
        
        return jsonify({
            'queue_size': sync_queue.qsize(),
            'peer_count': len(peers),
            'peers': [{'ip': p[0], 'name': p[1], 'type': p[2]} for p in peers]
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
