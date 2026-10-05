# Implementation Plan

## Overview

Implementation of the Serverless Docker Execution Service feature for the agentic-ai-plateform platform. This adds job submission, worker-based execution, container runtime abstraction, dashboard UI, and monitoring.

## Task Dependency Graph

```json
{
  "waves": [
    {"wave": 1, "tasks": [1]},
    {"wave": 2, "tasks": [2]},
    {"wave": 3, "tasks": [3, 10]},
    {"wave": 4, "tasks": [4, 5]},
    {"wave": 5, "tasks": [6, 9, 11, 12]},
    {"wave": 6, "tasks": [7]},
    {"wave": 7, "tasks": [8]}
  ]
}
```

## Tasks

- [x] 1. Database Migration
  - [x] 1.1 Create `migration/add_serverless_jobs.sql` with the `serverless_jobs`, `serverless_job_logs`, and `serverless_job_results` tables including all columns, constraints, and indexes as defined in the design document
  - [x] 1.2 Add migration execution to `init_db()` in `src/database_postgres.py` to apply the serverless jobs schema on startup (with error handling for already-applied migrations)

- [x] 2. Serverless Configuration {depends_on: [1]}
  - [x] 2.1 Create `src/serverless/__init__.py` package init file
  - [x] 2.2 Create `src/serverless/config.py` with `SERVERLESS_CONFIG` dictionary containing registry_whitelist, default_timeout, max_timeout, default_memory_limit, default_cpu_limit, max_concurrent_jobs, log_retention_days, poll_interval, container_stop_timeout, warm_pool_enabled, and warm_pool_size
  - [x] 2.3 Create `conf/serverless.ini` configuration file for runtime-configurable settings (registry whitelist, resource limits)

- [x] 3. Container Runtime Abstraction {depends_on: [2]}
  - [x] 3.1 Create `src/serverless/container_runtime.py` with the abstract `ContainerRuntime` base class defining methods: `pull_image`, `run_container`, `stop_container`, `get_logs`, `wait`, `cleanup`, and a static `detect()` method
  - [x] 3.2 Implement `DockerRuntime` class in `container_runtime.py` that executes Docker CLI commands with security flags (--read-only, --user nobody, --cap-drop ALL, --memory, --cpus, --network none, --security-opt no-new-privileges, --pids-limit 256)
  - [x] 3.3 Implement `PodmanRuntime` class in `container_runtime.py` that mirrors DockerRuntime but uses the `podman` binary
  - [x] 3.4 Implement the `detect()` static method that checks which runtime is available (Docker first, then Podman) and returns the appropriate instance

- [ ] 4. Worker Service {depends_on: [3, 10]}
  - [x] 4.1 Create `src/serverless/worker.py` with the `ServerlessWorker` class containing `__init__`, `run`, `claim_next_job`, `execute_job`, `store_result`, `mark_completed`, `mark_failed`, `mark_timeout` methods
  - [x] 4.2 Implement `claim_next_job` using `SELECT ... FOR UPDATE SKIP LOCKED` pattern to atomically claim pending jobs from the queue
  - [x] 4.3 Implement `execute_job` with the full lifecycle: validate registry whitelist, pull image, run container with security constraints, wait with timeout, capture stdout/stderr, store logs and results, update job status
  - [-] 4.4 Implement job cancellation detection: worker checks for cancelled status during execution and stops the container within 10 seconds
  - [x] 4.5 Implement `__main__` entry point in `worker.py` for running as `python -m src.serverless.worker` with signal handling (SIGTERM/SIGINT for graceful shutdown)
  - [x] 4.6 Create `src/serverless/log_cleanup.py` with a function to delete job_logs and completed jobs older than 30 days, integrated into the worker's daily schedule

- [ ] 5. Serverless API Routes {depends_on: [1, 2, 10]}
  - [x] 5.1 Create `src/routes/serverless_routes.py` with a Flask Blueprint `serverless_bp` registered at url_prefix `/api`
  - [x] 5.2 Implement `POST /api/jobs` endpoint: validate auth, validate payload (image, command required; env, timeout optional), validate image against registry whitelist, validate timeout range (1-3600), insert job record, return job_id with 201 status
  - [x] 5.3 Implement `GET /api/jobs/<job_id>` endpoint: validate auth, check ownership (owner or admin), return job status and metadata, 404 for non-existent jobs
  - [x] 5.4 Implement `GET /api/jobs/<job_id>/result` endpoint: validate auth, check ownership, verify job is in terminal state (409 if not), return exit_code, stdout, stderr from job_logs, and result from job_results
  - [-] 5.5 Implement `POST /api/jobs/<job_id>/cancel` endpoint: validate auth, check ownership, verify job is in cancellable state (pending/running), update status to cancelled, return 409 for terminal-state jobs
  - [x] 5.6 Implement `GET /api/jobs` endpoint: validate auth, return paginated list of user's jobs (admin sees all), support `?status=` filter and `?page=`/`?per_page=` pagination
  - [x] 5.7 Implement `GET /api/jobs/metrics` endpoint: admin-only, return counts of pending/running/failed jobs, average execution time, queue depth, and average container startup duration

