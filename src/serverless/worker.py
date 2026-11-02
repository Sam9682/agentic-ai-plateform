"""Serverless Docker Execution Service - Worker.

This module implements the ServerlessWorker class that polls the PostgreSQL
job queue and executes containerized workloads using the configured container
runtime (Docker or Podman).

Database access (Phase 4, R5.5). The serverless worker is a *separate* process
from the Flask app, so it cannot use the app's ``db_manager`` singleton. It
still adopts the platform's pooled-access pattern instead of opening a fresh
``psycopg2.connect`` per operation: :class:`_WorkerConnectionPool` wraps a
``psycopg2.pool.ThreadedConnectionPool`` and exposes a ``get_db_connection()``
context manager whose borrow/return contract mirrors
``database_postgres.PostgreSQLManager.get_db_connection`` exactly — ``getconn``
on entry, ``rollback`` + ``putconn(close=True)`` on error, and ``putconn`` in
``finally`` so the connection is always returned to the pool. Every former
per-op ``psycopg2.connect`` in ``claim_next_job``, ``check_cancelled``,
``store_result``, ``mark_completed``, ``mark_failed`` and ``mark_timeout`` now
borrows from this pool.

Concurrency (Phase 4, R5.4). The worker tracks an ``in_flight`` counter and a
``_max_concurrent`` cap (``SERVERLESS_CONFIG["max_concurrent_jobs"]``) and
defers claiming new work while ``in_flight >= _max_concurrent`` — mirroring the
ARO ``agent_worker``'s ``in_flight``/``max_in_flight`` accounting. The counter
is incremented before :meth:`ServerlessWorker.execute_job` and decremented in a
``finally`` so a slot is always freed when a job reaches a terminal status.

Execution policy (Phase 4, R1.9). The DB claim operation runs through the
shared :func:`src.execution_policy.run_with_policy` so a transient database
failure retries with bounded backoff while a deterministic failure is terminal,
giving the serverless worker the same execution semantics as the ARO worker.
"""

import json
import logging
import logging.handlers
import os
import signal
import socket
import time
from contextlib import contextmanager
from typing import Any, Dict, Optional

import psycopg2
import psycopg2.extras
import psycopg2.pool

from src.execution_policy import (
    BackoffParams,
    OutcomeStatus,
    run_with_policy,
    ssh_is_transient,
)
from src.serverless.config import SERVERLESS_CONFIG, validate_image_registry
from src.serverless.container_runtime import ContainerRuntime
from src.serverless.log_cleanup import cleanup_old_logs

logger = logging.getLogger(__name__)

#: Bounded-retry parameters for transient database failures (R1.9/R5.5). A
#: claim/update that fails with a transient connection error retries with
#: exponential backoff; a deterministic failure is terminal after one attempt.
_DB_MAX_ATTEMPTS = 3
_DB_BACKOFF = BackoffParams(base=0.1, multiplier=2.0, jitter_fraction=0.1, cap=2.0)


class _WorkerConnectionPool:
    """Pooled PostgreSQL access for the serverless worker process (R5.5).

    Wraps a ``psycopg2.pool.ThreadedConnectionPool`` built from the worker's own
    ``db_config`` and exposes a :meth:`get_db_connection` context manager whose
    borrow/return contract mirrors
    ``database_postgres.PostgreSQLManager.get_db_connection`` exactly:

    * ``getconn`` on entry with ``autocommit = False``,
    * on error, ``rollback`` then ``putconn(close=True)`` so a poisoned
      connection is never handed back to another caller,
    * in ``finally``, ``putconn`` so a healthy connection always returns to the
      pool.

    The pool is created lazily on first use so constructing a worker never
    requires a live database (keeps the class unit-testable).
    """

    def __init__(self, db_config: Dict[str, Any], *, minconn: int = 1,
                 maxconn: int = 10) -> None:
        self._db_config = db_config
        self._minconn = minconn
        self._maxconn = maxconn
        self._pool: Optional[psycopg2.pool.ThreadedConnectionPool] = None

    def _ensure_initialized(self) -> None:
        if self._pool is None:
            self._pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=self._minconn,
                maxconn=self._maxconn,
                host=self._db_config["host"],
                port=self._db_config["port"],
                dbname=self._db_config["database"],
                user=self._db_config["user"],
                password=self._db_config["password"],
            )

    @contextmanager
    def get_db_connection(self):
        """Borrow a connection from the pool; always return it in ``finally``.

        Mirrors ``PostgreSQLManager.get_db_connection`` — a failing connection is
        rolled back and returned with ``close=True`` so the pool replaces it;
        otherwise it is returned healthy for reuse.
        """
        self._ensure_initialized()
        conn = None
        try:
            conn = self._pool.getconn()
            conn.autocommit = False
            yield conn
        except Exception:
            if conn is not None:
                try:
                    conn.rollback()
                except Exception:
                    pass
                try:
                    self._pool.putconn(conn, close=True)
                except Exception:
                    pass
                conn = None
            raise
        finally:
            if conn is not None:
                try:
                    self._pool.putconn(conn)
                except Exception:
                    pass

    def closeall(self) -> None:
        """Close every pooled connection (used on worker shutdown)."""
        if self._pool is not None:
            try:
                self._pool.closeall()
            except Exception:
                pass


