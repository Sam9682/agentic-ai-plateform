# 03 — Database Schema Review

- **Title:** Database Schema Review
- **Audit date:** 2026-10-31
- **Requirement coverage:** R3.1, R3.2, R3.3, R11.1
- **Method:** SQL + source parsing. `migration/*.sql` was grepped for `CREATE TABLE` (pattern `(?i)create\s+table\s+(if\s+not\s+exists\s+)?["']?(\w+)`) and `ALTER TABLE … ADD/ALTER` statements; for each statement the table name, columns, and defining `.sql` file were recorded. `src/database_postgres.py` was scanned for table DDL and schema-bootstrap SQL. It issues **no inline `CREATE TABLE`**; instead its `init_db()` (around line 466) bootstraps the schema by reading and executing `scripts/postgresql_schema.sql`, then applies the `migration/*.sql` files in order. The base-table definitions therefore live in `scripts/postgresql_schema.sql` (loaded by `database_postgres.py`), and later `ALTER`s are attributed to the migration file that performs them. When a table appears in a base definition plus later `ALTER`s, the base definition file is recorded as the source and the altering files are noted.

## Inspected Sources

Recorded as inspected for the purposes of R11.1:

- `src/database_postgres.py` — schema bootstrap orchestrator (`init_db()`); issues no inline `CREATE TABLE`, loads `scripts/postgresql_schema.sql` and then the migrations below.
- `scripts/postgresql_schema.sql` — base schema loaded by `database_postgres.py` (defines the 14 pre-ARO/ZAF tables).
- `migration/add_tenancy.sql`
- `migration/add_agent_events.sql`
- `migration/add_agent_credentials.sql`
- `migration/add_agent_runtimes.sql`
- `migration/add_execution_environments.sql`
- `migration/add_agents.sql`
- `migration/add_agent_executions.sql`
- `migration/add_agent_tasks.sql`
- `migration/add_governance.sql`
- `migration/add_approvals.sql`
- `migration/add_mcp_registry.sql`
- `migration/add_incidents.sql`
- `migration/add_runtime_monitor.sql`
- `migration/add_mig_gpu.sql`
- `migration/add_serverless_jobs.sql`
- `migration/add_target_link_to_serverless_jobs.sql`
- `migration/add_deploy_templates.sql`
- `migration/add_password_reset_and_2fa.sql`
- `migration/add_extended_ports_to_user_applications.sql`
- `migration/add_url_to_applications.sql`
- `migration/add_user_id_to_services.sql`
- `migration/add_backups_history_to_deployments.sql`
- `migration/make_application_fkeys_deferrable.sql`
- `migration/fix_services_constraint.sql`
- `migration/fix_instances_fkey.sql`
- `migration/fix_deployment_user_id.sql` — data-only (`UPDATE`), defines/alters no table.
- `migration/fix_server_capacity.sql` — data-only (`UPDATE`), defines/alters no table.

### Note on bootstrap attribution

`src/database_postgres.py` is the runtime that *creates* every table (by executing the SQL above), but it contains no table DDL of its own. Per the task, tables whose DDL is issued through `database_postgres.py` are attributed to the SQL file it loads. The base tables are attributed to `scripts/postgresql_schema.sql`; the feature tables are attributed to their migration files. `database_postgres.py` is recorded as the bootstrap/apply path in each base table's notes.

### Migration apply order (from `database_postgres.py::init_db()`)

Base schema first (only when `users` is absent), then:
`add_password_reset_and_2fa` → `add_serverless_jobs` → `add_mig_gpu` → `add_target_link_to_serverless_jobs` → `make_application_fkeys_deferrable` → `add_deploy_templates` → `add_extended_ports_to_user_applications` → `add_runtime_monitor` → `add_tenancy` → `add_agent_events` → `add_agent_credentials` → `add_agent_runtimes` → `add_execution_environments` → `add_agents` → `add_agent_executions` → `add_agent_tasks` → `add_governance` → `add_approvals` → `add_mcp_registry` → `add_incidents`. The standalone `fix_*`, `add_url_to_applications`, `add_user_id_to_services`, `add_backups_history_to_deployments`, and `fix_instances_fkey` files are applied/managed outside this ordered loop (operational repair scripts and earlier migrations reflected in the base schema).

---

## Tables

### Base schema (`scripts/postgresql_schema.sql`, bootstrapped by `src/database_postgres.py`)

#### `users`
- **Source file:** `scripts/postgresql_schema.sql`
- **Altering files:** `migration/add_password_reset_and_2fa.sql` (adds `totp_secret`, `totp_enabled`, `totp_backup_codes`, `twofa_email_enabled`); `migration/add_deploy_templates.sql` (adds `account_type`)
- **Columns:** `id BIGSERIAL PK`, `username VARCHAR(255) UNIQUE NOT NULL`, `email VARCHAR(255) UNIQUE NOT NULL`, `password_hash VARCHAR(255) NOT NULL`, `first_name VARCHAR(255)`, `last_name VARCHAR(255)`, `suspended BOOLEAN DEFAULT true`, `created_at TIMESTAMPTZ DEFAULT now`; + `totp_secret VARCHAR(64)`, `totp_enabled BOOLEAN DEFAULT FALSE`, `totp_backup_codes TEXT`, `twofa_email_enabled BOOLEAN DEFAULT FALSE`, `account_type VARCHAR(32)` (via migrations)
- **Constraints:** PK `id`; UNIQUE `username`, `email`. Root referenced table for most FKs.

