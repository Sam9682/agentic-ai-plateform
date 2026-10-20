# Dynamic Application Routing — Implementation Summary (Traefik)

> **Migration note:** This summary previously described dynamic **nginx location
> blocks**. The platform now uses **Traefik v3.1** as its single HTTP/HTTPS
> entrypoint. nginx, the per-app nginx sidecar, `sub_filter` response rewriting,
> `docker ps` host-port discovery, and the ModSecurity WAF are gone. The module
> `src/nginx_manager.py` keeps its name and public API (it is the
> **Proxy_Manager**) but now writes Traefik dynamic configuration.

## Overview

The platform automatically routes user applications through Traefik, enabling
access via:
```
https://<DOMAIN>/{USER_NAME}/{APPLICATION_NAME}
```

Traefik matches the host + path prefix, strips `/{USER_NAME}/{APPLICATION_NAME}`,
and forwards to the application container over the shared Docker network
`swautomorph-shared`, reaching it on its **internal HTTP port** (known at deploy
time from the template, never scraped from `docker ps`).

## Routing Model

Routing is **hybrid**, using two equivalent Traefik providers:

1. **Docker label provider (static baseline).** The generated per-app
   `docker-compose.yml` carries Traefik labels on the app container at create
   time. Traefik discovers the route as soon as the container starts.
2. **Traefik file provider (programmatic path).** `src/nginx_manager.py` writes
   and deletes per-app dynamic config files under
   `${PLTF_FOLDER}/traefik/dynamic/app-{user}-{app}.yml`, hot-reloaded with no
   restart and no validation command. This is the path used by the deploy /
   rollback / teardown / sync lifecycle.

The file-provider route is authoritative for lifecycle operations; the compose
labels guarantee a correct route even before `insert_location_block` runs.

## Files

### Core Module
- **`src/nginx_manager.py`** — the Proxy_Manager (Traefik dynamic config management)
  - `insert_location_block()` — write the app's Traefik route file
  - `remove_location_block()` — delete the app's route file (missing = success)
  - `sync_all_locations()` — reconcile the dynamic directory to match the database
  - Internal helpers build the router rule, StripPrefix middleware, service
    load-balancer, and `serversTransports` timeouts, and write files atomically.

> The former nginx-only helpers (`generate_location_block`, `read_nginx_config`,
> `write_nginx_config`, `reload_nginx`, `test_nginx_config`,
> `discover_running_ports`, `build_http_upstream`, `to_http_upstream_url`) have
> been retired.

### Scripts
- **`scripts/sync_nginx_locations.py`** — CLI tool to sync all routes from the database
- **`scripts/test_nginx_locations.py`** — smoke test for the route lifecycle (now asserts Traefik output)

### Traefik configuration
- **`traefik/dynamic/app-{user}-{app}.yml`** — per-app route files (runtime)
- **`traefik/dynamic/tls.yml`** — TLS certificate references
- **`traefik/dynamic/secondary-domains.yml`** — multi-domain routers/services
- Root `docker-compose.yml` — the `traefik:v3.1` service owning `:80`/`:443`

## How It Works

### Automatic Updates

Traefik routes are automatically managed when:

1. **Assigning application to user** — POST `/api/users/{user_id}/applications`
   → `insert_location_block()` writes `traefik/dynamic/app-{user}-{app}.yml`
2. **Unassigning application** — DELETE `/api/users/{user_id}/applications`
   → `remove_location_block()` deletes the route file
3. **Cloning/deploying application** — POST `/api/deployments` with `action=clone`
   → `insert_location_block()` writes/updates the route after a successful clone

### Manual Sync

**Via API (admin only):**
```bash
curl -X POST https://<DOMAIN>/api/nginx/sync \
  -H "Cookie: session=your-session-cookie"
```

**Via CLI:**
```bash
python3 ./scripts/sync_nginx_locations.py
```

`sync_all_locations` writes a route file for every DB app and deletes any
`app-*.yml` with no matching DB app. It is idempotent.

## Example

### User `admin` with `ai-hypervisia` on internal port 5000, domain `softfluid.fr`

**Database entry:**
```sql
user:        admin
application: ai-hypervisia
url:         https://softfluid.fr/admin/ai-hypervisia
```

**Generated Traefik route (`traefik/dynamic/app-admin-ai-hypervisia.yml`):**
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
        dialTimeout: "30s"
        responseHeaderTimeout: "60s"
```

**Access:**
```bash
curl https://softfluid.fr/admin/ai-hypervisia
```

The app renders asset/link URLs under its prefix using the `BASE_PATH`
environment variable (`/admin/ai-hypervisia/`) that the platform injects at
deploy time — this replaces nginx `sub_filter` rewriting. WebSocket upgrades are
forwarded automatically by Traefik.

## Safety Features

1. **Atomic writes** — temp file + `os.replace`; Traefik never reads a partial file.
2. **Hot reload, no validation step** — the file watcher applies changes with no
   restart; a malformed file is logged and ignored while the last valid config
   keeps serving (no `nginx -t` needed).
3. **Boolean return + rollback** — every function returns `False` on failure so
   callers trigger existing rollback handling.
4. **Admin-only sync** — manual sync requires admin privileges.
5. **Opt-in exposure** — `exposedByDefault=false`; only `traefik.enable=true`
   containers are routed.

## Testing

```bash
python3 ./scripts/test_nginx_locations.py
```

## Deployment

No extra deployment steps for routing itself. Provisioning creates the shared
network and the dynamic directory:
```bash
docker network create swautomorph-shared   # idempotent, created by init_pltf.sh
# traefik/dynamic/ directory is created during provisioning
```
Routing is active once an application is assigned, deployed/cloned, or a manual
sync is triggered.

## Configuration

- **Per-app routes:** `${PLTF_FOLDER}/traefik/dynamic/app-{user}-{app}.yml`
- **TLS:** `${PLTF_FOLDER}/traefik/dynamic/tls.yml` (references existing certs)
- **Certificates mount:** `./ssl:/etc/traefik/ssl:ro`

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
python3 ./scripts/sync_nginx_locations.py
```

## Future Enhancements

- Custom domain mapping per application
- Per-app middlewares (rate limiting, access control) via Traefik middlewares
- Load balancing for multi-instance apps
- Health checks per router/service
- Metrics and monitoring per route
