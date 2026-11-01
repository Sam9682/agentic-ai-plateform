#!/usr/bin/env python3
"""Property test for sliding-window loop threshold semantics.

Feature: phase5-obs-supervisor, Property 3.

Validates: Requirements 2.1, 2.2, 2.3.

Task 2.4 (Phase 5, Half A). The OBS detection path builds an in-window signal
bundle via ``src.obs.signal_bundle.build_signal_bundle`` and runs the reused,
unchanged ``src.obs.anomaly_engine.analyze`` with the threshold passthrough
``src.obs.signal_bundle.analyze_thresholds(cfg)`` (which sets
``repeat_command_threshold = cfg.loop_threshold``). ``analyze`` delegates loop
detection to ``detect_repeated_commands``, which flags an operation as an
``execution.loop`` anomaly exactly when its in-window, non-allowlisted count
``n`` is at or above the threshold ``t`` (R2.2), and never below it (R2.3). The
count is taken over the Sliding_Window only (R2.1).

Property 3 (design.md): *for any* threshold ``t`` and any single operation
repeated ``n`` times within the window (and not allowlisted), an
``execution.loop`` anomaly is present in ``analyze(...)``'s output IF AND ONLY IF
``n >= t``. This test exercises both the at/above case (``n >= t`` => flagged)
and the below case (``n < t`` => not flagged).

The test builds ``n`` in-window events for one operation, passes a ``clock_of``
that reads the event timestamp, builds the bundle, calls ``analyze`` with the
threshold passthrough, and checks the presence of the ``execution.loop`` rule
against the ground-truth ``n >= t``. Pure functions only; no live Docker,
PostgreSQL, or SSH, and no LLM/ML.

Run directly:
    python3 tests/test_phase5_sliding_window_threshold.py
Or via pytest:
    pytest tests/test_phase5_sliding_window_threshold.py
"""
import os
import sys

from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.obs.anomaly_engine import analyze  # noqa: E402
from src.obs.signal_bundle import (  # noqa: E402
    WindowConfig,
    analyze_thresholds,
    build_signal_bundle,
)

NOW = 1_000_000.0
WINDOW_SECONDS = 300


def _has_loop_anomaly(result):
    """True iff the analyze() output carries an execution.loop anomaly."""
    return any(a["rule_id"] == "execution.loop" for a in result["anomalies"])


def _run(op, n, t, window_seconds=WINDOW_SECONDS):
    """Build a bundle of ``n`` in-window events for ``op`` and run analyze.

    Returns the ``analyze`` result with the loop threshold set to ``t``.
    """
    cfg = WindowConfig(
        window_seconds=window_seconds, loop_threshold=t, allowlist=()
    )
    # ``n`` occurrences of the single operation, all strictly inside the window
    # (ages in [0, window_seconds]). Distinct timestamps avoid any accidental
    # dedupe and keep every occurrence counted.
    events = [
        {"action": op, "ts": NOW - (i % (window_seconds + 1))}
        for i in range(n)
    ]
    bundle = build_signal_bundle(
        observations=[],
        events=events,
        allowed_globs=[],
        cfg=cfg,
        now=NOW,
        clock_of=lambda item: item.get("ts"),
    )
    # Sanity: the builder counted exactly n in-window, non-allowlisted commands.
    assert bundle["commands"].count(op) == n
    return analyze(bundle, analyze_thresholds(cfg))


@settings(max_examples=200)
@given(
    op=st.sampled_from(["op_a", "op_b", "op_c", "op_d", "op_e"]),
    n=st.integers(min_value=0, max_value=30),
    t=st.integers(min_value=1, max_value=20),
)
def test_loop_flagged_iff_count_at_or_above_threshold(op, n, t):
    """``execution.loop`` present IFF the in-window, non-allowlisted count
    ``n`` is at or above the threshold ``t``.

    Validates: Requirements 2.1, 2.2, 2.3.
    """
    result = _run(op, n, t)
    flagged = _has_loop_anomaly(result)

    if n >= t:
        # At/above the threshold -> flagged (R2.2).
        assert flagged, (
            f"expected execution.loop for n={n} >= t={t}, got none"
        )
    else:
        # Below the threshold -> not flagged (R2.3).
        assert not flagged, (
            f"did not expect execution.loop for n={n} < t={t}, but got one"
        )


@settings(max_examples=200)
@given(
    op=st.sampled_from(["op_a", "op_b", "op_c"]),
    t=st.integers(min_value=2, max_value=15),
)
def test_boundary_exactly_at_threshold_flags(op, t):
    """Exactly at the threshold (``n == t``) flags; one below (``n == t - 1``)
    does not -- the boundary is inclusive at/above (R2.2) and exclusive below
    (R2.3).

    Validates: Requirements 2.1, 2.2, 2.3.
    """
    at = _run(op, t, t)
    below = _run(op, t - 1, t)

    assert _has_loop_anomaly(at), f"n == t == {t} must flag execution.loop"
    assert not _has_loop_anomaly(below), (
        f"n == t - 1 == {t - 1} (< t == {t}) must not flag execution.loop"
    )


if __name__ == "__main__":
    test_loop_flagged_iff_count_at_or_above_threshold()
    test_boundary_exactly_at_threshold_flags()
    print("ok")
