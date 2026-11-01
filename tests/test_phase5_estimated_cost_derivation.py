#!/usr/bin/env python3
"""Property test for estimated-cost derivation from the rate card.

Feature: phase5-obs-supervisor, Property 9

Property 9: Estimated cost derives from the rate card.
``compute_cost`` sets ``estimated_cost = sum(value * rate)`` over the present
usage dimensions, stored separately from the measured ``usage`` values. The
derivation is proportional: scaling every present dimension's value by a factor
``k`` scales ``estimated_cost`` by ``k``.

Validates: Requirements 4.6, 4.7

Run directly:
    .venv/bin/python -m pytest tests/test_phase5_estimated_cost_derivation.py -q
"""
import math
import os
import sys

from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.obs.obs_cost import USAGE_DIMS, UsageDim, compute_cost  # noqa: E402

# Bounded, finite floats (no NaN/inf) so the derivation and the independent
# reference sum stay well-defined and float-comparable.
_VALUES = st.floats(
    min_value=0.0, max_value=1e6, allow_nan=False, allow_infinity=False
)
_RATES = st.floats(
    min_value=0.0, max_value=1e3, allow_nan=False, allow_infinity=False
)


def _usage_dims():
    """A subset of the known usage dims, each with a value + measured flag."""
    return st.dictionaries(
        keys=st.sampled_from(USAGE_DIMS),
        values=st.builds(UsageDim, value=_VALUES, measured=st.booleans()),
        min_size=0,
        max_size=len(USAGE_DIMS),
    )


def _rate_card():
    """A rate card that may omit some dims (unknown rate -> 0.0 contribution)."""
    return st.dictionaries(
        keys=st.sampled_from(USAGE_DIMS),
        values=_RATES,
        min_size=0,
        max_size=len(USAGE_DIMS),
    )


@settings(max_examples=200)
@given(usage_dims=_usage_dims(), rate_card=_rate_card())
def test_estimated_cost_equals_rate_card_sum(usage_dims, rate_card):
    """R4.6: estimated_cost == sum(value * rate) over present dims (rounded)."""
    result = compute_cost(usage_dims, rate_card)

    expected = round(
        sum(dim.value * rate_card.get(name, 0.0) for name, dim in usage_dims.items()),
        6,
    )
    assert math.isclose(
        result["estimated_cost"], expected, rel_tol=1e-9, abs_tol=1e-6
    ), f"estimated_cost {result['estimated_cost']!r} != reference sum {expected!r}"


@settings(max_examples=200)
@given(usage_dims=_usage_dims(), rate_card=_rate_card())
def test_usage_preserved_separately_from_estimated_cost(usage_dims, rate_card):
    """R4.7: measured usage values are preserved separately from the cost."""
    result = compute_cost(usage_dims, rate_card)

    usage = result["usage"]
    assert set(usage.keys()) == set(usage_dims.keys())
    for name, dim in usage_dims.items():
        assert usage[name]["value"] == dim.value
        assert usage[name]["measured"] == dim.measured
    # estimated_cost is a scalar stored apart from the per-dim usage mapping.
    # (An all-zero sum rounds to the int 0, so accept any real number here —
    # the point of R4.7 is separation from usage, not a specific numeric type.)
    assert isinstance(result["estimated_cost"], (int, float))
    assert not isinstance(result["estimated_cost"], bool)
    assert "estimated_cost" not in usage


@settings(max_examples=200)
@given(
    usage_dims=_usage_dims(),
    rate_card=_rate_card(),
    k=st.floats(min_value=0.0, max_value=1e3, allow_nan=False, allow_infinity=False),
)
def test_scaling_values_scales_cost_proportionally(usage_dims, rate_card, k):
    """R4.6: scaling every dim value by k scales estimated_cost by k."""
    scaled_dims = {
        name: UsageDim(value=dim.value * k, measured=dim.measured)
        for name, dim in usage_dims.items()
    }
    scaled = compute_cost(scaled_dims, rate_card)["estimated_cost"]

    # The underlying derivation is linear: scaling every value by k scales the
    # raw sum by k. Compare against the raw sum scaled and rounded once. Because
    # compute_cost rounds to 6 decimals on each independent call, allow a
    # tolerance covering the rounding step applied to each side (~1e-6, grown by
    # k for the scaled side) so large-but-finite costs stay comparable.
    raw = sum(dim.value * rate_card.get(name, 0.0) for name, dim in usage_dims.items())
    expected = round(raw * k, 6)
    tol = 2e-6 + 1e-6 * abs(k)
    assert math.isclose(scaled, expected, rel_tol=1e-9, abs_tol=tol), (
        f"scaled cost {scaled!r} != raw {raw!r} * k {k!r} rounded = {expected!r}"
    )
