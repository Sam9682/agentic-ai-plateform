# Agentic AI Platform

## Objective

agentic-ai-plateform is a centralized application deployment and management platform designed for GenAI agents. It provides automated deployment, lifecycle management, and SSO authentication for web applications through multiple interfaces (Web, CLI, API, MCP).

**Core Purpose**: Enable GenAI agents to autonomously deploy, manage, and access web applications without human intervention.

## Features

- 🔐 User registration and authentication with Gitea integration
- 🌐 Web-based dashboard with multi-language support (EN/FR)
- 📱 Application management with **PostgreSQL database** (enterprise-grade performance)
- 🔑 SSO Identity Provider with token-based authentication
- 🚀 **Application deployment system** (Clone, Start, Stop, Monitor, Logs)
- 🐳 Docker containerization with docker-compose
- 🖥️ Command-line interface (CLI) with comprehensive commands
- 🔌 REST API endpoints with streaming support (Server-Sent Events)
- 🤖 MCP (Model Context Protocol) support
- 🛡️ ModSecurity WAF protection with OWASP CRS rules
- 🔄 Automated database backups with PostgreSQL pg_dump
- 💰 Billing and cost tracking system with activity logging
- 🤖 **Virtual AI Agents**: AI Chat Developer and Operations assistants
- 📊 Database health monitoring and statistics
- 🌐 Multi-server deployment support with capacity management
- 🔀 **Dynamic Nginx Locations**: Automatic reverse proxy configuration per user/app
- 📖 Comprehensive user guide and documentation
- 🔧 **PostgreSQL connection pooling** with thread-safe operations
- 🔄 **SQLite to PostgreSQL migration tools**
- 🎮 **MIG Shared GPU**: NVIDIA Multi-Instance GPU partitioning and management per server
- ⚡ **Serverless Docker Execution**: Submit and run Docker-based jobs on-demand
- 🛡️ **Container Runtime Isolation**: Support for both standard containers (runc) and MicroVM isolation (Kata Containers)
- 🔄 **Multi-server Replication**: Peer-to-peer database replication with sync tokens
- 🎭 **App Orchestrator**: Automated application lifecycle orchestration with reconciliation
- 🔒 **Password Reset & 2FA**: Secure password recovery and two-factor authentication via email
- 🧩 **Deploy Templates Catalog**: One-click blueprints (Static Site, FastAPI, n8n, Ollama, Jupyter, Qdrant Vector DB) deployable identically across Dashboard, CLI, MCP, and REST
- 🧙 **Onboarding Setup Wizard**: Guided first-run configuration that safely writes `conf/deploy.ini` (timestamped backup, atomic write, hashed admin password)
- 🧪 **Sandbox Demo Account**: Labeled demo user and sandbox deployments for trying the platform without impacting real data
- 🔢 **Extended Port Allocation**: 12 consecutive ports (6 HTTP + 6 HTTPS) reserved per application
- ↕️ **Sortable Dashboard Grids**: Client-side column sorting across all dashboard tables
- 🟢 **Running-App Highlight**: Running applications are visually highlighted in the dashboard
- 🗂️ **Configurable Install Layout**: Install folder, Linux user, and paths driven by `conf/deploy.ini` (no hardcoded `/ubuntu/`)

## PostgreSQL Migration

### Database Migration
```bash
# Run the automated migration from SQLite to PostgreSQL
python3 ./migration/migrate_sqlite_to_postgres.py

# Configure PostgreSQL connection (environment variables)
export POSTGRES_HOST="localhost"
export POSTGRES_PORT="5432"
export POSTGRES_DB="ai_swautomorph"
export POSTGRES_USER="swautomorph"
export POSTGRES_PASSWORD="swautomorph_password"
```

### Migration Features
- ✅ **Complete Data Migration**: Preserves all existing data during transition
- 🔄 **Type Conversion**: Automatic SQLite to PostgreSQL data type mapping
- 📊 **Schema Mapping**: Column name normalization (SERVER_IP → server_ip)
- ⚡ **Sequence Reset**: Automatic adjustment of auto-increment sequences
- 🔒 **Transaction Safety**: Full rollback capability on migration errors

