#!/usr/bin/env python3
"""
Fix deployment records that have incorrect user_id.
This happens when admin clones applications for other users.
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database_postgres import db_manager
from src.config_postgres import LINUX_USER_INSTALLATION

def fix_deployment_user_ids():
    """Fix deployment records with incorrect user_id"""
    
    print("Fixing deployment user_id records...")
    
    # Get all deployments with potential mismatches
    deployments = db_manager.execute_query("""
        SELECT 
            d.id,
            d.user_id,
            d.deployment_path,
            d.application_name,
            u.username as current_username
        FROM deployments d
        JOIN users u ON d.user_id = u.id
    """, fetch_all=True)
    
    fixed_count = 0
    
    for deployment in deployments:
        dep_id, user_id, deployment_path, app_name, current_username = deployment
        
        # Extract username from deployment_path
        # Format: /home/{LINUX_USER_INSTALLATION}/deployments/{username}/{app-name}
        if deployment_path and deployment_path.startswith(f'/home/{LINUX_USER_INSTALLATION}/deployments/'):
            path_parts = deployment_path.split('/')
            if len(path_parts) >= 5:
                path_username = path_parts[4]
                
                # Check if username in path matches current user
                if path_username != current_username:
                    print(f"Found mismatch:")
                    print(f"  Deployment ID: {dep_id}")
                    print(f"  Application: {app_name}")
                    print(f"  Current user_id: {user_id} ({current_username})")
                    print(f"  Path username: {path_username}")
                    
                    # Get correct user_id
                    correct_user = db_manager.execute_query(
                        "SELECT id FROM users WHERE username = %s",
                        (path_username,), fetch_one=True
                    )
                    
                    if correct_user:
                        correct_user_id = correct_user[0]
                        print(f"  Correct user_id: {correct_user_id} ({path_username})")
                        
                        # Update the deployment record
                        db_manager.execute_query(
                            "UPDATE deployments SET user_id = %s WHERE id = %s",
                            (correct_user_id, dep_id)
                        )
                        print(f"  ✓ Fixed!")
                        fixed_count += 1
                    else:
                        print(f"  ✗ User '{path_username}' not found in database")
                    print()
    
    print(f"\nFixed {fixed_count} deployment record(s)")
    
    # Verify the fix
    print("\nVerifying all deployments...")
    deployments_home_prefix = f'/home/{LINUX_USER_INSTALLATION}/deployments/'
    deployments = db_manager.execute_query("""
        SELECT 
            d.id,
            d.user_id,
            u.username,
            d.deployment_path,
            d.application_name,
            CASE 
                WHEN d.deployment_path LIKE %s || u.username || '/%%' THEN 'CORRECT'
                ELSE 'MISMATCH'
            END as status
        FROM deployments d
        JOIN users u ON d.user_id = u.id
        ORDER BY d.id
    """, (deployments_home_prefix,), fetch_all=True)
    
    print(f"\n{'ID':<5} {'User ID':<10} {'Username':<15} {'Application':<20} {'Status':<10}")
    print("-" * 70)
    
    mismatch_count = 0
    for dep in deployments:
        dep_id, user_id, username, path, app_name, status = dep
        print(f"{dep_id:<5} {user_id:<10} {username:<15} {app_name:<20} {status:<10}")
        if status == 'MISMATCH':
            mismatch_count += 1
    
    if mismatch_count > 0:
        print(f"\n⚠️  Warning: {mismatch_count} deployment(s) still have mismatches")
    else:
        print(f"\n✓ All deployments verified successfully!")

if __name__ == '__main__':
    try:
        fix_deployment_user_ids()
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
