# Dynamic Application Routing (Traefik)

> **Migration note:** This document previously described dynamic **nginx location
> blocks**. The platform now uses **Traefik v3.1** as its single HTTP/HTTPS
> entrypoint. nginx, the per-app nginx sidecar, `sub_filter` response rewriting,
> `docker ps` host-port discovery, and the ModSecurity WAF have all been removed.
> The module (formerly `src/nginx_manager.py`, now `src/frontend_manager.py`)
> keeps its public API for backward compatibility, but it now writes **Traefik
> dynamic configuration** instead of nginx config. Think of it as the
> **Proxy_Manager**.

## Overview

The platform automatically creates a Traefik route for each user application,
allowing access via:
```
https://<DOMAIN>/{USER_NAME}/{APPLICATION_NAME}
```

Traefik matches that host + path prefix, strips the `/{USER_NAME}/{APPLICATION_NAME}`
prefix, and forwards the request to the application container over the shared
Docker network `swautomorph-shared`, reaching it on its **internal HTTP port**
(the port the app listens on inside the container — known at deploy time, never
scraped from `docker ps`).

## How It Works

Routing is **hybrid** — the same route is expressed through two Traefik providers
that are equivalent in effect:

### 1. Docker label provider (static baseline)

When an application is deployed, its generated per-app `docker-compose.yml`
carries Traefik labels on the app container at create time. Traefik's Docker
provider discovers the route the moment the container starts — no Python
involvement, self-healing on restart. Labels define:

- `traefik.enable=true` and `traefik.docker.network=swautomorph-shared`
- a router rule `Host(<DOMAIN>) && PathPrefix(/{user}/{app})`, `entrypoints=websecure`, `tls=true`
- a `stripprefix` middleware removing `/{user}/{app}`
- `services.<router>.loadbalancer.server.port=<internal HTTP port>`

### 2. Traefik file provider (programmatic path)

`src/frontend_manager.py` (the Proxy_Manager) writes and deletes a **per-app
dynamic config file** under a watched directory:
```
${PLTF_FOLDER}/traefik/dynamic/app-{user}-{app}.yml
```
Traefik hot-reloads file-provider changes with **no restart** and **no
`nginx -t`-style validation step**. Writes are **atomic** (temp file +
`os.replace`), so Traefik never reads a half-written file. This is the path the
platform's deploy / rollback / teardown / sync lifecycle uses, and it is
reconcilable directly from the database.

Because StripPrefix removes `/{user}/{app}` before forwarding, the app sees
root-relative paths internally. Apps are made **path-aware** by a `BASE_PATH`
environment variable set to `/{user}/{app}/`, so they emit asset and link URLs
under their prefix. This replaces the old nginx `sub_filter` response rewriting.
WebSocket upgrades are forwarded automatically by Traefik (no special directive).

### Example

For user `admin` with application `ai-hypervisia`, internal HTTP port `5000`,
and domain `softfluid.fr`:

**Access URL:**
```
https://softfluid.fr/admin/ai-hypervisia
```

**Docker-label form (on the app container, baseline):**
```yaml
labels:
  - "traefik.enable=true"
  - "traefik.docker.network=swautomorph-shared"
  - "traefik.http.routers.admin-ai-hypervisia.rule=Host(`softfluid.fr`) && PathPrefix(`/admin/ai-hypervisia`)"
  - "traefik.http.routers.admin-ai-hypervisia.entrypoints=websecure"
  - "traefik.http.routers.admin-ai-hypervisia.tls=true"
  - "traefik.http.routers.admin-ai-hypervisia.middlewares=admin-ai-hypervisia-strip@docker"
  - "traefik.http.middlewares.admin-ai-hypervisia-strip.stripprefix.prefixes=/admin/ai-hypervisia"
  - "traefik.http.services.admin-ai-hypervisia.loadbalancer.server.port=5000"
```

**File-provider form written by `insert_location_block`
(`traefik/dynamic/app-admin-ai-hypervisia.yml`):**
```yaml
http:
  routers:
    admin-ai-hypervisia:
      rule: "Host(`softfluid.fr`) && PathPrefix(`/admin/ai-hypervisia`)"
      entryPoints: ["websecure"]
      service: "admin-ai-hypervisia"
      middlewares: ["admin-ai-hypervisia-strip"]
      tls: {}
  middlewares:
    admin-ai-hypervisia-strip:
      stripPrefix:
        prefixes: ["/admin/ai-hypervisia"]
  services:
    admin-ai-hypervisia:
      loadBalancer:
        serversTransport: app-transport
        servers:
          - url: "http://admin-ai-hypervisia:5000"
  serversTransports:
    app-transport:
      forwardingTimeouts:
        dialTimeout: "30s"            # connect (was nginx proxy_connect_timeout 30s)
        responseHeaderTimeout: "60s"  # read    (was nginx proxy_read_timeout 60s)
```

