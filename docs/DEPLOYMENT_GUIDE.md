# Application Deployment Guide / Guide de Déploiement d'Applications

## English

### Overview

The AI-SwAutoMorph platform supports deploying applications across multiple servers with automatic capacity management, real-time monitoring, and GenAI-powered code evolution. Users can clone, start, stop, and monitor applications in their own isolated directories with full multi-server support, comprehensive billing tracking, and bilingual interface (English/French).

### Enhanced Features

#### For All Users
- **Clone Applications**: Clone git repositories to your personal deployment directory with automatic SSL certificate sync
- **Multi-Server Deployment**: Automatic server allocation based on capacity with intelligent load balancing
- **Start/Stop Applications**: Control application lifecycle using deployApp.sh scripts with user context
- **Real-time Monitoring**: Live status updates and streaming logs via Server-Sent Events
- **GenAI Code Evolution**: Modify applications using natural language through unified AI Chat agents
- **Isolated Deployments**: Each user gets their own deployment directory with port allocation
- **Comprehensive Billing Tracking**: Automatic cost tracking with precise time measurement and activity logging
- **Multi-Language Support**: Full English/French interface with navbar language switching and session persistence
- **Unified Virtual Agents**: Single interface for both Developer and Operations agents with context-aware prompts

#### For Administrators
- **Enhanced Server Management**: Add, configure, and monitor multiple deployment servers with capacity constraints
- **User Management**: Create users, manage permissions, track usage, and handle account suspension
- **Application Management**: Add git repository URLs, manage application catalog, and configure costs
- **Database Administration**: Direct database access, health monitoring, and comprehensive statistics
- **Cost Management**: Configure application costs, view billing reports, and generate invoices
- **Documentation Management**: Bilingual markdown documentation with live editing and dynamic switching
- **Security Management**: ModSecurity WAF configuration, input validation, and comprehensive logging

### Multi-Server Architecture

#### Enhanced Server Types and Status
- **STAND_BY**: Server ready for new deployments with available capacity
- **ACTIVE**: Server currently hosting deployments with ongoing operations
- **MAINTENANCE**: Server temporarily unavailable for new deployments

#### Advanced Capacity Management
```
Enhanced Server Constraints:
- SERVER_CAPACITY_USER_MAX: Maximum users per server with real-time tracking
- SERVER_CAPACITY_APPLI_MAX: Maximum applications per server with usage monitoring
- Automatic allocation based on current utilization and performance metrics
- Intelligent load balancing with geographic considerations
- Capacity-based server selection with fallback mechanisms
```

#### Intelligent Server Allocation
The platform automatically selects the optimal server based on:
1. Current server capacity utilization with real-time monitoring
2. Server status preference (STAND_BY > ACTIVE > MAINTENANCE)
3. Network connectivity, performance metrics, and response times
4. Geographic location, latency measurements, and user proximity
5. Historical performance data and reliability metrics
6. Resource availability (CPU, memory, disk space, network bandwidth)

### How It Works

#### Enhanced Directory Structure
```
/home/<LINUX_USER_INSTALLATION>/deployments/
├── username1/
│   ├── ai-haccp/
│   │   ├── deployApp.sh              # Application deployment script
│   │   ├── ssl/                      # Auto-synced SSL certificates
│   │   │   ├── fullchain.pem         # SSL certificate chain
│   │   │   └── privkey.pem           # Private key
│   │   ├── deployment.log            # Deployment activity logs
│   │   └── [application files]       # Cloned application source
│   └── ai-foodflow/
│       ├── deployApp.sh
│       ├── ssl/
│       └── [application files]
└── username2/
    └── ai-haccp/
        ├── deployApp.sh
        ├── ssl/
        └── [application files]
```


> The install root is configurable, not hardcoded. `LINUX_USER_INSTALLATION` and `PLTF_FOLDER` are read from `conf/deploy.ini`, so paths resolve to `/home/<LINUX_USER_INSTALLATION>/...` for your deployment (the example uses `ubuntu`).

#### Enhanced Deployment Process

1. **Intelligent Server Allocation**: System selects optimal server based on capacity, performance, and geographic location
2. **Secure Clone**: Downloads the git repository to `/home/<LINUX_USER_INSTALLATION>/deployments/{username}/{app-name}/` with input validation
3. **SSL Certificate Sync**: Automatically copies SSL certificates to deployment directory with proper permissions
4. **Context-Aware Deploy Commands**: Runs `deployApp.sh` with user context (user_id, name, email) and environment variables
5. **Real-time Monitoring**: Tracks deployment status with streaming updates and comprehensive logging
6. **Comprehensive Billing**: Records usage with precise time measurement, cost calculation, and activity logging
7. **Security Validation**: Path traversal protection, input sanitization, and permission verification

