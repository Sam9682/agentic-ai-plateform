#!/bin/bash

# Platform Production Deployment Script
# Organized with functions for better maintainability.
# The platform display name is read from PLTF_NAME in conf/deploy.ini.

set -e

# Version (read from conf/deploy.ini, fallback to default)
VERSION="0.0.1"
if [ -f "./conf/deploy.ini" ]; then
    INI_VERSION=$(grep -E "^VERSION=" ./conf/deploy.ini 2>/dev/null | cut -d'=' -f2 | xargs)
    if [ -n "$INI_VERSION" ]; then
        VERSION="$INI_VERSION"
    fi
fi

# Load configuration from deploy.ini
load_config() {
    local config_file="./conf/deploy.ini"
    if [ -f "$config_file" ]; then
        echo "📋 Loading configuration from $config_file"
        # Source the config file, ignoring comments and empty lines
        while IFS='=' read -r key value; do
            # Skip comments and empty lines
            [[ $key =~ ^[[:space:]]*# ]] && continue
            [[ -z $key ]] && continue
            # Remove leading/trailing whitespace and export
            key=$(echo "$key" | xargs)
            value=$(echo "$value" | xargs)
            if [[ -n $key && -n $value ]]; then
                export "$key"="$value"
            fi
        done < "$config_file"
        echo "  ✅ Configuration loaded successfully"
    else
        echo "  ⚠️ Configuration file $config_file not found, using defaults"
    fi
}

# Load configuration first
load_config

# Local temporary directory (in the application folder instead of system /tmp)
TMP_DIR="./tmp"
mkdir -p "$TMP_DIR"

# Activate virtual environment if it exists
if [ -d ".venv" ]; then
    echo "🐍 Activating virtual environment..."
    source .venv/bin/activate
    echo "  ✅ Virtual environment activated"
fi

# Color definitions
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
WHITE='\033[1;37m'
NC='\033[0m' # No Color

# Status symbols with colors
OK="${GREEN}[OK]${NC}"
ERROR="${RED}[ERROR]${NC}"
WARN="${YELLOW}[WARN]${NC}"
INFO="${BLUE}[INFO]${NC}"

# Global Variables (with fallback defaults)
NAME_OF_APPLICATION=${NAME_OF_APPLICATION:-"agentic-ai-plateform"}
APPLICATION_IDENTITY_NUMBER=${APPLICATION_IDENTITY_NUMBER:-0}
RANGE_START_CONTROLPLAN=${RANGE_START_CONTROLPLAN:-80}
RANGE_RESERVED_CONTROLPLAN=${RANGE_RESERVED_CONTROLPLAN:-0}
S3_BUCKET_NAME=${S3_BUCKET_NAME:-"agentic-ai-plateform-s3"}
PLTF_FOLDER=${PLTF_FOLDER:-"agentic-ai-plateform"}
# Display name shown in banners/usage; read from PLTF_NAME in deploy.ini.
PLTF_NAME=${PLTF_NAME:-"agentic-ai-plateform_AI_SharedGPU_Docker_Serverless"}
LINUX_USER_INSTALLATION=${LINUX_USER_INSTALLATION:-"ubuntu"}

# Global Parameters (command line args override config)
COMMAND=${1:-help}
LOCAL_MODE=${2:-0}
USER_ID=${3:-${DEFAULT_USER_ID:-0}}
USER_NAME=${4:-${DEFAULT_USER_NAME:-"admin"}}
USER_EMAIL=${5:-${DEFAULT_USER_EMAIL:-"admin@softfluid.fr"}}
DESCRIPTION=${6:-${DEFAULT_DESCRIPTION:-"Basic Admin user for Control Plan"}}

# Configuration (loaded from deploy.ini with fallback defaults)
DOMAIN=${DOMAIN:-"agentic-ai-plateform.com"}
EMAIL=${EMAIL:-"admin@agentic-ai-plateform.com"}
ENV_FILE=${ENV_FILE:-".env.prod"}
GITEA_VERSION=${GITEA_VERSION:-"1.21.3"}
GITEA_ADMIN_USER=${GITEA_ADMIN_USER:-"gitadmin"}
GITEA_ADMIN_PASSWORD=${GITEA_ADMIN_PASSWORD:-"password"}
GITEA_ADMIN_EMAIL=${GITEA_ADMIN_EMAIL:-"admin@agentic-ai-plateform.com"}

# Normalize LOCAL_MODE parameter (handle --locally and --docker)
case "$LOCAL_MODE" in
    "--locally")
        LOCAL_MODE="locally"
        ;;
    "--docker")
        LOCAL_MODE="docker"
        ;;
esac

# Check for --keep-gitea-running parameter
KEEP_GITEA_RUNNING=false
for arg in "$@"; do
    if [ "$arg" = "--keep-gitea-running" ]; then
        KEEP_GITEA_RUNNING=true
        break
    fi
done

# Interactive menu for deployment mode selection using Python simple-term-menu
show_deployment_menu() {
    # Check if simple-term-menu is available
    if ! python3 -c "from simple_term_menu import TerminalMenu" 2>/dev/null; then
        echo "Installing simple-term-menu..."
        pip3 install simple-term-menu >/dev/null 2>&1 || {
            echo "Failed to install simple-term-menu. Using fallback menu."
            echo "Select deployment mode:"
            echo "1) Locally (no Docker)"
            echo "2) Docker"
            read -p "Enter your choice (1-2): " choice
            case $choice in
                1) echo -e " $YELLOW locally" ;;
                2) echo -e " $YELLOW docker" ;;
                *) echo "locally" ;;
            esac
            return
        }
    fi

    # Use Python simple-term-menu for interactive selection
    python3 << 'EOF'
from simple_term_menu import TerminalMenu

options = ["Locally (no Docker)", "Docker"]
terminal_menu = TerminalMenu(
    options,
    title="🚀 Select deployment mode:",
    menu_cursor="▶ ",
    menu_cursor_style=("fg_cyan", "bold"),
    menu_highlight_style=("bg_cyan", "fg_black"),
    cycle_cursor=True
)

menu_entry_index = terminal_menu.show()

if menu_entry_index == 0:
    print("locally")
elif menu_entry_index == 1:
    print("docker")
else:
    print("locally")
EOF
}

