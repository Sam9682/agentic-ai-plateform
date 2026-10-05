"""Nginx configuration manager for dynamic location blocks"""
import os
import re
import json
import subprocess
import logging
from typing import Optional, Dict, Tuple
from urllib.parse import urlparse, urlunparse
from .config_postgres import PLTF_FOLDER

logger = logging.getLogger(__name__)

NGINX_CONF_DIR = "/etc/nginx/sites-available"
NGINX_ENABLED_DIR = "/etc/nginx/sites-enabled"
NGINX_CONF_FILE = PLTF_FOLDER

# Logical component identifiers. These are the classification labels used
# internally to map a running container to a role. They are intentionally
# decoupled from the container-name markers ('-nginx-', '-app-') used to
# detect the role, so a component's logical name can be changed in one place.
FRONTEND_COMPONENT = 'frontend-component'
BACKEND_COMPONENT = 'backend-component'


def discover_running_ports() -> Dict[Tuple[str, str], Dict[str, int]]:
    """Discover the real HTTP/HTTPS ports of running app containers.

    Each application is deployed with docker-compose into
    ``/home/<linux_user>/deployments/<user>/<app>``. The compose project sets
    the ``com.docker.compose.project.working_dir`` label to that path, which is
    the reliable way to map a running container back to its ``(user, app)``.

    A deployment runs several containers. Their names follow the platform
    convention ``<service>-<component>-<userid>-<hostport>`` where the two we
    care about are:

      * the ``nginx`` sidecar, publishing ``<HTTPS_PORT>:443`` (serves HTTPS)
      * the ``app`` container, publishing ``<HTTP_PORT>:<internal>`` (serves
        plain HTTP — this is what nginx must ``proxy_pass`` to)

    The internal app port varies per template (5000, 8000, ...), and the
    HTTP/HTTPS host-port offset is *not* constant across apps, so we cannot
    derive one from the other by arithmetic. We therefore read the real
    published host ports straight from Docker:

      * ``https`` = host port mapped to container 443 (the nginx sidecar)
      * ``http``  = host port published by the ``-app-`` container

    Ports drift from the database when an app is redeployed, which is exactly
    what leaves the generated nginx config pointing at a stale port; reading
    the live values keeps the proxy correct.

    Returns ``{(user, app): {"http": <port>, "https": <port>}}``. If Docker is
    unavailable an empty mapping is returned so callers fall back to the URL.
    """
    mapping: Dict[Tuple[str, str], Dict[str, int]] = {}
    try:
        result = subprocess.run(
            ['sudo', 'docker', 'ps', '--format', '{{json .}}'],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            logger.warning("docker ps failed while discovering ports: %s", result.stderr.strip())
            return mapping
    except Exception as e:  # pragma: no cover - environment dependent
        logger.warning("Could not run docker ps to discover ports: %s", e)
        return mapping

    for raw_line in result.stdout.splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            info = json.loads(raw_line)
        except (ValueError, TypeError):
            continue

        labels = info.get('Labels', '') or ''
        working_dir = _label_value(labels, 'com.docker.compose.project.working_dir')

        user_app = _user_app_from_working_dir(working_dir)
        if user_app is None:
            continue

        name = info.get('Names', '') or ''
        component = _component_from_name(name)
        ports_str = info.get('Ports', '') or ''

        entry = mapping.setdefault(user_app, {})

        if component == FRONTEND_COMPONENT:
            # The HTTPS sidecar: host port mapped to container 443.
            https_port = _published_port_for_target(ports_str, 443)
            if https_port is not None:
                entry['https'] = https_port
        elif component == BACKEND_COMPONENT:
            # The HTTP backend nginx must proxy_pass to. Use the first
            # published host port regardless of the internal container port.
            http_port = _first_published_port(ports_str)
            if http_port is not None:
                entry['http'] = http_port

    return mapping


def _component_from_name(name: str) -> Optional[str]:
    """Return the docker-compose service component from a container name.

    Names look like ``<app>-nginx-1-6136`` or ``<app>-app-25-8525``. We look
    for the ``-nginx-`` / ``-app-`` component marker.
    """
    if not name:
        return None
    if '-nginx-' in name:
        return FRONTEND_COMPONENT
    if '-app-' in name:
        return BACKEND_COMPONENT
    if '-postgres-' in name:
        return 'postgres'
    if '-frontend-' in name:
        return 'frontend'
    return None


def _first_published_port(ports_str: str) -> Optional[int]:
    """Return the first published host port from a docker Ports string.

    Prefers an IPv4 (0.0.0.0) mapping when present.
    """
    if not ports_str:
        return None
    pattern = re.compile(r'(\d+)\s*->\s*\d+/tcp')
    candidates = []
    for segment in ports_str.split(','):
        segment = segment.strip()
        m = pattern.search(segment)
        if m:
            is_ipv4 = segment.startswith('0.0.0.0')
            candidates.append((0 if is_ipv4 else 1, int(m.group(1))))
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][1]


