#!/usr/bin/env python3
"""Property test for allowlist exclusion from loop detection.

Feature: phase5-obs-supervisor, Property 4.

Validates: Requirements 2.4.

Task 2.3 (Phase 5, Half A). The signal-bundle builder
``src.obs.signal_bundle.build_signal_bundle`` applies the allowlist filter
BEFORE counting operations (``commands = [c for c in raw if c not in
allowlist]``). Because an allowlisted operation is removed before the multiset
is formed, it never reaches the ``commands`` list fed to
``anomaly_engine.analyze`` / ``detect_repeated_commands``. Consequently an
allowlisted operation can never produce an ``execution.loop`` anomaly, no matter
how many times it repeats in-window (R2.4: allowlisted operations are exempt
from loop detection regardless of repetition count).

Property 4 (design.md): *for any* allowlisted operation repeated an arbitrary
(possibly very large) number of times within the sliding window, running
``analyze`` over the built bundle never yields an ``execution.loop`` anomaly for
that allowlisted operation.

The test generates an allowlisted operation, a large in-window repetition count
(well above the loop threshold), and optional non-allowlisted "noise"
operations. It builds the bundle with the allowlisted op present in
``cfg.allowlist``, runs ``analyze``, and asserts no ``execution.loop`` evidence
mentions the allowlisted operation. Pure function; no live Docker, PostgreSQL,
or SSH, and no LLM/ML.

Run directly:
    python3 tests/test_phase5_allowlist_exclusion.py
Or via pytest:
    pytest tests/test_phase5_allowlist_exclusion.py
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

# A small alphabet of distinct operation identifiers. One is chosen as the
# allowlisted op; the rest can serve as non-allowlisted noise.
_OPERATIONS = ["op_a", "op_b", "op_c", "op_d", "op_e", "op_f"]


def _in_window_event(op, i):
    """An event carrying ``op`` with a timestamp strictly inside the window."""
    # age in [0, WINDOW_SECONDS); modulo keeps every occurrence in-window.
    age = float(i % WINDOW_SECONDS)
    return {"action": op, "ts": NOW - age}


@settings(max_examples=200)
@given(
    allowed_op=st.sampled_from(_OPERATIONS),
    repeats=st.integers(min_value=1, max_value=5000),
    loop_threshold=st.integers(min_value=1, max_value=10),
)
def test_allowlisted_op_never_flagged_regardless_of_repetition(
    allowed_op, repeats, loop_threshold
):
    """An allowlisted operation repeated arbitrarily many times in-window is
    never flagged as ``execution.loop``.

    Validates: Requirements 2.4.
    """
    cfg = WindowConfig(
        window_seconds=WINDOW_SECONDS,
        loop_threshold=loop_threshold,
        allowlist=(allowed_op,),
    )

    # The allowlisted op repeated ``repeats`` times, entirely in-window. Count
    # is deliberately allowed to far exceed the loop threshold.
    events = [_in_window_event(allowed_op, i) for i in range(repeats)]

    bundle = build_signal_bundle(
        observations=[],
        events=events,
        allowed_globs=[],
        cfg=cfg,
        now=NOW,
        clock_of=lambda item: item.get("ts"),
    )

    # The allowlist filter is applied BEFORE counting: the allowlisted op must
    # be absent from commands even though it repeated many times.
    assert allowed_op not in bundle["commands"]

    result = analyze(bundle, analyze_thresholds(cfg))

    # No execution.loop anomaly is produced at all (the only op present was
    # allowlisted and filtered out).
    loop_anomalies = [a for a in result["anomalies"] if a["rule_id"] == "execution.loop"]
    assert loop_anomalies == []


@settings(max_examples=200)
@given(
    allowed_op=st.sampled_from(_OPERATIONS),
    allowed_repeats=st.integers(min_value=1, max_value=2000),
    noise_op=st.sampled_from(_OPERATIONS),
    noise_repeats=st.integers(min_value=0, max_value=20),
    loop_threshold=st.integers(min_value=2, max_value=8),
)
def test_allowlisted_op_excluded_even_amid_non_allowlisted_noise(
    allowed_op, allowed_repeats, noise_op, noise_repeats, loop_threshold
):
    """Even when non-allowlisted operations are also present and may themselves
    be flagged, the allowlisted operation never appears in any ``execution.loop``
    finding.

    Validates: Requirements 2.4.
    """
    # Ensure the noise op is a different identifier than the allowlisted one so
    # the noise is genuinely non-allowlisted.
    if noise_op == allowed_op:
        noise_op = next(o for o in _OPERATIONS if o != allowed_op)

    cfg = WindowConfig(
        window_seconds=WINDOW_SECONDS,
        loop_threshold=loop_threshold,
        allowlist=(allowed_op,),
    )

    events = [_in_window_event(allowed_op, i) for i in range(allowed_repeats)]
    events += [_in_window_event(noise_op, i) for i in range(noise_repeats)]

    bundle = build_signal_bundle(
        observations=[],
        events=events,
        allowed_globs=[],
        cfg=cfg,
        now=NOW,
        clock_of=lambda item: item.get("ts"),
    )

    # Allowlisted op filtered out before counting.
    assert allowed_op not in bundle["commands"]

    result = analyze(bundle, analyze_thresholds(cfg))

    # No execution.loop finding ever references the allowlisted operation,
    # regardless of how the non-allowlisted noise is classified.
    for anomaly in result["anomalies"]:
        if anomaly["rule_id"] == "execution.loop":
            for line in anomaly["evidence"]:
                assert allowed_op not in line


if __name__ == "__main__":
    test_allowlisted_op_never_flagged_regardless_of_repetition()
    test_allowlisted_op_excluded_even_amid_non_allowlisted_noise()
    print("ok")
