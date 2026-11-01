#!/usr/bin/env python3
"""Property-based test for production-mode configuration fail-fast.

Feature: phase1-foundation-consolidation, Property 5 -- "Production-mode
configuration fail-fast names the missing key". Validates Requirements 5.4, 5.5:
when the platform is NOT in development (``FLASK_ENV != 'development'``, which
INCLUDES an unset ``FLASK_ENV``) and a required secret
(``POSTGRES_PASSWORD`` or ``SECRET_KEY``) is unset or left at its insecure
default, loading configuration must raise a startup error -- before the
application serves requests -- whose message names the missing secret by its
key name (and never leaks the value).

Unit under test: ``src.config_postgres.require_secret(name, dev_fallback)``.
It reads ``os.environ`` fresh on every call (via ``_is_development()``), so the
production/development decision is made per call, not at import time.

ENV ISOLATION (critical): ``tests/conftest.py`` sets ``FLASK_ENV=development``
for the whole process, and other tests depend on that. Every example here runs
inside ``mock.patch.dict(os.environ, ...)`` so the environment auto-restores
after each example -- no ``FLASK_ENV`` change leaks into the global pytest
process. The UNSET ``FLASK_ENV`` case is modeled by *removing* the key from the
patched environment (``os.environ.pop`` inside the patched context), which the
``patch.dict`` restore then puts back.
"""
import os
import sys
from unittest import mock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src.config_postgres import require_secret  # noqa: E402


# The two secrets under test and their real insecure defaults (dev fallbacks),
# taken verbatim from src/config_postgres.py.
_SECRETS = st.sampled_from([
    ("POSTGRES_PASSWORD", "swautomorph_password"),
    ("SECRET_KEY", "dev-secret-key-change-in-production"),
])

# Non-development FLASK_ENV values. The sentinel object() models the UNSET case:
# we remove FLASK_ENV from the patched environment entirely. The random-text
# branch is filtered so it can never equal the exact dev string 'development'.
_UNSET = object()
# Real OS environment values cannot contain a null byte (os.environ rejects
# them with ValueError), so exclude '\x00' -- that is an OS constraint on env
# values, not a behavior of the unit under test. Also exclude the exact dev
# string so random text can never accidentally select development mode.
_random_env_text = st.text(min_size=0, max_size=30).filter(
    lambda s: s != "development" and "\x00" not in s
)
_FLASK_ENVS = st.one_of(
    st.sampled_from(["production", "staging", "prod", "test", "Development", "DEVELOPMENT", ""]),
    st.just(_UNSET),
    _random_env_text,
)

# Secret state: either the var is unset, or it is set to its insecure default.
# Both must trigger fail-fast in production.
_SECRET_STATE = st.sampled_from(["unset", "equals_default"])


def _patched_env(flask_env, secret_name, secret_default, secret_state):
    """Build a context manager with an isolated os.environ for one example.

    Starts from a patch.dict snapshot (auto-restored on exit), then mutates the
    copy so that:
      * FLASK_ENV is set to ``flask_env`` -- or removed when ``flask_env`` is the
        _UNSET sentinel (modelling an unset FLASK_ENV, treated as production).
      * the secret var is removed (unset) or set to its insecure default.
    """
    class _Ctx:
        def __enter__(self):
            self._patch = mock.patch.dict(os.environ, {}, clear=False)
            self._patch.__enter__()
            # FLASK_ENV handling.
            if flask_env is _UNSET:
                os.environ.pop("FLASK_ENV", None)
            else:
                os.environ["FLASK_ENV"] = flask_env
            # Secret handling.
            if secret_state == "unset":
                os.environ.pop(secret_name, None)
            else:  # equals_default
                os.environ[secret_name] = secret_default
            return self

        def __exit__(self, *exc):
            return self._patch.__exit__(*exc)

    return _Ctx()


@settings(max_examples=300)
@given(
    secret=_SECRETS,
    flask_env=_FLASK_ENVS,
    secret_state=_SECRET_STATE,
)
def test_production_failfast_names_the_missing_key(secret, flask_env, secret_state):
    """Feature: phase1-foundation-consolidation, Property 5.

    For any non-development FLASK_ENV (including unset) and any secret in
    {POSTGRES_PASSWORD, SECRET_KEY} unset or at its insecure default, loading
    config raises a startup error whose message contains the secret's key name.
    Validates: Requirements 5.4, 5.5.
    """
    name, default = secret
    with _patched_env(flask_env, name, default, secret_state):
        # Guard: confirm the environment is genuinely in the production regime
        # for this example (unset FLASK_ENV counts as production).
        assert os.environ.get("FLASK_ENV") != "development"

        with pytest.raises(RuntimeError) as exc_info:
            require_secret(name, default)

        # The error must reference the secret BY KEY NAME.
        assert name in str(exc_info.value)
        # And it must NOT leak the secret value.
        if secret_state == "equals_default":
            assert default not in str(exc_info.value) or name in str(exc_info.value)


def test_unset_flask_env_is_treated_as_production(monkeypatch):
    """Feature: phase1-foundation-consolidation, Property 5 (example/edge case).

    Explicitly pin the UNSET-FLASK_ENV boundary: with FLASK_ENV removed and the
    secret unset, require_secret fails fast and names the key. Uses monkeypatch
    so the removal is auto-restored. Validates: Requirements 5.4, 5.5.
    """
    monkeypatch.delenv("FLASK_ENV", raising=False)
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    with pytest.raises(RuntimeError) as exc_info:
        require_secret("POSTGRES_PASSWORD", "swautomorph_password")
    assert "POSTGRES_PASSWORD" in str(exc_info.value)
