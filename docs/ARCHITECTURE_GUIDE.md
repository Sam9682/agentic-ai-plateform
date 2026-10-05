# 🏗️ AI-SwAutoMorph Architecture Design / Guide d'Architecture AI-SwAutoMorph

## English

<div class="center">
🚀 **Centralized Application Deployment Platform for GenAI Agents** 🤖
</div>

### 🌟 Overview

AI-SwAutoMorph is a **centralized application deployment and management platform** designed for GenAI agents. It provides automated deployment, lifecycle management, and SSO authentication for web applications through multiple interfaces (Web, CLI, API, MCP). The platform enables GenAI agents to autonomously deploy, manage, and access web applications without human intervention.

**Core Architecture**: Modular Flask application with thread-safe database operations, virtual AI agents, multi-server support, comprehensive billing system, and enhanced security features.

### 🏗️ Core Architecture

#### 1. 📦 Enhanced Modular Flask Application

```
🏠 <PLTF_FOLDER>/
├── 📁 src/                          # Core application modules
│   ├── ⚙️ config_postgres.py        # Configuration & multi-language support
│   ├── 🗄️ database_postgres.py       # PostgreSQL database manager with connection pooling
│   ├── 🗄️ database.py               # Legacy SQLite database manager (migration compatibility)
│   ├── 🔐 auth.py                   # Authentication & SSO management
│   ├── 🌐 ControlPlanFlaskApp_postgres.py    # Flask application factory
│   ├── 🎭 orchestrator.py           # Application lifecycle orchestration
│   ├── 🔄 replication_manager.py    # Peer-to-peer database replication
│   ├── 🌐 platform_discovery.py     # Platform capability discovery
│   ├── 📁 serverless/              # Serverless execution engine
│   │   ├── config.py               # Serverless configuration
│   │   └── worker.py               # Job worker process
│   └── 📁 routes/                   # Route handlers (blueprints)
│       ├── 🏠 main_routes.py        # Dashboard & documentation viewer
│       ├── 👤 auth_routes.py        # User authentication
│       ├── 🔑 sso_routes.py         # Single Sign-On functionality
│       ├── 🔌 api_routes.py         # REST API with streaming support
│       ├── 🤖 genai_routes.py       # Virtual AI agents with streaming
│       ├── 💰 billing_routes.py     # Billing and cost management
│       ├── 🎭 orchestrator_routes.py # Application lifecycle orchestration
│       ├── 🔄 replication_routes.py # Multi-server replication sync
│       ├── 🔒 security_routes.py   # Password reset & 2FA
│       ├── ⚡ serverless_routes.py  # Serverless Docker job execution
│       ├── 🎮 gpu_routes.py         # MIG shared GPU management
       ├── 🧩 templates_routes.py   # Deploy Templates REST API
       ├── 🧙 wizard_routes.py      # Onboarding setup wizard API
       └── 🧪 sandbox_routes.py     # Sandbox demo provision/reset/teardown

├── 📁 templates/                    # HTML templates with EN/FR support
│   ├── 🎨 base.html                 # Base template with navbar language switching
│   ├── 📊 dashboard.html            # Main dashboard with unified virtual agents
│   ├── 🚪 login.html                # Login page emphasizing AI agents
│   └── 📖 doc_viewer.html           # Markdown documentation viewer
├── 📁 static/                       # CSS, JS, and static files
├── 📁 docs/                         # Documentation with bilingual support
│   ├── 🏗️ ARCHITECTURE_GUIDE.md     # This file
│   ├── 🚀 DEPLOYMENT_GUIDE.md       # Deployment procedures
│   ├── 🗄️ DATABASE_IMPROVEMENTS.md  # Database architecture
│   └── 👥 USER_GUIDE.md             # AI agent usage guide
├── 📁 scripts/                      # CLI tools and utilities
│   ├── 💻 controller_cli.py                    # Command-line interface
│   └── 🔌 mcp_server.py             # Model Context Protocol server
├── 📁 migration/                    # Database migration scripts
│   ├── add_serverless_jobs.sql      # Serverless job queue schema
│   ├── add_mig_gpu.sql             # MIG GPU tables
│   └── add_password_reset_and_2fa.sql # Security features
├── 📁 tests/                        # Automated test suite (pytest)
├── 📁 shared/                       # Context files for virtual agents
│   ├── 📝 MODIFY_CODE_context.md    # Developer agent context
│   ├── ▶️ START_context.md          # Start operation context
│   ├── ⏹️ STOP_context.md           # Stop operation context
│   ├── 🔄 RESTART_context.md        # Restart operation context
│   ├── 🔍 PS_context.md             # Process status context
│   └── 📄 LOGS_context.md           # Log analysis context
├── 🖥️ init_pltf.sh                  # Platform initialization (Docker, NVIDIA, MIG)
└── 🚀 deployControlPlan.sh          # Main deployment control script
```