# Get server IP address
get_server_ip() {
    # Try to get the primary IPv4 address (prefer public IP)
    # Method 1: Try to get public IPv4 from external service (force IPv4)
    SERVER_IP=$(curl -4 -s --max-time 2 ifconfig.me 2>/dev/null || curl -4 -s --max-time 2 icanhazip.com 2>/dev/null)

    # Validate it's IPv4 (not IPv6)
    if [ -n "$SERVER_IP" ] && [[ ! "$SERVER_IP" =~ : ]]; then
        echo "$SERVER_IP"
        return
    fi

    # Method 2: Get the primary IPv4 from network interfaces (filter out IPv6)
    SERVER_IP=$(hostname -I | tr ' ' '\n' | grep -v ':' | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' | head -n 1)

    if [ -n "$SERVER_IP" ]; then
        echo "$SERVER_IP"
        return
    fi

    # Method 3: Try ip command to get IPv4 address
    SERVER_IP=$(ip -4 addr show | grep -oP '(?<=inet\s)\d+(\.\d+){3}' | grep -v '127.0.0.1' | head -n 1)

    if [ -n "$SERVER_IP" ]; then
        echo "$SERVER_IP"
        return
    fi

    # Method 4: Fallback to localhost if nothing else works
    echo "127.0.0.1"
}

# Calculate ports (convert alphanumeric USER_ID to numeric for port calculation)
calculate_ports() {
    # 12 consecutive ports per application (6 HTTP + 6 HTTPS), allocated as
    # alternating HTTP/HTTPS pairs starting from RANGE_START_CONTROLPLAN.
    HTTP_PORT=${RANGE_START_CONTROLPLAN}
    HTTPS_PORT=$((HTTP_PORT + 1))
    HTTP_PORT2=$((HTTPS_PORT + 1))
    HTTPS_PORT2=$((HTTP_PORT2 + 1))
    HTTP_PORT3=$((HTTPS_PORT2 + 1))
    HTTPS_PORT3=$((HTTP_PORT3 + 1))
    HTTP_PORT4=$((HTTPS_PORT3 + 1))
    HTTPS_PORT4=$((HTTP_PORT4 + 1))
    HTTP_PORT5=$((HTTPS_PORT4 + 1))
    HTTPS_PORT5=$((HTTP_PORT5 + 1))
    HTTP_PORT6=$((HTTPS_PORT5 + 1))
    HTTPS_PORT6=$((HTTP_PORT6 + 1))
}

# Display environment variables for operations
show_environment() {
    local operation=$1
    echo "🔍 Starting $operation operation..."
    echo -e "${CYAN}[STATUS]${NC} Environment Variables:"
    echo "  LOCAL_MODE=${LOCAL_MODE}"
    echo "  USER_ID=${USER_ID}"
    echo "  USER_NAME=${USER_NAME}"
    echo "  USER_EMAIL=${USER_EMAIL}"
    echo "  HTTP_PORT=${HTTP_PORT}"
    echo "  HTTPS_PORT=${HTTPS_PORT}"
    echo "  HTTP_PORT2=${HTTP_PORT2}"
    echo "  HTTPS_PORT2=${HTTPS_PORT2}"
    echo "  HTTP_PORT3=${HTTP_PORT3}"
    echo "  HTTPS_PORT3=${HTTPS_PORT3}"
    echo "  HTTP_PORT4=${HTTP_PORT4}"
    echo "  HTTPS_PORT4=${HTTPS_PORT4}"
    echo "  HTTP_PORT5=${HTTP_PORT5}"
    echo "  HTTPS_PORT5=${HTTPS_PORT5}"
    echo "  HTTP_PORT6=${HTTP_PORT6}"
    echo "  HTTPS_PORT6=${HTTPS_PORT6}"
    echo ""
}

# Check service status
check_status() {
    # print 80 '-' to seperate a new line
    echo "--------------------------------------------------------------------------------"
    echo -e "${CYAN}[STATUS]${NC} Locally Service Status:"
    check_flask_status
    check_nginx_status
    check_gitea_status
    echo "--------------------------------------------------------------------------------"
    echo -e "${CYAN}[STATUS]${NC} Docker Compose Status:"
    check_docker_status
}

check_flask_status() {
    # Check for Gunicorn PID file first (primary)
    if [ -f "conf/gunicorn.pid" ]; then
        PID=$(cat "conf/gunicorn.pid")
        if kill -0 "$PID" 2>/dev/null; then
            PROCESS_OWNER=$(ps -o user= -p "$PID" 2>/dev/null || echo "unknown")
            PROCESS_CMD=$(ps -o cmd= -p "$PID" 2>/dev/null | head -c 50)
            echo -e "  $OK Flask application: Running (PID: $PID, Owner: $PROCESS_OWNER)"
            echo -e "      Command: $PROCESS_CMD..."
        else
            echo -e "  $ERROR Flask application: Not running (stale PID: $PID)"
        fi
    # Fallback to legacy app.pid
    elif [ -f "${PID_FILE:-./conf/app.pid}" ]; then
        PID=$(cat "${PID_FILE:-./conf/app.pid}")
        if kill -0 "$PID" 2>/dev/null; then
            PROCESS_OWNER=$(ps -o user= -p "$PID" 2>/dev/null || echo "unknown")
            PROCESS_CMD=$(ps -o cmd= -p "$PID" 2>/dev/null | head -c 50)
            echo -e "  $OK Flask application: Running (PID: $PID, Owner: $PROCESS_OWNER)"
            echo -e "      Command: $PROCESS_CMD..."
        else
            echo -e "  $ERROR Flask application: Not running (stale PID: $PID)"
        fi
    else
        echo -e "  $ERROR Flask application: Not running (no PID file)"
    fi

    # Check for Gunicorn processes
    GUNICORN_PIDS=$(pgrep -f "gunicorn.*wsgi:application" 2>/dev/null || true)
    if [ -n "$GUNICORN_PIDS" ]; then
        echo -e "  $OK Gunicorn processes found: $GUNICORN_PIDS"
        for pid in $GUNICORN_PIDS; do
            OWNER=$(ps -o user= -p "$pid" 2>/dev/null || echo "unknown")
            PROCESS_TYPE=$(ps -o cmd= -p "$pid" 2>/dev/null | grep -o "gunicorn: [a-z]*" || echo "gunicorn")
            echo -e "    PID: $pid, Owner: $OWNER, Type: $PROCESS_TYPE"
        done
    fi

    # Check for any old Flask development server processes
    OTHER_PIDS=$(pgrep -f "python3 ControlPlanFlaskApp_postgres.py" 2>/dev/null || true)
    if [ -n "$OTHER_PIDS" ]; then
        echo -e "  $WARN Old Flask development server processes found: $OTHER_PIDS"
        for pid in $OTHER_PIDS; do
            OWNER=$(ps -o user= -p "$pid" 2>/dev/null || echo "unknown")
            echo -e "    PID: $pid, Owner: $OWNER (should be migrated to Gunicorn)"
        done
    fi
}

check_nginx_status() {
    if systemctl is-active --quiet nginx; then
        echo -e "  $OK Nginx: Running"
        if [ -f "${NGINX_SITES_ENABLED:-/etc/nginx/sites-enabled}/${NGINX_SITE_NAME:-${NAME_OF_APPLICATION}}" ]; then
            echo -e "  $OK $NAME_OF_APPLICATION site: Configured"
        else
            echo -e "  $WARN $NAME_OF_APPLICATION site: Not configured"
        fi
    else
        echo -e "  $ERROR Nginx: Not running"
    fi
}

check_gitea_status() {
    if systemctl is-active --quiet gitea 2>/dev/null; then
        echo -e "  $OK Gitea: Running on http://localhost:${GITEA_PORT:-3000}"
    else
        echo -e "  $ERROR Gitea: Not running"
    fi
}

check_docker_status() {
    if command -v docker-compose &> /dev/null; then
        docker-compose ps
    else
        echo "  ❌ Docker Compose not installed"
    fi
}

# Provide guidance for manual process cleanup
provide_cleanup_guidance() {
    echo ""
    echo -e "${YELLOW}[CLEANUP GUIDANCE]${NC} If processes couldn't be stopped automatically:"
    echo "  1. Check running Gunicorn processes: ps aux | grep 'gunicorn.*wsgi:application'"
    echo "  2. Kill specific PID: sudo kill -9 <PID>"
    echo "  3. Kill all Gunicorn processes: sudo pkill -9 -f 'gunicorn.*wsgi:application'"
    echo "  4. Check for old Flask processes: ps aux | grep 'python3 ControlPlanFlaskApp_postgres.py'"
    echo "  5. Kill old Flask processes: sudo pkill -9 -f 'python3 ControlPlanFlaskApp_postgres.py'"
    echo "  6. Check process ownership: ps -o pid,user,cmd -C python3"
    echo ""
}

# Database backup function
backup_database() {
    echo "💾 Creating PostgreSQL database backup..."

    # Load environment variables from .env file if it exists
    if [ -f ".env" ]; then
        echo "  📋 Loading PostgreSQL credentials from .env file..."
        export $(grep -v '^#' .env | grep -v '^$' | xargs)
    fi

    # Create backup directory with timestamp
    DATETIME=$(date +"%Y%m%d_%H%M%S")
    BACKUP_DIR="./softfluid/db/backup/$DATETIME"
    mkdir -p "$BACKUP_DIR"

    # PostgreSQL connection parameters from environment or defaults
    POSTGRES_HOST=${POSTGRES_HOST:-"localhost"}
    POSTGRES_PORT=${POSTGRES_PORT:-"5432"}
    POSTGRES_DB=${POSTGRES_DB:-"ai_swautomorph"}
    POSTGRES_USER=${POSTGRES_USER:-"swautomorph"}
    POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-"swautomorph_password"}

    # Set PGPASSWORD environment variable for non-interactive backup
    export PGPASSWORD="$POSTGRES_PASSWORD"

    echo "  📋 Backing up PostgreSQL database..."
    echo "    🔗 Connection: $POSTGRES_USER@$POSTGRES_HOST:$POSTGRES_PORT/$POSTGRES_DB"

    # Test connection first
    echo "    🔍 Testing PostgreSQL connection..."
    if ! pg_isready -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; then
        echo -e "  $ERROR PostgreSQL server is not ready or connection failed"
        echo "    💡 Check if PostgreSQL is running: sudo systemctl status postgresql"
        echo "    💡 Check connection: psql -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER -d $POSTGRES_DB"
        unset PGPASSWORD
        return 1
    fi

    # Create complete database dump using pg_dump
    echo "    💿 Creating complete database dump..."
    if pg_dump -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
        --no-password --verbose --clean --if-exists --create \
        > "$BACKUP_DIR/complete_database.sql" 2>"$BACKUP_DIR/backup.log"; then
        echo -e "  $OK PostgreSQL database backup completed: $BACKUP_DIR"
    else
        echo -e "  $ERROR PostgreSQL backup failed - check $BACKUP_DIR/backup.log"
        echo "    💡 Common issues:"
        echo "      - Wrong password: Check POSTGRES_PASSWORD in .env file"
        echo "      - User doesn't exist: sudo -u postgres createuser $POSTGRES_USER"
        echo "      - Database doesn't exist: sudo -u postgres createdb $POSTGRES_DB"
        echo "      - Permission denied: GRANT ALL ON DATABASE $POSTGRES_DB TO $POSTGRES_USER"
        unset PGPASSWORD
        return 1
    fi

    # Create data-only dump (without schema)
    echo "    📄 Creating data-only dump..."
    pg_dump -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
        --no-password --data-only --verbose \
        > "$BACKUP_DIR/data_only.sql" 2>>"$BACKUP_DIR/backup.log" || true

    # Create schema-only dump
    echo "    🏗️ Creating schema-only dump..."
    pg_dump -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
        --no-password --schema-only --verbose \
        > "$BACKUP_DIR/schema_only.sql" 2>>"$BACKUP_DIR/backup.log" || true

    # Unset PGPASSWORD for security
    unset PGPASSWORD

    echo "    📁 Files created:"
    ls -la "$BACKUP_DIR" | sed 's/^/      /'

    # Sync to S3 with IP address in path
    echo "  ☁️ Synchronizing to S3..."
    SERVER_IP=$(get_server_ip)
    echo "    📍 Server IP: $SERVER_IP"

    # Sync the specific backup to S3 with IP-based path structure
    if aws s3 sync "$BACKUP_DIR" "s3://${S3_BUCKET_NAME}/${NAME_OF_APPLICATION}/db/backup/$SERVER_IP/$DATETIME/" --profile OVH-SWAUTOMORPH; then
        echo -e "  $OK Backup synced to s3://${S3_BUCKET_NAME}/${NAME_OF_APPLICATION}/db/backup/$SERVER_IP/$DATETIME/"
    else
        echo "  ⚠️ S3 sync failed or not configured"
    fi
}

# Logs backup function
backup_logs() {
    echo "📋 Creating logs backup..."

    if [ -d "logs" ] && [ "$(ls -A logs 2>/dev/null)" ]; then
        echo "  📄 Synchronizing logs to S3..."
        if aws s3 sync ./logs s3://${S3_BUCKET_NAME}/${NAME_OF_APPLICATION}/logs --profile OVH-SWAUTOMORPH; then
            echo -e "  $OK Logs backup completed"
        else
            echo -e "  ⚠️ Logs S3 sync failed or not configured - continuing"
        fi
    else
        echo -e "  $WARN No logs directory or logs found - skipping backup"
    fi
}

# Database migration function
migrate_database() {
    echo "🔄 Migrating data from SQLite to PostgreSQL..."

    # Check if SQLite database exists
    if [ ! -f "softfluid/db/ai_swautomorph.db" ]; then
        echo -e "  $WARN No SQLite database found, skipping migration"
        return
    fi

    # Install PostgreSQL client if needed
    if ! command -v psycopg2 &> /dev/null; then
        echo "📦 Installing PostgreSQL dependencies..."
        pip3 install psycopg2-binary --break-system-packages
    fi

    # Wait for PostgreSQL to be ready
    echo "  ⏳ Waiting for PostgreSQL to be ready..."
    for i in {1..30}; do
        if docker-compose exec -T postgres pg_isready -U swautomorph -d ai_swautomorph &>/dev/null; then
            echo -e "  $OK PostgreSQL is ready"
            break
        fi
        sleep 2
    done

    # Run migration script
    python3 migration/migrate_sqlite_to_postgres.py
    echo -e "  $OK Data migration completed"
}