### Usage

#### From Enhanced Dashboard

1. **Clone Application**:
   - Click the "📥 Clone" button on any application card
   - System automatically allocates optimal server based on capacity and performance
   - Repository cloned with SSL certificates synced and proper permissions set
   - Status shows as "cloning" then "cloned" when complete with real-time progress
   - Streaming progress updates via Server-Sent Events with detailed logging

2. **Start Application**:
   - Click the "▶️ Start" button or use unified virtual agents interface
   - Runs `./deployApp.sh start {user_id} "{user_name}" {user_email}` with environment context
   - Real-time status updates and streaming logs available via SSE
   - Comprehensive billing tracking automatically starts with precise timestamps
   - Port allocation configured in `conf/deploy.ini`:
     ```ini
     # Flat keys in conf/deploy.ini (no section header).
     RANGE_START=6000
     RANGE_RESERVED=100
     RANGE_PORTS_PER_APPLICATION=12
     ```
   - Port calculation: `HTTP_PORT = RANGE_START + user_id * RANGE_RESERVED + app_id * RANGE_PORTS_PER_APPLICATION`
   - Each application is allocated 12 consecutive ports (6 HTTP + 6 HTTPS)
   - SSL certificate validation and HTTPS configuration

3. **Stop Application**:
   - Click the "⏹️ Stop" button or use virtual agents interface
   - Runs `./deployApp.sh stop` in the application directory with graceful shutdown
   - Billing tracking automatically stops and calculates costs with duration measurement
   - Graceful shutdown with cleanup and resource deallocation
   - Process termination with proper signal handling

4. **Check Status**:
   - Click the "📊 Status" button or use PS command via virtual agents
   - Runs `./deployApp.sh ps` and shows current state with JSON output parsing
   - Real-time application health monitoring with performance metrics
   - Docker container status, resource usage, and network connectivity
   - Port availability and SSL certificate status

5. **View Logs**:
   - Click the "📋 Logs" button or use virtual agents interface
   - Opens modal with deployment status and streaming logs via Server-Sent Events
   - Real-time log updates with filtering and search capabilities
   - Filterable and searchable log output with timestamp correlation
   - Log rotation and archival with configurable retention policies

6. **Enhanced GenAI Code Evolution**:
   - Select application and use unified virtual agents interface
   - Use natural language to request code modifications via Developer agent
   - System creates Git branch: `{user_id}-automorph-{app_name}-{timestamp}`
   - Automatic code modification, testing, and redeployment with validation
   - Context-aware prompts from shared/ directory with operation-specific guidance
   - Streaming responses with real-time progress updates and error handling

#### Enhanced API Endpoints

##### Advanced Server Management
```bash
# Get available servers with capacity information
GET /api/servers

# Allocate server for deployment with intelligent selection
POST /api/server/allocate
Content-Type: application/json
{
  "application_name": "AI HACCP"
}

# Add new server with capacity constraints (admin only)
POST /api/servers
Content-Type: application/json
{
  "SERVER_IP": "192.168.1.100",
  "SERVER_NAME": "worker-01",
  "SERVER_CAPACITY_USER_MAX": 20,
  "SERVER_CAPACITY_APPLI_MAX": 100,
  "SERVER_STATUS": "STAND_BY",
  "SERVER_TYPE": "worker"
}

# Update server configuration (admin only)
PUT /api/servers/{server_id}
Content-Type: application/json
{
  "SERVER_STATUS": "MAINTENANCE",
  "SERVER_CAPACITY_USER_MAX": 25
}
```

##### Enhanced Deployment Management
```bash
# Get user deployments with detailed status
GET /api/deployments

# Create deployment with intelligent server allocation and streaming
POST /api/deployments
Content-Type: application/json
{
  "action": "clone|start|stop|status|restart|ps|logs",
  "application_name": "AI HACCP",
  "git_url": "https://github.com/Sam9682/ai-haccp.git",
  "server_id": 1,
  "stream": true  // Enable real-time streaming with SSE
}

# Get deployment logs with streaming support
GET /api/deployments/{deployment_id}/logs
```

