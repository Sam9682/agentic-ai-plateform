#!/usr/bin/env python3
"""Property test for cost data-source classification.

Feature: phase5-obs-supervisor, Property 8.

Validates: Requirements 4.2, 4.3, 4.4, 4.5, 14.5.

Task 2.7 (Phase 5, Half A). The pure cost pipeline
``src.obs.obs_cost.compute_cost`` classifies every cost record's provenance
into exactly one of three ``data_source`` labels, based solely on the
``measured`` flags of the *present* usage dimensions (R4.2-R4.5):

  * all present dims measured              -> ``MEASURED``   (R4.3)
  * no present dim measured (incl. empty)  -> ``ESTIMATED``  (R4.2, R4.4)
  * a mix of measured and estimated dims   -> ``MIXED``      (R4.5)

Property 8 (design.md): the classifier is **total** — for any usage_dims map
(including the empty map) and any rate card, ``data_source`` is exactly one of
{MEASURED, ESTIMATED, MIXED} and equals an independent oracle computed directly
from the measured flags of the present dimensions. The empty-dims case
classifies ``ESTIMATED`` with ``estimated_cost == 0.0`` (R4.4, R14.5 totality).

The test generates random usage_dims maps over ``USAGE_DIMS`` (each present dim
a ``UsageDim(value, measured)``), including the empty case, plus a random
rate_card, calls ``compute_cost``, and asserts ``data_source`` matches the
oracle. Pure function; no live Docker, PostgreSQL, SSH, LLM, or ML.

Run directly:
    python3 tests/test_phase5_cost_classification.py
Or via pytest:
    pytest tests/test_phase5_cost_classification.py
"""
import os
import sys

from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.obs.obs_cost import USAGE_DIMS, UsageDim, compute_cost  # noqa: E402


# --------------------------------------------------------------------------- #
# Strategies
# --------------------------------------------------------------------------- #
_VALID_SOURCES = {"MEASURED", "ESTIMATED", "MIXED"}

# Finite, non-NaN usage values (compute_cost never raises on data).
_values = st.floats(
    min_value=0.0, max_value=1e9, allow_nan=False, allow_infinity=False
)

# A usage_dims map keyed by a subset of USAGE_DIMS; each entry a UsageDim.
_usage_dims_strategy = st.dictionaries(
    keys=st.sampled_from(list(USAGE_DIMS)),
    values=st.builds(UsageDim, value=_values, measured=st.booleans()),
    min_size=0,  # include the empty-dims case (R4.4)
    max_size=len(USAGE_DIMS),
)

# A rate card over an arbitrary subset of USAGE_DIMS (missing rate -> 0.0).
_rate_card_strategy = st.dictionaries(
    keys=st.sampled_from(list(USAGE_DIMS)),
    values=st.floats(
        min_value=0.0, max_value=1e3, allow_nan=False, allow_infinity=False
    ),
    min_size=0,
    max_size=len(USAGE_DIMS),
)


def _oracle_data_source(usage_dims):
    """Independent classification derived only from present dims' measured flags."""
    present = {k: v for k, v in usage_dims.items() if v is not None}
    flags = [v.measured for v in present.values()]
    if not flags:
        return "ESTIMATED"
    if all(flags):
        return "MEASURED"
    if any(flags):
        return "MIXED"
    return "ESTIMATED"


@settings(max_examples=200)
@given(usage_dims=_usage_dims_strategy, rate_card=_rate_card_strategy)
def test_data_source_matches_oracle_and_is_total(usage_dims, rate_card):
    """``data_source`` is exactly one of three labels and equals the oracle.

    Validates: Requirements 4.2, 4.3, 4.4, 4.5, 14.5.
    """
    result = compute_cost(usage_dims, rate_card)
    data_source = result["data_source"]

    # Totality: classifier emits exactly one of the three valid labels (R14.5).
    assert data_source in _VALID_SOURCES

    # Correctness: matches the independent oracle over present measured flags
    # (R4.2 ESTIMATED, R4.3 MEASURED, R4.5 MIXED).
    assert data_source == _oracle_data_source(usage_dims)


@settings(max_examples=200)
@given(usage_dims=_usage_dims_strategy, rate_card=_rate_card_strategy)
def test_all_measured_is_measured(usage_dims, rate_card):
    """A non-empty map whose present dims are all measured -> MEASURED (R4.3)."""
    forced = {k: UsageDim(v.value, True) for k, v in usage_dims.items()}
    result = compute_cost(forced, rate_card)
    if forced:
        assert result["data_source"] == "MEASURED"
    else:
        # Empty stays ESTIMATED even after forcing (no present dims).
        assert result["data_source"] == "ESTIMATED"


@settings(max_examples=200)
@given(usage_dims=_usage_dims_strategy, rate_card=_rate_card_strategy)
def test_none_measured_is_estimated(usage_dims, rate_card):
    """A map whose present dims are all estimated -> ESTIMATED (R4.2)."""
    forced = {k: UsageDim(v.value, False) for k, v in usage_dims.items()}
    result = compute_cost(forced, rate_card)
    assert result["data_source"] == "ESTIMATED"


@settings(max_examples=200)
@given(rate_card=_rate_card_strategy)
def test_empty_dims_estimated_zero_cost(rate_card):
    """The empty-dims case classifies ESTIMATED with estimated_cost 0.0 (R4.4)."""
    result = compute_cost({}, rate_card)
    assert result["data_source"] == "ESTIMATED"
    assert result["estimated_cost"] == 0.0
    assert result["usage"] == {}


@settings(max_examples=200)
@given(
    measured_dim=st.sampled_from(list(USAGE_DIMS)),
    other_dim=st.sampled_from(list(USAGE_DIMS)),
    v1=_values,
    v2=_values,
    rate_card=_rate_card_strategy,
)
def test_mixed_when_measured_and_estimated_present(
    measured_dim, other_dim, v1, v2, rate_card
):
    """One measured + one estimated present dim -> MIXED (R4.5)."""
    if measured_dim == other_dim:
        # Need two distinct keys for a genuine mix.
        idx = USAGE_DIMS.index(other_dim)
        other_dim = USAGE_DIMS[(idx + 1) % len(USAGE_DIMS)]
    usage_dims = {
        measured_dim: UsageDim(v1, True),
        other_dim: UsageDim(v2, False),
    }
    result = compute_cost(usage_dims, rate_card)
    assert result["data_source"] == "MIXED"


if __name__ == "__main__":
    test_data_source_matches_oracle_and_is_total()
    test_all_measured_is_measured()
    test_none_measured_is_estimated()
    test_empty_dims_estimated_zero_cost()
    test_mixed_when_measured_and_estimated_present()
    print("ok")
