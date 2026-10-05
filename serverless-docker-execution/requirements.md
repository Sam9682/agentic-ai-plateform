# Requirements Document

## Introduction

This feature adds a serverless container execution capability to the agentic-ai-plateform platform. Users can submit Docker-based jobs via a REST API, which are queued in PostgreSQL and executed by a separate worker service using Docker or Podman. The feature includes job lifecycle management (submission, status tracking, result retrieval, cancellation), container security enforcement, monitoring, and a new "Application Orchestrator" dashboard menu item. A new external module `agentic-ai-plateform-serverless-brik` on GitHub provides the web API service for serverless execution.

## Glossary

- **Job_Submission_API**: The REST API endpoint set (under `/api/jobs`) that accepts job requests from authenticated clients and returns job identifiers
- **Worker_Service**: A separate systemd service (`serverless-worker.service`) that polls the PostgreSQL job queue and executes containers via the Container_Runtime
- **Container_Runtime**: An abstraction layer that supports both Docker Engine and Podman for executing job containers
- **Job_Queue**: The PostgreSQL-based queue using the `FOR UPDATE SKIP LOCKED` pattern to distribute pending jobs to workers
- **Job**: A unit of work representing a single container execution with defined image, command, environment, and timeout
- **Registry_Whitelist**: A configurable list of approved container image registries from which images may be pulled
- **Warm_Pool**: An optional (Phase 2) set of pre-started idle containers maintained for reduced startup latency
- **Dashboard**: The existing agentic-ai-plateform web dashboard extended with a new main menu item "Application Orchestrator"
- **agentic-ai-plateform-serverless-brik**: A new GitHub module that provides the web API service layer for serverless job execution

## Requirements

### Requirement 1: Job Submission

**User Story:** As an authenticated user, I want to submit a container execution job via the API, so that I can run arbitrary containerized workloads on the platform.

#### Acceptance Criteria

1. WHEN an authenticated user sends a POST request to `/api/jobs` with a valid payload containing image, command, env, and timeout fields, THE Job_Submission_API SHALL create a new job record in PostgreSQL with status "pending" and return a response containing a UUID job_id within 100ms
2. IF the request payload is missing required fields (image or command), THEN THE Job_Submission_API SHALL return HTTP 400 with a descriptive error message
3. IF the specified image registry is not in the Registry_Whitelist, THEN THE Job_Submission_API SHALL reject the request with HTTP 403 and a message indicating the registry is not approved
4. IF the user is not authenticated, THEN THE Job_Submission_API SHALL return HTTP 401
5. THE Job_Submission_API SHALL validate that the timeout value is between 1 and 3600 seconds

### Requirement 2: Job Status Tracking

**User Story:** As an authenticated user, I want to query the status of my submitted jobs, so that I can monitor their progress.

#### Acceptance Criteria

1. WHEN an authenticated user sends a GET request to `/api/jobs/{job_id}`, THE Job_Submission_API SHALL return the current job status from the set: pending, running, completed, failed, timeout, cancelled
2. WHEN a job transitions from one status to another, THE Job_Submission_API SHALL record the transition timestamp in the jobs table
3. IF the specified job_id does not exist, THEN THE Job_Submission_API SHALL return HTTP 404
4. THE Job_Submission_API SHALL restrict job status visibility to the job owner and admin users

### Requirement 3: Job Result Retrieval

**User Story:** As an authenticated user, I want to retrieve the result of a completed job, so that I can use the output of the containerized workload.

#### Acceptance Criteria

1. WHEN an authenticated user sends a GET request to `/api/jobs/{job_id}/result` for a completed job, THE Job_Submission_API SHALL return the exit_code, stdout, stderr, and result (JSONB) fields
2. IF the job has not yet completed (status is pending or running), THEN THE Job_Submission_API SHALL return HTTP 409 with a message indicating the job is still in progress
3. THE Job_Submission_API SHALL stream stdout and stderr from the job_logs table ordered by creation timestamp

### Requirement 4: Job Cancellation

**User Story:** As an authenticated user, I want to cancel a running or pending job, so that I can stop unwanted workloads.

