"""Serverless Docker Execution Service - Configuration

Configuration keys consumed by the serverless worker (Phase 4):

* ``max_concurrent_jobs`` (R5.4) — upper bound on serverless jobs executing
  simultaneously for a worker. ``ServerlessWorker`` reads this as the default
  for its ``max_concurrent`` cap and defers claiming new work while
  ``in_flight >= max_concurrent_jobs``.
* ``db_pool_min_conn`` / ``db_pool_max_conn`` (R5.5) — sizing for the worker's
  pooled PostgreSQL access (``_WorkerConnectionPool`` /
  ``psycopg2.pool.ThreadedConnectionPool``). Surfaced here so the pool bounds
  are documented and configurable in one place. The defaults (``1`` / ``10``)
  are behavior-identical to the pool's existing hardcoded defaults, so exposing
  them changes nothing unless an operator overrides them.
"""

SERVERLESS_CONFIG = {
    'registry_whitelist': [
        'docker.io',
        'ghcr.io',
        'registry.example.com'
    ],
    'default_timeout': 300,
    'max_timeout': 3600,
    'default_memory_limit': '512m',
    'default_cpu_limit': '1',
    'max_concurrent_jobs': 100,
    'log_retention_days': 30,
    'poll_interval': 0.5,
    'container_stop_timeout': 10,
    'warm_pool_enabled': False,
    'warm_pool_size': 0,
    # Pooled DB access sizing (R5.5). Defaults match the worker pool's existing
    # minconn=1/maxconn=10 so surfacing them is behavior-neutral.
    'db_pool_min_conn': 1,
    'db_pool_max_conn': 10,
}


def validate_image_registry(image: str, whitelist: list) -> bool:
    """Check if a Docker image comes from an approved registry.

    Parses the image reference to extract the registry hostname and validates
    it against the provided whitelist. Images without an explicit registry
    prefix (e.g. 'python:3.11' or 'library/python:3.11') are assumed to
    come from 'docker.io'.

    Docker image reference parsing logic:
    - If the first path component (before the first '/') contains a '.' or ':'
      or equals 'localhost', it is treated as the registry hostname.
    - Otherwise, the image is assumed to come from 'docker.io'.

    Args:
        image: Full or short image reference (e.g. 'ghcr.io/org/app:latest',
               'python:3.11', 'myregistry.com/image',
               'registry.example.com:5000/myapp:latest').
        whitelist: List of approved registry hostnames.

    Returns:
        True if the image's registry is in the whitelist, False otherwise.
    """
    # Strip digest (e.g. @sha256:abc123...)
    image_ref = image.split("@")[0]

    # Split on '/' to get path components
    parts = image_ref.split("/")

    # Determine the first component (potential registry)
    first_component = parts[0]

    if len(parts) == 1:
        # Simple image name like 'python:3.11' — defaults to docker.io
        registry = "docker.io"
    else:
        # Check if first component looks like a registry hostname:
        # It contains a dot (e.g. 'ghcr.io', 'registry.example.com')
        # or a colon (e.g. 'localhost:5000', 'registry.example.com:5000')
        # or equals 'localhost'
        if "." in first_component or ":" in first_component or first_component == "localhost":
            # Extract hostname without port for whitelist comparison
            registry = first_component.split(":")[0]
        else:
            # User/image like 'library/python:3.11' — defaults to docker.io
            registry = "docker.io"

    return registry in whitelist
