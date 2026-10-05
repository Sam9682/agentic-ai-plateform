# Serverless Orchestration

## English

## Overview

The Serverless Orchestration module provides on-demand, ephemeral Docker container execution as a managed service. Users submit jobs specifying a container image and command; the platform handles scheduling, execution, security isolation, timeout enforcement, log capture, and result storage — all without requiring users to manage their own infrastructure.

---

## Architecture

```
┌───────────────┐        ┌────────────────┐       ┌──────────────────┐
│   REST API    │──────▶│  PostgreSQL    │◀──────│  Worker Service  │
│  /api/jobs    │        │  (Job Queue)   │       │  (Poll & Execute)│
└───────────────┘        └────────────────┘       └────────┬─────────┘
                                                          │
                                                          ▼
                                                 ┌───────────────────┐
                                                 │ Container Runtime │
                                                 │ (Docker / Podman) │
                                                 └───────────────────┘
```

### Components

|         Component        |                                        Role                                             |
|--------------------------|-----------------------------------------------------------------------------------------|
| **REST API**             | Accepts job submissions, returns status and results                                     |
| **PostgreSQL Job Queue** | Stores jobs with state machine (pending → running → completed/failed/timeout/cancelled) |
| **Worker Service**       | Polls the queue, claims jobs, executes containers, captures output                      |
| **Container Runtime**    | Abstract layer supporting Docker and Podman with full security hardening                |

---

## Job Lifecycle

1. **Submission** — User sends a `POST /api/jobs` request with image, command, optional env vars, and timeout.
2. **Queued** — Job is stored in PostgreSQL with status `pending`.
3. **Claimed** — A worker polls the queue using `FOR UPDATE SKIP LOCKED` (no contention between workers) and sets status to `running`.
4. **Execution** — The worker pulls the image, starts the container with security constraints, and waits for completion.
5. **Completion** — Stdout/stderr are captured and stored. Job is marked `completed`, `failed`, or `timeout`.
6. **Cancellation** — Users can cancel `pending` or `running` jobs via `POST /api/jobs/<id>/cancel`. Running containers are stopped gracefully.

### State Diagram

```
pending ──▶ running ──▶ completed
   │            │
   │            ├──▶ failed
   │            │
   │            └──▶ timeout
   │
   └──▶ cancelled
```

---

## Security Model

Every container runs with strict isolation:

| Constraint | Description |
|------------|-------------|
| `--read-only` | Root filesystem is mounted read-only |
| `--user nobody` | Runs as unprivileged user |
| `--cap-drop ALL` | All Linux capabilities are dropped |
| `--network none` | No network access by default |
| `--security-opt no-new-privileges` | Prevents privilege escalation |
| `--pids-limit 256` | Limits the number of processes |
| `--memory` | Memory limit (default 512 MB) |
| `--cpus` | CPU limit (default 1 core) |
| **Registry Whitelist** | Only approved registries are allowed (docker.io, ghcr.io, etc.) |

---

## API Reference

### Submit a Job

```http
POST /api/jobs
Content-Type: application/json

{
  "image": "python:3.11-slim",
  "command": ["python", "-c", "print('Hello from serverless!')"],
  "env": {"MY_VAR": "value"},
  "timeout": 60
}
```

**Response (201 Created):**
```json
{
  "job_id": "a1b2c3d4-e5f6-...",
  "status": "pending",
  "message": "Job submitted successfully"
}
```

### List Jobs

```http
GET /api/jobs?page=1&per_page=20&status=completed
```

Returns paginated job list with filtering by status.

### Get Job Status

```http
GET /api/jobs/<job_id>
```

Returns current job metadata including status, timestamps, and worker assignment.

### Get Job Result

```http
GET /api/jobs/<job_id>/result
```

Returns stdout, stderr, and exit code for completed jobs.

### Cancel a Job

```http
POST /api/jobs/<job_id>/cancel
```

Cancels a pending or running job. Running containers are stopped gracefully.

### Job Metrics (Admin only)

```http
GET /api/jobs/metrics
```

Returns aggregated statistics: total jobs, jobs by status, average execution time.

---

## Configuration