#### `applications`
- **Source file:** `scripts/postgresql_schema.sql`
- **Altering files:** `migration/add_url_to_applications.sql` (idempotent re-add of `url TEXT` + index; column already present in base schema); `migration/make_application_fkeys_deferrable.sql` (child FKs made DEFERRABLE)
- **Columns:** `id BIGSERIAL PK`, `name VARCHAR(255) UNIQUE NOT NULL`, `url TEXT`, `description TEXT`, `git_url TEXT`, `git_remote_url TEXT`, `git_local_url TEXT`, `git_repo_size INTEGER DEFAULT 50`, `docker_build_duration INTEGER`, `docker_start_duration INTEGER`, `docker_stop_duration INTEGER`, `docker_ps_duration INTEGER`, `docker_compose_ports TEXT`, `created_at TIMESTAMPTZ DEFAULT now`
- **Constraints:** PK `id`; UNIQUE `name`.

#### `auth_tokens`
- **Source file:** `scripts/postgresql_schema.sql`
- **Columns:** `id BIGSERIAL PK`, `user_id BIGINT NOT NULL`, `token_hash VARCHAR(255) UNIQUE NOT NULL`, `expires_at TIMESTAMPTZ NOT NULL`, `created_at TIMESTAMPTZ DEFAULT now`
- **Constraints:** PK `id`; UNIQUE `token_hash`; FK `user_id → users(id) ON DELETE CASCADE`. SSO token store.

#### `user_applications`
- **Source file:** `scripts/postgresql_schema.sql`
- **Altering files:** `migration/add_extended_ports_to_user_applications.sql` (idempotent add of `http_port3..6` / `https_port3..6`; columns already present in base schema and backfilled)
- **Columns:** `id BIGSERIAL PK`, `user_id BIGINT NOT NULL`, `application_id BIGINT NOT NULL`, `url TEXT NOT NULL`, `http_port`/`https_port`, `http_port2`/`https_port2`, `http_port3`/`https_port3`, `http_port4`/`https_port4`, `http_port5`/`https_port5`, `http_port6`/`https_port6` (all INTEGER), `others_port INTEGER`, `created_at TIMESTAMPTZ DEFAULT now`
- **Constraints:** PK `id`; UNIQUE `(user_id, application_id)`; FK `user_id → users(id) CASCADE`; FK `application_id → applications(id) CASCADE` (made DEFERRABLE by `make_application_fkeys_deferrable.sql`).

#### `servers`
- **Source file:** `scripts/postgresql_schema.sql`
- **Altering files:** `migration/add_mig_gpu.sql` (adds `shared_gpu_enabled BOOLEAN DEFAULT FALSE`); `migration/fix_server_capacity.sql` (data-only backfill of NULL capacities)
- **Columns:** `id BIGSERIAL PK`, `server_ip INET UNIQUE NOT NULL`, `server_name VARCHAR(255) NOT NULL`, `server_capacity_user_max INTEGER NOT NULL`, `server_capacity_appli_max INTEGER NOT NULL`, `server_status VARCHAR(50) DEFAULT 'STAND_BY'`, `server_type VARCHAR(50) NOT NULL`, `created_at TIMESTAMPTZ DEFAULT now`; + `shared_gpu_enabled BOOLEAN DEFAULT FALSE` (via migration)
- **Constraints:** PK `id`; UNIQUE `server_ip`. Referenced by deployments, instances, mig_profiles, mig_instances, runtime_containers, runtime_scan_runs, agent_executions.

#### `deployments`
- **Source file:** `scripts/postgresql_schema.sql`
- **Altering files:** `migration/add_backups_history_to_deployments.sql` (idempotent add of `backups_history JSONB` + GIN index; column already in base schema); `migration/add_deploy_templates.sql` (adds `is_sandbox BOOLEAN NOT NULL DEFAULT false`); `migration/make_application_fkeys_deferrable.sql` (FK DEFERRABLE); `migration/fix_deployment_user_id.sql` (data-only repair)
- **Columns:** `id BIGSERIAL PK`, `user_id BIGINT NOT NULL`, `application_id BIGINT`, `application_name VARCHAR(255) NOT NULL`, `status VARCHAR(50) DEFAULT 'pending'`, `deployment_path TEXT`, `git_url TEXT`, `swautomorph_url TEXT`, `gitea_branch_url TEXT`, `modification_history JSONB DEFAULT '[]'`, `backups_history JSONB DEFAULT '[]'`, `server_id BIGINT`, `created_at`/`updated_at TIMESTAMPTZ DEFAULT now`; + `is_sandbox BOOLEAN NOT NULL DEFAULT false` (via migration)
- **Constraints:** PK `id`; FK `user_id → users(id) CASCADE`; FK `application_id → applications(id) SET NULL` (DEFERRABLE); FK `server_id → servers(id) SET NULL`. `updated_at` trigger.

#### `application_costs`
- **Source file:** `scripts/postgresql_schema.sql`
- **Altering files:** `migration/make_application_fkeys_deferrable.sql` (FK DEFERRABLE)
- **Columns:** `id BIGSERIAL PK`, `application_id BIGINT NOT NULL`, `cost_per_day DECIMAL(10,2) DEFAULT 1.0`, `created_at`/`updated_at TIMESTAMPTZ DEFAULT now`
- **Constraints:** PK `id`; FK `application_id → applications(id) CASCADE` (DEFERRABLE). `updated_at` trigger.

#### `billing_activities`
- **Source file:** `scripts/postgresql_schema.sql`
- **Altering files:** `migration/make_application_fkeys_deferrable.sql` (FK DEFERRABLE)
- **Columns:** `id BIGSERIAL PK`, `user_id BIGINT NOT NULL`, `application_id BIGINT NOT NULL`, `action VARCHAR(50) NOT NULL`, `started_at TIMESTAMPTZ`, `stopped_at TIMESTAMPTZ`, `duration_seconds INTEGER`, `cost_amount DECIMAL(10,2)`, `created_at TIMESTAMPTZ DEFAULT now`
- **Constraints:** PK `id`; FK `user_id → users(id) CASCADE`; FK `application_id → applications(id) CASCADE` (DEFERRABLE).

