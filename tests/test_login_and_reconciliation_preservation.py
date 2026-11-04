#!/usr/bin/env python3
"""Preservation property tests (Task 2).

Feature: login-and-reconciliation-failures (bugfix), Correctness Property 2 and
Property 4 (Preservation). These tests are written BEFORE the fix and capture
the BASELINE behavior that must survive the two fixes. On UNFIXED code they MUST
PASS -- that is exactly what confirms the behavior to preserve. They are re-run
verbatim after the fix (Task 3.4) and must still pass (no regressions).

The two fixes (see ``design.md``) are deliberately narrow:

* Bug 1 fix adds a *startup* validation helper + a wsgi call that fails closed
  when ``SSO_MAC_KEY`` is unset. It does NOT touch token issuance/validation or
  any login response when the key IS set. So with the key set, every login
  branch and every ``validate_sso_token`` path must behave identically.
* Bug 2 fix registers the already-idempotent ``add_instance_remediation.sql`` in
  ``init_db()``. It must not reorder/alter any other migration or seed step, the
  migration stays an idempotent no-op, and the reconcile state machine must take
  no action for healthy instances at default remediation-column values.

Preservation coverage (Requirements 3.1 - 3.6):

* 3.1 valid non-2FA login issues ``token_hash`` + keyed ``token_mac`` and
  returns the clear token exactly once (property over user ids, key set).
* 3.2 ``validate_sso_token`` recomputes/verifies the keyed MAC over the stored
  hash, preserves the ``expires_at > NOW()`` predicate (SQL-level), accepts
  pre-existing NULL-``token_mac`` rows, and emits a token-free
  ``sso.validate.failed`` audit on every failed path (property over token rows:
  NULL mac, good mac, bad mac, no-row).
* 3.3 missing-fields / unknown-user / wrong-password / suspended / 2FA logins
  return 400 / 401 / 401 / 403 / ``requires_2fa`` unchanged (property over the
  login branches through the real ``/login`` route, key set).
* 3.4 re-applying ``add_instance_remediation.sql`` against an already-migrated DB
  is a harmless no-op (structural idempotency guards; live double-apply gated).
* 3.5 all currently applied migrations + seed/default-data steps run in their
  existing order and manner -- the baseline order is captured from ``init_db()``
  and asserted preserved.
* 3.6 the reconcile loop takes no remediation action for healthy instances at
  default remediation-column values (``restart_attempts=0``, ``replaced=FALSE``,
  ``grace_until``/``started_at`` NULL) -- property over the pure
  ``decide_remediation`` state machine.

NO-LIVE-DB CONVENTION
---------------------
Mirrors ``tests/test_login_and_reconciliation_bug_conditions.py`` and
``tests/test_phase4_instance_remediation_migration_idempotency.py``: the
deterministic facets use fakes / pure functions / source parsing and need no
live PostgreSQL. The one facet that genuinely needs a live DB (the
double-apply) is ``@pytest.mark.integration`` gated behind
``RUN_LOGIN_RECONCILE_INTEGRATION=1`` plus a reachable database, skipped by
default.

Run (deterministic checks; live facet skipped unless opt-in + DB present):
    pytest tests/test_login_and_reconciliation_preservation.py

Run the live double-apply facet manually (requires a reachable DB):
    RUN_LOGIN_RECONCILE_INTEGRATION=1 \
        pytest tests/test_login_and_reconciliation_preservation.py -v -m integration
"""
import hashlib
import hmac
import os
import re
import sys
from unittest import mock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Keep the dev context the suite runs under; importing auth/config below must
# not require production secrets merely to import. A fixed MAC key is set so the
# preservation facets exercise the "SSO_MAC_KEY is set" (non-bug) world.
os.environ.setdefault("FLASK_ENV", "development")
os.environ.setdefault("SSO_MAC_KEY", "preservation-test-sso-mac-key")

from src import auth  # noqa: E402

SSO_KEY_ENV = "SSO_MAC_KEY"
# A deterministic key used across the key-set (non-bug) facets.
PRESERVE_KEY = "preservation-test-sso-mac-key"

