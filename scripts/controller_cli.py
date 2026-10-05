#!/usr/bin/env python3
import click
import requests
import json
import subprocess
import os
import sys

# Add the parent directory to the path so we can import from src
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE_URL = 'http://www.swautomorph.com:80'

def select_from_list(items, title="Select an option"):
    """Interactive selection using arrow keys"""
    try:
        from simple_term_menu import TerminalMenu
        terminal_menu = TerminalMenu(
            items,
            title=title,
            menu_cursor="▶ ",
            menu_cursor_style=("fg_cyan", "bold"),
            menu_highlight_style=("bg_cyan", "fg_black"),
            cycle_cursor=True
        )
        choice = terminal_menu.show()
        return items[choice] if choice is not None else None
    except ImportError:
        # Fallback to numbered selection
        click.echo(f"\n{title}")
        for idx, item in enumerate(items, 1):
            click.echo(f"{idx}. {item}")
        choice = click.prompt('Select number', type=int)
        if 1 <= choice <= len(items):
            return items[choice - 1]
        return None

@click.group()
def cli():
    """AI-SwAutoMorph CLI Tool"""
    pass

@cli.command()
@click.option('--username', prompt=True, help='Username')
@click.option('--email', prompt=True, help='Email address')
@click.option('--password', prompt=True, hide_input=True, help='Password')
@click.option('--first-name', help='First name')
@click.option('--last-name', help='Last name')
def register(username, email, password, first_name, last_name):
    """Register a new user"""
    data = {
        'username': username,
        'email': email,
        'password': password,
        'first_name': first_name or '',
        'last_name': last_name or ''
    }
    
    try:
        response = requests.post(f'{BASE_URL}/register', json=data)
        if response.status_code == 201:
            click.echo('User registered successfully!')
        else:
            click.echo(f'Error: {response.json().get("error", "Unknown error")}')
    except requests.exceptions.ConnectionError:
        click.echo('Error: Cannot connect to server. Make sure the application is running.')

@cli.command()
def list_apps():
    """List all available applications"""
    try:
        response = requests.get(f'{BASE_URL}/api/applications')
        if response.status_code == 200:
            apps = response.json()
            if apps:
                click.echo('\nAvailable Applications:')
                nb = 1
                for app in apps:
                    url = app.get('git_url') or app.get('url', 'N/A')
                    click.echo(f"{nb}- {app['name']}: {url}")
                    if app.get('description'):
                        click.echo(f"  Description: {app['description']}")
                    nb = nb + 1
            else:
                click.echo('No applications found.')
        else:
            click.echo('Error fetching applications')
    except requests.exceptions.ConnectionError:
        click.echo('Error: Cannot connect to server. Make sure the application is running.')

@cli.command()
@click.option('--name', prompt=True, help='Application name')
@click.option('--url', prompt=True, help='Application URL')
@click.option('--description', help='Application description')
def add_app(name, url, description):
    """Add a new application (requires authentication)"""
    try:
        from src.database_postgres import db_manager
        db_manager.execute_query(
            'INSERT INTO applications (name, git_url, description) VALUES (%s, %s, %s)',
            (name, url, description or '')
        )
        click.echo('Application added successfully!')
    except Exception as e:
        click.echo(f'Error: {str(e)}')

@cli.command()
@click.option('--token', prompt=True, help='SSO token to validate')
def validate_token(token):
    """Validate an SSO token"""
    data = {'token': token}
    
    try:
        response = requests.post(f'{BASE_URL}/sso/validate', json=data)
        if response.status_code == 200:
            result = response.json()
            if result['valid']:
                user = result['user']
                click.echo(f'Token is valid for user: {user["username"]} ({user["email"]})')
                click.echo(f'Expires at: {user["expires_at"]}')
            else:
                click.echo('Token is invalid or expired')
        else:
            click.echo('Token validation failed')
    except requests.exceptions.ConnectionError:
        click.echo('Error: Cannot connect to server. Make sure the application is running.')

@cli.command()
def init_db():
    """Initialize the PostgreSQL database"""
    try:
        from src.database_postgres import init_db as app_init_db
        click.echo('Initializing PostgreSQL database...')
        app_init_db()
        click.echo('Database initialized successfully!')
    except Exception as e:
        click.echo(f'Error initializing database: {str(e)}')
        sys.exit(1)