**Application Initialization & Graceful Degradation:**

The Flask application implements graceful degradation for optional components during initialization:

```python
# Initialize database and orchestrator
with app.app_context():
    init_db()  # Core database - required
    
    try:
        # Optional: Orchestrator for container management
        from .orchestrator import orchestrator
        orchestrator.init_orchestrator_tables()
        orchestrator.start_reconciliation_loop()
    except Exception as e:
        print(f"[ERROR] Orchestrator initialization failed: {e}")
        # Continue without orchestrator if it fails
    
    try:
        # Optional: Replication for multi-server sync
        from .replication_manager import ReplicationManager
        replication_manager = ReplicationManager(db_manager, sync_secret)
        replication_manager.start_worker()
    except Exception as e:
        print(f"[ERROR] Replication initialization failed: {e}")
        # Continue in single-server mode
```

**Graceful Degradation Behavior:**

| Component | On Success | On Failure | Impact |
|-----------|------------|------------|--------|
| **Database** | Full functionality | Application fails to start | Critical - required |
| **Orchestrator** | Container orchestration enabled | Continues without orchestration | Core features remain operational |
| **Replication** | Multi-server sync enabled | Single-server mode | Platform works normally on one server |

**Recovery Options:**
- Orchestrator: Can be manually initialized via API or CLI without restart
- Replication: Can be enabled later via configuration update and restart
- Both: Check logs for specific error messages and resolve underlying issues

This design ensures **high availability** of critical platform features (user management, deployments, billing, authentication) even if optional components encounter initialization issues.

#### 2. 🤖 Enhanced Virtual AI Agents Integration

The platform provides **two specialized AI agents** with advanced features:

**🔧 AI Chat Developer Agent** (`/api/request_dev_ai_for_app`):
- 💻 Code modification and feature development
- 🗣️ Natural language to code translation
- 🌿 Git branch management with format `{user_id}-automorph-{app_name}-{timestamp}`
- 🧪 Automatic testing and deployment
- 🎯 Context-aware prompts from shared/MODIFY_CODE_context.md
- ⚡ Streaming responses with Server-Sent Events
- ⏱️ Timeout management (30 minutes) with graceful cleanup
- 📝 Prompt logging to dev_prompt_generated.txt
- 🔒 Security: Path traversal protection and input validation

**🚀 AI Chat Operations Agent** (`/api/request_ops_ai_for_app`):
- ⚡ Deployment operations (START, STOP, RESTART, PS, LOGS)
- 🏗️ Infrastructure management with multi-server support
- 📊 Application monitoring and troubleshooting
- 📈 Server capacity management and automatic allocation
- 🎯 Context-aware prompts for each operation type (START_context.md, STOP_context.md, etc.)
- 💰 Automatic billing activity recording for START/STOP actions
- 🔄 Fallback Q&A mode for invalid actions
- 📝 Prompt logging to ope_prompts_generated.log
- ⏱️ 30-minute timeout with process group termination

#### 3. 🌍 Enhanced Multi-Language Support

- **🔄 Navbar Language Switching**: FR/EN toggle in navigation bar with session persistence
- **💾 Session-Based Language**: Language preference stored in Flask session
- **🎨 Template Integration**: All templates support `get_text()` function with 200+ translations
- **📖 Documentation Viewer**: Markdown files with bilingual sections and dynamic switching
- **⚡ Dynamic Content**: JavaScript-based language switching for documentation
- **📱 Mobile Support**: Responsive design with hamburger menu

#### 4. 🗄️ Enhanced Database Schema