#### `users_logs`
- **Source file:** `scripts/postgresql_schema.sql`
- **Columns:** `id BIGSERIAL PK`, `user_id BIGINT NOT NULL`, `username VARCHAR(255) NOT NULL`, `action VARCHAR(50) NOT NULL`, `datetime TIMESTAMPTZ DEFAULT now`
- **Constraints:** PK `id`; FK `user_id → users(id) CASCADE`. Login/logout audit.

#### `payment_modes`
- **Source file:** `scripts/postgresql_schema.sql`
- **Columns:** `id BIGSERIAL PK`, `user_id BIGINT NOT NULL`, `payment_type VARCHAR(50) NOT NULL`, `bank_account VARCHAR(255)`, `paypal_email VARCHAR(255)`, `card_last_four VARCHAR(4)`, `card_type VARCHAR(50)`, `is_default BOOLEAN DEFAULT false`, `created_at TIMESTAMPTZ DEFAULT now`
- **Constraints:** PK `id`; FK `user_id → users(id) CASCADE`.

#### `invoicing`
- **Source file:** `scripts/postgresql_schema.sql`
- **Columns:** `id BIGSERIAL PK`, `user_id BIGINT NOT NULL`, `invoice_month VARCHAR(7) NOT NULL` (YYYY-MM), `total_amount DECIMAL(10,2) NOT NULL`, `status VARCHAR(50) DEFAULT 'unpaid'`, `payment_date TIMESTAMPTZ`, `payment_mode_id BIGINT`, `created_at TIMESTAMPTZ DEFAULT now`
- **Constraints:** PK `id`; FK `user_id → users(id) CASCADE`; FK `payment_mode_id → payment_modes(id) SET NULL`.

#### `configuration`
- **Source file:** `scripts/postgresql_schema.sql`
- **Columns:** `param_id BIGSERIAL PK`, `parent VARCHAR(255)`, `key VARCHAR(255)`, `value TEXT`
- **Constraints:** PK `param_id`. Nested key/value config store.

#### `services`
- **Source file:** `scripts/postgresql_schema.sql`
- **Altering files:** `migration/add_user_id_to_services.sql` (adds `user_id`, UNIQUE `(name, user_id)`, FK to users — reflected in base schema); `migration/fix_services_constraint.sql` (swaps `services_name_key` → `services_name_user_id_key`)
- **Columns:** `id BIGSERIAL PK`, `name VARCHAR(255) NOT NULL`, `image VARCHAR(255) NOT NULL`, `user_id BIGINT NOT NULL`, `desired_replicas INTEGER DEFAULT 1`, `ports TEXT` (JSON), `environment TEXT` (JSON), `volumes TEXT` (JSON), `health_check_path VARCHAR(255) DEFAULT '/health'`, `created_at`/`updated_at TIMESTAMPTZ DEFAULT now`
- **Constraints:** PK `id`; UNIQUE `(name, user_id)`; FK `user_id → users(id) CASCADE`. App Orchestrator logical services. `updated_at` trigger.

#### `instances`
- **Source file:** `scripts/postgresql_schema.sql`
- **Altering files:** `migration/fix_instances_fkey.sql` (adds `user_id`, composite FK `(service_name, user_id) → services(name, user_id)`, FK to users); `migration/fix_services_constraint.sql` (recreates `instances_service_name_fkey`)
- **Columns:** `id BIGSERIAL PK`, `service_id BIGINT NOT NULL`, `instance_id VARCHAR(255) NOT NULL`, `server_id BIGINT NOT NULL`, `service_name VARCHAR(255)`, `container_id VARCHAR(255)`, `status VARCHAR(50) DEFAULT 'pending'`, `port INTEGER`, `health_status VARCHAR(50) DEFAULT 'unknown'`, `last_health_check TIMESTAMPTZ`, `created_at`/`updated_at TIMESTAMPTZ DEFAULT now`
- **Constraints:** PK `id`; UNIQUE `(service_id, instance_id)`; FK `server_id → servers(id)`; FK `service_id → services(id) CASCADE`; (+ migration FKs on `user_id`/`service_name`). App Orchestrator running containers. `updated_at` trigger.

---

### Serverless execution (`migration/add_serverless_jobs.sql`)

#### `serverless_jobs`
- **Source file:** `migration/add_serverless_jobs.sql`
- **Altering files:** `migration/add_target_link_to_serverless_jobs.sql` (adds `target_link TEXT`)
- **Columns:** `id UUID PK DEFAULT gen_random_uuid()`, `user_id INTEGER NOT NULL`, `image TEXT NOT NULL`, `command JSONB NOT NULL`, `environment JSONB DEFAULT '{}'`, `timeout_seconds INTEGER NOT NULL DEFAULT 300`, `status TEXT NOT NULL DEFAULT 'pending'`, `created_at`/`started_at`/`completed_at TIMESTAMP`, `exit_code INTEGER`, `worker_id TEXT`; + `target_link TEXT` (via migration)
- **Constraints:** PK `id`; FK `user_id → users(id)` (declared twice: inline + `fk_user`); CHECK `timeout_seconds BETWEEN 1 AND 3600`; CHECK `status IN ('pending','running','completed','failed','timeout','cancelled')`.

#### `serverless_job_logs`
- **Source file:** `migration/add_serverless_jobs.sql`
- **Columns:** `id BIGSERIAL PK`, `job_id UUID NOT NULL`, `stream TEXT NOT NULL`, `content TEXT NOT NULL`, `created_at TIMESTAMP DEFAULT now`
- **Constraints:** PK `id`; FK `job_id → serverless_jobs(id) CASCADE`; CHECK `stream IN ('stdout','stderr')`.

