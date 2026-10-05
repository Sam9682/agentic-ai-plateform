#!/bin/bash

# Helper script to safely kill Flask processes
# Usage: ./scripts/kill_flask.sh [force]

set -e

# Color definitions
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}🔍 Checking for Flask processes...${NC}"

# Find all Flask processes
FLASK_PIDS=$(pgrep -f "python3 ControlPlanFlaskApp_postgres.py" 2>/dev/null || true)

if [ -z "$FLASK_PIDS" ]; then
    echo -e "${GREEN}✅ No Flask processes found${NC}"
    exit 0
fi

echo -e "${YELLOW}📋 Found Flask processes:${NC}"
for pid in $FLASK_PIDS; do
    OWNER=$(ps -o user= -p "$pid" 2>/dev/null || echo "unknown")
    CMD=$(ps -o cmd= -p "$pid" 2>/dev/null || echo "unknown")
    echo "  PID: $pid, Owner: $OWNER, Command: $CMD"
done

# Check if force flag is provided
FORCE_MODE="$1"

if [ "$FORCE_MODE" = "force" ]; then
    echo -e "${RED}💀 Force killing all Flask processes...${NC}"
    
    # Try to kill each process individually with better error handling
    for pid in $FLASK_PIDS; do
        OWNER=$(ps -o user= -p "$pid" 2>/dev/null || echo "unknown")
        
        if [ "$OWNER" = "$(whoami)" ]; then
            # We own this process, can kill it directly
            if kill -9 "$pid" 2>/dev/null; then
                echo -e "${GREEN}✅ Killed process $pid (owned by $OWNER)${NC}"
            else
                echo -e "${RED}❌ Failed to kill process $pid (owned by $OWNER)${NC}"
            fi
        else
            # Process owned by another user, need sudo
            echo -e "${YELLOW}🔐 Process $pid owned by $OWNER, trying with sudo...${NC}"
            if sudo kill -9 "$pid" 2>/dev/null; then
                echo -e "${GREEN}✅ Killed process $pid with sudo${NC}"
            else
                echo -e "${RED}❌ Failed to kill process $pid even with sudo${NC}"
            fi
        fi
    done
else
    echo -e "${YELLOW}🛑 Gracefully stopping Flask processes...${NC}"
    
    # Try graceful shutdown first
    for pid in $FLASK_PIDS; do
        OWNER=$(ps -o user= -p "$pid" 2>/dev/null || echo "unknown")
        
        if [ "$OWNER" = "$(whoami)" ]; then
            # We own this process, can kill it directly
            if kill "$pid" 2>/dev/null; then
                echo -e "${GREEN}✅ Sent TERM signal to process $pid (owned by $OWNER)${NC}"
            else
                echo -e "${RED}❌ Failed to send TERM signal to process $pid${NC}"
            fi
        else
            # Process owned by another user, need sudo
            echo -e "${YELLOW}🔐 Process $pid owned by $OWNER, trying with sudo...${NC}"
            if sudo kill "$pid" 2>/dev/null; then
                echo -e "${GREEN}✅ Sent TERM signal to process $pid with sudo${NC}"
            else
                echo -e "${RED}❌ Failed to send TERM signal to process $pid even with sudo${NC}"
            fi
        fi
    done
    
    # Wait a bit for graceful shutdown
    echo -e "${YELLOW}⏳ Waiting 3 seconds for graceful shutdown...${NC}"
    sleep 3
    
    # Check if any processes are still running
    REMAINING_PIDS=$(pgrep -f "python3 ControlPlanFlaskApp_postgres.py" 2>/dev/null || true)
    if [ -n "$REMAINING_PIDS" ]; then
        echo -e "${YELLOW}⚠️ Some processes still running: $REMAINING_PIDS${NC}"
        echo -e "${YELLOW}💡 Run with 'force' argument to force kill: $0 force${NC}"
        exit 1
    else
        echo -e "${GREEN}✅ All Flask processes stopped gracefully${NC}"
    fi
fi

# Final check
FINAL_PIDS=$(pgrep -f "python3 ControlPlanFlaskApp_postgres.py" 2>/dev/null || true)
if [ -z "$FINAL_PIDS" ]; then
    echo -e "${GREEN}🎉 All Flask processes successfully terminated${NC}"
    
    # Clean up PID file if it exists
    if [ -f "./conf/app.pid" ]; then
        rm -f ./conf/app.pid
        echo -e "${GREEN}🧹 Cleaned up PID file${NC}"
    fi
else
    echo -e "${RED}❌ Some processes could not be terminated: $FINAL_PIDS${NC}"
    echo -e "${YELLOW}💡 You may need to restart the system or contact an administrator${NC}"
    exit 1
fi