```sql
-- 🏢 Core entities with comprehensive billing and multi-server support
👥 Users: id, username, email, password_hash, first_name, last_name, suspended, created_at
📱 Applications: id, name, description, git_url, git_repo_size, docker_*_duration, created_at
🔗 User_Applications: id, user_id, application_id, url, http_port, https_port, http_port2, https_port2, http_port3, https_port3, http_port4, https_port4, http_port5, https_port5, http_port6, https_port6, others_port, created_at
🚀 Deployments: id, user_id, application_name, status, deployment_path, git_url, server_id, created_at, updated_at
🖥️ Servers: id, SERVER_IP, SERVER_NAME, SERVER_CAPACITY_USER_MAX, SERVER_CAPACITY_APPLI_MAX, SERVER_STATUS, SERVER_TYPE, shared_gpu_enabled, created_at
🔑 Auth_Tokens: id, user_id, token_hash, expires_at, created_at
💰 Application_Costs: id, application_id, cost_per_day, created_at, updated_at
📊 Billing_Activities: id, user_id, application_id, action, started_at, stopped_at, duration_seconds, cost_amount, created_at
📝 Users_Logs: id, user_id, username, action, datetime
💳 Payment_Modes: id, user_id, payment_type, bank_account, paypal_email, card_last_four, card_type, is_default, created_at
🧾 Invoicing: id, user_id, invoice_month, total_amount, status, payment_date, payment_mode_id, created_at
🎮 MIG_Profiles: id, server_id, profile_name, profile_id, gpu_memory_gb, created_at
🖥️ MIG_Instances: id, server_id, instance_uuid, profile_name, gpu_memory_mb, created_at
⚡ Serverless_Jobs: id, user_id, image, command, env, timeout, status, worker_id, stdout, stderr, exit_code, created_at, started_at, completed_at
🔒 Password_Reset_Tokens: id, user_id, token_hash, expires_at, created_at
```

**Enhanced Database Features**:
- 🐘 **PostgreSQL Database**: Migrated from SQLite to PostgreSQL for enterprise-grade performance
- 🏊 **Connection Pooling**: ThreadedConnectionPool with configurable min/max connections (2-20)
- 🔄 **ACID Transactions**: Full ACID compliance with proper transaction management
- 📊 **Advanced Data Types**: INET for IP addresses, BIGSERIAL for auto-increment, TIMESTAMP WITH TIME ZONE
- 🔍 **Optimized Indexes**: Performance-tuned indexes on frequently queried columns
- 🔒 **Enhanced Security**: Parameterized queries preventing SQL injection, SSL support
- ⚡ **Automatic Retry**: Exponential backoff for transient connection errors
- 📈 **Scalability**: Support for concurrent connections and high-throughput operations
- 🛠️ **Database Triggers**: Automatic updated_at timestamp management
- 🔧 **Migration Tools**: Automated SQLite to PostgreSQL migration script

#### 5. 🧭 Enhanced Navigation Architecture

**📋 Navbar Organization**:
- 📱 Applications and 💰 Billing tabs in main navigation
- ⚙️ Configuration dropdown (👥 Users, 🖥️ Servers, 🗄️ Database) for admin
- ❓ Help dropdown with direct links to documentation
- 🌍 Language toggle (FR/EN) with session persistence
- 📱 Mobile-responsive navigation with hamburger menu

**🎯 Dashboard Enhancements**:
- ↗️ Moved from content-area tabs to navbar navigation
- 📦 Consolidated menus in dropdown format
- 🔗 Direct access to markdown documentation
- ✨ Streamlined user experience with unified virtual agents interface
- 📊 Real-time application status updates
- 📈 Streaming logs with Server-Sent Events

#### 6. 💰 Comprehensive Billing System

**📊 Billing Features**:
- ⏱️ Automatic activity recording for START/STOP actions
- 💳 Prorated cost calculation based on actual usage time
- 📅 Period filtering (day, week, month, previous month)
- 👥 User filtering for admin users
- 🧾 Automated invoice generation with PDF export
- 💰 Multiple payment modes (bank transfer, PayPal, credit cards)
- 📊 Revenue tracking and cost summaries
- 📈 Detailed activity logging with billing_activities.log

#### 7. 🛡️ Enhanced Security Features