def _label_value(labels: str, key: str) -> Optional[str]:
    """Extract a single label value from docker's comma-separated label string."""
    for part in labels.split(','):
        part = part.strip()
        if part.startswith(key + '='):
            return part[len(key) + 1:]
    return None


def _user_app_from_working_dir(working_dir: Optional[str]) -> Optional[Tuple[str, str]]:
    """Map a compose working_dir to (user, app).

    Expected form: ``.../deployments/<user>/<app>``. Returns None if the path
    does not contain a ``deployments`` segment followed by user/app.
    """
    if not working_dir:
        return None
    parts = [p for p in working_dir.strip('/').split('/') if p]
    if 'deployments' not in parts:
        return None
    idx = parts.index('deployments')
    if idx + 2 < len(parts) + 1 and len(parts) >= idx + 3:
        return (parts[idx + 1], parts[idx + 2])
    return None


def _published_port_for_target(ports_str: str, target: int) -> Optional[int]:
    """Parse the published host port that maps to a given container port.

    Docker's ``Ports`` string looks like::

        80/tcp, 0.0.0.0:6136->443/tcp, [::]:6136->443/tcp

    We return the host port (6136) that maps to ``target`` (443). Prefers the
    IPv4 (0.0.0.0) mapping when present.
    """
    if not ports_str:
        return None
    # Match "<host>:<hostport>-><target>/tcp"
    pattern = re.compile(r'(\d+)\s*->\s*' + str(target) + r'/tcp')
    candidates = []
    for segment in ports_str.split(','):
        segment = segment.strip()
        m = pattern.search(segment)
        if m:
            is_ipv4 = segment.startswith('0.0.0.0')
            candidates.append((0 if is_ipv4 else 1, int(m.group(1))))
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][1]


def to_http_upstream_url(user_appli_url: str) -> str:
    """Convert an application URL to the HTTP upstream used by nginx proxy_pass.

    Application URLs are stored using the HTTPS scheme and the HTTPS port
    (the second entry of each port pair, e.g. ``https://host:8525``). The
    upstream that nginx should proxy to is the HTTP endpoint: the HTTP
    scheme and the HTTP port, which is the first entry of the pair and always
    one below the HTTPS port (e.g. ``http://host:8524``).

    The URL is returned without a trailing slash; callers append their own.
    """
    if not user_appli_url:
        return user_appli_url

    raw = user_appli_url.rstrip('/')

    try:
        # urlparse only fills netloc/port when the URL has a "//" authority.
        # For bare "host:port" forms it mistakes the host for the scheme, so
        # normalise by prepending a scheme when one is absent.
        if "://" not in raw:
            raw_for_parse = f"https://{raw}"
        else:
            raw_for_parse = raw
        parsed = urlparse(raw_for_parse)

        host = parsed.hostname
        port = parsed.port

        if host is None:
            # Could not parse a host; fall back to the original value.
            return raw

        if port is not None:
            # HTTP port is the first of the HTTP/HTTPS pair (one below HTTPS).
            http_port = port - 1 if port > 0 else port
            netloc = f"{host}:{http_port}"
        else:
            netloc = host

        rebuilt = urlunparse(('http', netloc, parsed.path or '', parsed.params, parsed.query, parsed.fragment))
        return rebuilt.rstrip('/')
    except (ValueError, IndexError):
        logger.warning("Could not derive HTTP upstream from URL '%s'; using it as-is", user_appli_url)
        return raw