## API Usage

### Automatic Updates

Routes are automatically updated when:
- Assigning an application to a user via `/api/users/{user_id}/applications` (POST)
- Unassigning an application via `/api/users/{user_id}/applications` (DELETE)
- Cloning/deploying an application via `/api/deployments` (POST with action=clone)

Each of these calls the preserved `insert_location_block` / `remove_location_block`
functions, which now write or delete the per-app Traefik dynamic file.

### Manual Sync

Sync all routes from the database (admin only):
```bash
curl -X POST https://<DOMAIN>/api/nginx/sync \
  -H "Cookie: session=your-session-cookie"
```

Or via CLI:
```bash
python3 ./scripts/sync_reverse_proxy.py
```

`sync_all_locations` reconciles the dynamic directory to **exactly** match the
database: it writes a route file for every DB app and deletes any `app-*.yml`
that no longer corresponds to a DB app. It is **idempotent** — a second run
produces the same directory contents. Port reconciliation is no longer needed,
because ports come from the deploy-time contract rather than live containers.

## Configuration Files

- **Per-app routes:** `${PLTF_FOLDER}/traefik/dynamic/app-{user}-{app}.yml`
- **TLS config:** `${PLTF_FOLDER}/traefik/dynamic/tls.yml`
- **Secondary domains:** `${PLTF_FOLDER}/traefik/dynamic/secondary-domains.yml`
- **Manager module:** `src/frontend_manager.py` (the Proxy_Manager)
- **Certificates:** `ssl/<DOMAIN>/fullchain_domain.crt` and `ssl/<DOMAIN>/privateKey_domain.key`
  (mounted read-only into Traefik at `/etc/traefik/ssl`)

## Troubleshooting

### Inspect the active routes
```bash
ls ${PLTF_FOLDER}/traefik/dynamic/
cat ${PLTF_FOLDER}/traefik/dynamic/app-<user>-<app>.yml
```

### Check Traefik logs
```bash
docker logs ${PLTF_FOLDER:-agentic-ai-plateform}-traefik
tail -f logs/api_routes.log
```

### Re-sync all routes
```bash
python3 ./scripts/sync_reverse_proxy.py
```

There is no reload/validate command to run: Traefik's file watcher hot-applies
changes automatically, and a malformed dynamic file is logged and ignored while
Traefik keeps serving the last valid config.

## Security Considerations

- Only admin users can manually trigger a route sync.
- Path validation prevents injection into router rules and file paths.
- Atomic writes (`os.replace`) ensure Traefik never reads a partial route file.
- `exposedByDefault=false` means only containers that opt in with
  `traefik.enable=true` are routed, so platform-internal services (postgres,
  gitea, the control-plane app) are not accidentally exposed.

## Implementation Details

### Module: `src/frontend_manager.py` (Proxy_Manager)

**Preserved public functions (signatures unchanged):**
- `insert_location_block(user_name, app_name, deployment_url, user_appli_url)` — write the app's Traefik route file
- `remove_location_block(user_name, app_name)` — delete the app's route file (missing file is success)
- `sync_all_locations(db_manager)` — reconcile the dynamic directory to match the database

Every function returns a boolean; any failure returns `False` so callers run
their existing rollback paths.

### Integration Points

**API Routes (`src/routes/api_routes.py`):**
- Application assignment endpoint
- Application unassignment endpoint
- Deployment clone action
- Manual sync endpoint

### Database Schema

Uses the existing `user_applications` table with username lookup:
```sql
SELECT u.username, a.name, ua.url
FROM user_applications ua
JOIN applications a ON ua.application_id = a.id
JOIN users u ON ua.user_id = u.id
WHERE ua.url IS NOT NULL AND ua.url != ''
```

**Note:** The system uses `username` (not `user_id`) in URL paths for better
readability and user experience.

## Future Enhancements

- Custom domain mapping per application
- Per-app middleware (rate limiting, auth) via additional Traefik middlewares
- Load balancing for multi-instance applications
- Health checks per router/service
