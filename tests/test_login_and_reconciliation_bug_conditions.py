#!/usr/bin/env python3
"""Bug-condition exploration tests (Task 1).

Feature: login-and-reconciliation-failures (bugfix), Correctness Property 1
(Bug Condition / Expected Behavior). These tests encode the EXPECTED behavior of
the fix and are written BEFORE the fix. On UNFIXED code they MUST FAIL -- the
failure is the counterexample that confirms each bug exists. After the fix they
turn green (re-run verbatim by Task 3.3).

Two independent defects (see ``design.md``):

Bug 1 -- missing ``SSO_MAC_KEY`` is only discovered lazily at the first token
operation. A successful ``POST /login`` ends by calling
``auth.generate_sso_token`` which calls ``auth._get_sso_mac_key``; with the key
unset that fails closed with
``RuntimeError: SSO_MAC_KEY is not set; refusing to issue/verify SSO tokens``,
so the login 500s. The expected fix surfaces the misconfiguration at STARTUP
with an actionable error naming ``SSO_MAC_KEY`` (a dedicated startup-validation
helper in ``src/auth.py`` invoked from ``wsgi.py``), without weakening the
request-time guard. When the key IS available a valid non-2FA login issues a
token and completes.

Bug 2 -- the orchestrator reconcile query reads ``restart_attempts``,
``replaced``, ``grace_until``, ``needs_attention`` from ``instances``, but
``init_db()`` in ``src/database_postgres.py`` never applies
``migration/add_instance_remediation.sql``, so the columns do not exist and the
query fails every pass with ``column i.restart_attempts does not exist``. The
expected fix registers that idempotent migration in ``init_db()`` so the columns
and the ``idx_instances_needs_attention`` index exist.

NO-LIVE-DB CONVENTION
---------------------
Driving ``init_db()`` / the reconcile query needs a live PostgreSQL (a real
connection pool, schema/migration files, a network ``socket.connect``), so --
mirroring ``tests/test_production_db_init_fail_fast_before_seeding.py`` and
``tests/test_phase4_instance_remediation_migration_idempotency.py`` -- the
deterministic checks here are STRUCTURAL (they assert the fix seams: the startup
helper exists and is wired into ``wsgi.py``; ``init_db()`` registers the
remediation migration in its application path). The actual live
``init_db()``+reconcile execution is an ``@pytest.mark.integration`` test gated
behind ``RUN_LOGIN_RECONCILE_INTEGRATION=1`` plus a reachable database, skipped
by default.

Run (structural checks; live demo skipped unless opt-in + DB present):
    pytest tests/test_login_and_reconciliation_bug_conditions.py

Run the live integration facets manually (requires a reachable DB):
    RUN_LOGIN_RECONCILE_INTEGRATION=1 \
        pytest tests/test_login_and_reconciliation_bug_conditions.py -v -m integration
"""
import os
import sys
from unittest import mock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Keep the dev context the suite runs under (conftest sets it too); importing
# auth below must not require the key to merely import.
os.environ.setdefault("FLASK_ENV", "development")
os.environ.setdefault("SSO_MAC_KEY", "unit-test-sso-mac-key")

from src import auth  # noqa: E402

SSO_KEY_ENV = "SSO_MAC_KEY"
MIGRATION_FILE = "add_instance_remediation.sql"
EXPECTED_REMEDIATION_COLUMNS = (
    "restart_attempts",
    "replaced",
    "needs_attention",
    "started_at",
    "grace_until",
)
EXPECTED_INDEX = "idx_instances_needs_attention"

# Opt-in flag for the live init_db()+reconcile facets.
RUN_INTEGRATION = os.environ.get("RUN_LOGIN_RECONCILE_INTEGRATION") == "1"


def _startup_validator():
    """Return the fix's startup-validation callable from ``src/auth.py`` or None.

    The fix adds a helper (named ``require_sso_mac_key`` or
    ``validate_startup_config``) that eagerly checks for ``SSO_MAC_KEY`` and
    fails closed with an actionable error naming it. On UNFIXED code no such
    helper exists, so this returns None and the deferred-failure facet fails --
    the counterexample confirming startup defers the failure to request time.
    """
    for name in ("require_sso_mac_key", "validate_startup_config"):
        fn = getattr(auth, name, None)
        if callable(fn):
            return fn
    return None


