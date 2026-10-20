#!/usr/bin/env python3
"""Property-based test for Traefik StripPrefix de-prefixing.

Feature: nginx-to-traefik-migration, Property 2
Property 2: StripPrefix forwards the de-prefixed path.
Validates: Requirements 3.1

``_build_route_config`` is pure config generation, so we assert on the
``stripPrefix.prefixes`` value the generated middleware declares: it must be
exactly ``["/{user}/{app}"]`` -- the prefix Traefik strips so that a request to
``/{user}/{app}/{suffix}`` is forwarded de-prefixed as ``/{suffix}``.
"""
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from hypothesis import given, settings
from hypothesis import strategies as st

from src.nginx_manager import _build_route_config, _prefix_path, _router_name


# user/app are DNS/label-safe identifiers: lowercase alphanumerics and hyphens.
_names = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-", min_size=1, max_size=20)

# A path-safe request suffix: a sequence of slash-separated path-safe segments.
_segment = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789-_.", min_size=1, max_size=15
)
_suffix = st.lists(_segment, min_size=1, max_size=4).map("/".join)


def _strip_prefix_middleware(config, user_name, app_name):
    """Return the stripPrefix block for the generated app's middleware."""
    middlewares = config["http"]["middlewares"]
    strip_name = f"{_router_name(user_name, app_name)}-strip"
    return middlewares[strip_name]["stripPrefix"]


@settings(max_examples=200)
@given(user_name=_names, app_name=_names, suffix=_suffix)
def test_strip_prefix_declares_exact_user_app_prefix(user_name, app_name, suffix):
    """The middleware strips exactly ``/{user}/{app}`` (Property 2).

    Feature: nginx-to-traefik-migration, Property 2
    Validates: Requirements 3.1
    """
    config = _build_route_config(
        user_name, app_name, backend_host="backend", backend_port=8080,
        domain="example.com",
    )

    expected_prefix = _prefix_path(user_name, app_name)
    assert expected_prefix == f"/{user_name}/{app_name}"

    strip = _strip_prefix_middleware(config, user_name, app_name)

    # The middleware declares exactly one prefix: /{user}/{app}.
    assert strip["prefixes"] == [expected_prefix]


@settings(max_examples=200)
@given(user_name=_names, app_name=_names, suffix=_suffix)
def test_strip_prefix_forwards_deprefixed_path(user_name, app_name, suffix):
    """Removing the declared prefix de-prefixes the request to ``/{suffix}``.

    Feature: nginx-to-traefik-migration, Property 2
    Validates: Requirements 3.1

    Traefik's StripPrefix removes the matched prefix from the request path.
    Model that transformation here: an incoming ``/{user}/{app}/{suffix}`` must
    forward as ``/{suffix}`` once the declared prefix is removed.
    """
    config = _build_route_config(
        user_name, app_name, backend_host="backend", backend_port=8080,
        domain="example.com",
    )

    prefix = _strip_prefix_middleware(config, user_name, app_name)["prefixes"][0]

    incoming = f"/{user_name}/{app_name}/{suffix}"
    assert incoming.startswith(prefix)

    forwarded = incoming[len(prefix):]
    assert forwarded == f"/{suffix}"


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
