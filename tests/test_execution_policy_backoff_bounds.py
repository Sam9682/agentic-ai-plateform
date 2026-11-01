#!/usr/bin/env python3
"""Property test for execution-policy backoff bounds (Task 2.2).

Feature: phase4-runtime-execution-hardening, Property 1: Backoff is bounded and
jitter-constrained.

Validates: Requirements 1.6.

``compute_backoff(index, p, rand)`` in ``src/execution_policy.py`` must, for any
retry ``index``, any :class:`BackoffParams`, and any ``rand()`` value in
``[0, 1)``:

* return a delay within ``[0.0, cap]`` (the final clamp), and
* keep the jitter within ``jitter_fraction`` of the deterministic delay, where
  ``deterministic = min(cap, base * multiplier ** index)``.

Run directly:
    python3 tests/test_execution_policy_backoff_bounds.py
Or via pytest:
    pytest tests/test_execution_policy_backoff_bounds.py
"""
import math
import os
import sys

from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.execution_policy import BackoffParams, compute_backoff  # noqa: E402


# Non-negative retry indices, bounded so ``multiplier ** index`` stays finite
# for the largest multiplier the params strategy can draw.
_index = st.integers(min_value=0, max_value=64)

# Finite, non-negative backoff parameters spanning tiny -> large magnitudes,
# with jitter_fraction across the full [0, 1] contract range.
_params = st.builds(
    BackoffParams,
    base=st.floats(min_value=0.0, max_value=1e6, allow_nan=False, allow_infinity=False),
    multiplier=st.floats(
        min_value=1.0, max_value=4.0, allow_nan=False, allow_infinity=False
    ),
    jitter_fraction=st.floats(
        min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False
    ),
    cap=st.floats(min_value=0.0, max_value=1e6, allow_nan=False, allow_infinity=False),
)

# rand() values across the random.random() contract: [0, 1).
_rand_value = st.floats(
    min_value=0.0, max_value=1.0, exclude_max=True, allow_nan=False, allow_infinity=False
)


@given(index=_index, p=_params, r=_rand_value)
@settings(max_examples=300)
def test_backoff_is_bounded_and_jitter_constrained(index, p, r):
    """Feature: phase4-runtime-execution-hardening, Property 1: Backoff is
    bounded and jitter-constrained.

    Validates: Requirements 1.6.
    """
    delay = compute_backoff(index, p, rand=lambda: r)

    # The result is always a finite, real delay.
    assert not math.isnan(delay)
    assert not math.isinf(delay)

    # Bounded: the final clamp guarantees 0 <= delay <= cap for every input.
    assert delay >= 0.0
    assert delay <= p.cap

    # Jitter-constrained: before the final clamp, the delay equals the
    # deterministic component plus a jitter that stays within jitter_fraction
    # of that deterministic value. Reconstruct both and assert the bound.
    deterministic = min(p.cap, p.base * (p.multiplier ** index))
    jitter = deterministic * p.jitter_fraction * (2.0 * r - 1.0)

    # |jitter| never exceeds jitter_fraction * deterministic (r in [0,1) =>
    # (2r - 1) in [-1, 1)).
    tol = 1e-9 * max(1.0, abs(deterministic))
    assert abs(jitter) <= deterministic * p.jitter_fraction + tol

    # The returned delay is exactly clamp(deterministic + jitter, 0, cap).
    expected = max(0.0, min(p.cap, deterministic + jitter))
    assert math.isclose(delay, expected, rel_tol=1e-9, abs_tol=1e-9)


def test_backoff_examples():
    """Concrete anchors: zero jitter is deterministic; cap always bounds."""
    # No jitter -> deterministic exponential growth, capped.
    p = BackoffParams(base=1.0, multiplier=2.0, jitter_fraction=0.0, cap=100.0)
    assert compute_backoff(0, p, rand=lambda: 0.5) == 1.0
    assert compute_backoff(1, p, rand=lambda: 0.5) == 2.0
    assert compute_backoff(3, p, rand=lambda: 0.5) == 8.0

    # Deterministic growth is capped before jitter is applied.
    capped = BackoffParams(base=1.0, multiplier=2.0, jitter_fraction=0.0, cap=5.0)
    assert compute_backoff(10, capped, rand=lambda: 0.5) == 5.0

    # Extreme jitter draws still clamp into [0, cap].
    jittery = BackoffParams(base=10.0, multiplier=1.0, jitter_fraction=1.0, cap=20.0)
    assert compute_backoff(0, jittery, rand=lambda: 0.0) == 0.0  # jitter = -det
    assert compute_backoff(0, jittery, rand=lambda: 0.999999) <= 20.0


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
