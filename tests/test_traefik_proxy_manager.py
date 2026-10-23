#!/usr/bin/env python3
"""Property-based tests for the Traefik Proxy_Manager route generation.

Feature: nginx-to-traefik-migration

These tests exercise the pure route-building core in ``src/frontend_manager.py``
(the Proxy_Manager) with no runtime dependencies. They import the module
directly and assert universal properties of the generated Traefik dynamic
configuration dict across many generated inputs.

Run directly:
    python3 tests/test_traefik_proxy_manager.py
Or via pytest:
    pytest tests/test_traefik_proxy_manager.py
"""
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from hypothesis import given, settings, strategies as st

from src.frontend_manager import _build_route_config


# ---------------------------------------------------------------------------
# Generation strategies
# ---------------------------------------------------------------------------
# User and app names on the platform are DNS-label-style identifiers: lowercase
# alphanumerics and hyphens. We constrain generation to that space so the names
# never introduce characters that would break the Traefik rule or the derived
# router identifier (``{user}-{app}``).
_DNS_LABEL = st.from_regex(r"[a-z0-9][a-z0-9-]{0,30}", fullmatch=True)

# Domains are dotted DNS names built from one or more labels (e.g.
# ``www.swautomorph.com``).
_DOMAIN = st.lists(_DNS_LABEL, min_size=1, max_size=4).map(".".join)

# Backend hosts are a hostname label, a dotted DNS name, or a docker service
# name - all drawn from the same safe label space.
_BACKEND_HOST = st.one_of(_DNS_LABEL, _DOMAIN)

# Internal container HTTP ports: valid TCP port range.
_BACKEND_PORT = st.integers(min_value=1, max_value=65535)


# ---------------------------------------------------------------------------
# Property 1: Deploy produces a complete, prefix-correct route
# Validates: Requirements 1.3, 1.5
# ---------------------------------------------------------------------------
@settings(max_examples=200)
@given(
    user_name=_DNS_LABEL,
    app_name=_DNS_LABEL,
    backend_host=_BACKEND_HOST,
    backend_port=_BACKEND_PORT,
    domain=_DOMAIN,
)
def test_property_1_complete_prefix_correct_route(
    user_name, app_name, backend_host, backend_port, domain
):
    """Feature: nginx-to-traefik-migration, Property 1.

    Over generated user/app/host/port/domain, the generated route must be a
    complete, prefix-correct Traefik route:
      * the router rule is exactly
        ``Host(`{domain}`) && PathPrefix(`/{user}/{app}`)``
      * the stripPrefix middleware prefix list is exactly ``["/{user}/{app}"]``
      * the service loadBalancer server url carries the supplied backend port
        (``http://{host}:{port}``)
    """
    config = _build_route_config(
        user_name, app_name, backend_host, backend_port, domain
    )

    prefix = f"/{user_name}/{app_name}"
    http = config["http"]

    # --- Router rule: Host(...) && PathPrefix(...) ------------------------
    routers = http["routers"]
    assert len(routers) == 1, "expected exactly one router"
    router = next(iter(routers.values()))
    expected_rule = f"Host(`{domain}`) && PathPrefix(`{prefix}`)"
    assert router["rule"] == expected_rule

    # --- StripPrefix middleware prefix list -------------------------------
    middlewares = http["middlewares"]
    assert len(middlewares) == 1, "expected exactly one middleware"
    middleware = next(iter(middlewares.values()))
    assert middleware["stripPrefix"]["prefixes"] == [prefix]

    # The router must reference that strip middleware.
    strip_name = next(iter(middlewares.keys()))
    assert router["middlewares"] == [strip_name]

    # --- Service load-balancer carries the supplied backend port ----------
    services = http["services"]
    assert len(services) == 1, "expected exactly one service"
    service = next(iter(services.values()))
    servers = service["loadBalancer"]["servers"]
    assert len(servers) == 1, "expected exactly one backend server"
    assert servers[0]["url"] == f"http://{backend_host}:{backend_port}"


if __name__ == "__main__":
    test_property_1_complete_prefix_correct_route()
    print("Property 1 (complete prefix-correct route): OK")
