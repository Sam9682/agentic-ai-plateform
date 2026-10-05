"""Database synchronization between PRIMARY and SECONDARY servers"""
import requests
import json
from typing import List, Dict, Optional

SYNC_TIMEOUT = 30

class DatabaseSync:
    """Handle database synchronization between PRIMARY and SECONDARY"""
    
    def __init__(self, db_manager):
        self.db_manager = db_manager
    
    def get_primary_server(self) -> Optional[Dict]:
        """Get PRIMARY server information"""
        result = self.db_manager.execute_query(
            "SELECT server_ip, server_name FROM servers WHERE server_type = 'PRIMARY' LIMIT 1",
            fetch_one=True
        )
        if result:
            return {'ip': result[0], 'name': result[1]}
        return None
    
    def sync_from_primary(self, primary_ip: str, tables: List[str] = None) -> bool:
        """Sync specified tables from PRIMARY server
        
        Args:
            primary_ip: IP address of PRIMARY server
            tables: List of table names to sync (default: all critical tables)
        
        Returns:
            True if sync successful, False otherwise
        """
        if tables is None:
            tables = ['users', 'applications', 'servers', 'deployments', 
                     'user_applications', 'application_costs']
        
        try:
            for table in tables:
                url = f"https://{primary_ip}/api/database/tables/{table}"
                response = requests.get(url, timeout=SYNC_TIMEOUT, verify=False)
                
                if response.status_code == 200:
                    data = response.json()
                    self._sync_table(table, data)
                else:
                    return False
            
            return True
        except Exception as e:
            print(f"Sync failed: {e}")
            return False
    
    def _sync_table(self, table: str, data: Dict):
        """Sync a single table with data from PRIMARY"""
        # Implementation depends on sync strategy (full replace, incremental, etc.)
        pass
    
    def check_primary_health(self, primary_ip: str) -> bool:
        """Check if PRIMARY server is healthy"""
        try:
            url = f"https://{primary_ip}/api/platform/status"
            response = requests.get(url, timeout=5, verify=False)
            return response.status_code == 200
        except:
            return False
