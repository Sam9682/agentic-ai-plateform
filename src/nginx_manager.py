"""Nginx configuration manager for dynamic location blocks"""
import os
import re
import glob
import tempfile
import logging
from typing import Optional, Tuple
from urllib.parse import urlparse
import yaml
from .config_postgres import DOMAIN

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Traefik dynamic-configuration (Proxy_Manager)
# ---------------------------------------------------------------------------
# The repo/install root. config_postgres.py has no exported path constant
# (PLTF_FOLDER is a folder *name*, not a path), so we derive the project root
# the same way config_postgres does internally: this module lives at
# <root>/src/nginx_manager.py, so two dirnames up is the install root. The root
# docker-compose.yml mounts ``./traefik/dynamic`` into the Traefik container at
# ``/etc/traefik/dynamic``, so the dynamic directory is anchored there.
_INSTALL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Per-app Traefik dynamic config directory (matches the compose mount
# ``./traefik/dynamic:/etc/traefik/dynamic``).
TRAEFIK_DYNAMIC_DIR = os.path.join(_INSTALL_ROOT, "traefik", "dynamic")

# Certificate path prefix *inside the Traefik container*. The root
# docker-compose.yml mounts the host ``./ssl`` directory read-only at
# ``/etc/traefik/ssl``, so every certFile/keyFile reference in the generated
# TLS dynamic config is anchored here (not at the host path).
TRAEFIK_SSL_DIR = "/etc/traefik/ssl"

# Carried-forward proxy timeouts (previously nginx proxy_connect_timeout 30s /
# proxy_read_timeout 60s). Applied via a shared serversTransport.
_DIAL_TIMEOUT = "30s"
_RESPONSE_HEADER_TIMEOUT = "60s"
_SERVERS_TRANSPORT = "app-transport"


def _prefix_path(user_name: str, app_name: str) -> str:
    """Return the Prefix_Path ``/{user}/{app}`` (no trailing slash in the rule)."""
    return f"/{user_name}/{app_name}"


def _router_name(user_name: str, app_name: str) -> str:
    """Return the Traefik router/service identifier ``{user}-{app}``."""
    return f"{user_name}-{app_name}"


def _backend_http_port(user_appli_url: str) -> int:
    """Return the internal container HTTP port known at deploy time.

    The port is derived from the stored application URL, never scraped from a
    running container (no ``docker ps``). Application URLs are stored using the
    HTTPS scheme/port (the second entry of each HTTP/HTTPS port pair); the HTTP
    port is always one below it. When the URL carries no port we fall back to
    the conventional plain-HTTP port 80.
    """
    _host, port = _host_and_port_from_url(user_appli_url)
    if port is None:
        return 80
    return port - 1 if port > 0 else port


def _route_file_path(user_name: str, app_name: str) -> str:
    """Return the per-app Traefik dynamic config file path."""
    return os.path.join(TRAEFIK_DYNAMIC_DIR, f"app-{user_name}-{app_name}.yml")


def _build_route_config(user_name: str, app_name: str, backend_host: str,
                        backend_port: int, domain: str) -> dict:
    """Build the Traefik dynamic-config dict for one application route.

    Produces a router (``Host(<domain>) && PathPrefix(/{user}/{app})`` on the
    ``websecure`` entrypoint with TLS enabled), a ``stripPrefix`` middleware for
    the Prefix_Path, a service whose load balancer points at
    ``http://<host>:<port>`` through the shared ``app-transport``, and that
    transport's carried-forward forwarding timeouts.
    """
    name = _router_name(user_name, app_name)
    prefix = _prefix_path(user_name, app_name)
    strip_mw = f"{name}-strip"

    return {
        "http": {
            "routers": {
                name: {
                    "rule": f"Host(`{domain}`) && PathPrefix(`{prefix}`)",
                    "entryPoints": ["websecure"],
                    "service": name,
                    "middlewares": [strip_mw],
                    "tls": {},
                }
            },
            "middlewares": {
                strip_mw: {
                    "stripPrefix": {
                        "prefixes": [prefix],
                    }
                }
            },
            "services": {
                name: {
                    "loadBalancer": {
                        "serversTransport": _SERVERS_TRANSPORT,
                        "servers": [
                            {"url": f"http://{backend_host}:{backend_port}"}
                        ],
                    }
                }
            },
            "serversTransports": {
                _SERVERS_TRANSPORT: {
                    "forwardingTimeouts": {
                        "dialTimeout": _DIAL_TIMEOUT,
                        "responseHeaderTimeout": _RESPONSE_HEADER_TIMEOUT,
                    }
                }
            },
        }
    }


def _write_route_file(path: str, config: dict) -> bool:
    """Atomically write a Traefik dynamic-config dict to ``path`` as YAML.

    The config is serialized with ``yaml.safe_dump`` into a temp file in the
    same directory, flushed and ``fsync``-ed, then ``os.replace``-d onto the
    target so Traefik's file watcher never reads a half-written file (the
    rename is atomic on POSIX). The ``TRAEFIK_DYNAMIC_DIR`` is created if it
    does not exist. On any failure the temp file is removed and ``False`` is
    returned; ``True`` is returned on success.

    This mirrors the temp-file-then-``os.replace`` discipline used by
    ``src/configuration_writer.py`` and the retired ``write_nginx_config``.
    """
    tmp_path = None
    try:
        target_dir = os.path.dirname(path) or "."
        os.makedirs(target_dir, exist_ok=True)

        content = yaml.safe_dump(config, default_flow_style=False, sort_keys=False)

        fd, tmp_path = tempfile.mkstemp(
            dir=target_dir,
            prefix=f".{os.path.basename(path)}.",
            suffix=".tmp",
        )
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())

        os.replace(tmp_path, path)
        return True
    except Exception as e:
        logger.error("Failed to write Traefik route file %s: %s", path, e)
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        return False