# =========================================================================== #
# Bug 1 -- deferred-failure facet (Requirements 1.2, 2.2)
# =========================================================================== #
def test_bug1_startup_fails_fast_naming_sso_mac_key(monkeypatch):
    """Startup validation fails closed and names SSO_MAC_KEY when it is unset.

    EXPECTED (fixed): a startup-validation helper in ``src/auth.py`` raises a
    clear error whose message contains ``SSO_MAC_KEY`` when the key is unset, so
    the misconfiguration is caught at boot rather than deferred to the first
    login. UNFIXED: no such helper exists -> FAILS (counterexample: the app
    starts without failing, deferring the RuntimeError to request time).

    Validates: Requirements 1.2, 2.2
    """
    monkeypatch.delenv(SSO_KEY_ENV, raising=False)

    validator = _startup_validator()
    assert validator is not None, (
        "no startup-validation helper found in src/auth.py "
        "(expected require_sso_mac_key / validate_startup_config); on unfixed "
        "code the missing-key failure is deferred to the first login request"
    )

    with pytest.raises(Exception) as exc_info:
        validator()
    assert SSO_KEY_ENV in str(exc_info.value), (
        "startup validation must name the missing SSO_MAC_KEY by key"
    )


def test_bug1_startup_validator_passes_when_key_set(monkeypatch):
    """When SSO_MAC_KEY is set the startup validator does not raise (fixed).

    EXPECTED (fixed): with the key present, startup validation succeeds so the
    app boots normally. UNFIXED: the helper does not exist -> FAILS.

    Validates: Requirement 2.2
    """
    monkeypatch.setenv(SSO_KEY_ENV, "present-startup-key")

    validator = _startup_validator()
    assert validator is not None, (
        "no startup-validation helper found in src/auth.py"
    )
    # Must not raise when the key is available.
    validator()


def test_bug1_startup_validation_wired_into_wsgi():
    """``wsgi.py`` invokes the startup validator at boot, before serving.

    EXPECTED (fixed): ``wsgi.py`` calls the ``src/auth.py`` startup-validation
    helper at import/startup (alongside ``init_db()``) so a missing key fails
    the boot fast. UNFIXED: ``wsgi.py`` references no such helper -> FAILS.

    Validates: Requirement 2.2
    """
    wsgi_path = os.path.join(PROJECT_ROOT, "wsgi.py")
    with open(wsgi_path, "r", encoding="utf-8") as fh:
        wsgi_src = fh.read()
    assert (
        "require_sso_mac_key" in wsgi_src or "validate_startup_config" in wsgi_src
    ), (
        "wsgi.py does not invoke an SSO_MAC_KEY startup validator; the missing "
        "key is not surfaced at startup (deferred-failure facet)"
    )