##### Enhanced GenAI Integration with Unified Interface
```bash
# AI Chat Developer for code modification with context-aware prompts and streaming
POST /api/request_dev_ai_for_app
Content-Type: application/json
{
  "message": "Add a comprehensive health check endpoint with monitoring and alerting",
  "application_name": "AI HACCP",
  "application_folder": "/home/<LINUX_USER_INSTALLATION>/deployments/user/ai-haccp",
  "action_operation": "MODIFY_CODE"
}

# AI Chat Operations for deployment operations with streaming and billing integration
POST /api/request_ops_ai_for_app
Content-Type: application/json
{
  "message": "[START] Start the application with full monitoring and logging",
  "application_name": "AI HACCP",
  "application_folder": "/home/<LINUX_USER_INSTALLATION>/deployments/user/ai-haccp",
  "action_operation": "START"
}

# Streaming deployment with real-time progress and comprehensive logging
POST /api/deployments
Content-Type: application/json
{
  "action": "start",
  "application_name": "AI HACCP",
  "stream": true,
  "server_id": 1
}
```

##### Comprehensive Billing API
```bash
# Get billing activities with period and user filtering
GET /api/billing/activities?period=month&user=username

# Get billing summary with cost breakdown
GET /api/billing/summary?period=week

# Get application costs (admin only)
GET /api/billing/costs

# Update application cost (admin only)
PUT /api/billing/costs/{app_id}
Content-Type: application/json
{
  "cost_per_day": 2.5
}

# Get invoices with filtering
GET /api/billing/invoices

# Generate invoice for specific month (admin only)
POST /api/billing/invoices/generate
Content-Type: application/json
{
  "month": "2026-01",
  "user": "username"
}

# Generate invoice PDF
GET /api/billing/invoices/{invoice_id}/pdf

# Mark invoice as paid
PUT /api/billing/invoices/{invoice_id}/pay
```

### Requirements

#### Port Configuration

Application port allocation is configured in `conf/deploy.ini`:

```ini
# Flat keys in conf/deploy.ini (no section header). RANGE_START and
# RANGE_RESERVED default to 6000 and 100 in code if not present.
RANGE_START=6000
RANGE_RESERVED=100
RANGE_PORTS_PER_APPLICATION=12
```

**Port Allocation Formula:**

Each application is allocated 12 consecutive ports (6 HTTP + 6 HTTPS),
laid out as alternating HTTP/HTTPS pairs:

```python
PORT_RANGE_BEGIN = RANGE_START + user_id * RANGE_RESERVED
HTTP_PORT  = PORT_RANGE_BEGIN + app_id * RANGE_PORTS_PER_APPLICATION
HTTPS_PORT  = HTTP_PORT + 1
HTTP_PORT2  = HTTPS_PORT + 1
HTTPS_PORT2 = HTTP_PORT2 + 1
HTTP_PORT3  = HTTPS_PORT2 + 1
HTTPS_PORT3 = HTTP_PORT3 + 1
HTTP_PORT4  = HTTPS_PORT3 + 1
HTTPS_PORT4 = HTTP_PORT4 + 1
HTTP_PORT5  = HTTPS_PORT4 + 1
HTTPS_PORT5 = HTTP_PORT5 + 1
HTTP_PORT6  = HTTPS_PORT5 + 1
HTTPS_PORT6 = HTTP_PORT6 + 1
```

**Example Calculation:**
- User ID: 2
- App ID: 3
- RANGE_START: 6000
- RANGE_RESERVED: 100
- RANGE_PORTS_PER_APPLICATION: 12

Result:
- PORT_RANGE_BEGIN = 6000 + (2 × 100) = 6200
- HTTP_PORT = 6200 + (3 × 12) = 6236
- HTTPS_PORT = 6237
- HTTP_PORT2 = 6238, HTTPS_PORT2 = 6239
- HTTP_PORT3 = 6240, HTTPS_PORT3 = 6241
- HTTP_PORT4 = 6242, HTTPS_PORT4 = 6243
- HTTP_PORT5 = 6244, HTTPS_PORT5 = 6245
- HTTP_PORT6 = 6246, HTTPS_PORT6 = 6247

**Configuration Notes:**
- Each user gets a reserved range of ports (default: 100 ports)
- Each application within that range gets 12 ports (6 HTTP + 6 HTTPS)
- With 12 ports per application, a 100-port user range fits up to 8 applications
- Modify `conf/deploy.ini` to adjust port ranges for your environment
- Ensure firewall rules allow traffic on allocated port ranges

