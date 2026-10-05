#!/usr/bin/env python3
"""
Test script for backups_history feature.
Tests database operations and API endpoints.
"""

import sys
import os
import json

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database_postgres import DatabaseManager

def test_backups_history():
    """Test backups_history functionality"""
    
    print("=" * 60)
    print("Testing Backups History Feature")
    print("=" * 60)
    
    db_manager = DatabaseManager()
    
    # Test 1: Check if backups_history column exists
    print("\n[Test 1] Checking if backups_history column exists...")
    try:
        result = db_manager.execute_query("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'deployments' 
            AND column_name = 'backups_history'
        """, fetch_one=True)
        
        if result:
            print(f"✓ Column exists: {result[0]} ({result[1]})")
        else:
            print("✗ Column does not exist. Run migration first:")
            print("  psql -U swautomorph -d ai_swautomorph -f migration/add_backups_history_to_deployments.sql")
            return False
    except Exception as e:
        print(f"✗ Error checking column: {e}")
        return False
    
    # Test 2: Check if index exists
    print("\n[Test 2] Checking if GIN index exists...")
    try:
        result = db_manager.execute_query("""
            SELECT indexname 
            FROM pg_indexes 
            WHERE tablename = 'deployments' 
            AND indexname = 'idx_deployments_backups_history'
        """, fetch_one=True)
        
        if result:
            print(f"✓ Index exists: {result[0]}")
        else:
            print("⚠ Index does not exist (optional but recommended)")
    except Exception as e:
        print(f"⚠ Error checking index: {e}")
    
    # Test 3: Get a sample deployment
    print("\n[Test 3] Finding a sample deployment...")
    try:
        deployment = db_manager.execute_query("""
            SELECT id, user_id, application_name, backups_history 
            FROM deployments 
            ORDER BY updated_at DESC 
            LIMIT 1
        """, fetch_one=True)
        
        if deployment:
            dep_id, user_id, app_name, backups = deployment
            print(f"✓ Found deployment: ID={dep_id}, App={app_name}")
            print(f"  Current backups count: {len(backups) if backups else 0}")
            
            # Test 4: Add a test backup entry
            print("\n[Test 4] Adding test backup entry...")
            test_backup = {
                'backup_file': 'test_backup_20260228_143022.sql.gz',
                's3_location': 's3://test-bucket/test-app/192.168.1.100/backups/test_backup_20260228_143022.sql.gz',
                'backup_size': '10.5M',
                'backup_date': '2026-02-28 14:30:22',
                'server_ip': '192.168.1.100',
                'created_by': user_id
            }
            
            db_manager.execute_query("""
                UPDATE deployments 
                SET backups_history = COALESCE(backups_history, '[]'::jsonb) || %s::jsonb,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (json.dumps(test_backup), dep_id))
            
            print(f"✓ Test backup entry added to deployment {dep_id}")
            
            # Test 5: Verify the backup was added
            print("\n[Test 5] Verifying backup entry...")
            updated = db_manager.execute_query("""
                SELECT backups_history 
                FROM deployments 
                WHERE id = %s
            """, (dep_id,), fetch_one=True)
            
            if updated and updated[0]:
                backups_list = updated[0]
                print(f"✓ Backups history retrieved: {len(backups_list)} entries")
                
                # Find our test backup
                found = False
                for backup in backups_list:
                    if backup.get('backup_file') == test_backup['backup_file']:
                        found = True
                        print(f"✓ Test backup found:")
                        print(f"  File: {backup['backup_file']}")
                        print(f"  S3: {backup['s3_location']}")
                        print(f"  Size: {backup['backup_size']}")
                        print(f"  Date: {backup['backup_date']}")
                        break
                
                if not found:
                    print("✗ Test backup not found in history")
                    return False
            else:
                print("✗ Failed to retrieve backups history")
                return False
            
            # Test 6: Query backups by date
            print("\n[Test 6] Testing JSONB query capabilities...")
            result = db_manager.execute_query("""
                SELECT id, application_name, 
                       jsonb_array_length(backups_history) as backup_count
                FROM deployments 
                WHERE backups_history IS NOT NULL 
                  AND jsonb_array_length(backups_history) > 0
                LIMIT 5
            """, fetch_all=True)
            
            if result:
                print(f"✓ Found {len(result)} deployments with backups:")
                for row in result:
                    print(f"  - Deployment {row[0]} ({row[1]}): {row[2]} backups")
            else:
                print("⚠ No deployments with backups found")
            
            print("\n" + "=" * 60)
            print("All tests passed! ✓")
            print("=" * 60)
            print("\nNext steps:")
            print("1. Test in dashboard: Navigate to Deployments Management")
            print("2. Test API: curl -X GET http://localhost:5000/api/deployments/{}/backups".format(dep_id))
            print("3. Test CLI: python3 scripts/add_backup_to_deployment.py --help")
            return True
            
        else:
            print("⚠ No deployments found in database")
            print("  Create a deployment first to test this feature")
            return False
            
    except Exception as e:
        print(f"✗ Error during testing: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    success = test_backups_history()
    sys.exit(0 if success else 1)