- [x] 6. Flask App Integration {depends_on: [5]}
  - [x] 6.1 Register `serverless_bp` in `src/ControlPlanFlaskApp_postgres.py` by adding the import and `app.register_blueprint(serverless_bp)` call

- [x] 7. Dashboard UI - Menu and Section {depends_on: [6]}
  - [x] 7.1 Add "Application Orchestrator" as a new top-level navigation item in `templates/base.html` (with 🚀 icon), wired to show `orchestratorServerlessSection`
  - [x] 7.2 Add `orchestratorServerlessSection` div in `templates/dashboard.html` with: job list table (columns: ID, image, status, created_at, actions), job submission form (fields: image, command, env as JSON, timeout), job detail/result view panel, and metrics summary panel
  - [x] 7.3 Add CSS styles for job status badges (color-coded: pending=gray, running=blue, completed=green, failed=red, timeout=orange, cancelled=yellow)

- [x] 8. Dashboard UI - JavaScript Functions {depends_on: [7]}
  - [x] 8.1 Add `submitServerlessJob()` function in `templates/dashboard_functions.js` that POSTs to `/api/jobs` and refreshes the job list
  - [x] 8.2 Add `refreshJobList()` function that GETs `/api/jobs` and renders the job table with status badges
  - [x] 8.3 Add `viewJobDetail(jobId)` function that GETs `/api/jobs/{id}` and `/api/jobs/{id}/result` and displays in the detail panel
  - [x] 8.4 Add `cancelJob(jobId)` function that POSTs to `/api/jobs/{id}/cancel` with confirmation dialog
  - [x] 8.5 Add `loadServerlessMetrics()` function that GETs `/api/jobs/metrics` and renders the metrics panel
  - [x] 8.6 Add auto-refresh timer (5 second interval) for the job list when the orchestrator section is visible

- [x] 9. Systemd Service Configuration {depends_on: [4]}
  - [x] 9.1 Create `systemd/serverless-worker.service` unit file with: Type=simple, WorkingDirectory pointing to the project root, ExecStart as `python3 -m src.serverless.worker`, Restart=always, RestartSec=5, Environment variables for WORKER_ID and PYTHONPATH, After=postgresql.service docker.service
  - [x] 9.2 Create `scripts/install_worker_service.sh` script that copies the service file to `/etc/systemd/system/`, runs daemon-reload, and enables the service

- [x] 10. Registry Whitelist Validation {depends_on: [2]}
  - [x] 10.1 Implement `validate_image_registry(image, whitelist)` function in `src/serverless/config.py` that parses a Docker image reference to extract the registry hostname and validates it against the configured whitelist (handling default docker.io for images without explicit registry)

- [x] 11. Monitoring and Logging Integration {depends_on: [4, 5]}
  - [x] 11.1 Add structured logging to all serverless API endpoints in `serverless_routes.py` (using the same pattern as existing routes: FileHandler + ConsoleHandler to `logs/serverless_routes.log`)
  - [x] 11.2 Add structured logging to the worker service with log rotation, logging job claim, execution start/end, and errors to `logs/serverless_worker.log`

- [x] 12. Integration Testing Setup {depends_on: [4, 5]}
  - [x] 12.1 Create `tests/test_serverless_routes.py` with tests for: job submission (valid/invalid), job status retrieval, job result retrieval, job cancellation, auth enforcement, registry whitelist rejection
  - [x] 12.2 Create `tests/test_container_runtime.py` with tests for: runtime detection, Docker command construction with security flags, Podman command construction
  - [x] 12.3 Create `tests/test_worker.py` with tests for: job claiming with FOR UPDATE SKIP LOCKED, job execution lifecycle, timeout handling, cancellation handling

## Notes

- Task 10 (Registry Whitelist Validation) is split from Task 2 because Task 4 and Task 5 both depend on it
- The Warm Pool feature (Requirement 14) is Phase 2 and not included in this implementation plan
- All tasks reference requirements and design from the spec documents
