#!/bin/bash
# Load PLTF_FOLDER from deploy.ini
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -f "${SCRIPT_DIR}/conf/deploy.ini" ]; then
    PLTF_FOLDER=$(grep -E "^PLTF_FOLDER=" "${SCRIPT_DIR}/conf/deploy.ini" 2>/dev/null | cut -d'=' -f2 | xargs)
fi
PLTF_FOLDER="${PLTF_FOLDER:-agentic-ai-plateform}"

cd /home/ubuntu/${PLTF_FOLDER}
./deployControlPlan.sh stop --locally --keep-gitea-running
