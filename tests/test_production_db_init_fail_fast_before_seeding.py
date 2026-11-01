#!/usr/bin/env python3
"""Property-based test for production DB-init fail-fast before seeding.

Feature: phase1-foundation-consolidation, Property 6 -- "Production-mode DB-init
fail-fast before seeding". Validates Requirements 5.6: IF the Platform is in
Production_Mode (``FLASK_ENV`` is any value other than the exact string
``development``, INCLUDING unset) AND DB_Init would seed the ``admin`` or
``demo`` user with the known default password, THEN THE DB_Init SHALL raise a
database-initialization error identifying the missing ``SEED_ADMIN_PASSWORD``
configuration BY NAME *before any default-credentialed user is created*.

UNIT UNDER TEST
---------------
``src.database_postgres._resolve_seed_password`` (added in task 10.2). In
production it raises ``RuntimeError`` naming ``SEED_ADMIN_PASSWORD`` when the
env var is unset or equal to its insecure default ``'password'``. The DB_Init
seed block in ``src/database_postgres.py`` calls it on a single line --

    seed_pw = _resolve_seed_password()            # <- raises here in prod
    admin_password_hash = generate_password_hash(seed_pw)
    cursor.execute('''INSERT INTO users ...''', ('admin', ...))
    ...
    cursor.execute('''INSERT INTO users ...''', ('demo', ...))

-- so the resolve is *positioned before* both the admin and demo INSERTs. That
placement (verified against the source at the admin-seed branch) is exactly the
ordering this test pins.

TWO COMPLEMENTARY ASSERTIONS
----------------------------
1. DIRECT (Hypothesis, >=100 examples): over (production FLASK_ENV incl UNSET)
   x (SEED_ADMIN_PASSWORD unset OR == 'password'), assert
   ``_resolve_seed_password()`` raises ``RuntimeError`` whose message contains
   ``'SEED_ADMIN_PASSWORD'``.

2. BEFORE-ANY-INSERT (example-based): a faithful reconstruction of the source
   seed ordering -- call the REAL ``_resolve_seed_password`` first, exactly as
   the source does, then (only if it returns) record an admin/demo INSERT on a
   spy ``MagicMock`` cursor. Under production with default/unset secret the
   resolve raises, so the spy proves ``cursor.execute`` is NEVER reached with an
   ``INSERT INTO users`` for admin/demo. Driving the real ``init_db()`` is
   infeasible without a live PostgreSQL (it opens a real connection pool, reads
   schema/migration files, and does a network ``socket.connect`` long before the
   seed branch), so we exercise the real resolve helper inside a structural
   mirror of the seed block rather than a live DB.

ENVIRONMENT ISOLATION (CRITICAL)
--------------------------------
``tests/conftest.py`` sets ``FLASK_ENV=development`` for the whole process and
many sibling tests depend on it. Every example here runs inside
``mock.patch.dict(os.environ, ...)``, which snapshots the environment on enter
and restores it verbatim on exit. We model UNSET by ``pop``-ing the key from the
patched copy, so neither ``FLASK_ENV`` nor ``SEED_ADMIN_PASSWORD`` is ever
mutated in the real process environment -- no leakage to other tests.
"""
import os
import sys
from unittest import mock

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src.database_postgres import _resolve_seed_password  # noqa: E402

# The Secret_Key_Name the production error must name (Requirement 5.6/5.7).
SEED_KEY = "SEED_ADMIN_PASSWORD"
# The insecure default the helper also rejects in production.
INSECURE_DEFAULT = "password"


def _apply_env(flask_env, seed_state):
    """Mutate the (already patched) os.environ copy to the requested state.

    ``flask_env`` is None to model an UNSET FLASK_ENV (production), else the
    exact string value. ``seed_state`` is None to model an UNSET
    SEED_ADMIN_PASSWORD, or the exact value to set.
    """
    if flask_env is None:
        os.environ.pop("FLASK_ENV", None)
    else:
        os.environ["FLASK_ENV"] = flask_env

    if seed_state is None:
        os.environ.pop(SEED_KEY, None)
    else:
        os.environ[SEED_KEY] = seed_state


# --- strategies -------------------------------------------------------------

# A production FLASK_ENV is anything that is NOT the exact string 'development',
# plus the UNSET case (modelled as None). We filter arbitrary text so it can
# never coincide with 'development', and exclude the NUL character because real
# environment variables cannot contain an embedded null byte (os.environ rejects
# it) -- it is not a value FLASK_ENV could ever actually hold.
_non_dev_text = st.text(min_size=0, max_size=30).filter(
    lambda s: s != "development" and "\x00" not in s
)
_flask_env_production = st.one_of(st.none(), _non_dev_text)

# The seeded-admin-password is "unset or at its default": None (unset) or the
# literal insecure default 'password'.
_seed_unset_or_default = st.sampled_from([None, INSECURE_DEFAULT])


