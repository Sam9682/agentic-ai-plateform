"""PostgreSQL database manager for the platform."""
import psycopg2
import psycopg2.pool
import threading
import time
import os
import logging
import configparser
from contextlib import contextmanager
from werkzeug.security import generate_password_hash
from .config_postgres import get_database_config, AI_ENGINE
from .query_converter import convert_sqlite_to_postgres_query

logger = logging.getLogger(__name__)

# Allowed container runtime types. Anything else is rejected and falls back to
# 'runc' to prevent arbitrary values being passed to `docker run --runtime`.
ALLOWED_RUNTIME_TYPES = {'runc', 'kata'}
DEFAULT_RUNTIME_TYPE = 'runc'

# Load deploy.ini configuration
def load_deploy_config():
    """Load configuration from deploy.ini file"""
    config = configparser.ConfigParser()
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'conf', 'deploy.ini')

    # Default values matching deployControlPlan.sh
    NAME_OF_APPLICATION = "agentic-ai-plateform"
    APPLICATION_IDENTITY_NUMBER = 0
    RANGE_START = 6000
    RANGE_RESERVED = 100
    RANGE_START_CONTROLPLAN = 80
    RANGE_RESERVED_CONTROLPLAN = 0
    RANGE_PORTS_PER_APPLICATION = 12
    DOMAIN = "softfluid.fr"

    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                content = f.read()

            # Parse key=value pairs
            for line in content.split('\n'):
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip().strip('"')

                    if key == 'NAME_OF_APPLICATION':
                        NAME_OF_APPLICATION = value
                    elif key == 'APPLICATION_IDENTITY_NUMBER':
                        APPLICATION_IDENTITY_NUMBER = int(value)
                    elif key == 'RANGE_START':
                        RANGE_START = int(value)
                    elif key == 'RANGE_RESERVED':
                        RANGE_RESERVED = int(value)
                    elif key == 'RANGE_START_CONTROLPLAN':
                        RANGE_START_CONTROLPLAN = int(value)
                    elif key == 'RANGE_RESERVED_CONTROLPLAN':
                        RANGE_RESERVED_CONTROLPLAN = int(value)
                    elif key == 'RANGE_PORTS_PER_APPLICATION':
                        RANGE_PORTS_PER_APPLICATION = int(value)
                    elif key =='DOMAIN':
                        DOMAIN = value
        except Exception as e:
            print(f"Warning: Could not load deploy.ini: {e}")

    return NAME_OF_APPLICATION, APPLICATION_IDENTITY_NUMBER, RANGE_START, RANGE_RESERVED, RANGE_START_CONTROLPLAN, RANGE_RESERVED_CONTROLPLAN, RANGE_PORTS_PER_APPLICATION, DOMAIN

# Load configuration values
NAME_OF_APPLICATION, APPLICATION_IDENTITY_NUMBER, RANGE_START, RANGE_RESERVED, RANGE_START_CONTROLPLAN, RANGE_RESERVED_CONTROLPLAN, RANGE_PORTS_PER_APPLICATION, DOMAIN = load_deploy_config()

def calculate_app_ports(user_id, app_id):
    """Calculate 12 consecutive ports (6 HTTP + 6 HTTPS) per application,
    using the same logic as deployControlPlan.sh calculate_ports().

    Returns a tuple of 12 ports in the order:
        HTTP_PORT, HTTPS_PORT,
        HTTP_PORT2, HTTPS_PORT2,
        HTTP_PORT3, HTTPS_PORT3,
        HTTP_PORT4, HTTPS_PORT4,
        HTTP_PORT5, HTTPS_PORT5,
        HTTP_PORT6, HTTPS_PORT6
    """
    PORT_RANGE_BEGIN = RANGE_START + user_id * RANGE_RESERVED
    HTTP_PORT = PORT_RANGE_BEGIN + app_id * RANGE_PORTS_PER_APPLICATION
    HTTPS_PORT = HTTP_PORT + 1
    HTTP_PORT2 = HTTPS_PORT + 1
    HTTPS_PORT2 = HTTP_PORT2 + 1
    HTTP_PORT3 = HTTPS_PORT2 + 1
    HTTPS_PORT3 = HTTP_PORT3 + 1
    HTTP_PORT4 = HTTPS_PORT3 + 1
    HTTPS_PORT4 = HTTP_PORT4 + 1
    HTTP_PORT5 = HTTPS_PORT4 + 1
    HTTPS_PORT5 = HTTP_PORT5 + 1
    HTTP_PORT6 = HTTPS_PORT5 + 1
    HTTPS_PORT6 = HTTP_PORT6 + 1
    return (
        HTTP_PORT, HTTPS_PORT,
        HTTP_PORT2, HTTPS_PORT2,
        HTTP_PORT3, HTTPS_PORT3,
        HTTP_PORT4, HTTPS_PORT4,
        HTTP_PORT5, HTTPS_PORT5,
        HTTP_PORT6, HTTPS_PORT6,
    )


