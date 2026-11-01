#!/usr/bin/env python3
"""Property test for heartbeat keeping a lease live (Task 13.5).

Feature: ARO durable task queue — lease renewal / reaper safety.

Covers ``task_repository.heartbeat(tenant_id, task_id, *, lease_ttl=...)``: a
claimed/running task's lease is renewed to ``now + lease_ttl`` on every beat and
``heartbeat_at`` is stamped to ``now`` (Req 6.5). The invariant this property
pins down is the one the reaper (Req 6.6/6.7) relies on for liveness: a worker
that keeps heart-beating at an interval SHORTER than ``lease_ttl`` always holds a
lease whose ``lease_expires_at`` is strictly in the future, so the reaper never
reclaims a live task.

The arithmetic: at modeled time ``t`` a beat writes ``lease_expires_at =
t + lease_ttl``. The next beat happens at ``t + interval``; because
``interval < lease_ttl`` we have ``t + interval < t + lease_ttl``, i.e. the
lease written at ``t`` is still in the future at the moment of the next beat.
Inductively this holds across the whole sequence of beats.

Two complementary properties are asserted:

* The pure arithmetic invariant over a controllable clock and a sequence of
  heartbeats with ``interval < lease_ttl`` (the clear invariant form).
* The same invariant driving the REAL ``heartbeat()`` against an injected fake
  db (via monkeypatching ``_get_db``) whose ``execute_query`` evaluates the
  lease SQL against a controllable "now", confirming the expiry it computes is
  always strictly greater than the current modeled time.

Run directly:
    python3 tests/test_aro_heartbeat_lease.py
Or via pytest:
    pytest tests/test_aro_heartbeat_lease.py
"""
import os
import sys

from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.aro import task_repository as task_repo  # noqa: E402


# --------------------------------------------------------------------------- #
# Strategies: a lease_ttl (seconds), a heartbeat interval strictly shorter than
# the ttl, and the number of beats. Times are modeled as integer seconds on a
# monotone clock so the arithmetic is exact (no float drift). The real
# heartbeat() clamps lease_ttl to >= 1, so we keep ttl >= 2 to leave room for a
# positive interval strictly below it.
# --------------------------------------------------------------------------- #
_LEASE_TTL = st.integers(min_value=2, max_value=3600)
_NUM_BEATS = st.integers(min_value=1, max_value=50)
_START = st.integers(min_value=0, max_value=1_000_000)
_IDS = st.integers(min_value=1, max_value=10_000)


@st.composite
def _ttl_and_interval(draw):
    """A (lease_ttl, interval) pair with ``1 <= interval < lease_ttl``."""
    lease_ttl = draw(_LEASE_TTL)
    interval = draw(st.integers(min_value=1, max_value=lease_ttl - 1))
    return lease_ttl, interval


# --------------------------------------------------------------------------- #
# Property 25 (pure arithmetic form): heartbeat keeps a live lease in the future
# Validates: Requirements 6.5
# --------------------------------------------------------------------------- #
@given(ti=_ttl_and_interval(), num_beats=_NUM_BEATS, start=_START)
@settings(max_examples=200)
def test_heartbeat_lease_stays_in_future_pure(ti, num_beats, start):
    """Feature: phase2-aro-completion, Property 25: Heartbeat keeps a live lease
    in the future.

    Modeling ``now`` with a controllable clock: beating at a fixed interval
    strictly shorter than ``lease_ttl``, the lease written by each beat is still
    strictly in the future at the moment of the following beat (and the reaper,
    which reclaims only when ``lease_expires_at < now``, would never reclaim it).
    Validates Req 6.5.
    """
    lease_ttl, interval = ti
    assert interval < lease_ttl  # generator invariant

    now = start
    prev_expiry = None
    for _ in range(num_beats):
        # A beat at the current modeled time sets the lease ttl seconds out.
        lease_expires_at = now + lease_ttl

        # At the moment of this beat the lease is strictly in the future.
        assert lease_expires_at > now

        # The lease written on the PREVIOUS beat must still be live now (the
        # core no-reclaim invariant): since the previous beat was one interval
        # ago and interval < lease_ttl, prev_expiry > now.
        if prev_expiry is not None:
            assert prev_expiry > now, (
                f"stale lease: prev_expiry={prev_expiry} not > now={now} "
                f"(ttl={lease_ttl}, interval={interval})"
            )

        prev_expiry = lease_expires_at
        now += interval

    # `now` now points one interval past the final beat (the time the next beat
    # WOULD occur). The lease written by the final beat must still be strictly
    # in the future there, since interval < lease_ttl — i.e. a continuously
    # beating worker is never reclaimable by the reaper. This is the decisive
    # end-state check (Req 6.5).
    assert prev_expiry > now, (
        f"final lease not live at next beat: prev_expiry={prev_expiry} "
        f"not > now={now} (ttl={lease_ttl}, interval={interval})"
    )


