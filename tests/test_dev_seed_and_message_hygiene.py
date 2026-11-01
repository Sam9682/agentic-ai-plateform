#!/usr/bin/env python3
"""Example tests for dev-mode seed and config/db-init message hygiene.

Feature: phase1-foundation-consolidation, Task 10.7 (example/smoke tests).
Validates Requirements 5.3 and 8.3:

- Req 5.3: WHILE the Platform is in Development_Mode, THE DB_Init SHALL retain
  the existing default password behavior when seeding the ``admin`` and ``demo``
  users. The pure helper ``src.database_postgres._resolve_seed_password`` returns
  the default ``'password'`` in development (``FLASK_ENV == 'development'``) when
  ``SEED_ADMIN_PASSWORD`` is unset, and must not raise.
- Req 8.3: WHEN App_Config or DB_Init emits a configuration or initialization
  message, THE Platform SHALL exclude the values of ``POSTGRES_PASSWORD``,
  ``SECRET_KEY``, and seeded user passwords from that message.

These are focused EXAMPLE tests (not Hypothesis). The exhaustive input-space
coverage lives in the Property tests (10.3-10.6). Here we assert the three
concrete, documented secret values never appear in the fail-fast messages, and
that each message still names its key (so operators can act on the error).

ENVIRONMENT ISOLATION
---------------------
``tests/conftest.py`` sets ``FLASK_ENV=development`` for the whole process and
other tests depend on that. Every example runs inside
``mock.patch.dict(os.environ, ...)``, which snapshots the environment on enter
and restores it verbatim on exit -- so the global ``FLASK_ENV=development`` and
any real secret vars are never clobbered for sibling tests. We force the
``FLASK_ENV`` we need inside the patch and ``pop`` secret vars within the
patched copy to model the "unset" case, never touching the real process env.
Both helpers under test read the environment fresh at call time, so importing
them once at module load (under the conftest dev context) is safe.
"""
import os
import sys
from unittest import mock

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src.config_postgres import require_secret  # noqa: E402
from src.database_postgres import _resolve_seed_password  # noqa: E402

# The three known default secret VALUES that must never leak into any
# config/db-init message. These are the literal defaults applied in src/.
POSTGRES_PASSWORD_DEFAULT = "swautomorph_password"
SECRET_KEY_DEFAULT = "dev-secret-key-change-in-production"
SEED_PASSWORD_DEFAULT = "password"


# ---------------------------------------------------------------------------
# Test 1 -- dev-mode seed uses the default password without error (Req 5.3)
# ---------------------------------------------------------------------------
def test_dev_seed_uses_default_password_without_error():
    """In development with SEED_ADMIN_PASSWORD unset, the seed password
    resolves to the default ``'password'`` and nothing is raised.

    Validates: Requirements 5.3.
    """
    with mock.patch.dict(os.environ, {"FLASK_ENV": "development"}, clear=False):
        # Model the "unset" case inside the patched copy only.
        os.environ.pop("SEED_ADMIN_PASSWORD", None)
        assert "SEED_ADMIN_PASSWORD" not in os.environ  # precondition

        # Must not raise, and must return the documented dev default.
        seed_pw = _resolve_seed_password()
        assert seed_pw == SEED_PASSWORD_DEFAULT

    # Real environment restored untouched (no leakage to sibling tests).
    assert os.environ.get("FLASK_ENV") == "development"


def test_dev_seed_hashes_default_password_through_insert_path():
    """Drive the dev seed hashing step the DB_Init INSERT path uses.

    ``src/database_postgres.py`` seeds the admin/demo users with
    ``generate_password_hash(_resolve_seed_password())``. In development this
    must produce a valid hash of ``'password'`` without raising, confirming the
    seed branch would reach the INSERT with the default credential preserved.

    Validates: Requirements 5.3.
    """
    from werkzeug.security import check_password_hash, generate_password_hash

    with mock.patch.dict(os.environ, {"FLASK_ENV": "development"}, clear=False):
        os.environ.pop("SEED_ADMIN_PASSWORD", None)

        seed_pw = _resolve_seed_password()  # must not raise
        admin_password_hash = generate_password_hash(seed_pw)

    assert check_password_hash(admin_password_hash, SEED_PASSWORD_DEFAULT)
    assert os.environ.get("FLASK_ENV") == "development"


