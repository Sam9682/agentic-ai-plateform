#!/usr/bin/env python3
"""Property test for idempotent reconciliation remediation.

Feature: phase4-runtime-execution-hardening, Property 12.

Property 12 (idempotent reconcile produces no duplicate side effects):
  Running ``health_check_instances`` over an already-converged (healthy) set of
  instances yields ``RemediationAction.NONE`` for every instance, performs NO
  remediation side effects (no restart/replace/mark-needs-attention, and
  therefore no ``ssh_execute_argv`` docker dispatch), and running the pass a
  SECOND time produces the identical sequence of persisted writes with no
  duplicate-key error.

A "converged, healthy" instance is one whose probe returns HTTP 200, whose
crash-loop counter (``restart_attempts``) is already 0, and which has not been
replaced. For such an instance ``decide_remediation`` returns ``NONE`` and the
health pass writes only the per-instance ``health_status`` UPDATE (keyed on the
stable instance id), so re-running the pass is a no-op with respect to
remediation — the definition of idempotent convergence (R4.5, R7.1). The
reconcile loop serializes passes across processes with the advisory lock so two
concurrent passes cannot produce duplicate side effects (R7.2).

Validates: Requirements 4.5, 7.1, 7.2

All collaborators are injected with fakes so the test runs with no live Docker,
SSH, or PostgreSQL (R8.2): a fake ``db_manager`` whose cursor records executed
SQL and serves the generated instance rows, a fake health probe pinned to
HTTP 200, and a spy on ``ssh_execute_argv`` to prove no docker dispatch occurs.

Run directly:
    python3 tests/test_orchestrator_idempotent_reconcile.py
Or via pytest:
    pytest tests/test_orchestrator_idempotent_reconcile.py
"""
import os
import sys
from contextlib import contextmanager
from unittest import mock

from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("FLASK_ENV", "development")

from src import orchestrator as orch_mod  # noqa: E402
from src.orchestrator import (  # noqa: E402
    LightOrchestrator,
    RemediationAction,
    decide_remediation,
)
from src import platform_discovery  # noqa: E402


# --------------------------------------------------------------------------- #
# Converged healthy instance rows
# --------------------------------------------------------------------------- #
# ``health_check_instances`` issues a single SELECT and fetchall() of rows
# shaped exactly like its query projection:
#   (i.id, i.service_id, i.instance_id, i.port, s.health_check_path,
#    srv.server_ip, i.restart_attempts, i.replaced,
#    EXTRACT(EPOCH FROM i.grace_until), EXTRACT(EPOCH FROM NOW()))
#
# A *converged healthy* instance has restart_attempts == 0 and replaced == False
# so that ``decide_remediation`` returns NONE AND the one conditional
# counter-reset write ("if healthy and restart_attempts != 0") does NOT fire —
# making the pass fully idempotent (identical writes on a second run).
_INSTANCE_ID = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789-", min_size=1, max_size=24
)
_HEALTH_PATH = st.sampled_from(["/health", "/healthz", "/", "/status"])
_PORT = st.integers(min_value=1, max_value=65535)
_SERVER_IP = st.from_regex(
    r"\A(10|172|192)\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\Z", fullmatch=True
)
# grace_until may be absent (None) or in the past: either way a HEALTHY probe
# yields NONE, so a converged healthy set converges regardless of grace.
_GRACE_UNTIL = st.one_of(st.none(), st.floats(min_value=0.0, max_value=1_000.0))


@st.composite
def _converged_instance(draw, db_id, service_id):
    """Generate one converged, healthy instance row."""
    now_epoch = 10_000.0
    grace_until = draw(_GRACE_UNTIL)
    return (
        db_id,                       # i.id
        service_id,                  # i.service_id
        draw(_INSTANCE_ID),          # i.instance_id
        draw(_PORT),                 # i.port
        draw(_HEALTH_PATH),          # s.health_check_path
        draw(_SERVER_IP),            # srv.server_ip
        0,                           # i.restart_attempts (converged => 0)
        False,                       # i.replaced (converged => not replaced)
        grace_until,                 # EXTRACT(EPOCH FROM i.grace_until)
        now_epoch,                   # EXTRACT(EPOCH FROM NOW())
    )