Default settings are defined in `src/serverless/config.py` (the `SERVERLESS_CONFIG` dict the worker loads). Operator-facing runtime overrides live in `conf/serverless.ini` and take effect on worker restart. The container runtime type (`runc` default, `kata` optional) is resolved separately from the database `configuration` table, read once at worker startup (a restart is required to change it).

Default values:

|         Parameter        |                 Default                  |       Description         |
|--------------------------|------------------------------------------|---------------------------|
| `registry_whitelist`     | docker.io, ghcr.io, registry.example.com | Approved image registries |
| `default_timeout`        | 300s                                     | Default job timeout       |
| `max_timeout`            | 3600s                                    | Maximum allowed timeout   |
| `default_memory_limit`   | 512m                                     | Container memory limit    |
| `default_cpu_limit`      | 1                                        | Container CPU limit       |
| `max_concurrent_jobs`    | 100                                      | Maximum concurrent jobs   |
| `log_retention_days`     | 30                                       | Days to retain job logs   |
| `poll_interval`          | 0.5s                                     | Queue polling interval    |
| `container_stop_timeout` | 10s                                      | Graceful stop timeout     |

---

## Worker Service

The worker runs as a standalone process that can be scaled horizontally:

```bash
python -m src.serverless.worker
```

### Environment Variables

|       Variable      |           Default         |        Description       |
|---------------------|---------------------------|--------------------------|
| `WORKER_ID`         | `worker-<hostname>-<pid>` | Unique worker identifier |
| `POSTGRES_HOST`     | localhost                 | Database host            |
| `POSTGRES_PORT`     | 5432                      | Database port            |
| `POSTGRES_DB`       | ai_swautomorph            | Database name            |
| `POSTGRES_USER`     | swautomorph               | Database user            |
| `POSTGRES_PASSWORD` | swautomorph_password      | Database password        |

### Features

- **Horizontal scaling** — Multiple workers can run concurrently; `SKIP LOCKED` ensures no duplicate job processing.
- **Graceful shutdown** — Handles `SIGTERM` and `SIGINT` for clean shutdown.
- **Automatic log cleanup** — Removes old logs/jobs every 24 hours based on `log_retention_days`.
- **Rotating log files** — Worker logs are rotated at 10 MB with 5 backup files.
- **Runtime auto-detection** — Automatically detects Docker or Podman on the host.

---

## GPU-Accelerated Jobs

When a server has **MIG Shared GPU** enabled, serverless jobs can access isolated GPU partitions via the `--gpus` Docker flag. This enables:

- **AI/ML Inference** — Run model inference on dedicated GPU slices
- **Training Jobs** — Execute training workloads with guaranteed GPU memory
- **Multi-tenant GPU** — Each job gets its own isolated MIG instance

### GPU Job Flow

1. Admin enables MIG shared GPU on a server (via `/api/servers/<id>/gpu/enabled`)
2. Admin creates MIG instances (e.g., 1g.10gb partitions)
3. Workers on that server can assign GPU slices to containers
4. Each container sees only its allocated GPU partition