# ---------------------------------------------------------------------------
# Helpers to capture each production fail-fast message.
# ---------------------------------------------------------------------------
def _config_failfast_message(key_name, default_value):
    """Trigger the config fail-fast for ``key_name`` in production and return
    the raised RuntimeError message. The var is removed inside the patched copy
    so the production branch (missing secret) is exercised."""
    with mock.patch.dict(os.environ, {"FLASK_ENV": "production"}, clear=False):
        os.environ.pop(key_name, None)
        with pytest.raises(RuntimeError) as exc_info:
            require_secret(key_name, default_value)
    assert os.environ.get("FLASK_ENV") == "development"  # restored
    return str(exc_info.value)


def _seed_failfast_message():
    """Trigger the db-init seed fail-fast in production (SEED_ADMIN_PASSWORD
    unset) and return the raised RuntimeError message."""
    with mock.patch.dict(os.environ, {"FLASK_ENV": "production"}, clear=False):
        os.environ.pop("SEED_ADMIN_PASSWORD", None)
        with pytest.raises(RuntimeError) as exc_info:
            _resolve_seed_password()
    assert os.environ.get("FLASK_ENV") == "development"  # restored
    return str(exc_info.value)


# ---------------------------------------------------------------------------
# Test 2 -- message hygiene: the three secret VALUES never leak (Req 8.3)
# ---------------------------------------------------------------------------
def test_config_postgres_password_message_excludes_secret_value():
    """The POSTGRES_PASSWORD fail-fast names the key but not its value.

    Validates: Requirements 8.3.
    """
    message = _config_failfast_message("POSTGRES_PASSWORD", POSTGRES_PASSWORD_DEFAULT)

    # Negative: the default VALUE must not appear anywhere in the message.
    assert POSTGRES_PASSWORD_DEFAULT not in message
    # Positive: the key name must be present so operators can act on the error.
    assert "POSTGRES_PASSWORD" in message


def test_config_secret_key_message_excludes_secret_value():
    """The SECRET_KEY fail-fast names the key but not its value.

    Validates: Requirements 8.3.
    """
    message = _config_failfast_message("SECRET_KEY", SECRET_KEY_DEFAULT)

    assert SECRET_KEY_DEFAULT not in message
    assert "SECRET_KEY" in message


def test_db_seed_message_excludes_default_password_value():
    """The SEED_ADMIN_PASSWORD fail-fast names the key but not the default
    password VALUE.

    SUBTLETY on the substring ``'password'``: the actual message is

        "Refusing to seed default users in production: required secret
         'SEED_ADMIN_PASSWORD' is missing or set to its insecure default.
         Set the 'SEED_ADMIN_PASSWORD' environment variable before db-init."

    The requirement is that the secret VALUE is not leaked. The default seed
    value is the lowercase token ``password``. The message only contains the
    uppercase substring ``PASSWORD`` inside the key name ``SEED_ADMIN_PASSWORD``
    -- it never contains the standalone lowercase value ``password``. So we
    assert on the exact VALUE token (case-sensitive) rather than a case-folded
    search that would false-positive on the key name. We also confirm the value
    is not present as a quoted standalone token.

    Validates: Requirements 8.3.
    """
    message = _seed_failfast_message()

    # Case-sensitive: the key name carries 'PASSWORD' (uppercase), never the
    # lowercase default VALUE 'password'.
    assert SEED_PASSWORD_DEFAULT not in message  # 'password' (lowercase) absent
    # And it must not appear quoted as a standalone value token either.
    assert f"'{SEED_PASSWORD_DEFAULT}'" not in message
    assert f'"{SEED_PASSWORD_DEFAULT}"' not in message
    # Positive: the key name must be present.
    assert "SEED_ADMIN_PASSWORD" in message


def test_no_known_secret_value_appears_in_any_failfast_message():
    """Cross-check: none of the three known default secret values appears in
    any of the three fail-fast messages.

    Validates: Requirements 8.3.
    """
    messages = [
        _config_failfast_message("POSTGRES_PASSWORD", POSTGRES_PASSWORD_DEFAULT),
        _config_failfast_message("SECRET_KEY", SECRET_KEY_DEFAULT),
        _seed_failfast_message(),
    ]
    known_values = [
        POSTGRES_PASSWORD_DEFAULT,
        SECRET_KEY_DEFAULT,
        SEED_PASSWORD_DEFAULT,
    ]
    for message in messages:
        for value in known_values:
            assert value not in message, (
                f"secret value leaked into message: {value!r}"
            )
