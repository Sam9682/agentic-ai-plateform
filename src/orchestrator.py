"""App Orchestrator for multi-instance application management"""
# import sqlite3  # COMMENTED OUT - Using PostgreSQL now
import threading
import time
import json
import subprocess
import requests
import logging
import psycopg2
from enum import Enum
from contextlib import contextmanager
from .database_postgres import db_manager, get_runtime_type, DOMAIN
from .execution_policy import (
    BackoffParams,
    OutcomeStatus,
    run_with_policy,
    ssh_is_transient,
)
from .ssh_utils import ssh_execute_argv
from .advisory_lock import advisory_lock, reconcile_lock_key
from . import platform_discovery

logger = logging.getLogger(__name__)

# Wall-clock budget (seconds) for a single Docker subprocess invocation. Every
# Docker operation the orchestrator dispatches carries an explicit timeout so a
# hung container runtime can never wedge a reconcile pass (R3.1). Sized for
# container operations (image pulls, slow starts), matching
# ``ssh_utils.SSH_CONTAINER_TIMEOUT_DEFAULT``.
DOCKER_SUBPROCESS_TIMEOUT = 120

# Maximum number of attempts for a single transient-classified Docker/SSH
# failure within one start. The policy bounds the backoff *inside* a start;
# ``CRASH_LOOP_CAP`` bounds restarts *across* reconcile passes (persisted in
# ``instances.restart_attempts``), so a persistently failing image cannot retry
# forever (R3.2).
_START_MAX_ATTEMPTS = 3

# Consecutive failed-start cap. Once ``instances.restart_attempts`` reaches this
# value the orchestrator stops attempting to start that instance (R3.3). The
# counter is reset to 0 on a successful/healthy start.
CRASH_LOOP_CAP = 5

# Wall-clock budget (seconds) for ``stop_reconciliation_loop`` to wait on the
# background reconcile thread. Sized to ~one reconcile interval (the loop sleeps
# ``interval`` seconds, default 30, between passes) so a shutdown cannot hang
# indefinitely behind an in-flight pass (R3.6). The thread is a daemon, so a
# join that times out never blocks interpreter exit.
RECONCILE_JOIN_TIMEOUT = 30

# Per-attempt wall-clock budget (seconds) for a single HTTP health probe. The
# probe is retried a bounded number of times through the shared execution
# policy (see ``_probe_health_status_code``); this bounds each individual
# ``requests.get`` so a hung instance cannot stall the health pass. Preserves
# the prior single-shot ``timeout=5`` behavior per attempt.
HEALTH_PROBE_TIMEOUT = 5


def should_attempt_start(restart_attempts: int, cap: int) -> bool:
    """Return whether an instance start should be attempted (pure, R3.3/R3.9).

    The crash-loop cap bounds *consecutive* failed starts persisted in
    ``instances.restart_attempts`` across reconcile passes. A start is attempted
    while the recorded failure count is strictly below ``cap``; once the count
    reaches the cap the orchestrator stops retrying that instance so a
    persistently failing image cannot restart-loop forever.

    Pure and unit-testable without live Docker or PostgreSQL (R3.9).
    """
    return restart_attempts < cap


class RemediationAction(Enum):
    """Remediation decision for an instance in a reconcile pass (R4.2-4.4).

    * ``NONE`` — the instance is healthy or still within its start-up grace
      window; no action is taken (R4.1, R4.5 idempotent convergence).
    * ``RESTART`` — unhealthy past grace with consecutive failures below the
      crash-loop cap: restart the container in place (R4.2).
    * ``REPLACE`` — consecutive failures have reached the cap and the instance
      has not yet been replaced: replace it once (R4.3).
    * ``NEEDS_ATTENTION`` — a replaced instance is still unhealthy after the cap
      is exhausted: surface it for operator review (R4.4).
    """

    NONE = "none"
    RESTART = "restart"
    REPLACE = "replace"
    NEEDS_ATTENTION = "needs_attention"


def decide_remediation(health_state, consecutive_failures, within_grace, cap,
                       replaced):
    """Pure remediation state machine (R4.2-4.4, R4.7).

    Given the evaluated ``health_state`` (``{'healthy': bool, ...}`` from
    :func:`src.platform_discovery.evaluate_health`), the persisted
    ``consecutive_failures`` count (``instances.restart_attempts``), whether the
    probe is ``within_grace``, the crash-loop ``cap``, and whether the instance
    has already been ``replaced``, decide the next :class:`RemediationAction`.

    Escalation ladder (unhealthy past grace): restart-in-place until
    ``consecutive_failures`` reaches ``cap`` -> replace once -> still failing ->
    ``NEEDS_ATTENTION``. A healthy instance, or one still inside its grace
    window, yields ``NONE`` so re-running a pass over converged instances does
    nothing (R4.1, R4.5).

    Pure and unit-testable without live Docker or PostgreSQL (R4.7).
    """
    if health_state["healthy"]:
        return RemediationAction.NONE          # R4.5 idempotent convergence
    if within_grace:
        return RemediationAction.NONE          # R4.1 still starting up
    if consecutive_failures < cap:
        return RemediationAction.RESTART       # R4.2 restart in place
    if not replaced:
        return RemediationAction.REPLACE       # R4.3 replace once
    return RemediationAction.NEEDS_ATTENTION   # R4.4 terminal surface

