"""Database health monitoring utilities"""
# import sqlite3  # COMMENTED OUT - Using PostgreSQL now
import time
from .database_postgres import db_manager

def check_database_health():
    """Check database health and return status"""
    try:
        # Test basic connectivity
        result = db_manager.execute_query('SELECT 1', fetch_one=True)
        if result and result[0] == 1:
            # Test table access - COMMENTED OUT for PostgreSQL migration
            # tables = db_manager.execute_query(
            #     "SELECT name FROM sqlite_master WHERE type='table'",
            #     fetch_all=True
            # )
            
            # Check WAL mode - COMMENTED OUT for PostgreSQL migration
            # wal_mode = db_manager.execute_query('PRAGMA journal_mode', fetch_one=True)
            
            return {
                'status': 'healthy',
                'tables_count': 0,  # Placeholder for PostgreSQL
                'journal_mode': 'postgresql',  # PostgreSQL doesn't use WAL mode like SQLite
                'timestamp': time.time()
            }
    except Exception as e:
        return {
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': time.time()
        }

def optimize_database():
    """Optimize database performance - COMMENTED OUT for PostgreSQL migration"""
    try:
        # Run VACUUM to optimize database - SQLite specific, not needed for PostgreSQL
        # with db_manager.get_db_connection() as conn:
        #     conn.execute('VACUUM')
        #     conn.execute('ANALYZE')
        return {'status': 'postgresql_no_vacuum_needed', 'timestamp': time.time()}
    except Exception as e:
        return {'status': 'failed', 'error': str(e), 'timestamp': time.time()}

def get_database_stats():
    """Get database statistics"""
    try:
        stats = {}
        
        # Get table row counts
        tables = ['application_costs', 'applications', 'auth_tokens', 'billing_activities', 'configuration', 'deployments', 'invoicing', 'payment_modes', 'servers', 'user_applications', 'users', 'users_logs', 'instances', 'services']
        for table in tables:
            count = db_manager.execute_query(f'SELECT COUNT(*) FROM {table}', fetch_one=True)
            stats[f'{table}_count'] = count[0] if count else 0
        
        # PostgreSQL database size
        size_query = "SELECT pg_database_size(current_database())"
        size_result = db_manager.execute_query(size_query, fetch_one=True)
        stats['database_size_bytes'] = size_result[0] if size_result else 0
        
        return stats
    except Exception as e:
        return {'error': str(e)}