@cli.command()
def db_health():
    """Check database health"""
    try:
        from src.db_health import check_database_health, get_database_stats
        health = check_database_health()
        stats = get_database_stats()
        
        click.echo('\n' + '='*60)
        click.echo('DATABASE HEALTH STATUS')
        click.echo('='*60)
        click.echo(f"Status: {health['status']}")
        if health['status'] == 'healthy':
            click.echo(f"Tables: {health['tables_count']}")
            click.echo(f"Journal Mode: {health['journal_mode']}")
        else:
            click.echo(f"Error: {health.get('error', 'Unknown error')}")
        
        if 'error' not in stats:
            click.echo('\n' + '='*60)
            click.echo('DATABASE STATISTICS')
            click.echo('='*60)
            click.echo(f"{'Table':<30} {'Records':>10}")
            click.echo('-'*60)
            for key, value in sorted(stats.items()):
                if key.endswith('_count'):
                    table_name = key.replace('_count', '').replace('_', ' ').title()
                    click.echo(f"{table_name:<30} {value:>10,}")
            click.echo('-'*60)
            if 'database_size_bytes' in stats:
                size_mb = stats['database_size_bytes'] / (1024 * 1024)
                click.echo(f"{'Database Size':<30} {size_mb:>9.2f} MB")
            click.echo('='*60)
        
    except Exception as e:
        click.echo(f'Error checking database health: {str(e)}')

@cli.command()
@click.argument('bucket_name')
@click.argument('mount_point')
@click.option('--passwd-file', default='.passwd-s3fs', help='S3FS password file')
def mount_s3fs(bucket_name, mount_point, passwd_file):
    """Mount OVH Cloud S3 storage using s3fs"""
    os.makedirs(mount_point, exist_ok=True)
    
    cmd = [
        "s3fs", bucket_name, mount_point,
        "-o", f"passwd_file={passwd_file}",
        "-o", "url=https://s3.gra.cloud.ovh.net",
        "-o", "use_path_request_style"
    ]
    
    try:
        subprocess.run(cmd, check=True)
        click.echo(f"Successfully mounted {bucket_name} to {mount_point}")
    except subprocess.CalledProcessError as e:
        click.echo(f"Mount failed: {e}")

@cli.command()
@click.option('--show-env', is_flag=True, help='Show current environment settings')
def db_status(show_env):
    """Show application status and configuration"""
    click.echo('Database Type: PostgreSQL')
    
    if show_env:
        click.echo('\nEnvironment Variables:')
        click.echo(f'POSTGRES_HOST: {os.environ.get("POSTGRES_HOST", "localhost")}')
        click.echo(f'POSTGRES_DB: {os.environ.get("POSTGRES_DB", "ai_swautomorph")}')
        click.echo(f'POSTGRES_USER: {os.environ.get("POSTGRES_USER", "swautomorph")}')
        click.echo(f'POSTGRES_PASSWORD: {"***" if os.environ.get("POSTGRES_PASSWORD") else "not set"}')
    
    try:
        from src.database_postgres import db_manager
        result = db_manager.execute_query("SELECT 1", fetch_one=True)
        if result:
            click.echo(f'✅ Database connection: OK')
        else:
            click.echo(f'❌ Database connection: Failed')
    except Exception as e:
        click.echo(f'❌ Database connection: Failed - {str(e)}')