def resolve_runtime_type(db_config: Dict[str, Any]) -> str:
    """Read and validate the configured container runtime type from PostgreSQL.

    The serverless worker is a separate process that connects to PostgreSQL via
    psycopg2 directly (it does not use the Flask ``db_manager``). This reads the
    top-level ``runtime_type`` configuration value once and sanitizes it against
    the shared whitelist. On any error it defaults to ``'runc'``.

    Args:
        db_config: PostgreSQL connection parameters.

    Returns:
        str: Either ``'runc'`` or ``'kata'``.
    """
    try:
        # Import only the pure sanitizer (no Flask dependencies). Done inside
        # the try so an import failure also falls back safely to 'runc'.
        from src.database_postgres import _sanitize_runtime_type

        conn = psycopg2.connect(**db_config)
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT value FROM configuration "
                    "WHERE key = 'runtime_type' AND parent IS NULL"
                )
                row = cursor.fetchone()
        finally:
            conn.close()
        value = row[0] if row else None
        return _sanitize_runtime_type(value)
    except Exception as e:
        logger.warning(
            "Could not resolve runtime_type from database (%s); defaulting to 'runc'",
            e,
        )
        return "runc"


class CancellationError(Exception):
    """Raised when a job is detected as cancelled during execution."""
    pass


