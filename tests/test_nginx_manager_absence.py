#!/usr/bin/env python3
"""Smoke test for reverse-proxy consolidation: nginx manager retired.

Feature: phase1-foundation-consolidation, task 2.4.

Asserts the structural invariant that the obsolete nginx-based reverse-proxy
manager has been removed and the retained Traefik-based manager remains present
as the sole reverse-proxy manager.

**Validates: Requirements 3.1, 3.2**

Run directly:
    python3 tests/test_nginx_manager_absence.py
Or via pytest:
    pytest tests/test_nginx_manager_absence.py
"""
import os
import sys

# Repo root is the parent of the tests/ directory holding this file (same
# technique used by the other tests in this directory).
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_nginx_manager_is_absent():
    """Requirement 3.2: src/frontend_nginx_manager.py no longer exists."""
    nginx_manager = os.path.join(PROJECT_ROOT, "src", "frontend_nginx_manager.py")
    assert not os.path.exists(nginx_manager), (
        "src/frontend_nginx_manager.py should be retired but still exists"
    )


def test_traefik_manager_is_present():
    """Requirement 3.1: src/frontend_manager.py is the sole reverse proxy."""
    traefik_manager = os.path.join(PROJECT_ROOT, "src", "frontend_manager.py")
    assert os.path.exists(traefik_manager), (
        "src/frontend_manager.py (Traefik) should remain as the sole "
        "reverse-proxy manager"
    )


if __name__ == "__main__":
    # Allow running as a plain script (outside pytest) for quick checks.
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