recover_database() {
    echo "🔄 Database Recovery Tool"

    BACKUP_BASE_DIR="./softfluid/db/backup"

    # Ask user to choose backup source (local or S3)
    echo "📍 Select backup source:"

    if python3 -c "from simple_term_menu import TerminalMenu" 2>/dev/null; then
        BACKUP_SOURCE=$(S3_BUCKET_NAME="$S3_BUCKET_NAME" NAME_OF_APPLICATION="$NAME_OF_APPLICATION" python3 << 'EOF'
import os
from simple_term_menu import TerminalMenu

s3_bucket = os.environ.get('S3_BUCKET_NAME', 'agentic-ai-plateform-s3')
app_name = os.environ.get('NAME_OF_APPLICATION', 'agentic-ai-plateform')
options = ["Local backups (./softfluid/db/backup)", f"Remote S3 backups (s3://{s3_bucket}/{app_name}/db/backup)"]
terminal_menu = TerminalMenu(
    options,
    title="📍 Select backup source:",
    menu_cursor="▶ ",
    menu_cursor_style=("fg_cyan", "bold"),
    menu_highlight_style=("bg_cyan", "fg_black"),
    cycle_cursor=True
)

menu_entry_index = terminal_menu.show()
print("local" if menu_entry_index == 0 else "s3")
EOF
)
    else
        # Fallback to numbered selection
        echo "1) Local backups (./softfluid/db/backup)"
        echo "2) Remote S3 backups (s3://${S3_BUCKET_NAME}/${NAME_OF_APPLICATION}/db/backup)"
        read -p "Select backup source (1-2): " choice
        case $choice in
            1) BACKUP_SOURCE="local" ;;
            2) BACKUP_SOURCE="s3" ;;
            *) BACKUP_SOURCE="local" ;;
        esac
    fi

    # Handle S3 backup source
    if [ "$BACKUP_SOURCE" = "s3" ]; then
        echo "☁️ Fetching backup list from S3..."

        # Check if AWS CLI is available
        if ! command -v aws &> /dev/null; then
            echo -e "  $ERROR AWS CLI is not installed"
            echo "    💡 Install AWS CLI: sudo apt-get install awscli"
            exit 1
        fi

        # Get current server IP
        SERVER_IP=$(get_server_ip)
        echo "  📍 Current Server IP: $SERVER_IP"

        # Ask user which server's backups to restore from
        echo ""
        echo "📡 Select backup server:"

        # List all available server IPs in S3
        S3_SERVERS=$(aws s3 ls s3://${S3_BUCKET_NAME}/${NAME_OF_APPLICATION}/db/backup/ --profile OVH-SWAUTOMORPH 2>/dev/null | grep "PRE" | awk '{print $2}' | sed 's/\///' | sort)

        if [ -z "$S3_SERVERS" ]; then
            echo -e "  $ERROR No server backups found in S3 bucket"
            echo "    💡 Check S3 connection: aws s3 ls s3://${S3_BUCKET_NAME}/${NAME_OF_APPLICATION}/db/backup/ --profile OVH-SWAUTOMORPH"
            exit 1
        fi

        echo "  ✅ Found servers in S3:"
        echo "$S3_SERVERS" | sed 's/^/    /'

        # Convert to array using mapfile to handle IPv6 addresses with colons
        mapfile -t SERVER_IPS <<< "$S3_SERVERS"

        echo "  📊 Total servers: ${#SERVER_IPS[@]}"

        # Add current server to the top if it exists in the list
        CURRENT_SERVER_FOUND=false
        for ip in "${SERVER_IPS[@]}"; do
            if [ "$ip" = "$SERVER_IP" ]; then
                CURRENT_SERVER_FOUND=true
                break
            fi
        done

        if [ "$CURRENT_SERVER_FOUND" = "true" ]; then
            # Create new array with current server first
            NEW_SERVER_IPS=("$SERVER_IP (current server)")
            for ip in "${SERVER_IPS[@]}"; do
                if [ "$ip" != "$SERVER_IP" ]; then
                    NEW_SERVER_IPS+=("$ip")
                fi
            done
            SERVER_IPS=("${NEW_SERVER_IPS[@]}")
        fi

        # Select server
        if python3 -c "from simple_term_menu import TerminalMenu" 2>/dev/null; then
            printf '%s\n' "${SERVER_IPS[@]}" > "$TMP_DIR/server_ips.txt"

            SELECTED_SERVER=$(python3 << 'EOF'
from simple_term_menu import TerminalMenu

with open('./tmp/server_ips.txt', 'r') as f:
    server_ips = [line.strip() for line in f if line.strip()]

terminal_menu = TerminalMenu(
    server_ips,
    title="📡 Select server to restore from:",
    menu_cursor="▶ ",
    menu_cursor_style=("fg_cyan", "bold"),
    menu_highlight_style=("bg_cyan", "fg_black"),
    cycle_cursor=True
)

menu_entry_index = terminal_menu.show()
if menu_entry_index is not None:
    # Remove "(current server)" suffix if present
    selected = server_ips[menu_entry_index].replace(" (current server)", "")
    print(selected)
EOF
)
            rm -f "$TMP_DIR/server_ips.txt"
        else
            # Fallback to numbered selection
            echo "Available servers:"
            for i in "${!SERVER_IPS[@]}"; do
                echo "  $((i+1))) ${SERVER_IPS[$i]}"
            done

            read -p "Select server (1-${#SERVER_IPS[@]}): " choice

            if ! [[ "$choice" =~ ^[0-9]+$ ]] || [ "$choice" -lt 1 ] || [ "$choice" -gt ${#SERVER_IPS[@]} ]; then
                echo -e "  $ERROR Invalid selection"
                exit 1
            fi

            SELECTED_SERVER="${SERVER_IPS[$((choice-1))]}"
            SELECTED_SERVER="${SELECTED_SERVER// (current server)/}"
        fi

        if [ -z "$SELECTED_SERVER" ]; then
            echo -e "  $WARN No server selected - operation cancelled"
            exit 0
        fi

        echo "  ✅ Selected server: $SELECTED_SERVER"

        # List S3 backup directories for the selected server
        S3_BACKUPS=$(aws s3 ls "s3://${S3_BUCKET_NAME}/${NAME_OF_APPLICATION}/db/backup/$SELECTED_SERVER/" --profile OVH-SWAUTOMORPH 2>/dev/null | grep "PRE" | awk '{print $2}' | sed 's/\///' | sort -r)

        if [ -z "$S3_BACKUPS" ]; then
            echo -e "  $ERROR No backups found for server $SELECTED_SERVER in S3 bucket"
            echo "    💡 Check S3 path: aws s3 ls s3://${S3_BUCKET_NAME}/${NAME_OF_APPLICATION}/db/backup/$SELECTED_SERVER/ --profile OVH-SWAUTOMORPH"
            exit 1
        fi

        # Convert to array using mapfile to handle special characters
        mapfile -t BACKUP_DATES <<< "$S3_BACKUPS"

        echo "  ✅ Found ${#BACKUP_DATES[@]} backup(s) in S3 for server $SELECTED_SERVER"
    else
        # Handle local backup source
        if [ ! -d "$BACKUP_BASE_DIR" ]; then
            echo -e "  $ERROR No backup directory found at $BACKUP_BASE_DIR"
            exit 1
        fi

        # List available backup dates
        BACKUP_DATES=($(ls -1 "$BACKUP_BASE_DIR" | sort -r))

        if [ ${#BACKUP_DATES[@]} -eq 0 ]; then
            echo -e "  $ERROR No backup folders found"
            exit 1
        fi

        echo "  ✅ Found ${#BACKUP_DATES[@]} local backup(s)"
    fi

    # Use simple-term-menu for backup selection
    if python3 -c "from simple_term_menu import TerminalMenu" 2>/dev/null; then
        # Create temporary file with backup dates
        printf '%s\n' "${BACKUP_DATES[@]}" > "$TMP_DIR/backup_dates.txt"

        SELECTED_BACKUP=$(python3 << 'EOF'
from simple_term_menu import TerminalMenu

with open('./tmp/backup_dates.txt', 'r') as f:
    backup_dates = [line.strip() for line in f if line.strip()]

terminal_menu = TerminalMenu(
    backup_dates,
    title="📅 Select backup to restore:",
    menu_cursor="▶ ",
    menu_cursor_style=("fg_green", "bold"),
    menu_highlight_style=("bg_green", "fg_black"),
    cycle_cursor=True
)

menu_entry_index = terminal_menu.show()
if menu_entry_index is not None:
    print(backup_dates[menu_entry_index])
EOF
)
        rm -f "$TMP_DIR/backup_dates.txt"
    else
        # Fallback to numbered selection
        echo "📅 Available backup dates:"
        for i in "${!BACKUP_DATES[@]}"; do
            echo "  $((i+1))) ${BACKUP_DATES[$i]}"
        done

        read -p "Select backup to restore (1-${#BACKUP_DATES[@]}): " choice

        if ! [[ "$choice" =~ ^[0-9]+$ ]] || [ "$choice" -lt 1 ] || [ "$choice" -gt ${#BACKUP_DATES[@]} ]; then
            echo -e "  $ERROR Invalid selection"
            exit 1
        fi

        SELECTED_BACKUP="${BACKUP_DATES[$((choice-1))]}"
    fi

    if [ -z "$SELECTED_BACKUP" ]; then
        echo -e "  $WARN No backup selected - operation cancelled"
        exit 0
    fi

    # Download from S3 if needed
    if [ "$BACKUP_SOURCE" = "s3" ]; then
        echo "☁️ Downloading backup from S3: $SELECTED_BACKUP"
        echo "  📡 Server: $SELECTED_SERVER"

        # Create temporary directory for S3 backup
        BACKUP_DIR="$BACKUP_BASE_DIR/s3-temp-$SELECTED_SERVER-$SELECTED_BACKUP"
        mkdir -p "$BACKUP_DIR"

        # Download the selected backup from S3
        echo "  📥 Syncing from s3://${S3_BUCKET_NAME}/${NAME_OF_APPLICATION}/db/backup/$SELECTED_SERVER/$SELECTED_BACKUP/ ..."
        if aws s3 sync "s3://${S3_BUCKET_NAME}/${NAME_OF_APPLICATION}/db/backup/$SELECTED_SERVER/$SELECTED_BACKUP/" "$BACKUP_DIR/" --profile OVH-SWAUTOMORPH; then
            echo -e "  $OK Backup downloaded successfully"
        else
            echo -e "  $ERROR Failed to download backup from S3"
            echo "    💡 Check S3 connection and permissions"
            rm -rf "$BACKUP_DIR"
            exit 1
        fi
    else
        BACKUP_DIR="$BACKUP_BASE_DIR/$SELECTED_BACKUP"
    fi

    echo "🔧 Restoring from backup: $SELECTED_BACKUP"

    # Get PostgreSQL credentials from environment or use defaults
    POSTGRES_HOST=${POSTGRES_HOST:-"localhost"}
    POSTGRES_PORT=${POSTGRES_PORT:-"5432"}
    POSTGRES_DB=${POSTGRES_DB:-"ai_swautomorph"}
    POSTGRES_USER=${POSTGRES_USER:-"swautomorph"}
    POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-"swautomorph_password"}

    echo "  🔗 Connection: $POSTGRES_USER@$POSTGRES_HOST:$POSTGRES_PORT/$POSTGRES_DB"

    # Set password for PostgreSQL commands
    export PGPASSWORD="$POSTGRES_PASSWORD"

    # Test PostgreSQL connection
    echo "  🔍 Testing PostgreSQL connection..."
    if ! pg_isready -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; then
        echo -e "  $ERROR PostgreSQL server is not ready or connection failed"
        echo "    💡 Check if PostgreSQL is running: sudo systemctl status postgresql"
        echo "    💡 Check connection: psql -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER -d $POSTGRES_DB"
        unset PGPASSWORD
        exit 1
    fi

    # Create a backup of current database before recovery
    echo "  💾 Creating backup of current database before recovery..."
    PRERECOVERY_BACKUP_DIR="$BACKUP_BASE_DIR/pre-recovery-$(date +%Y%m%d_%H%M%S)"
    mkdir -p "$PRERECOVERY_BACKUP_DIR"

    if pg_dump -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
        --no-password --verbose --clean --if-exists \
        > "$PRERECOVERY_BACKUP_DIR/complete_database.sql" 2>"$PRERECOVERY_BACKUP_DIR/backup.log"; then
        echo -e "  $OK Current database backed up to $PRERECOVERY_BACKUP_DIR"
    else
        echo -e "  $WARN Could not backup current database (it may not exist yet)"
    fi

    # Restore from complete dump if available
    if [ -f "$BACKUP_DIR/complete_database.sql" ]; then
        echo "  📥 Restoring from complete database dump..."

        # The complete dump contains DROP DATABASE and CREATE DATABASE commands
        # We need to run it against the 'postgres' database to allow it to manage the target database
        echo "    � Importing backup data (this will drop and recreate the database)..."

        # Terminate all connections to the database
        echo "    🔌 Terminating all connections to database..."
        psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d postgres \
            --no-password -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$POSTGRES_DB' AND pid <> pg_backend_pid();" >/dev/null 2>&1 || true
        if psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d postgres \
            --no-password -f "$BACKUP_DIR/complete_database.sql" > "$BACKUP_DIR/restore.log" 2>&1; then
            echo -e "  $OK Database restored from complete dump"
        else
            echo -e "  $ERROR Failed to restore database. Check $BACKUP_DIR/restore.log for details"
            echo "    Last 20 lines of restore log:"
            tail -20 "$BACKUP_DIR/restore.log" | sed 's/^/    /'
            unset PGPASSWORD
            exit 1
        fi
    elif [ -f "$BACKUP_DIR/schema_only.sql" ] && [ -f "$BACKUP_DIR/data_only.sql" ]; then
        echo "  📥 Restoring from schema and data dumps..."

        # Drop and recreate database
        echo "    🗑️ Dropping existing database..."
        psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d postgres \
            --no-password -c "DROP DATABASE IF EXISTS $POSTGRES_DB;" 2>/dev/null || true

        echo "    🆕 Creating fresh database..."
        psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d postgres \
            --no-password -c "CREATE DATABASE $POSTGRES_DB OWNER $POSTGRES_USER;" 2>/dev/null

        echo "    🏗️ Restoring schema..."
        psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
            --no-password < "$BACKUP_DIR/schema_only.sql" 2>"$BACKUP_DIR/restore_schema.log"

        echo "    📤 Restoring data..."
        if psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
            --no-password < "$BACKUP_DIR/data_only.sql" 2>"$BACKUP_DIR/restore_data.log"; then
            echo -e "  $OK Database restored from schema and data dumps"
        else
            echo -e "  $ERROR Failed to restore data. Check $BACKUP_DIR/restore_data.log for details"
            unset PGPASSWORD
            exit 1
        fi
    else
        echo -e "  $ERROR No valid backup files found in $BACKUP_DIR"
        echo "    Expected: complete_database.sql OR (schema_only.sql + data_only.sql)"
        unset PGPASSWORD
        exit 1
    fi

    # Clean up password
    unset PGPASSWORD

    # Clean up temporary S3 backup directory if it was used
    if [ "$BACKUP_SOURCE" = "s3" ]; then
        echo "  🧹 Cleaning up temporary S3 backup directory..."
        rm -rf "$BACKUP_DIR"
        echo -e "  $OK Temporary files removed"
    fi

    echo -e "  $OK Database recovery completed successfully"
    echo "  💡 Pre-recovery backup saved to: $PRERECOVERY_BACKUP_DIR"
}

# Stop services
stop_services() {
    echo "🛑 Stopping $NAME_OF_APPLICATION services..."

    # Remove backup cron job
    remove_backup_cron

    # Create database backup before stopping services
    backup_database || echo -e "  ⚠️ Pre-stop database backup failed; continuing to stop services anyway"

    # Create logs backup before stopping services (best-effort:
    # a logs-backup failure must NOT prevent services from being stopped)
    backup_logs || echo -e "  ⚠️ Pre-stop logs backup failed; continuing to stop services anyway"

    CLEANUP_NEEDED=false

    if [ "$LOCAL_MODE" = "locally" ]; then
        stop_flask_service || CLEANUP_NEEDED=true
        remove_nginx_config
        stop_nginx_service
        confirm_gitea_stop
    elif [ "$LOCAL_MODE" = "docker" ]; then
        stop_docker_services
    else
        stop_flask_service || CLEANUP_NEEDED=true
        remove_nginx_config
        stop_nginx_service
        confirm_gitea_stop
        stop_docker_services
    fi

    if [ "$CLEANUP_NEEDED" = "true" ]; then
        provide_cleanup_guidance
    fi

    echo -e "  $OK Services stop process completed"
}

# Confirm Gitea stop with user menu
confirm_gitea_stop() {
    if systemctl is-active --quiet gitea 2>/dev/null; then
        echo "⚠️ Gitea is currently running"

        # Auto-select "No" when --keep-gitea-running parameter is set
        if [ "$KEEP_GITEA_RUNNING" = "true" ]; then
            echo "  🔧 Auto-selecting: No, keep Gitea configuration (--keep-gitea-running parameter set)"
            CHOICE="no"
        # Check if simple-term-menu is available for interactive selection
        elif python3 -c "from simple_term_menu import TerminalMenu" 2>/dev/null; then
            # Use Python simple-term-menu for interactive selection
            CHOICE=$(python3 << 'EOF'
from simple_term_menu import TerminalMenu

options = ["No, keep Gitea configuration (but nginx is stopped)","Yes, stop and remove Gitea configuration"]
terminal_menu = TerminalMenu(
options,
title="🔧 Do you want to stop Gitea service?",
menu_cursor="▶ ",
menu_cursor_style=("fg_red", "bold"),
menu_highlight_style=("bg_red", "fg_yellow"),
cycle_cursor=True
)

menu_entry_index = terminal_menu.show()
print("no" if menu_entry_index == 0 else "yes")
EOF
)
        else
            # Fallback to simple prompt
            echo "Do you want to stop and remove Gitea configuration?"
            echo "1) Yes, stop and remove Gitea configuration"
            echo "2) No, keep Gitea configuration (but nginx is stopped)"
            read -p "Enter your choice (1-2): " choice
            case $choice in
                1) CHOICE="yes" ;;
                *) CHOICE="no" ;;
            esac
        fi

        if [ "$CHOICE" = "yes" ]; then
            remove_gitea
        else
            echo "  ⏭️ Skipping Gitea stop - service will continue running"
        fi
    else
        echo "  ℹ️ Gitea is not running - skipping"
    fi
}

# Remove Gitea installation
remove_gitea() {
    echo "🗑️ Stopping and removing Gitea installation..."

    # Stop and disable Gitea service
    sudo systemctl stop gitea 2>/dev/null || true
    sudo systemctl disable gitea 2>/dev/null || true

    # Remove systemd service file
    sudo rm -f /etc/systemd/system/gitea.service
    sudo systemctl daemon-reload

    # Remove Gitea binary
    sudo rm -f /usr/local/bin/gitea

    # Remove configuration and data
    sudo rm -rf /etc/gitea
    sudo rm -rf /var/lib/gitea
    sudo rm -rf /home/${LINUX_USER_INSTALLATION}/admin

    # Remove git user
    sudo userdel git 2>/dev/null || true
    sudo groupdel git 2>/dev/null || true

    echo "  ✅ Gitea stopped and removed successfully"
}

stop_flask_service() {
    local success=true

    # Try to stop using Gunicorn PID file first
    if [ -f "./conf/gunicorn.pid" ]; then
        PID=$(cat ./conf/gunicorn.pid)
        if kill -0 "$PID" 2>/dev/null; then
            if kill "$PID" 2>/dev/null; then
                sleep 2
                # Force kill if still running
                if kill -0 "$PID" 2>/dev/null; then
                    if kill -9 "$PID" 2>/dev/null; then
                        echo "  ✅ Application force stopped (PID: $PID)"
                    else
                        echo "  ⚠️ Could not force stop process (PID: $PID) - permission denied"
                        success=false
                    fi
                else
                    echo "  ✅ Application stopped (PID: $PID)"
                fi
            else
                echo "  ⚠️ Could not stop process (PID: $PID) - permission denied"
                success=false
            fi
        else
            echo "  ⚠️ Process not running (stale PID: $PID)"
        fi
        rm -f ./conf/gunicorn.pid
    # Fallback to legacy app.pid
    elif [ -f "./conf/app.pid" ]; then
        PID=$(cat ./conf/app.pid)
        if kill -0 "$PID" 2>/dev/null; then
            if kill "$PID" 2>/dev/null; then
                sleep 2
                # Force kill if still running
                if kill -0 "$PID" 2>/dev/null; then
                    if kill -9 "$PID" 2>/dev/null; then
                        echo "  ✅ Application force stopped (PID: $PID)"
                    else
                        echo "  ⚠️ Could not force stop process (PID: $PID) - permission denied"
                        success=false
                    fi
                else
                    echo "  ✅ Application stopped (PID: $PID)"
                fi
            else
                echo "  ⚠️ Could not stop process (PID: $PID) - permission denied"
                success=false
            fi
        else
            echo "  ⚠️ Process not running (stale PID: $PID)"
        fi
        rm -f ./conf/app.pid
    else
        echo "  ⚠️ No PID file found (./conf/gunicorn.pid or ./conf/app.pid)"
    fi

    # Force kill any remaining Gunicorn processes
    GUNICORN_PIDS=$(pgrep -f "gunicorn.*wsgi:application" 2>/dev/null || true)
    if [ -n "$GUNICORN_PIDS" ]; then
        echo "  🔥 Attempting to stop remaining Gunicorn processes: $GUNICORN_PIDS"
        if pkill -f "gunicorn.*wsgi:application" 2>/dev/null; then
            sleep 2
            REMAINING_PIDS=$(pgrep -f "gunicorn.*wsgi:application" 2>/dev/null || true)
            if [ -n "$REMAINING_PIDS" ]; then
                echo "  🔥 Force killing remaining processes: $REMAINING_PIDS"
                if pkill -9 -f "gunicorn.*wsgi:application" 2>/dev/null; then
                    echo "  ✅ All Gunicorn processes terminated"
                else
                    echo "  ⚠️ Some Gunicorn processes could not be terminated (permission denied)"
                    echo "  💡 Try: sudo pkill -9 -f 'gunicorn.*wsgi:application'"
                    success=false
                fi
            else
                echo "  ✅ All Gunicorn processes terminated"
            fi
        else
            echo "  ⚠️ Could not terminate Gunicorn processes (permission denied)"
            echo "  💡 Try: sudo pkill -f 'gunicorn.*wsgi:application'"
            success=false
        fi
    fi

    # Also check for old Flask development server processes
    FLASK_PIDS=$(pgrep -f "python3 ControlPlanFlaskApp_postgres.py" 2>/dev/null || true)
    if [ -n "$FLASK_PIDS" ]; then
        echo "  🔥 Found old Flask development server processes: $FLASK_PIDS"
        pkill -9 -f "python3 ControlPlanFlaskApp_postgres.py" 2>/dev/null || true
    fi

    # Return appropriate exit code
    if [ "$success" = "false" ]; then
        return 1
    fi
    return 0
}

remove_nginx_config() {
    if [ -f "/etc/nginx/sites-enabled/${NAME_OF_APPLICATION}" ]; then
        sudo rm -f /etc/nginx/sites-enabled/${NAME_OF_APPLICATION}
        # Only reload nginx if it's running
        if systemctl is-active --quiet nginx; then
            sudo nginx -t && sudo systemctl reload nginx
        fi
        echo "  ✅ Nginx configuration removed"
    fi
}

stop_nginx_service() {
    if systemctl is-active --quiet nginx; then
        sudo systemctl stop nginx
        echo "  ✅ Nginx service stopped"
    else
        echo "  ⚠️ Nginx service was not running"
    fi
}

stop_docker_services() {
    docker-compose down
}

# Show logs
show_logs() {
    echo "📋 $NAME_OF_APPLICATION Service Logs:"
    show_flask_logs
    show_nginx_logs
    show_docker_logs
}

show_flask_logs() {
    echo "  🐍 Flask Application Logs:"

    # Show Gunicorn logs
    if [ -f "logs/gunicorn_error.log" ]; then
        echo "    📋 Gunicorn Error Log (last 20 lines):"
        tail -n 20 logs/gunicorn_error.log
        echo ""
    fi

    if [ -f "logs/gunicorn_access.log" ]; then
        echo "    📋 Gunicorn Access Log (last 10 lines):"
        tail -n 10 logs/gunicorn_access.log
        echo ""
    fi

    # Show legacy Flask logs if they exist
    LOG_FILE="logs/app_logs_$(date +%Y%m%d).log"
    if [ -f "$LOG_FILE" ]; then
        echo "    📋 Legacy Flask Log ($LOG_FILE):"
        tail -n 20 "$LOG_FILE"
    else
        # Try to find any app logs in logs directory
        if ls logs/app_logs_*.log 1> /dev/null 2>&1; then
            echo "    📋 Available legacy log files:"
            ls -la logs/app_logs_*.log
        fi
    fi

    # Show available log files
    if ls logs/*.log 1> /dev/null 2>&1; then
        echo "    📁 All available log files:"
        ls -la logs/*.log
    fi
}

show_nginx_logs() {
    echo ""
    echo "🌐 Nginx Error Logs (last 20 lines):"
    sudo tail -n 20 /var/log/nginx/error.log 2>/dev/null || echo "  ❌ Cannot access Nginx logs"
}

show_docker_logs() {
    HTTP_PORT=$HTTP_PORT HTTPS_PORT=$((HTTPS_PORT + 363)) HTTP_PORT2=$HTTP_PORT2 HTTPS_PORT2=$((HTTPS_PORT2 + 363)) HTTP_PORT3=$HTTP_PORT3 HTTPS_PORT3=$((HTTPS_PORT3 + 363)) HTTP_PORT4=$HTTP_PORT4 HTTPS_PORT4=$((HTTPS_PORT4 + 363)) HTTP_PORT5=$HTTP_PORT5 HTTPS_PORT5=$((HTTPS_PORT5 + 363)) HTTP_PORT6=$HTTP_PORT6 HTTPS_PORT6=$((HTTPS_PORT6 + 363)) USER_ID=$USER_ID docker-compose logs -f
}

# Restart services
restart_services() {
    echo "🔄 Restarting $NAME_OF_APPLICATION services..."

    if [ "$LOCAL_MODE" = "locally" ]; then
        restart_flask_service
        reload_nginx_config
    elif [ "$LOCAL_MODE" = "docker" ]; then
        restart_docker_services
    else
        restart_flask_service
        reload_nginx_config
        restart_docker_services
    fi

    echo "✅ Services restarted"
}

# Upgrade the application by fetching and merging latest changes from git
upgrade() {
    echo "⬆️  Upgrading $NAME_OF_APPLICATION..."

    # Check if we are in a git repository
    if [ ! -d ".git" ]; then
        echo -e "  $ERROR Not a git repository. Cannot upgrade."
        exit 1
    fi

    # Show current branch and commit
    CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
    CURRENT_COMMIT=$(git rev-parse --short HEAD 2>/dev/null)
    echo "  📍 Current branch: $CURRENT_BRANCH"
    echo "  📍 Current commit: $CURRENT_COMMIT"

    # Check for uncommitted changes
    if ! git diff --quiet 2>/dev/null || ! git diff --cached --quiet 2>/dev/null; then
        echo -e "  $WARN Uncommitted changes detected. Stashing before upgrade..."
        git stash
        STASHED=true
    else
        STASHED=false
    fi

    # Fetch latest changes from remote
    echo "  📥 Fetching latest changes from remote..."
    if git fetch --all; then
        echo -e "  $OK Fetch completed"
    else
        echo -e "  $ERROR Failed to fetch from remote"
        if [ "$STASHED" = true ]; then
            echo "  🔄 Restoring stashed changes..."
            git stash pop
        fi
        exit 1
    fi

    # Merge changes
    echo "  🔀 Merging changes from origin/$CURRENT_BRANCH..."
    if git merge "origin/$CURRENT_BRANCH"; then
        NEW_COMMIT=$(git rev-parse --short HEAD 2>/dev/null)
        echo -e "  $OK Merge completed"
        echo "  📍 New commit: $NEW_COMMIT"
    else
        echo -e "  $ERROR Merge failed (conflicts detected)"
        echo "    💡 Resolve conflicts manually, then run: git merge --continue"
        if [ "$STASHED" = true ]; then
            echo "    💡 Stashed changes will need to be restored manually: git stash pop"
        fi
        exit 1
    fi

    # Restore stashed changes if any
    if [ "$STASHED" = true ]; then
        echo "  🔄 Restoring stashed changes..."
        if git stash pop; then
            echo -e "  $OK Stashed changes restored"
        else
            echo -e "  $WARN Conflict while restoring stashed changes"
            echo "    💡 Resolve conflicts manually"
        fi
    fi

    echo "✅ Upgrade completed successfully ($CURRENT_COMMIT → $NEW_COMMIT)"
}

restart_flask_service() {
    echo "  🔄 Restarting Flask application..."

    # Use the improved stop function
    if ! stop_flask_service; then
        echo "  ⚠️ Some processes could not be stopped, but continuing with restart..."
    fi

    echo "  🚀 Starting Flask application with Gunicorn..."
    # Create required directories
    mkdir -p logs conf

    # Activate virtual environment if available
    if [ -d ".venv" ]; then
        source .venv/bin/activate
    fi

    # Find gunicorn executable
    GUNICORN_CMD=""
    if [ -d ".venv" ] && [ -f ".venv/bin/gunicorn" ]; then
        GUNICORN_CMD=".venv/bin/gunicorn"
    elif command -v gunicorn >/dev/null 2>&1; then
        GUNICORN_CMD="gunicorn"
    else
        echo "  ❌ Gunicorn not found"
        return 1
    fi

    # Start Gunicorn (daemon mode is configured in gunicorn.conf.py)
    if $GUNICORN_CMD --config gunicorn.conf.py wsgi:application; then
        # Wait for daemon to start and get PID from pidfile
        sleep 2
        if [ -f "conf/gunicorn.pid" ]; then
            NEW_PID=$(cat conf/gunicorn.pid)
            if kill -0 "$NEW_PID" 2>/dev/null; then
                echo "  ✅ Flask application restarted with Gunicorn (PID: $NEW_PID)"
            else
                echo "  ❌ Gunicorn failed to restart (check logs: logs/gunicorn_error.log)"
                return 1
            fi
        else
            echo "  ❌ Gunicorn PID file not created (check logs: logs/gunicorn_error.log)"
            return 1
        fi
    else
        echo "  ❌ Failed to restart Gunicorn (check logs: logs/gunicorn_error.log)"
        return 1
    fi
}

reload_nginx_config() {
    if systemctl is-active --quiet nginx; then
        sudo nginx -t && sudo systemctl reload nginx
    else
        sudo systemctl start nginx
        sudo nginx -t
    fi
}

restart_docker_services() {
    HTTP_PORT=$HTTP_PORT HTTPS_PORT=$((HTTPS_PORT + 363)) HTTP_PORT2=$HTTP_PORT2 HTTPS_PORT2=$((HTTPS_PORT2 + 363)) HTTP_PORT3=$HTTP_PORT3 HTTPS_PORT3=$((HTTPS_PORT3 + 363)) HTTP_PORT4=$HTTP_PORT4 HTTPS_PORT4=$((HTTPS_PORT4 + 363)) HTTP_PORT5=$HTTP_PORT5 HTTPS_PORT5=$((HTTPS_PORT5 + 363)) HTTP_PORT6=$HTTP_PORT6 HTTPS_PORT6=$((HTTPS_PORT6 + 363)) USER_ID=$USER_ID docker-compose restart
}

# Start services
start_services() {
    echo "🚀 Starting $NAME_OF_APPLICATION deployment..."

    if [ "$LOCAL_MODE" = "locally" ]; then
        start_local_deployment
    elif [ "$LOCAL_MODE" = "docker" ]; then
        start_docker_deployment
    fi
}

start_local_deployment() {
    echo "💻 Starting local deployment..."
    install_python_dependencies

    # Setup Gitea (will skip if already configured) - non-blocking
    setup_gitea || echo "  ⚠️ Gitea setup failed - continuing with core services"

    # Always start Flask and Nginx regardless of Gitea status
    echo "🚀 Starting core services..."
    start_flask_application
    configure_nginx
    configure_firewall

    # Sync nginx locations as the final startup step (runs on top of reloaded nginx)
    sync_nginx_locations

    echo "✅ Local deployment completed successfully!"
}

# Setup Gitea for local development
setup_gitea() {
    echo "🔧 Checking Gitea installation..."

    # Check if Gitea is already running
    if systemctl is-active --quiet gitea 2>/dev/null; then
        echo "  ✅ Gitea is already running - skipping setup"
        return 0
    fi

    # Check if already configured
    if [ -f "/etc/gitea/app.ini" ]; then
        echo "  ✅ Gitea is already configured - starting service"
        sudo systemctl start gitea 2>/dev/null || true
        if systemctl is-active --quiet gitea; then
            echo "  ✅ Gitea is running on http://localhost:3000"
        fi
        return 0
    fi

    # Check if Gitea is installed
    if ! command -v gitea &> /dev/null; then
        echo "  📦 Installing Gitea..."

        # Download and install Gitea
        wget -O "$TMP_DIR/gitea" https://dl.gitea.io/gitea/1.21.3/gitea-1.21.3-linux-amd64
        sudo mv "$TMP_DIR/gitea" /usr/local/bin/gitea
        sudo chmod +x /usr/local/bin/gitea

        # Create gitea user
        sudo adduser --system --shell /bin/bash --gecos 'Git Version Control' --group --disabled-password --home /home/git git || true

        # Create directories
        sudo mkdir -p /var/lib/gitea/{custom,data,log}
        sudo chown -R git:git /var/lib/gitea/
        sudo chmod -R 750 /var/lib/gitea/

        # Create systemd service
        sudo tee /etc/systemd/system/gitea.service > /dev/null << 'EOF'
[Unit]
Description=Gitea (Git with a cup of tea)
After=syslog.target
After=network.target

[Service]
RestartSec=2s
Type=simple
User=git
Group=git
WorkingDirectory=/var/lib/gitea/
ExecStart=/usr/local/bin/gitea web --config /etc/gitea/app.ini
Restart=always
Environment=USER=git HOME=/home/git GITEA_WORK_DIR=/var/lib/gitea

[Install]
WantedBy=multi-user.target
EOF

        # Create config directory
        sudo mkdir -p /etc/gitea
        sudo chown root:git /etc/gitea
        sudo chmod 770 /etc/gitea

        echo "  ✅ Gitea installed successfully"
        configure_gitea
    fi

    # Only create admin user if Gitea started successfully
    if systemctl is-active --quiet gitea; then
        create_gitea_admin_user
    fi

    # Start Gitea service
    echo "🚀 Starting Gitea service..."
    sudo systemctl daemon-reload
    sudo systemctl enable gitea
    sudo systemctl start gitea

    # Wait for Gitea to start with timeout
    echo "  ⏳ Waiting for Gitea to start..."
    for i in {1..20}; do
        if systemctl is-active --quiet gitea; then
            echo "  ✅ Gitea service is active"
            break
        fi
        sleep 1
    done

    if systemctl is-active --quiet gitea; then
        echo "  ✅ Gitea is running on http://localhost:3000"
        # Create admin user after Gitea is confirmed running
        create_gitea_admin_user
    else
        echo "  ❌ Failed to start Gitea - continuing without it"
        return 1
    fi
}

# Configure Gitea with predefined settings
configure_gitea() {
    echo "  ⚙️ Configuring Gitea..."

    # Create required directories
    sudo mkdir -p /home/${LINUX_USER_INSTALLATION}/admin
    sudo mkdir -p /home/${LINUX_USER_INSTALLATION}/admin/db
    sudo mkdir -p /home/${LINUX_USER_INSTALLATION}/admin/data
    sudo mkdir -p /home/${LINUX_USER_INSTALLATION}/admin/data/gitea-repositories
    sudo chown -R git:git /home/${LINUX_USER_INSTALLATION}/admin
    sudo chmod a+w /home/${LINUX_USER_INSTALLATION}/admin/db/gitea.db

    # Create Gitea configuration
    sudo tee /etc/gitea/app.ini > /dev/null << EOF
[database]
DB_TYPE = sqlite3
PATH = /home/${LINUX_USER_INSTALLATION}/admin/db/gitea.db

[repository]
ROOT = /home/${LINUX_USER_INSTALLATION}/admin/data/gitea-repositories

[server]
DOMAIN = www.${S3_BUCKET_NAME}.com
HTTP_ADDR = 0.0.0.0
HTTP_PORT = 3000
ROOT_URL = https://www.${S3_BUCKET_NAME}.com/gitea/

[mailer]
ENABLED = false

[service]
DISABLE_REGISTRATION = false
REQUIRE_SIGNIN_VIEW = false

[log]
MODE = file
LEVEL = Info
ROOT_PATH = /var/lib/gitea/log

[security]
INSTALL_LOCK = true
DISABLE_QUERY_AUTH_TOKEN = true

[git.lfs]
START_SERVER = true
CONTENT_PATH = /home/${LINUX_USER_INSTALLATION}/admin

[repository]
ENABLE_PUSH_CREATE_USER = true
ENABLE_PUSH_CREATE_ORG = true
EOF

    sudo chown git:git /etc/gitea/app.ini
    sudo chmod 640 /etc/gitea/app.ini

    echo "  ✅ Gitea configured successfully"
}

# Setup Gitea admin user and API token
create_gitea_admin_user() {
    echo "👤 Setting up Gitea admin access..."

    # Wait for Gitea to be ready with timeout
    echo "  ⏳ Waiting for Gitea to be ready..."
    for i in {1..30}; do
        if curl -s http://localhost:3000 >/dev/null 2>&1; then
            echo "  ✅ Gitea is responding"
            break
        fi
        sleep 1
    done

    # Set environment variables for Gitea CLI
    export GITEA_WORK_DIR=/var/lib/gitea
    export USER=git
    export HOME=/home/git

    # Create gitadmin user with timeout
    echo "👤 Creating gitadmin user..."
    if timeout 10 sudo -u git -E /usr/local/bin/gitea admin user create \
        --username gitadmin \
        --password password \
        --email admin@${S3_BUCKET_NAME}.fr \
        --admin \
        --config /etc/gitea/app.ini \
        --work-path /var/lib/gitea 2>/dev/null; then
        echo "  ✅ Gitadmin user created successfully"
    else
        echo "  ⚠️ Failed to create gitadmin user automatically, trying manual creation..."
        # Retry without timeout for better error visibility
        sudo -u git -E /usr/local/bin/gitea admin user create \
            --username gitadmin \
            --password password \
            --email admin@${S3_BUCKET_NAME}.fr \
            --admin \
            --config /etc/gitea/app.ini \
            --work-path /var/lib/gitea || echo "  ❌ Manual user creation also failed"
    fi

    echo "  🔑 Gitea Admin Credentials:"
    echo "      Username: gitadmin"
    echo "      Password: password"
    echo "      URL: http://www.${S3_BUCKET_NAME}.com/gitea"

    # Try to generate API token with timeout
    setup_api_token
}

# Setup API token for admin user
setup_api_token() {
    echo "  🔑 Setting up API token..."

    # Try to generate API token with timeout
    timeout 10 sudo -u git -E /usr/local/bin/gitea admin user generate-access-token \
        --username gitadmin \
        --token-name "api-access" \
        --scopes "write:admin,write:user,write:repository" \
        --config /etc/gitea/app.ini \
        --work-path /var/lib/gitea 2>/dev/null | grep -o '[a-f0-9]\{40\}' > "$TMP_DIR/gitea_token_temp" 2>/dev/null || true

    if [ -f "$TMP_DIR/gitea_token_temp" ] && [ -s "$TMP_DIR/gitea_token_temp" ]; then
        TOKEN=$(cat "$TMP_DIR/gitea_token_temp")
        echo "$TOKEN" > "$TMP_DIR/gitea_admin_token"
        chmod 600 "$TMP_DIR/gitea_admin_token"
        rm -f "$TMP_DIR/gitea_token_temp"
        echo "  ✅ API token created and saved to $TMP_DIR/gitea_admin_token"
    else
        rm -f "$TMP_DIR/gitea_token_temp"
        echo "  ⚠️ Could not generate API token automatically (timeout or error)"
        echo "  📝 Manual token creation: Login to http://localhost:3000 > Settings > Applications"
    fi
}

start_docker_deployment() {
    echo "🐳 Starting Docker deployment..."
    cleanup_docker
    HTTP_PORT=$HTTP_PORT HTTPS_PORT=$((HTTPS_PORT + 363)) HTTP_PORT2=$HTTP_PORT2 HTTPS_PORT2=$((HTTPS_PORT2 + 363)) HTTP_PORT3=$HTTP_PORT3 HTTPS_PORT3=$((HTTPS_PORT3 + 363)) HTTP_PORT4=$HTTP_PORT4 HTTPS_PORT4=$((HTTPS_PORT4 + 363)) HTTP_PORT5=$HTTP_PORT5 HTTPS_PORT5=$((HTTPS_PORT5 + 363)) HTTP_PORT6=$HTTP_PORT6 HTTPS_PORT6=$((HTTPS_PORT6 + 363)) USER_ID=$USER_ID docker-compose up -d --build

    # Wait and migrate if needed
    if [ "$USE_POSTGRES" = "true" ] && [ -f "softfluid/db/ai_swautomorph.db" ]; then
        sleep 10
        migrate_database
    fi

    echo "  ✅ Docker services started"

    # Sync nginx locations as the final startup step (runs once services are up)
    sync_nginx_locations
}

install_python_dependencies() {
    if [ -f "requirements.txt" ]; then
        echo "  📦 Installing Python dependencies..."

        # Create and activate virtual environment if it doesn't exist
        if [ ! -d ".venv" ]; then
            echo "  🔧 Creating virtual environment..."
            python3 -m venv .venv
        fi

        # Activate virtual environment
        source .venv/bin/activate

        # Upgrade pip first
        pip install --upgrade pip

        # Install dependencies
        if pip install -r requirements.txt; then
            echo "  ✅ Python dependencies installed successfully"
        else
            echo "  ⚠️ Failed to install some dependencies, trying alternative method..."
            pip install --user -r requirements.txt
        fi

        # Verify gunicorn installation
        if ! command -v gunicorn >/dev/null 2>&1 && ! python3 -c "import gunicorn" >/dev/null 2>&1; then
            echo "  ⚠️ Gunicorn not found, installing separately..."
            pip install gunicorn
        fi

        # Verify dotenv installation
        if ! python3 -c "import dotenv" >/dev/null 2>&1; then
            echo "  ⚠️ python-dotenv not found, installing separately..."
            pip install python-dotenv
        fi
    fi
}

start_flask_application() {
    echo "  🚀 Starting Flask application with Gunicorn..."

    # Install dependencies first
    install_python_dependencies

    # Activate virtual environment
    if [ -d ".venv" ]; then
        source .venv/bin/activate
        echo "  ✅ Virtual environment activated"
    fi

    # Stop any existing Flask/Gunicorn processes
    EXISTING_PIDS=$(pgrep -f "gunicorn.*wsgi:application" 2>/dev/null || true)
    if [ -n "$EXISTING_PIDS" ]; then
        echo "  ⚠️ Found existing Gunicorn processes: $EXISTING_PIDS"
        echo "  🛑 Attempting to stop existing processes..."
        pkill -f "gunicorn.*wsgi:application" 2>/dev/null || true
        sleep 2
    fi

    # Create required directories
    mkdir -p logs conf

    # Initialize database if PostgreSQL is enabled
    if [ "${USE_POSTGRES:-true}" = "true" ]; then
        echo "  💾 Initializing PostgreSQL database..."
        export POSTGRES_HOST=${POSTGRES_HOST:-localhost}
        export POSTGRES_DB=${POSTGRES_DB:-ai_swautomorph}
        export POSTGRES_USER=${POSTGRES_USER:-swautomorph}
        export POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-swautomorph_password}
        export USE_POSTGRES=true
        export PYTHONPATH=/home/${LINUX_USER_INSTALLATION}/${NAME_OF_APPLICATION}

        if python3 ./scripts/controller_cli.py init-db; then
            echo "  ✅ Database initialized successfully"
        else
            echo "  ⚠️ Database initialization failed - continuing anyway"
        fi
    fi

    # Start Gunicorn with production configuration
    echo "  🚀 Starting Gunicorn server..."

    # Find gunicorn executable
    GUNICORN_CMD=""
    if [ -d ".venv" ] && [ -f ".venv/bin/gunicorn" ]; then
        GUNICORN_CMD=".venv/bin/gunicorn"
    elif command -v gunicorn >/dev/null 2>&1; then
        GUNICORN_CMD="gunicorn"
    elif [ -f "/home/${LINUX_USER_INSTALLATION}/.local/bin/gunicorn" ]; then
        GUNICORN_CMD="/home/${LINUX_USER_INSTALLATION}/.local/bin/gunicorn"
    elif python3 -c "import gunicorn" >/dev/null 2>&1; then
        GUNICORN_CMD="python3 -m gunicorn"
    else
        echo "  ❌ Gunicorn not found, installing..."
        pip install gunicorn
        GUNICORN_CMD="gunicorn"
    fi

    # Start Gunicorn in daemon mode
    if $GUNICORN_CMD --config gunicorn.conf.py wsgi:application; then
        # Wait for daemon to start and get PID from pidfile
        sleep 2
        if [ -f "./conf/gunicorn.pid" ]; then
            GUNICORN_PID=$(cat ./conf/gunicorn.pid)
            if kill -0 "$GUNICORN_PID" 2>/dev/null; then
                echo "  ✅ Flask application started with Gunicorn (PID: $GUNICORN_PID)"
                echo "  🌐 Application available at: http://localhost:5000"
                echo "  👥 Workers: $(python3 -c 'import multiprocessing; print(multiprocessing.cpu_count() * 2 + 1)')"
            else
                echo "  ❌ Gunicorn failed to start (check logs: logs/gunicorn_error.log)"
                return 1
            fi
        else
            echo "  ❌ Gunicorn PID file not created (check logs: logs/gunicorn_error.log)"
            return 1
        fi
    else
        echo "  ❌ Failed to start Gunicorn"
        return 1
    fi
}

configure_nginx() {
    echo "🌐 Configuring Nginx..."
    # Setup ModSecurity configuration if not already done
    setup_modsecurity_config
    # Check and enable ModSecurity module
    check_and_enable_modsecurity
    create_nginx_config
    enable_nginx_site
    test_and_reload_nginx
}

setup_modsecurity_config() {
    source "$(dirname "${BASH_SOURCE[0]}")/setup_modsecurity_config.sh"
}

check_and_enable_modsecurity() {
    # Check if ModSecurity module exists
    if [ -f "/usr/lib/nginx/modules/ngx_http_modsecurity_module.so" ] || [ -f "/etc/nginx/modules/ngx_http_modsecurity_module.so" ]; then
        enable_modsecurity_module
        MODSECURITY_AVAILABLE=true
    else
        echo "  ⚠️ ModSecurity module not found, using basic reverse proxy configuration"
        MODSECURITY_AVAILABLE=false
    fi
}

enable_modsecurity_module() {
    # Add load_module directive to main nginx.conf if not already present
    if ! grep -q "load_module modules/ngx_http_modsecurity_module.so" /etc/nginx/nginx.conf; then
        sudo sed -i '1i load_module modules/ngx_http_modsecurity_module.so;' /etc/nginx/nginx.conf
        echo "  ✅ ModSecurity module enabled in nginx.conf"
    fi
}

create_nginx_config() {
    # Start with empty config
    > $TMP_DIR/${NAME_OF_APPLICATION}-site

    # Process secondary domains first
    if [ -n "${SECONDARY_DOMAINS:-}" ]; then
        IFS=',' read -ra DOMAIN_CONFIGS <<< "$SECONDARY_DOMAINS"
        for domain_config in "${DOMAIN_CONFIGS[@]}"; do
            IFS=':' read -r domain server_names proxy_pass <<< "$domain_config"

            # Trim whitespace
            domain=$(echo "$domain" | xargs)
            server_names=$(echo "$server_names" | xargs)
            proxy_pass=$(echo "$proxy_pass" | xargs)

            if [ -n "$domain" ] && [ -n "$server_names" ]; then
                cat >> $TMP_DIR/${NAME_OF_APPLICATION}-site << EOF
server {
    listen 443 ssl;
    server_name ${server_names};

    ssl_certificate /home/${LINUX_USER_INSTALLATION}/${PLTF_FOLDER}/ssl/${domain}/fullchain_domain.crt;
    ssl_certificate_key /home/${LINUX_USER_INSTALLATION}/${PLTF_FOLDER}/ssl/${domain}/privateKey_domain.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    location / {
        proxy_pass ${proxy_pass};
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}

EOF
            fi
        done
    fi

    # HTTP redirect for main domain
    cat >> $TMP_DIR/${NAME_OF_APPLICATION}-site << EOF
server {
    listen 80;
    server_name ${DOMAIN} www.${DOMAIN};
    return 301 https://\$host\$request_uri;
}

EOF

    # Main domain HTTPS server block
    cat >> $TMP_DIR/${NAME_OF_APPLICATION}-site << EOF
server {
    listen 443 ssl;
    server_name ${DOMAIN} www.${DOMAIN};

    ssl_certificate /home/${LINUX_USER_INSTALLATION}/${PLTF_FOLDER}/ssl/${DOMAIN}/fullchain_domain.crt;
    ssl_certificate_key /home/${LINUX_USER_INSTALLATION}/${PLTF_FOLDER}/ssl/${DOMAIN}/privateKey_domain.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
EOF

    # Add ModSecurity configuration only if available
    if [ "${MODSECURITY_AVAILABLE:-false}" = "true" ]; then
        cat >> $TMP_DIR/${NAME_OF_APPLICATION}-site << EOF

    # WAF Protection
    modsecurity on;
    modsecurity_rules_file ${MODSECURITY_CONF_DIR:-/etc/nginx/modsec}/main.conf;
EOF
        echo "  ✅ ModSecurity WAF protection enabled"
    else
        echo "  ⚠️ Using basic reverse proxy without WAF protection"
    fi

    # Add location blocks for main domain
    cat >> $TMP_DIR/${NAME_OF_APPLICATION}-site << EOF

    location / {
        proxy_pass http://localhost:${FLASK_PORT:-5000};
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location /gitea/ {
        proxy_pass http://localhost:${GITEA_PORT:-3000}/;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header X-Forwarded-Host \$host;
        proxy_buffering off;

        # WebSocket support for Gitea
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";

        # Increase timeouts for large operations
        proxy_connect_timeout 60s;
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;
    }
}
EOF
}

enable_nginx_site() {
    sudo mv $TMP_DIR/${NAME_OF_APPLICATION}-site /etc/nginx/sites-available/${NAME_OF_APPLICATION}
    sudo ln -sf /etc/nginx/sites-available/${NAME_OF_APPLICATION} /etc/nginx/sites-enabled/
}

test_and_reload_nginx() {
    if systemctl is-active --quiet nginx; then
        echo "  ✅ Nginx is running - reloading configuration"
        sudo nginx -t && sudo systemctl reload nginx
    else
        echo "  🚀 Starting Nginx service"
        sudo systemctl start nginx
        sudo nginx -t
    fi
    echo "  ✅ Nginx configured successfully"
}

configure_firewall() {
    echo "🔥 Configuring firewall for internet access..."
    sudo ufw allow 80/tcp
    sudo ufw allow 443/tcp
    sudo ufw allow 3000/tcp
    sudo ufw allow 53/tcp
    sudo ufw --force enable
}

# Sync nginx location config from the database (final startup step).
# Runs with the activated .venv Python so src.nginx_manager and
# src.database_postgres import correctly. A sync failure is non-fatal:
# it warns and lets the deploy complete (guarded against set -e).
sync_nginx_locations() {
    echo "🔁 Syncing nginx locations from database..."
    if [ ! -f "./scripts/sync_nginx_locations.py" ]; then
        echo -e "  $WARN sync script not found - skipping nginx location sync"
        return 0
    fi
    # Prefer the venv python; fall back to python3. Capture the exit code
    # explicitly so a non-zero sync does not trip `set -e`.
    local sync_python="python3"
    if [ -x ".venv/bin/python" ]; then
        sync_python=".venv/bin/python"
    fi
    if "$sync_python" ./scripts/sync_nginx_locations.py; then
        echo -e "  $OK Nginx locations synced from database"
    else
        echo -e "  $WARN Nginx location sync failed (exit non-zero) - continuing deploy"
    fi
    return 0
}

cleanup_docker() {
    echo "🧹 Cleaning up..."
    HTTP_PORT=$HTTP_PORT HTTPS_PORT=$((HTTPS_PORT + 363)) HTTP_PORT2=$HTTP_PORT2 HTTPS_PORT2=$((HTTPS_PORT2 + 363)) HTTP_PORT3=$HTTP_PORT3 HTTPS_PORT3=$((HTTPS_PORT3 + 363)) HTTP_PORT4=$HTTP_PORT4 HTTPS_PORT4=$((HTTPS_PORT4 + 363)) HTTP_PORT5=$HTTP_PORT5 HTTPS_PORT5=$((HTTPS_PORT5 + 363)) HTTP_PORT6=$HTTP_PORT6 HTTPS_PORT6=$((HTTPS_PORT6 + 363)) USER_ID=$USER_ID docker-compose down --remove-orphans
}

# Validate user input
validate_user_id() {
    if ! [[ "$USER_ID" =~ ^[a-zA-Z0-9_-]+$ ]]; then
        echo "  ❌ Error: user_id must be alphanumeric (letters, numbers, underscore, hyphen)"
        exit 1
    fi
}

# Check system requirements
check_requirements() {
    if [ "$LOCAL_MODE" = "locally" ]; then
        check_local_requirements
    else
        check_docker_requirements
    fi
}

check_local_requirements() {
    if ! command -v python3 &> /dev/null; then
        echo "❌ Python3 is not installed. Installing Python3 first"
        # install python3 and python3-dev
        sudo apt install python3 python3-dev python3-psycopg2
    fi

    # Detect available PostgreSQL major version
    PG_VERSION=$(apt-cache search "^postgresql-[0-9]" 2>/dev/null | grep -oP "^postgresql-\K[0-9]+" | sort -n | tail -1)
    PG_VERSION=${PG_VERSION:-18}

    # Check for PostgreSQL server (not just client) and ensure cluster is running
    if ! pg_isready -q 2>/dev/null; then
        echo "❌ PostgreSQL server is not accepting connections."

        if ! command -v psql &> /dev/null; then
            echo "📦 Installing PostgreSQL ${PG_VERSION} server and development packages..."
            sudo apt update
            sudo apt install -y postgresql-server-dev-all libpq-dev build-essential
            sudo apt install -y postgresql-${PG_VERSION}
            echo "✅ PostgreSQL ${PG_VERSION} installed"
        else
            echo "📦 PostgreSQL client found but server not running. Installing server..."
            sudo apt update
            sudo apt install -y postgresql-${PG_VERSION}
            echo "✅ PostgreSQL ${PG_VERSION} server installed"
        fi

        # Ensure PostgreSQL service is started
        sudo systemctl start postgresql
        sudo systemctl enable postgresql

        # Wait for PostgreSQL to be ready
        echo "  ⏳ Waiting for PostgreSQL to accept connections..."
        for i in {1..30}; do
            if pg_isready -q 2>/dev/null; then
                echo "  ✅ PostgreSQL is accepting connections"
                break
            fi
            sleep 1
        done

        if ! pg_isready -q 2>/dev/null; then
            echo "  ❌ PostgreSQL failed to start. Check: sudo journalctl -u postgresql"
            exit 1
        fi

        # Setup PostgreSQL database and user for the application
        setup_postgresql_database
    fi

    if ! command -v nginx &> /dev/null; then
        echo "📦 Installing Nginx with ModSecurity..."
        install_nginx_with_modsecurity
        echo "✅ Nginx with ModSecurity installed successfully"
    fi
}

install_nginx_with_modsecurity() {
    sudo apt update

    # Install nginx and ModSecurity components
    sudo apt install -y nginx wget git

    # Try to install nginx-module-security (may not be available on all systems)
    sudo apt install -y libmodsecurity3 2>/dev/null || {
        echo "  ⚠️ libmodsecurity3 not available, installing alternative packages"
        sudo apt install -y libmodsecurity-dev modsecurity-crs 2>/dev/null || true
    }

    # Create ModSecurity directories
    sudo mkdir -p ${MODSECURITY_CONF_DIR:-/etc/nginx/modsec}

    # Download OWASP CRS rules if not available via package
    if [ ! -d "${MODSECURITY_RULES_DIR:-/usr/share/modsecurity-crs}" ]; then
        sudo git clone https://github.com/coreruleset/coreruleset.git ${MODSECURITY_RULES_DIR:-/usr/share/modsecurity-crs}
        cd ${MODSECURITY_RULES_DIR:-/usr/share/modsecurity-crs}
        sudo git checkout ${OWASP_CRS_VERSION:-v3.3.5}
    fi

    # Configure ModSecurity
    setup_modsecurity_config

    # Check if ModSecurity module is available before enabling
    check_and_enable_modsecurity

    sudo systemctl enable nginx
}

# Setup PostgreSQL database and user for the application
setup_postgresql_database() {
    echo "💾 Setting up PostgreSQL database and user..."

    # Load environment variables from .env file if it exists
    if [ -f ".env" ]; then
        echo "  📋 Loading PostgreSQL credentials from .env file..."
        export $(grep -v '^#' .env | grep -v '^$' | xargs)
    fi

    # Start PostgreSQL service
    sudo systemctl start postgresql
    sudo systemctl enable postgresql

    # Get PostgreSQL credentials from environment or use defaults
    POSTGRES_DB=${POSTGRES_DB:-"ai_swautomorph"}
    POSTGRES_USER=${POSTGRES_USER:-"swautomorph"}
    POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-"swautomorph_password"}

    echo "  🔗 Using credentials: $POSTGRES_USER@localhost:5432/$POSTGRES_DB"

    # Check if user already exists
    if sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$POSTGRES_USER'" | grep -q 1; then
        echo "  ✅ PostgreSQL user '$POSTGRES_USER' already exists"
        # Update password in case it changed
        echo "  🔑 Updating password for user '$POSTGRES_USER'..."
        sudo -u postgres psql -c "ALTER USER $POSTGRES_USER WITH PASSWORD '$POSTGRES_PASSWORD' CREATEDB;"
    else
        echo "  👤 Creating PostgreSQL user '$POSTGRES_USER'..."
        sudo -u postgres psql -c "CREATE USER $POSTGRES_USER WITH PASSWORD '$POSTGRES_PASSWORD' CREATEDB;"
        echo "  ✅ PostgreSQL user '$POSTGRES_USER' created"
    fi

    # Check if database already exists
    if sudo -u postgres psql -lqt | cut -d \| -f 1 | grep -qw "$POSTGRES_DB"; then
        echo "  ✅ PostgreSQL database '$POSTGRES_DB' already exists"
    else
        echo "  💾 Creating PostgreSQL database '$POSTGRES_DB'..."
        sudo -u postgres psql -c "CREATE DATABASE $POSTGRES_DB OWNER $POSTGRES_USER;"
        echo "  ✅ PostgreSQL database '$POSTGRES_DB' created"
    fi

    # Grant privileges
    echo "  🔑 Granting privileges to user '$POSTGRES_USER'..."
    sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE $POSTGRES_DB TO $POSTGRES_USER;"
    sudo -u postgres psql -c "GRANT CREATE ON SCHEMA public TO $POSTGRES_USER;" -d "$POSTGRES_DB"

    # Test connection
    echo "  🔍 Testing PostgreSQL connection..."
    if PGPASSWORD="$POSTGRES_PASSWORD" psql -h localhost -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT version();" >/dev/null 2>&1; then
        echo "  ✅ PostgreSQL connection test successful"
    else
        echo "  ⚠️ PostgreSQL connection test failed - check configuration"
        echo "    💡 Try manual connection: PGPASSWORD='$POSTGRES_PASSWORD' psql -h localhost -U $POSTGRES_USER -d $POSTGRES_DB"
    fi

    echo "  ✅ PostgreSQL database setup completed"
}

check_docker_requirements() {
    if ! command -v docker &> /dev/null; then
        echo "  ❌ Docker is not installed. Please install Docker first."
        exit 1
    fi

    if ! command -v docker-compose &> /dev/null; then
        echo "  ❌ Docker Compose is not installed. Please install Docker Compose first."
        exit 1
    fi
}

# Setup directories and certificates
setup_environment() {
    create_directories
    setup_ssl_certificates
    generate_environment_file
}

create_directories() {
    echo "📁 Creating directories..."
    mkdir -p data ssl logs softfluid/db
    chmod 755 data ssl logs softfluid/db
}

setup_ssl_certificates() {
    if [ ! -f ssl/fullchain_domain.crt ] || [ ! -f ssl/privateKey_domain.key ]; then
        echo "🔐 Generating SSL certificates..."
        ./scripts/generate_ssl.sh
    else
        echo "  ✅ SSL certificates already exist"
    fi
}

generate_environment_file() {
    if [ ! -f .env ]; then
        echo "🔑 Generating environment configuration..."
        SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")

        # Load existing password from .env if it exists, otherwise use default
        if [ -f ".env" ] && grep -q "POSTGRES_PASSWORD=" .env; then
            POSTGRES_PASSWORD=$(grep "POSTGRES_PASSWORD=" .env | cut -d'=' -f2)
        else
            POSTGRES_PASSWORD="swautomorph_password"
        fi

        cat > .env << EOF
# PostgreSQL Configuration (when USE_POSTGRES=true)
POSTGRES_HOST=localhost
POSTGRES_DB=ai_swautomorph
POSTGRES_USER=swautomorph
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
POSTGRES_PORT=5432
POSTGRES_MIN_CONN=2
POSTGRES_MAX_CONN=20
POSTGRES_TIMEOUT=10

# Flask Configuration
SECRET_KEY=${SECRET_KEY}
FLASK_ENV=production

# Active/Active Configuration
USE_POSTGRES=true
HTTP_PORT_1=6000
HTTP_PORT_2=6002
HTTP_LB_PORT=80
HTTPS_PORT=6001

# Instance Configuration
INSTANCE_1_ID=1
INSTANCE_2_ID=2
EOF
        echo "  ✅ Environment file created (.env)"
    else
        echo "  ✅ Environment file already exists (.env)"
    fi
}

# Show usage information
help() {
    echo "🚀 ${PLTF_NAME} Deployment Script v${VERSION}"
    echo "Usage: $0 [COMMAND] [MODE] [USER_ID] [USER_NAME] [USER_EMAIL] [DESCRIPTION] [OPTIONS]"
    echo ""
    echo "COMMANDS:"
    echo "  start     - Deploy and start all services (Flask app, Nginx, Gitea)"
    echo "              • Sets up SSL certificates and environment"
    echo "              • Installs dependencies and configures services"
    echo "              • Opens firewall ports (80, 443, 3000)"
    echo "              • Creates deployment directories and logs"
    echo "              • Sets up hourly database backup cron job"
    echo ""
    echo "  stop      - Stop all running services and clean up"
    echo "  -o        - Stop all running services and clean up (alias for stop)"
    echo "  --stop    - Stop all running services and clean up (alias for stop)"
    echo "              • Removes hourly database backup cron job"
    echo "              • Creates final database backup in ./softfluid/db/backup/\$DATETIME/"
    echo "              • Stops Flask application and removes PID file"
    echo "              • Removes Nginx site configuration"
    echo "              • Optionally stops and removes Gitea (interactive)"
    echo "              • Stops Docker containers if running"
    echo ""
    echo "  restart   - Restart all services without full redeployment"
    echo "  -r        - Restart all services without full redeployment (alias for restart)"
    echo "  --restart - Restart all services without full redeployment (alias for restart)"
    echo "              • Restarts Flask application with new PID"
    echo "              • Reloads Nginx configuration"
    echo "              • Restarts Docker containers if in Docker mode"
    echo ""
    echo "  upgrade   - Upgrade application from git remote"
    echo "  --upgrade - Upgrade application from git remote (alias for upgrade)"
    echo "              • Stashes uncommitted changes if any"
    echo "              • Fetches latest changes from remote (git fetch --all)"
    echo "              • Merges changes from origin into current branch"
    echo "              • Restores stashed changes after merge"
    echo ""
    echo "  ps        - Show status of all services"
    echo "  -p        - Show status of all services (alias for ps)"
    echo "  --ps      - Show status of all services (alias for ps)"
    echo "              • Flask application status and PID"
    echo "              • Nginx service status and site configuration"
    echo "              • Gitea service status"
    echo "              • Docker Compose container status"
    echo ""
    echo "  logs      - Display logs from all services"
    echo "  -l        - Display logs from all services (alias for logs)"
    echo "  --logs    - Display logs from all services (alias for logs)"
    echo "              • Flask application logs (current day)"
    echo "              • Nginx error logs (last 20 lines)"
    echo "              • Docker Compose logs (if running)"
    echo ""
    echo "  --recover_db - Recover PostgreSQL database from backup"
    echo "              • Lists available backup dates for selection"
    echo "              • Restores PostgreSQL database from selected backup"
    echo "              • Creates pre-recovery backup of current database"
    echo "              • Backs up current database before recovery"
    echo ""
    echo "  backup_db    - Create database backup manually"
    echo "  --backup_database - Create database backup manually (alias for backup_db)"
    echo "              • Creates timestamped backup in ./softfluid/db/backup/"
    echo "              • Dumps all database tables individually"
    echo "              • Creates complete database dump"
    echo "              • Syncs backup to S3 using OVH-SWAUTOMORPH profile"
    echo ""
    echo "  help      - Show this help menu"
    echo "  --help    - Show this help menu (alias for help)"
    echo "  -h        - Show this help menu (short alias for help)"
    echo ""
    echo "  version   - Display the current installed version"
    echo "  --version - Display the current installed version (alias for version)"
    echo "  -v        - Display the current installed version (short alias for version)"
    echo ""
    echo "OPTIONS:"
    echo "  --keep-gitea-running  - Automatically answer 'no' to Gitea stop question"
    echo "                          Keeps Gitea service running during stop operations"
    echo ""
    echo "MODES:"
    echo "  locally   - Deploy without Docker (direct system installation)"
    echo "              • Installs services directly on the host system"
    echo "              • Uses system Python, Nginx, and Gitea"
    echo "              • Suitable for production deployments"
    echo ""
    echo "  docker    - Deploy using Docker containers"
    echo "              • Uses docker-compose.yml configuration"
    echo "              • Isolated container environment"
    echo "              • Suitable for development and testing"
    echo ""
    echo "  [empty]   - Interactive mode (shows deployment menu)"
    echo "              • Prompts user to select deployment mode"
    echo "              • Uses simple-term-menu for better UX"
    echo ""
    echo "PARAMETERS:"
    echo "  USER_ID      - Alphanumeric user identifier (default: 0)"
    echo "                 Used for port calculation and user isolation"
    echo ""
    echo "  USER_NAME    - Display name for the user (default: 'admin')"
    echo "                 Used in configuration and logging"
    echo ""
    echo "  USER_EMAIL   - User email address (default: 'admin@${S3_BUCKET_NAME}.com')"
    echo "                 Used for SSL certificates and notifications"
    echo ""
    echo "  DESCRIPTION  - Deployment description (default: 'Basic Information Display')"
    echo "                 Used for documentation and logging purposes"
    echo ""
    echo "EXAMPLES:"
    echo "  $0 start                     # Interactive mode - shows deployment menu"
    echo "  $0 start locally             # Deploy locally without Docker"
    echo "  $0 start docker              # Deploy using Docker containers"
    echo "  $0 start locally 123 john    # Deploy locally for user 'john' with ID '123'"
    echo "  $0 stop                      # Stop all services (interactive Gitea removal)"
    echo "  $0 stop --keep-gitea-running # Stop all services but keep Gitea running"
    echo "  $0 stop locally              # Stop all services started "locally" (interactive Gitea removal)"
    echo "  $0 restart locally           # Restart local services"
    echo "  $0 upgrade                   # Upgrade application from git remote"
    echo "  $0 ps                        # Check status of all services"
    echo "  $0 logs                      # View logs from all services"
    echo "  $0 help                      # Show this help menu"
    echo "  $0 --help                    # Show this help menu"
    echo "  $0 -h                        # Show this help menu"
    echo "  $0 --version                 # Display current installed version"
    echo "  $0 -v                        # Display current installed version"
    echo ""
    echo "PORTS:"
    echo "  HTTP:  Calculated as 80 + (USER_ID * 100)"
    echo "  HTTPS: HTTP + 1"
    echo "  Gitea: 3000 (fixed)"
    echo "  Flask: 5000 (fixed for local mode)"
    echo ""
    echo "SERVICES:"
    echo "  • Flask Web Application (Python)"
    echo "  • Nginx Reverse Proxy (HTTPS/SSL)"
    echo "  • Gitea Git Repository Server"
    echo "  • Docker Containers (optional)"
    echo ""
    echo "ACCESS URLS:"
    echo "  • Main App: https://www.agentic-ai-plateform.com"
    echo "  • Gitea:    https://www.agentic-ai-plateform.com/gitea"
    echo "  • Local:    https://localhost (with SSL certificates)"
}

# Setup crontab for automatic backups
setup_backup_cron() {
    echo "⏰ Setting up hourly database backup cron job..."
    SCRIPT_PATH=$(realpath "$0")
    CRON_JOB="0 * * * * $SCRIPT_PATH --backup_db >/dev/null 2>&1"

    # Remove existing backup job if any
    (crontab -l 2>/dev/null | grep -v "$SCRIPT_PATH --backup_db") | crontab -

    # Add new backup job
    (crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab -

    echo "  ✅ Hourly backup cron job added"
}

# Remove backup cron job
remove_backup_cron() {
    echo "⏰ Removing database backup cron job..."
    SCRIPT_PATH=$(realpath "$0")

    # Remove backup job
    (crontab -l 2>/dev/null | grep -v "$SCRIPT_PATH --backup_db") | crontab -

    echo "  ✅ Backup cron job removed"
}

# Start env
start() {
    validate_user_id
    check_requirements
    setup_environment
    start_services
    setup_backup_cron
    echo "🎉 Deployment completed successfully!"
}

# Main function - orchestrates the deployment process
main() {
    calculate_ports
    show_environment

    # Show interactive menu for start, stop, restart commands if no LOCAL_MODE specified
    if [[ "$COMMAND" =~ ^(start|-s|--start|stop|-o|--stop|restart|-r|--restart)$ ]] && [ "$LOCAL_MODE" = "0" ]; then
        SELECTED_MODE=$(show_deployment_menu)
        if [ "$SELECTED_MODE" = "locally" ]; then
            LOCAL_MODE="locally"
        elif [ "$SELECTED_MODE" = "docker" ]; then
            LOCAL_MODE="docker"
        fi
    fi

    case $COMMAND in
        "ps"|"-p"|"--ps")
            check_status
            exit 0
            ;;
        "stop"|"-k"|"--stop")
            stop_services
            exit 0
            ;;
        "logs"|"-l"|"--logs")
            show_logs
            exit 0
            ;;
        "recover_db"|"--recover_db")
            recover_database
            exit 0
            ;;
        "backup_db"|"--backup_db")
            backup_database
            exit 0
            ;;
        "migrate_db"|"-m"|"--migrate_db")
            migrate_database
            exit 0
            ;;
        "restart"|"-r"|"--restart")
            restart_services
            exit 0
            ;;
        "upgrade"|"--upgrade")
            upgrade
            exit 0
            ;;
        "start"|"-s"|"--start")
            start
            exit 0
            ;;
        "help"|"--help"|"-h")
            help
            exit 0
            ;;
        "version"|"--version"|"-v")
            echo "${PLTF_NAME} v${VERSION}"
            exit 0
            ;;
        *)
            echo "❌ Unknown command: $COMMAND"
            echo ""
            help
            exit 1
            ;;
    esac
}

# Execute main function
main "$@"