**🔒 Security Enhancements**:
- 🛡️ ModSecurity WAF protection with OWASP CRS rules
- 🔍 Input validation and SQL injection prevention
- 📁 Path traversal protection for file operations
- 🔐 Session-based authentication with secure cookies
- 🎫 SSO token support with expiration management
- 👥 User isolation with separate deployment directories
- 📝 Comprehensive logging for security monitoring
- ⏱️ Process timeout management with graceful cleanup

#### 8. 🎮 MIG Shared GPU Management

**GPU Features**:
- 🖥️ **NVIDIA MIG Partitioning**: Split a single GPU into up to 7 isolated instances
- 🔧 **Per-Server Configuration**: Enable/disable shared GPU per server via web UI or API
- 📡 **SSH-based Management**: Remote GPU commands via subprocess SSH execution
- 🐳 **Docker GPU Access**: Each MIG instance accessible via `--gpus` flag in containers
- 🔒 **Admin-Only Access**: All GPU endpoints enforce admin authentication
- 📊 **Instance Tracking**: Database persistence of MIG profiles and active instances

**API Endpoints** (`/api/servers/<server_id>/gpu`):
- `PUT /enabled` — Toggle shared GPU (enables MIG mode via SSH on activation)
- `GET /profiles` — List available MIG partition profiles from GPU hardware
- `GET /instances` — List active MIG instances from database
- `POST /instances` — Create MIG instances from profile IDs (1-7)
- `DELETE /instances` — Destroy all MIG instances on server

#### 9. ⚡ Serverless Docker Execution

**Serverless Features**:
- 🐳 **On-Demand Containers**: Submit Docker jobs without managing infrastructure
- 🔒 **Security Hardening**: Read-only filesystem, no network, dropped capabilities
- ⏱️ **Timeout Enforcement**: Configurable per-job timeouts with graceful termination
- 📊 **Job Queue**: PostgreSQL-backed with `FOR UPDATE SKIP LOCKED` for concurrent workers
- 📈 **Horizontal Scaling**: Multiple workers can run concurrently
- 🧹 **Automatic Cleanup**: Old logs and jobs cleaned up based on retention policy

**API Endpoints** (`/api/jobs`):
- `POST /jobs` — Submit a new Docker job
- `GET /jobs` — List user jobs with pagination and filtering
- `GET /jobs/<id>` — Get job status and metadata
- `GET /jobs/<id>/result` — Get stdout/stderr and exit code
- `POST /jobs/<id>/cancel` — Cancel pending or running job
- `GET /jobs/metrics` — Aggregated job statistics (admin)


#### 10. 🛡️ Container Runtime Isolation

The platform supports two container runtimes, selectable per-platform from the admin Settings page and stored in the database `configuration` table:

- `runc` (default) — standard OCI runtime sharing the host kernel; no `--runtime` flag is emitted.
- `kata` (optional) — Kata Containers; each container runs in a dedicated MicroVM with its own kernel for hardware-level isolation.

When `kata` is selected the platform adds `--runtime kata` across orchestrator replica services, serverless jobs (worker reads the value once at startup; restart required), and git-based app deployments (passed to `deployApp.sh` as a trailing argument and the `RUNTIME_TYPE` env var). The value is validated against an allow-list (`runc`, `kata`) and falls back to `runc`.

#### 11. 🧩 Deploy Templates, 🧙 Onboarding Wizard, 🧪 Sandbox

- Deploy Templates: a validated blueprint catalog (`deploy_templates` table, `template_catalog.py`) with a surface-agnostic deploy service (`template_deploy.py`) shared by Dashboard, CLI, MCP and REST (`templates_routes.py`).
- Onboarding Wizard: first-run setup (`wizard_routes.py`, `configuration_writer.py`) that writes `conf/deploy.ini` atomically with a timestamped backup and hashes the admin password.
- Sandbox demo account: labeled demo user and sandbox deployments (`sandbox_routes.py`) for trying the platform without affecting real data.
- Configurable install layout: install folder, Linux user and paths are driven by `conf/deploy.ini` (`PLTF_FOLDER`, `LINUX_USER_INSTALLATION`) rather than a hardcoded path.


---

## Français

<div class="center">
🚀 **Plateforme Centralisée de Déploiement d'Applications pour Agents GenAI** 🤖
</div>

### 🌟 Aperçu