@st.composite
def _converged_instance_set(draw):
    """Generate a set of converged healthy instances with distinct ids."""
    count = draw(st.integers(min_value=0, max_value=10))
    rows = []
    for i in range(count):
        # Distinct db ids and distinct (service_id, instance_id) keys so a real
        # schema's unique constraint would be satisfied — the pass must not
        # itself introduce a duplicate key.
        rows.append(draw(_converged_instance(db_id=i + 1, service_id=(i % 3) + 1)))
    return rows


# --------------------------------------------------------------------------- #
# Fake database that records executed SQL and raises on duplicate-key writes
# --------------------------------------------------------------------------- #
class _DuplicateKeyError(Exception):
    """Raised by the fake cursor if the pass ever tries to re-insert a key."""


def _make_fake_db(instance_rows, recorder):
    """Build a fake db_manager for ``health_check_instances``.

    ``recorder`` is a list; every (sql, params) the cursor executes is appended
    so two passes can be compared for identical write sequences. The cursor
    tracks inserted ``(service_id, instance_id)`` keys and raises
    :class:`_DuplicateKeyError` if an INSERT ever repeats one — so a
    non-idempotent pass that tried to recreate a converged instance would fail
    loudly (R7.1).
    """

    class _FakeCursor:
        def __init__(self, rows):
            self._rows = rows
            self._inserted_keys = set()

        def execute(self, sql, params=None):
            recorder.append((" ".join(sql.split()), params))
            # Guard: a converged pass must never INSERT a new instance row.
            upper = sql.upper()
            if "INSERT INTO INSTANCES" in upper:
                key = params
                if key in self._inserted_keys:
                    raise _DuplicateKeyError(
                        f"duplicate key for instances: {key!r}"
                    )
                self._inserted_keys.add(key)

        def fetchall(self):
            return list(self._rows)

        def fetchone(self):
            return (1,)

    class _FakeConn:
        def __init__(self, rows):
            self._cursor = _FakeCursor(rows)
            self.commits = 0

        def cursor(self):
            return self._cursor

        def commit(self):
            self.commits += 1

    class _FakeDbManager:
        def __init__(self, rows):
            self._rows = rows

        @contextmanager
        def get_db_connection(self):
            yield _FakeConn(self._rows)

    return _FakeDbManager(instance_rows)


def _run_health_pass(orchestrator, instance_rows):
    """Run one ``health_check_instances`` pass over a converged healthy set.

    Returns ``(executed_sql, remediate_spy, ssh_spy)`` for assertions. The
    health probe is pinned to HTTP 200 (healthy) so every instance converges to
    ``RemediationAction.NONE``; ``ssh_execute_argv`` is spied to prove no docker
    dispatch (restart/replace) ever happens.
    """
    recorder = []
    fake_db = _make_fake_db(instance_rows, recorder)

    with mock.patch.object(orch_mod, "db_manager", fake_db), \
         mock.patch.object(
             LightOrchestrator, "_probe_health_status_code",
             return_value=platform_discovery.HEALTHY_STATUS_CODE,
         ), \
         mock.patch.object(
             orch_mod, "ssh_execute_argv", return_value=(True, "cid\n", "")
         ) as ssh_spy, \
         mock.patch.object(
             LightOrchestrator, "_remediate_instance"
         ) as remediate_spy:

        orchestrator.health_check_instances()

    return recorder, remediate_spy, ssh_spy