#### `serverless_job_results`
- **Source file:** `migration/add_serverless_jobs.sql`
- **Columns:** `job_id UUID PK`, `result JSONB`, `created_at TIMESTAMP DEFAULT now`
- **Constraints:** PK `job_id`; FK `job_id → serverless_jobs(id) CASCADE`.

---

### Shared GPU / MIG (`migration/add_mig_gpu.sql`)

#### `mig_profiles`
- **Source file:** `migration/add_mig_gpu.sql`
- **Columns:** `id SERIAL PK`, `server_id INTEGER NOT NULL`, `profile_name VARCHAR(64) NOT NULL`, `profile_id VARCHAR(128) NOT NULL`, `gpu_memory_gb INTEGER NOT NULL`, `created_at TIMESTAMP DEFAULT now`
- **Constraints:** PK `id`; UNIQUE `(server_id, profile_name)`; FK `server_id → servers(id) CASCADE`; CHECK `gpu_memory_gb BETWEEN 1 AND 80`.

#### `mig_instances`
- **Source file:** `migration/add_mig_gpu.sql`
- **Columns:** `id SERIAL PK`, `server_id INTEGER NOT NULL`, `instance_uuid VARCHAR(36) NOT NULL`, `profile_name VARCHAR(50) NOT NULL`, `gpu_memory_mb INTEGER NOT NULL`, `created_at TIMESTAMP DEFAULT now`
- **Constraints:** PK `id`; UNIQUE `(server_id, instance_uuid)`; FK `server_id → servers(id) CASCADE`; CHECK `gpu_memory_mb BETWEEN 1 AND 81920`.

---

### Deploy templates (`migration/add_deploy_templates.sql`)

#### `deploy_templates`
- **Source file:** `migration/add_deploy_templates.sql`
- **Columns:** `id BIGSERIAL PK`, `template_id VARCHAR(63) UNIQUE NOT NULL`, `app_type VARCHAR(64) NOT NULL`, `display_name VARCHAR(255) NOT NULL`, `source_image TEXT NOT NULL`, `ports JSONB NOT NULL`, `environment JSONB NOT NULL DEFAULT '[]'`, `memory_mb INTEGER NOT NULL`, `cpu_cores NUMERIC(4,1) NOT NULL`, `timeout_seconds INTEGER NOT NULL DEFAULT 300`, `enabled BOOLEAN NOT NULL DEFAULT true`, `created_at TIMESTAMPTZ DEFAULT now`
- **Constraints:** PK `id`; UNIQUE `template_id`; CHECK `memory_mb BETWEEN 64 AND 65536`, `cpu_cores BETWEEN 0.1 AND 64`, `timeout_seconds BETWEEN 1 AND 3600`. Seeded with six built-in templates via `ON CONFLICT DO NOTHING`.

---

### Authentication add-ons (`migration/add_password_reset_and_2fa.sql`)

#### `password_reset_tokens`
- **Source file:** `migration/add_password_reset_and_2fa.sql`
- **Columns:** `id BIGSERIAL PK`, `user_id BIGINT NOT NULL`, `token_hash VARCHAR(255) UNIQUE NOT NULL`, `expires_at TIMESTAMPTZ NOT NULL`, `used BOOLEAN DEFAULT FALSE`, `created_at TIMESTAMPTZ DEFAULT now`
- **Constraints:** PK `id`; UNIQUE `token_hash`; FK `user_id → users(id) CASCADE`.

#### `twofa_email_codes`
- **Source file:** `migration/add_password_reset_and_2fa.sql`
- **Columns:** `id BIGSERIAL PK`, `user_id BIGINT NOT NULL`, `code VARCHAR(6) NOT NULL`, `expires_at TIMESTAMPTZ NOT NULL`, `used BOOLEAN DEFAULT FALSE`, `created_at TIMESTAMPTZ DEFAULT now`
- **Constraints:** PK `id`; FK `user_id → users(id) CASCADE`.

---

### Runtime Security monitor (`migration/add_runtime_monitor.sql`)

#### `runtime_containers`
- **Source file:** `migration/add_runtime_monitor.sql`
- **Columns:** `id BIGSERIAL PK`, `server_id BIGINT NOT NULL`, `container_id TEXT NOT NULL`, `name TEXT`, `image TEXT`, `runtime TEXT`, `state TEXT NOT NULL DEFAULT 'unknown'`, `is_platform_managed BOOLEAN NOT NULL DEFAULT FALSE`, `classification TEXT NOT NULL DEFAULT 'unclassified'`, `confidence_score DOUBLE PRECISION NOT NULL DEFAULT 0.0`, `classification_evidence JSONB DEFAULT '[]'`, `labels JSONB DEFAULT '{}'`, `first_seen`/`last_seen TIMESTAMPTZ DEFAULT now`
- **Constraints:** PK `id`; UNIQUE `(server_id, container_id)`; FK `server_id → servers(id) CASCADE`; CHECK `classification IN ('probable_agent','unclassified')`.

#### `runtime_observations`
- **Source file:** `migration/add_runtime_monitor.sql`
- **Columns:** `id BIGSERIAL PK`, `container_pk BIGINT NOT NULL`, `cpu_percent DOUBLE PRECISION`, `memory_bytes BIGINT`, `pids INTEGER`, `process_summary JSONB DEFAULT '[]'`, `network_summary JSONB DEFAULT '{}'`, `state TEXT`, `observed_at TIMESTAMPTZ DEFAULT now`
- **Constraints:** PK `id`; FK `container_pk → runtime_containers(id) CASCADE`.