## Installation Methods

### Prerequisites Check
```bash
# Verify system requirements
which python3 && which pip && which docker && which docker-compose
```

### Interactive Deployment (Recommended)
```bash
# Bootstrap a fresh server. init_pltf.sh prompts for the platform identity
# (folder slug, display name, repo URL and shared submodule URL) and writes
# PLTF_NAME / PLTF_FOLDER into conf/deploy.ini. Press Enter to accept the
# shown defaults, or pre-set the values via environment variables for a
# non-interactive run:
#   PLTF_FOLDER=my-platform PLTF_NAME="My Platform" \
#   REPO_URL=https://github.com/your-org/your-repo.git ./init_pltf.sh
./init_pltf.sh

# The repository is cloned into the chosen PLTF_FOLDER; enter it to deploy.
cd "$PLTF_FOLDER"

# Interactive deployment with menu selection
./deployControlPlan.sh start
```

### Local System Deployment
```bash
# Deploy directly on host system (production)
./deployControlPlan.sh start locally

# With custom user parameters
./deployControlPlan.sh start locally 123 "John Doe" "john@example.com" "Production Deployment"
```

### Docker Deployment
```bash
# Deploy using Docker containers (development/testing)
./deployControlPlan.sh start docker

# Or direct docker-compose
docker-compose up -d --build
```

### Manual Installation Steps
```bash
# 1. Install Python dependencies
pip install -r requirements.txt

# 2. Initialize database
python3 ./scripts/controller_cli.py init-db

# 3a. Start the application (development)
python3 src/ControlPlanFlaskApp_postgres.py

# 3b. Start the application (production, via the WSGI entry point)
gunicorn -c gunicorn.conf.py wsgi:application
```

## Configuration

### Environment Variables
```bash
# Automatically generated during deployment
SECRET_KEY="auto-generated-32-byte-hex"
FLASK_ENV="production"
```

### Configuration File
```bash
# Edit deployment configuration
vim ./conf/deploy.ini

# Key settings:
DOMAIN="www.agentic-ai-plateform.com"
EMAIL="admin@agentic-ai-plateform.com"
GITEA_VERSION="1.21.3"
MODSECURITY_CONF_DIR="/etc/nginx/modsec"
```

### Database Initialization
```bash
# Initialize database schema
python3 ./scripts/controller_cli.py init-db

# Check database health
python3 ./scripts/controller_cli.py db-health
```

### SSL Certificate Setup
```bash
# Auto-generate self-signed certificate
./scripts/generate_ssl.sh

# Or use production certificates (place in ssl/ directory)
# - fullchain_domain.crt
# - privateKey_domain.key
```

## API Access for GenAI Agents

### User Registration
```bash
curl -X POST https://www.agentic-ai-plateform.com/register \
  -H "Content-Type: application/json" \
  -d '{"username":"agent","email":"agent@example.com","password":"secure_pass","first_name":"AI","last_name":"Agent"}'
```

### Application Management
```bash
# List applications
curl https://www.agentic-ai-plateform.com/api/applications

# Add application (admin required)
curl -X POST https://www.agentic-ai-plateform.com/api/applications \
  -H "Content-Type: application/json" \
  -H "Cookie: session=your-session-cookie" \
  -d '{"name":"MyApp","description":"My Application","git_url":"https://github.com/user/myapp.git"}'

# Deploy application with streaming
curl -X POST https://www.agentic-ai-plateform.com/api/deployments \
  -H "Content-Type: application/json" \
  -H "Cookie: session=your-session-cookie" \
  -d '{"application_name":"MyApp","action":"clone","git_url":"https://github.com/user/myapp.git","server_id":1,"stream":true}'

# Application lifecycle management
curl -X POST https://www.agentic-ai-plateform.com/api/deployments \
  -H "Content-Type: application/json" \
  -H "Cookie: session=your-session-cookie" \
  -d '{"application_name":"MyApp","action":"start"}'
```

