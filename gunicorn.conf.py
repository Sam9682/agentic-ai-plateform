# Gunicorn configuration file
import multiprocessing
import os

# Load PLTF_FOLDER from deploy.ini
def _get_pltf_folder():
    try:
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'conf', 'deploy.ini')
        with open(config_path, 'r') as f:
            for line in f:
                if line.strip().startswith('PLTF_FOLDER'):
                    return line.split('=', 1)[1].strip().strip("'\"")
    except Exception:
        pass
    return 'agentic-ai-plateform'

PLTF_FOLDER = _get_pltf_folder()

# Load LINUX_USER_INSTALLATION from deploy.ini
def _get_linux_user():
    try:
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'conf', 'deploy.ini')
        with open(config_path, 'r') as f:
            for line in f:
                if line.strip().startswith('LINUX_USER_INSTALLATION'):
                    value = line.split('=', 1)[1].strip().strip("'\"")
                    if value:
                        return value
    except Exception:
        pass
    return 'psmc'

LINUX_USER_INSTALLATION = _get_linux_user()

# Server socket
bind = "127.0.0.1:5000"
backlog = 2048

# Worker processes
workers = multiprocessing.cpu_count() * 2 + 1
worker_class = "sync"
worker_connections = 1000
timeout = 1800  # 30 minutes for AI Chat operations
keepalive = 2

# Restart workers after this many requests, to help prevent memory leaks
max_requests = 1000
max_requests_jitter = 50

# Logging
accesslog = "logs/gunicorn_access.log"
errorlog = "logs/gunicorn_error.log"
loglevel = "info"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'

# Process naming
proc_name = PLTF_FOLDER

# Daemon mode
daemon = True
pidfile = "conf/gunicorn.pid"

# User and group to run as
user = os.getuid()
group = os.getgid()

# Preload application for better performance
preload_app = True

# Enable auto-reload in development
reload = os.environ.get('FLASK_ENV') == 'development'

# Environment variables
raw_env = [
    f'PYTHONPATH=/home/{LINUX_USER_INSTALLATION}/{PLTF_FOLDER}',
    'USE_POSTGRES=true'
]