#!/bin/bash
# Example deployment script for App Orchestrator

set -e

echo "🎯 App Orchestrator - Example Service Deployment"
echo "=================================================="

# Configuration
SERVICE_NAME="ai-staticwebsite"
IMAGE="nginx:alpine"
REPLICAS=2
PORTS='{"80": "8080"}'
ENVIRONMENT='{"NGINX_HOST": "localhost", "NGINX_PORT": "80"}'
VOLUMES='["/var/www/html:/usr/share/nginx/html:ro"]'

echo "📋 Service Configuration:"
echo "  Name: $SERVICE_NAME"
echo "  Image: $IMAGE"
echo "  Replicas: $REPLICAS"
echo "  Ports: $PORTS"
echo ""

# Initialize orchestrator if needed
echo "🔧 Initializing orchestrator..."
python3 ./scripts/orchestrator_cli.py init

# Create the service
echo "🚀 Creating service..."
python3 ./scripts/orchestrator_cli.py create "$SERVICE_NAME" "$IMAGE" \
    --replicas "$REPLICAS" \
    --ports "$PORTS" \
    --environment "$ENVIRONMENT" \
    --volumes "$VOLUMES" \
    --health-check "/health"

echo "✅ Service created successfully!"

# Wait a moment for deployment
echo "⏳ Waiting for deployment..."
sleep 5

# Show service status
echo "📊 Service Status:"
python3 ./scripts/orchestrator_cli.py show "$SERVICE_NAME"

# Generate Nginx configuration
echo "🌐 Generating Nginx configuration..."
python3 ./scripts/orchestrator_cli.py nginx --output /tmp/orchestrator-upstreams.conf

echo "📄 Generated Nginx upstreams:"
cat /tmp/orchestrator-upstreams.conf

echo ""
echo "🎉 Deployment completed!"
echo ""
echo "Next steps:"
echo "1. Copy the generated upstreams to your Nginx configuration"
echo "2. Update your server blocks to use the upstream"
echo "3. Reload Nginx: sudo nginx -s reload"
echo ""
echo "Management commands:"
echo "  Scale up:   python3 ./scripts/orchestrator_cli.py scale $SERVICE_NAME 3"
echo "  Scale down: python3 ./scripts/orchestrator_cli.py scale $SERVICE_NAME 1"
echo "  Delete:     python3 ./scripts/orchestrator_cli.py delete $SERVICE_NAME"
echo "  Status:     python3 ./scripts/orchestrator_cli.py list"