@cli.command()
@click.confirmation_option(prompt='⚠️  This will permanently delete PostgreSQL database. Continue?')
def delete_db():
    """Delete PostgreSQL database completely"""
    import shutil
    from src.database_postgres import db_manager
    
    deleted = []
    errors = []
    
    # Drop all tables in the database
    try:
        click.echo('Dropping all tables...')
        tables_query = "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        tables = db_manager.execute_query(tables_query, fetch_all=True)
        
        for (table_name,) in tables:
            try:
                db_manager.execute_query(f'DROP TABLE IF EXISTS {table_name} CASCADE')
                deleted.append(f'Table: {table_name}')
            except Exception as e:
                errors.append(f'Table {table_name}: {str(e)}')
    except Exception as e:
        errors.append(f'Database operation: {str(e)}')
    
    # PostgreSQL data directory (Docker)
    postgres_data = 'softfluid/postgres_data'
    if os.path.exists(postgres_data):
        try:
            shutil.rmtree(postgres_data)
            deleted.append(f'Directory: {postgres_data}')
        except Exception as e:
            errors.append(f'{postgres_data}: {str(e)}')
    
    if deleted:
        click.echo('\n✅ Deleted:')
        for item in deleted:
            click.echo(f'  - {item}')
    
    if errors:
        click.echo('\n❌ Errors:')
        for error in errors:
            click.echo(f'  - {error}')
    
    if not deleted and not errors:
        click.echo('No PostgreSQL database or tables found.')

@cli.command()
def list_tables():
    """List all tables with record counts"""
    try:
        from src.database_postgres import db_manager
        
        tables_query = "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
        tables = db_manager.execute_query(tables_query, fetch_all=True)
        
        if not tables:
            click.echo('No tables found in database.')
            return
        
        click.echo('\n' + '='*60)
        click.echo('DATABASE TABLES')
        click.echo('='*60)
        click.echo(f"{'Table Name':<40} {'Records':>15}")
        click.echo('-'*60)
        
        for (table_name,) in tables:
            count_query = f"SELECT COUNT(*) FROM {table_name}"
            result = db_manager.execute_query(count_query, fetch_one=True)
            count = result[0] if result else 0
            click.echo(f"{table_name:<40} {count:>15,}")
        
        click.echo('='*60)
        
    except Exception as e:
        click.echo(f'Error: {str(e)}')

@cli.command()
@click.argument('sql_query')
@click.confirmation_option(prompt='⚠️  This will execute an SQL query. Continue?')
def exec_sql_request(sql_query):
    """Execute SQL query on database"""
    try:
        from src.database_postgres import db_manager
        
        result = db_manager.execute_query(sql_query)
        click.echo(f'✅ Query executed successfully. Rows affected: {result if result else 0}')
        
    except Exception as e:
        click.echo(f'❌ Error: {str(e)}')

@cli.command()
@click.argument('table_name', required=False)
def describe_table(table_name):
    """Describe table structure"""
    try:
        from src.database_postgres import db_manager
        
        # Get all tables if no table specified
        if not table_name:
            tables_query = "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
            tables = db_manager.execute_query(tables_query, fetch_all=True)
            
            if not tables:
                click.echo('No tables found in database.')
                return
            
            table_list = [tbl[0] for tbl in tables]
            table_name = select_from_list(table_list, "Select table to describe:")
            
            if not table_name:
                click.echo('No table selected.')
                return
        
        # Get table structure
        structure_query = """
            SELECT column_name, data_type, character_maximum_length, 
                   is_nullable, column_default
            FROM information_schema.columns
            WHERE table_name = %s
            ORDER BY ordinal_position
        """
        columns = db_manager.execute_query(structure_query, (table_name,), fetch_all=True)
        
        if not columns:
            click.echo(f'Table "{table_name}" not found.')
            return
        
        click.echo('\n' + '='*80)
        click.echo(f'TABLE: {table_name}')
        click.echo('='*80)
        click.echo(f"{'Column':<25} {'Type':<20} {'Nullable':<10} {'Default':<20}")
        click.echo('-'*80)
        
        for col_name, data_type, max_len, nullable, default in columns:
            type_str = f"{data_type}({max_len})" if max_len else data_type
            default_str = str(default)[:18] if default else '-'
            click.echo(f"{col_name:<25} {type_str:<20} {nullable:<10} {default_str:<20}")
        
        click.echo('='*80)
        
    except Exception as e:
        click.echo(f'Error: {str(e)}')