### Enhanced Server Management
```bash
# List servers with capacity information
curl https://www.swautomorph.com/api/servers

# Allocate server for deployment (automatic capacity-based selection)
curl -X POST https://www.swautomorph.com/api/server/allocate \
  -H "Content-Type: application/json" \
  -H "Cookie: session=your-session-cookie" \
  -d '{"application_name":"MyApp"}'

# Add new server (admin required)
curl -X POST https://www.swautomorph.com/api/servers \
  -H "Content-Type: application/json" \
  -H "Cookie: session=your-session-cookie" \
  -d '{"SERVER_IP":"192.168.1.100","SERVER_NAME":"worker-01","SERVER_CAPACITY_USER_MAX":20,"SERVER_CAPACITY_APPLI_MAX":100,"SERVER_STATUS":"STAND_BY","SERVER_TYPE":"worker"}'
```

### MIG Shared GPU Management
```bash
# Enable shared GPU on a server (admin required)
curl -X PUT https://www.swautomorph.com/api/servers/1/gpu/enabled \
  -H "Content-Type: application/json" \
  -H "Cookie: session=your-session-cookie" \
  -d '{"enabled": true}'

# List available MIG profiles from GPU hardware
curl https://www.swautomorph.com/api/servers/1/gpu/profiles \
  -H "Cookie: session=your-session-cookie"

# Create MIG instances (1-7 profile IDs)
curl -X POST https://www.swautomorph.com/api/servers/1/gpu/instances \
  -H "Content-Type: application/json" \
  -H "Cookie: session=your-session-cookie" \
  -d '{"profile_ids": ["9", "14", "9"]}'

# List active MIG instances
curl https://www.swautomorph.com/api/servers/1/gpu/instances \
  -H "Cookie: session=your-session-cookie"

# Destroy all MIG instances on a server
curl -X DELETE https://www.swautomorph.com/api/servers/1/gpu/instances \
  -H "Cookie: session=your-session-cookie"
```

### Serverless Docker Execution
```bash
# Submit a serverless Docker job
curl -X POST https://www.swautomorph.com/api/jobs \
  -H "Content-Type: application/json" \
  -H "Cookie: session=your-session-cookie" \
  -d '{"image": "python:3.11", "command": "python -c \"print(hello)\"", "timeout": 60}'

# Check job status
curl https://www.swautomorph.com/api/jobs/<job_id> \
  -H "Cookie: session=your-session-cookie"

# List user jobs
curl https://www.swautomorph.com/api/jobs \
  -H "Cookie: session=your-session-cookie"
```

### Deploy Templates (Onboarding Experience)

The platform ships a catalog of ready-to-deploy blueprints. Every surface (Dashboard, CLI, MCP, REST) deploys through the same template service, so behavior is identical everywhere. Deployed apps are exposed at `https://{domain}/{USER_ID}/{APPLICATION_NAME}`.

Built-in templates:

| Template ID       | Type          | Image                                          |
|-------------------|---------------|------------------------------------------------|
| `static-site`     | static_site   | nginx:1.27-alpine                              |
| `fastapi-starter` | fastapi       | tiangolo/uvicorn-gunicorn-fastapi:python3.11   |
| `n8n`             | n8n           | n8nio/n8n:latest                               |
| `ollama`          | ollama        | ollama/ollama:latest                           |
| `jupyter`         | jupyter       | jupyter/base-notebook:latest                   |
| `vector-db`       | vector_db     | qdrant/qdrant:latest                           |

```bash
# List available deploy templates
curl https://www.swautomorph.com/api/templates \
  -H "Cookie: session=your-session-cookie"

# Deploy an application from a template
curl -X POST https://www.swautomorph.com/api/templates/fastapi-starter/deploy \
  -H "Content-Type: application/json" \
  -H "Cookie: session=your-session-cookie" \
  -d '{"application_name":"my-api"}'
```

On any failure after port allocation, partial records are rolled back in a single transaction and the nginx location block is removed, so no partial resources remain.

### Container Runtime Isolation

The platform supports two container runtime types, configurable from the **Settings** page (admin only):

|       Runtime           |                                    Description                                      |                    Use Case                              |
|-------------------------|-------------------------------------------------------------------------------------|----------------------------------------------------------|
| **runc** (default)      | Standard OCI container runtime. Containers share the host kernel,                   | General-purpose workloads where speed and                |
|                         |  providing lightweight and fast execution.                                          |  density are priorities.                                 |
| **kata**                | Kata Containers runtime. Each container runs inside a dedicated lightweight MicroVM | Security-sensitive workloads, multi-tenant environments, | 
|                         |  with its own kernel, providing hardware-level isolation.                           |  or when stronger isolation                              |

