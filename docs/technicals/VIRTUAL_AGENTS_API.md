# 🤖 Virtual AI Agents API Reference / Référence API des Agents IA Virtuels

## English

<div class="center">
🚀 **Virtual AI Agents for Autonomous Application Management** 🌟
</div>

### 📋 Table of Contents
- [🌟 Overview](#overview)
- [🔧 AI Chat Developer Agent](#q-chat-developer-agent)
- [🚀 AI Chat Operations Agent](#q-chat-operations-agent)
- [📡 Enhanced Streaming API](#enhanced-streaming-api)
- [🎯 Context-Aware Prompts](#context-aware-prompts)
- [💰 Billing Integration](#billing-integration)
- [🔧 Error Handling](#error-handling)
- [🛡️ Security Features](#security-features)

### 🌟 Overview

AI-SwAutoMorph provides two specialized virtual AI agents designed for autonomous application management with enhanced features:

- **🔧 AI Chat Developer Agent**: Code modification, feature development, and application enhancement
- **🚀 AI Chat Operations Agent**: Deployment operations, infrastructure management, and application lifecycle

Both agents support:
- ⚡ **Enhanced Streaming responses** with Server-Sent Events and real-time progress tracking
- 🎯 **Context-aware prompts** from shared configuration files with dynamic variable substitution
- ⏱️ **Advanced timeout management** with graceful cleanup (30 minutes) and process group termination
- 💰 **Comprehensive billing** activity recording with precise time measurement
- 🔄 **Intelligent fallback modes** for error scenarios and invalid actions
- 🔒 **Enhanced security** with input validation, path traversal protection, and comprehensive logging
- 📝 **Detailed logging** with prompt generation tracking and error diagnostics

### 🔧 AI Chat Developer Agent

**Endpoint**: `POST /api/request_dev_ai_for_app`

**Purpose**: Autonomous code modification and feature development using natural language instructions with advanced Git integration.

#### 🛠️ Enhanced Capabilities
- 💻 **Advanced Code Analysis**: Understands existing codebase structure with dependency mapping
- ⚡ **Feature Development**: Adds new functionality based on requirements with validation
- 🔌 **API Creation**: Generates new REST endpoints and handlers with documentation
- 🔄 **Code Refactoring**: Improves code quality and performance with metrics
- 🐛 **Bug Resolution**: Identifies and fixes code issues with testing
- 🌿 **Enhanced Git Integration**: Creates branches with format `{user_id}-automorph-{app_name}-{timestamp}`
- 📝 **Prompt Logging**: Saves generated prompts to `dev_prompt_generated.txt` for debugging
- 🔒 **Security Validation**: Path traversal protection and input sanitization

#### 📝 Enhanced Request Format
```json
{
  "message": "Add a comprehensive API endpoint for user management with CRUD operations, authentication, and rate limiting",
  "application_name": "MyApp",
  "application_folder": "/home/ubuntu/deployments/user123/myapp",
  "action_operation": "MODIFY_CODE"
}
```

#### 📋 Request Parameters
- **message** (required): Natural language description of the code changes needed with detailed specifications
- **application_name** (required): Name of the application to modify (validated against database)
- **application_folder** (required): Full path to the application directory (validated for security)
- **action_operation** (optional): Specific operation type (defaults to "MODIFY_CODE", validated against allowed operations)

#### 🎯 Enhanced Context Loading
The agent automatically loads context from `/home/ubuntu/<PLTF_FOLDER>/shared/MODIFY_CODE_context.md` which includes:
- Application-specific configuration with environment variables
- User context and permissions with role-based access
- Git repository information with branch management
- Development guidelines and coding standards
- Security requirements and validation rules
- Testing procedures and quality assurance

#### 📡 Enhanced Streaming Response
```javascript
// JavaScript example for handling enhanced streaming response with error handling
const eventSource = new EventSource('/api/request_dev_ai_for_app', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Cache-Control': 'no-cache'
  },
  body: JSON.stringify(requestData)
});

eventSource.onmessage = function(event) {
  try {
    const data = JSON.parse(event.data);
    
    if (data.chunk) {
      console.log('Progress:', data.chunk);
      updateProgressUI(data.chunk);
    }
    
    if (data.done) {
      console.log('Completed:', data.success);
      if (data.success) {
        showSuccessMessage('Code modification completed successfully');
      } else {
        showErrorMessage('Code modification failed with return code: ' + data.returncode);
      }
      eventSource.close();
    }
    
    if (data.error) {
      console.error('Error:', data.error);
      showErrorMessage(data.error);
      eventSource.close();
    }
  } catch (e) {
    console.error('Failed to parse SSE data:', e);
  }
};

eventSource.onerror = function(event) {
  console.error('SSE connection error:', event);
  showErrorMessage('Connection to virtual developer lost');
  eventSource.close();
};
```

#### ⏱️ Enhanced Timeout Management
- **Duration**: 30 minutes (1800 seconds) with configurable limits
- **Graceful Termination**: SIGTERM followed by SIGKILL if needed with cleanup
- **Process Group Management**: Automatic process group termination for complete cleanup
- **Logging**: Timeout events logged with timestamps and process information
- **Resource Cleanup**: Memory and file handle cleanup on timeout
- **User Notification**: Real-time timeout warnings via streaming

### 🚀 AI Chat Operations Agent

**Endpoint**: `POST /api/request_ops_ai_for_app`

**Purpose**: Autonomous deployment operations and infrastructure management with comprehensive billing integration.

#### 🛠️ Enhanced Capabilities
- 🚀 **Advanced Deployment Management**: START, STOP, RESTART operations with validation
- 🏗️ **Infrastructure Operations**: Server and resource management with capacity monitoring
- 📊 **Comprehensive Monitoring**: Application status, health checks, and performance metrics
- 📋 **Advanced Log Management**: Real-time log viewing, analysis, and correlation
- 🔍 **Process Status**: PS command execution, monitoring, and resource tracking
- 🔧 **Intelligent Troubleshooting**: Automated problem diagnosis and resolution suggestions
- 💰 **Billing Integration**: Automatic cost tracking and activity recording
- 🖥️ **Multi-Server Support**: Intelligent server allocation and load balancing

#### 📝 Enhanced Request Format
```json
{
  "message": "[START] Start the application with full monitoring, logging, and health checks",
  "application_name": "MyApp",
  "application_folder": "/home/ubuntu/deployments/user123/myapp",
  "action_operation": "START"
}
```

#### 📋 Request Parameters
- **message** (required): Natural language description or command with operation context
- **application_name** (required): Name of the application to manage (validated against database)
- **application_folder** (required): Full path to the application directory (security validated)
- **action_operation** (optional): Specific operation (START, STOP, RESTART, PS, LOGS) with validation

#### 🎯 Enhanced Context-Aware Operations

The agent loads different context files based on the operation with dynamic variable substitution:

**Available Context Files**:
- `START_context.md` - Application startup procedures with environment setup
- `STOP_context.md` - Graceful shutdown procedures with cleanup
- `RESTART_context.md` - Restart and recovery procedures with validation
- `PS_context.md` - Process status monitoring with performance metrics
- `LOGS_context.md` - Log analysis and monitoring with correlation

**Enhanced Fallback Mode**: If no specific context is found, the agent operates in intelligent Q&A mode with:
- General assistance and troubleshooting guidance
- Best practices recommendations
- Error diagnosis and resolution suggestions
- Performance optimization tips
- Security recommendations

#### 💰 Enhanced Billing Integration
Comprehensive billing activity recording for:
- **START** operations: Records application startup time, server allocation, and resource usage
- **STOP** operations: Calculates duration, final costs, and resource deallocation
- **Cost Calculation**: Based on application-specific rates from `application_costs` table with prorated billing
- **Activity Logging**: Detailed logs in `billing_activities.log` with timestamps and user context
- **Invoice Generation**: Automatic monthly invoice creation with PDF export
- **Payment Tracking**: Integration with payment modes and transaction history

### 📡 Enhanced Streaming API

Both agents support advanced real-time streaming responses using Server-Sent Events (SSE) with enhanced features.

#### 🔌 Enhanced Response Format
```
data: {"chunk": "Starting AI Chat Developer session with enhanced logging..."}

data: {"chunk": "Found AI Chat at: /home/ubuntu/.local/bin/qchat", "timestamp": "2026-01-15T10:30:00Z"}

data: {"chunk": "Loading context from MODIFY_CODE_context.md", "context_size": 2048}

data: {"chunk": "Executing AI Chat command with timeout management...", "timeout": 1800}

data: {"chunk": "Code modification completed successfully", "files_modified": 3}

data: {"done": true, "success": true, "returncode": 0, "duration": 45.2, "files_changed": ["app.py", "models.py", "tests.py"]}
```

#### 📋 Enhanced Response Fields
- **chunk**: Progress message or output line with detailed information
- **timestamp**: ISO 8601 timestamp for each message
- **context_size**: Size of loaded context in bytes
- **timeout**: Remaining timeout in seconds
- **files_modified**: Number of files changed (for developer agent)
- **done**: Boolean indicating completion
- **success**: Boolean indicating success/failure
- **returncode**: Process exit code
- **duration**: Total execution time in seconds
- **files_changed**: Array of modified files
- **error**: Detailed error message if operation failed
- **warning**: Non-fatal warnings and recommendations

#### 🌐 Enhanced HTTP Headers
```
Content-Type: text/event-stream
Cache-Control: no-cache
X-Accel-Buffering: no
Connection: keep-alive
X-Agent-Type: developer|operations
X-Timeout: 1800
X-Context-Loaded: true
```

### 🎯 Context-Aware Prompts

The virtual agents use enhanced context-aware prompts loaded from the `shared/` directory with advanced features:

#### 📁 Enhanced Context File Structure
```
shared/
├── MODIFY_CODE_context.md    # Developer agent context with coding standards
├── START_context.md          # Start operation context with environment setup
├── STOP_context.md           # Stop operation context with cleanup procedures
├── RESTART_context.md        # Restart operation context with validation
├── PS_context.md             # Process status context with monitoring
├── LOGS_context.md           # Log analysis context with correlation
└── README.md                 # Context file documentation and guidelines
```

#### 🔄 Enhanced Variable Substitution
Context files support dynamic variable replacement with validation:
- `{USER_ID}` - Current user ID (validated against database)
- `{USER_NAME}` - User's full name (sanitized for security)
- `{USER_EMAIL}` - User's email address (validated format)
- `{APPLICATION_FOLDER}` - Application directory path (security validated)
- `{APPLICATION_NAME}` - Application name (validated against database)
- `{TAIL_LINES}` - Number of log lines to display (default: 100, max: 1000)
- `{TIMESTAMP}` - Current timestamp in ISO 8601 format
- `{SERVER_ID}` - Allocated server ID for deployment
- `{GIT_BRANCH}` - Generated Git branch name for modifications

#### 🛡️ Enhanced Security Features
- **Path Traversal Protection**: Sanitizes action names to prevent directory traversal attacks
- **Input Validation**: Comprehensive validation of all user inputs before processing
- **Permission Checks**: Verifies user permissions for operations with role-based access
- **Process Isolation**: Uses process groups for secure execution with resource limits
- **Audit Logging**: Comprehensive logging of all operations for security monitoring
- **Rate Limiting**: Prevents abuse with configurable rate limits per user
- **Content Filtering**: Filters potentially malicious content from prompts and responses

### 💰 Billing Integration

#### 📊 Enhanced Automatic Activity Recording
```sql
-- Enhanced billing activities table structure with additional fields
CREATE TABLE billing_activities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    application_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    started_at TIMESTAMP,
    stopped_at TIMESTAMP,
    duration_seconds INTEGER,
    cost_amount REAL,
    server_id INTEGER,
    resource_usage TEXT,  -- JSON field for resource metrics
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id),
    FOREIGN KEY (application_id) REFERENCES applications (id),
    FOREIGN KEY (server_id) REFERENCES servers (id)
);
```

#### 💳 Enhanced Cost Calculation
- **START Action**: Records start time, server allocation, and initial resource usage
- **STOP Action**: Records stop time, calculates total duration, resource usage, and final cost
- **Rate Lookup**: Uses `application_costs` table for per-day rates with tier-based pricing
- **Prorated Billing**: Calculates costs based on actual usage time with minute-level precision
- **Resource-Based Pricing**: Additional costs based on CPU, memory, and storage usage
- **Multi-Server Pricing**: Different rates based on server type and location

#### 📊 Enhanced Billing Reports
- **Usage Summary**: Detailed breakdown by application, user, and time period
- **Cost Analysis**: Trends, forecasting, and optimization recommendations
- **Invoice Generation**: Automated monthly invoices with PDF export and email delivery
- **Payment Integration**: Support for multiple payment methods and automatic billing
- **Audit Trail**: Complete history of all billing activities and adjustments

### 🔧 Error Handling

#### ⚠️ Enhanced Error Scenarios
1. **Authentication Failure**: Missing or invalid session with detailed error codes
2. **Permission Denied**: User lacks required permissions with specific permission requirements
3. **Application Not Found**: Invalid application name or path with suggestions
4. **Timeout Exceeded**: Operation exceeds 30-minute limit with partial results
5. **Process Failure**: AI Chat execution fails with diagnostic information
6. **Context Loading Error**: Missing or invalid context files with fallback options
7. **Network Issues**: Server connectivity problems with retry mechanisms
8. **Resource Constraints**: Insufficient system resources with recommendations
9. **Security Violations**: Blocked operations due to security policies
10. **Billing Errors**: Payment or cost calculation issues with resolution steps

#### 🛠️ Enhanced Error Response Format
```json
{
  "error": "Authentication required",
  "code": 401,
  "details": "User session not found or expired",
  "timestamp": "2026-01-15T10:30:00Z",
  "request_id": "req_123456789",
  "suggestions": [
    "Please log in again",
    "Check if your session has expired",
    "Verify your authentication credentials"
  ],
  "documentation": "https://docs.swautomorph.com/auth-errors"
}
```

#### 🔄 Enhanced Retry Mechanisms
- **Database Locks**: Automatic retry with exponential backoff and jitter
- **Process Failures**: Graceful cleanup and error reporting with diagnostics
- **Network Issues**: Connection timeout handling with circuit breaker pattern
- **Resource Constraints**: Memory and CPU limit management with scaling
- **Context Loading**: Fallback to default context with user notification
- **Billing Operations**: Transaction retry with consistency checks

---

## Français

<div class="center">
🚀 **Agents IA Virtuels pour la Gestion Autonome d'Applications** 🌟
</div>

### 📋 Table des Matières
- [🌟 Aperçu](#aperçu)
- [🔧 Agent Développeur AI Chat](#agent-développeur-q-chat)
- [🚀 Agent Opérations AI Chat](#agent-opérations-q-chat)
- [📡 API de Streaming Améliorée](#api-de-streaming-améliorée)
- [🎯 Prompts Contextuels](#prompts-contextuels)
- [💰 Intégration Facturation](#intégration-facturation)
- [🔧 Gestion d'Erreurs](#gestion-derreurs)
- [🛡️ Fonctionnalités de Sécurité](#fonctionnalités-de-sécurité)

### 🌟 Aperçu

AI-SwAutoMorph fournit deux agents IA virtuels spécialisés conçus pour la gestion autonome d'applications avec fonctionnalités améliorées :

- **🔧 Agent Développeur AI Chat** : Modification de code, développement de fonctionnalités et amélioration d'applications
- **🚀 Agent Opérations AI Chat** : Opérations de déploiement, gestion d'infrastructure et cycle de vie des applications

Les deux agents supportent :
- ⚡ **Réponses en streaming améliorées** avec Server-Sent Events et suivi de progression temps réel
- 🎯 **Prompts contextuels** depuis des fichiers de configuration partagés avec substitution de variables dynamique
- ⏱️ **Gestion avancée des timeouts** avec nettoyage gracieux (30 minutes) et terminaison de groupe de processus
- 💰 **Facturation complète** avec enregistrement d'activité et mesure de temps précise
- 🔄 **Modes de fallback intelligents** pour scénarios d'erreur et actions invalides
- 🔒 **Sécurité renforcée** avec validation d'entrée, protection contre traversée de chemin et journalisation complète
- 📝 **Journalisation détaillée** avec suivi de génération de prompts et diagnostics d'erreur

### 🔧 Agent Développeur AI Chat

**Point de terminaison** : `POST /api/request_dev_ai_for_app`

**Objectif** : Modification autonome de code et développement de fonctionnalités utilisant des instructions en langage naturel avec intégration Git avancée.

#### 🛠️ Capacités Améliorées
- 💻 **Analyse de Code Avancée** : Comprend la structure de la base de code existante avec cartographie des dépendances
- ⚡ **Développement de Fonctionnalités** : Ajoute de nouvelles fonctionnalités basées sur les exigences avec validation
- 🔌 **Création d'API** : Génère de nouveaux points de terminaison REST et gestionnaires avec documentation
- 🔄 **Refactorisation de Code** : Améliore la qualité et les performances du code avec métriques
- 🐛 **Résolution de Bugs** : Identifie et corrige les problèmes de code avec tests
- 🌿 **Intégration Git Améliorée** : Crée des branches avec format `{user_id}-automorph-{app_name}-{timestamp}`
- 📝 **Journalisation de Prompts** : Sauvegarde les prompts générés vers `dev_prompt_generated.txt` pour débogage
- 🔒 **Validation de Sécurité** : Protection contre traversée de chemin et sanitisation d'entrée

### 🚀 Agent Opérations AI Chat

**Point de terminaison** : `POST /api/request_ops_ai_for_app`

**Objectif** : Opérations de déploiement autonomes et gestion d'infrastructure avec intégration de facturation complète.

#### 🛠️ Capacités Améliorées
- 🚀 **Gestion de Déploiement Avancée** : Opérations START, STOP, RESTART avec validation
- 🏗️ **Opérations d'Infrastructure** : Gestion des serveurs et ressources avec surveillance de capacité
- 📊 **Surveillance Complète** : Statut d'application, vérifications de santé et métriques de performance
- 📋 **Gestion de Logs Avancée** : Visualisation de logs temps réel, analyse et corrélation
- 🔍 **Statut des Processus** : Exécution de commande PS, surveillance et suivi des ressources
- 🔧 **Dépannage Intelligent** : Diagnostic automatisé des problèmes et suggestions de résolution
- 💰 **Intégration Facturation** : Suivi automatique des coûts et enregistrement d'activité
- 🖥️ **Support Multi-Serveurs** : Allocation intelligente de serveur et équilibrage de charge

### 💰 Intégration Facturation

#### 📊 Enregistrement Automatique d'Activité Amélioré
- **Action START** : Enregistre l'heure de début, allocation de serveur et utilisation initiale des ressources
- **Action STOP** : Enregistre l'heure d'arrêt, calcule la durée totale, utilisation des ressources et coût final
- **Recherche de Tarif** : Utilise la table `application_costs` pour tarifs par jour avec tarification par niveaux
- **Facturation Proratisée** : Calcule les coûts basés sur le temps d'utilisation réel avec précision à la minute
- **Tarification Basée sur Ressources** : Coûts additionnels basés sur l'utilisation CPU, mémoire et stockage
- **Tarification Multi-Serveurs** : Tarifs différents basés sur le type et localisation du serveur

### 🔧 Gestion d'Erreurs

#### ⚠️ Scénarios d'Erreur Améliorés
1. **Échec d'Authentification** : Session manquante ou invalide avec codes d'erreur détaillés
2. **Permission Refusée** : L'utilisateur manque des permissions requises avec exigences de permission spécifiques
3. **Application Non Trouvée** : Nom d'application ou chemin invalide avec suggestions
4. **Timeout Dépassé** : L'opération dépasse la limite de 30 minutes avec résultats partiels
5. **Échec de Processus** : L'exécution AI Chat échoue avec informations de diagnostic
6. **Erreur de Chargement de Contexte** : Fichiers de contexte manquants ou invalides avec options de fallback
7. **Problèmes Réseau** : Problèmes de connectivité serveur avec mécanismes de retry
8. **Contraintes de Ressources** : Ressources système insuffisantes avec recommandations
9. **Violations de Sécurité** : Opérations bloquées dues aux politiques de sécurité
10. **Erreurs de Facturation** : Problèmes de paiement ou calcul de coût avec étapes de résolution