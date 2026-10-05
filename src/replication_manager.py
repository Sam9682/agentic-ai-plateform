"""
Event-Driven Database Replication Manager
Handles synchronization of critical tables across SwAutoMorph servers
"""
import threading
import queue
import time
import uuid
import requests
import urllib3
import logging
from datetime import datetime
from functools import wraps

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

# Tables to replicate (business-critical only)
REPLICATED_TABLES = {
    'USERS', 'SERVERS', 'APPLICATIONS', 'USER_APPLICATIONS', 'APPLICATION_COSTS', 'PAYMENT_MODES',
    'BILLING_ACTIVITES', 'AUTH_TOKENS'
}

# Global sync queue
sync_queue = queue.Queue()

# Recent events log (for monitoring) - only PENDING events
pending_events = {}
pending_events_lock = threading.Lock()
MAX_PENDING_EVENTS = 1000

# Shared secret for server authentication (should be in config)
SYNC_SECRET = None

class ReplicationManager:
    def __init__(self, db_manager, sync_secret=None):
        self.db_manager = db_manager
        self.sync_secret = sync_secret or 'secret-softfluid'
        self.worker_thread = None
        self.running = False
        global SYNC_SECRET
        SYNC_SECRET = self.sync_secret
        
    def start_worker(self):
        """Start background worker for async replication"""
        if self.worker_thread and self.worker_thread.is_alive():
            return
        
        self.running = True
        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker_thread.start()
        logger.info("[REPLICATION] Worker started")
    
    def stop_worker(self):
        """Stop background worker"""
        self.running = False
        if self.worker_thread:
            self.worker_thread.join(timeout=5)
        logger.info("[REPLICATION] Worker stopped")
    
    def _worker_loop(self):
        """Background worker that processes sync queue"""
        retry_queue = []
        
        while self.running:
            try:
                # Process new events
                try:
                    event = sync_queue.get(timeout=1)
                    success = self._propagate_event(event)
                    # Remove from pending events after successful propagation
                    if success:
                        with pending_events_lock:
                            pending_events.pop(event['event_id'], None)
                except queue.Empty:
                    pass
                
                # Retry failed events
                if retry_queue:
                    event = retry_queue.pop(0)
                    if not self._propagate_event(event):
                        event['retry_count'] = event.get('retry_count', 0) + 1
                        if event['retry_count'] < 3:
                            retry_queue.append(event)
                        else:
                            logger.error(f"[REPLICATION] Event {event['event_id']} failed after 3 retries")
                            # Remove from pending after max retries
                            with pending_events_lock:
                                pending_events.pop(event['event_id'], None)
                
                time.sleep(0.1)
            except Exception as e:
                logger.error(f"[REPLICATION] Worker error: {e}")
    
    def _propagate_event(self, event):
        """Send event to all peer servers"""
        peers = self._get_peer_servers()
        success = True
        
        for peer_ip in peers:
            # Try HTTPS first, fallback to HTTP
            for protocol in ['https', 'http']:
                try:
                    response = requests.post(
                        f"{protocol}://{peer_ip}/api/sync/replicate",
                        json=event,
                        headers={'X-Sync-Token': self.sync_secret},
                        timeout=5,
                        verify=False
                    )
                    
                    if response.status_code == 200:
                        logger.info(f"[REPLICATION] Synced {event['table']}.{event['operation']} to {peer_ip} via {protocol.upper()}")
                        break
                    else:
                        logger.warning(f"[REPLICATION] Failed to sync to {peer_ip} via {protocol.upper()}: {response.status_code}")
                        if protocol == 'http':
                            success = False
                except requests.exceptions.ConnectionError:
                    if protocol == 'http':
                        logger.error(f"[REPLICATION] Cannot connect to {peer_ip} on HTTPS or HTTP")
                        success = False
                except Exception as e:
                    if protocol == 'http':
                        logger.error(f"[REPLICATION] Error syncing to {peer_ip}: {e}")
                        success = False
        
        return success
    
    def _get_peer_servers(self):
        """Get list of peer server IPs"""
        try:
            servers = self.db_manager.execute_query(
                "SELECT server_ip FROM servers WHERE server_status != 'DISABLED'",
                fetch_all=True
            )
            # Exclude current server
            current_ip = self._get_current_ip()
            return [s[0] for s in servers if s[0] != current_ip]
        except:
            return []
    
    def _get_current_ip(self):
        """Get current server IP"""
        import socket
        try:
            return socket.gethostbyname(socket.gethostname())
        except:
            return '127.0.0.1'