#### Enhanced Application Requirements
Applications must include a `deployApp.sh` script that supports:
- `./deployApp.sh start {user_id} "{user_name}" {user_email}` - Start the application with user context
- `./deployApp.sh stop` - Stop the application gracefully with cleanup
- `./deployApp.sh ps` - Show application status (JSON format preferred for parsing)
- `./deployApp.sh restart {user_id} "{user_name}" {user_email}` - Restart the application with user context
- `./deployApp.sh logs` - Show application logs with timestamp correlation

#### Enhanced System Requirements
- Git installed on all deployment servers with SSH key authentication
- Docker and Docker Compose (if applications use containers) with proper networking
- SSH access between servers for remote deployment with key-based authentication
- SSL certificates for HTTPS support with automatic renewal capabilities
- Sufficient disk space for application deployments and log storage
- Network access to git repositories with firewall configuration
- ModSecurity WAF with OWASP CRS rules for security protection
- **PostgreSQL database** with connection pooling for enterprise-grade performance
- **Database migration tools** for SQLite to PostgreSQL transition
- Backup system with PostgreSQL pg_dump for disaster recovery
- **Port configuration** in `conf/deploy.ini` for application port allocation

### Troubleshooting

#### Common Issues

1. **Clone Failed**:
   - Check git URL is accessible from target server with network connectivity tests
   - Verify network connectivity between servers with ping and traceroute
   - Ensure sufficient disk space on target server with df command
   - Check SSH key authentication for remote servers with ssh-add -l
   - Validate git repository permissions and access credentials
   - Review firewall rules and network security groups

2. **Deploy Commands Fail**:
   - Verify `deployApp.sh` exists and is executable with ls -la
   - Check application dependencies are installed on target server
   - Review deployment logs for specific errors with tail -f
   - Ensure Docker/Docker Compose is available if needed with docker --version
   - Validate environment variables and user context
   - Check port availability and conflicts with netstat

3. **Language Switching Issues**:
   - Clear browser cache and cookies with Ctrl+Shift+Delete
   - Verify Flask session is maintained with session inspection
   - Check JavaScript is enabled for dynamic content with browser console
   - Ensure language preference is stored in session with debug logging
   - Validate template integration with get_text() function
   - Review browser compatibility and JavaScript errors

4. **Server Allocation Issues**:
   - Check server capacity limits in database with SQL queries
   - Verify server status is STAND_BY or ACTIVE with API calls
   - Ensure network connectivity to target servers with telnet tests
   - Review server health and resource availability with monitoring tools
   - Validate capacity calculations and allocation algorithms
   - Check server performance metrics and response times

5. **Billing Issues**:
   - Verify billing_activities table for activity records with SQL queries
   - Check application_costs table for cost configuration
   - Validate cost calculation logic and duration tracking
   - Review billing logs for errors and inconsistencies
   - Ensure START/STOP actions are properly recorded
   - Check invoice generation and PDF export functionality

6. **Virtual Agents Issues**:
   - Verify AI Chat installation and PATH configuration
   - Check context files in shared/ directory for proper formatting
   - Validate prompt generation and logging functionality
   - Review timeout settings and process management
   - Ensure streaming responses work correctly with SSE
   - Check security validation and input sanitization

### Enhanced Status Meanings

- `pending`: Command queued for execution with timestamp
- `running`: Command currently executing with progress tracking
- `cloning`: Git clone in progress with real-time updates
- `cloned`: Repository successfully cloned with validation
- `completed`: Command completed successfully with exit code 0
- `failed`: Command failed with error details and troubleshooting info
- `timeout`: Command exceeded time limit with graceful termination
- `error`: System error occurred with detailed error message and stack trace
- `maintenance`: Server in maintenance mode with limited functionality
- `allocated`: Server successfully allocated for deployment
- `streaming`: Real-time streaming in progress with SSE connection

---

## Français

### Aperçu

La plateforme AI-SwAutoMorph prend en charge le déploiement d'applications sur plusieurs serveurs avec gestion automatique de capacité, surveillance en temps réel et évolution de code alimentée par GenAI. Les utilisateurs peuvent cloner, démarrer, arrêter et surveiller les applications dans leurs propres répertoires isolés avec support multi-serveurs complet, suivi de facturation complet et interface bilingue (Anglais/Français).

### Fonctionnalités Améliorées

