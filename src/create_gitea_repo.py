#!/usr/bin/env python3
import requests
import subprocess
import sys
import os
from gitea_config import *

def create_user():
    """Create Gitea user if not exists"""
    url = f"{GITEA_SERVER}/api/v1/admin/users"
    headers = {
        "Authorization": f"token {ADMIN_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "username": USERNAME,
        "email": EMAIL,
        "password": PASSWORD,
        "must_change_password": False
    }
    
    response = requests.post(url, json=data, headers=headers)
    if response.status_code == 201:
        print(f"✓ User '{USERNAME}' created successfully")
    elif response.status_code == 422:
        print(f"✓ User '{USERNAME}' already exists")
    else:
        print(f"✗ Failed to create user: {response.text}")
        return False
    return True

def create_repository():
    """Create repository for the user"""
    url = f"{GITEA_SERVER}/api/v1/user/repos"
    headers = {
        "Authorization": f"token {USER_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "name": REPO_NAME,
        "description": "Employee check-in timing management system",
        "private": False
    }
    
    response = requests.post(url, json=data, headers=headers)
    if response.status_code == 201:
        print(f"✓ Repository '{REPO_NAME}' created successfully")
        return True
    elif response.status_code == 409:
        print(f"✓ Repository '{REPO_NAME}' already exists")
        return True
    else:
        print(f"✗ Failed to create repository: {response.text}")
        return False

def git_push():
    """Initialize git and push to repository"""
    repo_url = f"{GITEA_SERVER}/{USERNAME}/{REPO_NAME}.git"
    
    commands = [
        ["git", "init"],
        ["git", "add", "."],
        ["git", "commit", "-m", "Initial commit: AI Check-in at Work system"],
        ["git", "branch", "-M", "main"],
        ["git", "remote", "add", "origin", repo_url],
        ["git", "push", "-u", "origin", "main"]
    ]
    
    for cmd in commands:
        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            print(f"✓ {' '.join(cmd)}")
        except subprocess.CalledProcessError as e:
            if "already exists" in e.stderr or "already up to date" in e.stderr:
                print(f"✓ {' '.join(cmd)} (already done)")
            else:
                print(f"✗ {' '.join(cmd)} failed: {e.stderr}")
                return False
    return True

def main():
    print("Creating Gitea repository and pushing ai-checkinatwork project...")
    
    # Check if we're not in a git repo directory
    if os.path.exists(".git"):
        print("✗ This script should not be run from inside a git repository")
        sys.exit(1)
    
    # Create user
    if not create_user():
        sys.exit(1)
    
    # Create repository
    if not create_repository():
        sys.exit(1)
    
    # Push code
    if not git_push():
        sys.exit(1)
    
    print(f"\n✓ Project successfully pushed to {GITEA_SERVER}/{USERNAME}/{REPO_NAME}")

if __name__ == "__main__":
    main()
