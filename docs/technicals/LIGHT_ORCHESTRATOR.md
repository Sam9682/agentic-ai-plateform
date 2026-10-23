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

### 🌐 Reverse Proxy Traefik
- Traefik v3.1 est le **point d'entrée HTTP/HTTPS unique** (propriétaire de `:80` et `:443`) ; nginx et le WAF ModSecurity + OWASP CRS ont été retirés
- Découverte automatique des routes via le **Docker label provider** (`exposedByDefault=false`) et le **file provider** (surveillance de `traefik/dynamic/`)
- Load balancing géré par Traefik ; les conteneurs rejoignent le réseau Docker externe `swautomorph-shared`
- Routage par préfixe : chaque application est exposée sous `/{user}/{app}` et le middleware **StripPrefix** retire le préfixe avant de transmettre la requête au conteneur
- Pas de réécriture `sub_filter` du corps des réponses HTML/CSS/JS : les applications sont **path-aware** et émettent elles-mêmes leurs URLs préfixées via la variable d'environnement `BASE_PATH = /{user}/{app}/` (base href ou équivalent public-path du framework)
- Les WebSockets et les timeouts proxy (connect 30s, read/send 60s) sont conservés ; aucune découverte de ports via `docker ps` (les ports sont connus au moment du déploiement)

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

#### Synchroniser les Routes Traefik
```bash
# Réconcilie les fichiers de configuration dynamique Traefik (traefik/dynamic/)
# à partir de la base de données
python3 ./scripts/sync_reverse_proxy.py
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

#### Synchroniser les Routes Traefik
```bash
curl -X POST https://www.swautomorph.com/api/nginx/sync \
  -H "Cookie: session=your-session-cookie"
```

## Configuration Traefik

Traefik v3.1 est le point d'entrée HTTP/HTTPS unique. Il remplace nginx (et le WAF ModSecurity, retiré). Le routage est découvert automatiquement :

- **Docker label provider** (`exposedByDefault=false`) : les conteneurs d'application portent des labels Traefik posés au moment de la création du conteneur (dans le `docker-compose.yml` généré par application).
- **File provider** : Traefik surveille `traefik/dynamic/` et applique à chaud les fichiers de route par application (`app-{user}-{app}.yml`), la configuration TLS (`tls.yml`) et les domaines secondaires (`secondary-domains.yml`). Aucune étape de validation/reload de type `nginx -t` n'est nécessaire.

Les conteneurs d'application et Traefik communiquent via le réseau Docker externe `swautomorph-shared`.

### Exemple de route (labels Docker)

```yaml
labels:
  - "traefik.enable=true"
  - "traefik.docker.network=swautomorph-shared"
  # Routeur : host + préfixe par application
  - "traefik.http.routers.admin-my-app.rule=Host(`softfluid.fr`) && PathPrefix(`/admin/my-app`)"
  - "traefik.http.routers.admin-my-app.entrypoints=websecure"
  - "traefik.http.routers.admin-my-app.tls=true"
  - "traefik.http.routers.admin-my-app.middlewares=admin-my-app-strip@docker"
  # StripPrefix : retire /admin/my-app avant de transmettre à l'app
  - "traefik.http.middlewares.admin-my-app-strip.stripprefix.prefixes=/admin/my-app"
  # Service : port HTTP interne du conteneur (connu au déploiement, pas via docker ps)
  - "traefik.http.services.admin-my-app.loadbalancer.server.port=5000"
```

### Exemple de route équivalente (file provider)

```yaml
# traefik/dynamic/app-admin-my-app.yml
http:
  routers:
    admin-my-app:
      rule: "Host(`softfluid.fr`) && PathPrefix(`/admin/my-app`)"
      entryPoints: ["websecure"]
      service: "admin-my-app"
      middlewares: ["admin-my-app-strip"]
      tls: {}
  middlewares:
    admin-my-app-strip:
      stripPrefix:
        prefixes: ["/admin/my-app"]
  services:
    admin-my-app:
      loadBalancer:
        serversTransport: app-transport
        servers:
          - url: "http://admin-my-app:5000"
  serversTransports:
    app-transport:
      forwardingTimeouts:
        dialTimeout: "30s"            # connect (anciennement proxy_connect_timeout 30s)
        responseHeaderTimeout: "60s"  # read (anciennement proxy_read_timeout 60s)
```

### Applications path-aware (remplacement de `sub_filter`)

La réécriture `sub_filter` du corps des réponses n'existe plus. La plateforme injecte `BASE_PATH = /{user}/{app}/` comme variable d'environnement dans le conteneur ; l'application émet ses URLs d'assets et de liens sous ce préfixe (via `<base href>` ou l'équivalent public-path de son framework). Le middleware StripPrefix retire `/{user}/{app}` avant que la requête n'atteigne l'application, de sorte que celle-ci voit toujours des chemins relatifs à la racine en interne.

## Monitoring et Maintenance

### Health Checks
- Exécutés automatiquement toutes les 30 secondes
- Endpoint configurable par service (défaut : `/health`)
- Instances unhealthy automatiquement retirées du routage

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
- **Load Balancing** : Traefik gère automatiquement la répartition de charge

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

### Traefik ne Route Pas
1. Vérifiez que le fichier de route existe dans `traefik/dynamic/` (ou que le conteneur porte bien `traefik.enable=true` et ses labels de routeur)
2. Vérifiez que le conteneur d'application a rejoint le réseau `swautomorph-shared`
3. Consultez les logs Traefik (`docker logs <pltf>-traefik`)
4. Vérifiez la résolution DNS et le certificat TLS du domaine

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