#### Pour Tous les Utilisateurs
- **Cloner des Applications**: Cloner des dépôts git vers votre répertoire de déploiement personnel avec synchronisation automatique des certificats SSL
- **Déploiement Multi-Serveurs**: Allocation automatique de serveur basée sur la capacité avec équilibrage de charge intelligent
- **Démarrer/Arrêter Applications**: Contrôler le cycle de vie des applications avec les scripts deployApp.sh et contexte utilisateur
- **Surveillance Temps Réel**: Mises à jour de statut en direct et journaux en streaming via Server-Sent Events
- **Évolution de Code GenAI**: Modifier les applications en langage naturel via les agents AI Chat unifiés
- **Déploiements Isolés**: Chaque utilisateur obtient son propre répertoire de déploiement avec allocation de ports
- **Suivi de Facturation Complet**: Suivi automatique des coûts avec mesure de temps précise et journalisation d'activité
- **Support Multi-Langues**: Interface complète Anglais/Français avec changement de langue navbar et persistance de session
- **Agents Virtuels Unifiés**: Interface unique pour les agents Développeur et Opérations avec prompts contextuels

#### Pour les Administrateurs
- **Gestion de Serveurs Améliorée**: Ajouter, configurer et surveiller plusieurs serveurs de déploiement avec contraintes de capacité
- **Gestion d'Utilisateurs**: Créer des utilisateurs, gérer les permissions, suivre l'utilisation et gérer la suspension de comptes
- **Gestion d'Applications**: Ajouter des URLs de dépôts git, gérer le catalogue d'applications et configurer les coûts
- **Administration de Base de Données**: Accès direct à la base de données, surveillance de santé et statistiques complètes
- **Gestion des Coûts**: Configurer les coûts d'applications, voir les rapports de facturation et générer des factures
- **Gestion de Documentation**: Documentation markdown bilingue avec édition en direct et changement dynamique
- **Gestion de Sécurité**: Configuration ModSecurity WAF, validation d'entrée et journalisation complète

### Architecture Multi-Serveurs

#### Types et Statuts de Serveurs Améliorés
- **STAND_BY**: Serveur prêt pour nouveaux déploiements avec capacité disponible
- **ACTIVE**: Serveur hébergeant actuellement des déploiements avec opérations en cours
- **MAINTENANCE**: Serveur temporairement indisponible pour nouveaux déploiements

#### Gestion de Capacité Avancée
```
Contraintes Serveur Améliorées:
- SERVER_CAPACITY_USER_MAX: Maximum d'utilisateurs par serveur avec suivi temps réel
- SERVER_CAPACITY_APPLI_MAX: Maximum d'applications par serveur avec surveillance d'utilisation
- Allocation automatique basée sur l'utilisation actuelle et métriques de performance
- Équilibrage de charge intelligent avec considérations géographiques
- Sélection de serveur basée sur capacité avec mécanismes de fallback
```

#### Allocation de Serveur Intelligente
La plateforme sélectionne automatiquement le serveur optimal basé sur :
1. Utilisation actuelle de la capacité serveur avec surveillance temps réel
2. Préférence de statut serveur (STAND_BY > ACTIVE > MAINTENANCE)
3. Connectivité réseau, métriques de performance et temps de réponse
4. Localisation géographique, mesures de latence et proximité utilisateur
5. Données de performance historiques et métriques de fiabilité
6. Disponibilité des ressources (CPU, mémoire, espace disque, bande passante réseau)

### Fonctionnement

#### Structure de Répertoires Améliorée
```
/home/<LINUX_USER_INSTALLATION>/deployments/
├── username1/
│   ├── ai-haccp/
│   │   ├── deployApp.sh              # Script de déploiement d'application
│   │   ├── ssl/                      # Certificats SSL auto-synchronisés
│   │   │   ├── fullchain.pem         # Chaîne de certificats SSL
│   │   │   └── privkey.pem           # Clé privée
│   │   ├── deployment.log            # Journaux d'activité de déploiement
│   │   └── [fichiers application]    # Source d'application clonée
│   └── ai-foodflow/
│       ├── deployApp.sh
│       ├── ssl/
│       └── [fichiers application]
└── username2/
    └── ai-haccp/
        ├── deployApp.sh
        ├── ssl/
        └── [fichiers application]
```


> La racine d installation est configurable, pas codee en dur. `LINUX_USER_INSTALLATION` et `PLTF_FOLDER` sont lus depuis `conf/deploy.ini`, donc les chemins se resolvent en `/home/<LINUX_USER_INSTALLATION>/...` pour votre deploiement.

#### Processus de Déploiement Amélioré

