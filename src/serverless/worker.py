"""Serverless Docker Execution Service - Worker.

This module implements the ServerlessWorker class that polls the PostgreSQL
job queue and executes containerized workloads using the configured container
runtime (Docker or Podman).
"""

import json
import logging
import logging.handlers
import os
import signal
import socket
import time
from typing import Any, Dict, Optional

import psycopg2
import psycopg2.extras

from src.serverless.config import SERVERLESS_CONFIG, validate_image_registry
from src.serverless.container_runtime import ContainerRuntime
from src.serverless.log_cleanup import cleanup_old_logs

logger = logging.getLogger(__name__)


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
    """

    def __init__(
        self,
        worker_id: str,
        runtime: ContainerRuntime,
        db_config: Dict[str, Any],
        registry_whitelist: Optional[list] = None,
        runtime_type: str = "runc",
    ) -> None:
        """Initialize the ServerlessWorker.

        Args:
            worker_id: Unique identifier for this worker instance.
            runtime: ContainerRuntime instance for executing containers.
            db_config: Database connection parameters (host, port, dbname, user, password).
            registry_whitelist: List of approved registries. Defaults to config value.
            runtime_type: Container runtime to use ('runc' or 'kata'). Resolved
                once at worker startup; a restart is required to change it.
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

    def run(self) -> None:
        """Main polling loop that continuously claims and executes jobs.

        Polls the job queue for pending jobs. When a job is found, it is
        executed immediately. When the queue is empty, the worker sleeps
        for the configured poll interval before checking again.

        Also performs daily log cleanup when the cleanup interval has elapsed.

        The loop continues until self.running is set to False (e.g. via
        signal handler for graceful shutdown).
        """
        logger.info("Worker %s starting main loop", self.worker_id)
        while self.running:
            self._maybe_run_cleanup()
            job = self.claim_next_job()
            if job:
                logger.info("Worker %s claimed job %s", self.worker_id, job['id'])
                self.execute_job(job)
            else:
                time.sleep(self.poll_interval)
        logger.info("Worker %s shutting down gracefully", self.worker_id)

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

        Returns:
            A dictionary with the job's fields (id, image, command, environment,
            timeout_seconds, user_id) if a job was claimed, or None if the
            queue is empty.
        """
        conn = None
        try:
            conn = psycopg2.connect(
                host=self.db_config['host'],
                port=self.db_config['port'],
                dbname=self.db_config['database'],
                user=self.db_config['user'],
                password=self.db_config['password'],
            )
            conn.autocommit = False
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

            job = {
                'id': row['id'],
                'user_id': row['user_id'],
                'image': row['image'],
                'command': row['command'],
                'environment': row['environment'],
                'timeout_seconds': row['timeout_seconds'],
            }
            logger.info(
                "Claimed job %s (image=%s) on worker %s",
                job['id'], job['image'], self.worker_id,
            )
            return job
        except Exception as e:
            logger.error("Failed to claim job: %s", e)
            if conn:
                conn.rollback()
            return None
        finally:
            if conn:
                conn.close()

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

        Args:
            job_id: UUID of the job to check.

        Returns:
            True if the job status is 'cancelled', False otherwise.
        """
        conn = None
        try:
            conn = psycopg2.connect(
                host=self.db_config['host'],
                port=self.db_config['port'],
                dbname=self.db_config['database'],
                user=self.db_config['user'],
                password=self.db_config['password'],
            )
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT status FROM serverless_jobs WHERE id = %s",
                    (job_id,),
                )
                row = cur.fetchone()
                if row and row[0] == 'cancelled':
                    return True
            return False
        except Exception as e:
            logger.error("Failed to check cancellation status for job %s: %s", job_id, e)
            return False
        finally:
            if conn:
                conn.close()

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

        Args:
            job_id: UUID of the job.
            exit_code: Container process exit code.
            stdout: Captured standard output from the container.
            stderr: Captured standard error from the container.
        """
        conn = None
        try:
            conn = psycopg2.connect(
                host=self.db_config['host'],
                port=self.db_config['port'],
                dbname=self.db_config['database'],
                user=self.db_config['user'],
                password=self.db_config['password'],
            )
            conn.autocommit = False
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
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()

    def mark_completed(self, job_id: str, exit_code: int) -> None:
        """Update job status to 'completed' with the exit code.

        Sets the completed_at timestamp and records the container exit code
        in the serverless_jobs table.

        Args:
            job_id: UUID of the job to mark as completed.
            exit_code: Container process exit code.
        """
        conn = None
        try:
            conn = psycopg2.connect(
                host=self.db_config['host'],
                port=self.db_config['port'],
                dbname=self.db_config['database'],
                user=self.db_config['user'],
                password=self.db_config['password'],
            )
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
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()

    def mark_failed(self, job_id: str, error_message: str) -> None:
        """Update job status to 'failed' with an error message.

        Sets the completed_at timestamp and stores the error in the
        serverless_job_logs table as a stderr entry.

        Args:
            job_id: UUID of the job to mark as failed.
            error_message: Description of the failure.
        """
        conn = None
        try:
            conn = psycopg2.connect(
                host=self.db_config['host'],
                port=self.db_config['port'],
                dbname=self.db_config['database'],
                user=self.db_config['user'],
                password=self.db_config['password'],
            )
            conn.autocommit = False
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
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()

    def mark_timeout(self, job_id: str) -> None:
        """Update job status to 'timeout'.

        Sets the completed_at timestamp when a job exceeds its configured
        timeout_seconds limit. The container is stopped by the caller before
        this method is invoked.

        Args:
            job_id: UUID of the job to mark as timed out.
        """
        conn = None
        try:
            conn = psycopg2.connect(
                host=self.db_config['host'],
                port=self.db_config['port'],
                dbname=self.db_config['database'],
                user=self.db_config['user'],
                password=self.db_config['password'],
            )
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
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()


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