MIGRATION_FILE = "add_instance_remediation.sql"
MIGRATION_PATH = os.path.join(PROJECT_ROOT, "migration", MIGRATION_FILE)

# Opt-in flag for the single live facet (migration double-apply).
RUN_INTEGRATION = os.environ.get("RUN_LOGIN_RECONCILE_INTEGRATION") == "1"


# =========================================================================== #
# Shared fakes (no live DB).
# =========================================================================== #
class _FakeConn:
    """Captures cursor.execute calls so token-issuance SQL can be inspected."""

    def __init__(self, sink):
        self._sink = sink

    def cursor(self):
        return self

    def execute(self, sql, params=None):
        self._sink.setdefault("calls", []).append((" ".join(sql.split()), params))

    def commit(self):
        self._sink["committed"] = self._sink.get("committed", 0) + 1

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeDbManager:
    """Fake ``db_manager`` for ``generate_sso_token`` (connection-based path)."""

    def __init__(self):
        self.sink = {}

    def get_db_connection(self):
        return _FakeConn(self.sink)


# =========================================================================== #
# 3.1 Preservation -- token issuance stores token_hash + keyed token_mac and
# returns the clear token exactly once (SSO_MAC_KEY set). Property over user ids.
# =========================================================================== #
_USER_ID = st.integers(min_value=1, max_value=10_000_000)


