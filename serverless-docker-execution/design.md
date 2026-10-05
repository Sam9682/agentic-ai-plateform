# Design Document

## Introduction

This document describes the technical design for the Serverless Docker Execution Service feature. The architecture follows the existing agentic-ai-plateform Docker AI patterns: Flask Blueprints for API routes, PostgreSQL via the shared `db_manager`, and systemd for service management. A new module `agentic-ai-plateform-serverless-brik` is introduced as the API layer, while a separate `serverless-worker.service` handles container execution.

## Architecture Overview

```
┌─────────────┐     ┌────────────────────────┐     ┌─────────────────┐
│ Web Client  │────▶│ Flask App (Gunicorn)    │────▶│ PostgreSQL      │
│ (Dashboard) │     │ - serverless_bp         │     │ - jobs table    │
└─────────────┘     │ - existing auth         │     │ - job_logs      │
                    └────────────────────────┘     │ - job_results   │
                                                    └────────┬────────┘
                                                             │
                                                    ┌────────▼────────┐
                                                    │ Worker Service  │
                                                    │ (systemd)       │
                                                    │ - poll queue    │
                                                    │ - execute jobs  │
                                                    └────────┬────────┘
                                                             │
                                                    ┌────────▼────────┐
                                                    │ Container       │
                                                    │ Runtime         │
                                                    │ (Docker/Podman) │
                                                    └─────────────────┘
```

## Database Schema

### New Tables

```sql
-- Job queue table
CREATE TABLE IF NOT EXISTS serverless_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id INTEGER NOT NULL REFERENCES users(id),
    image TEXT NOT NULL,
    command JSONB NOT NULL,
    environment JSONB DEFAULT '{}',
    timeout_seconds INTEGER NOT NULL DEFAULT 300 CHECK (timeout_seconds BETWEEN 1 AND 3600),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'completed', 'failed', 'timeout', 'cancelled')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    exit_code INTEGER,
    worker_id TEXT,
    CONSTRAINT fk_user FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Indexes for queue operations
CREATE INDEX idx_serverless_jobs_status ON serverless_jobs(status);
CREATE INDEX idx_serverless_jobs_user_id ON serverless_jobs(user_id);
CREATE INDEX idx_serverless_jobs_pending ON serverless_jobs(status, created_at) WHERE status = 'pending';

-- Job output logs (stdout/stderr streaming)
CREATE TABLE IF NOT EXISTS serverless_job_logs (
    id BIGSERIAL PRIMARY KEY,
    job_id UUID NOT NULL REFERENCES serverless_jobs(id) ON DELETE CASCADE,
    stream TEXT NOT NULL CHECK (stream IN ('stdout', 'stderr')),
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_serverless_job_logs_job_id ON serverless_job_logs(job_id, created_at);

-- Job structured results
CREATE TABLE IF NOT EXISTS serverless_job_results (
    job_id UUID PRIMARY KEY REFERENCES serverless_jobs(id) ON DELETE CASCADE,
    result JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Migration File

File: `migration/add_serverless_jobs.sql`

## API Design

### Blueprint Registration

New file: `src/routes/serverless_routes.py`

Registered in `ControlPlanFlaskApp_postgres.py`:
```python
from .routes.serverless_routes import serverless_bp
app.register_blueprint(serverless_bp)
```

### Endpoints

#### POST /api/jobs — Submit Job

```python
@serverless_bp.route('/jobs', methods=['POST'])
def submit_job():
    # Auth check
    # Validate payload: image, command (required), env, timeout (optional)
    # Validate image against registry whitelist
    # Insert into serverless_jobs with status='pending'
    # Return { "job_id": "<uuid>" }, 201