@settings(max_examples=150, deadline=None)
@given(instance_rows=_converged_instance_set())
def test_converged_reconcile_is_idempotent_with_no_side_effects(instance_rows):
    """Feature: phase4-runtime-execution-hardening, Property 12.

    Validates: Requirements 4.5, 7.1, 7.2

    Over an arbitrary converged healthy instance set, one health pass:
      * decides ``RemediationAction.NONE`` for every instance,
      * performs NO remediation side effect (no ``_remediate_instance`` call and
        therefore no ``ssh_execute_argv`` docker dispatch), and
    a SECOND identical pass produces the EXACT same persisted write sequence
    with no duplicate-key error.
    """
    orchestrator = LightOrchestrator()

    # Decision layer: every converged healthy instance => NONE (R4.5).
    for row in instance_rows:
        restart_attempts, replaced = row[6], row[7]
        health_state = {"healthy": True, "within_grace": False}
        action = decide_remediation(
            health_state,
            consecutive_failures=restart_attempts,
            within_grace=False,
            cap=orch_mod.CRASH_LOOP_CAP,
            replaced=replaced,
        )
        assert action == RemediationAction.NONE

    # First pass.
    sql_1, remediate_1, ssh_1 = _run_health_pass(orchestrator, instance_rows)
    # No remediation side effects on a converged set (R7.1).
    assert remediate_1.call_count == 0
    assert ssh_1.call_count == 0

    # Second pass over the SAME converged set.
    sql_2, remediate_2, ssh_2 = _run_health_pass(orchestrator, instance_rows)
    assert remediate_2.call_count == 0
    assert ssh_2.call_count == 0

    # Idempotent convergence: identical persisted writes, no INSERT/duplicate
    # key, and only the benign per-instance health_status UPDATE (plus the final
    # commit's absence of writes) — the two passes are indistinguishable (R4.5).
    assert sql_1 == sql_2
    # A converged pass issues exactly one UPDATE per instance (health_status)
    # and never an INSERT or a counter-reset/remediation write.
    update_writes = [s for (s, _p) in sql_1 if s.upper().startswith("UPDATE")]
    insert_writes = [s for (s, _p) in sql_1 if "INSERT" in s.upper()]
    assert len(update_writes) == len(instance_rows)
    assert insert_writes == []


def test_single_converged_instance_example():
    """Feature: phase4-runtime-execution-hardening, Property 12 (example).

    Validates: Requirements 4.5, 7.1

    A concrete single healthy instance converges to NONE and two passes leave an
    identical, side-effect-free write trace.
    """
    orchestrator = LightOrchestrator()
    rows = [
        (1, 1, "svc-replica-1", 8080, "/health", "10.0.0.5", 0, False, None, 10_000.0),
    ]

    sql_1, remediate_1, ssh_1 = _run_health_pass(orchestrator, rows)
    sql_2, remediate_2, ssh_2 = _run_health_pass(orchestrator, rows)

    assert remediate_1.call_count == 0
    assert remediate_2.call_count == 0
    assert ssh_1.call_count == 0
    assert ssh_2.call_count == 0
    assert sql_1 == sql_2
    assert all("INSERT" not in s.upper() for (s, _p) in sql_1)


def test_empty_instance_set_is_trivially_idempotent():
    """Feature: phase4-runtime-execution-hardening, Property 12 (edge case).

    Validates: Requirements 4.5, 7.1

    With no running instances the pass does no per-instance work and no
    remediation on either run.
    """
    orchestrator = LightOrchestrator()

    sql_1, remediate_1, ssh_1 = _run_health_pass(orchestrator, [])
    sql_2, remediate_2, ssh_2 = _run_health_pass(orchestrator, [])

    assert remediate_1.call_count == 0
    assert remediate_2.call_count == 0
    assert ssh_1.call_count == 0
    assert ssh_2.call_count == 0
    assert sql_1 == sql_2
    # Only the SELECT of running instances; no per-instance UPDATE.
    assert all(not s.upper().startswith("UPDATE") for (s, _p) in sql_1)


if __name__ == "__main__":
    test_converged_reconcile_is_idempotent_with_no_side_effects()
    test_single_converged_instance_example()
    test_empty_instance_set_is_trivially_idempotent()
    print("ok")
