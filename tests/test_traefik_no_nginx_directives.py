#!/usr/bin/env python3
"""Property test — Property 4: Generated routing contains no nginx directives.

Feature: nginx-to-traefik-migration, Property 4
Validates: Requirements 2.3, 3.4

For any valid deploy input (user_name, app_name, backend_host, backend_port,
domain), the Traefik dynamic-config produced by
``src.frontend_manager._build_route_config`` — once serialized to YAML with
``yaml.safe_dump`` — must contain NONE of the nginx-specific constructs the
migration retires: nginx ``location`` blocks, ``proxy_pass``, ``sub_filter``
response-body rewriting, and the surrounding nginx proxy directives.

Matching-choice note
--------------------
The three tokens called out by the design (``location``, ``proxy_pass``,
``sub_filter``) differ in how safely they can be matched as bare substrings:

* ``proxy_pass`` and ``sub_filter`` are unambiguous — they never appear as a
  substring of any legitimate Traefik key or value (the generated config uses
  ``loadBalancer``, ``stripPrefix``, ``servers``, ``serversTransport``, ...).
  We therefore assert their plain-substring absence (case-insensitive).

* ``location`` is NOT safe as a bare substring: the Traefik token
  ``loadBalancer`` and the English word in a comment could both contain the
  letters ``location``/``lb...`` — and more importantly we must not flag a
  value just because it embeds those letters. nginx only ever writes the word
  as a *directive* that opens a block: ``location <path> {`` (and the
  reload/sync code emits exactly ``location / {`` and
  ``location /{user}/{app}/ {``). So for ``location`` we assert the absence of
  the nginx directive form — the word ``location`` followed by whitespace and
  then a path/brace — using a word-boundary regex, rather than the bare
  substring. This avoids false positives on Traefik's ``loadBalancer`` key
  (verified explicitly in ``test_loadbalancer_token_is_not_flagged``).

We additionally assert the absence of the other nginx proxy/rewrite directives
the old ``generate_location_block`` emitted (``proxy_redirect``,
``proxy_set_header``, ``proxy_http_version``, ``proxy_connect_timeout``,
``proxy_read_timeout``, ``proxy_send_timeout``, ``sub_filter_once``,
``sub_filter_types``) so "no response-body rewrite directive" (Req 3.4) is
covered concretely, not just by the ``sub_filter`` prefix.
"""
import os
import re
import sys

import yaml
from hypothesis import given, settings, strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src.frontend_manager import _build_route_config  # noqa: E402


# --- Generators -----------------------------------------------------------
# user/app names use the DNS/label-safe alphabet [a-z0-9-] the platform uses
# for user and application identifiers.
_DNS_LABEL = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-", min_size=1, max_size=24)
# backend host: a hostname-ish label (the compose network alias).
_HOST = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-.", min_size=1, max_size=40)
# domain: a dotted hostname.
_DOMAIN = st.builds(
    lambda a, b: f"{a}.{b}",
    st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-", min_size=1, max_size=20),
    st.sampled_from(["fr", "com", "net", "io", "org"]),
)
_PORT = st.integers(min_value=1, max_value=65535)


# --- nginx tokens we must never emit --------------------------------------
# Unambiguous substrings (safe to match anywhere, case-insensitive).
_UNAMBIGUOUS_NGINX_TOKENS = [
    "proxy_pass",
    "sub_filter",          # also covers sub_filter_once / sub_filter_types
    "proxy_redirect",
    "proxy_set_header",
    "proxy_http_version",
    "proxy_connect_timeout",
    "proxy_read_timeout",
    "proxy_send_timeout",
]

# The nginx ``location`` *directive* form: the word `location`, then
# whitespace, then a path or an opening brace. Matched case-insensitively with
# word boundaries so Traefik's ``loadBalancer`` key is never flagged.
_NGINX_LOCATION_DIRECTIVE = re.compile(r"\blocation\s+[/{]", re.IGNORECASE)


def _assert_no_nginx_directives(serialized: str) -> None:
    low = serialized.lower()
    for token in _UNAMBIGUOUS_NGINX_TOKENS:
        assert token not in low, f"generated config leaked nginx directive {token!r}"
    assert not _NGINX_LOCATION_DIRECTIVE.search(serialized), (
        "generated config leaked an nginx `location ...` block directive"
    )


# --- Property 4 -----------------------------------------------------------
@settings(max_examples=200)
@given(
    user_name=_DNS_LABEL,
    app_name=_DNS_LABEL,
    backend_host=_HOST,
    backend_port=_PORT,
    domain=_DOMAIN,
)
def test_generated_routing_has_no_nginx_directives(
    user_name, app_name, backend_host, backend_port, domain
):
    """Feature: nginx-to-traefik-migration, Property 4.

    Validates: Requirements 2.3, 3.4.
    """
    config = _build_route_config(user_name, app_name, backend_host, backend_port, domain)
    serialized = yaml.safe_dump(config, default_flow_style=False, sort_keys=False)
    _assert_no_nginx_directives(serialized)


def test_loadbalancer_token_is_not_flagged():
    """Guard the matching choice: the Traefik ``loadBalancer`` key (which
    contains the letters of ``location`` nowhere, but is the obvious near-miss)
    and ``stripPrefix`` must NOT trip the nginx-directive assertions."""
    config = _build_route_config("admin", "ai-hypervisia", "admin-ai-hypervisia", 5000, "softfluid.fr")
    serialized = yaml.safe_dump(config, default_flow_style=False, sort_keys=False)
    # Sanity: the real Traefik tokens are present ...
    assert "loadBalancer" in serialized
    assert "stripPrefix" in serialized
    # ... and the nginx-directive assertions still pass.
    _assert_no_nginx_directives(serialized)


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