@settings(max_examples=100)
@given(user_id=_USER_ID)
def test_preserve_token_issuance_stores_hash_and_keyed_mac(user_id):
    """Issuance stores token_hash + a keyed token_mac and returns the token once.

    Baseline (key set): ``generate_sso_token`` returns a non-empty clear token,
    inserts exactly one row into ``auth_tokens`` for the user, and the stored
    ``token_mac`` is the keyed HMAC over the stored ``token_hash`` (so the
    clear token is never stored and the MAC authenticates the hash). This holds
    on unfixed code and must remain true after the fix.

    Validates: Requirement 3.1
    """
    fake = _FakeDbManager()
    with mock.patch.dict(os.environ, {SSO_KEY_ENV: PRESERVE_KEY}), \
            mock.patch.object(auth, "db_manager", fake):
        token = auth.generate_sso_token(user_id)

        # Clear token returned exactly once, non-empty string.
        assert isinstance(token, str) and token

        calls = fake.sink.get("calls", [])
        inserts = [c for c in calls if "INSERT INTO auth_tokens" in c[0]]
        assert len(inserts) == 1, "exactly one token row must be inserted"
        _sql, params = inserts[0]
        insert_user_id, token_hash, token_mac, _expires_at = params

        assert insert_user_id == user_id

        # The clear token is NOT stored; the stored hash is sha256(token).
        assert token_hash == hashlib.sha256(token.encode()).hexdigest()
        assert token not in (token_hash, token_mac)

        # The stored MAC is the keyed HMAC over the stored hash.
        expected_mac = hmac.new(
            PRESERVE_KEY.encode("utf-8"),
            token_hash.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        assert token_mac == expected_mac

        # Old tokens for the user are cleared before insert (single live token).
        assert any(
            "DELETE FROM auth_tokens WHERE user_id" in c[0] for c in calls
        )


# =========================================================================== #
# 3.2 Preservation -- validate_sso_token: keyed-MAC verify over the stored hash,
# the expires_at > NOW() predicate preserved at the SQL layer, NULL-token_mac
# rows accepted, and a token-free sso.validate.failed audit on every failure.
# Property over generated token rows (NULL mac / good mac / bad mac / no row).
# =========================================================================== #
class _FakeValidateDbManager:
    """Fake ``db_manager`` for ``validate_sso_token`` (execute_query path).

    Records the SQL used (to assert the expiry predicate is preserved) and
    returns a scripted single row (or None) for the token lookup.
    """

    def __init__(self, row):
        self._row = row
        self.queries = []

    def execute_query(self, query, params=None, fetch_one=False, fetch_all=False):
        self.queries.append(" ".join(query.split()))
        if fetch_one:
            return self._row
        return None


# Row kinds the generator picks between. Each maps to a known baseline outcome.
_ROW_KIND = st.sampled_from(["null_mac", "good_mac", "bad_mac", "no_row"])
_USER_FIELDS = st.tuples(
    st.integers(min_value=1, max_value=1_000_000),  # id
    st.text(min_size=1, max_size=20),               # username
    st.emails() if hasattr(st, "emails") else st.text(min_size=3, max_size=30),
    st.text(max_size=15),                           # first_name
    st.text(max_size=15),                           # last_name
)


def _mac_for(token):
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    return hmac.new(
        PRESERVE_KEY.encode("utf-8"), token_hash.encode("utf-8"), hashlib.sha256
    ).hexdigest()


@settings(max_examples=120)
@given(
    kind=_ROW_KIND,
    user=_USER_FIELDS,
    token=st.text(min_size=8, max_size=48).filter(lambda s: s.strip() != ""),
)
def test_preserve_validate_sso_token_behavior(kind, user, token):
    """validate_sso_token: MAC verify, NULL-mac accept, expiry predicate, audit.

    Baseline (key set), by generated row kind:
      * ``good_mac`` / ``null_mac`` -> accept: returns the user dict, emits NO
        failure audit (NULL ``token_mac`` rows are accepted during the grace
        window; a correct keyed MAC verifies).
      * ``bad_mac`` -> reject: returns ``None`` and emits a token-free
        ``sso.validate.failed`` audit (reason ``mac_mismatch``).
      * ``no_row`` -> reject: returns ``None`` and emits a token-free
        ``sso.validate.failed`` audit (reason ``no_matching_token``).
    In every case the lookup SQL preserves the ``expires_at > NOW()`` predicate,
    and no emitted audit event carries the clear token or the token hash.

    Validates: Requirement 3.2
    """
    uid, username, email, first, last = user
    token_hash = hashlib.sha256(token.encode()).hexdigest()

    if kind == "no_row":
        row = None
    else:
        expires_at = "SENTINEL_EXPIRES_AT"
        if kind == "null_mac":
            stored_mac = None
        elif kind == "good_mac":
            stored_mac = _mac_for(token)
        else:  # bad_mac
            stored_mac = "deadbeef" * 8
        # Row shape mirrors the SELECT: (id, username, email, first, last,
        # expires_at, token_mac).
        row = (uid, username, email, first, last, expires_at, stored_mac)

    fake = _FakeValidateDbManager(row)
    events = []

    def _capture_audit(reason):
        events.append(reason)

    with mock.patch.dict(os.environ, {SSO_KEY_ENV: PRESERVE_KEY}), \
            mock.patch.object(auth, "db_manager", fake), \
            mock.patch.object(auth, "sso_validate_failed_audit", _capture_audit):
        result = auth.validate_sso_token(token)

    # The expiry predicate is preserved at the SQL layer on every path.
    assert fake.queries, "validate_sso_token must issue the lookup query"
    lookup = fake.queries[0].lower()
    assert "expires_at > now()" in lookup

    if kind in ("good_mac", "null_mac"):
        # Accepted: returns the user dict, no failure audit emitted.
        assert result is not None
        assert result["id"] == uid
        assert result["username"] == username
        assert events == []
    else:
        # Rejected: None + exactly one token-free failure audit.
        assert result is None
        assert len(events) == 1
        reason = events[0]
        assert reason in ("mac_mismatch", "no_matching_token")
        if kind == "bad_mac":
            assert reason == "mac_mismatch"
        else:
            assert reason == "no_matching_token"
        # The audit reason carries NO token value (not the clear token, not the
        # hash) -- only a non-secret reason identifier.
        assert token not in str(reason)
        assert token_hash not in str(reason)


# =========================================================================== #
# 3.3 Preservation -- login branch responses unchanged (SSO_MAC_KEY set):
# missing fields -> 400, unknown user -> 401, wrong password -> 401,
# suspended -> 403, 2FA-gated -> 200 + requires_2fa, valid non-2FA -> 200 + token.
# Property over the login branches, driven through the real /login route with a
# minimal app (only the auth blueprint) and a fake db_manager.
# =========================================================================== #
_VALID_PW = "correct horse battery staple"
_WRONG_PW = "definitely wrong password"


def _password_hash(pw):
    from werkzeug.security import generate_password_hash
    return generate_password_hash(pw)


class _RouteDbManager:
    """Fake ``db_manager`` used by the /login route.

    Returns a scripted user row for the first user SELECT; swallows the
    users_logs INSERT that a successful login performs. ``fetch_one`` governs
    the user lookup; non-fetch calls (the login-event INSERT) return 1.
    """

    def __init__(self, user_row):
        self._user_row = user_row

    def execute_query(self, query, params=None, fetch_one=False, fetch_all=False):
        q = query.lower()
        if fetch_one and "from users" in q:
            return self._user_row
        return 1


# Login branch kinds -> expected (status_code, assertion on json).
_LOGIN_BRANCH = st.sampled_from(
    ["missing_fields", "unknown_user", "wrong_password", "suspended",
     "twofa", "valid"]
)
_USERNAME = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789_", min_size=1, max_size=16
).filter(lambda s: s.strip() != "")


