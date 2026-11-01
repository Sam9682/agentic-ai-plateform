# 08 — Duplication and Obsolete Component Report

- **Title:** Duplication and Obsolete Component Report
- **Audit date:** 2026-10-31
- **Requirement coverage:** R8.1, R8.2, R8.3, R8.4, R11.1, R11.3
- **Method:** Candidate pairs/groups were identified three ways: (1) **similar names** — files sharing a stem that differ only by a suffix such as `_postgres`, `_fixed`, or `_nginx`; (2) **overlapping responsibilities** — modules whose docstrings/responsibilities cover the same concern (e.g. two reverse-proxy config managers); (3) **parallel implementations / repository–service pairings** inside the subsystems. Obsolescence was judged from the dead-module / no-inbound-import edge set in `docs/audit/02-dependency-map.md` (task 1) combined with direct inspection of which entry point the deployment path (`wsgi.py`, `deployControlPlan.sh`, `Dockerfile*`) actually uses. All inspection was read/search only; no source, migration, test, or infrastructure file was modified, and no live service was started.
- **Inputs consumed:**
  - `docs/audit/02-dependency-map.md` (task 1) — "Dead / Entry-Point Modules (no inbound `src/` imports)" list and the full 211-edge import set.
  - `docs/audit/04-api-inventory.md` (task 4) — the duplicate route finding `GET /api/deployments/<int:deployment_id>/logs` (handler `api_deployment_logs`) declared in **both** `routes/api_routes.py` and `routes/genai_routes.py` under the shared `/api` prefix.

## Inspected Sources

All modules under `src/` were inspected (the exhaustive 94-file `*.py` list is enumerated in `docs/audit/02-dependency-map.md` and is incorporated here by reference for R11.1). In addition, because duplication/obsolescence spans the entry-point and bootstrap layer that lives at the repository root, the following non-`src/` files were also inspected for this artifact:

- Root entry points / shims: `ControlPlanFlaskApp.py`, `wsgi.py`, `main.py` (via `src/main.py`).
- Bootstrap scripts: `init_pltf.sh`, `init_pltf_fixed.sh`.
- Deployment descriptors cross-checked to establish the canonical entry point: `deployControlPlan.sh`, `Dockerfile`, `Dockerfile.postgres`.

### Grouping used for the per-subsystem "no finding" record

Findings and the explicit "no finding" lines below are organized against the five audited subsystems from `docs/audit/01-architecture-diagram.md`: **ARO**, **ZAF**, **OBS**, **Infrastructure Orchestrator**, **Agent Supervisor**. Entry-point / bootstrap duplication that is not owned by any single subsystem is recorded under a separate **Platform entry-point & bootstrap** heading.

## Duplications

| Group | Files Involved | Nature of Duplication |
|-------|----------------|-----------------------|
| App entry point | `ControlPlanFlaskApp.py` (repo root, 5 lines), `src/ControlPlanFlaskApp_postgres.py` (126 lines), `wsgi.py`, `src/main.py` | **Parallel entry points for the same Flask app.** `ControlPlanFlaskApp.py` is a thin shim (`from src.main import main`); `wsgi.py` imports `create_app`/`init_db` from `src/ControlPlanFlaskApp_postgres.py`; `src/main.py` is the modular launcher. Three distinct ways to start the one application — the real app factory lives only in `ControlPlanFlaskApp_postgres.py`. Similar-name + overlapping-responsibility duplication. |
| Bootstrap script | `init_pltf.sh`, `init_pltf_fixed.sh` | **Parallel implementations of the platform bootstrap.** Both are 521 lines; a line-by-line comparison shows 139 differing lines (the `_fixed` variant reworks the Docker/Kata install and submodule-URL resolution blocks). Classic `_fixed` fork kept alongside the original. Similar-name duplication. |
| Reverse-proxy config manager | `src/frontend_manager.py` (Traefik), `src/frontend_nginx_manager.py` (nginx) | **Overlapping responsibility — two reverse-proxy managers.** Both expose location-block/route management for the same concern, but `frontend_manager.py` emits Traefik dynamic config (and is imported by `api_routes.py`, `sandbox_manager.py`, `template_deploy.py`) while `frontend_nginx_manager.py` writes nginx `sites-available`/`sites-enabled` files. The platform has migrated to Traefik (see `orchestrator.py` Traefik labels, `api_routes.py` comment "The reverse proxy is now Traefik"), so these are the before/after implementations of one responsibility. |
| Deployment logs route | `src/routes/api_routes.py`, `src/routes/genai_routes.py` | **Duplicate route + handler.** Both blueprints share the `/api` prefix and each registers `GET /api/deployments/<int:deployment_id>/logs` with a handler named `api_deployment_logs` (carried over from task 4). Two definitions of the same path/handler; last-registered blueprint wins at runtime, so one is effectively shadowed. |

> **Hypothesis checked and rejected.** The task's example `config_postgres.py` vs `config.py` was tested by file search: **no `config.py` exists** anywhere in the tree. The only config modules are `src/config_postgres.py` (the fan-in-20 config hub) and `src/gitea_config.py` (a distinct Gitea-specific config). There is therefore **no** `config.py`/`config_postgres.py` duplication to report. The repository/service names in ARO/ZAF (`*_repository.py` + `*_service.py`) are a deliberate layering pattern, not duplication — see the per-subsystem notes below.

## Obsolete