**Configuration:**
- Navigate to the **Settings** tab in the admin dashboard
- Select the desired runtime type (`runc` or `kata`) from the dropdown
- Click "Save Runtime Type"

**How it is applied:** When `kata` is selected, the platform adds `--runtime kata`
to the container launch across all three launch paths so containers boot inside a
Kata MicroVM:
- **Orchestrator replica services** — the `docker run` command built in
  `src/orchestrator.py` gains `--runtime kata`.
- **Serverless Docker jobs** — the worker launches job containers with
  `--runtime kata`. The worker reads `runtime_type` **once at startup**, so a
  worker restart is required to pick up a change.
- **Git-based application deployments** — the platform passes the runtime type to
  each app's `deployApp.sh` both as a trailing positional argument and via the
  `RUNTIME_TYPE` environment variable.

The value is validated against an allow-list (`runc`, `kata`); any other value
falls back to `runc`. Selecting `runc` (the Docker default) emits no `--runtime`
flag, so behavior is unchanged.

**`deployApp.sh` contract:** scripts receive the runtime type as the extra
trailing positional argument after the user email, and as `$RUNTIME_TYPE` in the
environment. To honor it, a script can run, for example:

```bash
docker run --runtime "${RUNTIME_TYPE:-runc}" ...
```

Scripts that ignore the extra argument and env var continue to work unchanged.

> **Prerequisite:** the `kata` runtime must be registered with the Docker daemon
> on each server (handled by `init_pltf.sh`). Verify with `docker info` (look for
> `kata` under Runtimes) and `docker run --runtime kata hello-world`.

### Dynamic Nginx Locations
```bash
# Access user applications via dynamic URLs
# Format: https://www.swautomorph.com/{USER_ID}/{APPLICATION_NAME}
# Example: User 2's ai-staticwebsite running on port 6217
curl https://www.swautomorph.com/2/ai-staticwebsite

# Sync all nginx locations from database (admin required)
curl -X POST https://www.swautomorph.com/api/nginx/sync \
  -H "Cookie: session=your-session-cookie"

# Or via CLI
python3 ./scripts/sync_nginx_locations.py
```

### Virtual AI Agents Integration
```bash
# AI Chat Developer Agent (code modifications)
curl -X POST https://www.swautomorph.com/api/request_dev_ai_for_app \
  -H "Content-Type: application/json" \
  -H "Cookie: session=your-session-cookie" \
  -d '{"message":"Add a new API endpoint for user management","application_name":"MyApp","application_folder":"/path/to/app","action_operation":"MODIFY_CODE"}'

# AI Chat Operations Agent (deployment operations)
curl -X POST https://www.swautomorph.com/api/request_ops_ai_for_app \
  -H "Content-Type: application/json" \
  -H "Cookie: session=your-session-cookie" \
  -d '{"message":"[START] Start the application","application_name":"MyApp","application_folder":"/path/to/app","action_operation":"START"}'

# Streaming deployment with real-time logs
curl -X POST https://www.swautomorph.com/api/deployments \
  -H "Content-Type: application/json" \
  -H "Cookie: session=your-session-cookie" \
  -d '{"application_name":"MyApp","action":"start","stream":true}'
```

### Enhanced CLI Interface

The CLI is a `click` command group; run `python3 ./scripts/controller_cli.py --help`
to list every command.