AI-SwAutoMorph est une **plateforme centralisée de déploiement et de gestion d'applications** conçue pour les agents GenAI. Elle fournit un déploiement automatisé, une gestion du cycle de vie et une authentification SSO pour les applications web à travers plusieurs interfaces (Web, CLI, API, MCP). La plateforme permet aux agents GenAI de déployer, gérer et accéder de manière autonome aux applications web sans intervention humaine.

**Architecture Principale**: Application Flask modulaire avec opérations de base de données thread-safe, agents IA virtuels, support multi-serveurs, système de facturation complet et fonctionnalités de sécurité avancées.

### 🏗️ Architecture Principale

#### 1. 📦 Application Flask Modulaire Améliorée

```
🏠 <PLTF_FOLDER>/
├── 📁 src/                          # Modules d'application principaux
│   ├── ⚙️ config_postgres.py        # Configuration et support multi-langues
│   ├── 🗄️ database_postgres.py       # Gestionnaire de base de données PostgreSQL avec pooling
│   ├── 🗄️ database.py               # Gestionnaire de base de données SQLite (compatibilité migration)
│   ├── 🔐 auth.py                   # Authentification et gestion SSO
│   ├── 🌐 ControlPlanFlaskApp_postgres.py    # Factory d'application Flask
│   ├── 🎭 orchestrator.py           # Application lifecycle orchestration
│   ├── 🔄 replication_manager.py    # Peer-to-peer database replication
│   ├── 🌐 platform_discovery.py     # Platform capability discovery
│   ├── 📁 serverless/              # Serverless execution engine
│   │   ├── config.py               # Serverless configuration
│   │   └── worker.py               # Job worker process
│   └── 📁 routes/                   # Gestionnaires de routes (blueprints)
│       ├── 🏠 main_routes.py        # Tableau de bord et visualiseur de documentation
│       ├── 👤 auth_routes.py        # Authentification utilisateur
│       ├── 🔑 sso_routes.py         # Fonctionnalité Single Sign-On
│       ├── 🔌 api_routes.py         # API REST avec support streaming
│       ├── 🤖 genai_routes.py       # Agents IA virtuels avec streaming
│       ├── 💰 billing_routes.py     # Facturation et gestion des coûts
│       ├── 🎭 orchestrator_routes.py # Application lifecycle orchestration
│       ├── 🔄 replication_routes.py # Multi-server replication sync
│       ├── 🔒 security_routes.py   # Password reset & 2FA
│       ├── ⚡ serverless_routes.py  # Serverless Docker job execution
│       ├── 🎮 gpu_routes.py         # MIG shared GPU management
       ├── 🧩 templates_routes.py   # Deploy Templates REST API
       ├── 🧙 wizard_routes.py      # Onboarding setup wizard API
       └── 🧪 sandbox_routes.py     # Sandbox demo provision/reset/teardown

├── 📁 templates/                    # Modèles HTML avec support EN/FR
│   ├── 🎨 base.html                 # Modèle de base avec changement de langue navbar
│   ├── 📊 dashboard.html            # Tableau de bord principal avec agents virtuels unifiés
│   ├── 🚪 login.html                # Page de connexion mettant l'accent sur les agents IA
│   └── 📖 doc_viewer.html           # Visualiseur de documentation Markdown
├── 📁 static/                       # Fichiers CSS, JS et statiques
├── 📁 docs/                         # Documentation avec support bilingue
│   ├── 🏗️ ARCHITECTURE_GUIDE.md     # Ce fichier
│   ├── 🚀 DEPLOYMENT_GUIDE.md       # Procédures de déploiement
│   ├── 🗄️ DATABASE_IMPROVEMENTS.md  # Architecture de base de données
│   └── 👥 USER_GUIDE.md             # Guide d'utilisation des agents IA
├── 📁 scripts/                      # Outils CLI et utilitaires
│   ├── 💻 controller_cli.py                    # Interface en ligne de commande
│   └── 🔌 mcp_server.py             # Serveur Model Context Protocol
├── 📁 migration/                    # Database migration scripts
│   ├── add_serverless_jobs.sql      # Serverless job queue schema
│   ├── add_mig_gpu.sql             # MIG GPU tables
│   └── add_password_reset_and_2fa.sql # Security features
├── 📁 tests/                        # Automated test suite (pytest)
├── 📁 shared/                       # Fichiers de contexte pour agents virtuels
│   ├── 📝 MODIFY_CODE_context.md    # Contexte agent développeur
│   ├── ▶️ START_context.md          # Contexte opération start
│   ├── ⏹️ STOP_context.md           # Contexte opération stop
│   ├── 🔄 RESTART_context.md        # Contexte opération restart
│   ├── 🔍 PS_context.md             # Contexte statut processus
│   └── 📄 LOGS_context.md           # Contexte analyse logs
├── 🖥️ init_pltf.sh                  # Platform initialization (Docker, NVIDIA, MIG)
└── 🚀 deployControlPlan.sh          # Script principal de contrôle de déploiement
```