@cli.command()
@click.argument('table_name', required=False)
@click.option('--limit', default=10, help='Number of rows to display')
def select_table(table_name, limit):
    """Display table content"""
    try:
        from src.database_postgres import db_manager
        
        # Get all tables if no table specified
        if not table_name:
            tables_query = "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
            tables = db_manager.execute_query(tables_query, fetch_all=True)
            
            if not tables:
                click.echo('No tables found in database.')
                return
            
            table_list = [tbl[0] for tbl in tables]
            table_name = select_from_list(table_list, "Select table to view:")
            
            if not table_name:
                click.echo('No table selected.')
                return
        
        # Get column names
        columns_query = """
            SELECT column_name FROM information_schema.columns
            WHERE table_name = %s ORDER BY ordinal_position
        """
        columns = db_manager.execute_query(columns_query, (table_name,), fetch_all=True)
        
        if not columns:
            click.echo(f'Table "{table_name}" not found.')
            return
        
        col_names = [col[0] for col in columns]
        
        # Get table data
        data_query = f"SELECT * FROM {table_name} LIMIT %s"
        rows = db_manager.execute_query(data_query, (limit,), fetch_all=True)
        
        if not rows:
            click.echo(f'\nTable "{table_name}" is empty.')
            return
        
        # Calculate column widths
        col_widths = [len(name) for name in col_names]
        for row in rows:
            for i, val in enumerate(row):
                col_widths[i] = max(col_widths[i], len(str(val)) if val is not None else 4)
        
        # Limit column width to 30 characters
        col_widths = [min(w, 30) for w in col_widths]
        
        total_width = sum(col_widths) + len(col_widths) * 3 + 1
        
        click.echo('\n' + '='*total_width)
        click.echo(f'TABLE: {table_name} (showing {len(rows)} of {len(rows)} rows)')
        click.echo('='*total_width)
        
        # Print header
        header = ' | '.join(name[:w].ljust(w) for name, w in zip(col_names, col_widths))
        click.echo(header)
        click.echo('-'*total_width)
        
        # Print rows
        for row in rows:
            row_str = ' | '.join(
                str(val)[:w].ljust(w) if val is not None else 'NULL'.ljust(w)
                for val, w in zip(row, col_widths)
            )
            click.echo(row_str)
        
        click.echo('='*total_width)
        
    except Exception as e:
        click.echo(f'Error: {str(e)}')

@cli.command()
def update_nginx_locations():
    """Sync nginx locations from database"""
    try:
        from src.database_postgres import db_manager
        from src.nginx_manager import sync_all_locations
        
        click.echo('Synchronizing nginx locations from database...')
        
        if sync_all_locations(db_manager):
            click.echo('✓ Nginx locations synced successfully')
        else:
            click.echo('✗ Failed to sync nginx locations')
            sys.exit(1)
    except Exception as e:
        click.echo(f'✗ Error: {str(e)}')
        sys.exit(1)

@cli.command()
def platform_status():
    """Show platform status and server roles"""
    try:
        from src.platform_discovery import get_current_server_ip
        from src.database_postgres import db_manager
        
        current_ip = get_current_server_ip()
        server = db_manager.execute_query(
            'SELECT server_type, server_name FROM servers WHERE server_ip = %s',
            (current_ip,), fetch_one=True
        )
        
        if server:
            click.echo(f"Platform Role: {server[0]}")
            click.echo(f"Server Name: {server[1]}")
            click.echo(f"Server IP: {current_ip}")
        else:
            click.echo("Server not registered in database")
        
        servers = db_manager.execute_query(
            'SELECT server_ip, server_name, server_type, server_status FROM servers ORDER BY id',
            fetch_all=True
        )
        
        click.echo("\nAll Servers:")
        for s in servers:
            click.echo(f"  - {s[1]} ({s[0]}): {s[2]} [{s[3]}]")
    except Exception as e:
        click.echo(f'Error: {str(e)}')

