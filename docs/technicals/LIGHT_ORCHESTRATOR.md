# App Orchestrator - Documentation

## Vue d'ensemble

Le App Orchestrator est un système d'orchestration simple et maintenable pour SwAutoMorph qui permet de gérer des applications multi-instances (HA) sans la complexité de Kubernetes.

## Fonctionnalités

### 🎯 Services et Réplicas
- Chaque application = service logique avec N instances (replicas)
- Chaque instance = container Docker sur un serveur
- Exemple : `ai-staticwebsite` avec `replicas=2` → 2 containers

### 🔄 État Désiré vs État Réel
- Stockage de l'état désiré : service, image, replicas, ports
- Vérification automatique de l'état réel via `docker ps`
- Réconciliation automatique :
  - Création des containers manquants
  - Redémarrage des containers arrêtés

### 📊 Scheduler Léger
- Sélection automatique du serveur avec le moins d'instances
- Respect des capacités serveur (`SERVER_CAPACITY_USER_MAX`, `SERVER_CAPACITY_APPLI_MAX`)
- Pas de consensus complexe, scheduler central dans SwAutoMorph

### 🏥 Health-check et Auto-healing
- Chaque instance expose un endpoint `/health`
- Si DOWN, suppression du container et recréation ailleurs si nécessaire
- Monitoring continu de la santé des instances

### 🌐 Nginx Dynamique
- Génération automatique des upstreams par service
- Load balancing `least_conn`
- Reload automatique Nginx après ajout/suppression d'instances
- Support des sticky sessions (optionnel)

## Architecture

### Base de Données

#### Table `services`
```sql
CREATE TABLE services (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    image TEXT NOT NULL,
    desired_replicas INTEGER DEFAULT 1,
    ports TEXT,  -- JSON: {"80": "8080", "443": "8443"}
    environment TEXT,  -- JSON: {"ENV_VAR": "value"}
    volumes TEXT,  -- JSON: ["/host:/container"]
    health_check_path TEXT DEFAULT '/health',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### Table `instances`
```sql
CREATE TABLE instances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_name TEXT NOT NULL,
    instance_id TEXT NOT NULL,  -- service_name-replica-N
    server_id INTEGER NOT NULL,
    container_id TEXT,
    status TEXT DEFAULT 'pending',  -- pending, running, failed, stopped
    port INTEGER,
    health_status TEXT DEFAULT 'unknown',  -- healthy, unhealthy, unknown
    last_health_check TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (server_id) REFERENCES servers (id),
    FOREIGN KEY (service_name) REFERENCES services (name)
);
```

## Utilisation

### Interface Web

Accédez à l'interface d'administration → Configuration → 🎯 App Orchestrator

#### Créer un Service
1. Cliquez sur "Create Service"
2. Remplissez les informations :
   - **Service Name** : nom unique du service
   - **Docker Image** : image Docker à utiliser
   - **Desired Replicas** : nombre d'instances souhaitées
   - **Port Mappings** : JSON des mappings de ports
   - **Environment Variables** : JSON des variables d'environnement
   - **Volumes** : JSON array des volumes
   - **Health Check Path** : endpoint de health check

#### Gérer les Services
- **Scale Up/Down** : boutons + et - pour ajuster les replicas
- **Delete** : supprimer un service et toutes ses instances
- **Status** : voir l'état en temps réel des services et instances

### CLI

#### Initialisation
```bash
python3 ./scripts/orchestrator_cli.py init
```

#### Créer un Service
```bash
python3 ./scripts/orchestrator_cli.py create my-app nginx:alpine \
    --replicas 2 \
    --ports '{"80": "8080"}' \
    --environment '{"ENV_VAR": "value"}' \
    --volumes '["/host/path:/container/path"]' \
    --health-check "/health"
```

#### Lister les Services
```bash
python3 ./scripts/orchestrator_cli.py list
```

#### Voir les Détails d'un Service
```bash
python3 ./scripts/orchestrator_cli.py show my-app
```

#### Scaler un Service
```bash
python3 ./scripts/orchestrator_cli.py scale my-app 3
```

#### Supprimer un Service
```bash
python3 ./scripts/orchestrator_cli.py delete my-app
```

#### Générer la Configuration Nginx
```bash
python3 ./scripts/orchestrator_cli.py nginx --output /etc/nginx/conf.d/orchestrator-upstreams.conf
```

#### Recharger Nginx
```bash
python3 ./scripts/orchestrator_cli.py reload
```

### API REST

#### Lister les Services
```bash
curl https://www.swautomorph.com/api/orchestrator/services
```

#### Créer un Service
```bash
curl -X POST https://www.swautomorph.com/api/orchestrator/services \
  -H "Content-Type: application/json" \
  -H "Cookie: session=your-session-cookie" \
  -d '{
    "name": "my-app",
    "image": "nginx:alpine",
    "desired_replicas": 2,
    "ports": {"80": "8080"},
    "environment": {"ENV_VAR": "value"},
    "volumes": ["/host:/container"],
    "health_check_path": "/health"
  }'
```

#### Scaler un Service
```bash
curl -X POST https://www.swautomorph.com/api/orchestrator/services/my-app/scale \
  -H "Content-Type: application/json" \
  -H "Cookie: session=your-session-cookie" \
  -d '{"replicas": 3}'
```

#### Supprimer un Service
```bash
curl -X DELETE https://www.swautomorph.com/api/orchestrator/services/my-app \
  -H "Cookie: session=your-session-cookie"
