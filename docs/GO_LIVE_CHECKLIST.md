# Go-Live Checklist

**Feature:** phase6-integration-e2e
**Audience:** Platform operators bringing the agentic-ai-platform to production.
**Scope:** Deployment-readiness prerequisites, database migration apply order,
required secrets/environment variables (by key name only), the two release
gates, and operational runbook notes.

> **Secret handling.** This checklist references every secret and credential by
> **key name only**. It contains **no secret values**. Supply the actual values
> through your secret store or environment at deploy time; never commit them to
> the repository and never echo them in logs (the platform already references
> these keys by name only in all its own output).

---

## 1. Environment prerequisites

Confirm each item before deploying.

- [ ] **Docker** engine is installed and running, and the daemon exposes an API
      version `>= 1.40`. The platform pins `DOCKER_API_VERSION=1.44` for Traefik
      (compose `traefik` service environment, and the `env DOCKER_API_VERSION`
      prefix across the `sudo` boundary in `deployControlPlan.sh`).
- [ ] **`swautomorph-shared` external Docker network** exists. Application
      containers and Traefik communicate over it, and the compose `traefik`
      service declares it as `external: true`. Create it once (idempotent):

      ```bash
      docker network create swautomorph-shared
      ```

      `init_pltf.sh` creates this network during provisioning; create it by hand
      if you are not running the full init script. If it is missing, compose
      fails to start Traefik.
- [ ] **PostgreSQL** service is reachable and healthy (`pg_isready`). The
      application bootstraps its schema on first boot from
      `scripts/postgresql_schema.sql` and then applies the ordered migrations in
      section 2.
- [ ] **Traefik** (v3.1) is the single HTTP/HTTPS entrypoint (owns `:80` and
      `:443`), discovers routes via the Docker label provider and the file
      provider (`traefik/dynamic/`), and reaches a ready state.
- [ ] **Application service** (Flask app) is healthy — the `/api/auth/status`
      endpoint responds.

---

## 2. Migration apply order

The base schema (`scripts/postgresql_schema.sql`) is created first on a fresh
database. Migrations under `migration/` are then applied **in the order below**.
This is the exact order `init_db()` in `src/database_postgres.py` applies them;
each migration is idempotent (`IF NOT EXISTS` / `ON CONFLICT`), so a re-run is
harmless.

### 2.1 Base schema (fresh database only)

1. `scripts/postgresql_schema.sql`

### 2.2 Feature migrations (applied automatically at boot by `init_db()`)

Apply in this order:

1. `migration/add_password_reset_and_2fa.sql`
2. `migration/add_serverless_jobs.sql`
3. `migration/add_mig_gpu.sql`
4. `migration/add_target_link_to_serverless_jobs.sql`
5. `migration/make_application_fkeys_deferrable.sql`
6. `migration/add_deploy_templates.sql`
7. `migration/add_extended_ports_to_user_applications.sql`
8. `migration/add_runtime_monitor.sql`

Then the ARO/ZAF/observability migrations, applied in dependency order:

9. `migration/add_tenancy.sql`
10. `migration/add_agent_events.sql`
11. `migration/add_agent_credentials.sql`
12. `migration/add_agent_runtimes.sql`
13. `migration/add_execution_environments.sql`
14. `migration/add_agents.sql`
15. `migration/add_agent_executions.sql`
16. `migration/add_agent_tasks.sql`
17. `migration/add_governance.sql`
18. `migration/add_approvals.sql`
19. `migration/add_mcp_registry.sql`
20. `migration/add_incidents.sql`
21. `migration/add_agent_cost_records.sql`
22. `migration/add_supervisor.sql`

### 2.3 Upgrade / fix migrations (existing databases, apply as needed)

For databases provisioned before a given column/constraint existed, apply the
relevant upgrade migrations manually (see
`docs/technicals/SCHEMA_MIGRATION_VERIFICATION.md`). They are idempotent and
safe to re-run:

- `migration/add_backups_history_to_deployments.sql`
- `migration/add_url_to_applications.sql`
- `migration/add_user_id_to_services.sql`
- `migration/fix_services_constraint.sql`
- `migration/add_instance_remediation.sql`
- `migration/add_aro_phase2.sql`
- `migration/add_credential_key_version.sql`
- `migration/fix_deployment_user_id.sql`
- `migration/fix_server_capacity.sql`
- `migration/fix_instances_fkey.sql`

Example manual apply:

```bash
psql -U swautomorph -d ai_swautomorph -f migration/add_backups_history_to_deployments.sql
```

---

## 3. Required secrets and configuration (key names only)

Provide each of the following before go-live. **No values appear here** — set
them in your secret store / environment.

### 3.1 Secrets and environment variables

| Key name | Purpose | Referenced in |
|----------|---------|---------------|
| `POSTGRES_PASSWORD` | PostgreSQL database password. | compose / DB connection |
| `SECRET_KEY` | Flask application secret (session signing). | application config |
| `SEED_ADMIN_PASSWORD` | Initial seeded admin credential. In production it **must** be set — db-init fails closed if it is missing. | `src/database_postgres.py` |
| `ZAF_SECRET_KEY` | Zero-trust Agent Firewall signing secret. | `src/zaf/*`, `src/gitea_auth.py` test wiring |
| `SSO_MAC_KEY` | HMAC key for SSO token MACs; fails closed when unset. | `src/auth.py` |
| `GITEA_TOKEN` | Gitea access token; wrapped so it cannot leak via logs/repr; fails closed when unset. | `src/gitea_auth.py` |

