#!/bin/bash
# Load PLTF_FOLDER and LINUX_USER_INSTALLATION from deploy.ini
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "${SCRIPT_DIR}/conf/deploy.ini" ]; then
    PLTF_FOLDER=$(grep -E "^PLTF_FOLDER=" "${SCRIPT_DIR}/conf/deploy.ini" 2>/dev/null | cut -d'=' -f2 | xargs)
    LINUX_USER_INSTALLATION=$(grep -E "^LINUX_USER_INSTALLATION=" "${SCRIPT_DIR}/conf/deploy.ini" 2>/dev/null | cut -d'=' -f2 | xargs)
fi
PLTF_FOLDER="${PLTF_FOLDER:-agentic-ai-plateform}"
LINUX_USER_INSTALLATION="${LINUX_USER_INSTALLATION:-psmc}"

cd /home/${LINUX_USER_INSTALLATION}/${PLTF_FOLDER}
export FLASK_ENV=production
gunicorn --bind 0.0.0.0:5000 --workers 4 --timeout 120 wsgi:app