# Ordered list of the 12 per-application port columns, matching the return
# order of calculate_app_ports(). Used to build INSERT/UPDATE statements so
# the column list, placeholders and value tuple always stay in sync.
APP_PORT_COLUMNS = (
    'http_port', 'https_port',
    'http_port2', 'https_port2',
    'http_port3', 'https_port3',
    'http_port4', 'https_port4',
    'http_port5', 'https_port5',
    'http_port6', 'https_port6',
)
# "http_port, https_port, ..." for use in INSERT column lists.
APP_PORT_COLUMNS_SQL = ', '.join(APP_PORT_COLUMNS)
# "%s, %s, ..." (12 placeholders) for use in INSERT VALUES.
APP_PORT_PLACEHOLDERS_SQL = ', '.join(['%s'] * len(APP_PORT_COLUMNS))
# "http_port = %s, https_port = %s, ..." for use in UPDATE SET clauses.
APP_PORT_UPDATE_SQL = ', '.join(f'{col} = %s' for col in APP_PORT_COLUMNS)

class PostgreSQLManager:
    """Thread-safe PostgreSQL database manager with connection pooling"""
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self._pool = None
            self._config = None
            self._initialized = True

    def _ensure_initialized(self):
        """Ensure the connection pool is initialized"""
        if self._pool is None:
            self._config = get_database_config()
            self._initialize_pool()

    def _is_connection_valid(self, conn):
        """Check if a connection is still valid"""
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT 1')
            return True
        except:
            return False

    def _initialize_pool(self):
        """Initialize PostgreSQL connection pool"""
        try:
            self._pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=self._config['min_connections'],
                maxconn=self._config['max_connections'],
                host=self._config['host'],
                port=self._config['port'],
                database=self._config['database'],
                user=self._config['user'],
                password=self._config['password'],
                sslmode=self._config.get('sslmode', 'prefer'),
                connect_timeout=self._config.get('connect_timeout', 10)
            )
            print(f"PostgreSQL connection pool initialized: {self._config['min_connections']}-{self._config['max_connections']} connections")
        except Exception as e:
            print(f"Failed to initialize PostgreSQL connection pool: {e}")
            # Try to re-initialize once more with default settings
            try:
                self._pool = psycopg2.pool.ThreadedConnectionPool(
                    minconn=1,
                    maxconn=10,
                    host=self._config['host'],
                    port=self._config['port'],
                    database=self._config['database'],
                    user=self._config['user'],
                    password=self._config['password'],
                    sslmode=self._config.get('sslmode', 'prefer'),
                    connect_timeout=10
                )
                print(f"PostgreSQL connection pool initialized with default settings: 1-10 connections")
            except Exception as e2:
                print(f"Failed to initialize PostgreSQL connection pool even with defaults: {e2}")
                raise

    @contextmanager
    def get_db_connection(self):
        """Context manager for database connections"""
        self._ensure_initialized()
        conn = None
        try:
            conn = self._pool.getconn()
            conn.autocommit = False
            yield conn
        except Exception as e:
            if conn:
                try:
                    conn.rollback()
                except:
                    pass
                # Return connection to pool even if there was an error
                self._pool.putconn(conn, close=True)
                conn = None
            raise
        finally:
            if conn:
                try:
                    self._pool.putconn(conn)
                except:
                    # If we can't put the connection back, it's likely already closed
                    pass

    def execute_query(self, query, params=None, fetch_one=False, fetch_all=False):
        """Execute a query with automatic retry on transient errors"""
        max_retries = 3
        retry_delay = 0.1

        # Convert SQLite query parameters to PostgreSQL format
        converted_query = convert_sqlite_to_postgres_query(query)

        for attempt in range(max_retries):
            conn = None
            try:
                with self.get_db_connection() as conn:
                    # Validate connection if it's not None
                    if conn and not self._is_connection_valid(conn):
                        # Connection is invalid, force a new one by breaking the context
                        raise psycopg2.OperationalError("Connection is invalid")

                    with conn.cursor() as cursor:
                        if params:
                            cursor.execute(converted_query, params)
                        else:
                            cursor.execute(converted_query)

                        # Only fetch if query returns results
                        if fetch_one:
                            if cursor.description:
                                result = cursor.fetchone()
                            else:
                                result = None
                        elif fetch_all:
                            if cursor.description:
                                result = cursor.fetchall()
                            else:
                                result = []
                        else:
                            # For non-fetch operations, we still need to ensure the query executed properly
                            result = cursor.rowcount

                        conn.commit()

                        # Queue replication for INSERT/UPDATE on replicated tables
                        self._queue_replication(converted_query, params)

                        return result
            except psycopg2.ProgrammingError as e:
                # Handle "no results to fetch" error gracefully
                if "no results to fetch" in str(e) or "PGRES_TUPLES_OK" in str(e):
                    # This error can occur when trying to fetch results from a non-SELECT query
                    # In such cases, we should return appropriate default values
                    if conn:
                        conn.commit()
                    return None if (fetch_one or fetch_all) else 0
                raise
            except (psycopg2.OperationalError, psycopg2.InterfaceError, psycopg2.DatabaseError) as e:
                # Handle database connection issues and other database errors
                if "PGRES_TUPLES_OK" in str(e) and not (fetch_one or fetch_all):
                    # Special case for the specific error mentioned in the issue
                    # When we're not fetching results, just return 0 to indicate success
                    if conn:
                        conn.commit()
                    return 0
                # Log the error for debugging purposes
                print(f"Database error on attempt {attempt}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay * (2 ** attempt))  # Exponential backoff
                    continue
                raise
            except Exception as e:
                # Catch any other unexpected exceptions
                print(f"Unexpected error in execute_query: {e}")
                if conn:
                    try:
                        conn.rollback()
                    except:
                        pass
                raise

    def _queue_replication(self, query, params):
        """Queue replication event for INSERT/UPDATE on replicated tables"""
        try:
            query_upper = query.upper().strip()
            replicated_tables = {'USERS', 'SERVERS', 'APPLICATIONS', 'USER_APPLICATIONS', 'BILLING_ACTIVITIES', 'AUTH_TOKENS'}

            # Detect operation and table
            operation = None
            table = None

            if query_upper.startswith('INSERT INTO'):
                operation = 'INSERT'
                # Extract table name
                parts = query_upper.split()
                if len(parts) >= 3:
                    table = parts[2].strip('(').split('(')[0]
            elif query_upper.startswith('UPDATE'):
                operation = 'UPDATE'
                # Extract table name
                parts = query_upper.split()
                if len(parts) >= 2:
                    table = parts[1].split()[0]

            if operation and table and table in replicated_tables:
                from src.replication_manager import queue_replication_event
                # Build data dict from params
                data = {}
                if params:
                    if isinstance(params, (list, tuple)):
                        data = {'params': params}
                    elif isinstance(params, dict):
                        data = params
                queue_replication_event(table.lower(), operation, data)
        except Exception:
            pass  # Silently ignore replication errors

    def execute_many(self, query, params_list):
        """Execute multiple queries in a single transaction"""
        max_retries = 3
        retry_delay = 0.1

        # Convert SQLite query parameters to PostgreSQL format
        converted_query = convert_sqlite_to_postgres_query(query)

        for attempt in range(max_retries):
            try:
                with self.get_db_connection() as conn:
                    with conn.cursor() as cursor:
                        cursor.executemany(converted_query, params_list)
                        conn.commit()
                        return cursor.rowcount
            except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
                if attempt < max_retries - 1:
                    time.sleep(retry_delay * (2 ** attempt))
                    continue
                raise

# Global database manager instance
db_manager = PostgreSQLManager()

def load_default_apps():
    """Load default applications from conf/default_apps config file.

    File format: name | description | git_url | git_repo_size | docker_build_duration | docker_start_duration | docker_stop_duration | docker_ps_duration
    Lines starting with # are comments, empty lines are ignored.
    """
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'conf', 'default_apps')
    default_apps = []

    if not os.path.exists(config_path):
        print(f"Warning: default_apps config file not found at {config_path}")
        return default_apps

    try:
        with open(config_path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                parts = [p.strip() for p in line.split('|')]
                if len(parts) != 8:
                    print(f"Warning: skipping malformed line in default_apps: {line}")
                    continue
                name, description, git_url = parts[0], parts[1], parts[2]
                git_repo_size = int(parts[3])
                docker_build_duration = int(parts[4])
                docker_start_duration = int(parts[5])
                docker_stop_duration = int(parts[6])
                docker_ps_duration = int(parts[7])
                default_apps.append((name, description, git_url, git_repo_size, docker_build_duration, docker_start_duration, docker_stop_duration, docker_ps_duration))
    except Exception as e:
        print(f"Warning: Could not load default_apps config: {e}")

    return default_apps

def init_db():
    """Initialize database with required tables"""
    with db_manager.get_db_connection() as conn:
        with conn.cursor() as cursor:

            # Check if tables exist
            cursor.execute("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'users'
            """)

            if not cursor.fetchone():
                # Read and execute schema
                schema_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scripts', 'postgresql_schema.sql')
                with open(schema_path, 'r') as f:
                    schema_sql = f.read()
                cursor.execute(schema_sql)
                print("Database schema created successfully")

            # Apply 2FA and password reset migration
            try:
                migration_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'migration', 'add_password_reset_and_2fa.sql')
                if os.path.exists(migration_path):
                    with open(migration_path, 'r') as f:
                        migration_sql = f.read()
                    cursor.execute(migration_sql)
                    conn.commit()
            except Exception as e:
                # Migration may already be applied, ignore errors
                conn.rollback()
                print(f"[INFO] 2FA migration check: {e}")

            # Apply serverless jobs migration
            try:
                migration_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'migration', 'add_serverless_jobs.sql')
                if os.path.exists(migration_path):
                    with open(migration_path, 'r') as f:
                        migration_sql = f.read()
                    cursor.execute(migration_sql)
                    conn.commit()
            except Exception as e:
                # Migration may already be applied, ignore errors
                conn.rollback()
                print(f"[INFO] Serverless jobs migration check: {e}")

            # Apply MIG shared GPU migration
            try:
                migration_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'migration', 'add_mig_gpu.sql')
                if os.path.exists(migration_path):
                    with open(migration_path, 'r') as f:
                        migration_sql = f.read()
                    cursor.execute(migration_sql)
                    conn.commit()
            except Exception as e:
                # Migration may already be applied, ignore errors
                conn.rollback()
                print(f"[INFO] MIG GPU migration check: {e}")

            # Apply target_link migration for serverless jobs
            try:
                migration_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'migration', 'add_target_link_to_serverless_jobs.sql')
                if os.path.exists(migration_path):
                    with open(migration_path, 'r') as f:
                        migration_sql = f.read()
                    cursor.execute(migration_sql)
                    conn.commit()
            except Exception as e:
                # Migration may already be applied, ignore errors
                conn.rollback()
                print(f"[INFO] Target link migration check: {e}")

            # Make application FK constraints deferrable (required for ID updates)
            try:
                migration_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'migration', 'make_application_fkeys_deferrable.sql')
                if os.path.exists(migration_path):
                    with open(migration_path, 'r') as f:
                        migration_sql = f.read()
                    cursor.execute(migration_sql)
                    conn.commit()
            except Exception as e:
                # Migration may already be applied, ignore errors
                conn.rollback()
                print(f"[INFO] Deferrable FK migration check: {e}")

            # Apply deploy templates catalog and sandbox labeling migration
            try:
                migration_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'migration', 'add_deploy_templates.sql')
                if os.path.exists(migration_path):
                    with open(migration_path, 'r') as f:
                        migration_sql = f.read()
                    cursor.execute(migration_sql)
                    conn.commit()
            except Exception as e:
                # Migration may already be applied, ignore errors
                conn.rollback()
                print(f"[INFO] Deploy templates migration check: {e}")

            # Apply extended ports migration for user_applications (ports 3-6)
            try:
                migration_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'migration', 'add_extended_ports_to_user_applications.sql')
                if os.path.exists(migration_path):
                    with open(migration_path, 'r') as f:
                        migration_sql = f.read()
                    cursor.execute(migration_sql)
                    conn.commit()
            except Exception as e:
                # Migration may already be applied, ignore errors
                conn.rollback()
                print(f"[INFO] Extended ports migration check: {e}")

            # Ensure agentic-ai-plateform-serverless-brik application exists and is assigned to all users
            try:
                cursor.execute("SELECT id FROM applications WHERE name = %s", ('opcp-serverless-brik',))
                serverless_app = cursor.fetchone()
                if not serverless_app:
                    # Insert the application
                    cursor.execute('''
                        INSERT INTO applications (name, description, git_url, git_repo_size, docker_build_duration, docker_start_duration, docker_stop_duration, docker_ps_duration)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                    ''', ('opcp-serverless-brik', 'agentic-ai-plateform Serverless Docker Execution', 'https://github.com/Sam9682/opcp-serverless-brik.git', 10, 30, 30, 10, 1))
                    serverless_app_id = cursor.fetchone()[0]
                    # Insert default cost
                    cursor.execute('INSERT INTO application_costs (application_id, cost_per_day) VALUES (%s, %s)', (serverless_app_id, 1.0))
                else:
                    serverless_app_id = serverless_app[0]

                # Assign to all users that don't have it yet
                cursor.execute('SELECT id FROM users')
                all_users = cursor.fetchall()
                for user_row in all_users:
                    uid = user_row[0]
                    cursor.execute('SELECT id FROM user_applications WHERE user_id = %s AND application_id = %s', (uid, serverless_app_id))
                    if not cursor.fetchone():
                        app_ports = calculate_app_ports(uid, serverless_app_id)
                        url = f'https://www.{DOMAIN}:{app_ports[1]}'
                        cursor.execute(f'''
                            INSERT INTO user_applications (user_id, application_id, url, {APP_PORT_COLUMNS_SQL})
                            VALUES (%s, %s, %s, {APP_PORT_PLACEHOLDERS_SQL})
                            ON CONFLICT (user_id, application_id) DO NOTHING
                        ''', (uid, serverless_app_id, url, *app_ports))

                # Ensure a deployment record exists for admin so the endpoint shows up
                cursor.execute("SELECT id FROM users WHERE username = %s", ('admin',))
                admin_row = cursor.fetchone()
                if admin_row:
                    admin_id = admin_row[0]
                    cursor.execute("SELECT id FROM deployments WHERE user_id = %s AND application_name = %s", (admin_id, 'opcp-serverless-brik'))
                    if not cursor.fetchone():
                        cursor.execute("SELECT id FROM servers LIMIT 1")
                        server_row = cursor.fetchone()
                        server_id = server_row[0] if server_row else None
                        swautomorph_url = f"https://{DOMAIN}/admin/opcp-serverless-brik"
                        cursor.execute('''
                            INSERT INTO deployments (user_id, application_id, application_name, status, server_id, swautomorph_url)
                            VALUES (%s, %s, %s, %s, %s, %s)
                        ''', (admin_id, serverless_app_id, 'opcp-serverless-brik', 'RUNNING', server_id, swautomorph_url))

                conn.commit()
                print("[INFO] opcp-serverless-brik application ensured for all users")
            except Exception as e:
                conn.rollback()
                print(f"[INFO] opcp-serverless-brik setup check: {e}")

            # Insert default applications from conf/default_apps.
            # Use ON CONFLICT so this is idempotent and independent of whether
            # the applications table is already partially populated (e.g. the
            # opcp-serverless-brik record inserted above). Previously this was
            # guarded by "COUNT(*) == 0", but since the serverless-brik block
            # always inserts a row first, the count was never zero and the
            # default apps were never loaded.
            # Seed the default applications AND their default costs in their OWN
            # committed transaction, mirroring the opcp-serverless-brik block
            # above. Previously this insert shared a single transaction with the
            # long downstream seeding block (admin/demo creation, user_applications,
            # payment modes, configuration) that only commits at the END of
            # init_db(). Because get_db_connection() rolls back on ANY exception,
            # a failure anywhere in that later block discarded these uncommitted
            # default apps while the already-committed serverless-brik row
            # survived -> only ONE application ended up in the table. Committing
            # here makes the 11 default apps durable before the downstream block
            # runs. ON CONFLICT (name) DO NOTHING keeps this idempotent.
            try:
                default_apps = load_default_apps()
                if default_apps:
                    cursor.executemany('''
                        INSERT INTO applications (name, description, git_url, git_repo_size, docker_build_duration, docker_start_duration, docker_stop_duration, docker_ps_duration)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (name) DO NOTHING
                    ''', default_apps)

                # Insert default costs for any application that doesn't have one
                # yet, in the SAME committed transaction as the apps so a later
                # failure can never leave a seeded app without a cost.
                cursor.execute('''
                    SELECT a.id FROM applications a
                    LEFT JOIN application_costs c ON c.application_id = a.id
                    WHERE c.id IS NULL
                ''')
                app_ids = cursor.fetchall()
                for app_id in app_ids:
                    cursor.execute('INSERT INTO application_costs (application_id, cost_per_day) VALUES (%s, %s)', (app_id[0], 1.0))

                conn.commit()
                print("[INFO] Default applications and costs ensured")
            except Exception as e:
                conn.rollback()
                print(f"[INFO] Default applications seeding check: {e}")

            # Insert current server if none exists
            cursor.execute('SELECT COUNT(*) FROM servers')
            if cursor.fetchone()[0] == 0:
                import socket
                try:
                    # Get current server IP
                    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    s.connect(("8.8.8.8", 80))
                    current_ip = s.getsockname()[0]
                    s.close()
                except:
                    current_ip = "127.0.0.1"

                cursor.execute('''
                    INSERT INTO servers (server_ip, server_name, server_capacity_user_max, server_capacity_appli_max, server_status, server_type)
                    VALUES (%s, %s, %s, %s, %s, %s)
                ''', (current_ip, 'main-server', 10, 50, 'STAND_BY', 'STAND_ALONE'))

            # Create default admin user if none exists
            cursor.execute('SELECT COUNT(*) FROM users WHERE username = %s', ('admin',))
            if cursor.fetchone()[0] == 0:
                admin_password_hash = generate_password_hash('password')
                cursor.execute('''
                    INSERT INTO users (username, email, password_hash, first_name, last_name, suspended)
                    VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
                ''', ('admin', f'admin@{DOMAIN}', admin_password_hash, 'System', 'Administrator', False))

                demo_password_hash = generate_password_hash('password')
                cursor.execute('''
                    INSERT INTO users (username, email, password_hash, first_name, last_name, suspended)
                    VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
                ''', ('demo', f'demo@{DOMAIN}', demo_password_hash, 'System', 'Demo', False))

                # Get admin user ID and assign all applications with URLs
                admin_id = cursor.fetchone()[0]
                cursor.execute('SELECT id, name FROM applications')
                apps = cursor.fetchall()
                for app in apps:
                    app_id, app_name = app[0], app[1]
                    # Calculate URL using the same logic as deployControlPlan.sh
                    app_ports = calculate_app_ports(admin_id, app_id)

                    url = f'https://www.{DOMAIN}:{app_ports[1]}'
                    cursor.execute(f'''
                        INSERT INTO user_applications (user_id, application_id, url, {APP_PORT_COLUMNS_SQL})
                        VALUES (%s, %s, %s, {APP_PORT_PLACEHOLDERS_SQL})
                    ''', (admin_id, app_id, url, *app_ports))

                # Ensure costs exist for all applications
                cursor.execute('SELECT id FROM applications')
                app_ids = cursor.fetchall()
                for app_id in app_ids:
                    cursor.execute('SELECT COUNT(*) FROM application_costs WHERE application_id = %s', (app_id[0],))
                    if cursor.fetchone()[0] == 0:
                        cursor.execute('INSERT INTO application_costs (application_id, cost_per_day) VALUES (%s, %s)', (app_id[0], 1.0))

                # Create default payment mode for admin
                cursor.execute('SELECT COUNT(*) FROM payment_modes WHERE user_id = %s', (admin_id,))
                if cursor.fetchone()[0] == 0:
                    cursor.execute('''
                        INSERT INTO payment_modes (user_id, payment_type, is_default)
                        VALUES (%s, %s, %s)
                    ''', (admin_id, 'bank_transfer', True))

            # Update existing user_applications records with port information if missing
            cursor.execute('SELECT id, user_id, application_id FROM user_applications WHERE http_port IS NULL OR https_port IS NULL')
            records_to_update = cursor.fetchall()
            for record in records_to_update:
                record_id, user_id, app_id = record
                app_ports = calculate_app_ports(user_id, app_id)
                cursor.execute(f'''
                    UPDATE user_applications SET {APP_PORT_UPDATE_SQL}
                    WHERE id = %s
                ''', (*app_ports, record_id))

            # Insert default configuration parameters if none exist
            cursor.execute('SELECT COUNT(*) FROM configuration')
            if cursor.fetchone()[0] == 0:
                default_config = [
                    (None, 'agentic_engine', AI_ENGINE),
                    (None, 'agentic_command', ''),
                    (None, 'runtime_type', 'runc')
                ]
                cursor.executemany('INSERT INTO configuration (parent, key, value) VALUES (%s, %s, %s)', default_config)

            conn.commit()

def assign_default_apps_to_user(user_id):
    """Assign default applications to a new user"""
    with db_manager.get_db_connection() as conn:
        with conn.cursor() as cursor:

            # Get all applications
            cursor.execute('SELECT id, name FROM applications')
            apps = cursor.fetchall()

            # Assign all applications to the user with calculated URLs
            for app in apps:
                app_id, app_name = app[0], app[1]
                # Calculate URL using the same logic as deployControlPlan.sh
                app_ports = calculate_app_ports(user_id, app_id)

                # Compose URL
                url = f'https://www.{DOMAIN}:{app_ports[1]}'
                cursor.execute(f'''
                    INSERT INTO user_applications (user_id, application_id, url, {APP_PORT_COLUMNS_SQL})
                    VALUES (%s, %s, %s, {APP_PORT_PLACEHOLDERS_SQL})
                    ON CONFLICT (user_id, application_id) DO NOTHING
                ''', (user_id, app_id, url, *app_ports))

            conn.commit()

def assign_app_to_all_users(app_id, app_name):
    """Assign a new application to all existing users"""
    with db_manager.get_db_connection() as conn:
        with conn.cursor() as cursor:

            # Get all user IDs
            cursor.execute('SELECT id FROM users')
            user_ids = cursor.fetchall()

            # Assign application to all users with calculated URLs
            for user_id in user_ids:
                uid = user_id[0]
                # Calculate URL using the same logic as deployControlPlan.sh
                app_ports = calculate_app_ports(uid, app_id)

                url = f'https://www.{DOMAIN}:{app_ports[1]}'
                cursor.execute(f'''
                    INSERT INTO user_applications (user_id, application_id, url, {APP_PORT_COLUMNS_SQL})
                    VALUES (%s, %s, %s, {APP_PORT_PLACEHOLDERS_SQL})
                    ON CONFLICT (user_id, application_id) DO NOTHING
                ''', (uid, app_id, url, *app_ports))

            conn.commit()

def get_config_value(key, parent=None, default_value=None):
    """Get configuration value from database"""
    result = db_manager.execute_query(
        'SELECT value FROM configuration WHERE key = %s AND (parent = %s OR (parent IS NULL AND %s IS NULL))',
        (key, parent, parent), fetch_one=True
    )
    return result[0] if result else default_value


def _sanitize_runtime_type(value):
    """Validate a container runtime type against the allowed whitelist.

    This function is intentionally free of Flask/DB dependencies so that the
    serverless worker (a separate process) can import and reuse it.

    Args:
        value: The raw runtime type value (e.g. from configuration).

    Returns:
        str: ``value`` if it is an allowed runtime type, otherwise
        ``'runc'`` (the safe default). A warning is logged on fallback.
    """
    if value in ALLOWED_RUNTIME_TYPES:
        return value
    if value not in (None, '', DEFAULT_RUNTIME_TYPE):
        logger.warning(
            "Invalid runtime_type %r; falling back to %r. Allowed values: %s",
            value, DEFAULT_RUNTIME_TYPE, sorted(ALLOWED_RUNTIME_TYPES),
        )
    return DEFAULT_RUNTIME_TYPE


def get_runtime_type():
    """Resolve the configured container runtime type, validated.

    Reads the top-level ``runtime_type`` configuration value and sanitizes it
    against the allowed whitelist. Returns ``'runc'`` when unset or invalid.

    Returns:
        str: Either ``'runc'`` or ``'kata'``.
    """
    value = get_config_value('runtime_type', None, DEFAULT_RUNTIME_TYPE)
    return _sanitize_runtime_type(value)