@cli.command()
@click.argument('remote_ip')
def discover_server(remote_ip):
    """Discover remote SwAutoMorph server"""
    try:
        from src.platform_discovery import get_current_server_ip, check_remote_platform, determine_role, update_server_role
        from src.database_postgres import db_manager
        
        click.echo(f"Checking {remote_ip} for SwAutoMorph...")
        
        remote_status = check_remote_platform(remote_ip)
        
        if remote_status:
            click.echo(f"✓ SwAutoMorph found!")
            click.echo(f"  Role: {remote_status.get('role')}")
            click.echo(f"  Version: {remote_status.get('version')}")
            click.echo(f"  Server: {remote_status.get('server_name')}")
            
            current_ip = get_current_server_ip()
            our_role = determine_role(current_ip, remote_ip, remote_status, db_manager)
            
            click.echo(f"\nRole determination:")
            click.echo(f"  Current server will be: {our_role}")
            click.echo(f"  Remote server is: {remote_status.get('role')}")
            
            update_server_role(current_ip, our_role, db_manager)
            click.echo(f"\n✓ Local server role updated to {our_role}")
        else:
            click.echo("✗ No SwAutoMorph detected at this IP")
    except Exception as e:
        click.echo(f'Error: {str(e)}')

@cli.command()
def replication_sync_status():
    """Check replication sync status across servers"""
    try:
        from src.database_postgres import db_manager
        from src.replication_manager import REPLICATED_TABLES
        
        click.echo('\n' + '='*60)
        click.echo('REPLICATION STATUS')
        click.echo('='*60)
        
        servers = db_manager.execute_query(
            "SELECT server_ip, server_name, server_type, server_status FROM servers",
            fetch_all=True
        )
        
        click.echo(f"\nPeer Servers: {len(servers)}")
        for server in servers:
            click.echo(f"  - {server[1]} ({server[0]}) [{server[2]}] - {server[3]}")
        
        click.echo(f"\nReplicated Tables: {', '.join(REPLICATED_TABLES)}")
        
        click.echo('\n' + '='*60)
        click.echo('RECORD COUNTS')
        click.echo('='*60)
        for table in REPLICATED_TABLES:
            try:
                result = db_manager.execute_query(f"SELECT COUNT(*) FROM {table}", fetch_one=True)
                click.echo(f"  {table:<25} {result[0]:>10,} records")
            except Exception as e:
                click.echo(f"  {table:<25} Error: {e}")
        click.echo('='*60)
    except Exception as e:
        click.echo(f'Error: {str(e)}')

@cli.command()
@click.argument('table')
@click.argument('server_ip')
def replication_sync_table(table, server_ip):
    """Manually sync table to remote server"""
    try:
        from src.database_postgres import db_manager
        from src.replication_manager import REPLICATED_TABLES
        import requests
        import urllib3
        import time
        from datetime import datetime
        
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        if table not in REPLICATED_TABLES:
            click.echo(f"Error: Table '{table}' is not configured for replication")
            click.echo(f"Available tables: {', '.join(REPLICATED_TABLES)}")
            return
        
        click.echo(f"\nManual Sync: {table} -> {server_ip}\n")
        
        records = db_manager.execute_query(f"SELECT * FROM {table}", fetch_all=True)
        click.echo(f"Found {len(records)} records to sync")
        
        columns = db_manager.execute_query(
            f"SELECT column_name FROM information_schema.columns WHERE table_name = '{table}' ORDER BY ordinal_position",
            fetch_all=True
        )
        col_names = [c[0] for c in columns]
        
        sync_secret = os.environ.get('SYNC_SECRET', 'default-sync-secret-change-me')
        success_count = 0
        
        # Detect protocol
        protocol = 'https'
        try:
            requests.get(f"https://{server_ip}/api/sync/health", timeout=2, verify=False)
        except:
            protocol = 'http'
        
        with click.progressbar(records, label='Syncing') as bar:
            for record in bar:
                data = dict(zip(col_names, record))
                # Convert datetime objects to ISO format strings
                for key, value in data.items():
                    if isinstance(value, datetime):
                        data[key] = value.isoformat()
                
                event = {
                    'event_id': f"manual-{table}-{time.time()}",
                    'timestamp': datetime.now().isoformat(),
                    'table': table,
                    'operation': 'INSERT',
                    'data': data,
                    'primary_key': {'id': data.get('id')},
                    'version': int(time.time() * 1000)
                }
                
                try:
                    response = requests.post(
                        f"{protocol}://{server_ip}/api/sync/replicate",
                        json=event,
                        headers={'X-Sync-Token': sync_secret},
                        timeout=5,
                        verify=False
                    )
                    if response.status_code == 200:
                        result = response.json()
                        if result.get('status') in ['applied', 'skipped']:
                            success_count += 1
                except Exception as e:
                    click.echo(f"\nError syncing record {data.get('id')}: {e}")
        
        click.echo(f"\nSync complete: {success_count}/{len(records)} records synced successfully")
    except Exception as e:
        click.echo(f'Error: {str(e)}')