# --------------------------------------------------------------------------- #
# Property 25 (real-function form): drive heartbeat() with an injected fake db
# whose execute_query evaluates the lease SQL against a controllable "now".
# Validates: Requirements 6.5
# --------------------------------------------------------------------------- #
class _FakeDb:
    """Minimal db double that evaluates heartbeat()'s UPDATE against a clock.

    It recognizes the lease-renewal UPDATE, extracts the ``lease_ttl`` bound
    parameter, and computes ``lease_expires_at = now + lease_ttl`` and
    ``heartbeat_at = now`` against the injected ``now`` (modeled seconds). Any
    matching claimed/running row returns a truthy rowcount so heartbeat() reports
    success. The computed expiry is recorded for the test to assert on.
    """

    def __init__(self, now, *, status="claimed"):
        self.now = now
        self.status = status
        self.last_lease_expires_at = None
        self.last_heartbeat_at = None
        self.calls = 0

    def execute_query(self, sql, params=None, fetch_one=False, fetch_all=False):
        self.calls += 1
        assert "UPDATE agent_tasks" in sql
        assert "lease_expires_at" in sql and "heartbeat_at" in sql
        # heartbeat() passes params as (lease_ttl, tenant_id, task_id).
        lease_ttl = int(params[0])
        # Model the SQL "CURRENT_TIMESTAMP + ttl * INTERVAL '1 second'".
        self.last_lease_expires_at = self.now + lease_ttl
        self.last_heartbeat_at = self.now
        # Row matches only when claimed/running (mirrors the WHERE clause).
        return 1 if self.status in ("claimed", "running") else 0


@given(
    ti=_ttl_and_interval(),
    num_beats=_NUM_BEATS,
    start=_START,
    tenant_id=_IDS,
    task_id=_IDS,
)
@settings(max_examples=200)
def test_heartbeat_real_function_expiry_in_future(ti, num_beats, start, tenant_id,
                                                  task_id):
    """Feature: phase2-aro-completion, Property 25: Heartbeat keeps a live lease
    in the future.

    Driving the REAL ``task_repository.heartbeat`` against a fake db bound to a
    controllable clock: every beat returns success and computes a
    ``lease_expires_at`` strictly greater than the modeled ``now`` at the beat,
    and the lease from the previous beat is still in the future at the next beat
    because the interval is strictly shorter than ``lease_ttl``. Validates Req
    6.5.
    """
    lease_ttl, interval = ti
    now = start
    prev_expiry = None

    original_get_db = task_repo._get_db
    try:
        for _ in range(num_beats):
            fake = _FakeDb(now)
            task_repo._get_db = lambda fake=fake: fake

            ok = task_repo.heartbeat(tenant_id, task_id, lease_ttl=lease_ttl)

            # A claimed/running row was matched and renewed.
            assert ok is True
            assert fake.calls == 1
            # heartbeat_at stamped to the modeled now; expiry is now + ttl.
            assert fake.last_heartbeat_at == now
            assert fake.last_lease_expires_at == now + lease_ttl
            # Expiry strictly in the future at the moment of this beat.
            assert fake.last_lease_expires_at > now

            # The previous beat's lease is still live at this (later) beat time.
            if prev_expiry is not None:
                assert prev_expiry > now, (
                    f"stale lease via real heartbeat(): prev_expiry={prev_expiry} "
                    f"not > now={now} (ttl={lease_ttl}, interval={interval})"
                )

            prev_expiry = fake.last_lease_expires_at
            now += interval
    finally:
        task_repo._get_db = original_get_db


@given(ti=_ttl_and_interval(), start=_START, tenant_id=_IDS, task_id=_IDS)
@settings(max_examples=100)
def test_heartbeat_non_live_row_not_renewed(ti, start, tenant_id, task_id):
    """Feature: phase2-aro-completion, Property 25: Heartbeat keeps a live lease
    in the future.

    Boundary: heartbeat() only renews a claimed/running row. When the row is in
    any other status the UPDATE matches nothing and heartbeat() returns False,
    so no lease is extended (the reaper path is left intact). Validates the
    tenant-/status-scoped renewal underpinning Req 6.5.
    """
    lease_ttl, _interval = ti
    fake = _FakeDb(start, status="succeeded")
    original_get_db = task_repo._get_db
    try:
        task_repo._get_db = lambda: fake
        ok = task_repo.heartbeat(tenant_id, task_id, lease_ttl=lease_ttl)
    finally:
        task_repo._get_db = original_get_db
    assert ok is False


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
