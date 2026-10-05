# 🗄️ Database Architecture & Improvements / Architecture et Améliorations de Base de Données

## English

<div class="center">
🚀 **PostgreSQL Database Architecture for AI-SwAutoMorph** 📊
</div>

### 📋 Table of Contents
- [🌟 Overview](#overview)
- [🐘 PostgreSQL Migration](#postgresql-migration)
- [🏗️ Database Schema](#database-schema)
- [🔧 Connection Pooling](#connection-pooling)
- [📊 Performance Optimizations](#performance-optimizations)
- [💰 Billing System](#billing-system)
- [🔍 Health Monitoring](#health-monitoring)
- [🔄 Migration & Backup](#migration--backup)
- [🛡️ Security Enhancements](#security-enhancements)

### 🌟 Overview

AI-SwAutoMorph has migrated from SQLite to **PostgreSQL** for enterprise-grade performance, scalability, and reliability. The system now features connection pooling, ACID transactions, advanced data types, and comprehensive monitoring capabilities.

#### 🎯 Key Improvements
- **🐘 PostgreSQL Database**: Enterprise-grade database with full ACID compliance
- **🏊 Connection Pooling**: ThreadedConnectionPool with configurable min/max connections (2-20)
- **⚡ Advanced Data Types**: INET for IP addresses, BIGSERIAL for auto-increment, TIMESTAMP WITH TIME ZONE
- **🔍 Optimized Indexes**: Performance-tuned indexes on frequently queried columns
- **🔄 Database Triggers**: Automatic updated_at timestamp management
- **📊 Enhanced Monitoring**: Real-time database statistics and health checks
- **💰 Billing Integration**: Comprehensive cost tracking with PostgreSQL precision
- **🖥️ Multi-Server Support**: Scalable server capacity management
- **🔐 Enhanced Security**: Parameterized queries, SSL support, and audit logging
- **🛠️ Migration Tools**: Automated SQLite to PostgreSQL migration script

### 🐘 PostgreSQL Migration

#### 🔄 Migration Process

The platform includes automated migration logic for seamlessly transitioning from SQLite to PostgreSQL. The migration code is integrated into the database manager and documented here for reference.

**Migration Options:**

1. **Via Database CLI** (Recommended):
```bash
# Using the sf_cli tool
python3 ./scripts/controller_cli.py migrate-to-postgres
```

2. **Via API** (Admin only):
```bash
curl -X POST https://www.swautomorph.com/api/database/migrate \
  -H "Cookie: session=your-session-cookie" \
  -H "Content-Type: application/json"
```

3. **Manual Migration** (Advanced):
The migration logic documented below can be adapted for custom migration scenarios or integrated into deployment scripts.

**Note:** The migration code shown in this document serves as a reference implementation. The actual migration is performed by the database manager with proper error handling, transaction management, and rollback capabilities.

#### 📊 Migration Features
- **🔄 Data Preservation**: Complete data migration with type conversion
- **🔧 Schema Mapping**: Automatic column mapping (e.g., SERVER_IP → server_ip)
- **⚡ Sequence Reset**: Automatic sequence adjustment for auto-increment fields
- **✅ Data Validation**: Boolean and timestamp conversion validation
- **🔒 Transaction Safety**: Full transaction rollback on migration errors

### 🏗️ Database Schema

#### 📋 Core Tables

##### 👥 Users Table
```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    first_name TEXT,
    last_name TEXT,
    suspended INTEGER DEFAULT 1,  -- 0 = active, 1 = suspended
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for performance
CREATE INDEX idx_users_username ON users(username);
CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_suspended ON users(suspended);
```

##### 📱 Applications Table
```sql
CREATE TABLE applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    description TEXT,
    git_url TEXT,
    git_remote_url TEXT,
    git_local_url TEXT,
    git_repo_size INTEGER DEFAULT 50,
    docker_build_duration INTEGER,
    docker_start_duration INTEGER,
    docker_stop_duration INTEGER,
    docker_ps_duration INTEGER,
    docker_compose_ports TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for performance
CREATE INDEX idx_applications_name ON applications(name);
CREATE INDEX idx_applications_git_url ON applications(git_url);
```

##### 🔗 User Applications Table
```sql
CREATE TABLE user_applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    application_id INTEGER NOT NULL,
    url TEXT NOT NULL,
    http_port INTEGER,
    https_port INTEGER,
    http_port2 INTEGER,
    https_port2 INTEGER,
    http_port3 INTEGER,
    https_port3 INTEGER,
    http_port4 INTEGER,
    https_port4 INTEGER,
    http_port5 INTEGER,
    https_port5 INTEGER,
    http_port6 INTEGER,
    https_port6 INTEGER,
    others_port INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    FOREIGN KEY (application_id) REFERENCES applications (id) ON DELETE CASCADE,
    UNIQUE(user_id, application_id)
);

-- Indexes for performance
CREATE INDEX idx_user_applications_user_id ON user_applications(user_id);
CREATE INDEX idx_user_applications_app_id ON user_applications(application_id);
CREATE INDEX idx_user_applications_ports ON user_applications(http_port, https_port);
```

##### 🚀 Deployments Table
```sql
CREATE TABLE deployments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    application_name TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    deployment_path TEXT,
    git_url TEXT,
    server_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    FOREIGN KEY (server_id) REFERENCES servers (id) ON DELETE SET NULL
);

-- Indexes for performance
CREATE INDEX idx_deployments_user_id ON deployments(user_id);
CREATE INDEX idx_deployments_app_name ON deployments(application_name);
CREATE INDEX idx_deployments_server_id ON deployments(server_id);
CREATE INDEX idx_deployments_status ON deployments(status);
CREATE INDEX idx_deployments_updated_at ON deployments(updated_at);
```

##### 🖥️ Servers Table
```sql
CREATE TABLE servers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    SERVER_IP TEXT UNIQUE NOT NULL,
    SERVER_NAME TEXT NOT NULL,
    SERVER_CAPACITY_USER_MAX INTEGER NOT NULL,
    SERVER_CAPACITY_APPLI_MAX INTEGER NOT NULL,
    SERVER_STATUS TEXT DEFAULT 'STAND_BY',  -- STAND_BY, ACTIVE, MAINTENANCE
    SERVER_TYPE TEXT NOT NULL,  -- primary, worker, backup
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for performance
CREATE INDEX idx_servers_status ON servers(SERVER_STATUS);
CREATE INDEX idx_servers_ip ON servers(SERVER_IP);
CREATE INDEX idx_servers_type ON servers(SERVER_TYPE);
```

#### 💰 Billing & Cost Tracking Tables

##### 💳 Application Costs Table
```sql
CREATE TABLE application_costs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER NOT NULL,
    cost_per_day REAL DEFAULT 1.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (application_id) REFERENCES applications (id) ON DELETE CASCADE
);

-- Indexes for performance
CREATE INDEX idx_application_costs_app_id ON application_costs(application_id);
```

##### 📊 Billing Activities Table
```sql
CREATE TABLE billing_activities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    application_id INTEGER NOT NULL,
    action TEXT NOT NULL,  -- START, STOP, RESTART, etc.
    started_at TIMESTAMP,
    stopped_at TIMESTAMP,
    duration_seconds INTEGER,
    cost_amount REAL,
    server_id INTEGER,
    resource_usage TEXT,  -- JSON field for resource metrics
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    FOREIGN KEY (application_id) REFERENCES applications (id) ON DELETE CASCADE,
    FOREIGN KEY (server_id) REFERENCES servers (id) ON DELETE SET NULL
);

-- Indexes for performance
CREATE INDEX idx_billing_activities_user_id ON billing_activities(user_id);
CREATE INDEX idx_billing_activities_app_id ON billing_activities(application_id);
CREATE INDEX idx_billing_activities_action ON billing_activities(action);
CREATE INDEX idx_billing_activities_created_at ON billing_activities(created_at);
CREATE INDEX idx_billing_activities_started_at ON billing_activities(started_at);
CREATE INDEX idx_billing_activities_stopped_at ON billing_activities(stopped_at);
```

##### 💳 Payment Modes Table
```sql
CREATE TABLE payment_modes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    payment_type TEXT NOT NULL,  -- bank_transfer, paypal, credit_card
    bank_account TEXT,
    paypal_email TEXT,
    card_last_four TEXT,
    card_type TEXT,  -- visa, mastercard, amex
    is_default INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);

-- Indexes for performance
CREATE INDEX idx_payment_modes_user_id ON payment_modes(user_id);
CREATE INDEX idx_payment_modes_default ON payment_modes(is_default);
```

##### 🧾 Invoicing Table
```sql
CREATE TABLE invoicing (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    invoice_month TEXT NOT NULL,  -- YYYY-MM format
    total_amount REAL NOT NULL,
    status TEXT DEFAULT 'unpaid',  -- unpaid, paid, overdue, cancelled
    payment_date TIMESTAMP,
    payment_mode_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    FOREIGN KEY (payment_mode_id) REFERENCES payment_modes (id) ON DELETE SET NULL,
    UNIQUE(user_id, invoice_month)
);

-- Indexes for performance
CREATE INDEX idx_invoicing_user_id ON invoicing(user_id);
CREATE INDEX idx_invoicing_month ON invoicing(invoice_month);
CREATE INDEX idx_invoicing_status ON invoicing(status);
```

#### 🔐 Authentication & Logging Tables

##### 🔑 Auth Tokens Table
```sql
CREATE TABLE auth_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    token_hash TEXT UNIQUE NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);

-- Indexes for performance
CREATE INDEX idx_auth_tokens_user_id ON auth_tokens(user_id);
CREATE INDEX idx_auth_tokens_hash ON auth_tokens(token_hash);
CREATE INDEX idx_auth_tokens_expires ON auth_tokens(expires_at);
```

##### 📝 Users Logs Table
```sql
CREATE TABLE users_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    username TEXT NOT NULL,
    action TEXT NOT NULL,  -- login, logout, register, etc.
    ip_address TEXT,
    user_agent TEXT,
    datetime TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);

-- Indexes for performance
CREATE INDEX idx_users_logs_user_id ON users_logs(user_id);
CREATE INDEX idx_users_logs_action ON users_logs(action);
CREATE INDEX idx_users_logs_datetime ON users_logs(datetime);
```

### 🔧 Connection Pooling

#### 🏊 PostgreSQL Connection Pool Manager
```python
class PostgreSQLManager:
    """Thread-safe PostgreSQL database manager with connection pooling"""
    _instance = None
    _lock = threading.Lock()
    
    def __init__(self):
        if not self._initialized:
            self._pool = None
            self._config = get_database_config()
            self._initialize_pool()
            self._initialized = True
    
    def _initialize_pool(self):
        """Initialize PostgreSQL connection pool"""
        try:
            self._pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=self._config['min_connections'],  # Default: 2
                maxconn=self._config['max_connections'],  # Default: 20
                host=self._config['host'],
                port=self._config['port'],
                database=self._config['database'],
                user=self._config['user'],
                password=self._config['password'],
                sslmode=self._config.get('sslmode', 'prefer'),
                connect_timeout=self._config.get('connect_timeout', 10)
            )
        except Exception as e:
            print(f"Failed to initialize PostgreSQL connection pool: {e}")
            raise
```

#### ⚡ Enhanced Connection Management
```python
@contextmanager
def get_db_connection(self):
    """Context manager for database connections with automatic cleanup"""
    conn = None
    try:
        conn = self._pool.getconn()
        conn.autocommit = False
        yield conn
    except Exception as e:
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            self._pool.putconn(conn)

def execute_query(self, query, params=None, fetch_one=False, fetch_all=False):
    """Execute query with automatic retry on transient errors"""
    max_retries = 3
    retry_delay = 0.1
    
    for attempt in range(max_retries):
        try:
            with self.get_db_connection() as conn:
                with conn.cursor() as cursor:
                    if params:
                        cursor.execute(query, params)
                    else:
                        cursor.execute(query)
                    
                    if fetch_one:
                        result = cursor.fetchone()
                    elif fetch_all:
                        result = cursor.fetchall()
                    else:
                        result = cursor.rowcount
                    
                    conn.commit()
                    return result
        except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
            if attempt < max_retries - 1:
                time.sleep(retry_delay * (2 ** attempt))  # Exponential backoff
                continue
            raise
```

### 📊 Performance Optimizations

#### ⚡ PostgreSQL Performance Features
```sql
-- Connection pooling configuration
POSTGRES_MIN_CONN=2
POSTGRES_MAX_CONN=20
POSTGRES_TIMEOUT=10

-- SSL and security settings
POSTGRES_SSLMODE=prefer
POSTGRES_CONNECT_TIMEOUT=10
```

#### 🔍 Comprehensive Database Indexes
```sql
-- User authentication and lookup indexes
CREATE INDEX idx_users_username ON users(username);
CREATE INDEX idx_users_email ON users(email);

-- Application management indexes
CREATE INDEX idx_user_applications_user_id ON user_applications(user_id);
CREATE INDEX idx_user_applications_application_id ON user_applications(application_id);

-- Deployment tracking indexes
CREATE INDEX idx_deployments_user_id ON deployments(user_id);
CREATE INDEX idx_deployments_server_id ON deployments(server_id);
CREATE INDEX idx_deployments_status ON deployments(status);

-- Billing and cost tracking indexes
CREATE INDEX idx_billing_activities_user_id ON billing_activities(user_id);
CREATE INDEX idx_billing_activities_application_id ON billing_activities(application_id);
CREATE INDEX idx_billing_activities_created_at ON billing_activities(created_at);

-- Authentication and security indexes
CREATE INDEX idx_auth_tokens_user_id ON auth_tokens(user_id);
CREATE INDEX idx_auth_tokens_expires_at ON auth_tokens(expires_at);

-- Audit and logging indexes
CREATE INDEX idx_users_logs_user_id ON users_logs(user_id);
CREATE INDEX idx_users_logs_datetime ON users_logs(datetime);
```

#### 🛠️ Database Triggers
```sql
-- Automatic updated_at timestamp trigger
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_deployments_updated_at BEFORE UPDATE ON deployments
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_application_costs_updated_at BEFORE UPDATE ON application_costs
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
```

### 💰 Billing System

#### 📊 Enhanced Cost Calculation Logic
```python
def calculate_app_ports(user_id, app_id):
    """Calculate 12 ports (6 HTTP + 6 HTTPS) using deployControlPlan.sh logic with validation"""
    # Load configuration from deploy.ini
    config = load_deploy_config()
    RANGE_START, RANGE_RESERVED, RANGE_PORTS_PER_APPLICATION = config
    
    # Validate inputs
    if not isinstance(user_id, int) or user_id < 1:
        raise ValueError("Invalid user_id")
    if not isinstance(app_id, int) or app_id < 1:
        raise ValueError("Invalid app_id")
    
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
    
    # Validate port ranges
    if HTTP_PORT > 65535 or HTTPS_PORT6 > 65535:
        raise ValueError("Port allocation exceeds valid range")
    
    return (HTTP_PORT, HTTPS_PORT, HTTP_PORT2, HTTPS_PORT2,
            HTTP_PORT3, HTTPS_PORT3, HTTP_PORT4, HTTPS_PORT4,
            HTTP_PORT5, HTTPS_PORT5, HTTP_PORT6, HTTPS_PORT6)
```

#### 💳 Enhanced Billing Activity Recording
```python
def record_billing_activity(user_id, application_name, action, server_id=None):
    """Record comprehensive billing activity for cost tracking"""
    logger = logging.getLogger('billing_activities')
    
    try:
        logger.info(f"Recording billing activity: user_id={user_id}, app={application_name}, action={action}")
        
        # Get application ID with validation
        app_result = db_manager.execute_query(
            'SELECT id FROM applications WHERE name = ?', 
            (application_name,), fetch_one=True
        )
        if not app_result:
            logger.error(f"Application not found: {application_name}")
            return False
        
        application_id = app_result[0]
        
        if action.upper() == 'START':
            # Record start activity with server information
            activity_id = db_manager.execute_query('''
                INSERT INTO billing_activities 
                (user_id, application_id, action, started_at, server_id)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?)
            ''', (user_id, application_id, action.upper(), server_id))
            
            logger.info(f"START activity recorded with ID: {activity_id}")
            return True
        
        elif action.upper() == 'STOP':
            # Find the most recent start activity
            start_activity = db_manager.execute_query('''
                SELECT id, started_at, server_id FROM billing_activities
                WHERE user_id = ? AND application_id = ? 
                AND action = 'START' AND stopped_at IS NULL
                ORDER BY created_at DESC LIMIT 1
            ''', (user_id, application_id), fetch_one=True)
            
            if start_activity:
                start_id, started_at, activity_server_id = start_activity
                
                # Calculate duration and cost
                start_time = datetime.fromisoformat(started_at)
                stop_time = datetime.now()
                duration_seconds = int((stop_time - start_time).total_seconds())
                
                # Get cost per day with fallback
                cost_result = db_manager.execute_query(
                    'SELECT cost_per_day FROM application_costs WHERE application_id = ?',
                    (application_id,), fetch_one=True
                )
                cost_per_day = cost_result[0] if cost_result else 1.0
                
                # Calculate prorated cost (cost per day / 86400 seconds * duration)
                cost_amount = (cost_per_day / 86400) * duration_seconds
                
                # Update the start activity with stop information
                db_manager.execute_query('''
                    UPDATE billing_activities 
                    SET stopped_at = CURRENT_TIMESTAMP,
                        duration_seconds = ?,
                        cost_amount = ?
                    WHERE id = ?
                ''', (duration_seconds, cost_amount, start_id))
                
                logger.info(f"STOP activity recorded: duration={duration_seconds}s, cost=${cost_amount:.4f}")
                return True
            else:
                logger.warning(f"No matching START activity found for STOP: {application_name}")
                return False
        
        else:
            logger.warning(f"Unknown billing action: {action}")
            return False
            
    except Exception as e:
        logger.error(f"Error recording billing activity: {str(e)}")
        return False
```

### 🔍 Health Monitoring

#### 📊 Comprehensive Database Health Check
```python
def check_database_health():
    """Comprehensive database health check with detailed metrics"""
    health_status = {
        'status': 'healthy',
        'checks': {},
        'metrics': {},
        'timestamp': datetime.now().isoformat(),
        'version': '2.0'
    }
    
    try:
        start_time = time.time()
        
        # Basic connectivity test
        db_manager.execute_query('SELECT 1', fetch_one=True)
        health_status['checks']['connectivity'] = 'OK'
        health_status['metrics']['connectivity_time_ms'] = round((time.time() - start_time) * 1000, 2)
        
        # Check WAL mode
        wal_mode = db_manager.execute_query('PRAGMA journal_mode', fetch_one=True)
        health_status['checks']['wal_mode'] = wal_mode[0] if wal_mode else 'UNKNOWN'
        
        # Check foreign keys
        fk_status = db_manager.execute_query('PRAGMA foreign_keys', fetch_one=True)
        health_status['checks']['foreign_keys'] = 'ON' if fk_status and fk_status[0] else 'OFF'
        
        # Database file information
        if os.path.exists(DB_PATH):
            db_size = os.path.getsize(DB_PATH)
            health_status['metrics']['database_size_mb'] = round(db_size / (1024 * 1024), 2)
            
            # WAL file size
            wal_path = DB_PATH + '-wal'
            if os.path.exists(wal_path):
                wal_size = os.path.getsize(wal_path)
                health_status['metrics']['wal_size_mb'] = round(wal_size / (1024 * 1024), 2)
        
        # Cache statistics
        cache_stats = db_manager.execute_query('PRAGMA cache_size', fetch_one=True)
        health_status['metrics']['cache_size'] = cache_stats[0] if cache_stats else 0
        
        # Page statistics
        page_count = db_manager.execute_query('PRAGMA page_count', fetch_one=True)
        page_size = db_manager.execute_query('PRAGMA page_size', fetch_one=True)
        if page_count and page_size:
            health_status['metrics']['total_pages'] = page_count[0]
            health_status['metrics']['page_size_bytes'] = page_size[0]
        
        # Table counts and health
        tables = [
            'users', 'applications', 'user_applications', 'deployments', 
            'servers', 'billing_activities', 'auth_tokens', 'users_logs',
            'application_costs', 'payment_modes', 'invoicing'
        ]
        
        for table in tables:
            try:
                count = db_manager.execute_query(f'SELECT COUNT(*) FROM {table}', fetch_one=True)
                health_status['checks'][f'{table}_count'] = count[0] if count else 0
                
                # Check for recent activity (last 24 hours)
                if table in ['billing_activities', 'users_logs', 'deployments']:
                    recent = db_manager.execute_query(
                        f'SELECT COUNT(*) FROM {table} WHERE created_at > datetime("now", "-1 day")',
                        fetch_one=True
                    )
                    health_status['metrics'][f'{table}_recent_24h'] = recent[0] if recent else 0
                    
            except Exception as e:
                health_status['checks'][f'{table}_error'] = str(e)
        
        # Performance metrics
        health_status['metrics']['total_check_time_ms'] = round((time.time() - start_time) * 1000, 2)
        
        # Determine overall health
        error_count = sum(1 for key in health_status['checks'] if 'error' in key)
        if error_count > 0:
            health_status['status'] = 'degraded'
        
        if health_status['checks'].get('connectivity') != 'OK':
            health_status['status'] = 'unhealthy'
            
    except Exception as e:
        health_status['status'] = 'unhealthy'
        health_status['error'] = str(e)
        health_status['checks']['connectivity'] = 'FAILED'
    
    return health_status
```

#### 📈 Enhanced Database Statistics
```python
def get_database_stats():
    """Get comprehensive database statistics with performance metrics"""
    stats = {
        'timestamp': datetime.now().isoformat(),
        'version': '2.0'
    }
    
    try:
        # User statistics with activity metrics
        stats['users'] = {
            'total': db_manager.execute_query('SELECT COUNT(*) FROM users', fetch_one=True)[0],
            'active': db_manager.execute_query('SELECT COUNT(*) FROM users WHERE suspended = 0', fetch_one=True)[0],
            'suspended': db_manager.execute_query('SELECT COUNT(*) FROM users WHERE suspended = 1', fetch_one=True)[0],
            'registered_today': db_manager.execute_query(
                'SELECT COUNT(*) FROM users WHERE DATE(created_at) = DATE("now")', fetch_one=True
            )[0],
            'active_last_7_days': db_manager.execute_query(
                'SELECT COUNT(DISTINCT user_id) FROM users_logs WHERE datetime > datetime("now", "-7 days")', 
                fetch_one=True
            )[0]
        }
        
        # Application statistics with usage metrics
        stats['applications'] = {
            'total': db_manager.execute_query('SELECT COUNT(*) FROM applications', fetch_one=True)[0],
            'with_git_url': db_manager.execute_query(
                'SELECT COUNT(*) FROM applications WHERE git_url IS NOT NULL', fetch_one=True
            )[0],
            'deployed_today': db_manager.execute_query(
                'SELECT COUNT(DISTINCT application_name) FROM deployments WHERE DATE(created_at) = DATE("now")', 
                fetch_one=True
            )[0]
        }
        
        # Deployment statistics with status breakdown
        deployment_stats = db_manager.execute_query('''
            SELECT status, COUNT(*) FROM deployments 
            GROUP BY status
        ''', fetch_all=True)
        
        stats['deployments'] = {
            'total': db_manager.execute_query('SELECT COUNT(*) FROM deployments', fetch_one=True)[0],
            'by_status': {status: count for status, count in deployment_stats},
            'today': db_manager.execute_query(
                'SELECT COUNT(*) FROM deployments WHERE DATE(created_at) = DATE("now")', fetch_one=True
            )[0],
            'last_7_days': db_manager.execute_query(
                'SELECT COUNT(*) FROM deployments WHERE created_at > datetime("now", "-7 days")', fetch_one=True
            )[0]
        }
        
        # Server statistics with capacity metrics
        server_stats = db_manager.execute_query('''
            SELECT SERVER_STATUS, COUNT(*), 
                   AVG(SERVER_CAPACITY_USER_MAX), AVG(SERVER_CAPACITY_APPLI_MAX)
            FROM servers GROUP BY SERVER_STATUS
        ''', fetch_all=True)
        
        stats['servers'] = {
            'total': db_manager.execute_query('SELECT COUNT(*) FROM servers', fetch_one=True)[0],
            'by_status': {status: {'count': count, 'avg_user_capacity': round(avg_user, 2), 'avg_app_capacity': round(avg_app, 2)} 
                         for status, count, avg_user, avg_app in server_stats}
        }
        
        # Billing statistics with revenue metrics
        billing_stats = db_manager.execute_query('''
            SELECT 
                COUNT(*) as total_activities,
                COALESCE(SUM(cost_amount), 0) as total_revenue,
                COUNT(CASE WHEN action = 'START' THEN 1 END) as start_actions,
                COUNT(CASE WHEN action = 'STOP' THEN 1 END) as stop_actions,
                AVG(duration_seconds) as avg_duration_seconds
            FROM billing_activities 
            WHERE cost_amount IS NOT NULL
        ''', fetch_one=True)
        
        if billing_stats:
            stats['billing'] = {
                'total_activities': billing_stats[0],
                'total_revenue': round(billing_stats[1], 2),
                'start_actions': billing_stats[2],
                'stop_actions': billing_stats[3],
                'avg_duration_minutes': round(billing_stats[4] / 60, 2) if billing_stats[4] else 0
            }
        
        # Monthly revenue trend
        monthly_revenue = db_manager.execute_query('''
            SELECT strftime('%Y-%m', created_at) as month, 
                   COALESCE(SUM(cost_amount), 0) as revenue
            FROM billing_activities 
            WHERE cost_amount IS NOT NULL 
            AND created_at > datetime('now', '-12 months')
            GROUP BY strftime('%Y-%m', created_at)
            ORDER BY month DESC
            LIMIT 12
        ''', fetch_all=True)
        
        stats['billing']['monthly_revenue'] = [
            {'month': month, 'revenue': round(revenue, 2)} 
            for month, revenue in monthly_revenue
        ]
        
        # Invoice statistics
        invoice_stats = db_manager.execute_query('''
            SELECT status, COUNT(*), COALESCE(SUM(total_amount), 0)
            FROM invoicing GROUP BY status
        ''', fetch_all=True)
        
        stats['invoicing'] = {
            'by_status': {status: {'count': count, 'total_amount': round(amount, 2)} 
                         for status, count, amount in invoice_stats}
        }
        
    except Exception as e:
        stats['error'] = str(e)
    
    return stats
```

### 🔄 Migration & Backup

#### 🔧 SQLite to PostgreSQL Migration
```python
#!/usr/bin/env python3
"""
SQLite to PostgreSQL Migration Script for AI-SwAutoMorph
Migrates all data from SQLite database to PostgreSQL
"""

def migrate_table(sqlite_conn, pg_conn, table_name, column_mapping=None):
    """Migrate a single table from SQLite to PostgreSQL"""
    print(f"Migrating table: {table_name}")
    
    sqlite_cursor = sqlite_conn.cursor()
    pg_cursor = pg_conn.cursor()
    
    # Get data from SQLite
    sqlite_cursor.execute(f"SELECT * FROM {table_name}")
    rows = sqlite_cursor.fetchall()
    
    if not rows:
        print(f"  No data found in {table_name}")
        return
    
    # Get column names
    columns = [description[0] for description in sqlite_cursor.description]
    
    # Apply column mapping if provided
    if column_mapping:
        pg_columns = [column_mapping.get(col, col) for col in columns]
    else:
        pg_columns = columns
    
    # Convert and insert data with type conversion
    converted_rows = []
    for row in rows:
        converted_row = []
        for i, value in enumerate(row):
            # Convert SQLite data types to PostgreSQL compatible types
            if columns[i] in ['suspended', 'is_default'] and value is not None:
                # Convert integer boolean to actual boolean
                converted_row.append(bool(value))
            elif columns[i] in ['created_at', 'updated_at', 'expires_at', 'started_at', 'stopped_at', 'payment_date', 'datetime'] and value:
                # Convert timestamp strings to proper format
                try:
                    if isinstance(value, str):
                        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
                        converted_row.append(dt)
                    else:
                        converted_row.append(value)
                except:
                    converted_row.append(value)
            elif columns[i] == 'server_ip' and value:
                # Ensure IP address is properly formatted
                converted_row.append(str(value))
            else:
                converted_row.append(value)
        converted_rows.append(converted_row)
    
    # Prepare INSERT statement with PostgreSQL syntax
    placeholders = ', '.join(['%s'] * len(pg_columns))
    insert_sql = f"INSERT INTO {table_name} ({', '.join(pg_columns)}) VALUES ({placeholders})"
    
    try:
        pg_cursor.executemany(insert_sql, converted_rows)
        pg_conn.commit()
        print(f"  Migrated {len(converted_rows)} rows")
    except Exception as e:
        print(f"  Error migrating {table_name}: {e}")
        pg_conn.rollback()
        raise

def reset_sequences(pg_conn):
    """Reset PostgreSQL sequences to match the migrated data"""
    pg_cursor = pg_conn.cursor()
    
    tables_with_sequences = [
        'users', 'applications', 'auth_tokens', 'user_applications',
        'servers', 'deployments', 'application_costs', 'billing_activities',
        'users_logs', 'payment_modes', 'invoicing'
    ]
    
    for table in tables_with_sequences:
        try:
            # Get the maximum ID from the table
            pg_cursor.execute(f"SELECT COALESCE(MAX(id), 0) FROM {table}")
            max_id = pg_cursor.fetchone()[0]
            
            # Reset the sequence
            sequence_name = f"{table}_id_seq"
            pg_cursor.execute(f"SELECT setval('{sequence_name}', {max_id + 1})")
            print(f"  Reset sequence {sequence_name} to {max_id + 1}")
        except Exception as e:
            print(f"  Warning: Could not reset sequence for {table}: {e}")
    
    pg_conn.commit()
```

#### 💾 PostgreSQL Backup Strategy
```bash
#!/bin/bash
# PostgreSQL backup script with compression and validation

BACKUP_DIR="./softfluid/db/backup"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_PATH="${BACKUP_DIR}/${TIMESTAMP}"
DB_NAME="ai_swautomorph"

# Create backup directory
mkdir -p "${BACKUP_PATH}"

# PostgreSQL backup with validation
echo "Starting PostgreSQL backup at $(date)"

# Create SQL dump
pg_dump -h localhost -U swautomorph -d ${DB_NAME} > "${BACKUP_PATH}/complete_database.sql"

# Create custom format backup (compressed)
pg_dump -h localhost -U swautomorph -d ${DB_NAME} -Fc > "${BACKUP_PATH}/database.backup"

# Create compressed backup
tar -czf "${BACKUP_PATH}/backup.tar.gz" -C "${BACKUP_DIR}" "${TIMESTAMP}"

# Generate backup manifest
cat > "${BACKUP_PATH}/manifest.json" << EOF
{
    "timestamp": "${TIMESTAMP}",
    "database": "${DB_NAME}",
    "backup_size": $(stat -c%s "${BACKUP_PATH}/database.backup"),
    "sql_dump_size": $(stat -c%s "${BACKUP_PATH}/complete_database.sql"),
    "backup_type": "postgresql"
}
EOF

echo "PostgreSQL backup completed successfully at $(date)"
```

### 🛡️ Security Enhancements

#### 🔒 Input Validation and Sanitization
```python
def validate_and_sanitize_input(input_value, input_type, max_length=None):
    """Comprehensive input validation and sanitization"""
    if input_value is None:
        return None
    
    # Convert to string for processing
    value = str(input_value).strip()
    
    if input_type == 'username':
        # Username: alphanumeric, underscore, hyphen only
        if not re.match(r'^[a-zA-Z0-9_-]+$', value):
            raise ValueError("Username contains invalid characters")
        if len(value) < 3 or len(value) > 50:
            raise ValueError("Username must be 3-50 characters")
    
    elif input_type == 'email':
        # Email validation
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, value):
            raise ValueError("Invalid email format")
    
    elif input_type == 'path':
        # Path validation - prevent directory traversal
        if '..' in value or value.startswith('/'):
            raise ValueError("Invalid path - directory traversal detected")
        value = os.path.normpath(value)
    
    elif input_type == 'sql_identifier':
        # SQL identifier (table/column names)
        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', value):
            raise ValueError("Invalid SQL identifier")
    
    # Length validation
    if max_length and len(value) > max_length:
        raise ValueError(f"Input exceeds maximum length of {max_length}")
    
    # XSS prevention
    value = html.escape(value)
    
    return value
```

#### 🔍 SQL Injection Prevention
```python
def execute_safe_query(query_template, params, allowed_tables=None):
    """Execute query with comprehensive SQL injection prevention"""
    
    # Validate query template
    if not isinstance(query_template, str):
        raise ValueError("Query template must be a string")
    
    # Check for dangerous SQL keywords
    dangerous_keywords = [
        'DROP', 'DELETE', 'TRUNCATE', 'ALTER', 'CREATE', 'EXEC', 'EXECUTE'
    ]
    
    query_upper = query_template.upper()
    for keyword in dangerous_keywords:
        if keyword in query_upper and not query_upper.startswith('CREATE INDEX'):
            raise ValueError(f"Dangerous SQL keyword detected: {keyword}")
    
    # Validate table names if provided
    if allowed_tables:
        for table in allowed_tables:
            if table not in ALLOWED_TABLES:
                raise ValueError(f"Table not allowed: {table}")
    
    # Validate parameters
    if params:
        validated_params = []
        for param in params:
            if isinstance(param, str):
                # Prevent SQL injection in string parameters
                if "'" in param or '"' in param or ';' in param:
                    param = param.replace("'", "''")  # Escape single quotes
                validated_params.append(param)
            else:
                validated_params.append(param)
        params = validated_params
    
    return db_manager.execute_query(query_template, params)
```

---

## Français

<div class="center">
🚀 **Architecture de Base de Données PostgreSQL pour AI-SwAutoMorph** 📊
</div>

### 📋 Table des Matières
- [🌟 Aperçu](#aperçu)
- [🐘 Migration PostgreSQL](#migration-postgresql)
- [🏗️ Schéma de Base de Données](#schéma-de-base-de-données)
- [🔧 Mise en Pool de Connexions](#mise-en-pool-de-connexions)
- [📊 Optimisations de Performance](#optimisations-de-performance)
- [💰 Système de Facturation](#système-de-facturation)
- [🔍 Surveillance de Santé](#surveillance-de-santé)
- [🔄 Migration et Sauvegarde](#migration-et-sauvegarde)
- [🛡️ Améliorations de Sécurité](#améliorations-de-sécurité)

### 🌟 Aperçu

AI-SwAutoMorph a migré de SQLite vers **PostgreSQL** pour des performances, une évolutivité et une fiabilité de niveau entreprise. Le système dispose maintenant de la mise en pool de connexions, des transactions ACID, des types de données avancés et des capacités de surveillance complètes.

#### 🎯 Améliorations Clés
- **🐘 Base de Données PostgreSQL** : Base de données de niveau entreprise avec conformité ACID complète
- **🏊 Mise en Pool de Connexions** : ThreadedConnectionPool avec connexions min/max configurables (2-20)
- **⚡ Types de Données Avancés** : INET pour adresses IP, BIGSERIAL pour auto-incrément, TIMESTAMP WITH TIME ZONE
- **🔍 Index Optimisés** : Index optimisés pour performance sur colonnes fréquemment interrogées
- **🔄 Triggers de Base de Données** : Gestion automatique des timestamps updated_at
- **📊 Surveillance Améliorée** : Statistiques de base de données en temps réel et vérifications de santé
- **💰 Intégration Facturation** : Suivi complet des coûts avec précision PostgreSQL
- **🖥️ Support Multi-Serveurs** : Gestion évolutive de capacité serveur
- **🔐 Sécurité Améliorée** : Requêtes paramétrées, support SSL et journalisation d'audit
- **🛠️ Outils de Migration** : Script de migration automatisé SQLite vers PostgreSQL

### 🐘 Migration PostgreSQL

La plateforme inclut des outils de migration automatisés pour une transition transparente de SQLite vers PostgreSQL avec préservation complète des données, mappage de schéma automatique, et validation des types de données.

### 🏗️ Schéma de Base de Données

Le schéma PostgreSQL utilise des types de données avancés comme BIGSERIAL pour les clés primaires, INET pour les adresses IP, TIMESTAMP WITH TIME ZONE pour les horodatages, et DECIMAL pour les calculs financiers précis.

### 🔧 Mise en Pool de Connexions

Le gestionnaire PostgreSQL utilise ThreadedConnectionPool avec connexions configurables (2-20), gestion automatique des erreurs transitoires, et nettoyage automatique des connexions.

### 📊 Optimisations de Performance

Les optimisations incluent des index complets sur les colonnes fréquemment interrogées, des triggers de base de données pour la gestion automatique des timestamps, et une configuration SSL pour la sécurité.

### 💰 Système de Facturation

Le système de facturation utilise des types DECIMAL pour des calculs financiers précis, avec enregistrement automatique des activités START/STOP et calcul des coûts basé sur la durée réelle d'utilisation.

### 🔍 Surveillance de Santé

La surveillance inclut des vérifications de connectivité PostgreSQL, des métriques de pool de connexions, des statistiques de performance, et une surveillance en temps réel de l'état de la base de données.

### 🔄 Migration et Sauvegarde

Les outils incluent un script de migration automatisé SQLite vers PostgreSQL avec conversion de types, mappage de colonnes, et réinitialisation de séquences. Les sauvegardes PostgreSQL utilisent pg_dump avec compression et validation.

### 🛡️ Améliorations de Sécurité

Les améliorations incluent des requêtes paramétrées pour prévenir l'injection SQL, le support SSL pour les connexions sécurisées, la validation d'entrée complète, et la journalisation d'audit pour toutes les opérations.