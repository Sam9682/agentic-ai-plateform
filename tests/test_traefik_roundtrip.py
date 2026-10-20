#!/usr/bin/env python3
"""Property test for the insert/remove round-trip on Traefik route files.

Feature: nginx-to-traefik-migration, Property 6
Property 6: Insert then remove is an identity on the route set (round-trip).
Validates: Requirements 8.2, 8.3

Against a temporary dynamic directory, for any ``user_name``/``app_name`` and a
valid ``user_appli_url`` (host + port), calling
``src.nginx_manager.insert_location_block`` followed by
``src.nginx_manager.remove_location_block`` must leave the set of route files
identical to the pre-insert state, and both calls must report success.

The module-level ``TRAEFIK_DYNAMIC_DIR`` is redirected to a fresh temporary
directory per example. ``_route_file_path`` reads that module global at call
time, so setting ``nginx_manager.TRAEFIK_DYNAMIC_DIR`` is sufficient to redirect
every filesystem write/delete performed by insert/remove.
"""
import os
import sys
import tempfile

from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src import nginx_manager  # noqa: E402

# DNS-label-ish fragments for user/app names: lowercase alnum + hyphen.
_NAME = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789-", min_size=1, max_size=20
)
# Valid port range. ``_backend_http_port`` computes ``port - 1`` from the stored
# HTTPS port, so keep the minimum at 2 to stay within a valid backend port.
_PORT = st.integers(min_value=2, max_value=65535)


def _dir_file_set(path):
    """Return the set of entry names currently present in ``path``."""
    return set(os.listdir(path))


@settings(max_examples=200)
@given(user_name=_NAME, app_name=_NAME, port=_PORT)
def test_insert_then_remove_is_identity_on_route_set(user_name, app_name, port):
    """Feature: nginx-to-traefik-migration, Property 6.

    Validates: Requirements 8.2, 8.3
    """
    url = f"https://{user_name}-{app_name}:{port}"

    original_dir = nginx_manager.TRAEFIK_DYNAMIC_DIR
    tmp_dir = tempfile.mkdtemp(prefix="traefik-roundtrip-")
    nginx_manager.TRAEFIK_DYNAMIC_DIR = tmp_dir
    try:
        # Pre-insert state of the dynamic directory.
        before = _dir_file_set(tmp_dir)

        # Insert must succeed and create exactly the per-app route file.
        inserted = nginx_manager.insert_location_block(
            user_name, app_name, url, url
        )
        assert inserted is True, "insert_location_block should return True"

        after_insert = _dir_file_set(tmp_dir)
        expected_file = f"app-{user_name}-{app_name}.yml"
        assert expected_file in after_insert, (
            f"expected route file {expected_file!r} after insert, "
            f"dir has {sorted(after_insert)}"
        )

        # Remove must succeed and restore the original route set exactly.
        removed = nginx_manager.remove_location_block(user_name, app_name)
        assert removed is True, "remove_location_block should return True"

        after_remove = _dir_file_set(tmp_dir)
        assert after_remove == before, (
            "insert+remove should be an identity on the route set: "
            f"before={sorted(before)} after={sorted(after_remove)}"
        )
    finally:
        nginx_manager.TRAEFIK_DYNAMIC_DIR = original_dir
        # Best-effort cleanup of the temporary directory.
        for name in os.listdir(tmp_dir):
            try:
                os.remove(os.path.join(tmp_dir, name))
            except OSError:
                pass
        try:
            os.rmdir(tmp_dir)
        except OSError:
            pass


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
