#!/usr/bin/env python3
"""Property test for carried-forward proxy timeouts in generated Traefik routes.

Feature: nginx-to-traefik-migration, Property 11
Property 11: Application routes carry the carried-forward timeouts.
Validates: Requirements 6.2

Over generated application route inputs, the config produced by
``src.frontend_manager._build_route_config`` must declare the nginx-equivalent
proxy timeouts on its shared ``serversTransports.app-transport`` forwarding
timeouts: a connect/dial timeout of ``30s`` and a read/response-header timeout
of ``60s``.
"""
import os
import sys

from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src.frontend_manager import _build_route_config  # noqa: E402

# DNS-label-ish fragments for user/app names: lowercase alnum + hyphen.
_NAME = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-", min_size=1, max_size=20)
# Hostname-ish fragments for backend host / domain.
_HOST = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-.", min_size=1, max_size=40)
_PORT = st.integers(min_value=1, max_value=65535)


@settings(max_examples=200)
@given(
    user_name=_NAME,
    app_name=_NAME,
    backend_host=_HOST,
    backend_port=_PORT,
    domain=_HOST,
)
def test_app_routes_carry_carried_forward_timeouts(
    user_name, app_name, backend_host, backend_port, domain
):
    """Feature: nginx-to-traefik-migration, Property 11.

    Validates: Requirements 6.2
    """
    config = _build_route_config(
        user_name=user_name,
        app_name=app_name,
        backend_host=backend_host,
        backend_port=backend_port,
        domain=domain,
    )

    transports = config["http"]["serversTransports"]
    assert "app-transport" in transports, (
        "expected a shared 'app-transport' serversTransport"
    )

    forwarding = transports["app-transport"]["forwardingTimeouts"]
    assert forwarding["dialTimeout"] == "30s", (
        f"expected 30s connect/dial timeout, got {forwarding.get('dialTimeout')!r}"
    )
    assert forwarding["responseHeaderTimeout"] == "60s", (
        "expected 60s read/response-header timeout, got "
        f"{forwarding.get('responseHeaderTimeout')!r}"
    )


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