1. **Allocation de Serveur Intelligente**: Le système sélectionne le serveur optimal basé sur la capacité, performance et localisation géographique
2. **Clone Sécurisé**: Télécharge le dépôt git vers `/home/<LINUX_USER_INSTALLATION>/deployments/{username}/{app-name}/` avec validation d'entrée
3. **Sync Certificat SSL**: Copie automatiquement les certificats SSL vers le répertoire de déploiement avec permissions appropriées
4. **Commandes Deploy Contextuelles**: Exécute `deployApp.sh` avec contexte utilisateur (user_id, nom, email) et variables d'environnement
5. **Surveillance Temps Réel**: Suit le statut de déploiement avec mises à jour streaming et journalisation complète
6. **Facturation Complète**: Enregistre l'utilisation avec mesure de temps précise, calcul de coût et journalisation d'activité
7. **Validation de Sécurité**: Protection contre traversée de chemin, sanitisation d'entrée et vérification de permissions

### Dépannage

#### Problèmes Courants

1. **Échec de Clone**:
   - Vérifier que l'URL git est accessible depuis le serveur cible avec tests de connectivité réseau
   - Vérifier la connectivité réseau entre serveurs avec ping et traceroute
   - S'assurer d'un espace disque suffisant sur le serveur cible avec commande df
   - Vérifier l'authentification par clé SSH pour serveurs distants avec ssh-add -l
   - Valider les permissions de dépôt git et identifiants d'accès
   - Examiner les règles de pare-feu et groupes de sécurité réseau

2. **Échec des Commandes Deploy**:
   - Vérifier que `deployApp.sh` existe et est exécutable avec ls -la
   - Vérifier que les dépendances d'application sont installées sur le serveur cible
   - Examiner les journaux de déploiement pour erreurs spécifiques avec tail -f
   - S'assurer que Docker/Docker Compose est disponible si nécessaire avec docker --version
   - Valider les variables d'environnement et contexte utilisateur
   - Vérifier la disponibilité des ports et conflits avec netstat

3. **Problèmes de Changement de Langue**:
   - Vider le cache et cookies du navigateur avec Ctrl+Shift+Delete
   - Vérifier que la session Flask est maintenue avec inspection de session
   - Vérifier que JavaScript est activé pour le contenu dynamique avec console navigateur
   - S'assurer que la préférence de langue est stockée en session avec journalisation debug
   - Valider l'intégration template avec fonction get_text()
   - Examiner la compatibilité navigateur et erreurs JavaScript

4. **Problèmes d'Allocation Serveur**:
   - Vérifier les limites de capacité serveur en base de données avec requêtes SQL
   - Vérifier que le statut serveur est STAND_BY ou ACTIVE avec appels API
   - S'assurer de la connectivité réseau vers les serveurs cibles avec tests telnet
   - Examiner la santé serveur et disponibilité des ressources avec outils de surveillance
   - Valider les calculs de capacité et algorithmes d'allocation
   - Vérifier les métriques de performance serveur et temps de réponse

5. **Problèmes de Facturation**:
   - Vérifier la table billing_activities pour enregistrements d'activité avec requêtes SQL
   - Vérifier la table application_costs pour configuration de coût
   - Valider la logique de calcul de coût et suivi de durée
   - Examiner les journaux de facturation pour erreurs et incohérences
   - S'assurer que les actions START/STOP sont correctement enregistrées
   - Vérifier la génération de factures et fonctionnalité d'export PDF

6. **Problèmes d'Agents Virtuels**:
   - Vérifier l'installation AI Chat et configuration PATH
   - Vérifier les fichiers de contexte dans le répertoire shared/ pour formatage approprié
   - Valider la génération de prompts et fonctionnalité de journalisation
   - Examiner les paramètres de timeout et gestion de processus
   - S'assurer que les réponses streaming fonctionnent correctement avec SSE
   - Vérifier la validation de sécurité et sanitisation d'entrée

### Significations des Statuts Améliorées

- `pending`: Commande en file d'attente pour exécution avec horodatage
- `running`: Commande en cours d'exécution avec suivi de progression
- `cloning`: Clone git en cours avec mises à jour temps réel
- `cloned`: Dépôt cloné avec succès avec validation
- `completed`: Commande terminée avec succès avec code de sortie 0
- `failed`: Commande échouée avec détails d'erreur et info de dépannage
- `timeout`: Commande a dépassé la limite de temps avec terminaison gracieuse
- `error`: Erreur système survenue avec message d'erreur détaillé et trace de pile
- `maintenance`: Serveur en mode maintenance avec fonctionnalité limitée
- `allocated`: Serveur alloué avec succès pour déploiement
- `streaming`: Streaming temps réel en cours avec connexion SSE