```bash
# Register user
python3 ./scripts/controller_cli.py register --username agent --email agent@example.com --password secure_pass

# List applications
python3 ./scripts/controller_cli.py list-apps

# Add application
python3 ./scripts/controller_cli.py add-app --name MyApp --url https://myapp.com --description "My Application"

# Validate SSO token
python3 ./scripts/controller_cli.py validate-token --token your-sso-token

# Initialize the PostgreSQL database
python3 ./scripts/controller_cli.py init-db

# Database health check / status
python3 ./scripts/controller_cli.py db-health
python3 ./scripts/controller_cli.py db-status --show-env

# Inspect the database
python3 ./scripts/controller_cli.py list-tables
python3 ./scripts/controller_cli.py describe-table user_applications
python3 ./scripts/controller_cli.py query-table applications --limit 10

# Mount S3 storage for backups
python3 ./scripts/controller_cli.py mount-s3fs softfluid /mnt/s3

# Nginx and platform/replication operations
python3 ./scripts/controller_cli.py update-nginx-locations
python3 ./scripts/controller_cli.py platform-status
python3 ./scripts/controller_cli.py replication-sync-status

# Install the control plane as a systemd service
python3 ./scripts/controller_cli.py install-as-systemctl-service
```

#### Onboarding: sandbox and deploy-template commands

```bash
# Demo sandbox lifecycle (Demo_User + seeded sample applications)
python3 ./scripts/controller_cli.py sandbox provision
python3 ./scripts/controller_cli.py sandbox reset
python3 ./scripts/controller_cli.py sandbox teardown

# Deploy templates
python3 ./scripts/controller_cli.py templates list
python3 ./scripts/controller_cli.py templates deploy fastapi-starter my-api
```

### MCP Protocol
```bash
# Start MCP server for agent communication
python3 ./scripts/mcp_server.py
```

## Service Management

### Service Status
```bash
# Check all services status
./deployControlPlan.sh ps

# View service logs
./deployControlPlan.sh logs

# Restart services
./deployControlPlan.sh restart

# Stop services
./deployControlPlan.sh stop
```

### Enhanced Health Checks
```bash
# API health check
curl https://www.swautomorph.com/api/auth/status

# Database health check with statistics (admin required)
curl https://www.swautomorph.com/api/health/database

# Check Docker services
docker-compose ps

# Check deployment logs with streaming
curl https://www.swautomorph.com/api/deployments/1/logs
```

### Database Management
```bash
# Create manual backup
./deployControlPlan.sh backup_db

# Recover from backup
./deployControlPlan.sh --recover_db

# Database health check
python3 ./scripts/controller_cli.py db-health
```

## Default Configuration

- **Web Interface**: https://www.swautomorph.com (or https://localhost)
- **API Endpoint**: https://www.swautomorph.com/api
- **Gitea Server**: https://www.swautomorph.com/gitea (port 3000)
- **MCP Server**: Available via scripts/mcp_server.py
- **Database**: **PostgreSQL with connection pooling** (enterprise-grade performance and scalability)
- **Deployment Directory**: /home/<LINUX_USER_INSTALLATION>/deployments/[username]/[appname] (user from conf/deploy.ini)
- **SSL Certificates**: ssl/ directory
- **Logs**: logs/ directory with daily rotation and Gunicorn logging
- **Backups**: softfluid/db/backup/ with S3 sync and hourly automated backups
- **Virtual Agents**: AI Chat Developer and Operations with context-aware prompts

## Architecture