def _delete_route_file(path: str) -> bool:
    """Delete a per-app Traefik route file.

    A missing file is treated as success (idempotent removal), so rollback and
    teardown can call this best-effort. Returns ``True`` on successful deletion
    or when the file was already absent; returns ``False`` only on an actual
    deletion error.
    """
    try:
        os.remove(path)
        return True
    except FileNotFoundError:
        return True
    except Exception as e:
        logger.error("Failed to delete Traefik route file %s: %s", path, e)
        return False


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


def insert_location_block(user_name: str, app_name: str, deployment_url: str, user_appli_url: str) -> bool:
    """Apply an application's Traefik route (file provider).

    Derives the Prefix_Path, the backend host/port, and the platform domain,
    builds the Traefik dynamic-config dict via :func:`_build_route_config`, and
    writes it atomically to ``traefik/dynamic/app-{user}-{app}.yml``. Traefik's
    file watcher hot-applies the change; there is no validation/reload step.

    The backend host is the app container's network alias on
    ``swautomorph-shared`` (the hostname carried by ``user_appli_url``); the
    backend port is the internal HTTP port derived at deploy time from the URL
    (:func:`_backend_http_port`), never scraped from ``docker ps``. The router
    ``Host(...)`` rule uses the platform ``DOMAIN``.

    Returns ``True`` on success. Any exception is caught, logged, and converted
    to ``False`` so callers run their existing rollback handling (Req 8.6).
    """
    try:
        backend_host = _host_from_url(user_appli_url)
        if not backend_host:
            logger.error(
                "Cannot insert Traefik route for %s/%s: no host in URL '%s'",
                user_name, app_name, user_appli_url,
            )
            return False

        backend_port = _backend_http_port(user_appli_url)

        config = _build_route_config(
            user_name, app_name, backend_host, backend_port, DOMAIN
        )

        return _write_route_file(_route_file_path(user_name, app_name), config)

    except Exception as e:
        logger.error(f"Failed to insert Traefik route: {e}")
        return False

def remove_location_block(user_name: str, app_name: str) -> bool:
    """Remove an application's Traefik route (file provider).

    Deletes the per-app dynamic config file
    ``traefik/dynamic/app-{user}-{app}.yml``. A missing file is treated as
    success (idempotent removal) so rollback/teardown can call this
    best-effort. Returns ``True`` on success, ``False`` on an actual deletion
    error. Any unexpected exception is caught, logged, and converted to
    ``False`` so callers run their existing rollback handling (Req 8.6).
    """
    try:
        return _delete_route_file(_route_file_path(user_name, app_name))

    except Exception as e:
        logger.error(f"Failed to remove Traefik route: {e}")
        return False