#### `runtime_anomalies`
- **Source file:** `migration/add_runtime_monitor.sql`
- **Columns:** `id BIGSERIAL PK`, `container_pk BIGINT NOT NULL`, `rule_id TEXT NOT NULL`, `severity TEXT NOT NULL DEFAULT 'low'`, `evidence JSONB DEFAULT '[]'`, `status TEXT NOT NULL DEFAULT 'open'`, `detected_at TIMESTAMPTZ DEFAULT now`
- **Constraints:** PK `id`; FK `container_pk → runtime_containers(id) CASCADE`; CHECK `severity IN ('low','medium','high','critical')`; CHECK `status IN ('open','acknowledged','resolved')`. Alert-only (no enforcement).

#### `runtime_scan_runs`
- **Source file:** `migration/add_runtime_monitor.sql`
- **Columns:** `id BIGSERIAL PK`, `server_id BIGINT`, `started_at TIMESTAMPTZ DEFAULT now`, `finished_at TIMESTAMPTZ`, `containers_seen INTEGER NOT NULL DEFAULT 0`, `error TEXT`
- **Constraints:** PK `id`; FK `server_id → servers(id) SET NULL`.

---

### Multi-tenancy (`migration/add_tenancy.sql`)

#### `tenants`
- **Source file:** `migration/add_tenancy.sql`
- **Columns:** `id BIGSERIAL PK`, `slug VARCHAR(64) UNIQUE NOT NULL`, `name VARCHAR(255) NOT NULL`, `status VARCHAR(32) NOT NULL DEFAULT 'active'`, `created_at TIMESTAMPTZ DEFAULT now`
- **Constraints:** PK `id`; UNIQUE `slug`; CHECK `status IN ('active','suspended','archived')`. Seeds the `default` tenant. Root of all ARO/ZAF tenant scoping.

#### `tenant_members`
- **Source file:** `migration/add_tenancy.sql`
- **Columns:** `id BIGSERIAL PK`, `tenant_id BIGINT NOT NULL`, `user_id BIGINT NOT NULL`, `role VARCHAR(32) NOT NULL DEFAULT 'operator'`, `is_default BOOLEAN NOT NULL DEFAULT FALSE`, `created_at TIMESTAMPTZ DEFAULT now`
- **Constraints:** PK `id`; UNIQUE `(tenant_id, user_id)`; FK `tenant_id → tenants(id) CASCADE`; FK `user_id → users(id) CASCADE`; CHECK `role IN ('viewer','operator','admin')`.

---

### Event / audit backbone (`migration/add_agent_events.sql`)

#### `agent_events`
- **Source file:** `migration/add_agent_events.sql`
- **Columns:** `id BIGSERIAL PK`, `event_id VARCHAR(128) NOT NULL`, `tenant_id BIGINT NOT NULL`, `agent_id VARCHAR(255)`, `execution_id VARCHAR(255)`, `event_type VARCHAR(128) NOT NULL`, `source VARCHAR(128) NOT NULL`, `action JSONB DEFAULT '{}'`, `decision VARCHAR(32)`, `risk_score INTEGER NOT NULL DEFAULT 0`, `severity VARCHAR(16) NOT NULL DEFAULT 'INFO'`, `correlation_id VARCHAR(128)`, `occurred_at`/`recorded_at TIMESTAMPTZ DEFAULT now`
- **Constraints:** PK `id`; UNIQUE `(tenant_id, event_id)`; FK `tenant_id → tenants(id) CASCADE`; CHECK `decision IS NULL OR IN ('ALLOW','DENY','REQUIRE_APPROVAL','QUARANTINE')`; CHECK `risk_score 0..100`; CHECK `severity IN ('INFO','LOW','MEDIUM','HIGH','CRITICAL')`. Append-only (no UPDATE/DELETE path).

---

### Credential vault (`migration/add_agent_credentials.sql`)

#### `agent_credentials`
- **Source file:** `migration/add_agent_credentials.sql`
- **Columns:** `id BIGSERIAL PK`, `tenant_id BIGINT NOT NULL`, `agent_id VARCHAR(255)`, `name VARCHAR(255) NOT NULL`, `kind VARCHAR(64) NOT NULL DEFAULT 'generic'`, `scope VARCHAR(512) NOT NULL DEFAULT ''`, `ciphertext TEXT NOT NULL`, `status VARCHAR(32) NOT NULL DEFAULT 'active'`, `rotated_at TIMESTAMPTZ`, `created_at TIMESTAMPTZ DEFAULT now`
- **Constraints:** PK `id`; UNIQUE `(tenant_id, name)`; FK `tenant_id → tenants(id) CASCADE`; CHECK `status IN ('active','revoked')`. `ciphertext` holds AEAD ciphertext only (never plaintext).

#### `agent_scoped_tokens`
- **Source file:** `migration/add_agent_credentials.sql`
- **Columns:** `id BIGSERIAL PK`, `tenant_id BIGINT NOT NULL`, `credential_id BIGINT NOT NULL`, `agent_id VARCHAR(255)`, `token_hash VARCHAR(128) UNIQUE NOT NULL`, `scope VARCHAR(512) NOT NULL DEFAULT ''`, `expires_at TIMESTAMPTZ NOT NULL`, `revoked BOOLEAN NOT NULL DEFAULT FALSE`, `created_at TIMESTAMPTZ DEFAULT now`
- **Constraints:** PK `id`; UNIQUE `token_hash`; FK `tenant_id → tenants(id) CASCADE`; FK `credential_id → agent_credentials(id) CASCADE`. Short-lived scoped tokens stored hashed.

---

### Agent runtime registry (`migration/add_agent_runtimes.sql`)

