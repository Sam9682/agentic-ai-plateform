"""Shared pytest configuration for the test suite.

Registers custom markers so running the suite with ``-W error`` or strict marker
settings does not warn/fail on them.
"""

import os

# Restore the development context the suite has always run under. Before Phase 1,
# src/config_postgres.py defaulted FLASK_ENV to 'development'; the Phase 1 secret
# fail-fast now treats unset FLASK_ENV as production, so the harness must declare
# the dev context explicitly. setdefault respects any explicitly-set value.
os.environ.setdefault("FLASK_ENV", "development")


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: marks tests that bring up real services (Traefik, Docker) "
        "and require explicit opt-in env vars plus a live daemon; skipped by "
        "default. See tests/test_traefik_docker_api_version_integration.py.",
    )