#### 2. 🤖 Intégration des Agents IA Virtuels Avancés

La plateforme fournit **deux agents IA spécialisés** avec fonctionnalités avancées :

**🔧 Agent Développeur AI Chat** (`/api/request_dev_ai_for_app`):
- 💻 Modification de code et développement de fonctionnalités
- 🗣️ Traduction langage naturel vers code
- 🌿 Gestion des branches Git avec format `{user_id}-automorph-{app_name}-{timestamp}`
- 🧪 Tests et déploiement automatiques
- 🎯 Prompts contextuels depuis shared/MODIFY_CODE_context.md
- ⚡ Réponses en streaming avec Server-Sent Events
- ⏱️ Gestion des timeouts (30 minutes) avec nettoyage gracieux
- 📝 Journalisation des prompts vers dev_prompt_generated.txt
- 🔒 Sécurité: Protection contre la traversée de chemin et validation d'entrée

**🚀 Agent Opérations AI Chat** (`/api/request_ops_ai_for_app`):
- ⚡ Opérations de déploiement (START, STOP, RESTART, PS, LOGS)
- 🏗️ Gestion d'infrastructure avec support multi-serveurs
- 📊 Surveillance et dépannage d'applications
- 📈 Gestion de capacité serveur et allocation automatique
- 🎯 Prompts contextuels pour chaque type d'opération (START_context.md, STOP_context.md, etc.)
- 💰 Enregistrement automatique d'activité de facturation pour actions START/STOP
- 🔄 Mode Q&A de fallback pour actions invalides
- 📝 Journalisation des prompts vers ope_prompts_generated.log
- ⏱️ Timeout de 30 minutes avec terminaison de groupe de processus

#### 3. 🌍 Support Multi-Langues Amélioré

- **🔄 Changement de Langue Navbar**: Basculement FR/EN dans la barre de navigation avec persistance de session
- **💾 Langue Basée sur Session**: Préférence de langue stockée dans la session Flask
- **🎨 Intégration Template**: Tous les templates supportent la fonction `get_text()` avec 200+ traductions
- **📖 Visualiseur de Documentation**: Fichiers Markdown avec sections bilingues et changement dynamique
- **⚡ Contenu Dynamique**: Changement de langue basé JavaScript pour la documentation
- **📱 Support Mobile**: Design responsive avec menu hamburger

#### 4. 🗄️ Schéma de Base de Données Amélioré

```sql
-- 🏢 Entités principales avec facturation complète et support multi-serveurs
👥 Users: id, username, email, password_hash, first_name, last_name, suspended, created_at
📱 Applications: id, name, description, git_url, git_repo_size, docker_*_duration, created_at
🔗 User_Applications: id, user_id, application_id, url, http_port, https_port, http_port2, https_port2, http_port3, https_port3, http_port4, https_port4, http_port5, https_port5, http_port6, https_port6, others_port, created_at
🚀 Deployments: id, user_id, application_name, status, deployment_path, git_url, server_id, created_at, updated_at
🖥️ Servers: id, SERVER_IP, SERVER_NAME, SERVER_CAPACITY_USER_MAX, SERVER_CAPACITY_APPLI_MAX, SERVER_STATUS, SERVER_TYPE, shared_gpu_enabled, created_at
🔑 Auth_Tokens: id, user_id, token_hash, expires_at, created_at
💰 Application_Costs: id, application_id, cost_per_day, created_at, updated_at
📊 Billing_Activities: id, user_id, application_id, action, started_at, stopped_at, duration_seconds, cost_amount, created_at
📝 Users_Logs: id, user_id, username, action, datetime
💳 Payment_Modes: id, user_id, payment_type, bank_account, paypal_email, card_last_four, card_type, is_default, created_at
🧾 Invoicing: id, user_id, invoice_month, total_amount, status, payment_date, payment_mode_id, created_at
🎮 MIG_Profiles: id, server_id, profile_name, profile_id, gpu_memory_gb, created_at
🖥️ MIG_Instances: id, server_id, instance_uuid, profile_name, gpu_memory_mb, created_at
⚡ Serverless_Jobs: id, user_id, image, command, env, timeout, status, worker_id, stdout, stderr, exit_code, created_at, started_at, completed_at
🔒 Password_Reset_Tokens: id, user_id, token_hash, expires_at, created_at
```