### 3.2 Managed `known_hosts` path

- **Config key:** `ssh_managed_known_hosts` (configuration table / `deploy.ini`).
- **Default:** `<repo>/conf/ssh/known_hosts`.
- Used for TOFU host-key verification
  (`StrictHostKeyChecking=accept-new` + `UserKnownHostsFile=<managed>`). Ensure
  the path (and its parent directory) is writable; the platform creates the
  parent before invoking SSH. See `src/ssh_utils.py`.

### 3.3 Rate card and roles configuration

- **Rate card:** the `[rate_card]` section of `conf/obs.ini`. Supplies the per-
  usage-dimension rates used to derive estimated cost (`src/obs/obs_cost.py`).
  A missing rate contributes `0.0`.
- **Roles configuration:** `conf/supervisor_roles.yaml`. The Supervisor loads
  its Role set from this file (roles are data, not code), so adding a role is a
  config change with no code change (`src/aro/supervisor.py`).

---

## 4. Release gates

A release is permitted only when **both** gates below are green.

### 4.1 Full-suite green gate (Green_Gate)

Runs every test runner in a single invocation and reports one combined result:

```bash
scripts/run_green_gate.sh
```

- Runs pytest (`tests/` + the DB-coupled `scripts/test_*.py`, with the harness
  environment set so the previously-gated integration tests execute rather than
  skip), `node --test` in `tests/js`, and the bash harness suites.
- Passes **iff** pytest **and** node **and** bash all pass; otherwise it fails
  and names the failing runner(s). Exit `0` on PASS, non-zero on FAIL.
- Release expectation: **zero** pre-existing failures and the three
  previously-skipped integration tests execute and pass.

### 4.2 E2E governed-scenario gate

Proves the end-to-end governed security enforcement chain against **mocked**
cloud providers (AWS STS, OpenStack). Keep `ZAF_LIVE_OPENSTACK` **unset** so the
scenario stays fully mocked and performs no destructive cloud mutations:

```bash
pytest tests/test_e2e_governed_scenario.py
```

The scenario covers: inspect/allow, delete/require-approval/block (HTTP 202, no
deletion), approve/execute, parameter-change/invalidate (an approval binds to
exactly its action and parameters), the live-cloud guard (the real provider
refuses mutations unless `ZAF_LIVE_OPENSTACK` is explicitly set), and audit
recording of every decision.

---

## 5. Operational runbook notes

- **Reproduce the live verification environment.** Use the integration harness
  to stand up PostgreSQL, the app, and Traefik, wait for health, export the
  opt-in gates, run the gated suites, and tear down:

  ```bash
  scripts/run_integration_harness.sh [--profile integration] [--keep-up] [--health-timeout <sec>]
  ```

  To reproduce the same steps **by hand without CI**, follow the **Manual_Recipe**
  documented alongside the harness (harness README / `scripts/run_integration_harness.sh --help`):
  create the `swautomorph-shared` network, `docker compose up` the three
  services, wait for health, export `RUN_TRAEFIK_INTEGRATION`,
  `RUN_TRAEFIK_LOCALLY_INTEGRATION`, and `USE_POSTGRES=true` (leave
  `ZAF_LIVE_OPENSTACK` unset), then run the gated pytest modules and DB-coupled
  scripts.

- **Service health before anything else.** If PostgreSQL, the app, or Traefik is
  not healthy within the health timeout, do not proceed — the harness aborts and
  names the unhealthy service. No partial runs against an unhealthy environment.

- **Missing network symptom.** If Traefik fails to start, confirm the
  `swautomorph-shared` network exists (section 1). Compose cannot attach Traefik
  without it.

- **Docker API negotiation.** If Traefik's Docker provider is stuck in a
  discovery retry loop, confirm `DOCKER_API_VERSION` (`>= 1.40`, pinned to
  `1.44`) reaches the provider — in docker mode via the compose service
  environment, and in locally mode via the `env DOCKER_API_VERSION=...` prefix in
  `deployControlPlan.sh` (a plain `export` is stripped across `sudo`).

- **Secret hygiene in logs.** The platform names secret keys, never values, in
  all configuration and initialization messages. Keep this invariant in any
  custom tooling or runbook automation you add.

- **Live cloud actions are gated.** Keep `ZAF_LIVE_OPENSTACK` unset in CI and in
  any verification run. Set it only for an explicitly authorized, operator-driven
  live action — never as a default.

- **Rollback.** Migrations are additive and idempotent; a failed boot does not
  partially corrupt applied migrations (each is committed independently and
  errors are rolled back and logged by key name). If a deploy fails health
  checks, restore the previous application image and re-run the green gate before
  retrying.

---

## 6. Go-live sign-off

- [ ] Section 1 prerequisites confirmed.
- [ ] Section 2 migrations applied in order; DB healthy.
- [ ] Section 3 secrets/configuration provided (by key name), no values in repo
      or logs.
- [ ] Section 4.1 full-suite Green_Gate is green (zero pre-existing failures;
      previously-skipped integration tests execute and pass).
- [ ] Section 4.2 E2E governed-scenario gate passes with `ZAF_LIVE_OPENSTACK`
      unset.
- [ ] Section 5 runbook notes reviewed; on-call aware of the health, network,
      and secret-hygiene expectations.