### Directory Structure
```
<PLTF_FOLDER>/                    # Folder name from conf/deploy.ini
├── src/                    # Main application source
│   ├── routes/            # Flask route blueprints
│   │   ├── main_routes.py        # Dashboard & documentation
│   │   ├── auth_routes.py        # User authentication
│   │   ├── sso_routes.py         # Single Sign-On
│   │   ├── api_routes.py         # REST API with streaming
│   │   ├── genai_routes.py       # Virtual AI agents
│   │   ├── billing_routes.py     # Billing & cost tracking
│   │   ├── orchestrator_routes.py # App lifecycle orchestration
│   │   ├── replication_routes.py # Multi-server replication
│   │   ├── security_routes.py   # Password reset & 2FA
│   │   ├── serverless_routes.py  # Serverless Docker execution
│   │   ├── gpu_routes.py         # MIG shared GPU management
│   │   ├── templates_routes.py   # Deploy Templates REST API
│   │   ├── wizard_routes.py      # Onboarding setup wizard API
│   │   └── sandbox_routes.py     # Sandbox demo provision/reset/teardown
│   ├── serverless/        # Serverless execution engine (worker, container runtime, log cleanup)
│   ├── wizard/            # Onboarding setup wizard (setup_wizard.py, ssl_configurator.py)
│   ├── ControlPlanFlaskApp_postgres.py    # Main Flask application factory
│   ├── database_postgres.py      # PostgreSQL database manager with connection pooling
│   ├── query_converter.py        # SQL dialect conversion helper
│   ├── db_sync.py                # Database sync helpers for replication
│   ├── db_health.py              # Database health & statistics
│   ├── nginx_manager.py          # Dynamic nginx location management
│   ├── orchestrator.py           # Application orchestration & reconciliation
│   ├── replication_manager.py    # Peer-to-peer database replication
│   ├── platform_discovery.py     # Platform capability discovery
│   ├── template_catalog.py       # Deploy Templates catalog (single source of truth)
│   ├── template_deploy.py        # Surface-agnostic template deploy service
│   ├── sandbox_manager.py        # Sandbox demo provision/reset/teardown
│   ├── configuration_writer.py   # Safe writer for conf/deploy.ini (onboarding wizard)
│   ├── email_service.py          # Email delivery (password reset, 2FA)
│   ├── create_gitea_repo.py      # Gitea repository provisioning
│   ├── gitea_config.py           # Gitea configuration helpers
│   ├── config_postgres.py        # Configuration & multi-language
│   └── auth.py                   # Authentication utilities
├── migration/             # Database migration scripts (SQLite→PostgreSQL + schema evolution)
│   ├── add_serverless_jobs.sql                      # Serverless jobs schema
│   ├── add_target_link_to_serverless_jobs.sql       # Serverless job target link
│   ├── add_mig_gpu.sql                              # MIG GPU tables & server flag
│   ├── add_password_reset_and_2fa.sql               # Security features schema
│   ├── add_deploy_templates.sql                     # Deploy templates catalog & sandbox labeling
│   ├── add_extended_ports_to_user_applications.sql  # 12-port allocation per app
│   ├── add_backups_history_to_deployments.sql       # Backup history tracking
│   ├── add_url_to_applications.sql                  # Application URL column
│   └── ...                                          # Other migrations & fixups
├── scripts/               # CLI tools, utilities, and Python tests
│   ├── controller_cli.py         # Command-line interface (click)
│   ├── orchestrator_cli.py       # Orchestrator CLI
│   ├── mcp_server.py             # Model Context Protocol server
│   ├── sync_nginx_locations.py   # Sync nginx locations from database
│   ├── mount_s3fs.py             # Mount S3 storage for backups
│   ├── controlplan_service.py    # systemd service wrapper
│   ├── generate_ssl.sh           # Self-signed SSL certificate generator
│   ├── setup_letsencrypt.sh      # Let's Encrypt certificate setup
│   ├── install_worker_service.sh # Install the serverless worker service
│   ├── postgresql_schema.sql     # PostgreSQL schema definition
│   └── test_*.py                 # pytest suites (platform, orchestrator, nginx, backups)
├── tests/                 # Additional test suites
│   ├── bash/             # Shell tests for init_pltf.sh (ownership, preservation, path)
│   └── js/               # Dashboard JavaScript tests (sorting, highlight, headers)
├── templates/            # HTML templates with EN/FR support
│   ├── shared_gpu.html           # MIG GPU management page
│   ├── dashboard.html            # Main dashboard
│   └── ...                       # Other templates
├── static/               # CSS, JS, and static files
├── ssl/                  # SSL certificates
├── logs/                 # Application logs with Gunicorn support
├── shared/               # Context files for virtual agents
├── docs/                  # Comprehensive documentation
│   ├── USER_GUIDE.md             # AI agent usage guide
│   ├── ARCHITECTURE_GUIDE.md     # System architecture
│   ├── DEPLOYMENT_GUIDE.md       # Deployment procedures
│   ├── INIT_PLATFORM.md          # Platform initialization guide
│   ├── SERVERLESS.md             # Serverless Docker execution guide
│   ├── SHARE_GPU_DOCKER.md       # MIG shared GPU guide
│   ├── PLATFORM_OVERVIEW.md      # Platform overview
│   ├── LIST_OF_APP_AVAILABLE.md  # Deploy template catalog reference
│   └── technicals/               # Technical deep-dive documents
├── conf/                 # Configuration files (deploy.ini.template, serverless.ini, default_apps)
├── systemd/              # systemd unit files (serverless worker, control plane)
├── wsgi.py               # WSGI production entry point (gunicorn)
├── gunicorn.conf.py      # Gunicorn configuration
├── docker-compose.yml    # Docker Compose stack
├── Dockerfile            # Application image
├── Dockerfile.postgres   # PostgreSQL image
├── requirements.txt      # Python dependencies
├── setup_postgresql.sh   # PostgreSQL setup helper
├── setup_modsecurity_config.sh # ModSecurity WAF configuration
├── init_pltf.sh          # Platform initialization (Docker, NVIDIA drivers, MIG, Kata runtime)
└── deployControlPlan.sh  # Main deployment script
```

