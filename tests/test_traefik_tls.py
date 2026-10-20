#!/usr/bin/env python3
"""Property test for TLS certificate references in the generated Traefik config.

Feature: nginx-to-traefik-migration, Property 9
Property 9: TLS config references the existing certificate files for every domain.
Validates: Requirements 4.1

Over generated configured-domain sets (lists of hostname-ish domain names), the
dict produced by ``src.nginx_manager.build_tls_config`` must contain exactly one
``tls.certificates`` entry per *unique* domain (duplicates collapsed, first-seen
order preserved), each entry referencing that domain's existing certificate pair
inside the Traefik container
(``/etc/traefik/ssl/<domain>/fullchain_domain.crt`` and
``/etc/traefik/ssl/<domain>/privateKey_domain.key``), plus an empty default
store (``tls.stores.default == {}``).
"""
import os
import sys

from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src.nginx_manager import build_tls_config, TRAEFIK_SSL_DIR  # noqa: E402

# A single DNS label: lowercase alnum + hyphen, non-empty.
_LABEL = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789-", min_size=1, max_size=15
)
# A hostname-ish domain: one or more labels joined by dots (e.g. "example.fr").
_DOMAIN = st.lists(_LABEL, min_size=1, max_size=4).map(".".join)
# A list of configured domains (may contain duplicates, which must be collapsed).
_DOMAIN_LIST = st.lists(_DOMAIN, min_size=0, max_size=12)


def _first_seen_unique(domains):
    """Return the domains with duplicates removed, preserving first-seen order."""
    ordered = []
    for d in domains:
        if d and d not in ordered:
            ordered.append(d)
    return ordered


@settings(max_examples=200)
@given(domains=_DOMAIN_LIST)
def test_tls_config_references_certificate_files_per_domain(domains):
    """Feature: nginx-to-traefik-migration, Property 9.

    Validates: Requirements 4.1
    """
    config = build_tls_config(domains)

    # The top-level shape: tls.certificates (list) and tls.stores.default == {}.
    tls = config["tls"]
    certificates = tls["certificates"]
    assert isinstance(certificates, list)
    assert tls["stores"]["default"] == {}

    expected_domains = _first_seen_unique(domains)

    # Exactly one certificate entry per unique domain, no more, no fewer.
    assert len(certificates) == len(expected_domains), (
        f"expected {len(expected_domains)} certificate entries "
        f"(unique domains {expected_domains}), got {len(certificates)}"
    )

    # Each entry references the expected certFile/keyFile for its domain, and the
    # entries appear in first-seen order.
    for domain, cert in zip(expected_domains, certificates):
        assert cert["certFile"] == f"{TRAEFIK_SSL_DIR}/{domain}/fullchain_domain.crt", (
            f"certFile mismatch for {domain!r}: {cert.get('certFile')!r}"
        )
        assert cert["keyFile"] == f"{TRAEFIK_SSL_DIR}/{domain}/privateKey_domain.key", (
            f"keyFile mismatch for {domain!r}: {cert.get('keyFile')!r}"
        )


@settings(max_examples=200)
@given(domain=_DOMAIN, extra=_DOMAIN_LIST)
def test_duplicate_domains_collapse_to_single_entry(domain, extra):
    """Feature: nginx-to-traefik-migration, Property 9.

    Validates: Requirements 4.1

    A domain repeated any number of times yields exactly one certificate entry,
    and interleaving it with other domains preserves first-seen order.
    """
    # Build a list where ``domain`` appears multiple times, interleaved with
    # other generated domains.
    domains = [domain] + extra + [domain] + extra + [domain]
    config = build_tls_config(domains)
    certificates = config["tls"]["certificates"]

    expected_domains = _first_seen_unique(domains)
    assert len(certificates) == len(expected_domains)

    # The repeated domain appears exactly once among the cert entries.
    cert_files = [c["certFile"] for c in certificates]
    target = f"{TRAEFIK_SSL_DIR}/{domain}/fullchain_domain.crt"
    assert cert_files.count(target) == 1, (
        f"domain {domain!r} should collapse to exactly one entry, "
        f"found {cert_files.count(target)}"
    )

    # Order is preserved: the cert entries line up with first-seen unique order.
    assert cert_files == [
        f"{TRAEFIK_SSL_DIR}/{d}/fullchain_domain.crt" for d in expected_domains
    ]


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