#### `agent_runtimes`
- **Source file:** `migration/add_agent_runtimes.sql`
- **Columns:** `id BIGSERIAL PK`, `tenant_id BIGINT NOT NULL`, `identifier VARCHAR(128) NOT NULL`, `name VARCHAR(255) NOT NULL`, `version VARCHAR(64) NOT NULL`, `vendor VARCHAR(255)`, `install_source TEXT`, `install_method JSONB DEFAULT '{}'`, `supported_protocols JSONB DEFAULT '[]'`, `dependencies JSONB DEFAULT '[]'`, `required_permissions JSONB DEFAULT '[]'`, `execution_modes JSONB DEFAULT '[]'`, `health_check JSONB DEFAULT '{}'`, `config_schema JSONB DEFAULT '{}'`, `status VARCHAR(32) NOT NULL DEFAULT 'registered'`, `created_at TIMESTAMPTZ DEFAULT now`
- **Constraints:** PK `id`; UNIQUE `(tenant_id, identifier)`; FK `tenant_id → tenants(id) CASCADE`; CHECK `status IN ('registered','disabled')`.

---

### Execution environments (`migration/add_execution_environments.sql`)

#### `execution_environments`
- **Source file:** `migration/add_execution_environments.sql`
- **Columns:** `id BIGSERIAL PK`, `tenant_id BIGINT NOT NULL`, `name VARCHAR(255) NOT NULL`, `kind VARCHAR(32) NOT NULL DEFAULT 'docker'`, `cpu_limit VARCHAR(16) NOT NULL DEFAULT '1'`, `memory_limit VARCHAR(16) NOT NULL DEFAULT '512m'`, `disk_limit VARCHAR(16)`, `pids_limit INTEGER NOT NULL DEFAULT 256`, `exec_timeout_seconds INTEGER NOT NULL DEFAULT 1800`, `network_policy VARCHAR(16) NOT NULL DEFAULT 'proxy'`, `read_only BOOLEAN NOT NULL DEFAULT TRUE`, `run_as_user VARCHAR(64) NOT NULL DEFAULT 'nobody'`, `env JSONB DEFAULT '{}'`, `created_at TIMESTAMPTZ DEFAULT now`
- **Constraints:** PK `id`; UNIQUE `(tenant_id, name)`; FK `tenant_id → tenants(id) CASCADE`; CHECK `kind IN ('docker','kata','firecracker','k8s')`; CHECK `network_policy IN ('proxy','none')`.

---

### Agents (`migration/add_agents.sql`)

#### `agents`
- **Source file:** `migration/add_agents.sql`
- **Columns:** `id BIGSERIAL PK`, `tenant_id BIGINT NOT NULL`, `identity VARCHAR(512) NOT NULL`, `name VARCHAR(255) NOT NULL`, `runtime_id BIGINT NOT NULL`, `environment_id BIGINT`, `owner_user_id BIGINT`, `status VARCHAR(32) NOT NULL DEFAULT 'REGISTERED'`, `configuration JSONB DEFAULT '{}'`, `permissions JSONB DEFAULT '[]'`, `policy_refs JSONB DEFAULT '[]'`, `credential_refs JSONB DEFAULT '[]'`, `created_at`/`updated_at TIMESTAMPTZ DEFAULT now`
- **Constraints:** PK `id`; UNIQUE `(tenant_id, identity)`, `(tenant_id, name)`; FK `tenant_id → tenants(id) CASCADE`; FK `runtime_id → agent_runtimes(id) RESTRICT`; FK `environment_id → execution_environments(id) SET NULL`; FK `owner_user_id → users(id) SET NULL`; CHECK `status IN (REGISTERED, INSTALLING, INSTALLED, CONFIGURING, READY, STARTING, RUNNING, STOPPING, STOPPED, FAILED, UNHEALTHY, QUARANTINED, TERMINATED)`.

---

### Agent executions (`migration/add_agent_executions.sql`)

#### `agent_executions`
- **Source file:** `migration/add_agent_executions.sql`
- **Columns:** `id BIGSERIAL PK`, `tenant_id BIGINT NOT NULL`, `agent_id BIGINT NOT NULL`, `execution_ref VARCHAR(255) NOT NULL`, `server_id BIGINT`, `container_id TEXT`, `status VARCHAR(32) NOT NULL DEFAULT 'STARTING'`, `detail JSONB DEFAULT '{}'`, `started_at TIMESTAMPTZ DEFAULT now`, `ended_at TIMESTAMPTZ`
- **Constraints:** PK `id`; UNIQUE `(tenant_id, execution_ref)`; FK `tenant_id → tenants(id) CASCADE`; FK `agent_id → agents(id) CASCADE`; FK `server_id → servers(id) SET NULL`; CHECK `status IN (STARTING, RUNNING, STOPPING, STOPPED, FAILED, UNHEALTHY, QUARANTINED, TERMINATED)`.

---

### Agent task queue (`migration/add_agent_tasks.sql`)

#### `agent_tasks`
- **Source file:** `migration/add_agent_tasks.sql`
- **Columns:** `id BIGSERIAL PK`, `tenant_id BIGINT NOT NULL`, `agent_id BIGINT NOT NULL`, `task_ref VARCHAR(255) NOT NULL`, `operation VARCHAR(128) NOT NULL DEFAULT 'prompt'`, `payload JSONB DEFAULT '{}'`, `initiator_user_id BIGINT`, `priority INTEGER NOT NULL DEFAULT 100`, `status VARCHAR(32) NOT NULL DEFAULT 'pending'`, `policy_context JSONB DEFAULT '{}'`, `result_ref TEXT`, `result JSONB`, `attempts INTEGER NOT NULL DEFAULT 0`, `max_attempts INTEGER NOT NULL DEFAULT 1`, `timeout_seconds INTEGER NOT NULL DEFAULT 1800`, `cancel_requested BOOLEAN NOT NULL DEFAULT FALSE`, `worker_id VARCHAR(128)`, `deadline TIMESTAMPTZ`, `created_at TIMESTAMPTZ DEFAULT now`, `started_at TIMESTAMPTZ`, `finished_at TIMESTAMPTZ`, `idempotency_key VARCHAR(255)`
- **Constraints:** PK `id`; UNIQUE `(tenant_id, task_ref)`; partial UNIQUE index on `(tenant_id, idempotency_key)` where not null; FK `tenant_id → tenants(id) CASCADE`; FK `agent_id → agents(id) CASCADE`; FK `initiator_user_id → users(id) SET NULL`; CHECK `status IN ('pending','claimed','running','succeeded','failed','cancelled','timeout')`. Claimed via `FOR UPDATE SKIP LOCKED`.