def sync_all_locations(db_manager) -> bool:
    """Reconcile the Traefik dynamic directory to exactly match the database.

    Queries every ``user_applications`` row that carries a non-empty URL and,
    for each, writes/overwrites the per-app route file
    ``traefik/dynamic/app-{user}-{app}.yml`` (via :func:`insert_location_block`,
    which derives the backend host/port and builds the route config). Any
    existing ``app-*.yml`` file that no longer corresponds to a current DB app
    is deleted so the directory matches the database exactly; ``tls.yml`` and
    ``secondary-domains.yml`` are never touched.

    Per-app failures are isolated: a single bad app is logged and skipped, the
    remaining apps are still reconciled, and the function returns ``False`` if
    any app failed (otherwise ``True``). Stale-port reconciliation is
    intentionally gone — ports now come from the deploy-time contract, not from
    live containers, so no ``docker ps`` discovery or DB rewrite is performed.

    Running this twice against the same database is idempotent: the second run
    produces the same directory contents.
    """
    try:
        # Get all user applications with URLs (same SELECT as before).
        apps = db_manager.execute_query("""
            SELECT u.username, a.name, ua.url
            FROM user_applications ua
            JOIN applications a ON ua.application_id = a.id
            JOIN users u ON ua.user_id = u.id
            WHERE ua.url IS NOT NULL AND ua.url != ''
        """, fetch_all=True) or []

        all_ok = True

        # Desired set of per-app route files (one per DB app). Write/overwrite
        # each one; isolate per-app failures so a single bad app does not abort
        # the whole reconciliation.
        desired_files = set()
        for app in apps:
            try:
                user_name, app_name, url = app
                desired_files.add(_route_file_path(user_name, app_name))
                if not insert_location_block(user_name, app_name, url, url):
                    logger.error(
                        "Failed to sync Traefik route for %s/%s", user_name, app_name
                    )
                    all_ok = False
            except Exception as e:
                logger.error("Failed to sync Traefik route for app %r: %s", app, e)
                all_ok = False

        # Reconcile removals: delete any per-app route file that no longer maps
        # to a DB app. Only ``app-*.yml`` files are considered; tls.yml and
        # secondary-domains.yml are left untouched.
        try:
            existing_files = glob.glob(os.path.join(TRAEFIK_DYNAMIC_DIR, "app-*.yml"))
        except Exception as e:
            logger.error("Failed to list Traefik dynamic directory: %s", e)
            existing_files = []

        for path in existing_files:
            if path in desired_files:
                continue
            if not _delete_route_file(path):
                logger.error("Failed to delete stale Traefik route file %s", path)
                all_ok = False

        return all_ok

    except Exception as e:
        logger.error(f"Failed to sync Traefik routes: {e}")
        return False


# ---------------------------------------------------------------------------
# SECONDARY_DOMAINS multi-domain routing (Proxy_Manager, file provider)
# ---------------------------------------------------------------------------
# ``SECONDARY_DOMAINS`` is a comma-separated list of ``domain:server_names:
# proxy_pass`` entries (the existing deploy.ini format; see
# deployControlPlan.sh which parses it with ``IFS=':'``). ``server_names`` is a
# space-separated list within its field. Each entry maps to exactly one Traefik
# router (``Host(...)`` over the server names, on both the ``web`` and
# ``websecure`` entrypoints, with TLS enabled and an HTTP->HTTPS redirect
# middleware on the web router) and exactly one service whose load-balancer
# backend is the entry's ``proxy_pass`` URL. The whole config is rendered to
# ``traefik/dynamic/secondary-domains.yml`` via the file provider.

# Name of the shared HTTP->HTTPS redirect middleware applied on the web router.
_REDIRECT_MIDDLEWARE = "secondary-redirect-to-https"


def _secondary_router_name(domain: str) -> str:
    """Return a deterministic, Traefik-safe router/service id for a domain.

    Traefik router and service names may not contain dots or other separators
    used in rule syntax, so the domain's dots are turned into dashes and the
    result is prefixed with ``secondary-`` (matching the design example
    ``secondary-hypervisia-fr``).
    """
    safe = re.sub(r"[^A-Za-z0-9-]", "-", domain.strip().lower())
    safe = re.sub(r"-+", "-", safe).strip("-")
    return f"secondary-{safe}"


def parse_secondary_domains(raw: Optional[str]) -> list:
    """Parse the ``SECONDARY_DOMAINS`` string into structured entries.

    The format is a comma-separated list of ``domain:server_names:proxy_pass``
    entries where ``server_names`` is a space-separated list within its field,
    e.g. ``hypervisia.fr:hypervisia.fr www.hypervisia.fr:https://softfluid.fr:6137``.

    Note the ``proxy_pass`` value itself commonly contains a colon (scheme and
    port), so only the first two ``:`` separators delimit the fields; the
    remainder is the ``proxy_pass`` value.

    Returns a list of ``(domain, [server_names], proxy_pass)`` tuples. Blank or
    malformed entries (missing a domain, server names, or proxy_pass) are
    skipped so a partially filled config never yields a broken router.
    """
    if not raw or not raw.strip():
        return []

    entries = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        # Split into at most 3 fields: proxy_pass keeps its own ":".
        parts = chunk.split(":", 2)
        if len(parts) < 3:
            logger.warning(
                "Skipping malformed SECONDARY_DOMAINS entry (expected "
                "'domain:server_names:proxy_pass'): %r", chunk
            )
            continue
        domain = parts[0].strip()
        server_names = [s for s in parts[1].split() if s]
        proxy_pass = parts[2].strip()
        if not domain or not server_names or not proxy_pass:
            logger.warning(
                "Skipping incomplete SECONDARY_DOMAINS entry: %r", chunk
            )
            continue
        entries.append((domain, server_names, proxy_pass))
    return entries