```

Request:
```json
{
    "image": "registry.example.com/myapp:latest",
    "command": ["python", "script.py"],
    "env": {"KEY": "value"},
    "timeout": 300
}
```

Response (201):
```json
{
    "job_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

#### GET /api/jobs/{job_id} — Job Status

```python
@serverless_bp.route('/jobs/<job_id>', methods=['GET'])
def get_job_status(job_id):
    # Auth check + ownership check (owner or admin)
    # Query serverless_jobs by id
    # Return job status and metadata
```

Response:
```json
{
    "job_id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "running",
    "image": "registry.example.com/myapp:latest",
    "created_at": "2024-01-15T10:30:00Z",
    "started_at": "2024-01-15T10:30:01Z",
    "completed_at": null,
    "exit_code": null,
    "worker_id": "worker-001"
}
```

#### GET /api/jobs/{job_id}/result — Job Result

```python
@serverless_bp.route('/jobs/<job_id>/result', methods=['GET'])
def get_job_result(job_id):
    # Auth check + ownership check
    # Verify job is in terminal state
    # Return exit_code, stdout, stderr, result
```

Response:
```json
{
    "exit_code": 0,
    "stdout": "output text...",
    "stderr": "",
    "result": {"key": "structured_output"}
}
```

#### POST /api/jobs/{job_id}/cancel — Cancel Job

```python
@serverless_bp.route('/jobs/<job_id>/cancel', methods=['POST'])
def cancel_job(job_id):
    # Auth check + ownership check
    # Verify job is in cancellable state (pending or running)
    # Update status to 'cancelled'
    # If running, signal worker to stop container
```

#### GET /api/jobs — List Jobs (for dashboard)

```python
@serverless_bp.route('/jobs', methods=['GET'])
def list_jobs():
    # Auth check
    # Query user's jobs with pagination
    # Admin sees all jobs
    # Support ?status= filter
```

### GET /api/jobs/metrics — Monitoring Metrics

```python
@serverless_bp.route('/jobs/metrics', methods=['GET'])
def get_metrics():
    # Auth check (admin only)
    # Return aggregated metrics
```

## Worker Service Design

### File Structure

```
src/
├── serverless/
│   ├── __init__.py
│   ├── worker.py            # Main worker loop
│   ├── container_runtime.py # Docker/Podman abstraction
│   ├── config.py            # Worker configuration
│   └── log_cleanup.py       # 30-day log purge
```

### Worker Main Loop (`worker.py`)

```python
class ServerlessWorker:
    def __init__(self, worker_id, runtime, db_config, registry_whitelist):
        self.worker_id = worker_id
        self.runtime = runtime  # ContainerRuntime instance
        self.running = True
    
    def run(self):
        """Main polling loop"""
        while self.running:
            job = self.claim_next_job()
            if job:
                self.execute_job(job)
            else:
                time.sleep(0.5)  # Short sleep when queue empty
    
    def claim_next_job(self):
        """Claim a pending job using FOR UPDATE SKIP LOCKED"""
        # SELECT * FROM serverless_jobs 
        # WHERE status = 'pending' 
        # ORDER BY created_at ASC 
        # LIMIT 1 
        # FOR UPDATE SKIP LOCKED
        # Then UPDATE SET status='running', worker_id=self.worker_id, started_at=now()
    
    def execute_job(self, job):
        """Pull image, run container, capture output, store result"""
        try:
            self.runtime.pull_image(job['image'])
            container_id = self.runtime.run_container(
                image=job['image'],
                command=job['command'],
                env=job['environment'],
                timeout=job['timeout_seconds'],
                memory_limit='512m',
                cpu_limit='1',
                network='none',
                read_only=True,
                user='nobody'
            )
            # Wait for completion with timeout
            exit_code = self.runtime.wait(container_id, timeout=job['timeout_seconds'])
            stdout = self.runtime.get_logs(container_id, stream='stdout')
            stderr = self.runtime.get_logs(container_id, stream='stderr')
            # Store results
            self.store_result(job['id'], exit_code, stdout, stderr)
            self.mark_completed(job['id'], exit_code)
        except TimeoutError:
            self.runtime.stop_container(container_id)
            self.mark_timeout(job['id'])
        except Exception as e:
            self.mark_failed(job['id'], str(e))
        finally:
            self.runtime.cleanup(container_id)
```

### Container Runtime Abstraction (`container_runtime.py`)

```python
class ContainerRuntime:
    """Abstract interface for Docker/Podman"""
    
    @staticmethod
    def detect():
        """Detect available runtime (Docker or Podman)"""
        # Check for docker, then podman
        # Return DockerRuntime() or PodmanRuntime()
    
    def pull_image(self, image: str) -> None: ...
    def run_container(self, image, command, env, timeout, **security_opts) -> str: ...
    def stop_container(self, container_id: str, timeout: int = 10) -> None: ...
    def get_logs(self, container_id: str, stream: str) -> str: ...
    def wait(self, container_id: str, timeout: int) -> int: ...
    def cleanup(self, container_id: str) -> None: ...


class DockerRuntime(ContainerRuntime):
    """Docker Engine implementation"""
    
    def run_container(self, image, command, env, timeout, **opts):
        cmd = ['docker', 'run', '-d', '--name', f'job-{uuid}']
        # Security flags
        cmd += ['--read-only', '--user', 'nobody']
        cmd += ['--cap-drop', 'ALL']
        cmd += ['--memory', opts.get('memory_limit', '512m')]
        cmd += ['--cpus', opts.get('cpu_limit', '1')]
        cmd += ['--network', opts.get('network', 'none')]
        # Environment
        for k, v in env.items():
            cmd += ['-e', f'{k}={v}']
        cmd += [image] + command
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result.stdout.strip()


class PodmanRuntime(ContainerRuntime):
    """Podman implementation (same CLI interface)"""
    # Podman is CLI-compatible with Docker
    # Override binary name to 'podman'
```

### Systemd Service (`serverless-worker.service`)

```ini
[Unit]
Description=agentic-ai-plateform Serverless Worker Service
After=postgresql.service docker.service
Requires=postgresql.service

[Service]
Type=simple
User=ubuntu
Group=ubuntu
WorkingDirectory=/home/ubuntu/agentic-ai-plateform
ExecStart=/usr/bin/python3 -m src.serverless.worker
Restart=always
RestartSec=5
Environment=WORKER_ID=worker-001
Environment=PYTHONPATH=/home/ubuntu/agentic-ai-plateform

[Install]
WantedBy=multi-user.target
```

## Configuration

### Worker Configuration (`src/serverless/config.py`)

```python
SERVERLESS_CONFIG = {
    'registry_whitelist': [
        'docker.io',
        'ghcr.io',
        'registry.example.com'
    ],
    'default_timeout': 300,
    'max_timeout': 3600,
    'default_memory_limit': '512m',
    'default_cpu_limit': '1',
    'max_concurrent_jobs': 100,
    'log_retention_days': 30,
    'poll_interval': 0.5,
    'container_stop_timeout': 10,
    'warm_pool_enabled': False,
    'warm_pool_size': 0,
}
```

### Registry Whitelist Validation

```python
def validate_image_registry(image: str, whitelist: list) -> bool:
    """Check if image comes from an approved registry"""
    # Parse image to extract registry
    # Default registry is docker.io for images without prefix
    # Compare against whitelist
```

## Dashboard Integration

### Menu Addition

In `templates/base.html`, add a new top-level navigation item:

```html
<li class="nav-item">
    <a href="#" onclick="showSection('orchestratorServerlessSection')" class="nav-link">
        🚀 Application Orchestrator
    </a>
</li>
```

### Dashboard Section (in `templates/dashboard.html`)

New section `orchestratorServerlessSection` containing:
- Job list table with status badges (color-coded)
- Job submission form (image, command, env, timeout)
- Job detail modal (status, logs, result)
- Metrics panel (pending/running/failed counts, avg execution time)
- Auto-refresh every 5 seconds for active jobs

### JavaScript Functions

```javascript
// Job management functions
function submitServerlessJob() { /* POST /api/jobs */ }
function refreshJobList() { /* GET /api/jobs */ }
function viewJobDetail(jobId) { /* GET /api/jobs/{id} + /result */ }
function cancelJob(jobId) { /* POST /api/jobs/{id}/cancel */ }
function loadServerlessMetrics() { /* GET /api/jobs/metrics */ }
```

## Security Design

### Container Security Flags

Every container execution includes:
```bash
docker run \
  --read-only \
  --user nobody \
  --cap-drop ALL \
  --memory 512m \
  --cpus 1 \
  --network none \
  --security-opt no-new-privileges \
  --pids-limit 256 \
  <image> <command>
```

### Secret Handling

Secrets are passed to containers via:
1. Environment variables (for simple secrets)
2. Mounted tmpfs files (for complex secrets)

Never via CLI arguments (visible in `ps` output).

## Log Cleanup

### Scheduled Purge

```python
def cleanup_old_logs():
    """Purge job logs older than 30 days"""
    db_manager.execute_query('''
        DELETE FROM serverless_job_logs 
        WHERE created_at < CURRENT_TIMESTAMP - INTERVAL '30 days'
    ''')
    db_manager.execute_query('''
        DELETE FROM serverless_jobs 
        WHERE completed_at < CURRENT_TIMESTAMP - INTERVAL '30 days'
        AND status IN ('completed', 'failed', 'timeout', 'cancelled')
    ''')
```

Run via the worker service on a daily schedule or as a separate cron job.

## Integration with agentic-ai-plateform-serverless-brik

The `agentic-ai-plateform-serverless-brik` module is cloned from GitHub and integrated as:

1. Git submodule or pip-installable package
2. Provides the Flask Blueprint (`serverless_bp`) with all `/api/jobs` endpoints
3. Uses the platform's `db_manager` for database access
4. Uses the platform's session-based auth (via `session['user_id']`)
5. Registered in `ControlPlanFlaskApp_postgres.py` alongside other blueprints

## File Changes Summary

| File | Action | Description |
|------|--------|-------------|
| `migration/add_serverless_jobs.sql` | Create | Database migration for new tables |
| `src/routes/serverless_routes.py` | Create | API Blueprint for /api/jobs |
| `src/serverless/__init__.py` | Create | Worker package init |
| `src/serverless/worker.py` | Create | Worker main loop |
| `src/serverless/container_runtime.py` | Create | Docker/Podman abstraction |
| `src/serverless/config.py` | Create | Worker configuration |
| `src/serverless/log_cleanup.py` | Create | Log retention cleanup |
| `src/ControlPlanFlaskApp_postgres.py` | Modify | Register serverless_bp |
| `templates/base.html` | Modify | Add menu item |
| `templates/dashboard.html` | Modify | Add orchestrator section |
| `templates/dashboard_functions.js` | Modify | Add JS functions |
| `systemd/serverless-worker.service` | Create | Systemd unit file |
| `conf/serverless.ini` | Create | Serverless config file |