---

### Governance / PDP (`migration/add_governance.sql`)

#### `governance_policies`
- **Source file:** `migration/add_governance.sql`
- **Columns:** `id BIGSERIAL PK`, `tenant_id BIGINT NOT NULL`, `name VARCHAR(255) NOT NULL`, `version INTEGER NOT NULL DEFAULT 1`, `scope VARCHAR(32) NOT NULL DEFAULT 'tenant'`, `rules JSONB DEFAULT '[]'`, `enabled BOOLEAN NOT NULL DEFAULT TRUE`, `created_at TIMESTAMPTZ DEFAULT now`
- **Constraints:** PK `id`; UNIQUE `(tenant_id, name, version)`; FK `tenant_id → tenants(id) CASCADE`; CHECK `scope IN ('tenant','agent')`.

#### `agent_permissions`
- **Source file:** `migration/add_governance.sql`
- **Columns:** `id BIGSERIAL PK`, `tenant_id BIGINT NOT NULL`, `agent_id BIGINT NOT NULL`, `action_glob VARCHAR(255) NOT NULL`, `created_at TIMESTAMPTZ DEFAULT now`
- **Constraints:** PK `id`; UNIQUE `(tenant_id, agent_id, action_glob)`; FK `tenant_id → tenants(id) CASCADE`; FK `agent_id → agents(id) CASCADE`.

#### `governance_decisions`
- **Source file:** `migration/add_governance.sql`
- **Columns:** `id BIGSERIAL PK`, `tenant_id BIGINT NOT NULL`, `agent_identity VARCHAR(512)`, `action VARCHAR(255) NOT NULL`, `resource TEXT`, `decision VARCHAR(32) NOT NULL`, `matched_rule JSONB`, `risk_score INTEGER NOT NULL DEFAULT 0`, `reason TEXT`, `params_hash VARCHAR(128)`, `decided_at TIMESTAMPTZ DEFAULT now`
- **Constraints:** PK `id`; FK `tenant_id → tenants(id) CASCADE`; CHECK `decision IN ('ALLOW','DENY','REQUIRE_APPROVAL','QUARANTINE')`. Immutable audit of PDP decisions.

---

### Human approvals (`migration/add_approvals.sql`)

#### `approval_requests`
- **Source file:** `migration/add_approvals.sql`
- **Columns:** `id BIGSERIAL PK`, `tenant_id BIGINT NOT NULL`, `agent_identity VARCHAR(512)`, `action VARCHAR(255) NOT NULL`, `resource TEXT`, `params JSONB DEFAULT '{}'`, `params_hash VARCHAR(128) NOT NULL`, `risk_explanation TEXT`, `triggering_policy JSONB`, `status VARCHAR(16) NOT NULL DEFAULT 'pending'`, `approver_user_id BIGINT`, `decided_at TIMESTAMPTZ`, `created_at TIMESTAMPTZ DEFAULT now`, `expires_at TIMESTAMPTZ`
- **Constraints:** PK `id`; FK `tenant_id → tenants(id) CASCADE`; FK `approver_user_id → users(id) SET NULL`; CHECK `status IN ('pending','approved','rejected','expired')`. `params_hash` binds an approval to the exact action + params.

---

### Governed MCP registry (`migration/add_mcp_registry.sql`)

#### `mcp_servers`
- **Source file:** `migration/add_mcp_registry.sql`
- **Columns:** `id BIGSERIAL PK`, `tenant_id BIGINT NOT NULL`, `name VARCHAR(255) NOT NULL`, `transport VARCHAR(32) NOT NULL DEFAULT 'stdio'`, `endpoint TEXT`, `enabled BOOLEAN NOT NULL DEFAULT TRUE`, `created_at TIMESTAMPTZ DEFAULT now`
- **Constraints:** PK `id`; UNIQUE `(tenant_id, name)`; FK `tenant_id → tenants(id) CASCADE`; CHECK `transport IN ('stdio','http','sse')`.

#### `mcp_tools`
- **Source file:** `migration/add_mcp_registry.sql`
- **Columns:** `id BIGSERIAL PK`, `tenant_id BIGINT NOT NULL`, `server_id BIGINT NOT NULL`, `tool_name VARCHAR(255) NOT NULL`, `canonical_action VARCHAR(255) NOT NULL`, `param_schema JSONB DEFAULT '{}'`, `rate_limit_per_minute INTEGER NOT NULL DEFAULT 60`, `enabled BOOLEAN NOT NULL DEFAULT TRUE`, `created_at TIMESTAMPTZ DEFAULT now`
- **Constraints:** PK `id`; UNIQUE `(tenant_id, server_id, tool_name)`; FK `tenant_id → tenants(id) CASCADE`; FK `server_id → mcp_servers(id) CASCADE`.

---

### Incidents / anomalies (`migration/add_incidents.sql`)

