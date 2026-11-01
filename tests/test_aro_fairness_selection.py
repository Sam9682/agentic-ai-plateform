#!/usr/bin/env python3
"""Property test for per-tenant fairness selection (Phase 2 ARO, Task 13.8).

Feature: phase2-aro-completion, Property 29.

Exercises the pure, deterministic ``pick_next_tenant(pending_by_tenant,
last_served)`` round-robin cursor in ``src/aro/task_repository.py``. This is the
helper ``claim_next_task`` uses to order candidate tasks by
``(tenant_rank, priority, created_at)`` so that one tenant's backlog cannot
starve another's (Req 6.10).

Selection rule under test (pure, no DB):
  * eligible tenants are ordered ascending;
  * ``last_served=None`` (or absent from the ordering) starts from the lowest;
  * otherwise return the first tenant strictly greater than ``last_served``,
    wrapping to the lowest;
  * a mapping ``{tenant_id: count}`` makes only positive-count tenants eligible;
  * an empty input (or all-zero mapping) returns ``None``.

Property 29 (no starvation): starting from ``last_served=None`` and repeatedly
feeding the returned tenant back as ``last_served``, every tenant with pending
work is served within a bounded number of picks (at most N picks for N pending
tenants) and the sequence cycles through all of them; a zero-count tenant is
never returned.

Validates: Requirements 6.10

Run directly:
    python3 tests/test_aro_fairness_selection.py
Or via pytest:
    pytest tests/test_aro_fairness_selection.py -v
"""
import os
import sys

from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.aro.task_repository import pick_next_tenant  # noqa: E402

# Tenant ids are generated as integers so the "ascending order" that the
# round-robin relies on is well defined and easy to cross-check.
tenant_ids = st.integers(min_value=-1000, max_value=1000)


@settings(max_examples=200, deadline=None)
@given(tenants=st.sets(tenant_ids, min_size=1, max_size=12))
def test_every_tenant_served_within_n_picks_no_starvation(tenants):
    """Starting from ``last_served=None`` over N tenants that all have pending
    work, N successive picks serve EVERY tenant exactly once — a full,
    non-starving cycle (bounded by N).

    Feature: phase2-aro-completion, Property 29.
    Validates: Requirements 6.10
    """
    n = len(tenants)
    pending = {t: 1 for t in tenants}

    served = []
    last = None
    for _ in range(n):
        nxt = pick_next_tenant(pending, last)
        assert nxt is not None, "a tenant with pending work must be served"
        served.append(nxt)
        last = nxt

    # Bounded: within N picks every tenant with pending work is served.
    assert set(served) == set(tenants)
    # No tenant served twice before all others are served (true round-robin).
    assert len(served) == n == len(set(served))


@settings(max_examples=200, deadline=None)
@given(tenants=st.sets(tenant_ids, min_size=1, max_size=12))
def test_sequence_cycles_in_ascending_order(tenants):
    """The round-robin walks the eligible tenants in ascending order and then
    wraps, so the serve sequence over one cycle is exactly the sorted tenants.

    Feature: phase2-aro-completion, Property 29.
    Validates: Requirements 6.10
    """
    ordered = sorted(tenants)
    pending = {t: 1 for t in tenants}

    served = []
    last = None
    for _ in range(len(ordered)):
        last = pick_next_tenant(pending, last)
        served.append(last)

    assert served == ordered
    # Wrapping: the next pick after a full cycle returns to the lowest tenant.
    assert pick_next_tenant(pending, last) == ordered[0]


@settings(max_examples=200, deadline=None)
@given(
    data=st.data(),
    tenants=st.sets(tenant_ids, min_size=2, max_size=12),
)
def test_second_cycle_repeats_first_bounded_fairness(data, tenants):
    """Over 2*N picks the serve order is the sorted tenants repeated twice:
    no tenant can be starved while another is served a second time.

    Feature: phase2-aro-completion, Property 29.
    Validates: Requirements 6.10
    """
    ordered = sorted(tenants)
    pending = {t: 1 for t in tenants}

    served = []
    last = None
    for _ in range(2 * len(ordered)):
        last = pick_next_tenant(pending, last)
        served.append(last)

    assert served == ordered + ordered
    # Across any window of N consecutive picks, every tenant appears once.
    start = data.draw(st.integers(min_value=0, max_value=len(ordered)))
    window = served[start:start + len(ordered)]
    assert set(window) == set(tenants)


@settings(max_examples=200, deadline=None)
@given(
    positive=st.sets(tenant_ids, min_size=1, max_size=8),
    zeros=st.sets(tenant_ids, min_size=1, max_size=8),
)
def test_zero_count_tenants_never_served(positive, zeros):
    """In the mapping form, a tenant with a non-positive pending count is never
    returned — it is not eligible even across a full cycle.

    Feature: phase2-aro-completion, Property 29.
    Validates: Requirements 6.10
    """
    # Ensure the zero-count tenants are disjoint from the positive ones so a
    # tenant isn't both pending and empty.
    zeros = zeros - positive
    pending = {t: 1 for t in positive}
    pending.update({t: 0 for t in zeros})

    served = set()
    last = None
    # Walk well past one full cycle to be sure a zero tenant never sneaks in.
    for _ in range(len(positive) + len(zeros) + 2):
        nxt = pick_next_tenant(pending, last)
        assert nxt in positive, "only positive-count tenants are eligible"
        served.add(nxt)
        last = nxt

    for z in zeros:
        assert z not in served
    # Every positive tenant is still reached (no starvation) within the walk.
    assert served == set(positive)


@settings(max_examples=200, deadline=None)
@given(tenants=st.sets(tenant_ids, min_size=1, max_size=12))
def test_iterable_and_mapping_forms_agree(tenants):
    """The iterable form and an all-positive mapping form produce the same
    selection for the same ``last_served`` — the mapping only adds the
    positive-count eligibility filter.

    Feature: phase2-aro-completion, Property 29.
    Validates: Requirements 6.10
    """
    as_list = list(tenants)
    as_map = {t: 1 for t in tenants}

    # First pick (last_served=None) and every subsequent cursor position agree.
    last_list = None
    last_map = None
    for _ in range(len(tenants) + 1):
        pl = pick_next_tenant(as_list, last_list)
        pm = pick_next_tenant(as_map, last_map)
        assert pl == pm
        last_list, last_map = pl, pm


@settings(max_examples=200, deadline=None)
@given(
    tenants=st.sets(tenant_ids, min_size=1, max_size=12),
    unknown=tenant_ids,
)
def test_last_served_absent_starts_from_lowest_or_next_greater(tenants, unknown):
    """When ``last_served`` is not among the pending tenants, the cursor still
    returns the first tenant strictly greater than it (wrapping to the lowest),
    so a stale cursor never starves anyone.

    Feature: phase2-aro-completion, Property 29.
    Validates: Requirements 6.10
    """
    ordered = sorted(tenants)
    pending = {t: 1 for t in tenants}
    nxt = pick_next_tenant(pending, unknown)

    expected = next((t for t in ordered if t > unknown), ordered[0])
    assert nxt == expected


def test_empty_input_returns_none():
    """No pending work (empty iterable or all-zero mapping) returns ``None``.

    Validates: Requirements 6.10
    """
    assert pick_next_tenant([], None) is None
    assert pick_next_tenant(set(), 5) is None
    assert pick_next_tenant({}, None) is None
    assert pick_next_tenant({"a": 0, "b": 0}, None) is None


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([os.path.abspath(__file__), "-v"]))
