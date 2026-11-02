#!/bin/bash
# Test script to verify orchestrator service creation fix

echo "=== Orchestrator Service Creation Test ==="
echo ""

# Database connection details
DB_NAME="ai_swautomorph"
DB_USER="swautomorph"

# Test service name
SERVICE_NAME="test-service-$(date +%s)"

echo "1. Checking current state..."
echo "   Services count:"
psql -U $DB_USER -d $DB_NAME -c "SELECT COUNT(*) FROM services;" -t

echo "   Instances count:"
psql -U $DB_USER -d $DB_NAME -c "SELECT COUNT(*) FROM instances;" -t

echo "   Billing activities count:"
psql -U $DB_USER -d $DB_NAME -c "SELECT COUNT(*) FROM billing_activities;" -t

echo ""
echo "2. To test the fix:"
echo "   a. Go to the dashboard: https://swautomorph.com"
echo "   b. Navigate to Orchestrator section"
echo "   c. Click 'Create Service'"
echo "   d. Fill in the form:"
echo "      - Application Name: Select an application"
echo "      - Git URL: Select a git URL"
echo "      - Desired Replicas: 1"
echo "   e. Click 'Create Service'"
echo ""
echo "3. After creating the service, run this script again to verify:"
echo "   ./test_orchestrator_fix.sh verify $SERVICE_NAME"
echo ""

if [ "$1" == "verify" ] && [ -n "$2" ]; then
    SERVICE_NAME=$2
    echo "=== Verifying Service: $SERVICE_NAME ==="
    echo ""
    
    echo "Service record:"
    psql -U $DB_USER -d $DB_NAME -c "SELECT id, name, desired_replicas, created_at FROM services WHERE name = '$SERVICE_NAME';"
    
    echo ""
    echo "Instance records:"
    psql -U $DB_USER -d $DB_NAME -c "SELECT id, instance_id, server_id, status, port, health_status FROM instances WHERE service_name = '$SERVICE_NAME';"
    
    echo ""
    echo "Billing activities:"
    psql -U $DB_USER -d $DB_NAME -c "SELECT ba.id, ba.action, ba.started_at, a.name FROM billing_activities ba JOIN applications a ON ba.application_id = a.id WHERE a.name = '$SERVICE_NAME';"
    
    echo ""
    echo "Expected results:"
    echo "  - Service record: 1 row with desired_replicas = 1"
    echo "  - Instance records: 1 row with status = 'running'"
    echo "  - Billing activities: 1 row with action = 'START'"
fi
