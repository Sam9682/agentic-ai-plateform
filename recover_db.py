#!/usr/bin/env python3
"""Database recovery script for AI-SwAutoMorph"""

import os
import sys
# import sqlite3  # COMMENTED OUT - Using PostgreSQL now
import shutil
from datetime import datetime

# Add project root to path to import config
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from src.config_postgres import PLTF_FOLDER, LINUX_USER_INSTALLATION

def recover_database():
    """Recover corrupted database by creating a new one"""
    
    db_path = f"/home/{LINUX_USER_INSTALLATION}/{PLTF_FOLDER}/softfluid/db/ai_swautomorph.db"
    backup_path = f"{db_path}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    print("Starting database recovery...")
    
    # 1. Backup corrupted database
    if os.path.exists(db_path):
        shutil.copy2(db_path, backup_path)
        print(f"Corrupted database backed up to: {backup_path}")
    
    # 2. Remove corrupted files
    for file_ext in ['', '-shm', '-wal']:
        file_path = f"{db_path}{file_ext}"
        if os.path.exists(file_path):
            os.remove(file_path)
            print(f"Removed: {file_path}")
    
    # 3. Initialize new database using the app's init function
    try:
        sys.path.append(f'/home/{LINUX_USER_INSTALLATION}/{PLTF_FOLDER}')
        from src.database_postgres import init_db
        
        print("Initializing new database...")
        init_db()
        print("Database initialized successfully!")
        
        # 4. Verify the new database - COMMENTED OUT for PostgreSQL migration
        # conn = sqlite3.connect(db_path)
        # cursor = conn.cursor()
        
        # Check tables
        # cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        # tables = cursor.fetchall()
        # print(f"Created tables: {[table[0] for table in tables]}")
        
        # Check integrity
        # cursor.execute("PRAGMA integrity_check")
        # result = cursor.fetchone()
        # print(f"Database integrity: {result[0]}")
        
        # conn.close()
        
        print("Database verification skipped - using PostgreSQL now")
        
        return True
        
    except Exception as e:
        print(f"Error during recovery: {e}")
        return False

if __name__ == "__main__":
    success = recover_database()
    if success:
        print("\n✅ Database recovery completed successfully!")
        print("You can now restart your application.")
    else:
        print("\n❌ Database recovery failed!")
        print("Please check the error messages above.")