### Key Components

- **Flask Application**: Multi-blueprint architecture with modular routes and virtual AI agents
- **Database**: **PostgreSQL with connection pooling** for enterprise-grade performance and thread-safe operations
- **Authentication**: Session-based with SSO token support, password reset, and two-factor authentication
- **Deployment**: Multi-server support with capacity management, automatic allocation, and streaming APIs
- **App Orchestrator**: Automated application lifecycle management with reconciliation loop
- **Serverless Execution**: Docker-based job submission and execution engine with worker processes
- **Deploy Templates**: Validated blueprint catalog (`deploy_templates` table) with a surface-agnostic deploy service shared by Dashboard, CLI, MCP, and REST
- **Onboarding Wizard**: First-run setup that persists `conf/deploy.ini` atomically with a timestamped backup and hashes the admin password into the database
- **Container Runtime**: Configurable runtime type — standard containers (runc) or MicroVM isolation (Kata Containers) for stronger workload boundaries
- **MIG Shared GPU**: NVIDIA Multi-Instance GPU partitioning via SSH with per-server configuration and web UI
- **Replication**: Peer-to-peer database replication across multiple servers with sync tokens
- **Nginx Proxy**: Dynamic location blocks for user applications with automatic configuration
- **Security**: ModSecurity WAF with OWASP CRS rules, password reset, and 2FA via email
- **Monitoring**: Health checks, database statistics, real-time streaming logs, and performance metrics
- **Virtual AI Agents**: AI Chat Developer and Operations assistants with context-aware prompts
- **Billing System**: Comprehensive cost tracking with activity logging, usage monitoring, and automated invoicing
- **Multi-language**: English/French support with session-based language switching and bilingual documentation
- **Backup System**: Automated hourly backups with S3 sync and interactive recovery tools
- **Platform Init**: Automated server provisioning including Docker, NVIDIA drivers, and MIG mode setup

## Troubleshooting

### Common Issues
```bash
# Check service status
./deployControlPlan.sh ps

# View detailed logs
./deployControlPlan.sh logs

# Port conflicts
sudo netstat -tulpn | grep -E ':(80|443|3000|5000)'

# Permission issues (replace <user> with LINUX_USER_INSTALLATION from conf/deploy.ini)
sudo chown -R <user>:<user> /home/<user>/deployments/
sudo chown -R <user>:<user> /home/<user>/<PLTF_FOLDER>/

# Database issues
python3 ./scripts/controller_cli.py db-health
./deployControlPlan.sh --recover_db

# SSL certificate issues
./scripts/generate_ssl.sh
./scripts/fix_ssl_chain.sh
```

### Reset Installation
```bash
# Stop all services
./deployControlPlan.sh stop

# Complete reset (Docker)
docker-compose down -v
docker system prune -f

# Complete reset (Local)
sudo systemctl stop nginx gitea
sudo rm -rf /etc/nginx/sites-enabled/<PLTF_FOLDER>
# Drop the PostgreSQL database (prompts for confirmation)
python3 ./scripts/controller_cli.py delete-db

# Restart deployment
./deployControlPlan.sh start
```

### Debug Mode
```bash
# Enable debug logging
export FLASK_DEBUG=1
export FLASK_ENV=development

# Run with verbose output
./deployControlPlan.sh start locally 2>&1 | tee deployment.log
```