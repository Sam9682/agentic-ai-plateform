#!/usr/bin/env python3
"""
Helper script to add backup entries to deployment's backups_history.
This script is called after a successful database backup operation.

Usage:
    python3 add_backup_to_deployment.py --deployment-id <id> --backup-file <file> --s3-location <url> [options]
"""

import sys
import os
import argparse
import json
from datetime import datetime

# Add parent directory to path to import database manager
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database_postgres import DatabaseManager

def add_backup_entry(deployment_id, backup_file, s3_location, backup_size=None, server_ip=None, user_id=None):
    """Add a backup entry to deployment's backups_history"""
    
    db_manager = DatabaseManager()
    
    try:
        # Create backup entry
        backup_entry = {
            'backup_file': backup_file,
            's3_location': s3_location,
            'backup_size': backup_size,
            'backup_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'server_ip': server_ip,
            'created_by': user_id
        }
        
        # Append to backups_history using PostgreSQL JSONB operations
        db_manager.execute_query('''
            UPDATE deployments 
            SET backups_history = COALESCE(backups_history, '[]'::jsonb) || %s::jsonb,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        ''', (json.dumps(backup_entry), deployment_id))
        
        print(f"✓ Backup entry added successfully to deployment {deployment_id}")
        print(f"  Backup file: {backup_file}")
        print(f"  S3 location: {s3_location}")
        print(f"  Backup size: {backup_size or 'N/A'}")
        print(f"  Server IP: {server_ip or 'N/A'}")
        
        return True
        
    except Exception as e:
        print(f"✗ Error adding backup entry: {str(e)}", file=sys.stderr)
        return False

def main():
    parser = argparse.ArgumentParser(description='Add backup entry to deployment backups_history')
    parser.add_argument('--deployment-id', type=int, required=True, help='Deployment ID')
    parser.add_argument('--backup-file', required=True, help='Backup file name')
    parser.add_argument('--s3-location', required=True, help='S3 location URL')
    parser.add_argument('--backup-size', help='Backup file size (e.g., 10M, 1.5G)')
    parser.add_argument('--server-ip', help='Server IP address')
    parser.add_argument('--user-id', type=int, help='User ID who created the backup')
    
    args = parser.parse_args()
    
    success = add_backup_entry(
        deployment_id=args.deployment_id,
        backup_file=args.backup_file,
        s3_location=args.s3_location,
        backup_size=args.backup_size,
        server_ip=args.server_ip,
        user_id=args.user_id
    )
    
    sys.exit(0 if success else 1)

if __name__ == '__main__':
    main()
