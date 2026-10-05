# Gitea Configuration
# Update these values with your actual Gitea server details

import os

GITEA_SERVER = "http://www.swautomorph.com/gitea"  # Your Gitea server URL
USERNAME = "gitadmin"
EMAIL = "admin@swautomorph.com"
PASSWORD = "password"       # Password for the user
REPO_NAME = "ai-checkinatwork"

# Auto-load token from file if available
def get_admin_token():
    try:
        with open('/tmp/gitea_admin_token', 'r') as f:
            return f.read().strip()
    except:
        return "your_admin_token_here"

ADMIN_TOKEN = get_admin_token()
USER_TOKEN = ADMIN_TOKEN  # Use same token for both operations
