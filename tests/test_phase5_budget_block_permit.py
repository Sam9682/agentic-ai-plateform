#!/usr/bin/env python3
"""Property test for budget block-on-exceed / permit-within.

Feature: phase5-obs-supervisor, Property 14

Property 14: Budget blocks on exceed, permits within.
``budget_check`` aggregates the separately-stored ``estimated_cost`` of every
cost record in a delegation chain and compares the total against a configured
``ceiling``. The call permits (``within == True``) when the aggregate does not
exceed the ceiling and blocks/escalates (``within == False``) when it would
exceed. The boundary ``total == ceiling`` permits. The returned ``total`` equals
the independent sum of each record's ``estimated_cost``.

Validates: Requirements 11.2, 11.3

Run directly:
    .venv/bin/python -m pytest tests/test_phase5_budget_block_permit.py -q
"""
import math
import os
import sys

from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.aro.supervisor import budget_check  # noqa: E402

# Bounded, finite, non-negative costs so the aggregate and the independent
# oracle sum stay well-defined and float-comparable.
_COSTS = st.floats(
    min_value=0.0, max_value=1e6, allow_nan=False, allow_infinity=False
)
_CEILINGS = st.floats(
    min_value=0.0, max_value=1e9, allow_nan=False, allow_infinity=False
)


def _cost_record(cost):
    """A cost record shaped like an ``agent_cost_records`` row for the chain."""
    return {"estimated_cost": cost}


def _cost_records():
    """Random lists of cost records (may be empty)."""
    return st.lists(st.builds(_cost_record, cost=_COSTS), min_size=0, max_size=20)


@settings(max_examples=200)
@given(records=_cost_records(), ceiling=_CEILINGS)
def test_within_iff_total_not_exceeding_ceiling(records, ceiling):
    """R11.2/R11.3: within is True iff the summed cost is <= the ceiling."""
    result = budget_check(records, ceiling)

    # Independent oracle: the aggregate the function should be comparing.
    oracle_total = round(sum(r["estimated_cost"] for r in records), 6)
    expected_within = oracle_total <= float(ceiling)

    assert result["within"] is expected_within, (
        f"within {result['within']!r} but oracle total {oracle_total!r} "
        f"vs ceiling {float(ceiling)!r} expected within={expected_within!r}"
    )


@settings(max_examples=200)
@given(records=_cost_records(), ceiling=_CEILINGS)
def test_total_equals_independent_sum(records, ceiling):
    """R11.2: the returned total equals the independent sum of records."""
    result = budget_check(records, ceiling)

    oracle_total = round(sum(r["estimated_cost"] for r in records), 6)
    assert math.isclose(
        result["total"], oracle_total, rel_tol=1e-9, abs_tol=1e-6
    ), f"total {result['total']!r} != independent sum {oracle_total!r}"
    assert math.isclose(result["ceiling"], float(ceiling), rel_tol=1e-9, abs_tol=1e-6)


@settings(max_examples=200)
@given(records=_cost_records())
def test_boundary_total_equals_ceiling_permits(records):
    """R11.3: the boundary total == ceiling permits (within is True)."""
    # Set the ceiling exactly to the aggregate so total == ceiling.
    ceiling = round(sum(r["estimated_cost"] for r in records), 6)
    result = budget_check(records, ceiling)

    assert result["within"] is True, (
        f"boundary total == ceiling ({ceiling!r}) should permit, "
        f"got within={result['within']!r}"
    )


@settings(max_examples=200)
@given(records=_cost_records(), over=st.floats(
    min_value=1e-3, max_value=1e6, allow_nan=False, allow_infinity=False
))
def test_exceed_blocks(records, over):
    """R11.2: a ceiling strictly below the aggregate blocks (within False)."""
    total = round(sum(r["estimated_cost"] for r in records), 6)
    # A ceiling set below the aggregate by a positive margin must block.
    ceiling = total - over
    result = budget_check(records, ceiling)

    assert result["within"] is False, (
        f"total {total!r} exceeds ceiling {ceiling!r} should block, "
        f"got within={result['within']!r}"
    )