# Decorator for automatic replication
def replicate(table, operation='INSERT'):
    """Decorator to automatically replicate database operations"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Execute original function
            result = func(*args, **kwargs)
            
            # Only replicate if table is in whitelist
            if table.upper() not in REPLICATED_TABLES:
                return result
            
            # Queue replication event
            try:
                event = {
                    'event_id': str(uuid.uuid4()),
                    'timestamp': datetime.utcnow().isoformat(),
                    'table': table,
                    'operation': operation,
                    'data': kwargs.get('data', {}),
                    'primary_key': kwargs.get('pk', {}),
                    'version': int(time.time() * 1000)  # Millisecond timestamp as version
                }
                sync_queue.put(event)
                
                # Add to pending events (will be removed after processing)
                with pending_events_lock:
                    pending_events[event['event_id']] = event
                    # Cleanup old events if too many
                    if len(pending_events) > MAX_PENDING_EVENTS:
                        oldest_key = next(iter(pending_events))
                        pending_events.pop(oldest_key)
                
                logger.debug(f"[REPLICATION] Queued {table}.{operation}")
            except Exception as e:
                logger.error(f"[REPLICATION] Failed to queue event: {e}")
            
            return result
        return wrapper
    return decorator

def queue_replication_event(table, operation, data, primary_key=None):
    """Manually queue a replication event"""
    if table.upper() not in REPLICATED_TABLES:
        return
    
    event = {
        'event_id': str(uuid.uuid4()),
        'timestamp': datetime.utcnow().isoformat(),
        'table': table,
        'operation': operation,
        'data': data,
        'primary_key': primary_key or {},
        'version': int(time.time() * 1000)
    }
    sync_queue.put(event)
    
    # Add to pending events (will be removed after processing)
    with pending_events_lock:
        pending_events[event['event_id']] = event
        # Cleanup old events if too many
        if len(pending_events) > MAX_PENDING_EVENTS:
            oldest_key = next(iter(pending_events))
            pending_events.pop(oldest_key)
    
    logger.debug(f"[REPLICATION] Queued {table}.{operation}")

def apply_replication_event(db_manager, event):
    """Apply a replication event to local database"""
    table = event['table']
    operation = event['operation']
    data = event['data']
    pk = event.get('primary_key', {})
    version = event.get('version', 0)
    
    # Check for conflicts (version-based)
    if pk and operation in ['UPDATE', 'DELETE']:
        pk_col = list(pk.keys())[0]
        pk_val = pk[pk_col]
        
        existing = db_manager.execute_query(
            f"SELECT updated_at FROM {table} WHERE {pk_col} = %s",
            (pk_val,), fetch_one=True
        )
        
        if existing:
            # Simple conflict resolution: newer version wins
            existing_version = int(existing[0].timestamp() * 1000) if existing[0] else 0
            if existing_version > version:
                logger.info(f"[REPLICATION] Skipping {table}.{operation} - local version newer")
                return False
    
    # Apply operation
    try:
        if operation == 'INSERT':
            columns = ', '.join(data.keys())
            placeholders = ', '.join(['%s'] * len(data))
            # Use UPSERT to update existing records instead of skipping
            update_clause = ', '.join([f"{k} = EXCLUDED.{k}" for k in data.keys() if k != 'id'])
            query = f"INSERT INTO {table} ({columns}) VALUES ({placeholders}) ON CONFLICT (id) DO UPDATE SET {update_clause}"
            db_manager.execute_query(query, tuple(data.values()))
            
        elif operation == 'UPDATE':
            set_clause = ', '.join([f"{k} = %s" for k in data.keys()])
            pk_col = list(pk.keys())[0]
            query = f"UPDATE {table} SET {set_clause} WHERE {pk_col} = %s"
            db_manager.execute_query(query, tuple(data.values()) + (pk[pk_col],))
            
        elif operation == 'DELETE':
            pk_col = list(pk.keys())[0]
            query = f"DELETE FROM {table} WHERE {pk_col} = %s"
            db_manager.execute_query(query, (pk[pk_col],))
        
        logger.info(f"[REPLICATION] Applied {table}.{operation}")
        return True
    except Exception as e:
        logger.error(f"[REPLICATION] Failed to apply {table}.{operation}: {e}")
        return False