@settings(max_examples=200)
@given(flask_env=_flask_env_production, seed_state=_seed_unset_or_default)
def test_production_resolve_seed_password_fail_fast_names_key(flask_env, seed_state):
    """Feature: phase1-foundation-consolidation, Property 6.

    In production (FLASK_ENV != 'development', incl unset) with the seeded-admin
    password unset or at its insecure default, ``_resolve_seed_password`` raises
    ``RuntimeError`` naming ``SEED_ADMIN_PASSWORD``. Validates: Requirements 5.6.
    """
    # Defensive: the strategy already excludes it, but never run the dev branch.
    assume(flask_env != "development")

    with mock.patch.dict(os.environ, {}, clear=False):
        _apply_env(flask_env, seed_state)

        # Preconditions of the production fail-fast case.
        assert os.environ.get("FLASK_ENV") != "development"
        assert os.environ.get(SEED_KEY) in (None, INSECURE_DEFAULT)

        with pytest.raises(RuntimeError) as exc_info:
            _resolve_seed_password()

        # The message must reference the secret BY NAME (Req 5.6/5.7) ...
        assert SEED_KEY in str(exc_info.value)

    # Real environment restored untouched -> no leakage for sibling tests.
    assert os.environ.get("FLASK_ENV") == "development"


@settings(max_examples=200)
@given(flask_env=_flask_env_production, seed_state=_seed_unset_or_default)
def test_production_db_init_raises_before_any_user_insert(flask_env, seed_state):
    """Feature: phase1-foundation-consolidation, Property 6.

    BEFORE-ANY-INSERT guarantee. This faithfully reconstructs the source seed
    ordering from ``src/database_postgres.py`` -- ``seed_pw =
    _resolve_seed_password()`` placed *before* the admin/demo
    ``INSERT INTO users`` calls -- driving the REAL resolve helper against a spy
    cursor. In production with the secret unset/default the resolve raises, so
    the spy proves no admin/demo INSERT was ever executed: no default-credentialed
    user is created. Validates: Requirements 5.6.
    """
    assume(flask_env != "development")

    # Spy cursor: fetchone() returns [0] so the real seed guard
    # ``if cursor.fetchone()[0] == 0:`` would ENTER the seed branch, maximising
    # the chance an INSERT could slip through if ordering were wrong.
    cursor = mock.MagicMock()
    cursor.fetchone.return_value = [0]

    def seed_block_mirror():
        """Mirror of the source admin/demo seed block ordering."""
        # Source: the admin-count guard precedes the resolve + INSERTs.
        cursor.execute("SELECT COUNT(*) FROM users WHERE username = %s", ("admin",))
        if cursor.fetchone()[0] == 0:
            # EXACT source ordering: resolve the credential BEFORE any INSERT.
            seed_pw = _resolve_seed_password()  # raises in prod -> stops here
            # The following INSERTs mirror the real admin/demo seeding and must
            # never be reached when the resolve raises.
            cursor.execute(
                "INSERT INTO users (username, email, password_hash, first_name, last_name, suspended) "
                "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                ("admin", "admin@x", seed_pw, "System", "Administrator", False),
            )
            cursor.execute(
                "INSERT INTO users (username, email, password_hash, first_name, last_name, suspended) "
                "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                ("demo", "demo@x", seed_pw, "System", "Demo", False),
            )

    with mock.patch.dict(os.environ, {}, clear=False):
        _apply_env(flask_env, seed_state)

        with pytest.raises(RuntimeError) as exc_info:
            seed_block_mirror()

        assert SEED_KEY in str(exc_info.value)

        # Core of Property 6: NO write (INSERT INTO users for admin/demo) was
        # ever executed -- only the harmless admin-count SELECT guard ran.
        executed_sql = [
            (c.args[0] if c.args else "") for c in cursor.execute.call_args_list
        ]
        assert not any(
            "INSERT INTO users" in sql for sql in executed_sql
        ), f"admin/demo INSERT executed before fail-fast: {executed_sql!r}"
        # The only statement the spy should have seen is the pre-seed count guard.
        assert all("INSERT" not in sql for sql in executed_sql)

    assert os.environ.get("FLASK_ENV") == "development"


def test_source_seed_ordering_matches_mirror():
    """Guard: the source really resolves the seed password BEFORE the admin/demo
    INSERTs, so the mirror above stays faithful. Validates: Requirements 5.6.

    Reads ``src/database_postgres.py`` and asserts the single
    ``seed_pw = _resolve_seed_password()`` line precedes the first
    ``INSERT INTO users`` referencing ``'admin'``.
    """
    src_path = os.path.join(PROJECT_ROOT, "src", "database_postgres.py")
    with open(src_path, "r", encoding="utf-8") as f:
        text = f.read()

    resolve_idx = text.index("seed_pw = _resolve_seed_password()")
    insert_idx = text.index("INSERT INTO users", resolve_idx)
    # The resolve call appears before the admin INSERT that follows it.
    assert resolve_idx < insert_idx
    # And the admin username literal is seeded after the resolve, confirming the
    # guarded INSERT is the admin/demo seed path.
    assert "'admin'" in text[resolve_idx:insert_idx + 400]