**Fonctionnalités de Base de Données Améliorées**:
- 🐘 **Base de Données PostgreSQL**: Migration de SQLite vers PostgreSQL pour performance de niveau entreprise
- 🏊 **Mise en Pool de Connexions**: ThreadedConnectionPool avec connexions min/max configurables (2-20)
- 🔄 **Transactions ACID**: Conformité ACID complète avec gestion de transaction appropriée
- 📊 **Types de Données Avancés**: INET pour adresses IP, BIGSERIAL pour auto-incrément, TIMESTAMP WITH TIME ZONE
- 🔍 **Index Optimisés**: Index optimisés pour performance sur colonnes fréquemment interrogées
- 🔒 **Sécurité Améliorée**: Requêtes paramétrées prévenant l'injection SQL, support SSL
- ⚡ **Retry Automatique**: Backoff exponentiel pour erreurs de connexion transitoires
- 📈 **Évolutivité**: Support pour connexions concurrentes et opérations haut débit
- 🛠️ **Triggers de Base de Données**: Gestion automatique des timestamps updated_at
- 🔧 **Outils de Migration**: Script de migration automatisé SQLite vers PostgreSQL

#### 5. 🧭 Architecture de Navigation Améliorée

**📋 Organisation Navbar**:
- 📱 Onglets Applications et 💰 Facturation dans la navigation principale
- ⚙️ Menu déroulant Configuration (👥 Utilisateurs, 🖥️ Serveurs, 🗄️ Base de données) pour admin
- ❓ Menu déroulant Aide avec liens directs vers la documentation
- 🌍 Basculement de langue (FR/EN) avec persistance de session
- 📱 Navigation responsive mobile avec menu hamburger

**🎯 Améliorations du Tableau de Bord**:
- ↗️ Déplacé des onglets de zone de contenu vers la navigation navbar
- 📦 Menus consolidés en format déroulant
- 🔗 Accès direct à la documentation markdown
- ✨ Expérience utilisateur rationalisée avec interface agents virtuels unifiée
- 📊 Mises à jour de statut d'application en temps réel
- 📈 Journaux en streaming avec Server-Sent Events

#### 6. 💰 Système de Facturation Complet

**📊 Fonctionnalités de Facturation**:
- ⏱️ Enregistrement automatique d'activité pour actions START/STOP
- 💳 Calcul de coût proraté basé sur le temps d'utilisation réel
- 📅 Filtrage par période (jour, semaine, mois, mois précédent)
- 👥 Filtrage par utilisateur pour les administrateurs
- 🧾 Génération automatique de factures avec export PDF
- 💰 Modes de paiement multiples (virement bancaire, PayPal, cartes de crédit)
- 📊 Suivi des revenus et résumés de coûts
- 📈 Journalisation détaillée d'activité avec billing_activities.log

#### 7. 🛡️ Fonctionnalités de Sécurité Améliorées

**🔒 Améliorations de Sécurité**:
- 🛡️ Protection ModSecurity WAF avec règles OWASP CRS
- 🔍 Validation d'entrée et prévention d'injection SQL
- 📁 Protection contre la traversée de chemin pour opérations de fichiers
- 🔐 Authentification basée sur session avec cookies sécurisés
- 🎫 Support de token SSO avec gestion d'expiration
- 👥 Isolation utilisateur avec répertoires de déploiement séparés
- 📝 Journalisation complète pour surveillance de sécurité
- ⏱️ Gestion de timeout de processus avec nettoyage gracieux

#### 8. 🎮 Gestion GPU Partagé MIG