#### `agent_anomalies`
- **Source file:** `migration/add_incidents.sql`
- **Columns:** `id BIGSERIAL PK`, `tenant_id BIGINT NOT NULL`, `agent_identity VARCHAR(512)`, `rule_id VARCHAR(128) NOT NULL`, `severity VARCHAR(16) NOT NULL DEFAULT 'LOW'`, `risk_score INTEGER NOT NULL DEFAULT 0`, `evidence JSONB DEFAULT '[]'`, `status VARCHAR(16) NOT NULL DEFAULT 'open'`, `detected_at TIMESTAMPTZ DEFAULT now`
- **Constraints:** PK `id`; FK `tenant_id → tenants(id) CASCADE`; CHECK `severity IN ('INFO','LOW','MEDIUM','HIGH','CRITICAL')`; CHECK `status IN ('open','acknowledged','resolved')`. Agent-level (distinct from container-level `runtime_anomalies`).

#### `security_incidents`
- **Source file:** `migration/add_incidents.sql`
- **Columns:** `id BIGSERIAL PK`, `tenant_id BIGINT NOT NULL`, `agent_identity VARCHAR(512)`, `kind VARCHAR(64) NOT NULL`, `severity VARCHAR(16) NOT NULL DEFAULT 'HIGH'`, `summary TEXT NOT NULL`, `detail JSONB DEFAULT '{}'`, `status VARCHAR(16) NOT NULL DEFAULT 'open'`, `actions_taken JSONB DEFAULT '[]'`, `created_at TIMESTAMPTZ DEFAULT now`
- **Constraints:** PK `id`; FK `tenant_id → tenants(id) CASCADE`; CHECK `severity IN ('INFO','LOW','MEDIUM','HIGH','CRITICAL')`; CHECK `status IN ('open','contained','resolved')`.

---

## Summary Index

| Table | Source File |
|-------|-------------|
| users | `scripts/postgresql_schema.sql` (bootstrapped by `src/database_postgres.py`) |
| applications | `scripts/postgresql_schema.sql` |
| auth_tokens | `scripts/postgresql_schema.sql` |
| user_applications | `scripts/postgresql_schema.sql` |
| servers | `scripts/postgresql_schema.sql` |
| deployments | `scripts/postgresql_schema.sql` |
| application_costs | `scripts/postgresql_schema.sql` |
| billing_activities | `scripts/postgresql_schema.sql` |
| users_logs | `scripts/postgresql_schema.sql` |
| payment_modes | `scripts/postgresql_schema.sql` |
| invoicing | `scripts/postgresql_schema.sql` |
| configuration | `scripts/postgresql_schema.sql` |
| services | `scripts/postgresql_schema.sql` |
| instances | `scripts/postgresql_schema.sql` |
| serverless_jobs | `migration/add_serverless_jobs.sql` |
| serverless_job_logs | `migration/add_serverless_jobs.sql` |
| serverless_job_results | `migration/add_serverless_jobs.sql` |
| mig_profiles | `migration/add_mig_gpu.sql` |
| mig_instances | `migration/add_mig_gpu.sql` |
| deploy_templates | `migration/add_deploy_templates.sql` |
| password_reset_tokens | `migration/add_password_reset_and_2fa.sql` |
| twofa_email_codes | `migration/add_password_reset_and_2fa.sql` |
| runtime_containers | `migration/add_runtime_monitor.sql` |
| runtime_observations | `migration/add_runtime_monitor.sql` |
| runtime_anomalies | `migration/add_runtime_monitor.sql` |
| runtime_scan_runs | `migration/add_runtime_monitor.sql` |
| tenants | `migration/add_tenancy.sql` |
| tenant_members | `migration/add_tenancy.sql` |
| agent_events | `migration/add_agent_events.sql` |
| agent_credentials | `migration/add_agent_credentials.sql` |
| agent_scoped_tokens | `migration/add_agent_credentials.sql` |
| agent_runtimes | `migration/add_agent_runtimes.sql` |
| execution_environments | `migration/add_execution_environments.sql` |
| agents | `migration/add_agents.sql` |
| agent_executions | `migration/add_agent_executions.sql` |
| agent_tasks | `migration/add_agent_tasks.sql` |
| governance_policies | `migration/add_governance.sql` |
| agent_permissions | `migration/add_governance.sql` |
| governance_decisions | `migration/add_governance.sql` |
| approval_requests | `migration/add_approvals.sql` |
| mcp_servers | `migration/add_mcp_registry.sql` |
| mcp_tools | `migration/add_mcp_registry.sql` |
| agent_anomalies | `migration/add_incidents.sql` |
| security_incidents | `migration/add_incidents.sql` |

**Total: 44 tables** — 14 base tables in `scripts/postgresql_schema.sql` (bootstrapped by `src/database_postgres.py`) and 30 feature tables across 13 migration files.

## Notes on ambiguities and ALTER-only / data-only files

- **`src/database_postgres.py` issues no inline `CREATE TABLE`.** All DDL is sourced from `.sql` files it reads and executes in `init_db()`. Tables are therefore attributed to those `.sql` files per the task's attribution rule, with `database_postgres.py` noted as the bootstrap/apply path.
- **`migration/add_url_to_applications.sql`**, **`add_backups_history_to_deployments.sql`**, and **`add_extended_ports_to_user_applications.sql`** re-add columns that already exist in the current base schema (`scripts/postgresql_schema.sql`). They are idempotent (`ADD COLUMN IF NOT EXISTS`) and recorded as altering files; the base schema already carries these columns.
- **`migration/add_user_id_to_services.sql`** and **`fix_instances_fkey.sql`** add `user_id`/FKs that are likewise present in the current base schema; recorded as altering files for `services`/`instances`.
- **`migration/fix_services_constraint.sql`** performs constraint swaps only (no new table); recorded as an altering file for `services` and `instances`.
- **`migration/make_application_fkeys_deferrable.sql`** alters FK constraints on `user_applications`, `deployments`, `application_costs`, `billing_activities`; no new table.
- **`migration/fix_deployment_user_id.sql`** and **`migration/fix_server_capacity.sql`** are data-only repair scripts (`UPDATE`/`SELECT`); they define or alter no table and introduce no schema object.
