# Platform Overview

Agentic-AI-Powered Store (a.k.a. AI-SwAutoMorph) is a centralized application deployment and management platform for both humans and GenAI agents. It automates clone/build/run lifecycles, SSO authentication, and multi-server operations, and exposes every capability through four interchangeable interfaces: Web dashboard, REST API, CLI, and MCP (Model Context Protocol).

## Core Capabilities

- Application deployment lifecycle: clone, build, start, stop, restart, status, logs (streamed via Server-Sent Events).
- App Orchestrator with a reconciliation loop for replica lifecycle management.
- Serverless Docker execution: on-demand, sandboxed container jobs with a PostgreSQL-backed queue.
- MIG Shared GPU: partition an NVIDIA GPU (H100/A100/A30) into up to 7 isolated instances, per-server, via the web UI or API.
- Configurable container runtime: `runc` (default) or `kata` (optional MicroVM isolation).
- Multi-server with capacity-based allocation and peer-to-peer database replication.
- Dynamic nginx locations: automatic reverse-proxy blocks per user/app.
- Deploy Templates catalog (static site, FastAPI, n8n, Ollama, Jupyter, Qdrant) shared across Dashboard, CLI, MCP and REST.
- Onboarding setup wizard that safely writes `conf/deploy.ini`, plus a labeled Sandbox demo account.
- 12 consecutive ports (6 HTTP + 6 HTTPS) reserved per application.
- Security: SSO, 2FA, password reset, ModSecurity WAF (OWASP CRS), per-user isolation.
- Billing and cost tracking with activity logging and PDF invoices.
- PostgreSQL with connection pooling; hourly backups with S3 sync.

## High-Level Architecture

```
Clients:  Web Dashboard  |  REST API  |  CLI  |  MCP (AI agents)
                         v
          Flask multi-blueprint application (src/routes/*)
                         v
   Orchestrator | Serverless workers | GPU/MIG mgr | Replication
                         v
   PostgreSQL  .  Nginx  .  Docker  .  Gitea  .  S3 (OVHcloud)
```

## Access Interfaces

| Interface | Use case |
|-----------|----------|
| Web Dashboard | Visual management for operators and admins |
| REST API | Integration into CI/CD and automation |
| CLI | DevOps and scripting workflows |
| MCP | Autonomous deployment by GenAI agents |

## Configuration at a Glance

- `conf/deploy.ini` — platform identity (`PLTF_NAME`, `PLTF_FOLDER`, `REPO_URL`, `SUBMODULE_URL`), domain, version, install layout (`LINUX_USER_INSTALLATION`) and port allocation. Every key is commented.
- `conf/default_apps` — the default applications provisioned for the admin at startup.
- `conf/serverless.ini` — operator-facing serverless runtime overrides.
- `init_pltf.sh` bootstraps a fresh server (dependencies, Docker, NVIDIA drivers, MIG, kata runtime) and resolves identity defaults via env var > deploy.ini > fallback.

## Related Documentation

- [INIT_PLATFORM.md](./INIT_PLATFORM.md) — server bootstrap
- [DEPLOYMENT_GUIDE.md](./DEPLOYMENT_GUIDE.md) — deploying applications
- [ARCHITECTURE_GUIDE.md](./ARCHITECTURE_GUIDE.md) — system architecture
- [USER_GUIDE.md](./USER_GUIDE.md) — using the platform and agents
- [SERVERLESS.md](./SERVERLESS.md) — serverless Docker execution
- [SHARE_GPU_DOCKER.md](./SHARE_GPU_DOCKER.md) — shared GPU via Docker
- [LIST_OF_APP_AVAILABLE.md](./LIST_OF_APP_AVAILABLE.md) — default applications