def _host_from_url(user_appli_url: str) -> Optional[str]:
    """Extract the hostname from a stored application URL."""
    if not user_appli_url:
        return None
    raw = user_appli_url.rstrip('/')
    raw_for_parse = raw if "://" in raw else f"https://{raw}"
    try:
        return urlparse(raw_for_parse).hostname
    except ValueError:
        return None


def _host_and_port_from_url(user_appli_url: str) -> Tuple[Optional[str], Optional[int]]:
    """Extract (hostname, port) from a stored application URL."""
    if not user_appli_url:
        return (None, None)
    raw = user_appli_url.rstrip('/')
    raw_for_parse = raw if "://" in raw else f"https://{raw}"
    try:
        parsed = urlparse(raw_for_parse)
        return (parsed.hostname, parsed.port)
    except ValueError:
        return (None, None)


def build_http_upstream(user_appli_url: str, real_http_port: Optional[int] = None) -> str:
    """Build the ``http://host:port`` upstream nginx should proxy to.

    When ``real_http_port`` is provided (discovered from the running container)
    it takes precedence over whatever port is encoded in the stored URL. This
    is what keeps the generated nginx config in sync with the actually running
    containers even when the database URL is stale. When no real port is known
    we fall back to deriving it from the stored HTTPS URL.
    """
    if real_http_port:
        host = _host_from_url(user_appli_url)
        if host:
            return f"http://{host}:{real_http_port}"
    return to_http_upstream_url(user_appli_url)


def generate_location_block(user_name: str, app_name: str, deployment_url: str,
                            user_appli_url: str, real_http_port: Optional[int] = None) -> str:
    """Generate nginx location block for user application.

    ``real_http_port`` is the actual HTTP port published by the running
    container. When given it overrides the (possibly stale) port stored in the
    database URL so the proxy always targets the live container.
    """
    location_path = f"/{user_name}/{app_name}/"

    # nginx must proxy to the HTTP endpoint (HTTP scheme + HTTP port, the first
    # port of the pair). Prefer the real running port; fall back to the URL.
    user_appli_url = build_http_upstream(user_appli_url, real_http_port)

    return f"""
    # Dynamic location for user {user_name} - {app_name}
    location {location_path} {{
        proxy_pass {user_appli_url}/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Redirect rewriting to preserve context path
        proxy_redirect {user_appli_url}/ {location_path};
        proxy_redirect / {location_path};

        # WebSocket support
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";

        # Timeouts
        proxy_connect_timeout 30s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;

        # Rewrite HTML content to fix absolute paths
        sub_filter 'href="/' 'href="{location_path}';
        sub_filter 'src="/' 'src="{location_path}';
        sub_filter_once off;
        sub_filter_types text/css text/javascript application/javascript;
    }}
"""

def get_nginx_config_path() -> str:
    """Get the path to the nginx configuration file"""
    return os.path.join(NGINX_CONF_DIR, NGINX_CONF_FILE)

def read_nginx_config() -> str:
    """Read current nginx configuration"""
    config_path = get_nginx_config_path()

    try:
        with open(config_path, 'r') as f:
            return f.read()
    except Exception as e:
        logger.error(f"Failed to read nginx config: {e}")
        raise