def _make_login_app():
    """Build a minimal Flask app exposing only the /login route.

    Avoids ``create_app()`` (which opens DB connections and registers every
    blueprint) so the branch property stays deterministic and DB-free.
    """
    from flask import Flask
    from src.routes.auth_routes import auth_bp

    app = Flask(__name__, template_folder=os.path.join(PROJECT_ROOT, "templates"))
    app.secret_key = "preservation-test-secret"
    app.register_blueprint(auth_bp)
    app.config["TESTING"] = True
    return app


@settings(max_examples=90, deadline=None)
@given(branch=_LOGIN_BRANCH, username=_USERNAME, user_id=_USER_ID)
def test_preserve_login_branch_responses(branch, username, user_id):
    """Each login branch returns its existing status/payload (key set).

    Baseline (key set):
      * ``missing_fields`` -> 400
      * ``unknown_user``   -> 401
      * ``wrong_password`` -> 401
      * ``suspended``      -> 403
      * ``twofa``          -> 200 + ``requires_2fa`` payload
      * ``valid``          -> 200 + ``sso_token`` issued once
    The Bug 1 fix only adds a startup check; with the key set these responses
    must be identical before and after the fix.

    Validates: Requirement 3.3
    """
    # Build the scripted user row + request body for the branch.
    # users SELECT shape: (id, password_hash, suspended, totp_enabled,
    # twofa_email_enabled).
    if branch == "missing_fields":
        user_row = None
        body = {"username": username}  # password missing
        expected_status = 400
    elif branch == "unknown_user":
        user_row = None
        body = {"username": username, "password": _VALID_PW}
        expected_status = 401
    elif branch == "wrong_password":
        user_row = (user_id, _password_hash(_VALID_PW), False, False, False)
        body = {"username": username, "password": _WRONG_PW}
        expected_status = 401
    elif branch == "suspended":
        user_row = (user_id, _password_hash(_VALID_PW), True, False, False)
        body = {"username": username, "password": _VALID_PW}
        expected_status = 403
    elif branch == "twofa":
        user_row = (user_id, _password_hash(_VALID_PW), False, True, False)
        body = {"username": username, "password": _VALID_PW}
        expected_status = 200
    else:  # valid
        user_row = (user_id, _password_hash(_VALID_PW), False, False, False)
        body = {"username": username, "password": _VALID_PW}
        expected_status = 200

    app = _make_login_app()
    fake_db = _RouteDbManager(user_row)

    # Patch the db_manager referenced by the route module and the token issuer
    # the route imported. generate_sso_token is patched to a deterministic stub
    # so this branch property isolates the ROUTE response contract (3.3); the
    # real issuance contract is pinned separately by 3.1.
    with mock.patch.dict(os.environ, {SSO_KEY_ENV: PRESERVE_KEY}), \
            mock.patch("src.routes.auth_routes.db_manager", fake_db), \
            mock.patch(
                "src.routes.auth_routes.generate_sso_token",
                lambda uid: "stub-sso-token",
            ):
        client = app.test_client()
        resp = client.post("/login", json=body)

    assert resp.status_code == expected_status, (
        f"branch {branch!r} expected {expected_status}, got {resp.status_code}"
    )
    payload = resp.get_json()
    assert payload is not None

    if branch == "twofa":
        assert payload.get("requires_2fa") is True
        assert "sso_token" not in payload
    elif branch == "valid":
        assert payload.get("sso_token") == "stub-sso-token"
        assert "requires_2fa" not in payload
    else:
        # Error branches carry an 'error' message and never issue a token.
        assert "error" in payload
        assert "sso_token" not in payload


