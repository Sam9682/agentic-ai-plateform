# 04 — API Inventory

| Field | Value |
|-------|-------|
| **Title** | API Inventory |
| **Audit date** | 2026-10-31 |
| **Requirements** | 4.1, 4.2, 4.3, 11.1 |

## Inspected sources

Every `*_routes.py` module under `src/routes/` was inspected (read/search only):

| Module | Inspected | Defines routes | Blueprint `url_prefix` |
|--------|-----------|----------------|------------------------|
| `src/routes/__init__.py` | yes | no | — |
| `src/routes/aro_common.py` | yes | no | — (shared helpers: `tenant_scoped`, `role_required`) |
| `src/routes/engine_runner.py` | yes | no | — (non-route helper module) |
| `src/routes/main_routes.py` | yes | yes | *(none)* |
| `src/routes/auth_routes.py` | yes | yes | *(none)* |
| `src/routes/api_routes.py` | yes | yes | `/api` |
| `src/routes/genai_routes.py` | yes | yes | `/api` |
| `src/routes/agent_control_routes.py` | yes | yes | `/api` |
| `src/routes/sandbox_routes.py` | yes | yes | `/api` |
| `src/routes/templates_routes.py` | yes | yes | `/api` |
| `src/routes/serverless_routes.py` | yes | yes | `/api` |
| `src/routes/wizard_routes.py` | yes | yes | `/api/wizard` |
| `src/routes/billing_routes.py` | yes | yes | *(none)* — paths already contain `/api/billing` |
| `src/routes/replication_routes.py` | yes | yes | *(none)* — paths already contain `/api/sync` |
| `src/routes/gpu_routes.py` | yes | yes | `/api/servers/<int:server_id>/gpu` |
| `src/routes/orchestrator_routes.py` | yes | yes | `/api/orchestrator` |
| `src/routes/sso_routes.py` | yes | yes | `/sso` |
| `src/routes/security_routes.py` | yes | yes | `/security` |
| `src/routes/obs_routes.py` | yes | yes | `/api/v1/observability` |
| `src/routes/zaf_governance_routes.py` | yes | yes | `/api/v1/governance` |
| `src/routes/aro_task_routes.py` | yes | yes | `/api/v1/agents` |
| `src/routes/aro_agent_routes.py` | yes | yes | `/api/v1/agents` |
| `src/routes/aro_runtime_routes.py` | yes | yes | `/api/v1/agents` |

## Method

