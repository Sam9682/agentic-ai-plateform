#!/usr/bin/env python3
"""Test script for Traefik dynamic route management (Proxy_Manager).

Exercises the preserved public entry points ``insert_location_block`` /
``remove_location_block`` plus the pure route builder ``_build_route_config``,
asserting the generated Traefik dynamic config (not retired nginx output).

Runnable both as a plain script (``python3 scripts/test_nginx_locations.py``)
and under pytest (``pytest scripts/test_nginx_locations.py``).
"""
import sys
import os
import tempfile

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import nginx_manager
from src.nginx_manager import (
    insert_location_block,
    remove_location_block,
    _build_route_config,
    _route_file_path,
    TRAEFIK_DYNAMIC_DIR,  # noqa: F401 - imported to prove the symbol still exists
)

# Explicit public domain so the assertions do not depend on deploy.ini.
DOMAIN = "www.swautomorph.com"


def test_generate_location():
    """Traefik route generation produces a prefix-correct router/service."""
    print("Testing Traefik route generation...")

    config = _build_route_config(
        "admin", "ai-hypervisia", "admin-ai-hypervisia", 5000, DOMAIN
    )
    dumped = yaml.safe_dump(config, default_flow_style=False, sort_keys=False)

    http = config["http"]
    router = http["routers"]["admin-ai-hypervisia"]
    middleware = http["middlewares"]["admin-ai-hypervisia-strip"]
    service = http["services"]["admin-ai-hypervisia"]

    # Router rule: Host(<domain>) && PathPrefix(`/admin/ai-hypervisia`) (Property 1)
    assert router["rule"] == f"Host(`{DOMAIN}`) && PathPrefix(`/admin/ai-hypervisia`)"
    assert "Host(`" + DOMAIN + "`) && PathPrefix(`/admin/ai-hypervisia`)" in dumped

    # StripPrefix middleware with exactly the prefix /admin/ai-hypervisia (Property 2)
    assert middleware["stripPrefix"]["prefixes"] == ["/admin/ai-hypervisia"]

    # Backend service points at the supplied port 5000 (Property 1)
    servers = service["loadBalancer"]["servers"]
    assert servers == [{"url": "http://admin-ai-hypervisia:5000"}]

    # No nginx directives anywhere in the generated config (Property 4)
    assert "proxy_pass" not in dumped
    assert "sub_filter" not in dumped
    assert "location" not in dumped

    print("✓ Traefik route generation works")
    print(dumped)


def test_insert_location():
    """Inserting a route writes the per-app dynamic file with the router."""
    print("\nTesting Traefik route insertion...")

    url = f"https://{DOMAIN}:6217"
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Point the module's dynamic dir at a temp directory for the test.
        original_dir = nginx_manager.TRAEFIK_DYNAMIC_DIR
        nginx_manager.TRAEFIK_DYNAMIC_DIR = tmp_dir
        try:
            result = insert_location_block("admin", "ai-hypervisia", url, url)
            assert result, "insert_location_block should report success"

            route_file = nginx_manager._route_file_path("admin", "ai-hypervisia")
            assert os.path.exists(route_file), f"route file missing: {route_file}"

            with open(route_file, "r", encoding="utf-8") as f:
                contents = f.read()
            config = yaml.safe_load(contents)

            # The written file carries the per-app router. (Property 6)
            assert "admin-ai-hypervisia" in config["http"]["routers"]
            assert "PathPrefix(`/admin/ai-hypervisia`)" in contents
            assert "proxy_pass" not in contents

            print("✓ Traefik route inserted and dynamic file written")
            print(contents)
        finally:
            nginx_manager.TRAEFIK_DYNAMIC_DIR = original_dir


def test_remove_location():
    """Removing a route deletes the per-app dynamic file."""
    print("\nTesting Traefik route removal...")

    url = f"https://{DOMAIN}:6217"
    with tempfile.TemporaryDirectory() as tmp_dir:
        original_dir = nginx_manager.TRAEFIK_DYNAMIC_DIR
        nginx_manager.TRAEFIK_DYNAMIC_DIR = tmp_dir
        try:
            # Seed a route to remove.
            assert insert_location_block("admin", "ai-hypervisia", url, url)
            route_file = nginx_manager._route_file_path("admin", "ai-hypervisia")
            assert os.path.exists(route_file)

            result = remove_location_block("admin", "ai-hypervisia")
            assert result, "remove_location_block should report success"
            assert not os.path.exists(route_file), "route file should be gone"

            print("✓ Traefik route removed and dynamic file deleted")
        finally:
            nginx_manager.TRAEFIK_DYNAMIC_DIR = original_dir


def main():
    print("=== Traefik Dynamic Route Tests ===\n")

    try:
        test_generate_location()
        test_insert_location()
        test_remove_location()

        print("\n=== All tests completed ===")
        return 0

    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