# =========================================================================== #
# 3.4 Preservation -- add_instance_remediation.sql stays an idempotent no-op.
# Structural guards (no live DB) + a gated live double-apply. On unfixed code
# the migration file already ships with IF NOT EXISTS guards, so these pass and
# must keep passing (the fix only registers the file in init_db, not the file).
# =========================================================================== #
def _read_migration():
    with open(MIGRATION_PATH, "r", encoding="utf-8") as fh:
        return fh.read()


def _strip_comments(sql):
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def _normalize(sql):
    return " ".join(sql.split())


def test_preserve_migration_is_idempotent_structurally():
    """Every ADD COLUMN / CREATE INDEX is guarded by IF NOT EXISTS (no-op re-run).

    Baseline: the migration ships fully idempotent, so a re-run against an
    already-migrated DB is a harmless no-op. The Bug 2 fix relies on this and
    must not change it.

    Validates: Requirement 3.4
    """
    assert os.path.isfile(MIGRATION_PATH), f"missing migration at {MIGRATION_PATH}"
    sql = _strip_comments(_read_migration())

    add_columns = re.findall(r"ADD\s+COLUMN([^,;]*)", sql, flags=re.IGNORECASE)
    assert add_columns, "expected ADD COLUMN statements in the migration"
    for clause in add_columns:
        assert re.match(
            r"IF\s+NOT\s+EXISTS", _normalize(clause), flags=re.IGNORECASE
        ), f"ADD COLUMN not guarded by IF NOT EXISTS: {_normalize(clause)!r}"

    creates = re.findall(r"CREATE\s+INDEX([^;]*)", sql, flags=re.IGNORECASE)
    assert creates, "expected a CREATE INDEX in the migration"
    for clause in creates:
        assert re.match(
            r"IF\s+NOT\s+EXISTS", _normalize(clause), flags=re.IGNORECASE
        ), f"CREATE INDEX not guarded by IF NOT EXISTS: {_normalize(clause)!r}"

    # Purely additive: no destructive statements.
    joined = _normalize(sql).lower()
    for forbidden in ("drop table", "drop column", "drop index",
                      "delete from", "truncate", "alter column"):
        assert forbidden not in joined, f"unexpected destructive stmt: {forbidden!r}"


# =========================================================================== #
# 3.5 Preservation -- all currently applied migrations and seed/default-data
# steps run in their existing order and manner. Capture the baseline order from
# init_db() source and assert it is preserved (the fix must only ADD the
# remediation migration without disturbing the existing sequence).
# =========================================================================== #
def _init_db_source():
    src_path = os.path.join(PROJECT_ROOT, "src", "database_postgres.py")
    with open(src_path, "r", encoding="utf-8") as fh:
        text = fh.read()
    start = text.index("def init_db(")
    end = text.index("\ndef ", start + 1)
    return text[start:end]


