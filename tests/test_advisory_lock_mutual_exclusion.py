#!/usr/bin/env python3
"""Property test for advisory-lock mutual exclusion.

Feature: phase4-runtime-execution-hardening, Property 9.

Property 9: Advisory-lock mutual exclusion.
  * A blocking acquire issues ``pg_advisory_lock`` and always acquires
    (Requirement 3.4: a reconciliation pass holds the lock while it runs).
  * A non-blocking acquire issues ``pg_try_advisory_lock`` and yields
    ``acquired=False`` — i.e. *skips* — when another session already holds the
    lock (Requirement 3.5 / 7.2 / 7.3: a concurrent reconcile is skipped rather
    than racing, so no duplicate side effects can occur).
  * A lock that was acquired is ALWAYS released via ``pg_advisory_unlock`` in
    the context manager's ``finally`` block — even if the critical section
    raises — and a failed non-blocking try never issues a spurious unlock.
  * ``reconcile_lock_key(scope)`` is a deterministic pure function: the same
    scope always derives the same signed 64-bit key, so separate processes
    contend on the *same* advisory lock (Requirement 7.2 / 7.3).

Validates: Requirements 3.4, 3.5, 7.2, 7.3

The test uses a fake connection whose cursor merely records the
``pg_advisory_lock`` / ``pg_try_advisory_lock`` / ``pg_advisory_unlock`` SQL it
is handed (no live PostgreSQL — Requirement 8.3). A shared boolean models a
single "server" holding the lock so a non-blocking try observes contention.

Run directly:
    python3 tests/test_advisory_lock_mutual_exclusion.py
Or via pytest:
    pytest tests/test_advisory_lock_mutual_exclusion.py
"""
import os
import sys

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.advisory_lock import (  # noqa: E402
    _INT64_MAX,
    _INT64_MIN,
    advisory_lock,
    reconcile_lock_key,
)


class _FakeCursor:
    """A cursor that records the advisory-lock SQL it is asked to execute.

    It models a *single* advisory lock owned by a shared ``LockState`` so that
    ``pg_try_advisory_lock`` observes real contention: it returns truthy only
    when the lock is free, and ``pg_advisory_lock`` always "succeeds" (a real
    blocking acquire waits, which we represent as immediate success because the
    fake never actually contends with a live concurrent holder within one
    process).
    """

    def __init__(self, state):
        self._state = state
        self._last_row = None

    def execute(self, sql, params=()):
        self._state.calls.append((sql, tuple(params)))
        if "pg_try_advisory_lock" in sql:
            if self._state.held:
                self._last_row = (False,)
            else:
                self._state.held = True
                self._last_row = (True,)
        elif "pg_advisory_lock" in sql:
            # Blocking acquire: always eventually acquires.
            self._state.held = True
            self._last_row = (True,)
        elif "pg_advisory_unlock" in sql:
            self._state.held = False
            self._last_row = (True,)
        else:  # pragma: no cover - the module only issues the three above
            self._last_row = None

    def fetchone(self):
        return self._last_row


class _LockState:
    """Shared, in-process model of one advisory lock plus a call log."""

    def __init__(self, held=False):
        self.held = held
        self.calls = []

    def sql_calls(self):
        return [sql for sql, _params in self.calls]


class _FakeConn:
    """A fake connection handing out cursors bound to a shared ``_LockState``."""

    def __init__(self, state):
        self._state = state

    def cursor(self):
        return _FakeCursor(self._state)


def _count(state, fragment):
    return sum(1 for sql in state.sql_calls() if fragment in sql)


# ---------------------------------------------------------------------------
# Property 9 — blocking acquire uses pg_advisory_lock and always acquires,
# then always releases in finally.
# ---------------------------------------------------------------------------
@given(key=st.integers(min_value=_INT64_MIN, max_value=_INT64_MAX))
@settings(max_examples=200)
def test_blocking_acquire_locks_and_releases(key):
    """Blocking acquire issues pg_advisory_lock and releases in finally.

    Feature: phase4-runtime-execution-hardening, Property 9.
    Validates: Requirements 3.4, 7.2, 7.3
    """
    state = _LockState(held=False)
    conn = _FakeConn(state)

    with advisory_lock(conn, key, blocking=True) as acquired:
        assert acquired is True
        assert state.held is True
        # The blocking path must use pg_advisory_lock, never the try variant.
        assert _count(state, "pg_try_advisory_lock") == 0
        assert _count(state, "SELECT pg_advisory_lock(%s)") == 1
        # Acquire issued with exactly the requested key.
        assert (("SELECT pg_advisory_lock(%s)", (key,))) in state.calls

    # Released in finally: lock free again and exactly one unlock issued.
    assert state.held is False
    assert _count(state, "pg_advisory_unlock") == 1
    assert (("SELECT pg_advisory_unlock(%s)", (key,))) in state.calls