@cli.command()
@click.argument('server_ip')
def replication_sync_all_tables(server_ip):
    """Sync all replicated tables to remote server"""
    tables = ['users', 'application_costs', 'payment_modes', 'applications', 
              'auth_tokens', 'user_applications', 'billing_activities']
    
    click.echo(f"\nSyncing all tables to {server_ip}\n")
    
    for table in tables:
        click.echo(f"\n{'='*60}")
        click.echo(f"Syncing table: {table}")
        click.echo('='*60)
        
        try:
            from src.database_postgres import db_manager
            import requests
            import urllib3
            import time
            from datetime import datetime
            
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            
            records = db_manager.execute_query(f"SELECT * FROM {table}", fetch_all=True)
            click.echo(f"Found {len(records)} records")
            
            if not records:
                click.echo("No records to sync")
                continue
            
            columns = db_manager.execute_query(
                f"SELECT column_name FROM information_schema.columns WHERE table_name = '{table}' ORDER BY ordinal_position",
                fetch_all=True
            )
            col_names = [c[0] for c in columns]
            
            sync_secret = os.environ.get('SYNC_SECRET', 'default-sync-secret-change-me')
            success_count = 0
            
            protocol = 'https'
            try:
                requests.get(f"https://{server_ip}/api/sync/health", timeout=2, verify=False)
            except:
                protocol = 'http'
            
            with click.progressbar(records, label='Syncing') as bar:
                for record in bar:
                    data = dict(zip(col_names, record))
                    for key, value in data.items():
                        if isinstance(value, datetime):
                            data[key] = value.isoformat()
                    
                    event = {
                        'event_id': f"manual-{table}-{time.time()}",
                        'timestamp': datetime.now().isoformat(),
                        'table': table,
                        'operation': 'INSERT',
                        'data': data,
                        'primary_key': {'id': data.get('id')},
                        'version': int(time.time() * 1000)
                    }
                    
                    try:
                        response = requests.post(
                            f"{protocol}://{server_ip}/api/sync/replicate",
                            json=event,
                            headers={'X-Sync-Token': sync_secret},
                            timeout=5,
                            verify=False
                        )
                        if response.status_code == 200:
                            result = response.json()
                            if result.get('status') in ['applied', 'skipped']:
                                success_count += 1
                    except Exception as e:
                        click.echo(f"\nError syncing record {data.get('id')}: {e}")
            
            click.echo(f"Completed: {success_count}/{len(records)} records synced")
        except Exception as e:
            click.echo(f"Error syncing {table}: {str(e)}")
    
    click.echo(f"\n{'='*60}")
    click.echo("All tables sync completed")
    click.echo('='*60)

@cli.command()
@click.argument('server_ip')
def replication_test_sync(server_ip):
    """Test connectivity to peer server"""
    try:
        import requests
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        click.echo(f"\nTesting Connectivity: {server_ip}\n")
        
        for protocol in ['https', 'http']:
            try:
                url = f"{protocol}://{server_ip}/api/sync/health"
                click.echo(f"Trying {protocol.upper()}...")
                
                response = requests.get(url, timeout=5, verify=False)
                
                if response.status_code == 200:
                    data = response.json()
                    click.echo(f"✓ Server is reachable via {protocol.upper()}")
                    click.echo(f"  Status: {data.get('status')}")
                    click.echo(f"  Queue Size: {data.get('queue_size')}")
                    click.echo(f"  Timestamp: {data.get('timestamp')}")
                    return
                else:
                    click.echo(f"  Server returned status {response.status_code}")
            except requests.exceptions.ConnectionError:
                click.echo(f"  Connection refused on {protocol.upper()}")
            except Exception as e:
                click.echo(f"  Error: {e}")
        
        click.echo(f"\n✗ Could not connect to {server_ip} on HTTPS or HTTP")
        click.echo(f"  Possible issues:")
        click.echo(f"  - Server is not running")
        click.echo(f"  - Firewall blocking ports 80/443")
        click.echo(f"  - Wrong IP address")
    except Exception as e:
        click.echo(f'Error: {str(e)}')