def build_secondary_domains_config(entries: list) -> dict:
    """Build the Traefik dynamic-config dict for the secondary domains.

    ``entries`` is a list of ``(domain, [server_names], proxy_pass)`` tuples as
    returned by :func:`parse_secondary_domains`. Each entry yields exactly one
    router and one service:

    * router: ``Host(`name1`, `name2`, ...)`` over the entry's server names,
      attached to both the ``web`` and ``websecure`` entrypoints, ``tls: {}``,
      with the shared HTTP->HTTPS redirect middleware applied so plain-HTTP
      requests are upgraded (mirroring the previous nginx ``return 301`` block);
    * service: a ``loadBalancer`` whose single server url is the entry's
      ``proxy_pass`` value.

    The redirect middleware is declared once and shared by all routers. When
    ``entries`` is empty an empty ``http`` config is returned so the file
    provider has nothing to route.
    """
    routers: dict = {}
    services: dict = {}

    for domain, server_names, proxy_pass in entries:
        name = _secondary_router_name(domain)
        host_list = ", ".join(f"`{sn}`" for sn in server_names)
        routers[name] = {
            "rule": f"Host({host_list})",
            "entryPoints": ["web", "websecure"],
            "service": name,
            "middlewares": [_REDIRECT_MIDDLEWARE],
            "tls": {},
        }
        services[name] = {
            "loadBalancer": {
                "servers": [
                    {"url": proxy_pass}
                ]
            }
        }

    http: dict = {
        "routers": routers,
        "services": services,
    }

    # Only declare the redirect middleware when there is at least one router to
    # apply it to, keeping an empty config genuinely empty.
    if routers:
        http["middlewares"] = {
            _REDIRECT_MIDDLEWARE: {
                "redirectScheme": {
                    "scheme": "https",
                    "permanent": True,
                }
            }
        }

    return {"http": http}


def _secondary_domains_file_path() -> str:
    """Return the path of the rendered secondary-domains dynamic config file."""
    return os.path.join(TRAEFIK_DYNAMIC_DIR, "secondary-domains.yml")


def write_secondary_domains_config(raw: Optional[str], path: Optional[str] = None) -> bool:
    """Render the ``SECONDARY_DOMAINS`` config to the dynamic config file.

    Parses ``raw`` (the ``SECONDARY_DOMAINS`` string), builds the router/service
    config, and writes it to ``traefik/dynamic/secondary-domains.yml`` (or the
    supplied ``path``). The atomic route-file writer ``_write_route_file`` is
    reused when present; otherwise the write is performed atomically here. Any
    failure is caught, logged, and reported as ``False`` so provisioning can
    react, matching the Proxy_Manager error-handling contract.
    """
    target = path or _secondary_domains_file_path()
    try:
        entries = parse_secondary_domains(raw)
        config = build_secondary_domains_config(entries)

        writer = globals().get("_write_route_file")
        if callable(writer):
            return bool(writer(target, config))

        # Fallback atomic write (temp file + os.replace) when the shared
        # route-file writer is not available.
        import yaml  # local import: only needed for the fallback path
        os.makedirs(os.path.dirname(target), exist_ok=True)
        tmp_path = f"{target}.tmp"
        try:
            with open(tmp_path, "w") as f:
                yaml.safe_dump(config, f, default_flow_style=False, sort_keys=False)
            os.replace(tmp_path, target)
            return True
        except Exception:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            raise
    except Exception as e:
        logger.error("Failed to write secondary-domains config to %s: %s", target, e)
        return False


# ---------------------------------------------------------------------------
# TLS dynamic configuration (Traefik file provider)
# ---------------------------------------------------------------------------
# Traefik terminates HTTPS using the existing certificate pairs stored under
# ``ssl/<domain>/``. Rather than re-issuing certificates, the file provider is
# pointed at a single ``tls.yml`` listing one ``tls.certificates`` entry per
# configured domain (the primary ``DOMAIN`` plus each ``SECONDARY_DOMAINS``
# entry). Routers that declare ``tls: {}`` pick the matching certificate by SNI
# from the default store. See design "TLS via the file provider".


