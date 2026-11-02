# Scripts

Operational and verification scripts for the agentic-ai-platform.

## Integration Harness

`run_integration_harness.sh` is the Phase 6 reproducible, credential-free
integration harness. It brings up the live environment (PostgreSQL, the Flask
app, and Traefik), waits for every service to report healthy, exports the opt-in
gates that unblock the previously-gated suites, runs those suites, and tears the
environment down.

```
run_integration_harness.sh [--profile <name>] [--keep-up] [--health-timeout <sec>]
  exit 0  -> all gated suites executed and passed
  exit !0 -> a service failed health, a prerequisite is missing, or a suite failed
```

No real cloud-provider credentials are configured, read, or required. The E2E
gate `ZAF_LIVE_OPENSTACK` is deliberately left unset so the governed scenario
stays fully mocked. Secrets are referenced by key name only; the harness never
emits a secret value.

## Manual Recipe (reproduce the harness by hand, without CI)

The steps below reproduce what `run_integration_harness.sh` does, for an
operator who wants to run the previously-gated suites by hand without CI. Run
every command from the repository root.

> Secrets in this recipe are referenced **by key name only**. Never paste secret
> values into a shell history or a log. The commands below read values from your
> environment or from the compose defaults; they do not print secret values.

### 1. Prerequisite: the `swautomorph-shared` external Docker network

The compose `traefik` service attaches to an external Docker network named
`swautomorph-shared` (`networks: swautomorph-shared: external: true`). If it is
absent, Compose fails to start Traefik. Create it once before bringing the
services up:

```bash
docker network create swautomorph-shared
```

This network is idempotent across runs — if it already exists, the create
command reports that and you can proceed. You can confirm it with
`docker network inspect swautomorph-shared`.

### 2. Bring up the three services

Start the harness-relevant services (their declared dependencies come along
automatically):

```bash
docker compose up -d postgres app traefik
```

If Compose reports a missing-network error, revisit step 1 and create
`swautomorph-shared`.

### 3. Wait for health before running any suite

Do not run a gated suite until all three services are healthy. Check each one:

- **PostgreSQL** — ready when `pg_isready` succeeds inside the container:

  ```bash
  docker compose exec postgres pg_isready -U swautomorph -d ai_swautomorph
  ```

- **Application** — ready when the auth-status endpoint responds from inside the
  app container (the port defaults to `6000`, overridable via `HTTP_PORT`):

  ```bash
  docker compose exec app curl -fsS http://localhost:6000/api/auth/status
  ```

- **Traefik** — ready when its container reports healthy or its healthcheck/web
  entrypoint is reachable:

  ```bash
  docker compose exec traefik traefik healthcheck --ping
  ```

Alternatively, watch the aggregate health with `docker compose ps` until the
`postgres`, `app`, and `traefik` services show a healthy/running state. If a
service never becomes healthy, inspect its logs (`docker compose logs --tail=40
<service>`; log output references env by key name, not secret values) and fix
the environment before proceeding.

### 4. Export the opt-in gates

With the services healthy, export the three opt-in gates that unblock the
previously-gated suites. Leave `ZAF_LIVE_OPENSTACK` **unset** so the E2E
governed scenario stays fully mocked and no cloud credentials are required.

```bash
export RUN_TRAEFIK_INTEGRATION=1
export RUN_TRAEFIK_LOCALLY_INTEGRATION=1
export USE_POSTGRES=true
```

Also make the non-cloud PostgreSQL connection settings available to the suites.
These are local, non-cloud settings referenced by key name only — the password
is read from your environment (or the compose default) and is never printed:

```bash
export POSTGRES_HOST=localhost
export POSTGRES_PORT=5432
export POSTGRES_DB=ai_swautomorph
export POSTGRES_USER=swautomorph
# POSTGRES_PASSWORD is taken from the environment / compose default; do not echo it.
```

Confirm the live-cloud gate is not set:

```bash
unset ZAF_LIVE_OPENSTACK
```

### 5. Run the gated suites

Run the integration-marked pytest modules and the DB-coupled scripts. Run them
all, then inspect the combined result — a non-zero exit from any module means a
gated suite failed.

```bash
# Integration_Pytest_Tests
python3 -m pytest \
  tests/test_traefik_docker_api_version_integration.py \
  tests/test_traefik_control_plane.py \
  tests/test_e2e_governed_scenario.py

# DB_Coupled_Scripts (require live PostgreSQL + USE_POSTGRES=true)
python3 -m pytest scripts/test_*.py
```

A suite that was skipped at import or collection during the audit should now
**execute its assertions** rather than skip, because the gates in step 4 are set
and the services from step 2 are healthy.

### 6. Tear down

When finished, bring the environment down:

```bash
docker compose down --remove-orphans
```

The `swautomorph-shared` network is external and is not removed by
`compose down`; leave it in place for the next run, or remove it explicitly with
`docker network rm swautomorph-shared` if you no longer need it.

---

This Manual Recipe is cross-referenced from the
[Go-Live Checklist](../docs/GO_LIVE_CHECKLIST.md).