> **Note**: GPU access requires the server to have `shared_gpu_enabled = true` and active MIG instances. See the [MIG Shared GPU](#) documentation for setup instructions.

---

## Use Cases

- **CI/CD Pipelines** — Run build, test, and linting steps in isolated containers.
- **Data Processing** — Execute batch data transformations without dedicated infrastructure.
- **Scheduled Tasks** — Run periodic jobs (cron-like) with full isolation and resource limits.
- **AI/ML Workloads** — Submit model training or inference jobs with GPU acceleration via MIG partitions.
- **Code Execution** — Safely run user-submitted code in sandboxed containers.
- **GPU Inference** — Run AI model inference on isolated GPU slices without managing GPU infrastructure.

---

## Français

## Vue d'ensemble

Le module d'Orchestration Serverless fournit une exécution de conteneurs Docker à la demande, éphémère et gérée. Les utilisateurs soumettent des jobs en spécifiant une image conteneur et une commande ; la plateforme gère la planification, l'exécution, l'isolation de sécurité, l'application des délais, la capture des logs et le stockage des résultats — le tout sans que les utilisateurs aient besoin de gérer leur propre infrastructure.

---

## Architecture

```
┌───────────────┐       ┌────────────────┐       ┌──────────────────┐
│   API REST    │──────▶│  PostgreSQL    │◀──────│  Service Worker  │
│  /api/jobs    │       │  (File d'att.) │       │  (Poll & Exécute)│
└───────────────┘       └────────────────┘       └────────┬─────────┘
                                                          │
                                                          ▼
                                                 ┌──────────────────┐
                                                 │  Runtime Conteneur│
                                                 │ (Docker / Podman) │
                                                 └──────────────────┘
```

### Composants

| Composant | Rôle |
|-----------|------|
| **API REST** | Accepte les soumissions de jobs, retourne le statut et les résultats |
| **File d'attente PostgreSQL** | Stocke les jobs avec machine d'état (pending → running → completed/failed/timeout/cancelled) |
| **Service Worker** | Interroge la file, réclame les jobs, exécute les conteneurs, capture la sortie |
| **Runtime Conteneur** | Couche abstraite supportant Docker et Podman avec sécurisation complète |

---

## Cycle de vie d'un Job

1. **Soumission** — L'utilisateur envoie une requête `POST /api/jobs` avec l'image, la commande, les variables d'env optionnelles et le timeout.
2. **En file d'attente** — Le job est stocké dans PostgreSQL avec le statut `pending`.
3. **Réclamé** — Un worker interroge la file via `FOR UPDATE SKIP LOCKED` et passe le statut à `running`.
4. **Exécution** — Le worker télécharge l'image, démarre le conteneur avec les contraintes de sécurité et attend la fin.
5. **Terminaison** — Stdout/stderr sont capturés et stockés. Le job est marqué `completed`, `failed` ou `timeout`.
6. **Annulation** — Les utilisateurs peuvent annuler les jobs `pending` ou `running` via `POST /api/jobs/<id>/cancel`.

---

## Modèle de sécurité

Chaque conteneur s'exécute avec une isolation stricte :

| Contrainte | Description |
|------------|-------------|
| `--read-only`                      | Système de fichiers racine en lecture seule     |
| `--user nobody`                    | Exécution en tant qu'utilisateur non privilégié |
| `--cap-drop ALL`                   | Toutes les capacités Linux sont retirées        |
| `--network none`                   | Pas d'accès réseau par défaut                   |
| `--security-opt no-new-privileges` | Empêche l'escalade de privilèges                |
| `--pids-limit 256`                 | Limite le nombre de processus                   |
| `--memory`                         | Limite mémoire (défaut 512 Mo)                  |
| `--cpus`                           | Limite CPU (défaut 1 cœur)                      |
| **Liste blanche de registres**     | Seuls les registres approuvés sont autorisés    |

---

## Référence API

### Soumettre un Job

```http
POST /api/jobs
Content-Type: application/json

{
  "image": "python:3.11-slim",
  "command": ["python", "-c", "print('Bonjour depuis serverless!')"],
  "env": {"MA_VAR": "valeur"},
  "timeout": 60
}
```

### Lister les Jobs

```http
GET /api/jobs?page=1&per_page=20&status=completed
```

### Obtenir le statut d'un Job

```http
GET /api/jobs/<job_id>
```

### Obtenir le résultat d'un Job

```http
GET /api/jobs/<job_id>/result
```

### Annuler un Job

```http
POST /api/jobs/<job_id>/cancel
```

### Métriques des Jobs (Admin uniquement)

```http
GET /api/jobs/metrics
```

---

## Cas d'utilisation

- **Pipelines CI/CD** — Exécuter des étapes de build, test et linting dans des conteneurs isolés.
- **Traitement de données** — Exécuter des transformations batch sans infrastructure dédiée.
- **Tâches planifiées** — Exécuter des jobs périodiques avec isolation complète et limites de ressources.
- **Charges IA/ML** — Soumettre des jobs d'entraînement ou d'inférence avec accélération GPU via partitions MIG.
- **Exécution de code** — Exécuter en toute sécurité du code soumis par l'utilisateur dans des conteneurs sandboxés.
- **Inférence GPU** — Exécuter l'inférence de modèles IA sur des tranches GPU isolées sans gérer l'infrastructure GPU.