- Route decorators were extracted with the pattern `@\w+\.route(\s*["']([^"']+)["'](.*methods\s*=\s*\[([^\]]*)\])?` to capture the path and the optional `methods=` list. When no `methods=` is present, the HTTP method defaults to `GET` (Flask's default).
- Blueprint prefixes were extracted by grepping `Blueprint(` and `url_prefix=`; each route's **Path** column below is the full path (`url_prefix` + decorator path).
- A grep for `add_url_rule` found **no matches**, so there are no programmatically registered routes. All routes are statically declared via decorators; none are dynamically built. (Any that were would be flagged "ambiguous" per the audit method rather than omitted.)

## Routes by module

The seven modules named in Requirement 4.2 are covered explicitly first, followed by the remaining route modules.

### `aro_task_routes.py` (prefix `/api/v1/agents`)

| Method | Path | Source File | Handler |
|--------|------|-------------|---------|
| POST | `/api/v1/agents/tasks` | `src/routes/aro_task_routes.py` | `submit_task` |
| GET | `/api/v1/agents/tasks/<int:task_id>` | `src/routes/aro_task_routes.py` | `get_task` |
| POST | `/api/v1/agents/tasks/<int:task_id>/cancel` | `src/routes/aro_task_routes.py` | `cancel_task` |
| GET | `/api/v1/agents/tasks/<int:task_id>/events` | `src/routes/aro_task_routes.py` | `task_events` |

### `aro_agent_routes.py` (prefix `/api/v1/agents`)

| Method | Path | Source File | Handler |
|--------|------|-------------|---------|
| GET | `/api/v1/agents/` | `src/routes/aro_agent_routes.py` | `list_agents` |
| POST | `/api/v1/agents/` | `src/routes/aro_agent_routes.py` | `register_agent` |
| GET | `/api/v1/agents/<int:agent_id>` | `src/routes/aro_agent_routes.py` | `get_agent` |
| DELETE | `/api/v1/agents/<int:agent_id>` | `src/routes/aro_agent_routes.py` | `delete_agent` |
| POST | `/api/v1/agents/<int:agent_id>/ready` | `src/routes/aro_agent_routes.py` | `ready_agent` |
| POST | `/api/v1/agents/<int:agent_id>/start` | `src/routes/aro_agent_routes.py` | `start_agent` |
| POST | `/api/v1/agents/<int:agent_id>/stop` | `src/routes/aro_agent_routes.py` | `stop_agent` |
| POST | `/api/v1/agents/<int:agent_id>/restart` | `src/routes/aro_agent_routes.py` | `restart_agent` |
| GET | `/api/v1/agents/<int:agent_id>/status` | `src/routes/aro_agent_routes.py` | `agent_status` |

### `aro_runtime_routes.py` (prefix `/api/v1/agents`)

| Method | Path | Source File | Handler |
|--------|------|-------------|---------|
| GET | `/api/v1/agents/runtimes` | `src/routes/aro_runtime_routes.py` | `list_runtimes` |
| POST | `/api/v1/agents/runtimes` | `src/routes/aro_runtime_routes.py` | `register_runtime` |
| GET | `/api/v1/agents/runtimes/<int:runtime_id>` | `src/routes/aro_runtime_routes.py` | `get_runtime` |
| GET | `/api/v1/agents/runtimes/<int:runtime_id>/health` | `src/routes/aro_runtime_routes.py` | `runtime_health` |

> Note: `aro_task_routes.py`, `aro_agent_routes.py`, and `aro_runtime_routes.py` all share the blueprint prefix `/api/v1/agents`. The sub-paths (`/tasks`, `/runtimes`, `/<int:agent_id>`) keep them from colliding, but this shared prefix across three blueprints is worth flagging for the dependency/duplication analyses.

### `zaf_governance_routes.py` (prefix `/api/v1/governance`)

| Method | Path | Source File | Handler |
|--------|------|-------------|---------|
| POST | `/api/v1/governance/policies` | `src/routes/zaf_governance_routes.py` | `create_policy` |
| GET | `/api/v1/governance/policies` | `src/routes/zaf_governance_routes.py` | `list_policies` |
| POST | `/api/v1/governance/evaluate` | `src/routes/zaf_governance_routes.py` | `evaluate` |
| GET | `/api/v1/governance/decisions` | `src/routes/zaf_governance_routes.py` | `list_decisions` |
| GET | `/api/v1/governance/approvals` | `src/routes/zaf_governance_routes.py` | `list_approvals` |
| POST | `/api/v1/governance/approvals/<int:approval_id>/approve` | `src/routes/zaf_governance_routes.py` | `approve_request` |
| POST | `/api/v1/governance/approvals/<int:approval_id>/reject` | `src/routes/zaf_governance_routes.py` | `reject_request` |

### `obs_routes.py` (prefix `/api/v1/observability`)

| Method | Path | Source File | Handler |
|--------|------|-------------|---------|
| GET | `/api/v1/observability/events` | `src/routes/obs_routes.py` | `list_events` |
| GET | `/api/v1/observability/metrics` | `src/routes/obs_routes.py` | `metrics` |
| GET | `/api/v1/observability/anomalies` | `src/routes/obs_routes.py` | `anomalies` |
| GET | `/api/v1/observability/incidents` | `src/routes/obs_routes.py` | `incidents` |
| GET | `/api/v1/observability/agents/<path:identity>/timeline` | `src/routes/obs_routes.py` | `agent_timeline` |
| GET | `/api/v1/observability/agents/<path:identity>/risk` | `src/routes/obs_routes.py` | `agent_risk` |

### `orchestrator_routes.py` (prefix `/api/orchestrator`)

| Method | Path | Source File | Handler |
|--------|------|-------------|---------|
| GET | `/api/orchestrator/user-applications` | `src/routes/orchestrator_routes.py` | `get_user_applications` |
| GET | `/api/orchestrator/git-urls` | `src/routes/orchestrator_routes.py` | `get_git_urls` |
| GET | `/api/orchestrator/services` | `src/routes/orchestrator_routes.py` | `list_services` |
| GET | `/api/orchestrator/services/<service_name>` | `src/routes/orchestrator_routes.py` | `get_service` |
| POST | `/api/orchestrator/services` | `src/routes/orchestrator_routes.py` | `create_service` |
| PUT | `/api/orchestrator/services/<service_name>` | `src/routes/orchestrator_routes.py` | `update_service` |
| POST | `/api/orchestrator/services/<service_name>/scale` | `src/routes/orchestrator_routes.py` | `scale_service` |
| DELETE | `/api/orchestrator/services/<service_name>` | `src/routes/orchestrator_routes.py` | `delete_service` |
| POST | `/api/orchestrator/health-check` | `src/routes/orchestrator_routes.py` | `trigger_health_check` |
| GET | `/api/orchestrator/nginx/config` | `src/routes/orchestrator_routes.py` | `get_nginx_config` |
| POST | `/api/orchestrator/nginx/reload` | `src/routes/orchestrator_routes.py` | `reload_nginx` |
| POST | `/api/orchestrator/reconcile` | `src/routes/orchestrator_routes.py` | `trigger_reconciliation` |
| GET | `/api/orchestrator/status` | `src/routes/orchestrator_routes.py` | `orchestrator_status` |
| POST | `/api/orchestrator/services/multi-user-deploy` | `src/routes/orchestrator_routes.py` | `multi_user_deploy` |

### `security_routes.py` (prefix `/security`)

| Method | Path | Source File | Handler |
|--------|------|-------------|---------|
| POST | `/security/password-reset/request` | `src/routes/security_routes.py` | `request_password_reset` |
| GET | `/security/password-reset/<token>` | `src/routes/security_routes.py` | `password_reset_page` |
| POST | `/security/password-reset/<token>` | `src/routes/security_routes.py` | `password_reset_submit` |
| POST | `/security/change-password` | `src/routes/security_routes.py` | `change_password` |
| POST | `/security/2fa/setup` | `src/routes/security_routes.py` | `setup_2fa` |
| POST | `/security/2fa/verify-setup` | `src/routes/security_routes.py` | `verify_2fa_setup` |
| POST | `/security/2fa/disable` | `src/routes/security_routes.py` | `disable_2fa` |
| POST | `/security/2fa/enable-email` | `src/routes/security_routes.py` | `enable_2fa_email` |
| POST | `/security/2fa/send-email-code` | `src/routes/security_routes.py` | `send_2fa_email_code` |
| POST | `/security/2fa/verify-login` | `src/routes/security_routes.py` | `verify_2fa_login` |
| GET | `/security/2fa/status` | `src/routes/security_routes.py` | `get_2fa_status` |
| GET | `/security/2fa/admin-status/<int:user_id>` | `src/routes/security_routes.py` | `get_2fa_admin_status` |

---

### `main_routes.py` (no prefix)

| Method | Path | Source File | Handler |
|--------|------|-------------|---------|
| GET | `/` | `src/routes/main_routes.py` | `index` |
| GET | `/dashboard` | `src/routes/main_routes.py` | `dashboard` |
| GET | `/set_language/<language>` | `src/routes/main_routes.py` | `set_language` |
| GET | `/docs` | `src/routes/main_routes.py` | `docs` |
| GET | `/docs/<filename>` | `src/routes/main_routes.py` | `view_doc` |
| GET | `/userguide` | `src/routes/main_routes.py` | `userguide` |
| GET | `/favicon.ico` | `src/routes/main_routes.py` | `favicon` |
| GET | `/servers/<int:server_id>/gpu` | `src/routes/main_routes.py` | `shared_gpu_page` |
| GET | `/.well-known/pki-validation/<filename>` | `src/routes/main_routes.py` | `ssl_validation` |

### `auth_routes.py` (no prefix)

| Method | Path | Source File | Handler |
|--------|------|-------------|---------|
| GET, POST | `/register` | `src/routes/auth_routes.py` | `register` |
| POST | `/login` | `src/routes/auth_routes.py` | `login` |
| GET | `/logout` | `src/routes/auth_routes.py` | `logout` |
| POST | `/auth/sso` | `src/routes/auth_routes.py` | `auth_sso` |

### `sso_routes.py` (prefix `/sso`)

| Method | Path | Source File | Handler |
|--------|------|-------------|---------|
| POST | `/sso/validate` | `src/routes/sso_routes.py` | `sso_validate` |
| GET | `/sso/app/<app_name>` | `src/routes/sso_routes.py` | `sso_app_login` |
| GET | `/sso/auth` | `src/routes/sso_routes.py` | `sso_auth` |
| GET | `/sso/login` | `src/routes/sso_routes.py` | `sso_login_page` |
| POST | `/sso/authenticate` | `src/routes/sso_routes.py` | `sso_authenticate` |

### `api_routes.py` (prefix `/api`)

| Method | Path | Source File | Handler |
|--------|------|-------------|---------|
| GET | `/api/auth/status` | `src/routes/api_routes.py` | `auth_status` |
| GET | `/api/health/database` | `src/routes/api_routes.py` | `database_health` |
| GET, POST | `/api/applications` | `src/routes/api_routes.py` | `api_applications` |
| GET | `/api/applications/pdf-data` | `src/routes/api_routes.py` | `api_applications_pdf_data` |
| GET | `/api/applications/available` | `src/routes/api_routes.py` | `api_available_applications` |
| PUT, DELETE | `/api/applications/<int:app_id>` | `src/routes/api_routes.py` | `api_application_actions` |
| GET, POST | `/api/users` | `src/routes/api_routes.py` | `api_users` |
| GET | `/api/users/id` | `src/routes/api_routes.py` | `api_user_id_by_username` |
| PUT, DELETE | `/api/users/<int:user_id>` | `src/routes/api_routes.py` | `api_user_actions` |
| GET, POST, DELETE | `/api/users/<int:user_id>/applications` | `src/routes/api_routes.py` | `api_user_applications` |
| GET, POST | `/api/database/tables/<table_name>` | `src/routes/api_routes.py` | `api_database_table` |
| GET | `/api/platform/status` | `src/routes/api_routes.py` | `platform_status` |
| POST | `/api/platform/servers/add` | `src/routes/api_routes.py` | `platform_servers_add` |
| POST | `/api/servers/discover` | `src/routes/api_routes.py` | `api_servers_discover` |
| POST | `/api/servers/add-remote` | `src/routes/api_routes.py` | `api_servers_add_remote` |
| GET, POST | `/api/servers` | `src/routes/api_routes.py` | `api_servers` |
| PUT, DELETE | `/api/servers/<int:server_id>` | `src/routes/api_routes.py` | `api_server_actions` |
| POST | `/api/servers/<int:server_id>/promote` | `src/routes/api_routes.py` | `api_server_promote` |
| POST | `/api/servers/<int:server_id>/promote-secondary` | `src/routes/api_routes.py` | `api_server_promote_secondary` |
| POST | `/api/servers/<int:server_id>/sync` | `src/routes/api_routes.py` | `api_server_sync` |
| POST | `/api/server/allocate` | `src/routes/api_routes.py` | `api_server_allocate` |
| PUT, DELETE | `/api/database/tables/<table_name>/<record_id>` | `src/routes/api_routes.py` | `api_database_record` |
| GET, POST | `/api/deployments` | `src/routes/api_routes.py` | `api_deployments` |
| GET | `/api/deployments/<int:deployment_id>/logs` | `src/routes/api_routes.py` | `api_deployment_logs` |
| POST | `/api/nginx/sync` | `src/routes/api_routes.py` | `api_nginx_sync` |
| GET | `/api/replication/queue` | `src/routes/api_routes.py` | `api_replication_queue` |
| GET, POST | `/api/configuration` | `src/routes/api_routes.py` | `api_configuration` |
| PUT, DELETE | `/api/configuration/<int:param_id>` | `src/routes/api_routes.py` | `api_configuration_actions` |
| GET | `/api/deployments/all` | `src/routes/api_routes.py` | `api_deployments_all` |
| DELETE | `/api/deployments/<int:deployment_id>` | `src/routes/api_routes.py` | `api_deployment_delete` |
| POST | `/api/nginx/update-deployment` | `src/routes/api_routes.py` | `api_nginx_update_deployment` |
| GET | `/api/deployments/<app_name>/gitea` | `src/routes/api_routes.py` | `api_deployment_gitea` |
| POST | `/api/deployments/<app_name>/gitea/branch` | `src/routes/api_routes.py` | `api_deployment_gitea_branch` |
| POST | `/api/deployments/<int:deployment_id>/backup` | `src/routes/api_routes.py` | `api_deployment_add_backup` |
| GET | `/api/deployments/<int:deployment_id>/backups` | `src/routes/api_routes.py` | `api_deployment_get_backups` |

### `genai_routes.py` (prefix `/api`)

| Method | Path | Source File | Handler |
|--------|------|-------------|---------|
| GET | `/api/deployments/<int:deployment_id>/logs` | `src/routes/genai_routes.py` | `api_deployment_logs` |
| POST | `/api/request_dev_ai_for_app` | `src/routes/genai_routes.py` | `api_request_dev_ai_for_app` |
| POST | `/api/request_ops_ai_for_app` | `src/routes/genai_routes.py` | `api_request_ops_ai_for_app` |

> Note (potential collision): `genai_routes.py` and `api_routes.py` share the `/api` prefix and **both** register `GET /api/deployments/<int:deployment_id>/logs` with a handler named `api_deployment_logs`. This duplicate path/handler pairing is flagged for the duplication report (artifact 08).

### `agent_control_routes.py` (prefix `/api`)

| Method | Path | Source File | Handler |
|--------|------|-------------|---------|
| GET | `/api/agent-control/containers` | `src/routes/agent_control_routes.py` | `list_containers` |

### `sandbox_routes.py` (prefix `/api`)

| Method | Path | Source File | Handler |
|--------|------|-------------|---------|
| POST | `/api/sandbox/provision` | `src/routes/sandbox_routes.py` | `provision_sandbox` |
| POST | `/api/sandbox/reset` | `src/routes/sandbox_routes.py` | `reset_sandbox` |
| POST | `/api/sandbox/teardown` | `src/routes/sandbox_routes.py` | `teardown_sandbox` |
| GET | `/api/sandbox/status` | `src/routes/sandbox_routes.py` | `sandbox_status` |

### `templates_routes.py` (prefix `/api`)

| Method | Path | Source File | Handler |
|--------|------|-------------|---------|
| GET | `/api/templates` | `src/routes/templates_routes.py` | `list_templates` |
| POST | `/api/templates/<template_id>/deploy` | `src/routes/templates_routes.py` | `deploy_template` |

### `serverless_routes.py` (prefix `/api`)

| Method | Path | Source File | Handler |
|--------|------|-------------|---------|
| GET | `/api/serverless-links` | `src/routes/serverless_routes.py` | `get_serverless_links` |
| POST | `/api/jobs` | `src/routes/serverless_routes.py` | `submit_job` |
| GET | `/api/jobs` | `src/routes/serverless_routes.py` | `list_jobs` |
| GET | `/api/jobs/metrics` | `src/routes/serverless_routes.py` | `get_metrics` |
| GET | `/api/jobs/<job_id>` | `src/routes/serverless_routes.py` | `get_job_status` |
| GET | `/api/jobs/<job_id>/result` | `src/routes/serverless_routes.py` | `get_job_result` |
| POST | `/api/jobs/<job_id>/cancel` | `src/routes/serverless_routes.py` | `cancel_job` |

### `wizard_routes.py` (prefix `/api/wizard`)

| Method | Path | Source File | Handler |
|--------|------|-------------|---------|
| GET | `/api/wizard/steps` | `src/routes/wizard_routes.py` | `get_steps` |
| GET | `/api/wizard/state` | `src/routes/wizard_routes.py` | `get_state` |
| POST | `/api/wizard/step/<step>` | `src/routes/wizard_routes.py` | `submit_step` |
| POST | `/api/wizard/ssl/generate` | `src/routes/wizard_routes.py` | `ssl_generate` |
| POST | `/api/wizard/ssl/upload` | `src/routes/wizard_routes.py` | `ssl_upload` |
| POST | `/api/wizard/reset` | `src/routes/wizard_routes.py` | `reset` |

### `billing_routes.py` (no prefix; paths include `/api/billing`)

| Method | Path | Source File | Handler |
|--------|------|-------------|---------|
| GET | `/api/billing/activities` | `src/routes/billing_routes.py` | `get_billing_activities` |
| GET | `/api/billing/summary` | `src/routes/billing_routes.py` | `get_billing_summary` |
| GET | `/api/billing/costs` | `src/routes/billing_routes.py` | `get_application_costs` |
| PUT | `/api/billing/costs/<int:app_id>` | `src/routes/billing_routes.py` | `update_application_cost` |
| GET | `/api/billing/invoices` | `src/routes/billing_routes.py` | `get_invoices` |
| GET | `/api/billing/users` | `src/routes/billing_routes.py` | `get_billing_users` |
| GET | `/api/billing/invoices/months` | `src/routes/billing_routes.py` | `get_available_months` |
| POST | `/api/billing/invoices/generate` | `src/routes/billing_routes.py` | `generate_invoice` |
| GET | `/api/billing/invoices/<int:invoice_id>/pdf` | `src/routes/billing_routes.py` | `generate_invoice_pdf` |
| PUT | `/api/billing/invoices/<int:invoice_id>/pay` | `src/routes/billing_routes.py` | `mark_invoice_paid` |
| GET | `/api/billing/debug/<month>` | `src/routes/billing_routes.py` | `debug_billing_data` |

### `replication_routes.py` (no prefix; paths include `/api/sync`)

| Method | Path | Source File | Handler |
|--------|------|-------------|---------|
| POST | `/api/sync/replicate` | `src/routes/replication_routes.py` | `receive_replication` |
| GET | `/api/sync/health` | `src/routes/replication_routes.py` | `sync_health` |
| GET | `/api/sync/status` | `src/routes/replication_routes.py` | `sync_status` |

### `gpu_routes.py` (prefix `/api/servers/<int:server_id>/gpu`)

| Method | Path | Source File | Handler |
|--------|------|-------------|---------|
| GET | `/api/servers/<int:server_id>/gpu/profiles` | `src/routes/gpu_routes.py` | `get_profiles` |
| GET | `/api/servers/<int:server_id>/gpu/instances` | `src/routes/gpu_routes.py` | `get_instances` |
| POST | `/api/servers/<int:server_id>/gpu/instances` | `src/routes/gpu_routes.py` | `create_instances` |
| PUT | `/api/servers/<int:server_id>/gpu/enabled` | `src/routes/gpu_routes.py` | `set_shared_gpu_enabled` |
| DELETE | `/api/servers/<int:server_id>/gpu/instances` | `src/routes/gpu_routes.py` | `delete_instances` |

## Ambiguities and notes

- **No dynamically built routes.** A grep for `add_url_rule` across `src/routes/*.py` returned no matches; every route is declared statically via a `@<bp>.route(...)` decorator, so there are no ambiguous/dynamic routes to flag. (Had any existed, the audit method records them as ambiguous rather than omitting them.)
- **Shared `/api/v1/agents` prefix** across `aro_task_routes.py`, `aro_agent_routes.py`, and `aro_runtime_routes.py` — three blueprints under one prefix; no path collisions, but flagged for the dependency map.
- **Duplicate `/api/deployments/<int:deployment_id>/logs` (GET, handler `api_deployment_logs`)** defined in both `api_routes.py` and `genai_routes.py` under the shared `/api` prefix — forwarded to the duplication report (artifact 08).
- **Non-route modules:** `src/routes/__init__.py`, `src/routes/aro_common.py` (shared decorators `tenant_scoped` / `role_required`), and `src/routes/engine_runner.py` define no HTTP routes; inspected and recorded for completeness (R11.1).
- **Method default:** every row without an explicit `methods=` list (e.g. `main_routes.py`, several `billing_routes.py` entries, `genai_routes.py` logs) is recorded as `GET` per the Flask default.