**Fonctionnalités GPU**:
- 🖥️ **Partitionnement NVIDIA MIG**: Diviser un seul GPU en jusqu'à 7 instances isolées
- 🔧 **Configuration Par Serveur**: Activer/désactiver le GPU partagé par serveur via l'interface web ou API
- 📡 **Gestion via SSH**: Commandes GPU distantes via exécution SSH subprocess
- 🐳 **Accès GPU Docker**: Chaque instance MIG accessible via le flag `--gpus` dans les conteneurs
- 🔒 **Accès Admin Uniquement**: Tous les endpoints GPU appliquent l'authentification admin
- 📊 **Suivi des Instances**: Persistance en base de données des profils MIG et instances actives

**Endpoints API** (`/api/servers/<server_id>/gpu`):
- `PUT /enabled` — Basculer le GPU partagé (active le mode MIG via SSH à l'activation)
- `GET /profiles` — Lister les profils de partition MIG disponibles du matériel GPU
- `GET /instances` — Lister les instances MIG actives depuis la base de données
- `POST /instances` — Créer des instances MIG à partir d'IDs de profils (1-7)
- `DELETE /instances` — Détruire toutes les instances MIG sur le serveur

#### 9. ⚡ Exécution Docker Serverless

**Fonctionnalités Serverless**:
- 🐳 **Conteneurs à la Demande**: Soumettre des jobs Docker sans gérer l'infrastructure
- 🔒 **Sécurisation Renforcée**: Système de fichiers en lecture seule, pas de réseau, capacités retirées
- ⏱️ **Application des Timeouts**: Timeouts configurables par job avec terminaison gracieuse
- 📊 **File d'Attente**: Sauvegardée en PostgreSQL avec `FOR UPDATE SKIP LOCKED` pour workers concurrents
- 📈 **Mise à l'Échelle Horizontale**: Plusieurs workers peuvent fonctionner simultanément
- 🧹 **Nettoyage Automatique**: Anciens logs et jobs nettoyés selon la politique de rétention

**Endpoints API** (`/api/jobs`):
- `POST /jobs` — Soumettre un nouveau job Docker
- `GET /jobs` — Lister les jobs utilisateur avec pagination et filtrage
- `GET /jobs/<id>` — Obtenir le statut et métadonnées du job
- `GET /jobs/<id>/result` — Obtenir stdout/stderr et code de sortie
- `POST /jobs/<id>/cancel` — Annuler un job en attente ou en cours
- `GET /jobs/metrics` — Statistiques agrégées des jobs (admin)

#### 10. 🛡️ Isolation du Runtime de Conteneur

La plateforme supporte deux runtimes de conteneur, selectionnables par plateforme depuis la page Settings admin et stockes dans la table `configuration` de la base :

- `runc` (defaut) — runtime OCI standard partageant le noyau hote ; aucun flag `--runtime` emis.
- `kata` (optionnel) — Kata Containers ; chaque conteneur tourne dans une MicroVM dediee avec son propre noyau.

Quand `kata` est selectionne, la plateforme ajoute `--runtime kata` sur les repliques orchestrateur, les jobs serverless (le worker lit la valeur au demarrage ; redemarrage requis) et les deploiements git (transmis a `deployApp.sh` en argument et via `RUNTIME_TYPE`). La valeur est validee contre une liste (`runc`, `kata`) et retombe sur `runc`.

#### 11. 🧩 Deploy Templates, 🧙 Assistant d Onboarding, 🧪 Sandbox

- Deploy Templates : catalogue de blueprints valides (table `deploy_templates`, `template_catalog.py`) avec un service de deploiement agnostique (`template_deploy.py`) partage par Dashboard, CLI, MCP et REST.
- Assistant d onboarding : configuration au premier demarrage (`wizard_routes.py`, `configuration_writer.py`) qui ecrit `conf/deploy.ini` de maniere atomique avec sauvegarde horodatee.
- Compte demo Sandbox : utilisateur demo et deploiements sandbox (`sandbox_routes.py`) pour tester sans impacter les donnees reelles.
- Layout d installation configurable : dossier, utilisateur Linux et chemins pilotes par `conf/deploy.ini` (`PLTF_FOLDER`, `LINUX_USER_INSTALLATION`).