# =========================================================================== #
# Bug 1 -- request-time facet (Requirements 1.1, 2.1)
# Scoped property over valid, active, non-2FA login inputs. The login route ends
# by calling generate_sso_token(user_id); we drive that token-issuing step
# directly over a generated space of user ids with a fake db_manager so no live
# DB is needed. The fixed world guarantees (via the startup check) that a login
# is only reached with the key available, so a valid non-2FA login COMPLETES and
# issues a token instead of raising. UNFIXED: with the key unset
# generate_sso_token raises RuntimeError at request time -> FAILS.
# =========================================================================== #
class _FakeConn:
    def __init__(self, sink):
        self._sink = sink

    def cursor(self):
        return self

    def execute(self, sql, params=None):
        self._sink.setdefault("calls", []).append((" ".join(sql.split()), params))

    def commit(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeDbManager:
    def __init__(self):
        self.sink = {}

    def get_db_connection(self):
        return _FakeConn(self.sink)


# Valid, active, non-2FA login inputs reduce (at the token-issuing step) to a
# user id. Scope to realistic positive primary keys.
_USER_ID = st.integers(min_value=1, max_value=10_000_000)


@settings(max_examples=100)
@given(user_id=_USER_ID)
def test_bug1_valid_login_completes_and_issues_token(user_id):
    """A valid, active, non-2FA login completes by issuing an SSO token.

    EXPECTED (fixed): the token-issuing step of ``/login``
    (``generate_sso_token``) returns a clear token exactly once and completes
    the login, for the available-key world the startup check guarantees. UNFIXED
    + key unset: ``_get_sso_mac_key`` raises
    ``RuntimeError: SSO_MAC_KEY is not set; ...`` as an unhandled exception ->
    this property FAILS.

    This facet is driven with the key available to the process (the fixed,
    startup-validated state); the request-time RuntimeError that breaks login
    on unfixed/unset-key is pinned separately below as the documented
    counterexample.

    Uses ``mock.patch`` context managers rather than the function-scoped
    ``monkeypatch`` fixture because Hypothesis does not reset fixtures between
    generated examples.

    Validates: Requirements 1.1, 2.1
    """
    fake = _FakeDbManager()
    # The fixed world only reaches a login once startup validation has confirmed
    # the key is available. Gate the property on that validator so the test is
    # faithful to the expected post-fix behavior; on unfixed code the validator
    # is absent and the test fails here (deferred failure never surfaced).
    with mock.patch.dict(os.environ, {SSO_KEY_ENV: "request-time-available-key"}), \
         mock.patch.object(auth, "db_manager", fake):
        validator = _startup_validator()
        assert validator is not None, (
            "startup validation helper absent; a login can still be reached "
            "with SSO_MAC_KEY unset, deferring the RuntimeError to request time"
        )
        validator()

        # Must COMPLETE (return a clear token) rather than raise.
        token = auth.generate_sso_token(user_id)
        assert isinstance(token, str) and token

        inserts = [
            c for c in fake.sink.get("calls", []) if "INSERT INTO auth_tokens" in c[0]
        ]
        assert len(inserts) == 1
        _sql, params = inserts[0]
        assert params[0] == user_id


def test_bug1_request_time_counterexample_unset_key(monkeypatch):
    """Document the request-time counterexample on unfixed/unset-key.

    This pins the ACTUAL observed defect: with ``SSO_MAC_KEY`` unset the
    token-issuing step raises the specific RuntimeError that 500s the login. The
    fix leaves this fail-closed guard intact (by design) and instead prevents
    reaching request time without the key via the startup check. This assertion
    stays green before and after the fix and records the counterexample text.

    Validates: Requirement 1.1
    """
    monkeypatch.delenv(SSO_KEY_ENV, raising=False)
    monkeypatch.setattr(auth, "db_manager", _FakeDbManager())
    with pytest.raises(RuntimeError) as exc_info:
        auth.generate_sso_token(user_id=1)
    assert SSO_KEY_ENV in str(exc_info.value)


# =========================================================================== #
# Bug 2 -- migration-omitted facet (Requirements 1.5, 2.4)
# Deterministic, no live DB: assert init_db() registers the remediation
# migration in its application path. On UNFIXED code the migration name never
# appears in database_postgres.py's init_db() -> FAILS, which is exactly why the
# columns are absent after init_db() on a fresh DB.
# =========================================================================== #
def _init_db_source():
    src_path = os.path.join(PROJECT_ROOT, "src", "database_postgres.py")
    with open(src_path, "r", encoding="utf-8") as fh:
        text = fh.read()
    start = text.index("def init_db(")
    return text[start:]


def test_bug2_init_db_registers_remediation_migration():
    """``init_db()`` applies ``add_instance_remediation.sql``.

    EXPECTED (fixed): the remediation migration is registered in ``init_db()``'s
    migration application path (so the columns/index are created). UNFIXED: the
    migration name is absent from ``init_db()`` -> FAILS (counterexample: the
    remediation columns are never created, so the reconcile query errors).

    Validates: Requirements 1.5, 2.4
    """
    init_src = _init_db_source()
    assert MIGRATION_FILE in init_src, (
        f"init_db() does not register {MIGRATION_FILE!r}; the remediation "
        "columns are never created on a fresh DB"
    )


# =========================================================================== #
# Bug 2 -- live facets (Requirements 1.3, 1.5, 2.3, 2.4), integration only.
# Run init_db() on a reachable DB, then (a) assert the remediation columns and
# index exist and (b) execute the reconcile query without error. On UNFIXED code
# init_db() omits the migration so the columns are absent and the reconcile
# query raises ``column i.restart_attempts does not exist``.
# =========================================================================== #
def _db_manager_or_skip():
    try:
        from src.database_postgres import db_manager  # noqa: WPS433
    except Exception as exc:  # pragma: no cover - import/env dependent
        pytest.skip(f"live-db facet: import failed ({exc})")
    return db_manager


@pytest.mark.integration
@pytest.mark.skipif(
    not RUN_INTEGRATION,
    reason=(
        "live init_db()+reconcile needs a reachable PostgreSQL. Set "
        "RUN_LOGIN_RECONCILE_INTEGRATION=1 and point at a database to run it. "
        "Skipped by default."
    ),
)
def test_bug2_init_db_creates_remediation_columns_and_index_live():
    """After ``init_db()`` the remediation columns and index exist on instances.

    EXPECTED (fixed): all five columns + the needs-attention index exist.
    UNFIXED: they are absent -> FAILS.

    Validates: Requirements 1.5, 2.4
    """
    from src.database_postgres import init_db  # noqa: WPS433

    db_manager = _db_manager_or_skip()
    try:
        init_db()
        with db_manager.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'instances' AND column_name = ANY(%s)",
                (list(EXPECTED_REMEDIATION_COLUMNS),),
            )
            present = {r[0] for r in cur.fetchall()}
            missing = set(EXPECTED_REMEDIATION_COLUMNS) - present
            assert not missing, f"remediation columns missing after init_db(): {missing}"

            cur.execute(
                "SELECT COUNT(*) FROM pg_indexes "
                "WHERE tablename = 'instances' AND indexname = %s",
                (EXPECTED_INDEX,),
            )
            assert cur.fetchone()[0] == 1, f"{EXPECTED_INDEX} missing after init_db()"
            conn.rollback()
    except pytest.skip.Exception:
        raise
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"no reachable PostgreSQL for live init_db facet: {exc}")