#### Acceptance Criteria

1. WHEN an authenticated user sends a POST request to `/api/jobs/{job_id}/cancel` for a job in "pending" or "running" status, THE Job_Submission_API SHALL mark the job as "cancelled"
2. WHEN a running job is cancelled, THE Worker_Service SHALL stop the associated container within 10 seconds using the Container_Runtime
3. IF the job is already in a terminal state (completed, failed, timeout, cancelled), THEN THE Job_Submission_API SHALL return HTTP 409 with a message indicating the job cannot be cancelled

### Requirement 5: Worker Service Job Processing

**User Story:** As a platform operator, I want jobs to be processed by a separate worker service, so that the web application remains responsive.

#### Acceptance Criteria

1. THE Worker_Service SHALL run as a separate systemd service (`serverless-worker.service`) independent from the Gunicorn web process
2. WHEN the Worker_Service polls the Job_Queue, THE Worker_Service SHALL use the `SELECT ... FOR UPDATE SKIP LOCKED` pattern to claim pending jobs without blocking other workers
3. WHEN the Worker_Service claims a job, THE Worker_Service SHALL update the job status to "running" and record its worker_id
4. WHEN the Worker_Service processes a job, THE Worker_Service SHALL execute the following steps in order: pull image, start container, capture output, store result, update status
5. IF the container execution exceeds the job timeout, THEN THE Worker_Service SHALL stop the container and mark the job status as "timeout"
6. THE Worker_Service SHALL process the job queue with a polling latency of less than 1 second

### Requirement 6: Container Runtime Abstraction

**User Story:** As a platform operator, I want the worker to support both Docker and Podman, so that I can choose the container runtime based on infrastructure requirements.

#### Acceptance Criteria

1. THE Worker_Service SHALL provide a Container_Runtime abstraction that supports both Docker Engine and Podman
2. WHEN the Worker_Service starts, THE Worker_Service SHALL detect which Container_Runtime is available and configure itself accordingly
3. THE Container_Runtime abstraction SHALL expose a uniform interface for: pull image, run container, stop container, get logs, and inspect container

### Requirement 7: Container Security Enforcement

**User Story:** As a platform operator, I want all job containers to run with restricted security settings, so that workloads cannot compromise the host system.

#### Acceptance Criteria

1. THE Worker_Service SHALL execute all job containers with the following security constraints: non-root user, read-only root filesystem, dropped Linux capabilities (all except NET_BIND_SERVICE), and network disabled by default
2. THE Worker_Service SHALL enforce configurable resource limits: memory limit (default 512MB), CPU limit (default 1 core), and the user-specified timeout
3. THE Worker_Service SHALL pass secrets to containers only via environment variables or mounted files, and SHALL NOT pass secrets as command-line arguments
4. THE Worker_Service SHALL only pull images from registries listed in the Registry_Whitelist

### Requirement 8: Database Schema for Job Management

**User Story:** As a platform developer, I want a well-defined database schema for jobs, logs, and results, so that the system can reliably track and store job execution data.

#### Acceptance Criteria

1. THE Job_Queue SHALL use a `jobs` table with columns: id (UUID PRIMARY KEY), user_id (FK), image (TEXT), command (JSONB), environment (JSONB), timeout_seconds (INTEGER), status (TEXT), created_at (TIMESTAMP), started_at (TIMESTAMP), completed_at (TIMESTAMP), exit_code (INTEGER), worker_id (TEXT)
2. THE Job_Queue SHALL use a `job_logs` table with columns: id (BIGSERIAL PRIMARY KEY), job_id (UUID FK), stream (TEXT for stdout/stderr), content (TEXT), created_at (TIMESTAMP)
3. THE Job_Queue SHALL use a `job_results` table with columns: job_id (UUID PRIMARY KEY FK), result (JSONB), created_at (TIMESTAMP)
4. THE Job_Queue SHALL include appropriate indexes on jobs.status, jobs.user_id, and job_logs.job_id for query performance

### Requirement 9: Application Orchestrator Dashboard