class ServerlessWorker:
    """Worker service that polls the job queue and executes container jobs.

    The worker claims pending jobs from PostgreSQL using the FOR UPDATE SKIP LOCKED
    pattern, executes them via the container runtime with security constraints,
    captures output, and stores results back in the database.

    Attributes:
        worker_id: Unique identifier for this worker instance.
        runtime: ContainerRuntime instance (Docker or Podman).
        db_config: Database connection configuration dictionary.
        registry_whitelist: List of approved container image registries.
        running: Flag controlling the main polling loop.
        poll_interval: Seconds to sleep between queue polls when idle.
        in_flight: Number of jobs currently executing (R5.4).
        max_concurrent: Configured upper bound on simultaneous jobs (R5.4).
    """

    def __init__(
        self,
        worker_id: str,
        runtime: ContainerRuntime,
        db_config: Dict[str, Any],
        registry_whitelist: Optional[list] = None,
        runtime_type: str = "runc",
        pool: Optional["_WorkerConnectionPool"] = None,
        max_concurrent: Optional[int] = None,
    ) -> None:
        """Initialize the ServerlessWorker.

        Args:
            worker_id: Unique identifier for this worker instance.
            runtime: ContainerRuntime instance for executing containers.
            db_config: Database connection parameters (host, port, database, user, password).
            registry_whitelist: List of approved registries. Defaults to config value.
            runtime_type: Container runtime to use ('runc' or 'kata'). Resolved
                once at worker startup; a restart is required to change it.
            pool: Pooled database access (R5.5). Defaults to a
                :class:`_WorkerConnectionPool` built from ``db_config``; an
                injected fake keeps the worker unit-testable without a live DB.
            max_concurrent: Upper bound on simultaneous jobs (R5.4). Defaults to
                ``SERVERLESS_CONFIG["max_concurrent_jobs"]``.
        """
        self.worker_id = worker_id
        self.runtime = runtime
        self.db_config = db_config
        self.runtime_type = runtime_type
        self.registry_whitelist = (
            registry_whitelist
            if registry_whitelist is not None
            else SERVERLESS_CONFIG["registry_whitelist"]
        )
        self.running = True
        self.poll_interval = SERVERLESS_CONFIG["poll_interval"]
        self.last_cleanup_time: float = 0.0
        self.cleanup_interval: float = 86400.0  # 24 hours in seconds
        #: Pooled DB access replacing per-op ``psycopg2.connect`` (R5.5).
        self._pool = pool if pool is not None else _WorkerConnectionPool(db_config)
        #: Max simultaneous jobs; claiming is deferred while at the cap (R5.4).
        self._max_concurrent = max(
            1,
            int(
                max_concurrent
                if max_concurrent is not None
                else SERVERLESS_CONFIG["max_concurrent_jobs"]
            ),
        )
        #: Number of jobs currently executing. Incremented before
        #: ``execute_job`` and decremented in ``finally`` (R5.4).
        self.in_flight = 0

    @property
    def max_concurrent(self) -> int:
        """The configured max-concurrent-jobs cap (read-only, for observability)."""
        return self._max_concurrent

    def run(self) -> None:
        """Main polling loop that continuously claims and executes jobs.

        Each cycle delegates to :meth:`run_once`. When no job is handled (queue
        empty or at the concurrency cap) the worker sleeps for the configured
        poll interval before checking again.

        Also performs daily log cleanup when the cleanup interval has elapsed.

        The loop continues until self.running is set to False (e.g. via
        signal handler for graceful shutdown).
        """
        logger.info("Worker %s starting main loop", self.worker_id)
        while self.running:
            self._maybe_run_cleanup()
            if not self.run_once():
                time.sleep(self.poll_interval)
        logger.info("Worker %s shutting down gracefully", self.worker_id)

    def run_once(self) -> bool:
        """Claim and execute a single job. Returns True when one was handled.

        Enforces the max-concurrent-jobs cap (R5.4): while
        ``in_flight >= max_concurrent`` the worker skips claiming entirely and
        returns ``False`` until a running job completes. Mirrors the ARO
        ``agent_worker.run_once`` accounting: ``in_flight`` is incremented
        before :meth:`execute_job` and decremented in a ``finally`` so a slot is
        always freed when the job reaches a terminal status.

        Returns:
            True when a job was claimed and executed, False when the worker was
            at capacity or the queue was empty.
        """
        # Max-concurrent cap: do not claim new work while at capacity (R5.4).
        if self.in_flight >= self._max_concurrent:
            return False
        job = self.claim_next_job()
        if job is None:
            return False
        logger.info("Worker %s claimed job %s", self.worker_id, job['id'])
        # Account for the in-flight job across its synchronous execution so the
        # cap is correctly enforced and observable (R5.4).
        self.in_flight += 1
        try:
            self.execute_job(job)
        finally:
            self.in_flight -= 1
        return True

    def _maybe_run_cleanup(self) -> None:
        """Run log cleanup if the daily interval has elapsed.

        Checks whether enough time has passed since the last cleanup run.
        If so, executes the cleanup and updates the last_cleanup_time.
        Errors during cleanup are logged but do not stop the worker.
        """
        now = time.time()
        if now - self.last_cleanup_time >= self.cleanup_interval:
            logger.info("Worker %s running daily log cleanup", self.worker_id)
            try:
                logs_deleted, jobs_deleted = cleanup_old_logs(self.db_config)
                logger.info(
                    "Cleanup completed: %d logs, %d jobs removed",
                    logs_deleted,
                    jobs_deleted,
                )
            except Exception as e:
                logger.error("Daily cleanup failed, will retry next cycle: %s", e)
            self.last_cleanup_time = now

    def claim_next_job(self) -> Optional[Dict[str, Any]]:
        """Claim a pending job from the queue using FOR UPDATE SKIP LOCKED.

        Atomically selects the oldest pending job and updates its status to
        'running', recording this worker's ID and the start timestamp. Uses
        PostgreSQL's SKIP LOCKED to avoid contention with other workers.

        The claim borrows a connection from the shared pool (R5.5) and runs
        through :func:`run_with_policy` (R1.9) so a transient database failure
        retries with bounded backoff while a deterministic failure is terminal.
        A failed or empty claim returns ``None`` (unchanged contract).

        Returns:
            A dictionary with the job's fields (id, image, command, environment,
            timeout_seconds, user_id) if a job was claimed, or None if the
            queue is empty.
        """

        def _op(_token) -> Optional[Dict[str, Any]]:
            with self._pool.get_db_connection() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        """SELECT * FROM serverless_jobs
                           WHERE status = 'pending'
                           ORDER BY created_at ASC
                           LIMIT 1
                           FOR UPDATE SKIP LOCKED""",
                    )
                    row = cur.fetchone()
                    if row is None:
                        conn.commit()
                        return None

                    cur.execute(
                        """UPDATE serverless_jobs
                           SET status = 'running',
                               worker_id = %s,
                               started_at = CURRENT_TIMESTAMP
                           WHERE id = %s""",
                        (self.worker_id, row['id']),
                    )
                    conn.commit()
                return {
                    'id': row['id'],
                    'user_id': row['user_id'],
                    'image': row['image'],
                    'command': row['command'],
                    'environment': row['environment'],
                    'timeout_seconds': row['timeout_seconds'],
                }

        outcome = run_with_policy(
            _op,
            timeout=None,
            max_attempts=_DB_MAX_ATTEMPTS,
            backoff=_DB_BACKOFF,
            is_transient=ssh_is_transient,
        )
        if outcome.status is OutcomeStatus.SUCCEEDED:
            job = outcome.value
            if job is not None:
                logger.info(
                    "Claimed job %s (image=%s) on worker %s",
                    job['id'], job['image'], self.worker_id,
                )
            return job
        logger.error("Failed to claim job: %s", outcome.error)
        return None

    def execute_job(self, job: Dict[str, Any]) -> None:
        """Execute a claimed job through the full container lifecycle.

        Steps:
        1. Validate the image registry against the whitelist.
        2. Pull the container image.
        3. Run the container with security constraints.
        4. Wait for completion (respecting timeout).
        5. Capture stdout and stderr logs.
        6. Store results and update job status.

        Handles timeout by stopping the container and marking the job as
        'timeout'. Handles other exceptions by marking the job as 'failed'.
        Always cleans up the container resources in a finally block.

        Args:
            job: Dictionary containing the job record fields from the database.
        """
        container_id = None
        start_time = time.time()
        logger.info(
            "Execution start: job_id=%s image=%s command=%s",
            job['id'], job['image'], job.get('command'),
        )
        try:
            # 1. Validate registry whitelist
            if not validate_image_registry(job['image'], self.registry_whitelist):
                self.mark_failed(job['id'], f"Image registry not in whitelist: {job['image']}")
                return

            # 2. Pull image
            self.runtime.pull_image(job['image'])

            # 3. Run container with security constraints
            container_id = self.runtime.run_container(
                image=job['image'],
                command=job['command'],
                env=job.get('environment', {}),
                timeout=job['timeout_seconds'],
                memory_limit=SERVERLESS_CONFIG['default_memory_limit'],
                cpu_limit=SERVERLESS_CONFIG['default_cpu_limit'],
                network='none',
                runtime_type=self.runtime_type,
            )

            # 4. Wait for completion with timeout and cancellation checks
            exit_code = self._wait_with_cancellation_check(
                container_id, job['id'], job['timeout_seconds']
            )

            # 5. Capture stdout/stderr
            stdout = self.runtime.get_logs(container_id, stream='stdout')
            stderr = self.runtime.get_logs(container_id, stream='stderr')

            # 6. Store results and mark completed
            self.store_result(job['id'], exit_code, stdout, stderr)
            self.mark_completed(job['id'], exit_code)
            duration = time.time() - start_time
            logger.info(
                "Execution end: job_id=%s status=completed exit_code=%d duration=%.2fs",
                job['id'], exit_code, duration,
            )

        except CancellationError:
            duration = time.time() - start_time
            logger.info(
                "Execution end: job_id=%s status=cancelled duration=%.2fs",
                job['id'], duration,
            )
        except TimeoutError:
            if container_id:
                self.runtime.stop_container(container_id, timeout=SERVERLESS_CONFIG['container_stop_timeout'])
            self.mark_timeout(job['id'])
            duration = time.time() - start_time
            logger.warning(
                "Execution end: job_id=%s status=timeout duration=%.2fs",
                job['id'], duration,
            )
        except Exception as e:
            self.mark_failed(job['id'], str(e))
            duration = time.time() - start_time
            logger.error(
                "Execution end: job_id=%s status=failed duration=%.2fs error=%s",
                job['id'], duration, e,
            )
        finally:
            if container_id:
                self.runtime.cleanup(container_id)

    def check_cancelled(self, job_id: str) -> bool:
        """Check if a job has been cancelled by querying its current status.

        Queries the database for the job's current status. This is used during
        execution to detect if a user has requested cancellation via the API.
        Borrows a connection from the shared pool (R5.5).

        Args:
            job_id: UUID of the job to check.

        Returns:
            True if the job status is 'cancelled', False otherwise.
        """
        try:
            with self._pool.get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT status FROM serverless_jobs WHERE id = %s",
                        (job_id,),
                    )
                    row = cur.fetchone()
                    conn.commit()
                    if row and row[0] == 'cancelled':
                        return True
            return False
        except Exception as e:
            logger.error("Failed to check cancellation status for job %s: %s", job_id, e)
            return False

    def _wait_with_cancellation_check(
        self, container_id: str, job_id: str, timeout: int
    ) -> int:
        """Wait for container completion with periodic cancellation checks.

        Uses a polling loop with short wait intervals to allow checking the
        database for cancellation requests. Each iteration waits up to
        check_interval seconds for the container to finish, then queries the
        job status to detect if it has been cancelled.

        Args:
            container_id: The container ID to wait on.
            job_id: UUID of the job (for cancellation checks).
            timeout: Maximum total seconds to wait for completion.

        Returns:
            The container exit code if it completed normally.

        Raises:
            CancellationError: If the job was cancelled during execution.
            TimeoutError: If the container did not finish within the timeout.
        """
        elapsed = 0
        check_interval = 2  # Check every 2 seconds
        while elapsed < timeout:
            try:
                exit_code = self.runtime.wait(container_id, timeout=check_interval)
                return exit_code
            except TimeoutError:
                elapsed += check_interval
                if self.check_cancelled(job_id):
                    self.runtime.stop_container(container_id, timeout=10)
                    raise CancellationError(f"Job {job_id} was cancelled")
        raise TimeoutError(f"Container did not finish within {timeout} seconds")

    def store_result(
        self, job_id: str, exit_code: int, stdout: str, stderr: str
    ) -> None:
        """Store job execution output in the database.

        Inserts stdout and stderr into the serverless_job_logs table and
        stores a structured result in the serverless_job_results table.
        Borrows a connection from the shared pool (R5.5).

        Args:
            job_id: UUID of the job.
            exit_code: Container process exit code.
            stdout: Captured standard output from the container.
            stderr: Captured standard error from the container.
        """
        try:
            with self._pool.get_db_connection() as conn:
                with conn.cursor() as cur:
                    # Insert stdout log
                    cur.execute(
                        """INSERT INTO serverless_job_logs (job_id, stream, content)
                           VALUES (%s, 'stdout', %s)""",
                        (job_id, stdout),
                    )
                    # Insert stderr log
                    cur.execute(
                        """INSERT INTO serverless_job_logs (job_id, stream, content)
                           VALUES (%s, 'stderr', %s)""",
                        (job_id, stderr),
                    )
                    # Insert structured result
                    result_data = json.dumps({
                        'exit_code': exit_code,
                        'stdout_length': len(stdout),
                        'stderr_length': len(stderr),
                    })
                    cur.execute(
                        """INSERT INTO serverless_job_results (job_id, result)
                           VALUES (%s, %s)""",
                        (job_id, result_data),
                    )
                conn.commit()
        except Exception as e:
            logger.error("Failed to store result for job %s: %s", job_id, e)

    def mark_completed(self, job_id: str, exit_code: int) -> None:
        """Update job status to 'completed' with the exit code.

        Sets the completed_at timestamp and records the container exit code
        in the serverless_jobs table. Borrows a connection from the shared
        pool (R5.5).

        Args:
            job_id: UUID of the job to mark as completed.
            exit_code: Container process exit code.
        """
        try:
            with self._pool.get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """UPDATE serverless_jobs
                           SET status = 'completed',
                               exit_code = %s,
                               completed_at = CURRENT_TIMESTAMP
                           WHERE id = %s""",
                        (exit_code, job_id),
                    )
                conn.commit()
        except Exception as e:
            logger.error("Failed to mark job %s as completed: %s", job_id, e)

    def mark_failed(self, job_id: str, error_message: str) -> None:
        """Update job status to 'failed' with an error message.

        Sets the completed_at timestamp and stores the error in the
        serverless_job_logs table as a stderr entry. Borrows a connection from
        the shared pool (R5.5).

        Args:
            job_id: UUID of the job to mark as failed.
            error_message: Description of the failure.
        """
        try:
            with self._pool.get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """UPDATE serverless_jobs
                           SET status = 'failed',
                               completed_at = CURRENT_TIMESTAMP
                           WHERE id = %s""",
                        (job_id,),
                    )
                    cur.execute(
                        """INSERT INTO serverless_job_logs (job_id, stream, content)
                           VALUES (%s, 'stderr', %s)""",
                        (job_id, error_message),
                    )
                conn.commit()
        except Exception as e:
            logger.error("Failed to mark job %s as failed: %s", job_id, e)

    def mark_timeout(self, job_id: str) -> None:
        """Update job status to 'timeout'.

        Sets the completed_at timestamp when a job exceeds its configured
        timeout_seconds limit. The container is stopped by the caller before
        this method is invoked. Borrows a connection from the shared pool (R5.5).

        Args:
            job_id: UUID of the job to mark as timed out.
        """
        try:
            with self._pool.get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """UPDATE serverless_jobs
                           SET status = 'timeout',
                               completed_at = CURRENT_TIMESTAMP
                           WHERE id = %s""",
                        (job_id,),
                    )
                conn.commit()
        except Exception as e:
            logger.error("Failed to mark job %s as timeout: %s", job_id, e)