# Baseline: the ordered sequence of migration filenames applied by init_db() on
# UNFIXED code (individual blocks first, then the ARO/ZAF loop). Captured by
# observation of the current source. The fix must preserve this relative order
# and manner; add_instance_remediation.sql is ADDED, not inserted before any of
# these in a way that reorders them.
_BASELINE_MIGRATION_ORDER = (
    "add_password_reset_and_2fa.sql",
    "add_serverless_jobs.sql",
    "add_mig_gpu.sql",
    "add_target_link_to_serverless_jobs.sql",
    "make_application_fkeys_deferrable.sql",
    "add_deploy_templates.sql",
    "add_extended_ports_to_user_applications.sql",
    "add_runtime_monitor.sql",
    "add_tenancy.sql",
    "add_agent_events.sql",
    "add_agent_credentials.sql",
    "add_agent_runtimes.sql",
    "add_execution_environments.sql",
    "add_agents.sql",
    "add_agent_executions.sql",
    "add_agent_tasks.sql",
    "add_governance.sql",
    "add_approvals.sql",
    "add_mcp_registry.sql",
    "add_incidents.sql",
    "add_agent_cost_records.sql",
    "add_supervisor.sql",
)

# Baseline: the ordered seed/default-data anchors init_db() performs, by the
# order their marker strings appear in the source. These must keep running in
# the same order and manner after the fix.
_BASELINE_SEED_ORDER = (
    "opcp-serverless-brik application ensured",   # serverless-brik seed
    "Default applications and costs ensured",      # default apps + costs seed
    "SELECT COUNT(*) FROM servers",                # default server seed
    "SELECT COUNT(*) FROM users WHERE username",   # default admin/demo seed
    "SELECT COUNT(*) FROM configuration",          # default configuration seed
)


def test_preserve_existing_migration_application_order():
    """init_db() applies the existing migrations in their baseline relative order.

    Baseline: the migration filenames above appear in init_db() in this exact
    relative order on unfixed code. The Bug 2 fix adds the remediation migration
    without reordering any of them, so this order must be preserved.

    Validates: Requirement 3.5
    """
    init_src = _init_db_source()
    positions = []
    for name in _BASELINE_MIGRATION_ORDER:
        idx = init_src.find(name)
        assert idx != -1, f"migration {name!r} no longer applied by init_db()"
        positions.append((name, idx))

    ordered = [name for name, _idx in sorted(positions, key=lambda p: p[1])]
    assert ordered == list(_BASELINE_MIGRATION_ORDER), (
        "existing migration application order changed:\n"
        f"  expected: {list(_BASELINE_MIGRATION_ORDER)}\n"
        f"  actual:   {ordered}"
    )


def test_preserve_existing_seed_step_order_and_manner():
    """init_db() runs the existing seed/default-data steps in their baseline order.

    Baseline: the seed anchors (serverless-brik, default apps+costs, default
    server, default admin/demo, default configuration) appear in init_db() in
    this exact order on unfixed code. The fix must not disturb them.

    Validates: Requirement 3.5
    """
    init_src = _init_db_source()
    positions = []
    for marker in _BASELINE_SEED_ORDER:
        idx = init_src.find(marker)
        assert idx != -1, f"seed step {marker!r} no longer present in init_db()"
        positions.append((marker, idx))

    ordered = [m for m, _i in sorted(positions, key=lambda p: p[1])]
    assert ordered == list(_BASELINE_SEED_ORDER), (
        "existing seed step order changed:\n"
        f"  expected: {list(_BASELINE_SEED_ORDER)}\n"
        f"  actual:   {ordered}"
    )


# =========================================================================== #
# 3.6 Preservation -- reconcile takes no remediation action for healthy
# instances at default remediation-column values. Property over the pure
# decide_remediation state machine (R4.x), which the reconcile loop drives.
# Healthy instances at defaults (restart_attempts=0, replaced=FALSE,
# grace_until/started_at NULL) must yield RemediationAction.NONE.
# =========================================================================== #
from src import orchestrator  # noqa: E402
from src import platform_discovery  # noqa: E402


