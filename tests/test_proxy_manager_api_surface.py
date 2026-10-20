#!/usr/bin/env python3
"""Example tests for the preserved Proxy_Manager public API surface.

Feature: nginx-to-traefik-migration
Validates: Requirements 8.1

These are example (non-property) tests asserting that the Proxy_Manager keeps
the exact import path and call signatures that existing callers rely on. The
migration replaced the nginx implementation with Traefik, but the public
contract (``insert_location_block``, ``remove_location_block``,
``sync_all_locations``) must remain unchanged so deploy, rollback, teardown,
and sync code paths continue to function without rewriting their callers.

Run directly:
    python3 tests/test_proxy_manager_api_surface.py
Or via pytest:
    pytest tests/test_proxy_manager_api_surface.py
"""
import inspect
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# The functions must be importable via this exact path/names (Req 8.1).
from src.nginx_manager import (
    insert_location_block,
    remove_location_block,
    sync_all_locations,
)


def test_functions_are_importable_and_callable():
    """All three Proxy_Manager entry points import and are callables.

    Validates: Requirements 8.1
    """
    assert callable(insert_location_block)
    assert callable(remove_location_block)
    assert callable(sync_all_locations)


def test_insert_location_block_signature():
    """``insert_location_block`` keeps its 4 positional parameters.

    Validates: Requirements 8.1
    """
    params = list(inspect.signature(insert_location_block).parameters.values())
    names = [p.name for p in params]
    assert names == ["user_name", "app_name", "deployment_url", "user_appli_url"]
    assert len(params) == 4
    for p in params:
        assert p.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )


def test_remove_location_block_signature():
    """``remove_location_block`` keeps its 2 positional parameters.

    Validates: Requirements 8.1
    """
    params = list(inspect.signature(remove_location_block).parameters.values())
    names = [p.name for p in params]
    assert names == ["user_name", "app_name"]
    assert len(params) == 2
    for p in params:
        assert p.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )


def test_sync_all_locations_signature():
    """``sync_all_locations`` keeps its single positional parameter.

    Validates: Requirements 8.1
    """
    params = list(inspect.signature(sync_all_locations).parameters.values())
    names = [p.name for p in params]
    assert names == ["db_manager"]
    assert len(params) == 1
    assert params[0].kind in (
        inspect.Parameter.POSITIONAL_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    )


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