def main() -> None:
    """Entry point for running the worker as python -m src.serverless.worker.

    Sets up:
    - Logging configuration for the worker process with file rotation.
    - Signal handling for SIGTERM and SIGINT to trigger graceful shutdown.
    - Container runtime detection (Docker or Podman).
    - Database configuration from environment variables.
    - Worker instantiation and main loop execution.

    The worker_id is read from the WORKER_ID environment variable, falling
    back to a generated default of 'worker-<hostname>-<pid>'.
    """
    # Configure logging with RotatingFileHandler and StreamHandler
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    formatter = logging.Formatter(log_format)

    # Get project root directory dynamically
    project_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    log_dir = os.path.join(project_root, "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "serverless_worker.log")

    # Rotating file handler: 10 MB max, 5 backup files
    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=10 * 1024 * 1024, backupCount=5
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    # Configure root logger for the serverless namespace
    root_logger = logging.getLogger("src.serverless")
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    root_logger.propagate = False

    # Determine worker ID
    worker_id = os.environ.get(
        "WORKER_ID",
        f"worker-{socket.gethostname()}-{os.getpid()}",
    )

    logger.info("Initializing serverless worker: %s", worker_id)

    # Detect container runtime
    try:
        runtime = ContainerRuntime.detect()
        logger.info("Detected container runtime: %s", type(runtime).__name__)
    except RuntimeError as e:
        logger.error("Failed to detect container runtime: %s", e)
        raise SystemExit(1)

    # Database configuration
    db_config = {
        "host": os.environ.get("POSTGRES_HOST", "localhost"),
        "port": int(os.environ.get("POSTGRES_PORT", 5432)),
        "database": os.environ.get("POSTGRES_DB", "ai_swautomorph"),
        "user": os.environ.get("POSTGRES_USER", "swautomorph"),
        "password": os.environ.get("POSTGRES_PASSWORD", "swautomorph_password"),
    }

    # Resolve the configured container runtime type once at startup.
    # A worker restart is required to pick up a configuration change.
    runtime_type = resolve_runtime_type(db_config)
    logger.info("Using container runtime type: %s", runtime_type)

    # Create worker instance
    worker = ServerlessWorker(
        worker_id=worker_id,
        runtime=runtime,
        db_config=db_config,
        runtime_type=runtime_type,
    )

    # Signal handler for graceful shutdown
    def handle_shutdown_signal(signum: int, frame) -> None:
        sig_name = signal.Signals(signum).name
        logger.info("Received %s, initiating graceful shutdown...", sig_name)
        worker.running = False

    signal.signal(signal.SIGTERM, handle_shutdown_signal)
    signal.signal(signal.SIGINT, handle_shutdown_signal)

    # Start the main run loop
    logger.info("Worker %s starting...", worker_id)
    worker.run()
    logger.info("Worker %s has stopped.", worker_id)


if __name__ == "__main__":
    main()