@cli.command()
def install_as_systemctl_service():
    """Install SWAutomorph as systemd service"""
    import shutil
    
    # Resolve install identity and render the unit via the shared helper so the
    # live install and the committed fallback artifact never diverge. User= and
    # the /home/<user>/<folder> paths come from LINUX_USER_INSTALLATION and
    # PLTF_FOLDER in conf/deploy.ini (canonical fallbacks psmc / agentic-ai-plateform).
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from controlplan_service import resolve_service_identity, render_controlplan_unit

    linux_user, pltf_folder = resolve_service_identity()
    systemd_path = '/etc/systemd/system/swautomorph-controlplan.service'
    service_content = render_controlplan_unit(linux_user, pltf_folder)
    
    try:
        click.echo('Installing systemd service...')
        with open(systemd_path, 'w') as f:
            f.write(service_content)
        click.echo(f'✓ Generated service file at {systemd_path} (using PLTF_FOLDER={pltf_folder})')
        
        subprocess.run(['systemctl', 'daemon-reload'], check=True)
        click.echo('✓ Reloaded systemd daemon')
        
        subprocess.run(['systemctl', 'enable', 'swautomorph-controlplan.service'], check=True)
        click.echo('✓ Enabled swautomorph-controlplan service')
        
        click.echo('\n✅ Service installed successfully!')
        click.echo('\nUsage:')
        click.echo('  sudo systemctl start swautomorph-controlplan')
        click.echo('  sudo systemctl stop swautomorph-controlplan')
        click.echo('  sudo systemctl status swautomorph-controlplan')
    except subprocess.CalledProcessError as e:
        click.echo(f'✗ Error: {e}')
        sys.exit(1)
    except PermissionError:
        click.echo('✗ Permission denied. Run with sudo:')
        click.echo('  sudo python3 ./scripts/controller_cli.py install-as-systemctl-service')
        sys.exit(1)
    except Exception as e:
        click.echo(f'✗ Error: {str(e)}')
        sys.exit(1)

# ----------------------------------------------------------------------------
# Onboarding Experience: sandbox + templates subcommands (Req 1.1, 2.1, 2.2,
# 9.1, 9.3). Every surface deploys through the same shared components:
#   - SandboxManager (src/sandbox_manager.py) for provision/reset/teardown
#   - TemplateCatalog (src/template_catalog.py) as the single source of truth
#   - TemplateDeployService (src/template_deploy.py) for template deploys
# ----------------------------------------------------------------------------

@cli.group()
def sandbox():
    """Manage the demo sandbox environment (provision/reset/teardown)."""
    pass


@sandbox.command(name='provision')
def sandbox_provision():
    """Provision the demo sandbox (Demo_User + seeded sample applications)."""
    try:
        from src.orchestrator import orchestrator
        from src.sandbox_manager import SandboxManager

        manager = SandboxManager(orchestrator=orchestrator)
        report = manager.provision()

        if report.success:
            click.echo('✅ Sandbox provisioned successfully!')
            if report.message:
                click.echo(report.message)

            creds = report.credentials or {}
            click.echo('\nDemo_User credentials:')
            click.echo(f"  Username: {creds.get('username')}")
            click.echo(f"  Password: {creds.get('password')}")
            if creds.get('user_id') is not None:
                click.echo(f"  User ID:  {creds.get('user_id')}")

            click.echo('\nSeeded applications:')
            for app in report.apps:
                click.echo(
                    f"  - {app.get('application_name')} "
                    f"[{app.get('status')}]: {app.get('access_url')}"
                )
        else:
            click.echo(f"❌ {report.message or 'Sandbox provisioning failed.'}")
            if report.failed:
                click.echo('Failed applications:')
                for item in report.failed:
                    label = item.get('application_name') or item.get('template_id') or item.get('reason')
                    detail = item.get('message')
                    click.echo(f"  - {label}" + (f": {detail}" if detail else ''))
            sys.exit(1)
    except Exception as e:
        click.echo(f'Error: {str(e)}')
        sys.exit(1)