def _secondary_domains() -> list:
    """Return the domain portion of each ``SECONDARY_DOMAINS`` entry.

    ``SECONDARY_DOMAINS`` is a comma-separated list of
    ``domain:server_names:proxy_pass`` entries (the existing ``deploy.ini``
    format). For TLS only the first colon-field (the ``domain``, which names the
    ``ssl/<domain>/`` certificate directory) is needed; ``server_names`` and
    ``proxy_pass`` are ignored here. The value is read from ``deploy.ini`` the
    same way ``config_postgres`` reads its other settings, so the TLS config
    tracks the deploy configuration without requiring a new exported constant.

    Returns an ordered list of domain names with blanks skipped. An unreadable
    or unset ``SECONDARY_DOMAINS`` yields an empty list.
    """
    raw = None
    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(base_dir, "conf", "deploy.ini")
        with open(config_path, "r") as f:
            for line in f:
                if line.strip().startswith("SECONDARY_DOMAINS"):
                    raw = line.split("=", 1)[1].strip().strip("'\"")
                    break
    except Exception as e:  # pragma: no cover - environment dependent
        logger.warning("Could not read SECONDARY_DOMAINS from deploy.ini: %s", e)
        return []

    if not raw:
        return []

    domains = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        # The domain is the first colon-field. ``proxy_pass`` may itself contain
        # colons (e.g. ``https://host:6137``) but that is past the first split.
        domain = entry.split(":", 1)[0].strip()
        if domain:
            domains.append(domain)
    return domains


def _configured_domains() -> list:
    """Return every domain that needs a TLS certificate entry.

    The primary ``DOMAIN`` first, then each ``SECONDARY_DOMAINS`` domain, with
    duplicates removed while preserving order.
    """
    ordered = []
    for domain in [DOMAIN, *_secondary_domains()]:
        if domain and domain not in ordered:
            ordered.append(domain)
    return ordered


def build_tls_config(domains) -> dict:
    """Build the Traefik TLS dynamic-config dict for the given domains.

    For each domain, emit a ``tls.certificates`` entry referencing the existing
    certificate pair inside the Traefik container
    (``/etc/traefik/ssl/<domain>/fullchain_domain.crt`` and
    ``/etc/traefik/ssl/<domain>/privateKey_domain.key``). A default store is
    declared so routers using ``tls: {}`` resolve certificates by SNI.

    Duplicate domains are collapsed while preserving first-seen order so the
    output has exactly one certificate entry per domain.
    """
    seen = []
    certificates = []
    for domain in domains:
        if not domain or domain in seen:
            continue
        seen.append(domain)
        certificates.append({
            "certFile": f"{TRAEFIK_SSL_DIR}/{domain}/fullchain_domain.crt",
            "keyFile": f"{TRAEFIK_SSL_DIR}/{domain}/privateKey_domain.key",
        })

    return {
        "tls": {
            "certificates": certificates,
            "stores": {
                "default": {},
            },
        }
    }


def _tls_file_path() -> str:
    """Return the path of the TLS dynamic config file (``tls.yml``)."""
    return os.path.join(TRAEFIK_DYNAMIC_DIR, "tls.yml")


def _write_yaml_atomic(path: str, config: dict) -> bool:
    """Serialize ``config`` to YAML and write it atomically to ``path``.

    Writes to a temp file in the destination directory then ``os.replace``s it
    into place so Traefik's file watcher never reads a half-written file. On any
    failure the temp file is removed and ``False`` is returned.
    """
    directory = os.path.dirname(path)
    tmp_path = f"{path}.tmp"
    try:
        os.makedirs(directory, exist_ok=True)
        with open(tmp_path, "w") as f:
            yaml.safe_dump(config, f, default_flow_style=False, sort_keys=False)
        os.replace(tmp_path, path)
        return True
    except Exception as e:
        logger.error("Failed to write TLS config to %s: %s", path, e)
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        return False


def write_tls_config(domains=None) -> bool:
    """Render the TLS dynamic config to ``traefik/dynamic/tls.yml``.

    When ``domains`` is omitted the configured set (primary ``DOMAIN`` plus each
    ``SECONDARY_DOMAINS`` entry) is used. Returns ``True`` on success, ``False``
    on any failure.
    """
    if domains is None:
        domains = _configured_domains()
    config = build_tls_config(domains)
    return _write_yaml_atomic(_tls_file_path(), config)
