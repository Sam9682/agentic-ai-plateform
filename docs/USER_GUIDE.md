# 🤖 AI-SwAutoMorph User Guide / Guide Utilisateur AI-SwAutoMorph

## English

<div class="center">
🚀 **Centralized Application Deployment Platform for GenAI Agents** 🌟
</div>

### 📋 Table of Contents
- [🌟 Overview](#overview)
- [🤖 Virtual AI Agents](#virtual-ai-agents)
- [🔧 AI Chat Developer Agent](#q-chat-developer-agent)
- [🚀 AI Chat Operations Agent](#q-chat-operations-agent)
- [⚡ Agent Workflows](#agent-workflows)
- [🎯 Platform Features](#platform-features)
- [💰 Billing System](#billing-system)
- [🔧 Troubleshooting](#troubleshooting)

### 🌟 Overview

AI-SwAutoMorph is a **centralized application deployment and management platform** designed for GenAI agents. It provides automated deployment, lifecycle management, and SSO authentication for web applications through multiple interfaces (Web, CLI, API, MCP). The platform enables GenAI agents to autonomously deploy, manage, and access web applications without human intervention.

**Core Purpose**: Enable GenAI agents to autonomously deploy, manage, and access web applications through intelligent automation with comprehensive billing tracking and multi-server support.

<div class="center">
🎯 **Key Features**: Virtual AI Agents, Multi-Server Deployment, Billing & Cost Tracking, SSO Authentication, ModSecurity WAF Protection
</div>

### 🤖 Virtual AI Agents

The platform provides **two specialized virtual AI agents** with context-aware prompts and streaming responses:

#### 🔧 AI Chat Developer Agent
**🎯 Purpose:** Code modification, feature development, and application enhancement

- 💻 Modifies source code based on natural language requests
- ⚡ Adds new features and API endpoints
- 🔄 Refactors and optimizes existing code
- 🐛 Handles bug fixes and code improvements
- 🌿 Creates timestamped Git branches with format `{user_id}-automorph-{app_name}-{timestamp}`
- ⏱️ 30-minute timeout with graceful cleanup
- 📡 Real-time streaming responses with Server-Sent Events

#### 🚀 AI Chat Operations Agent
**🎯 Purpose:** Deployment operations, infrastructure management, and application lifecycle

- ⚡ Handles deployment commands (START, STOP, RESTART, PS, LOGS)
- 📊 Manages application lifecycle and monitoring
- 🏗️ Performs infrastructure operations with multi-server support
- 🚀 Executes deployment scripts with user context
- 📈 Provides real-time status updates and streaming logs
- 💰 Automatic billing activity recording for START/STOP actions
- 🔄 Fallback Q&A mode for invalid actions

![Virtual Operations](https://www.swautomorph.com/static/VirtualOperations.png)

### 🔧 AI Chat Developer Agent

#### 🛠️ Agent Capabilities
- **🔍 Code Analysis:** Understands existing codebase structure
- **⚡ Feature Development:** Adds new functionality based on requirements
- **🔌 API Creation:** Generates new REST endpoints and handlers
- **🔄 Code Refactoring:** Improves code quality and performance
- **🐛 Bug Resolution:** Identifies and fixes code issues
- **🌿 Git Integration:** Creates branches with format `{user_id}-automorph-{app_name}-{timestamp}`

#### 🔌 API Endpoint
```
POST /api/request_dev_ai_for_app
```

**📝 Request Body:**
```json
{
  "message": "Add a new API endpoint for user management",
  "application_name": "MyApp",
  "application_folder": "/path/to/app",
  "auto_approve": true,
  "gitea_url": "http://localhost:3000/gitadmin/branch-name",
  "userid": "1",
  "username": "agent"
}
```

### 🚀 AI Chat Operations Agent

#### 🛠️ Agent Capabilities
- **🚀 Deployment Management:** Handles START, STOP, RESTART operations
- **🏗️ Infrastructure Operations:** Manages servers and resources
- **📊 Monitoring:** Checks application status and logs
- **📈 Scaling:** Manages application capacity and performance
- **🔧 Troubleshooting:** Diagnoses and resolves deployment issues
- **🖥️ Multi-Server Support:** Automatic server allocation based on capacity

#### 🔌 API Endpoint
```
POST /api/request_ops_ai_for_app
```

**📝 Request Body:**
```json
{
  "message": "[START] Start the application",
  "application_name": "MyApp",
  "application_folder": "/path/to/app"
}
```

### ⚡ Agent Workflows

#### 1. 🏗️ Application Setup
- 👤 Register agent user account via `/register` endpoint
- 📱 Add application with Git repository (admin required)
- 📥 Clone application to deployment directory
- 🖥️ Automatic server allocation based on capacity

#### 2. 💻 Development Phase (Developer Agent)
- 🔍 Analyze existing codebase structure
- ⚡ Implement new features or fixes using natural language
- 🌿 Create timestamped Git branches for tracking
- ⚙️ Modify configuration files and dependencies
- 🧪 Test deployment with `deployApp.sh`

#### 3. 🚀 Deployment Phase (Operations Agent)
- ▶️ Start application services with user context
- 📊 Monitor deployment status with real-time updates
- 📋 Check application logs and health
- 🔄 Manage application lifecycle (start/stop/restart)
- 🖥️ Handle server capacity and resource allocation

### 🎯 Platform Features

#### 🌍 Multi-Language Support
- **🔄 Navbar Language Toggle:** FR/EN switching in navigation bar
- **💾 Session Persistence:** Language preference stored in Flask session
- **📖 Documentation:** All guides available in English and French
- **⚡ Dynamic Switching:** Real-time language changes without page reload
- **🎨 Template Integration:** All templates support `get_text()` function

#### 🧭 Enhanced Navigation Architecture
- **📱 Applications Tab:** Main application management interface with real-time status
- **💰 Billing Tab:** Comprehensive cost tracking and invoice management
- **⚙️ Configuration Dropdown:** Admin access to Users, Servers, Database management
- **❓ Help Dropdown:** Direct access to Architecture, Deployment, and User guides
- **📱 Mobile Responsive:** Hamburger menu for mobile devices
- **🌍 Language Toggle:** Persistent language switching in navbar

#### 📊 Enhanced Dashboard Features
- **⏱️ Real-time Status:** Live application status updates
- **📈 Streaming Logs:** Server-Sent Events for real-time log viewing
- **🎴 Application Cards:** Visual interface with status indicators
- **🔘 Action Buttons:** Clone, Start, Stop, Status, Logs with streaming support
- **🤖 Unified Virtual Agents:** Single interface for Developer and Operations agents
- **🖥️ Multi-Server Support:** Automatic server allocation based on capacity
- **💰 Billing Integration:** Real-time cost tracking and activity logging

#### 🔐 Enhanced Authentication & Security
- **🔑 Session-based Authentication:** Secure login with session management
- **🎫 SSO Token Support:** Single Sign-On integration with Gitea
- **🏠 User Isolation:** Each user gets isolated deployment directories
- **👑 Admin Controls:** Comprehensive admin interface for system management
- **🛡️ ModSecurity WAF:** Protection with OWASP CRS rules
- **🔒 Input Validation:** SQL injection prevention and path traversal protection

#### 🖥️ Multi-Server Architecture
- **🏗️ Server Management:** Add, configure, and monitor multiple deployment servers
- **📊 Capacity Management:** Automatic server allocation based on utilization
- **🔄 Server Status:** STAND_BY, ACTIVE, MAINTENANCE status management
- **🌐 Remote Deployment:** SSH-based deployment to remote servers
- **⚖️ Load Balancing:** Intelligent server selection for optimal performance

### 💰 Billing System

#### 📊 Comprehensive Cost Tracking
- **⏱️ Automatic Activity Recording:** START/STOP actions tracked with precise timestamps
- **💳 Cost Calculation:** Prorated billing based on actual usage time
- **📈 Usage Monitoring:** Real-time tracking of application usage
- **🧾 Invoice Generation:** Automated monthly invoice creation
- **💰 Payment Modes:** Support for bank transfer, PayPal, and credit cards
- **📊 Billing Reports:** Detailed usage summaries and activity logs

#### 💳 Billing Features
- **📅 Period Filtering:** View costs by day, week, month, or previous month
- **👥 User Filtering:** Admin can filter by specific users
- **📊 Cost Management:** Configure application-specific daily rates
- **🧾 Invoice Management:** Generate, view, and mark invoices as paid
- **📈 Activity Logging:** Detailed logs of all billable activities
- **💰 Revenue Tracking:** Total revenue and cost summaries

### 🎮 MIG Shared GPU Management

The platform provides GPU sharing through NVIDIA Multi-Instance GPU (MIG) technology, allowing administrators to partition a single GPU into multiple isolated instances.

#### 🖥️ Web Interface

Navigate to **Servers** → click **Shared-GPU** button on any server to access the GPU management page:

1. **Enable/Disable**: Toggle switch to activate MIG mode on the server
2. **View Profiles**: See available partition sizes (e.g., 1g.10gb, 2g.20gb, 4g.40gb)
3. **Create Instances**: Select profiles and click "Create Instances" (max 7 per GPU)
4. **Monitor**: View active MIG instances with UUID, profile, memory, and timestamp
5. **Destroy**: Remove all instances with one click when reconfiguration is needed

#### 🔌 GPU API Endpoints

All GPU endpoints require admin authentication and use the prefix `/api/servers/<server_id>/gpu`:

```bash
# Enable shared GPU on a server
curl -X PUT https://www.swautomorph.com/api/servers/1/gpu/enabled \
  -H "Content-Type: application/json" \
  -H "Cookie: session=your-session-cookie" \
  -d '{"enabled": true}'

# List available MIG profiles
curl https://www.swautomorph.com/api/servers/1/gpu/profiles \
  -H "Cookie: session=your-session-cookie"

# Create MIG instances (1-7 profile IDs)
curl -X POST https://www.swautomorph.com/api/servers/1/gpu/instances \
  -H "Content-Type: application/json" \
  -H "Cookie: session=your-session-cookie" \
  -d '{"profile_ids": ["9", "14", "9"]}'

# List active instances
curl https://www.swautomorph.com/api/servers/1/gpu/instances \
  -H "Cookie: session=your-session-cookie"

# Destroy all instances
curl -X DELETE https://www.swautomorph.com/api/servers/1/gpu/instances \
  -H "Cookie: session=your-session-cookie"
```

#### 🐳 Using GPU Instances in Docker

After creating MIG instances, containers can access specific GPU slices:

```bash
docker run --gpus '"device=MIG-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"' my-ai-model:latest
```

---

### ⚡ Serverless Docker Execution

Submit Docker-based jobs on-demand without managing infrastructure. The platform handles scheduling, execution, security isolation, and result storage.

#### 🔌 Serverless API

```bash
# Submit a job
curl -X POST https://www.swautomorph.com/api/jobs \
  -H "Content-Type: application/json" \
  -H "Cookie: session=your-session-cookie" \
  -d '{"image": "python:3.11-slim", "command": ["python", "-c", "print(hello)"], "timeout": 60}'

# Check job status
curl https://www.swautomorph.com/api/jobs/<job_id> \
  -H "Cookie: session=your-session-cookie"

# Get job result (stdout/stderr)
curl https://www.swautomorph.com/api/jobs/<job_id>/result \
  -H "Cookie: session=your-session-cookie"

# Cancel a job
curl -X POST https://www.swautomorph.com/api/jobs/<job_id>/cancel \
  -H "Cookie: session=your-session-cookie"

# List all user jobs
curl https://www.swautomorph.com/api/jobs?page=1&per_page=20 \
  -H "Cookie: session=your-session-cookie"
```

#### 📊 Job States
- `pending` — Queued, waiting for a worker
- `running` — Being executed in a container
- `completed` — Finished successfully
- `failed` — Container exited with non-zero code
- `timeout` — Exceeded the configured timeout
- `cancelled` — Cancelled by user

---

### 🧩 Deploy Templates

The platform ships a catalog of ready-to-deploy blueprints. Every surface (Dashboard, CLI, MCP, REST) deploys through the same service, so behavior is identical everywhere. Deployed apps are exposed at `https://{domain}/{USER_ID}/{APPLICATION_NAME}`.

Built-in templates: `static-site` (nginx), `fastapi-starter`, `n8n`, `ollama`, `jupyter`, `vector-db` (Qdrant).

```bash
# List available templates
curl https://www.swautomorph.com/api/templates -H "Cookie: session=your-session-cookie"

# Deploy from a template
curl -X POST https://www.swautomorph.com/api/templates/fastapi-starter/deploy -H "Content-Type: application/json" -H "Cookie: session=your-session-cookie" -d '{"application_name":"my-api"}'
```

### 🛡️ Container Runtime

Admins can choose the container runtime from the Settings page: `runc` (default, shares the host kernel) or `kata` (optional, each container in its own MicroVM). The choice applies to app deployments, serverless jobs, and orchestrator replicas; serverless workers pick up a change on restart.

### 🧙 Onboarding Wizard and 🧪 Sandbox

On first run, a guided setup wizard writes `conf/deploy.ini` safely (timestamped backup, atomic write, hashed admin password). A labeled Sandbox demo account lets you try the platform with throwaway deployments that do not affect real data.

### 🔧 Troubleshooting

#### 🚫 Authentication Failures
- ✅ Verify session cookies are included in requests
- 👤 Check if user account has appropriate permissions
- 🎫 Ensure SSO token is valid and not expired
- ⚠️ Confirm user account is not suspended (suspended=0)
- 🔐 Verify password hash is correct in database

#### 🔧 Developer Agent Issues
- 📁 Verify application folder path exists and is accessible
- 🔒 Check if application has proper file permissions
- 🌿 Ensure Git repository is accessible and credentials are valid
- 🖥️ Confirm AI Chat is installed and accessible in PATH
- ⏱️ Check for timeout issues (30-minute limit)
- 📝 Verify context files exist in shared/ directory

#### 🚀 Operations Agent Issues
- ⚙️ Check if deployment scripts (`deployApp.sh`) are executable
- 🐳 Verify Docker services are running on target server
- 💾 Ensure server has sufficient resources (CPU, memory, disk)
- 🌐 Confirm network connectivity between servers
- 🖥️ Verify server status is STAND_BY or ACTIVE
- 💰 Check billing activity recording for START/STOP actions

#### 🌍 Language Switching Issues
- 🗑️ Clear browser cache and cookies
- 🔄 Check Flask session is properly maintained
- 💾 Verify language preference is stored in session
- ⚡ Ensure JavaScript is enabled for dynamic content switching
- 🎨 Confirm template integration with get_text() function

#### 💰 Billing Issues
- 📊 Check application_costs table for cost configuration
- ⏱️ Verify billing_activities table for activity records
- 🧾 Confirm invoice generation for specific months
- 💳 Check payment_modes table for user payment methods
- 📈 Verify cost calculation logic and duration tracking

#### 🔍 Debug Commands
```bash
# 🔍 Check authentication status
curl https://www.swautomorph.com/api/auth/status

# 📱 Verify applications
curl https://www.swautomorph.com/api/applications

# 🖥️ Check server capacity and allocation
curl https://www.swautomorph.com/api/servers

# 💰 Check billing activities
curl https://www.swautomorph.com/api/billing/activities

# 🗄️ Database health check (admin only)
curl https://www.swautomorph.com/api/health/database

# 🧪 Test developer agent
curl -X POST /api/request_dev_ai_for_app \
  -H "Content-Type: application/json" \
  -H "Cookie: session=your-session-cookie" \
  -d '{"message":"test connection","application_name":"test"}'

# 🧪 Test operations agent
curl -X POST /api/request_ops_ai_for_app \
  -H "Content-Type: application/json" \
  -H "Cookie: session=your-session-cookie" \
  -d '{"message":"[START] test","application_name":"test"}'

# 🎮 Check GPU status on a server
curl https://www.swautomorph.com/api/servers/1/gpu/instances \
  -H "Cookie: session=your-session-cookie"

# ⚡ Check serverless job metrics (admin)
curl https://www.swautomorph.com/api/jobs/metrics \
  -H "Cookie: session=your-session-cookie"
```

---

## Français

<div class="center">
🚀 **Agents IA Autonomes pour la Gestion d'Applications Web** 🌟
</div>

### 📋 Table des Matières
- [🌟 Aperçu pour les Agents IA](#aperçu-pour-les-agents-ia)
- [🤖 Types d'Agents IA](#types-dagents-ia)
- [🔧 Agent Développeur AI Chat](#agent-développeur-q-chat)
- [🚀 Agent Opérations AI Chat](#agent-opérations-q-chat)
- [⚡ Flux de Travail des Agents](#flux-de-travail-des-agents)
- [🎯 Fonctionnalités de la Plateforme](#fonctionnalités-de-la-plateforme)
- [🔧 Dépannage](#dépannage)

### 🌟 Aperçu

AI-SwAutoMorph est une **plateforme centralisée de déploiement et de gestion d'applications** conçue pour les agents GenAI. Elle fournit un déploiement automatisé, une gestion du cycle de vie et une authentification SSO pour les applications web à travers plusieurs interfaces (Web, CLI, API, MCP). La plateforme permet aux agents GenAI de déployer, gérer et accéder de manière autonome aux applications web sans intervention humaine.

**Objectif Principal**: Permettre aux agents GenAI de déployer, gérer et accéder de manière autonome aux applications web grâce à l'automatisation intelligente avec suivi complet de facturation et support multi-serveurs.

<div class="center">
🎯 **Fonctionnalités Clés**: Agents IA Virtuels, Déploiement Multi-Serveurs, Suivi de Facturation et Coûts, Authentification SSO, Protection ModSecurity WAF
</div>

### 🤖 Types d'Agents IA

#### 🔧 Agent Développeur AI Chat
**🎯 Objectif:** Modification de code, développement de fonctionnalités et amélioration d'applications

- 💻 Modifie le code source basé sur des demandes en langage naturel
- ⚡ Ajoute de nouvelles fonctionnalités et points de terminaison API
- 🔄 Refactorise et optimise le code existant
- 🐛 Gère les corrections de bugs et améliorations de code
- 🌿 Crée des branches Git horodatées pour le suivi des modifications

#### 🚀 Agent Opérations AI Chat
**🎯 Objectif:** Opérations de déploiement, gestion d'infrastructure et cycle de vie des applications

- ⚡ Gère les commandes de déploiement (START, STOP, RESTART)
- 📊 Gère le cycle de vie et la surveillance des applications
- 🏗️ Effectue les opérations d'infrastructure
- 🚀 Exécute les scripts et configurations de déploiement
- 📈 Fournit des mises à jour de statut en temps réel et journaux en streaming

![Virtual Operations](https://www.swautomorph.com/static/VirtualOperations.png)

### 🔧 Agent Développeur AI Chat

#### 🛠️ Capacités de l'Agent
- **🔍 Analyse de Code:** Comprend la structure de la base de code existante
- **⚡ Développement de Fonctionnalités:** Ajoute de nouvelles fonctionnalités basées sur les exigences
- **🔌 Création d'API:** Génère de nouveaux points de terminaison REST et gestionnaires
- **🔄 Refactorisation de Code:** Améliore la qualité et les performances du code
- **🐛 Résolution de Bugs:** Identifie et corrige les problèmes de code
- **🌿 Intégration Git:** Crée des branches avec format `{user_id}-automorph-{app_name}-{timestamp}`

#### 🔌 Point de Terminaison API
```
POST /api/request_dev_ai_for_app
```

**📝 Corps de Requête:**
```json
{
  "message": "Ajouter un nouveau point de terminaison API pour la gestion des utilisateurs",
  "application_name": "MonApp",
  "application_folder": "/chemin/vers/app",
  "auto_approve": true,
  "gitea_url": "http://localhost:3000/gitadmin/branch-name",
  "userid": "1",
  "username": "agent"
}
```

### 🚀 Agent Opérations AI Chat

#### 🛠️ Capacités de l'Agent
- **🚀 Gestion de Déploiement:** Gère les opérations START, STOP, RESTART
- **🏗️ Opérations d'Infrastructure:** Gère les serveurs et ressources
- **📊 Surveillance:** Vérifie le statut et les journaux des applications
- **📈 Mise à l'Échelle:** Gère la capacité et les performances des applications
- **🔧 Dépannage:** Diagnostique et résout les problèmes de déploiement
- **🖥️ Support Multi-Serveurs:** Allocation automatique de serveur basée sur la capacité

#### 🔌 Point de Terminaison API
```
POST /api/request_ops_ai_for_app
```

**📝 Corps de Requête:**
```json
{
  "message": "[START] Démarrer l'application",
  "application_name": "MonApp",
  "application_folder": "/chemin/vers/app"
}
```

### ⚡ Flux de Travail des Agents

#### 1. 🏗️ Configuration de l'Application
- 👤 Enregistrer le compte utilisateur agent via le point de terminaison `/register`
- 📱 Ajouter l'application avec le dépôt Git (admin requis)
- 📥 Cloner l'application vers le répertoire de déploiement
- 🖥️ Allocation automatique de serveur basée sur la capacité

#### 2. 💻 Phase de Développement (Agent Développeur)
- 🔍 Analyser la structure de la base de code existante
- ⚡ Implémenter de nouvelles fonctionnalités ou corrections en langage naturel
- 🌿 Créer des branches Git horodatées pour le suivi
- ⚙️ Modifier les fichiers de configuration et dépendances
- 🧪 Tester le déploiement avec `deployApp.sh`

#### 3. 🚀 Phase de Déploiement (Agent Opérations)
- ▶️ Démarrer les services d'application avec contexte utilisateur
- 📊 Surveiller le statut de déploiement avec mises à jour temps réel
- 📋 Vérifier les journaux et la santé de l'application
- 🔄 Gérer le cycle de vie de l'application (start/stop/restart)
- 🖥️ Gérer la capacité serveur et l'allocation des ressources

### 🎯 Fonctionnalités de la Plateforme

#### 🌍 Support Multi-Langues
- **🔄 Basculement Langue Navbar:** Changement FR/EN dans la barre de navigation
- **💾 Persistance Session:** Préférence de langue stockée dans la session utilisateur
- **📖 Documentation:** Tous les guides disponibles en Anglais et Français
- **⚡ Changement Dynamique:** Modifications de langue temps réel sans rechargement de page

#### 🧭 Organisation de Navigation
- **📱 Onglet Applications:** Interface principale de gestion d'applications
- **💰 Onglet Facturation:** Suivi des coûts et surveillance d'utilisation
- **⚙️ Menu Déroulant Configuration:** Accès admin aux Utilisateurs, Serveurs, Base de données
- **❓ Menu Déroulant Aide:** Accès direct aux guides Architecture, Déploiement et Utilisateur
- **📱 Responsive Mobile:** Menu hamburger pour appareils mobiles

### 🎮 Gestion GPU Partagé MIG

La plateforme permet le partage GPU via la technologie NVIDIA Multi-Instance GPU (MIG), permettant aux administrateurs de partitionner un seul GPU en plusieurs instances isolées.

#### 🖥️ Interface Web

Naviguer vers **Serveurs** → cliquer sur **Shared-GPU** pour accéder à la page de gestion GPU :

1. **Activer/Désactiver**: Interrupteur pour activer le mode MIG sur le serveur
2. **Voir les Profils**: Tailles de partition disponibles (ex: 1g.10gb, 2g.20gb, 4g.40gb)
3. **Créer des Instances**: Sélectionner des profils et cliquer "Créer" (max 7 par GPU)
4. **Surveiller**: Voir les instances MIG actives avec UUID, profil, mémoire et timestamp
5. **Détruire**: Supprimer toutes les instances en un clic pour reconfiguration

### ⚡ Exécution Docker Serverless

Soumettre des jobs Docker à la demande sans gérer l'infrastructure. La plateforme gère la planification, l'exécution, l'isolation de sécurité et le stockage des résultats.

#### 📊 États des Jobs
- `pending` — En file d'attente
- `running` — En cours d'exécution dans un conteneur
- `completed` — Terminé avec succès
- `failed` — Conteneur terminé avec code non-zéro
- `timeout` — Délai configuré dépassé
- `cancelled` — Annulé par l'utilisateur

---

### 🧩 Deploy Templates

La plateforme fournit un catalogue de blueprints prets a deployer. Chaque surface (Dashboard, CLI, MCP, REST) deploie via le meme service, donc le comportement est identique partout. Les apps deployees sont exposees sur `https://{domain}/{USER_ID}/{APPLICATION_NAME}`.

Templates integres : `static-site` (nginx), `fastapi-starter`, `n8n`, `ollama`, `jupyter`, `vector-db` (Qdrant).

### 🛡️ Runtime de Conteneur

Les admins choisissent le runtime depuis la page Settings : `runc` (defaut, partage le noyau hote) ou `kata` (optionnel, chaque conteneur dans sa propre MicroVM). Le choix s applique aux deploiements, jobs serverless et repliques orchestrateur ; les workers serverless prennent en compte un changement au redemarrage.

### 🧙 Assistant d Onboarding et 🧪 Sandbox

Au premier demarrage, un assistant guide ecrit `conf/deploy.ini` en securite (sauvegarde horodatee, ecriture atomique, mot de passe admin hache). Un compte demo Sandbox permet de tester la plateforme avec des deploiements jetables sans impacter les donnees reelles.

### 🔧 Dépannage

#### 🚫 Échecs d'Authentification
- ✅ Vérifier que les cookies de session sont inclus dans les requêtes
- 👤 Vérifier si le compte agent a les permissions appropriées
- 🎫 S'assurer que le token SSO est valide et non expiré
- ⚠️ Confirmer que le compte utilisateur n'est pas suspendu

#### 🔧 Problèmes de l'Agent Développeur
- 📁 Vérifier que le chemin du dossier d'application existe et est accessible
- 🔒 Vérifier si l'application a les permissions de fichier appropriées
- 🌿 S'assurer que le dépôt Git est accessible et les identifiants sont valides
- 🖥️ Confirmer que le serveur Gitea fonctionne et est accessible

#### 🚀 Problèmes de l'Agent Opérations
- ⚙️ Vérifier si les scripts de déploiement (`deployApp.sh`) sont exécutables
- 🐳 Vérifier que les services Docker fonctionnent sur le serveur cible
- 💾 S'assurer que le serveur a suffisamment de ressources (CPU, mémoire, disque)
- 🌐 Confirmer la connectivité réseau entre serveurs