| Component | Source File | Why Obsolete |
|-----------|-------------|--------------|
| Nginx reverse-proxy manager | `src/frontend_nginx_manager.py` | Superseded by the Traefik-based `frontend_manager.py`. Has **no inbound `src/` import** (task 1 dead-module list) and targets `/etc/nginx/sites-available` / `sites-enabled`; the platform now routes through Traefik (shared `swautomorph-shared` network + Traefik labels in `orchestrator.py`). Legacy nginx implementation left behind by the nginx→Traefik migration. |
| Root app shim | `ControlPlanFlaskApp.py` | Superseded by the `wsgi:application` / `src/ControlPlanFlaskApp_postgres.py` path used by production (`deployControlPlan.sh` runs `gunicorn … wsgi:application`; `Dockerfile.postgres` runs `src/ControlPlanFlaskApp_postgres.py`). Only the legacy `Dockerfile` still references this shim (`FLASK_APP=ControlPlanFlaskApp.py`). Candidate obsolete entry point kept for backward compatibility. |
| `_fixed` bootstrap fork | `init_pltf_fixed.sh` | A `_fixed` variant of `init_pltf.sh`. One of the two is stale by definition — a forked copy rather than an edit-in-place — and should be reconciled into a single bootstrap script. Which is canonical is not determinable from imports (shell scripts are invoked, not imported); flagged for human reconciliation. |
| Legacy `Dockerfile` | `Dockerfile` | Points at the obsolete root shim (`ControlPlanFlaskApp.py`, Flask dev server) whereas `Dockerfile.postgres` is the Postgres/production image. Candidate obsolete build descriptor; cross-referenced here only because it keeps the root shim alive. |

### Candidate dead modules carried from task 1 — classified

Task 1 handed four "candidate dead" `src/` modules to this stage (no inbound import, but not entry points). They are classified here as **not obsolete** — each is reached by a non-import mechanism or is a not-yet-wired feature rather than superseded code:

- `src/aro/execution_manager.py`, `src/aro/runtime_scanner.py` — invoked as worker/scan tasks, not imported; **not obsolete** (hand to the Gap Matrix as integration questions, not duplication).
- `src/obs/anomaly_engine.py` — OBS anomaly engine, not yet wired into a route/worker; **not-yet-integrated**, not superseded.
- `src/zaf/mcp_gateway.py`, `src/zaf/infra_proxy.py`, `src/zaf/response_service.py`, `src/zaf/credential_vault.py` — ZAF enforcement/response components with no inbound import; **PARTIALLY_INTEGRATED candidates** per task 1, not obsolete duplicates.

These are recorded as "not a duplication/obsolescence finding" so they are not double-counted against the Gap Matrix (task 10), which owns the integration classification.

## Per-Subsystem Findings

The four root-level duplications/obsolescence items above (app entry points, bootstrap scripts, nginx manager, deployment-logs route, Dockerfile) sit in the **platform entry-point & bootstrap** and **shared HTTP/proxy** layers rather than inside a single subsystem. For each of the five audited subsystems, the specific finding or the explicit no-finding line follows.

- **ARO** — The `*_repository.py` / `*_service.py` pairings (`agent_repository`+`lifecycle_service`, `runtime_registry_repository`+`runtime_registry_service`, `task_repository`, `events_repository`+`event_service`) are a deliberate data-access / service layering, not duplication; each repository and its service have distinct responsibilities per the task-1 adjacency list. **No identified duplication or obsolescence.**
- **ZAF** — No duplicated or superseded ZAF modules. The four no-inbound-import enforcement components (`mcp_gateway`, `infra_proxy`, `response_service`, `credential_vault`) are integration gaps owned by the Gap Matrix, not obsolete code. **No identified duplication or obsolescence.**
- **OBS** — `obs/` and `runtime_monitor/` cover distinct concerns (anomaly/risk scoring vs runtime collection/classification) with no overlapping or `_fixed`/`_postgres` variants. `anomaly_engine.py`'s lack of inbound imports is an integration gap, not obsolescence. **No identified duplication or obsolescence.**
- **Infrastructure Orchestrator** — `orchestrator.py`, `sandbox_manager.py`, `platform_discovery.py`, and the `serverless/` package are each singular; no parallel `_fixed`/`_postgres` implementations. (The Traefik/nginx proxy-manager duplication is attributed to the shared HTTP/proxy layer above, not to this subsystem.) **No identified duplication or obsolescence.**
- **Agent Supervisor** — `aro/agent_worker.py` and `agent_control_service.py` are singular implementations with no sibling variants. **No identified duplication or obsolescence.**

## Summary

- **Duplications: 4 groups** — parallel app entry points (`ControlPlanFlaskApp.py` / `ControlPlanFlaskApp_postgres.py` / `wsgi.py` / `main.py`), parallel bootstrap scripts (`init_pltf.sh` / `init_pltf_fixed.sh`), two reverse-proxy managers (Traefik `frontend_manager.py` / nginx `frontend_nginx_manager.py`), and the duplicate `/api/deployments/<int:deployment_id>/logs` route/handler across `api_routes.py` and `genai_routes.py`.
- **Obsolete: 4 components** — `frontend_nginx_manager.py` (nginx→Traefik migration leftover, no inbound import), `ControlPlanFlaskApp.py` (root shim superseded by `wsgi:application`), `init_pltf_fixed.sh` (`_fixed` fork), and the legacy `Dockerfile` (points at the obsolete shim).
- The task example `config_postgres.py` vs `config.py` is **not** a real duplication — no `config.py` exists.
- All five subsystems carry an explicit per-subsystem line; the substantive findings live in the shared entry-point/bootstrap and HTTP/proxy layers.
- Recommended consolidation targets for the implementation plan (task 11, Phase 1 "foundation/consolidation"): collapse to a single entry point (`wsgi:application` + `ControlPlanFlaskApp_postgres.create_app`), retire `frontend_nginx_manager.py`, reconcile the two `init_pltf*.sh` scripts, and de-duplicate the `api_deployment_logs` route.