```

#### Statut de l'Orchestrateur
```bash
curl https://www.swautomorph.com/api/orchestrator/status
```

#### Générer la Configuration Nginx
```bash
curl https://www.swautomorph.com/api/orchestrator/nginx/config
```

#### Recharger Nginx
```bash
curl -X POST https://www.swautomorph.com/api/orchestrator/nginx/reload \
  -H "Cookie: session=your-session-cookie"
```

## Configuration Nginx

### Exemple de Configuration

```nginx
# Include orchestrator-generated upstreams
include /etc/nginx/conf.d/orchestrator-upstreams.conf;

server {
    listen 80;
    server_name my-app.swautomorph.com;
    
    location / {
        proxy_pass http://my-app;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Health check
        proxy_next_upstream error timeout invalid_header http_500 http_502 http_503 http_504;
        proxy_connect_timeout 5s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }
}
```

### Upstream Généré Automatiquement

```nginx
upstream my-app {
    least_conn;
    server 192.168.1.100:8001;
    server 192.168.1.101:8002;
}
```

## Monitoring et Maintenance

### Health Checks
- Exécutés automatiquement toutes les 30 secondes
- Endpoint configurable par service (défaut : `/health`)
- Instances unhealthy automatiquement supprimées des upstreams

### Réconciliation
- Boucle de réconciliation automatique toutes les 30 secondes
- Compare l'état désiré vs l'état réel
- Crée/supprime les instances selon les besoins

### Logs
- Logs d'orchestration dans les logs SwAutoMorph
- Logs Docker accessibles via `docker logs <container_id>`

## Exemples d'Usage

### Déploiement d'un Site Web Statique
```bash
./scripts/deploy_example_service.sh
```

### Application Web avec Base de Données
```bash
# Service web
python3 ./scripts/orchestrator_cli.py create webapp nginx:alpine \
    --replicas 3 \
    --ports '{"80": "8080"}' \
    --environment '{"DB_HOST": "db.internal"}' \
    --health-check "/api/health"

# Service base de données (1 replica pour éviter les conflits)
python3 ./scripts/orchestrator_cli.py create database postgres:13 \
    --replicas 1 \
    --ports '{"5432": "5432"}' \
    --environment '{"POSTGRES_DB": "myapp", "POSTGRES_USER": "user", "POSTGRES_PASSWORD": "pass"}' \
    --volumes '["/var/lib/postgresql/data:/var/lib/postgresql/data"]'
```

### Microservices
```bash
# API Gateway
python3 ./scripts/orchestrator_cli.py create api-gateway nginx:alpine \
    --replicas 2 \
    --ports '{"80": "8080", "443": "8443"}'

# Service utilisateurs
python3 ./scripts/orchestrator_cli.py create user-service node:16-alpine \
    --replicas 3 \
    --ports '{"3000": "3000"}' \
    --health-check "/users/health"

# Service commandes
python3 ./scripts/orchestrator_cli.py create order-service python:3.9-slim \
    --replicas 2 \
    --ports '{"5000": "5000"}' \
    --health-check "/orders/health"
```

## Limitations et Considérations

### Limitations Actuelles
- **Base de données** : SQLite locale, pas de réplication (pour l'instant)
- **Réseau** : Pas de réseau overlay, utilise l'IP des serveurs
- **Stockage** : Pas de stockage distribué, volumes locaux uniquement
- **Sécurité** : Pas de chiffrement inter-services par défaut

### Bonnes Pratiques
- **Health Checks** : Implémentez toujours des endpoints de santé
- **Graceful Shutdown** : Gérez les signaux SIGTERM dans vos applications
- **Logs** : Utilisez la sortie standard pour les logs
- **Configuration** : Utilisez les variables d'environnement pour la configuration
- **Monitoring** : Surveillez les métriques via l'interface web

### Évolutivité
- **Serveurs** : Ajoutez des serveurs via l'interface SwAutoMorph
- **Services** : Scalez horizontalement selon les besoins
- **Load Balancing** : Nginx gère automatiquement la répartition de charge

## Dépannage

### Service ne Démarre Pas
1. Vérifiez les logs : `docker logs <container_id>`
2. Vérifiez la disponibilité de l'image : `docker pull <image>`
3. Vérifiez les ports disponibles sur le serveur
4. Vérifiez les variables d'environnement et volumes

### Instances Unhealthy
1. Vérifiez l'endpoint de health check
2. Vérifiez les logs de l'application
3. Vérifiez la connectivité réseau
4. Redémarrez le service si nécessaire

### Nginx ne Route Pas
1. Vérifiez la génération des upstreams
2. Rechargez la configuration Nginx
3. Vérifiez les logs Nginx
4. Vérifiez la résolution DNS

### Performance
- Ajustez le nombre de replicas selon la charge
- Surveillez l'utilisation des serveurs
- Optimisez les health checks (fréquence, timeout)

## Roadmap

### Fonctionnalités Futures
- **Réplication DB** : Support de la réplication SQLite ou migration vers PostgreSQL
- **Service Discovery** : DNS automatique pour les services
- **Secrets Management** : Gestion sécurisée des secrets
- **Metrics** : Intégration Prometheus/Grafana
- **Rolling Updates** : Déploiements sans interruption
- **Auto-scaling** : Scaling automatique basé sur les métriques

### Intégrations
- **CI/CD** : Hooks pour les pipelines de déploiement
- **Monitoring** : Alertes et notifications
- **Backup** : Sauvegarde automatique des volumes
- **Security** : Scanning des images, policies réseau