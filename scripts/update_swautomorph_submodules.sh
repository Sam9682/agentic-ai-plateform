#!/bin/bash

# Load PLTF_FOLDER from deploy.ini
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -f "${SCRIPT_DIR}/conf/deploy.ini" ]; then
    PLTF_FOLDER=$(grep -E "^PLTF_FOLDER=" "${SCRIPT_DIR}/conf/deploy.ini" 2>/dev/null | cut -d'=' -f2 | xargs)
fi
PLTF_FOLDER="${PLTF_FOLDER:-agentic-ai-plateform}"

folders=("ai-beewoo" "ai-checkinatwork" "ai-foodflow" "ai-haccp" "ai-staticwebsite" "ai-transats" "${PLTF_FOLDER}")

for folder in "${folders[@]}"; do
    if [ -d "/home/ubuntu/$folder" ]; then
        echo "Updating submodule in $folder..."
        cd "/home/ubuntu/$folder"
        git submodule update --remote shared
        git add .
        git commit -m "Update shared submodule"
        git push
        cd ..
    else
        echo "Warning: $folder directory not found"
    fi
done

echo "Submodule updates completed"