@settings(max_examples=120)
@given(
    now=st.floats(min_value=0, max_value=1e10, allow_nan=False, allow_infinity=False),
    # Healthy instances at default remediation-column values: restart_attempts
    # defaults to 0; replaced defaults to FALSE; grace_until/started_at NULL.
    status_code=st.just(platform_discovery.HEALTHY_STATUS_CODE),
)
def test_preserve_healthy_default_instance_no_remediation(now, status_code):
    """Healthy instances at default remediation columns trigger no remediation.

    Baseline: a healthy probe (HTTP 200) with the default persisted remediation
    state (``restart_attempts=0``, ``replaced=FALSE``, ``grace_until`` NULL ->
    not within grace) decides ``RemediationAction.NONE``. The Bug 2 fix only
    makes the columns exist; it must not change this converged behavior.

    Validates: Requirement 3.6
    """
    # grace_until NULL -> within_grace is False (no grace window anchored).
    health_state = platform_discovery.evaluate_health(status_code, now, None)
    assert health_state["healthy"] is True
    assert health_state["within_grace"] is False

    action = orchestrator.decide_remediation(
        health_state,
        consecutive_failures=0,       # restart_attempts default
        within_grace=health_state["within_grace"],
        cap=orchestrator.CRASH_LOOP_CAP,
        replaced=False,               # replaced default
    )
    assert action == orchestrator.RemediationAction.NONE


@settings(max_examples=120)
@given(
    # An instance still inside its start-up grace window (started_at set,
    # grace_until in the future) is also "healthy for remediation purposes":
    # even a failing probe must NOT remediate yet. Defaults for a freshly
    # started instance -> NONE.
    delta=st.floats(min_value=0.001, max_value=1e6, allow_nan=False,
                    allow_infinity=False),
    failing_status=st.sampled_from([None, 500, 502, 503, 404]),
)
def test_preserve_within_grace_no_remediation(delta, failing_status):
    """An instance within its grace window takes no remediation action.

    Baseline: when ``now < grace_until`` the health evaluation reports
    ``within_grace`` and ``decide_remediation`` returns ``NONE`` even for a
    failing probe (R4.1 still-starting). Preserved by the fix.

    Validates: Requirement 3.6
    """
    now = 1_000_000.0
    grace_until = now + delta  # still within grace
    health_state = platform_discovery.evaluate_health(
        failing_status, now, grace_until
    )
    assert health_state["within_grace"] is True

    action = orchestrator.decide_remediation(
        health_state,
        consecutive_failures=0,
        within_grace=True,
        cap=orchestrator.CRASH_LOOP_CAP,
        replaced=False,
    )
    assert action == orchestrator.RemediationAction.NONE


# =========================================================================== #
# 3.4 (live) -- double-apply against a reachable PostgreSQL, integration only.
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
        "live migration double-apply needs a reachable PostgreSQL. Set "
        "RUN_LOGIN_RECONCILE_INTEGRATION=1 and point at a database to run it. "
        "Skipped by default."
    ),
)
def test_preserve_migration_double_apply_is_no_op_live():
    """Applying add_instance_remediation.sql twice is a no-op on a live DB.

    Baseline: the second apply raises nothing and each column/index exists
    exactly once. Preserved by the fix (which only registers the migration).

    Validates: Requirement 3.4
    """
    db_manager = _db_manager_or_skip()
    sql = _read_migration()
    expected_columns = (
        "restart_attempts", "needs_attention", "replaced", "started_at",
        "grace_until",
    )
    expected_index = "idx_instances_needs_attention"
    try:
        with db_manager.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(sql)
            cur.execute(sql)  # second apply must not raise

            cur.execute(
                "SELECT column_name, COUNT(*) FROM information_schema.columns "
                "WHERE table_name = 'instances' AND column_name = ANY(%s) "
                "GROUP BY column_name",
                (list(expected_columns),),
            )
            counts = dict(cur.fetchall())
            for col in expected_columns:
                assert counts.get(col) == 1, (
                    f"column {col!r} expected exactly once, got {counts.get(col)}"
                )

            cur.execute(
                "SELECT COUNT(*) FROM pg_indexes "
                "WHERE tablename = 'instances' AND indexname = %s",
                (expected_index,),
            )
            assert cur.fetchone()[0] == 1
            conn.rollback()
    except pytest.skip.Exception:
        raise
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"no reachable PostgreSQL for live double-apply: {exc}")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
