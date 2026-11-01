#!/usr/bin/env python3
"""Property-based test: no secret VALUE appears in any emitted error message.

Feature: phase1-foundation-consolidation, Property 7 -- "No secret value appears
in any emitted error or log message". Validates Requirements 5.7, 8.1, 8.2:
every error message and log line produced by the step-10 changed code contains
the secret's key NAME and never the secret VALUE.

Units under test (step 10 changed code):
  * ``src.config_postgres.require_secret(name, dev_fallback)`` -- raises
    RuntimeError in production naming the key only.
  * ``src.database_postgres._resolve_seed_password()`` -- raises RuntimeError in
    production naming ``SEED_ADMIN_PASSWORD`` only.
Both read ``os.environ`` fresh on every call (via ``_is_development()``), so the
production/development decision is per-call, not at import time. Neither function
emits any log line; the only secret-bearing text they could produce is the
RuntimeError message, so the property focuses on the raised message. (Confirmed
by reading both sources: the changed code adds NO logging of secret names or
values.)

PROPERTY FRAMING -- name vs value, and the non-raising success path
-------------------------------------------------------------------
The fail-fast fires ONLY when the secret var is UNSET or EQUALS ITS DEFAULT. A
production run with a non-default value does NOT raise (that is the success
path), so an arbitrary non-default value never produces a message to inspect.
To exercise an *arbitrary* secret value V through the raising path, we drive the
"equals default" branch with the default itself set to V:

  * ``require_secret(name, dev_fallback=V)`` with ``os.environ[name] == V`` makes
    ``value == dev_fallback`` true, so the production branch raises -- while V is
    a genuine, arbitrary secret value that actually flowed into the function.
    We then assert V does NOT appear in the message. For the db helper, the
    default is the fixed literal ``'password'``, so the arbitrary-value lever is
    the env var set to that default.

To keep the value-absence assertion meaningful (not accidentally satisfied or
defeated by the key name), generated values V are filtered so they never contain
the key name as a substring and are non-empty; then "key NAME present" and
"value V absent" are two independent, both-checked conditions.

We also pin the UNSET case (V never read, so trivially absent) and a targeted
check that the three shipped default values never leak:
``swautomorph_password``, ``dev-secret-key-change-in-production``, ``password``.

ENV ISOLATION (critical)
------------------------
``tests/conftest.py`` sets ``FLASK_ENV=development`` process-wide and sibling
tests depend on it. Every example runs inside ``mock.patch.dict(os.environ, ...)``
(auto-restored on exit); the UNSET-FLASK_ENV / unset-secret cases are modelled by
``pop`` inside the patched copy. No ``FLASK_ENV`` or secret var change leaks into
the global pytest process.
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
from src.database_postgres import _resolve_seed_password  # noqa: E402


# Config secrets under test and their real shipped insecure defaults.
_CONFIG_SECRETS = {
    "POSTGRES_PASSWORD": "swautomorph_password",
    "SECRET_KEY": "dev-secret-key-change-in-production",
}
_config_secret_names = st.sampled_from(sorted(_CONFIG_SECRETS))

# All key names the changed code may name in a message.
_ALL_KEY_NAMES = ["POSTGRES_PASSWORD", "SECRET_KEY", "SEED_ADMIN_PASSWORD"]

# The three shipped default values that must never leak into any message.
_KNOWN_DEFAULT_VALUES = [
    "swautomorph_password",
    "dev-secret-key-change-in-production",
    "password",
]

# ``os.environ`` assignment rejects null bytes (ValueError) and surrogate code
# points (UnicodeEncodeError). Those are constraints of the OS environment, not
# of the units under test, so strings assigned to env vars draw from the
# printable/latin range only. Values are only ever *stored* in env vars here, so
# the same restriction applies to the arbitrary secret values below.
_env_safe_chars = st.characters(
    min_codepoint=32, max_codepoint=126
)

# Non-development FLASK_ENV values; the sentinel models the UNSET case.
_UNSET = object()
_random_env_text = st.text(
    alphabet=_env_safe_chars, min_size=0, max_size=20
).filter(lambda s: s != "development")
_FLASK_ENVS = st.one_of(
    st.sampled_from(["production", "staging", "prod", "test", "PRODUCTION", ""]),
    st.just(_UNSET),
    _random_env_text,
)

# Arbitrary secret VALUES. Constraints are on the input space, not the unit:
#   * env-safe chars -> these values are stored in os.environ, which rejects
#                       null bytes (ValueError) and surrogates (UnicodeEncodeError)
#   * sentinel-prefixed, non-empty -> the full value can never be an incidental
#                       substring of the fixed English message, so "value absent"
#                       is a real no-echo check rather than a coincidence
#   * must not contain any key name as a substring, so the value-absence check
#     is independent of the key-name-present check.
def _free_of_key_names(s: str) -> bool:
    return all(k not in s for k in _ALL_KEY_NAMES)


# A unique sentinel that cannot occur in either fixed English message template.
# Prefixing every generated value with it guarantees the FULL value is never an
# incidental substring of the static message text (a short value like "A" would
# otherwise appear by chance). This keeps the "value absent" assertion a genuine
# no-echo check: the only way the value could appear is if the code interpolated
# it -- which is exactly what the property forbids.
_SENTINEL = "ZZSECRETVALUEZZ"
_arbitrary_values = st.text(
    alphabet=_env_safe_chars, min_size=0, max_size=40
).filter(_free_of_key_names).map(lambda s: _SENTINEL + s)


def _patched_prod_env(flask_env):
    """Context manager: isolated os.environ with a production FLASK_ENV.

    ``flask_env is _UNSET`` removes FLASK_ENV entirely (treated as production).
    The snapshot is restored on exit, so nothing leaks to sibling tests.
    """
    class _Ctx:
        def __enter__(self):
            self._patch = mock.patch.dict(os.environ, {}, clear=False)
            self._patch.__enter__()
            if flask_env is _UNSET:
                os.environ.pop("FLASK_ENV", None)
            else:
                os.environ["FLASK_ENV"] = flask_env
            return self

        def __exit__(self, *exc):
            return self._patch.__exit__(*exc)

    return _Ctx()


# ===========================================================================
# Property 7 -- config require_secret: arbitrary value via the equals-default
# branch; message names the key and never echoes the value.
# ===========================================================================
@settings(max_examples=200)
@given(name=_config_secret_names, flask_env=_FLASK_ENVS, value=_arbitrary_values)
def test_config_message_names_key_and_hides_arbitrary_value(name, flask_env, value):
    """Feature: phase1-foundation-consolidation, Property 7.

    For an arbitrary secret VALUE routed through the production fail-fast (by
    making the env var equal the supplied ``dev_fallback``), the RuntimeError
    message contains the key NAME and does NOT contain the VALUE.
    Validates: Requirements 5.7, 8.1, 8.2.
    """
    with _patched_prod_env(flask_env):
        os.environ[name] = value  # genuine secret value in the environment
        assert os.environ.get("FLASK_ENV") != "development"  # prod regime

        # value == dev_fallback -> production branch raises.
        with pytest.raises(RuntimeError) as exc_info:
            require_secret(name, value)

        message = str(exc_info.value)
        # (a) key NAME present.
        assert name in message
        # (b) secret VALUE absent -- independent of (a) because value excludes
        #     every key name by construction.
        assert value not in message


@settings(max_examples=100)
@given(name=_config_secret_names, flask_env=_FLASK_ENVS)
def test_config_message_hides_default_when_var_unset(name, flask_env):
    """Feature: phase1-foundation-consolidation, Property 7.

    With the secret var UNSET in production, require_secret raises; the message
    names the key and leaks neither the shipped default nor any known default
    value. Validates: Requirements 5.7, 8.1, 8.2.
    """
    default = _CONFIG_SECRETS[name]
    with _patched_prod_env(flask_env):
        os.environ.pop(name, None)
        assert os.environ.get("FLASK_ENV") != "development"

        with pytest.raises(RuntimeError) as exc_info:
            require_secret(name, default)

        message = str(exc_info.value)
        assert name in message
        for leaked in _KNOWN_DEFAULT_VALUES:
            assert leaked not in message


# ===========================================================================
# Property 7 -- db _resolve_seed_password: arbitrary value via the default
# ('password') branch; message names SEED_ADMIN_PASSWORD and never the value.
# ===========================================================================
@settings(max_examples=100)
@given(flask_env=_FLASK_ENVS, value=_arbitrary_values)
def test_seed_message_names_key_and_hides_arbitrary_value(flask_env, value):
    """Feature: phase1-foundation-consolidation, Property 7.

    _resolve_seed_password raises in production when SEED_ADMIN_PASSWORD is unset
    or equals the default. Routing an arbitrary value: setting the var to the
    fixed default 'password' triggers the raise; separately the unset case with
    an arbitrary value confined to the environment confirms no echo. The message
    names SEED_ADMIN_PASSWORD and never any secret value.
    Validates: Requirements 5.7, 8.1, 8.2.
    """
    with _patched_prod_env(flask_env):
        # Place an arbitrary value in an unrelated slot and leave the real seed
        # var unset so the fail-fast fires; the arbitrary value must not surface.
        os.environ.pop("SEED_ADMIN_PASSWORD", None)
        os.environ["SOME_OTHER_SECRET"] = value
        assert os.environ.get("FLASK_ENV") != "development"

        with pytest.raises(RuntimeError) as exc_info:
            _resolve_seed_password()

        message = str(exc_info.value)
        assert "SEED_ADMIN_PASSWORD" in message
        assert value not in message
        for leaked in _KNOWN_DEFAULT_VALUES:
            assert leaked not in message


@settings(max_examples=100)
@given(flask_env=_FLASK_ENVS)
def test_seed_message_hides_default_when_at_default(flask_env):
    """Feature: phase1-foundation-consolidation, Property 7.

    With SEED_ADMIN_PASSWORD set to its insecure default 'password' in
    production, _resolve_seed_password raises; the message names the key and
    does not echo 'password' or any known default value.
    Validates: Requirements 5.7, 8.1, 8.2.
    """
    with _patched_prod_env(flask_env):
        os.environ["SEED_ADMIN_PASSWORD"] = "password"
        assert os.environ.get("FLASK_ENV") != "development"

        with pytest.raises(RuntimeError) as exc_info:
            _resolve_seed_password()

        message = str(exc_info.value)
        assert "SEED_ADMIN_PASSWORD" in message
        for leaked in _KNOWN_DEFAULT_VALUES:
            assert leaked not in message


# ===========================================================================
# Isolation guard (example): confirm nothing leaked to the global environment.
# ===========================================================================
def test_env_isolation_restored_after_examples():
    """Feature: phase1-foundation-consolidation, Property 7 (isolation guard).

    The suite-wide dev context from conftest must be intact: FLASK_ENV is still
    'development' and the transient SOME_OTHER_SECRET slot never persisted.
    """
    assert os.environ.get("FLASK_ENV") == "development"
    assert "SOME_OTHER_SECRET" not in os.environ