def write_nginx_config(config: str) -> bool:
    """Write nginx configuration to file"""
    config_path = get_nginx_config_path()

    try:
        # Write to temp file first
        temp_path = f"/tmp/{NGINX_CONF_FILE}"
        with open(temp_path, 'w') as f:
            f.write(config)

        # Move with sudo
        result = subprocess.run(['sudo', 'mv', temp_path, config_path], capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            logger.error(f"Failed to move config: {result.stderr}")
            return False

        # Set proper permissions
        subprocess.run(['sudo', 'chmod', '644', config_path], capture_output=True, text=True, timeout=10)

        # Create symlink in sites-enabled if not exists
        enabled_path = os.path.join(NGINX_ENABLED_DIR, NGINX_CONF_FILE)
        if not os.path.exists(enabled_path):
            subprocess.run(['sudo', 'ln', '-sf', config_path, enabled_path], capture_output=True, text=True, timeout=10)

        return True
    except Exception as e:
        logger.error(f"Failed to write nginx config: {e}")
        return False

def _strip_dynamic_blocks(config: str, only_user: Optional[str] = None,
                          only_app: Optional[str] = None) -> str:
    """Remove dynamic location blocks from an nginx config, robustly.

    The previous implementation stopped skipping at the first line whose
    stripped content equalled ``}``. That is fragile: any change to block
    formatting (or a partially written block) could leave the closing brace
    mismatched and emit a malformed block (e.g. a ``location`` with no
    ``proxy_pass``). Here we track brace depth from the ``location`` line so we
    always remove exactly the whole block, no matter its internal formatting.

    If ``only_user``/``only_app`` are given, only that specific block is
    removed; otherwise every dynamic block is stripped.
    """
    marker = "# Dynamic location for user"
    if only_user is not None and only_app is not None:
        target_marker = f"# Dynamic location for user {only_user} - {only_app}"
    else:
        target_marker = None

    lines = config.split('\n')
    out = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        is_marker = (marker in line) if target_marker is None else (target_marker in line)
        if is_marker:
            # Skip the marker comment line(s) and the following location block,
            # balancing braces so we consume exactly one block.
            i += 1
            # Advance to the opening brace of the location block.
            depth = 0
            opened = False
            while i < n:
                cur = lines[i]
                depth += cur.count('{') - cur.count('}')
                i += 1
                if '{' in cur:
                    opened = True
                if opened and depth <= 0:
                    break
            # Drop a single trailing blank separator line if present.
            if i < n and lines[i].strip() == '':
                i += 1
            continue
        out.append(line)
        i += 1
    return '\n'.join(out)


def insert_location_block(user_name: str, app_name: str, deployment_url: str, user_appli_url: str) -> bool:
    """Insert or update location block in nginx configuration"""
    try:
        config = read_nginx_config()

        # Use the real running container port when available.
        ports = discover_running_ports().get((user_name, app_name), {})
        real_http_port = ports.get('http')

        location_block = generate_location_block(
            user_name, app_name, deployment_url, user_appli_url, real_http_port
        )

        # Remove existing location block for this user/app if it exists.
        config = _strip_dynamic_blocks(config, only_user=user_name, only_app=app_name)

        # Insert before the main location / block in the 443 server
        location_root_idx = config.find('    location / {')
        if location_root_idx != -1:
            config = config[:location_root_idx] + location_block + '\n' + config[location_root_idx:]

        # Write configuration
        if write_nginx_config(config):
            return reload_nginx()

        return False

    except Exception as e:
        logger.error(f"Failed to insert location block: {e}")
        return False

def remove_location_block(user_name: str, app_name: str) -> bool:
    """Remove location block from nginx configuration"""
    try:
        config = read_nginx_config()

        config = _strip_dynamic_blocks(config, only_user=user_name, only_app=app_name)

        # Write configuration
        if write_nginx_config(config):
            return reload_nginx()

        return False

    except Exception as e:
        logger.error(f"Failed to remove location block: {e}")
        return False

def test_nginx_config() -> bool:
    """Test nginx configuration for syntax errors"""
    try:
        result = subprocess.run(['sudo', 'nginx', '-t'], capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            logger.error(f"Nginx config test failed: {result.stderr}")
        return result.returncode == 0
    except Exception as e:
        logger.error(f"Failed to test nginx config: {e}")
        return False

def reload_nginx() -> bool:
    """Reload nginx configuration"""
    try:
        result = subprocess.run(['sudo', 'nginx', '-t'], capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            logger.error(f"Nginx configuration test failed: {result.stderr}")
            return False

        result = subprocess.run(['sudo', 'systemctl', 'reload', 'nginx'], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            logger.info("Nginx reloaded successfully")
            return True
        else:
            logger.error(f"Failed to reload nginx: {result.stderr}")
            return False
    except Exception as e:
        logger.error(f"Failed to reload nginx: {e}")
        return False

def _reconcile_stale_db_url(db_manager, user_name: str, app_name: str,
                            stored_url: str, real_http_port: int, real_https_port: int) -> None:
    """Update the stored URL/ports when they disagree with the running container.

    Best-effort: failures are logged but never abort the sync. Keeps the
    database aligned with reality so future syncs (and the dashboard link) are
    correct without a redeploy.
    """
    try:
        host = _host_from_url(stored_url) or ''
        new_url = f"https://{host}:{real_https_port}" if host else stored_url
        db_manager.execute_query(
            """
            UPDATE user_applications
            SET url = %s, http_port = %s, https_port = %s
            FROM applications a, users u
            WHERE user_applications.application_id = a.id
              AND user_applications.user_id = u.id
              AND u.username = %s AND a.name = %s
            """,
            (new_url, real_http_port, real_https_port, user_name, app_name),
        )
        logger.info(
            "Reconciled stale ports for %s/%s: url -> %s (http=%s, https=%s)",
            user_name, app_name, new_url, real_http_port, real_https_port,
        )
    except Exception as e:
        logger.warning("Could not reconcile DB ports for %s/%s: %s", user_name, app_name, e)


def sync_all_locations(db_manager) -> bool:
    """Sync all user application locations from database.

    The nginx upstream port is taken from the *actually running* container
    (discovered from Docker), not the possibly-stale port stored in the
    database URL. When the two disagree the database is reconciled so it
    matches reality. This fixes the class of bug where a redeployed app is
    serving on a new port but nginx keeps proxying to the old one.
    """
    try:
        # Get all user applications with URLs
        apps = db_manager.execute_query("""
            SELECT u.username, a.name, ua.url
            FROM user_applications ua
            JOIN applications a ON ua.application_id = a.id
            JOIN users u ON ua.user_id = u.id
            WHERE ua.url IS NOT NULL AND ua.url != ''
        """, fetch_all=True)

        if not apps:
            logger.info("No applications to sync")
            return True

        # Discover the real, currently-running ports once.
        running_ports = discover_running_ports()

        # Start with base configuration
        config = read_nginx_config()

        # Clear all dynamic locations robustly (brace-balanced).
        config = _strip_dynamic_blocks(config)

        # Build all location blocks, preferring the real running port.
        location_blocks = []
        for app in apps:
            user_name, app_name, url = app
            ports = running_ports.get((user_name, app_name), {})
            real_http_port = ports.get('http')
            real_https_port = ports.get('https')

            location_blocks.append(
                generate_location_block(user_name, app_name, url, url, real_http_port)
            )

            # If the running container's port differs from what the DB stores,
            # reconcile the DB so it stops being stale.
            if real_http_port and real_https_port:
                stored_https = _host_and_port_from_url(url)[1]
                if stored_https != real_https_port:
                    _reconcile_stale_db_url(
                        db_manager, user_name, app_name, url,
                        real_http_port, real_https_port,
                    )

        # Insert before location / in the 443 server
        location_root_idx = config.find('    location / {')
        if location_root_idx != -1:
            config = config[:location_root_idx] + '\n'.join(location_blocks) + '\n' + config[location_root_idx:]

        # Write and reload
        if write_nginx_config(config):
            return reload_nginx()

        return False

    except Exception as e:
        logger.error(f"Failed to sync locations: {e}")
        return False