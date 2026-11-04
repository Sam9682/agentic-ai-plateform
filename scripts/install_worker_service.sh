#!/bin/bash
set -e

# Install script for the agentic-ai-plateform Serverless Worker systemd service.
# This script copies the service file, reloads systemd, and enables the service.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SERVICE_FILE="$PROJECT_ROOT/systemd/serverless-worker.service"
SERVICE_NAME="serverless-worker.service"
DEST="/etc/systemd/system/$SERVICE_NAME"

# Check running as root
if [ "$EUID" -ne 0 ]; then
    echo "Error: This script must be run as root (use sudo)."
    exit 1
fi

# Verify the service file exists
if [ ! -f "$SERVICE_FILE" ]; then
    echo "Error: Service file not found at $SERVICE_FILE"
    exit 1
fi

echo "Installing $SERVICE_NAME..."

# Copy service file to systemd directory
echo "  Copying $SERVICE_FILE -> $DEST"
cp "$SERVICE_FILE" "$DEST"

# Reload systemd daemon
echo "  Reloading systemd daemon..."
systemctl daemon-reload

# Enable the service to start on boot
echo "  Enabling $SERVICE_NAME..."
systemctl enable "$SERVICE_NAME"

# Optionally start the service
if [ "${1}" = "--start" ]; then
    echo "  Starting $SERVICE_NAME..."
    systemctl start "$SERVICE_NAME"
    echo "  Service started."
else
    echo ""
    echo "  Service installed and enabled. To start it now, run:"
    echo "    sudo systemctl start $SERVICE_NAME"
    echo ""
    echo "  Or re-run this script with --start:"
    echo "    sudo $0 --start"
fi

echo ""
echo "Done. Check status with: systemctl status $SERVICE_NAME"
