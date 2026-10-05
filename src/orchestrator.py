"""App Orchestrator for multi-instance application management"""
# import sqlite3  # COMMENTED OUT - Using PostgreSQL now
import threading
import time
import json
import subprocess
import requests
import logging
import psycopg2
from contextlib import contextmanager
from .database_postgres import db_manager, get_runtime_type

logger = logging.getLogger(__name__)

class LightOrchestrator:
    """Simple orchestrator for managing multi-instance applications"""

    def __init__(self):
        self._lock = threading.Lock()
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
        """Reconcile desired vs actual state for a service"""
        with self._lock:
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

        # Start container
        try:
            container_id = self._start_container(
                server_id, instance_id, image, port, ports, environment, volumes
            )

            logger.debug(f"Started container {container_id} for {instance_id}")

            # Update instance with container ID
            with db_manager.get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE instances
                    SET container_id = %s, status = 'running', updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                ''', (container_id, db_instance_id))
                conn.commit()

        except Exception as e:
            logger.error(f"Failed to start instance {instance_id}: {e}")
            # Mark as failed
            with db_manager.get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE instances
                    SET status = 'failed', updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                ''', (db_instance_id,))
                conn.commit()

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

        # Add environment variables
        if environment:
            for key, value in environment.items():
                cmd.extend(['-e', f'{key}={value}'])

        # Add volumes
        if volumes:
            for volume in volumes:
                cmd.extend(['-v', volume])

        # Add restart policy
        cmd.extend(['--restart', 'unless-stopped'])

        # Add image
        cmd.append(image)

        # Execute command (locally for now, could be extended for remote servers)
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise Exception(f"Docker run failed: {result.stderr}")

        return result.stdout.strip()

    def _stop_instance(self, instance_db_id):
        """Stop and remove an instance"""
        with db_manager.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT container_id, instance_id FROM instances WHERE id = %s', (instance_db_id,))
            instance = cursor.fetchone()

            if instance and instance[0]:  # has container_id
                container_id = instance[0]
                instance_id = instance[1]

                try:
                    # Stop and remove container
                    subprocess.run(['docker', 'stop', container_id], check=True)
                    subprocess.run(['docker', 'rm', container_id], check=True)
                except subprocess.CalledProcessError as e:
                    logger.error(f"Failed to stop container {container_id}: {e}")

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

    def health_check_instances(self):
        """Check health of all running instances"""
        with db_manager.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT i.id, i.instance_id, i.port, s.health_check_path, srv.server_ip
                FROM instances i
                JOIN services s ON i.service_id = s.id
                JOIN servers srv ON i.server_id = srv.id
                WHERE i.status = 'running'
            ''')
            instances = cursor.fetchall()

            for instance in instances:
                instance_id, name, port, health_path, server_ip = instance

                try:
                    # Health check via HTTP
                    url = f"http://{server_ip}:{port}{health_path}"
                    response = requests.get(url, timeout=5)

                    if response.status_code == 200:
                        health_status = 'healthy'
                    else:
                        health_status = 'unhealthy'

                except Exception:
                    health_status = 'unhealthy'

                # Update health status
                cursor.execute('''
                    UPDATE instances
                    SET health_status = %s, last_health_check = CURRENT_TIMESTAMP
                    WHERE id = %s
                ''', (health_status, instance_id))

            conn.commit()

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

                    # Reconcile all services
                    with db_manager.get_db_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute('SELECT name, user_id FROM services')
                        services = cursor.fetchall()

                        for service in services:
                            self._reconcile_service(service[0], service[1])

                    # Update Nginx config if needed
                    self.generate_nginx_config()

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
        """Stop background reconciliation loop"""
        self._running = False
        if self._reconcile_thread:
            self._reconcile_thread.join()

# Global orchestrator instance
orchestrator = LightOrchestrator()