**User Story:** As an authenticated user, I want a new "Application Orchestrator" main menu item in the dashboard, so that I can manage and monitor serverless jobs from the web interface.

#### Acceptance Criteria

1. THE Dashboard SHALL display a new main menu item labeled "Application Orchestrator" at the top navigation level (not as a submenu)
2. WHEN the user navigates to the Application Orchestrator page, THE Dashboard SHALL display a job management panel showing: list of submitted jobs with status, job submission form, and job detail/result views
3. THE Dashboard SHALL display monitoring metrics including: count of pending, running, and failed jobs, average execution time, queue depth, and container startup duration
4. THE Dashboard SHALL auto-refresh job status every 5 seconds for active jobs

### Requirement 10: Monitoring and Logging

**User Story:** As a platform operator, I want comprehensive monitoring and logging for the serverless execution service, so that I can detect issues and audit usage.

#### Acceptance Criteria

1. THE Worker_Service SHALL expose metrics for: count of pending jobs, count of running jobs, count of failed jobs, average execution time, queue depth, and container startup duration
2. THE Job_Submission_API SHALL log all job submission, cancellation, and result retrieval actions with user_id and timestamp
3. THE Worker_Service SHALL retain job logs for 30 days and automatically purge logs older than 30 days

### Requirement 11: Performance Requirements

**User Story:** As a platform operator, I want the system to meet defined performance targets, so that users experience responsive job submission and execution.

#### Acceptance Criteria

1. THE Job_Submission_API SHALL respond to all API requests within 100ms at the 95th percentile
2. THE Worker_Service SHALL begin processing a pending job within 1 second of it being enqueued (queue latency)
3. THE Worker_Service SHALL start a job container within 5 seconds of claiming the job (container startup time)
4. THE Worker_Service SHALL support at least 100 concurrent running jobs on a single server
5. THE Job_Submission_API SHALL maintain 99.5% availability measured over a rolling 30-day window

### Requirement 12: agentic-ai-plateform-serverless-brik Integration

**User Story:** As a platform developer, I want to integrate the `agentic-ai-plateform-serverless-brik` GitHub module as the serverless API service layer, so that the platform leverages a dedicated, maintainable component for job execution.

#### Acceptance Criteria

1. THE Job_Submission_API SHALL be implemented within the `agentic-ai-plateform-serverless-brik` module and integrated with the existing Flask application via a new Blueprint registered at `/api/jobs`
2. THE agentic-ai-plateform-serverless-brik module SHALL use the same PostgreSQL connection pooling infrastructure as the existing platform (via `database_postgres.db_manager`)
3. THE agentic-ai-plateform-serverless-brik module SHALL authenticate requests using the existing session-based authentication mechanism from the platform

### Requirement 13: Scalability Roadmap Support

**User Story:** As a platform architect, I want the system designed to support future multi-worker and Kubernetes migration, so that the platform can scale without rewriting the external API.

#### Acceptance Criteria

1. THE Job_Submission_API SHALL maintain the same external API contract (`/api/jobs` endpoints) across all scalability phases (single server, multiple workers, Kubernetes)
2. THE Worker_Service SHALL identify itself with a unique worker_id when claiming jobs, so that multiple workers can operate concurrently in Phase 2
3. THE Job_Queue SHALL support concurrent access from multiple Worker_Service instances using the `FOR UPDATE SKIP LOCKED` pattern without data corruption

### Requirement 14: Warm Pool (Phase 2 - Optional)

**User Story:** As a platform operator, I want to optionally maintain a pool of idle pre-started containers, so that job startup latency is reduced below 1 second.

#### Acceptance Criteria

1. WHERE the Warm_Pool feature is enabled, THE Worker_Service SHALL maintain a configurable number (N) of idle containers ready for immediate job assignment
2. WHERE the Warm_Pool feature is enabled, WHEN a new job is submitted, THE Worker_Service SHALL assign the job to an available idle container from the Warm_Pool within 1 second
3. WHERE the Warm_Pool feature is enabled, WHEN a Warm_Pool container is consumed, THE Worker_Service SHALL replenish the pool by starting a new idle container
