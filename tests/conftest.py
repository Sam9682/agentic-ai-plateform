"""Shared pytest configuration for the test suite.

Registers custom markers so running the suite with ``-W error`` or strict marker
settings does not warn/fail on them.
"""


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: marks tests that bring up real services (Traefik, Docker) "
        "and require explicit opt-in env vars plus a live daemon; skipped by "
        "default. See tests/test_traefik_docker_api_version_integration.py.",
    )