# Shared external Docker network that Traefik joins so its Docker provider can
# reach app containers by name/alias. Every app container created here is
# attached to this network in addition to its default network so Traefik can
# route to it (nginx-to-traefik-migration design, "Docker network strategy").
TRAEFIK_SHARED_NETWORK = "swautomorph-shared"

# Canonical platform env var carrying the per-app Base_Path. template_deploy
# injects BASE_PATH=/{user}/{app}/ into the deployment environment; the
# orchestrator reads it to recover the user_name needed to build Traefik router
# names/rules without changing create_service's signature.
BASE_PATH_ENV_VAR = "BASE_PATH"

class LightOrchestrator:
    """Simple orchestrator for managing multi-instance applications"""

    def __init__(self):
        # Reconciliation is serialized across processes with a PostgreSQL
        # advisory lock (see ``_reconcile_service`` / ``reconcile_loop``) rather
        # than an in-process ``threading.Lock``, so separate orchestrator
        # processes contend on the same lock (R3.4, R3.5, R7.2, R7.3).
        #
        # ``_reconcile_lock_held`` is set by the background loop while it holds
        # the pass-level advisory lock, so the per-service ``_reconcile_service``
        # calls it makes do not try to re-acquire the same key on a second pool
        # connection (which would self-deadlock). Direct callers (create/scale)
        # leave it False and acquire the lock themselves.
        self._reconcile_lock_held = False
        self._reconcile_thread = None
        self._running = False

    def init_orchestrator_tables(self):
        """Initialize orchestrator-specific tables (now handled by postgresql_schema.sql)"""
        # Tables are now created via postgresql_schema.sql
        # This method kept for backward compatibility
        pass

    def create_service(self, name, image, user_id, desired_replicas=1, ports=None, environment=None, volumes=None, health_check_path='/health'):
        """Create a new service"""
        logger.debug(f"Creating service {name} for user {user_id} with {desired_replicas} replicas")

        ports_json = json.dumps(ports) if ports else None
        env_json = json.dumps(environment) if environment else None
        volumes_json = json.dumps(volumes) if volumes else None

        with db_manager.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO services
                (name, image, user_id, desired_replicas, ports, environment, volumes, health_check_path, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (name, user_id) DO UPDATE SET
                image = EXCLUDED.image,
                desired_replicas = EXCLUDED.desired_replicas,
                ports = EXCLUDED.ports,
                environment = EXCLUDED.environment,
                volumes = EXCLUDED.volumes,
                health_check_path = EXCLUDED.health_check_path,
                updated_at = CURRENT_TIMESTAMP
            ''', (name, image, user_id, desired_replicas, ports_json, env_json, volumes_json, health_check_path))
            conn.commit()
            logger.debug(f"Service {name} created in database for user {user_id}")

        # Trigger reconciliation
        try:
            self._reconcile_service(name, user_id)
            logger.debug(f"Reconciliation triggered for {name}")
        except Exception as e:
            logger.error(f"Reconciliation failed for {name}: {e}")

    def scale_service(self, service_name, user_id, replicas):
        """Scale a service to desired number of replicas"""
        with db_manager.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE services SET desired_replicas = %s, updated_at = CURRENT_TIMESTAMP
                WHERE name = %s AND user_id = %s
            ''', (replicas, service_name, user_id))
            conn.commit()

        self._reconcile_service(service_name, user_id)

    def delete_service(self, service_name, user_id):
        """Delete a service and all its instances"""
        # Stop all instances first
        self._stop_all_instances(service_name, user_id)

        with db_manager.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM services WHERE name = %s AND user_id = %s', (service_name, user_id))
            conn.commit()

    def get_service_status(self, service_name=None, user_id=None):
        """Get status of services and their instances"""
        with db_manager.get_db_connection() as conn:
            cursor = conn.cursor()

            if service_name and user_id:
                cursor.execute('SELECT * FROM services WHERE name = %s AND user_id = %s', (service_name, user_id))
                services = cursor.fetchall()
            elif user_id:
                cursor.execute('SELECT * FROM services WHERE user_id = %s', (user_id,))
                services = cursor.fetchall()
            else:
                cursor.execute('SELECT * FROM services')
                services = cursor.fetchall()

            result = []
            for service in services:
                service_data = {
                    'name': service[1],
                    'image': service[2],
                    'user_id': service[3],
                    'desired_replicas': service[4],
                    'ports': json.loads(service[5]) if service[5] else {},
                    'instances': []
                }

                # Get instances for this service
                cursor.execute('''
                    SELECT i.*, s.server_name, s.server_ip
                    FROM instances i
                    JOIN servers s ON i.server_id = s.id
                    WHERE i.service_id = %s
                ''', (service[0],))
                instances = cursor.fetchall()

                for instance in instances:
                    service_data['instances'].append({
                        'instance_id': instance[2],
                        'server_name': instance[11],
                        'server_ip': instance[12],
                        'container_id': instance[4],
                        'status': instance[5],
                        'port': instance[6],
                        'health_status': instance[7]
                    })

                result.append(service_data)

            return result

    def _reconcile_service(self, service_name, user_id):
        """Reconcile desired vs actual state for a service.

        Reconciliation is serialized across processes with a PostgreSQL advisory
        lock on ``reconcile_lock_key()`` instead of an in-process
        ``threading.Lock`` (R3.4, R3.5, R7.2, R7.3). Direct callers (create/scale)
        acquire the lock *blocking* here. When the background reconcile loop
        already holds the pass-level lock (``_reconcile_lock_held``) it reconciles
        directly without re-acquiring the same key on a second pool connection
        (which would self-deadlock).
        """
        if self._reconcile_lock_held:
            self._reconcile_service_locked(service_name, user_id)
            return

        with db_manager.get_db_connection() as conn:
            with advisory_lock(conn, reconcile_lock_key()):
                self._reconcile_service_locked(service_name, user_id)

    def _reconcile_service_locked(self, service_name, user_id):
        """Reconcile a single service assuming the reconcile lock is held."""
        with db_manager.get_db_connection() as conn:
            cursor = conn.cursor()

            # Get service configuration
            cursor.execute('SELECT * FROM services WHERE name = %s AND user_id = %s', (service_name, user_id))
            service = cursor.fetchone()
            if not service:
                return

            desired_replicas = service[4] or 0

            # Get current running instances
            cursor.execute('''
                SELECT * FROM instances
                WHERE service_id = %s AND status IN ('running', 'pending')
            ''', (service[0],))
            current_instances = cursor.fetchall()

            current_count = len(current_instances)

            if current_count < desired_replicas:
                # Need to create more instances
                for i in range(current_count, desired_replicas):
                    try:
                        self._create_instance(service, i + 1)
                    except Exception as e:
                        logger.error(f"Failed to create instance for service {service_name}: {e}")
                        # Continue with remaining instances even if one fails
                        continue
            elif current_count > desired_replicas:
                # Need to remove instances
                instances_to_remove = current_instances[desired_replicas:]
                for instance in instances_to_remove:
                    self._stop_instance(instance[0])  # instance id

    @staticmethod
    def _is_git_url(image):
        """Check if the image field is a git URL rather than a Docker image reference"""
        if not image:
            return False
        return (image.endswith('.git')
                or image.startswith('http://') or image.startswith('https://')
                or image.startswith('git@')
                or 'github.com' in image or 'gitlab.com' in image
                or 'gitea' in image or 'forgejo' in image)

    def _create_instance(self, service, replica_num):
        """Create a new instance of a service"""
        service_name = service[1]
        image = service[2]
        user_id = service[3]
        ports = json.loads(service[5]) if service[5] else {}
        environment = json.loads(service[6]) if service[6] else {}
        volumes = json.loads(service[7]) if service[7] else []

        # Skip docker run for git-based services — these are managed by
        # multi_user_deploy via deployApp.sh, not by the orchestrator's
        # container lifecycle.
        if self._is_git_url(image):
            logger.debug(
                f"Skipping _create_instance for git-based service '{service_name}' "
                f"(replica {replica_num}). Managed via deployApp.sh."
            )
            return

        logger.debug(f"Creating instance for service {service_name}")

        # Select best server using simple scheduler
        server_id = self._select_server()
        if not server_id:
            logger.error(f"No available server for {service_name}")
            return

        logger.debug(f"Selected server {server_id} for {service_name}")

        instance_id = f"{service_name}-replica-{replica_num}"

        # Find available port
        port = self._find_available_port(server_id)
        logger.debug(f"Assigned port {port} to {instance_id}")

        # Create instance record with conflict handling
        with db_manager.get_db_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute('''
                    INSERT INTO instances
                    (service_id, instance_id, server_id, status, port)
                    VALUES (%s, %s, %s, 'pending', %s) RETURNING id
                ''', (service[0], instance_id, server_id, port))
                db_instance_id = cursor.fetchone()[0]
                conn.commit()
                logger.debug(f"Created instance record {db_instance_id}")
            except psycopg2.IntegrityError as e:
                # Handle duplicate key violation
                if "instances_service_id_instance_id_key" in str(e):
                    logger.warning(f"Instance {instance_id} already exists for service {service_name}, skipping creation")
                    conn.rollback()
                    return
                else:
                    # Re-raise other integrity errors
                    conn.rollback()
                    raise
            except Exception:
                # Rollback on any other exception
                conn.rollback()
                raise

        # Crash-loop cap: stop attempting to start an instance that has already
        # failed ``CRASH_LOOP_CAP`` consecutive times (R3.3). The counter is
        # persisted in ``instances.restart_attempts`` so the bound holds across
        # reconcile passes, not just within a single process.
        restart_attempts = self._get_restart_attempts(db_instance_id)
        if not should_attempt_start(restart_attempts, CRASH_LOOP_CAP):
            logger.warning(
                "Instance %s has reached the crash-loop cap (%s attempts); "
                "not attempting start",
                instance_id, CRASH_LOOP_CAP,
            )
            return

        # Start container
        try:
            container_id = self._start_container(
                server_id, instance_id, image, port, ports, environment, volumes
            )

            logger.debug(f"Started container {container_id} for {instance_id}")

            # Update instance with container ID and reset the crash-loop counter
            # on a successful start (R3.3).
            with db_manager.get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE instances
                    SET container_id = %s, status = 'running', restart_attempts = 0,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                ''', (container_id, db_instance_id))
                conn.commit()

        except Exception as e:
            logger.error(f"Failed to start instance {instance_id}: {e}")
            # Mark as failed and increment the consecutive-failure counter so the
            # crash-loop cap can eventually stop retrying (R3.2, R3.3).
            with db_manager.get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE instances
                    SET status = 'failed',
                        restart_attempts = restart_attempts + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                ''', (db_instance_id,))
                conn.commit()

    @staticmethod
    def _get_restart_attempts(db_instance_id):
        """Return the persisted consecutive failed-start count for an instance.

        Reads ``instances.restart_attempts`` (added by
        ``migration/add_instance_remediation.sql``). Returns 0 when the row or
        column is unavailable so the crash-loop cap degrades to "always attempt"
        rather than raising.
        """
        try:
            with db_manager.get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'SELECT restart_attempts FROM instances WHERE id = %s',
                    (db_instance_id,),
                )
                row = cursor.fetchone()
                if row and row[0] is not None:
                    return int(row[0])
        except Exception as e:  # noqa: BLE001 - counter read is best-effort
            logger.debug("Could not read restart_attempts for %s: %s",
                         db_instance_id, e)
        return 0

    @staticmethod
    def _user_app_from_environment(environment, fallback_app_name):
        """Recover ``(user_name, app_name)`` for Traefik routing.

        template_deploy injects ``BASE_PATH=/{user}/{app}/`` into the deployment
        environment (design "Base_Path propagation to apps"). We parse it here so
        the orchestrator can build the Traefik router name/rule without a new
        ``create_service`` parameter. If BASE_PATH is absent or malformed, we fall
        back to the service name as the app and leave the user empty so the
        router name degrades gracefully instead of raising.
        """
        base_path = None
        if isinstance(environment, dict):
            base_path = environment.get(BASE_PATH_ENV_VAR)

        if base_path:
            parts = [segment for segment in str(base_path).split('/') if segment]
            if len(parts) >= 2:
                return parts[0], parts[1]
            if len(parts) == 1:
                return "", parts[0]

        return "", fallback_app_name

    @staticmethod
    def _internal_http_port(ports, fallback_port):
        """Return the container's internal HTTP port for the Traefik service.

        Traefik reaches the app over the shared network, so the backend port is
        the port the app listens on *inside* the container — the ``container_port``
        key of the ports map — not the published host port (retires docker ps
        discovery, Req 1.5). Falls back to the allocated host port if the ports
        map is empty.
        """
        if ports:
            try:
                first_container_port = next(iter(ports.keys()))
                return int(first_container_port)
            except (StopIteration, TypeError, ValueError):
                pass
        return fallback_port

    def _build_traefik_labels(self, user_name, app_name, backend_port):
        """Build the Traefik Docker-provider labels for an app container.

        Mirrors design "Concrete label example": enable Traefik on the shared
        network, a host+prefix router on the websecure entrypoint with TLS, a
        StripPrefix middleware removing the per-app prefix, and a service pointing
        at the container's internal HTTP port (Req 1.3, 1.4, 1.5, 3.2).
        """
        router = f"{user_name}-{app_name}" if user_name else app_name
        prefix = f"/{user_name}/{app_name}" if user_name else f"/{app_name}"
        return {
            "traefik.enable": "true",
            "traefik.docker.network": TRAEFIK_SHARED_NETWORK,
            f"traefik.http.routers.{router}.rule":
                f"Host(`{DOMAIN}`) && PathPrefix(`{prefix}`)",
            f"traefik.http.routers.{router}.entrypoints": "websecure",
            f"traefik.http.routers.{router}.tls": "true",
            f"traefik.http.routers.{router}.middlewares": f"{router}-strip",
            f"traefik.http.middlewares.{router}-strip.stripprefix.prefixes": prefix,
            f"traefik.http.services.{router}.loadbalancer.server.port": str(backend_port),
        }

    def _start_container(self, server_id, instance_id, image, port, ports, environment, volumes):
        """Start a Docker container"""
        # Get server info
        with db_manager.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT server_ip FROM servers WHERE id = %s', (server_id,))
            server_ip = cursor.fetchone()[0]

        # Build docker run command
        cmd = ['docker', 'run', '-d', '--name', instance_id]

        # Select container runtime (e.g. 'kata' MicroVM isolation). 'runc' is
        # the Docker default, so the flag is only emitted for non-default values.
        runtime_type = get_runtime_type()
        if runtime_type != 'runc':
            logger.debug(f"Using container runtime '{runtime_type}' for {instance_id}")
            cmd.extend(['--runtime', runtime_type])

        # Add port mappings
        if ports:
            for container_port, host_port in ports.items():
                cmd.extend(['-p', f'{port}:{container_port}'])

        # Add environment variables. BASE_PATH (injected by template_deploy) is
        # forwarded here unchanged so it reaches the container at create time;
        # we do not re-inject it (template_deploy owns that value).
        if environment:
            for key, value in environment.items():
                cmd.extend(['-e', f'{key}={value}'])

        # Add volumes
        if volumes:
            for volume in volumes:
                cmd.extend(['-v', volume])

        # Attach the app container to the shared Traefik network so Traefik's
        # Docker provider can reach it by name/alias. This replaces the old
        # nginx-sidecar + <HTTPS_PORT>:443 publish model: the container is
        # exposed purely through Traefik labels + the shared network, never a
        # published :443 (Req 1.1, 1.4, 2.2).
        cmd.extend(['--network', TRAEFIK_SHARED_NETWORK])

        # Attach Traefik routing labels so the route is discovered the moment the
        # container starts, with no docker ps port scraping (Req 1.3, 1.5).
        user_name, app_name = self._user_app_from_environment(
            environment, fallback_app_name=instance_id
        )
        backend_port = self._internal_http_port(ports, port)
        for label_key, label_value in self._build_traefik_labels(
            user_name, app_name, backend_port
        ).items():
            cmd.extend(['-l', f'{label_key}={label_value}'])

        # Add restart policy
        cmd.extend(['--restart', 'unless-stopped'])

        # Add image
        cmd.append(image)

        # Dispatch the docker run on the instance's selected server via the
        # hardened ssh_utils argv transport (R3.7). ``ssh_execute_argv`` passes
        # the command as an argument array with safe quoting and transparently
        # short-circuits to local execution when ``server_ip`` is this host
        # (``is_local_server``), so single-node installs behave exactly as
        # before. The call is wrapped in the shared execution policy so a
        # transient SSH/Docker failure retries with bounded backoff while a
        # deterministic failure fails fast (R3.2). Every attempt carries an
        # explicit timeout (R3.1). No nginx path is reintroduced (R3.8).
        container_id = self._run_docker_argv(
            server_ip, cmd, action=f"start {instance_id}"
        )
        return container_id

    def _run_docker_argv(self, server_ip, argv, *, action):
        """Run a Docker argv on ``server_ip`` under the shared execution policy.

        Routes the per-server ``ssh_execute_argv`` dispatch through
        :func:`src.execution_policy.run_with_policy` so a transient failure
        retries with bounded backoff and a deterministic failure (non-zero
        docker exit that is not transient) fails fast without retry (R3.2).
        Each attempt is bounded by :data:`DOCKER_SUBPROCESS_TIMEOUT` (R3.1).

        Returns the trimmed stdout (the container id for ``docker run -d``).
        Raises ``Exception`` on any terminal non-success so the caller can mark
        the instance failed and increment the crash-loop counter.
        """
        def op(_token):
            success, stdout, stderr = ssh_execute_argv(
                server_ip, argv, timeout=DOCKER_SUBPROCESS_TIMEOUT
            )
            if not success:
                # Surface stderr so ``ssh_is_transient`` can classify the
                # failure (transient network blip -> retry; deterministic docker
                # error -> terminal). ``ssh_execute_argv`` already retries
                # transient SSH transport errors internally; a non-success tuple
                # here reflects the terminal remote outcome, so raise a plain
                # exception carrying stderr and let the policy classify it.
                raise Exception(stderr or f"docker {action} failed")
            return stdout.strip()

        outcome = run_with_policy(
            op,
            timeout=None,  # each attempt is bounded by the subprocess timeout
            max_attempts=_START_MAX_ATTEMPTS,
            backoff=BackoffParams(),
            is_transient=ssh_is_transient,
        )

        if outcome.status == OutcomeStatus.SUCCEEDED:
            return outcome.value

        err = outcome.error
        stderr = getattr(err, "stderr", None) or (str(err) if err else "")
        raise Exception(
            f"Docker {action} failed ({outcome.status.value}): {stderr}"
        )

    def _stop_instance(self, instance_db_id):
        """Stop and remove an instance"""
        with db_manager.get_db_connection() as conn:
            cursor = conn.cursor()
            # Resolve the instance's selected server so the stop/rm run on the
            # server that actually hosts the container (R3.7) rather than always
            # locally. ``is_local_server`` keeps single-node installs local.
            cursor.execute('''
                SELECT i.container_id, i.instance_id, srv.server_ip
                FROM instances i
                JOIN servers srv ON i.server_id = srv.id
                WHERE i.id = %s
            ''', (instance_db_id,))
            instance = cursor.fetchone()

            if instance and instance[0]:  # has container_id
                container_id = instance[0]
                instance_id = instance[1]
                server_ip = instance[2]

                # Stop then remove the container on its host server via the
                # hardened argv transport. Each docker subprocess carries an
                # explicit timeout (R3.1) and runs through the shared execution
                # policy so a transient failure retries with bounded backoff
                # (R3.2). A stop/rm failure is logged but does not block removal
                # of the instance record, preserving the prior best-effort
                # semantics.
                for verb in ('stop', 'rm'):
                    try:
                        self._run_docker_argv(
                            server_ip,
                            ['docker', verb, container_id],
                            action=f"{verb} {instance_id}",
                        )
                    except Exception as e:  # noqa: BLE001 - best-effort cleanup
                        logger.error(
                            "Failed to %s container %s: %s",
                            verb, container_id, e,
                        )

            # Remove instance record
            cursor.execute('DELETE FROM instances WHERE id = %s', (instance_db_id,))
            conn.commit()

    def _stop_all_instances(self, service_name, user_id):
        """Stop all instances of a service"""
        with db_manager.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT i.id FROM instances i
                JOIN services s ON i.service_id = s.id
                WHERE s.name = %s AND s.user_id = %s
            ''', (service_name, user_id))
            instances = cursor.fetchall()

            for instance in instances:
                self._stop_instance(instance[0])

    def _select_server(self):
        """Simple scheduler - select server with least instances"""
        with db_manager.get_db_connection() as conn:
            cursor = conn.cursor()

            cursor.execute('''
                SELECT s.id, COALESCE(s.server_capacity_appli_max, 100) as capacity, COUNT(i.id) as current_instances
                FROM servers s
                LEFT JOIN instances i ON s.id = i.server_id AND i.status = 'running'
                WHERE s.server_status IN ('STAND_BY', 'ACTIVE')
                GROUP BY s.id, s.server_capacity_appli_max
                HAVING COUNT(i.id) < COALESCE(s.server_capacity_appli_max, 100)
                ORDER BY COUNT(i.id) ASC
                LIMIT 1
            ''')
            result = cursor.fetchone()
            return result[0] if result else None

    def _find_available_port(self, server_id, start_port=8000):
        """Find an available port on a server"""
        with db_manager.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT port FROM instances
                WHERE server_id = %s AND status = 'running' AND port IS NOT NULL
                ORDER BY port
            ''', (server_id,))
            used_ports = {row[0] for row in cursor.fetchall() if row[0]}

        port = start_port
        while port in used_ports:
            port += 1
        return port

    def _probe_health_status_code(self, url):
        """Probe an instance's health URL, retrying transient failures (R4.1).

        The HTTP probe is routed through the shared execution policy with a
        short bound (:data:`platform_discovery.HEALTH_PROBE_MAX_ATTEMPTS`) so a
        transient network blip does not immediately look unhealthy while a
        persistent failure still resolves quickly within one reconcile pass. A
        connection-level error is raised so ``ssh_is_transient`` can classify it
        as retryable; an exhausted retry or a non-200 response yields the
        observed status code (``None`` when the probe never connected).

        Returns the final HTTP status code, or ``None`` when the probe could not
        reach the instance after its bounded retries.
        """
        def op(_token):
            response = requests.get(url, timeout=HEALTH_PROBE_TIMEOUT)
            return response.status_code

        outcome = run_with_policy(
            op,
            timeout=None,  # each attempt is bounded by the requests timeout
            max_attempts=platform_discovery.HEALTH_PROBE_MAX_ATTEMPTS,
            backoff=BackoffParams(),
            is_transient=ssh_is_transient,
        )

        if outcome.status == OutcomeStatus.SUCCEEDED:
            return outcome.value
        # A transient probe failure that exhausted its retries (or any other
        # terminal) is treated as "could not reach" -> unhealthy input.
        return None

    def health_check_instances(self):
        """Check health of running instances and remediate the unhealthy ones.

        Each instance's HTTP probe is retried through the shared execution
        policy (short bound) and evaluated with
        :func:`src.platform_discovery.evaluate_health` against its persisted
        ``grace_until`` so a still-starting instance is not remediated (R4.1).
        The pure :func:`decide_remediation` state machine then selects the
        action using the persisted ``restart_attempts`` and ``replaced`` flags,
        and the orchestrator escalates restart -> replace -> needs_attention
        (R4.2-R4.4).

        Remediation keys on the stable ``(service_id, instance_id)`` identity so
        re-running a pass over an already-converged instance performs no side
        effects (R4.5, R7.1). The reconcile loop serializes passes across
        processes with the advisory lock (R7.2).
        """
        with db_manager.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT i.id, i.service_id, i.instance_id, i.port,
                       s.health_check_path, srv.server_ip,
                       i.restart_attempts, i.replaced,
                       EXTRACT(EPOCH FROM i.grace_until),
                       EXTRACT(EPOCH FROM NOW())
                FROM instances i
                JOIN services s ON i.service_id = s.id
                JOIN servers srv ON i.server_id = srv.id
                WHERE i.status = 'running'
            ''')
            instances = cursor.fetchall()

            for instance in instances:
                (db_id, service_id, instance_id, port, health_path, server_ip,
                 restart_attempts, replaced, grace_until_epoch,
                 now_epoch) = instance

                url = f"http://{server_ip}:{port}{health_path}"
                status_code = self._probe_health_status_code(url)

                now = float(now_epoch) if now_epoch is not None else time.time()
                grace_until = (
                    float(grace_until_epoch)
                    if grace_until_epoch is not None else None
                )
                health_state = platform_discovery.evaluate_health(
                    status_code, now, grace_until
                )
                health_status = 'healthy' if health_state['healthy'] else 'unhealthy'
                within_grace = health_state['within_grace']

                # Persist the observed health status for every instance.
                cursor.execute('''
                    UPDATE instances
                    SET health_status = %s, last_health_check = CURRENT_TIMESTAMP
                    WHERE id = %s
                ''', (health_status, db_id))

                action = decide_remediation(
                    health_state,
                    consecutive_failures=restart_attempts or 0,
                    within_grace=within_grace,
                    cap=CRASH_LOOP_CAP,
                    replaced=bool(replaced),
                )

                if action == RemediationAction.NONE:
                    # Healthy or still within grace. Reset the crash-loop
                    # counter on a healthy instance so a later failure starts
                    # the escalation ladder fresh (R4.5 idempotent convergence).
                    if health_state['healthy'] and (restart_attempts or 0) != 0:
                        cursor.execute('''
                            UPDATE instances
                            SET restart_attempts = 0, updated_at = CURRENT_TIMESTAMP
                            WHERE id = %s
                        ''', (db_id,))
                    continue

                try:
                    self._remediate_instance(
                        conn, cursor, db_id, service_id, instance_id, action
                    )
                except Exception as e:  # noqa: BLE001 - one bad instance must
                    # not abort the whole health pass.
                    logger.error(
                        "Remediation (%s) failed for instance %s: %s",
                        action.value, instance_id, e,
                    )

            conn.commit()

    def _remediate_instance(self, conn, cursor, db_id, service_id, instance_id,
                            action):
        """Apply a remediation ``action`` to an unhealthy instance (R4.2-R4.4).

        Keyed on the stable ``(service_id, instance_id)`` identity so the action
        converges the same instance idempotently across passes (R4.5, R7.1):

        * ``RESTART`` — stop+start the container in place and increment the
          persisted ``restart_attempts`` crash-loop counter.
        * ``REPLACE`` — tear the instance down and recreate it, marking
          ``replaced`` so a still-failing instance escalates next pass.
        * ``NEEDS_ATTENTION`` — flag the instance for operator review; no
          further automatic recovery is attempted.
        """
        if action == RemediationAction.RESTART:
            logger.info("Restarting unhealthy instance %s in place", instance_id)
            self._restart_instance_in_place(cursor, db_id)
            cursor.execute('''
                UPDATE instances
                SET restart_attempts = restart_attempts + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            ''', (db_id,))

        elif action == RemediationAction.REPLACE:
            logger.warning(
                "Replacing instance %s after crash-loop cap reached", instance_id
            )
            cursor.execute('''
                UPDATE instances
                SET replaced = TRUE, restart_attempts = 0,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            ''', (db_id,))
            self._replace_instance(service_id, instance_id)

        elif action == RemediationAction.NEEDS_ATTENTION:
            logger.error(
                "Instance %s remains unhealthy after restart+replace; "
                "marking needs_attention", instance_id
            )
            cursor.execute('''
                UPDATE instances
                SET needs_attention = TRUE, health_status = 'unhealthy',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            ''', (db_id,))

    def _restart_instance_in_place(self, cursor, db_id):
        """Restart an instance's container on its host server (R4.2).

        Resolves the container id and host ``server_ip`` and issues a
        ``docker restart`` through the hardened argv transport so the restart
        runs on the instance's selected server with a bounded timeout and the
        shared execution policy, exactly like start/stop.
        """
        cursor.execute('''
            SELECT i.container_id, srv.server_ip
            FROM instances i
            JOIN servers srv ON i.server_id = srv.id
            WHERE i.id = %s
        ''', (db_id,))
        row = cursor.fetchone()
        if not row or not row[0]:
            return
        container_id, server_ip = row[0], row[1]
        self._run_docker_argv(
            server_ip,
            ['docker', 'restart', container_id],
            action=f"restart {container_id}",
        )

    def _replace_instance(self, service_id, instance_id):
        """Replace a persistently unhealthy instance (R4.3).

        Tears the existing container down and lets the next reconcile pass
        recreate the instance from the service's desired replica count. Keyed on
        ``(service_id, instance_id)`` so replacing is idempotent for the same
        logical instance.
        """
        with db_manager.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT i.container_id, srv.server_ip
                FROM instances i
                JOIN servers srv ON i.server_id = srv.id
                WHERE i.service_id = %s AND i.instance_id = %s
            ''', (service_id, instance_id))
            row = cursor.fetchone()
            if row and row[0]:
                container_id, server_ip = row[0], row[1]
                for verb in ('stop', 'rm'):
                    try:
                        self._run_docker_argv(
                            server_ip,
                            ['docker', verb, container_id],
                            action=f"{verb} {instance_id}",
                        )
                    except Exception as e:  # noqa: BLE001 - best-effort teardown
                        logger.error(
                            "Failed to %s container %s during replace: %s",
                            verb, container_id, e,
                        )

    def generate_nginx_config(self):
        """Generate Nginx upstream configuration for all services"""
        config_lines = []

        with db_manager.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT DISTINCT s.id, s.name FROM services s
                JOIN instances i ON i.service_id = s.id
                WHERE i.status = 'running'
            ''')
            services = cursor.fetchall()

            for service in services:
                service_id, service_name = service[0], service[1]

                # Get healthy instances
                cursor.execute('''
                    SELECT srv.server_ip, i.port
                    FROM instances i
                    JOIN servers srv ON i.server_id = srv.id
                    WHERE i.service_id = %s AND i.status = 'running'
                    AND (i.health_status = 'healthy' OR i.health_status = 'unknown')
                ''', (service_id,))
                instances = cursor.fetchall()

                if instances:
                    config_lines.append(f"upstream {service_name} {{")
                    config_lines.append("    least_conn;")

                    for instance in instances:
                        server_ip, port = instance
                        config_lines.append(f"    server {server_ip}:{port};")

                    config_lines.append("}")
                    config_lines.append("")

        return "\n".join(config_lines)

    def reload_nginx(self):
        """Reload Nginx configuration"""
        try:
            subprocess.run(['nginx', '-s', 'reload'], check=True)
            return True
        except subprocess.CalledProcessError:
            return False

    def start_reconciliation_loop(self, interval=30):
        """Start background reconciliation loop"""
        if self._running:
            return

        self._running = True

        def reconcile_loop():
            while self._running:
                try:
                    # Health check all instances
                    self.health_check_instances()

                    # Serialize the reconcile pass across processes with a
                    # non-blocking advisory lock. If another orchestrator
                    # process already holds it, skip this pass instead of
                    # waiting — that process is reconciling, and skipping avoids
                    # the duplicate-key integrity error concurrent passes would
                    # otherwise race into (R3.4, R3.5, R7.2, R7.3).
                    with db_manager.get_db_connection() as conn:
                        with advisory_lock(conn, reconcile_lock_key(), blocking=False) as acquired:
                            if not acquired:
                                logger.debug(
                                    "Reconcile lock held by another process; skipping this pass"
                                )
                            else:
                                # Reconcile all services. The pass-level lock is
                                # already held, so flag it so each
                                # _reconcile_service call does not re-acquire the
                                # same key on another pool connection.
                                cursor = conn.cursor()
                                cursor.execute('SELECT name, user_id FROM services')
                                services = cursor.fetchall()

                                self._reconcile_lock_held = True
                                try:
                                    for service in services:
                                        self._reconcile_service(service[0], service[1])
                                finally:
                                    self._reconcile_lock_held = False

                except Exception as e:
                    logger.error(f"Reconciliation error: {e}")
                    # Log more details about the error for debugging
                    if "duplicate key value violates unique constraint" in str(e) and "instances_service_id_instance_id_key" in str(e):
                        logger.error(f"Duplicate instance key error details: {e}")
                        # Try to extract service info from the error
                        try:
                            # This is a workaround to get more context about the problematic service
                            logger.error(f"Problematic service info - Name: {service_name}, User ID: {user_id}")
                        except:
                            pass

                time.sleep(interval)

        self._reconcile_thread = threading.Thread(target=reconcile_loop, daemon=True)
        self._reconcile_thread.start()

    def stop_reconciliation_loop(self):
        """Stop background reconciliation loop.

        Join with a bounded timeout (``RECONCILE_JOIN_TIMEOUT``, ~one reconcile
        interval) so shutdown cannot hang behind an in-flight pass (R3.6). The
        thread is a daemon, so a timed-out join never blocks interpreter exit.
        """
        self._running = False
        if self._reconcile_thread:
            self._reconcile_thread.join(timeout=RECONCILE_JOIN_TIMEOUT)

# Global orchestrator instance
orchestrator = LightOrchestrator()