@sandbox.command(name='reset')
def sandbox_reset():
    """Reset the sandbox: remove existing sample apps and re-seed the baseline."""
    try:
        from src.orchestrator import orchestrator
        from src.sandbox_manager import SandboxManager

        manager = SandboxManager(orchestrator=orchestrator)
        report = manager.reset()

        click.echo(report.message or ('Sandbox reset.' if report.success else 'Sandbox reset failed.'))
        if report.failed:
            click.echo('Failures:')
            for item in report.failed:
                label = item.get('application_name') or item.get('template_id')
                detail = item.get('message')
                click.echo(f"  - {label}" + (f": {detail}" if detail else ''))
        if not report.success:
            sys.exit(1)
    except Exception as e:
        click.echo(f'Error: {str(e)}')
        sys.exit(1)


@sandbox.command(name='teardown')
def sandbox_teardown():
    """Tear down the sandbox: stop and remove all demo resources."""
    try:
        from src.orchestrator import orchestrator
        from src.sandbox_manager import SandboxManager

        manager = SandboxManager(orchestrator=orchestrator)
        report = manager.teardown()

        click.echo(report.message or ('Sandbox torn down.' if report.success else 'Sandbox teardown failed.'))
        if report.failed:
            click.echo('Failures:')
            for item in report.failed:
                label = item.get('application_name') or item.get('template_id')
                detail = item.get('message')
                click.echo(f"  - {label}" + (f": {detail}" if detail else ''))
        if not report.success:
            sys.exit(1)
    except Exception as e:
        click.echo(f'Error: {str(e)}')
        sys.exit(1)


@cli.group()
def templates():
    """Deploy templates from the marketplace catalog (list/deploy)."""
    pass


@templates.command(name='list')
def templates_list():
    """List the available Deploy_Templates (identifier + application type)."""
    try:
        from src.template_catalog import TemplateCatalog

        catalog = TemplateCatalog().load()
        entries = catalog.list()

        if not entries:
            click.echo('No valid templates are available.')
            return

        click.echo('\nAvailable Templates:')
        click.echo('='*60)
        click.echo(f"{'Identifier':<30} {'App Type':<20}")
        click.echo('-'*60)
        for entry in entries:
            click.echo(f"{str(entry.get('identifier')):<30} {str(entry.get('app_type')):<20}")
        click.echo('='*60)
    except Exception as e:
        click.echo(f'Error: {str(e)}')
        sys.exit(1)


@templates.command(name='deploy')
@click.argument('template_id')
@click.argument('app_name')
@click.option('--user-id', 'user_id', type=int, required=True, help='Owner user id for the deployment')
def templates_deploy(template_id, app_name, user_id):
    """Deploy TEMPLATE_ID as APP_NAME for the given user (Req 9.1, 9.3)."""
    try:
        from src.orchestrator import orchestrator
        from src.template_catalog import TemplateCatalog
        from src.template_deploy import TemplateDeployService

        catalog = TemplateCatalog().load()

        # Unknown template_id: list the available identifiers and deploy NOTHING
        # (Req 9.3). Checked up front so the orchestrator is never invoked.
        if catalog.get(template_id) is None:
            click.echo(f"❌ Error: template '{template_id}' not found.")
            available = [entry.get('identifier') for entry in catalog.list()]
            if available:
                click.echo('Available template identifiers:')
                for identifier in available:
                    click.echo(f"  - {identifier}")
            else:
                click.echo('No valid templates are available.')
            sys.exit(1)

        service = TemplateDeployService(catalog, orchestrator)
        result = service.deploy(template_id, app_name, user_id)

        if result.success:
            click.echo('✅ Deployment initiated successfully!')
            click.echo(f"  Deployment identifier: {result.application_id}")
            if result.access_url:
                click.echo(f"  Access URL: {result.access_url}")
        else:
            click.echo(f"❌ Error: {result.message or 'deployment failed'}")
            sys.exit(1)
    except Exception as e:
        click.echo(f'Error: {str(e)}')
        sys.exit(1)


if __name__ == '__main__':
    cli()