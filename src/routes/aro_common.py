"""Shared helpers for the ARO/ZAF/OBS blueprints.

Centralizes the small bits every new blueprint needs: the EN/FR ``get_text``
resolver (mirrors ``agent_control_routes.py``) and a JSON body parser. Auth and
tenant scoping are provided by :mod:`src.authz` decorators; routes read the
resolved tenant from ``flask.g.tenant_id``.
"""

from __future__ import annotations

from typing import Any, Dict

from flask import request, session

from ..config_postgres import TRANSLATIONS


def get_language() -> str:
    return session.get("language", "en")


def get_text(key: str) -> str:
    """Resolve a message key for the active language, English fallback."""
    try:
        lang = get_language()
        return TRANSLATIONS.get(lang, {}).get(key, TRANSLATIONS["en"].get(key, key))
    except (KeyError, AttributeError, TypeError):
        return key


def json_body() -> Dict[str, Any]:
    """Return the request JSON body as a dict (empty dict when absent/invalid)."""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}
