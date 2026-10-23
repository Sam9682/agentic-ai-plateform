#!/usr/bin/env python3
"""Property-based test for secondary-domain router/service mapping.

Feature: nginx-to-traefik-migration, Property 10
Property 10: Each secondary-domain entry maps to exactly one router and backend.
Validates: Requirements 5.1, 5.3

Over well-formed ``SECONDARY_DOMAINS`` lists, each ``domain:server_names:proxy_pass``
entry must yield exactly one router -- whose ``Host(...)`` rule lists that entry's
server names -- and exactly one service whose backend url equals that entry's
``proxy_pass``.

Two complementary angles are covered:

* ``build_secondary_domains_config`` is exercised directly on generated
  ``(domain, [server_names], proxy_pass)`` tuples (the shape
  :func:`parse_secondary_domains` returns), isolating the router/service mapping
  from the string-parsing concern.
* ``parse_secondary_domains`` is exercised on a raw ``SECONDARY_DOMAINS`` string
  constructed from the same generated entries, asserting it round-trips back to
  those entries so the end-to-end ``raw -> config`` path holds the same property.

Router and service names are derived from the (sanitized) domain, so generated
domains are kept distinct after sanitization -- distinct base labels joined to a
fixed suffix -- so router/service names never collide and the one-to-one count
holds.
"""
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from hypothesis import given, settings
from hypothesis import strategies as st

from src.frontend_manager import (
    _secondary_router_name,
    build_secondary_domains_config,
    parse_secondary_domains,
)


# A base label that survives _secondary_router_name sanitization unchanged:
# lowercase alphanumerics only (no dots, no leading/trailing dashes). Distinct
# labels therefore yield distinct domains AND distinct router/service names.
_label = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=1, max_size=12)

# A server_name is a hostname-ish token (lowercase alnum, dots, hyphens). These
# live inside the Host(...) rule, so no ":" or "," which would break the rule
# syntax or the raw-string field delimiters.
_server_name = st.from_regex(r"[a-z0-9]([a-z0-9-]{0,10}\.){0,2}[a-z0-9]{2,6}", fullmatch=True)

# proxy_pass like "https://host:port" -- deliberately contains colons so the
# raw-string path exercises the "only the first two ':' delimit fields" rule.
_host = st.from_regex(r"[a-z0-9][a-z0-9.-]{0,20}[a-z0-9]", fullmatch=True)
_port = st.integers(min_value=1, max_value=65535)
_scheme = st.sampled_from(["http", "https"])


@st.composite
def _entries(draw):
    """Generate a list of well-formed, distinct-domain secondary-domain entries.

    Returns a list of ``(domain, [server_names], proxy_pass)`` tuples -- the
    exact shape :func:`parse_secondary_domains` yields and
    :func:`build_secondary_domains_config` consumes.
    """
    labels = draw(st.lists(_label, min_size=1, max_size=5, unique=True))
    entries = []
    for label in labels:
        domain = f"{label}.example.com"
        server_names = draw(st.lists(_server_name, min_size=1, max_size=3, unique=True))
        scheme = draw(_scheme)
        host = draw(_host)
        port = draw(_port)
        proxy_pass = f"{scheme}://{host}:{port}"
        entries.append((domain, server_names, proxy_pass))
    return entries


def _service_url(config, name):
    return config["http"]["services"][name]["loadBalancer"]["servers"][0]["url"]


@settings(max_examples=200)
@given(entries=_entries())
def test_each_entry_maps_to_exactly_one_router_and_service(entries):
    """One router + one service per entry, with matching Host rule and backend.

    Feature: nginx-to-traefik-migration, Property 10
    Validates: Requirements 5.1, 5.3
    """
    config = build_secondary_domains_config(entries)
    routers = config["http"]["routers"]
    services = config["http"]["services"]

    # Exactly one router and one service per entry (no collisions, no extras).
    assert len(routers) == len(entries)
    assert len(services) == len(entries)

    for domain, server_names, proxy_pass in entries:
        name = _secondary_router_name(domain)

        # Exactly one router and one service keyed by this entry's name.
        assert name in routers
        assert name in services

        rule = routers[name]["rule"]
        # The router rule is a Host(...) over exactly this entry's server names,
        # each wrapped in backticks.
        assert rule.startswith("Host(") and rule.endswith(")")
        for server_name in server_names:
            assert f"`{server_name}`" in rule
        # No server name beyond this entry's leaked into the rule.
        assert rule.count("`") == 2 * len(server_names)

        # The service backend url is exactly this entry's proxy_pass.
        assert _service_url(config, name) == proxy_pass


@settings(max_examples=200)
@given(entries=_entries())
def test_parse_then_build_preserves_the_mapping(entries):
    """raw SECONDARY_DOMAINS string -> parse -> build holds the same mapping.

    Feature: nginx-to-traefik-migration, Property 10
    Validates: Requirements 5.1, 5.3

    Build the raw string by joining ``domain:server_names:proxy_pass`` (server
    names space-joined) with ``,`` between entries, then assert
    ``parse_secondary_domains`` round-trips it back to the generated entries and
    the resulting config carries the same one-router/one-service mapping.
    """
    raw = ",".join(
        f"{domain}:{' '.join(server_names)}:{proxy_pass}"
        for domain, server_names, proxy_pass in entries
    )

    parsed = parse_secondary_domains(raw)

    # The raw string round-trips back to the generated entries (tuples compare
    # equal: domain str, server_names list, proxy_pass str).
    assert parsed == entries

    config = build_secondary_domains_config(parsed)
    routers = config["http"]["routers"]
    services = config["http"]["services"]

    assert len(routers) == len(entries)
    assert len(services) == len(entries)

    for domain, server_names, proxy_pass in entries:
        name = _secondary_router_name(domain)
        assert name in routers
        assert name in services
        rule = routers[name]["rule"]
        for server_name in server_names:
            assert f"`{server_name}`" in rule
        assert _service_url(config, name) == proxy_pass


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