# ---------------------------------------------------------------------------
# Property 9 — non-blocking try SKIPS when the lock is already held, and never
# issues a spurious unlock for a lock it did not acquire.
# ---------------------------------------------------------------------------
@given(key=st.integers(min_value=_INT64_MIN, max_value=_INT64_MAX))
@settings(max_examples=200)
def test_nonblocking_try_skips_when_held(key):
    """A non-blocking try yields acquired=False when the lock is held.

    Feature: phase4-runtime-execution-hardening, Property 9.
    Validates: Requirements 3.5, 7.2, 7.3

    This is the mutual-exclusion guarantee: while one process holds the lock, a
    second process's try-lock skips rather than operating on the same
    instances. A skipped try must NOT release the lock the other holder owns.
    """
    state = _LockState(held=True)  # another session already holds it
    conn = _FakeConn(state)

    with advisory_lock(conn, key, blocking=False) as acquired:
        assert acquired is False
        # It used the try variant, not the blocking acquire.
        assert _count(state, "pg_try_advisory_lock") == 1
        assert _count(state, "SELECT pg_advisory_lock(%s)") == 0
        # The lock remains held by the other session.
        assert state.held is True

    # A failed try must never issue an unlock (no spurious release).
    assert _count(state, "pg_advisory_unlock") == 0
    assert state.held is True


# ---------------------------------------------------------------------------
# Property 9 — non-blocking try ACQUIRES when the lock is free and releases it.
# ---------------------------------------------------------------------------
@given(key=st.integers(min_value=_INT64_MIN, max_value=_INT64_MAX))
@settings(max_examples=200)
def test_nonblocking_try_acquires_when_free_and_releases(key):
    """A non-blocking try acquires a free lock and releases it in finally.

    Feature: phase4-runtime-execution-hardening, Property 9.
    Validates: Requirements 3.5, 7.2, 7.3
    """
    state = _LockState(held=False)
    conn = _FakeConn(state)

    with advisory_lock(conn, key, blocking=False) as acquired:
        assert acquired is True
        assert state.held is True
        assert _count(state, "pg_try_advisory_lock") == 1

    assert state.held is False
    assert _count(state, "pg_advisory_unlock") == 1


# ---------------------------------------------------------------------------
# Property 9 — the acquired lock is released even when the critical section
# raises (the finally guarantee).
# ---------------------------------------------------------------------------
@given(
    key=st.integers(min_value=_INT64_MIN, max_value=_INT64_MAX),
    blocking=st.booleans(),
)
@settings(max_examples=200)
def test_acquired_lock_released_even_on_exception(key, blocking):
    """An acquired lock is always released in finally, even on error.

    Feature: phase4-runtime-execution-hardening, Property 9.
    Validates: Requirements 3.4, 3.5, 7.2, 7.3
    """
    state = _LockState(held=False)
    conn = _FakeConn(state)

    class _Boom(Exception):
        pass

    with pytest.raises(_Boom):
        with advisory_lock(conn, key, blocking=blocking) as acquired:
            assert acquired is True
            assert state.held is True
            raise _Boom("critical section failed")

    # Despite the exception, the lock was released exactly once.
    assert state.held is False
    assert _count(state, "pg_advisory_unlock") == 1


# ---------------------------------------------------------------------------
# Property 9 — a skipped try that raises inside the (skipped) body still issues
# NO unlock, because nothing was acquired.
# ---------------------------------------------------------------------------
@given(key=st.integers(min_value=_INT64_MIN, max_value=_INT64_MAX))
@settings(max_examples=200)
def test_skipped_try_never_unlocks_even_on_exception(key):
    """A skipped non-blocking try never unlocks, even if the body raises.

    Feature: phase4-runtime-execution-hardening, Property 9.
    Validates: Requirements 3.5, 7.2, 7.3
    """
    state = _LockState(held=True)  # held by another session
    conn = _FakeConn(state)

    class _Boom(Exception):
        pass

    with pytest.raises(_Boom):
        with advisory_lock(conn, key, blocking=False) as acquired:
            assert acquired is False
            raise _Boom("body still ran but we did not own the lock")

    # No unlock issued; the other session still holds the lock.
    assert _count(state, "pg_advisory_unlock") == 0
    assert state.held is True


# ---------------------------------------------------------------------------
# Property 9 — reconcile_lock_key is deterministic across calls and in range,
# so separate processes contend on the same lock.
# ---------------------------------------------------------------------------
@given(scope=st.text(min_size=0, max_size=64))
@settings(max_examples=200)
def test_reconcile_lock_key_is_deterministic_and_in_range(scope):
    """reconcile_lock_key(scope) is a deterministic, in-range pure function.

    Feature: phase4-runtime-execution-hardening, Property 9.
    Validates: Requirements 7.2, 7.3

    The same scope always maps to the same signed 64-bit key, so a lock derived
    in one process matches the lock derived in another. Distinct scopes may
    differ; equal scopes must never differ.
    """
    k1 = reconcile_lock_key(scope)
    k2 = reconcile_lock_key(scope)
    assert k1 == k2, "key derivation must be deterministic for a fixed scope"
    assert _INT64_MIN <= k1 <= _INT64_MAX, "key must fit PostgreSQL signed bigint"
    assert isinstance(k1, int)


@given(a=st.text(min_size=0, max_size=32), b=st.text(min_size=0, max_size=32))
@settings(max_examples=200)
def test_reconcile_lock_key_equal_scopes_match_distinct_may_differ(a, b):
    """Equal scopes produce equal keys; the derivation is a function of scope.

    Feature: phase4-runtime-execution-hardening, Property 9.
    Validates: Requirements 7.2, 7.3
    """
    if a == b:
        assert reconcile_lock_key(a) == reconcile_lock_key(b)
    # The default scope is stable too.
    assert reconcile_lock_key() == reconcile_lock_key("global")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