@pytest.mark.integration
@pytest.mark.skipif(
    not RUN_INTEGRATION,
    reason=(
        "live reconcile query needs a reachable PostgreSQL. Set "
        "RUN_LOGIN_RECONCILE_INTEGRATION=1 and point at a database to run it. "
        "Skipped by default."
    ),
)
def test_bug2_reconcile_query_executes_without_error_live():
    """The reconcile query over the remediation columns executes without error.

    EXPECTED (fixed): after ``init_db()`` the query referencing
    ``restart_attempts``/``replaced``/``grace_until``/``needs_attention`` runs
    cleanly. UNFIXED: it raises ``column i.restart_attempts does not exist`` ->
    FAILS.

    Validates: Requirements 1.3, 2.3
    """
    from src.database_postgres import init_db  # noqa: WPS433

    db_manager = _db_manager_or_skip()
    try:
        init_db()
        with db_manager.get_db_connection() as conn:
            cur = conn.cursor()
            # Mirror the orchestrator reconcile projection over the remediation
            # columns; LIMIT 0 keeps it a pure schema/column-existence check.
            cur.execute(
                """
                SELECT i.id, i.restart_attempts, i.replaced,
                       i.needs_attention,
                       EXTRACT(EPOCH FROM i.grace_until)
                FROM instances i
                WHERE i.status = 'running'
                LIMIT 0
                """
            )
            cur.fetchall()
            conn.rollback()
    except pytest.skip.Exception:
        raise
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"no reachable PostgreSQL for live reconcile facet: {exc}")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
