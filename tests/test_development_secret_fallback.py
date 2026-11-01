#!/usr/bin/env python3
"""Property-based test for development-mode secret fallback.

Feature: phase1-foundation-consolidation, Property 4 -- "Development-mode secret
fallback". Validates Requirements 5.1, 5.2: WHILE the Platform is in
Development_Mode (``FLASK_ENV == 'development'``), THE App_Config SHALL retain
the existing fallback value for ``POSTGRES_PASSWORD`` / ``SECRET_KEY`` when the
environment variable is unset.

The unit under test is the pure helper ``src.config_postgres.require_secret``.
In development, ``require_secret(name, dev_fallback)`` returns
``os.environ[name]`` if the var is set, else ``dev_fallback``, and never raises.

ENVIRONMENT ISOLATION
---------------------
This test manipulates ``FLASK_ENV`` and the secret env vars. ``tests/conftest.py``
sets ``FLASK_ENV=development`` for the whole process and other tests depend on
that. Every example therefore runs inside ``mock.patch.dict(os.environ, ...)``,
which snapshots the environment on enter and restores it verbatim on exit --
so the global ``FLASK_ENV=development`` and any real secret vars are never
clobbered for sibling tests. We force ``FLASK_ENV='development'`` inside the
patch and *remove* the secret var within the patched copy (via ``pop``) to model
the "unset" case, without ever touching the real process environment.
"""
import os
import sys
from unittest import mock

from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src.config_postgres import require_secret  # noqa: E402

# The two secrets named by Property 4, paired with their real production
# defaults as applied in src/config_postgres.py (used here only as fallbacks).
_REAL_DEFAULTS = {
    "POSTGRES_PASSWORD": "swautomorph_password",
    "SECRET_KEY": "dev-secret-key-change-in-production",
}

# Secret name sampled from the exact set the property covers.
_secret_names = st.sampled_from(sorted(_REAL_DEFAULTS))

# Arbitrary non-empty fallback text, plus the real defaults, so the property
# holds for both the shipped fallbacks and any other caller-supplied fallback.
_fallbacks = st.one_of(
    st.sampled_from(sorted(_REAL_DEFAULTS.values())),
    st.text(min_size=1, max_size=40),
)


@settings(max_examples=200)
@given(name=_secret_names, dev_fallback=_fallbacks)
def test_dev_fallback_when_unset_returns_fallback_and_never_raises(name, dev_fallback):
    """Feature: phase1-foundation-consolidation, Property 4.

    In development with the secret var UNSET, ``require_secret`` returns the
    supplied fallback and raises nothing. Validates: Requirements 5.1, 5.2.
    """
    # Patched copy of the environment: dev mode on, secret var removed.
    # patch.dict restores the real os.environ on exit, so no leakage.
    with mock.patch.dict(os.environ, {"FLASK_ENV": "development"}, clear=False):
        os.environ.pop(name, None)  # removal is confined to the patched dict
        assert name not in os.environ  # precondition: the var is unset

        result = require_secret(name, dev_fallback)  # must not raise

        assert result == dev_fallback

    # After the context exits, the real environment is restored untouched.
    assert os.environ.get("FLASK_ENV") == "development"


@settings(max_examples=200)
@given(
    name=_secret_names,
    dev_fallback=_fallbacks,
    # OS environment values cannot contain null bytes (os.environ rejects them
    # with ValueError), so exclude \x00 from the generated set value -- it is a
    # constraint of the input space, not of the unit under test.
    set_value=st.text(
        alphabet=st.characters(blacklist_characters="\x00"), min_size=0, max_size=40
    ),
)
def test_dev_returns_set_value_over_fallback_and_never_raises(name, dev_fallback, set_value):
    """Feature: phase1-foundation-consolidation, Property 4.

    Strengthening case: in development with the secret var SET, ``require_secret``
    returns the set value (including the empty string) in preference to the
    fallback, and still never raises. Validates: Requirements 5.1, 5.2.
    """
    with mock.patch.dict(
        os.environ, {"FLASK_ENV": "development", name: set_value}, clear=False
    ):
        result = require_secret(name, dev_fallback)  # must not raise

        assert result == set_value

    assert os.environ.get("FLASK_ENV") == "development"
