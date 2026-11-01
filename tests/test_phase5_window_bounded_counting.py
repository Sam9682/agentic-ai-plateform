#!/usr/bin/env python3
"""Property test for window-bounded counting.

Feature: phase5-obs-supervisor, Property 5.

Validates: Requirements 2.1, 2.3.

Task 2.2 (Phase 5, Half A). The signal-bundle builder
``src.obs.signal_bundle.build_signal_bundle`` applies a sliding-window filter so
that only inputs ``x`` with ``now - clock_of(x) <= cfg.window_seconds``
contribute to the ``commands`` list fed to
``anomaly_engine.detect_repeated_commands``. Because counting happens over the
in-window commands only, an operation observed *only* outside the window is
never counted toward loop detection (R2.1 counts within a Sliding_Window rather
than over all history; R2.3 below-threshold recurrence is not flagged, and an
operation with zero in-window occurrences trivially stays below any threshold).

Property 5 (design.md): *for any* split of events into an in-window group and an
out-of-window group, every operation that appears ONLY outside the window is
absent from the built ``commands`` list (and hence cannot be counted toward loop
detection), while every operation that appears at least once in-window is
present in ``commands``.

The test generates events tagged with a timestamp relative to ``now`` and
``window_seconds`` (strictly inside vs strictly outside the window), passes a
``clock_of`` that reads the event timestamp, and compares the resulting
``commands`` multiset against an independent oracle computed directly from the
in-window subset. Pure function; no live Docker, PostgreSQL, or SSH, and no
LLM/ML.

Run directly:
    python3 tests/test_phase5_window_bounded_counting.py
Or via pytest:
    pytest tests/test_phase5_window_bounded_counting.py
"""
import os
import sys
from collections import Counter

from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.obs.signal_bundle import WindowConfig, build_signal_bundle  # noqa: E402


# --------------------------------------------------------------------------- #
# Strategies
# --------------------------------------------------------------------------- #
# A small operation alphabet keeps collisions (same op in and out of window)
# likely, which is exactly the interesting case for Property 5.
_OPERATIONS = st.sampled_from(
    ["op_a", "op_b", "op_c", "op_d", "op_e", "op_f"]
)

NOW = 1_000_000.0
WINDOW_SECONDS = 300


def _event(op, in_window):
    """Build an event dict carrying an operation and a window-relative age.

    in-window events get an age in [0, WINDOW_SECONDS] (``now - ts`` within the
    window); out-of-window events get an age strictly greater than
    WINDOW_SECONDS. The operation is carried under the ``action`` key (the first
    key the builder reads: ``action``/``operation``/``command``).
    """
    return {"op": op, "in_window": in_window}


# A list of (operation, in_window flag) events.
_events_strategy = st.lists(
    st.tuples(_OPERATIONS, st.booleans()),
    min_size=0,
    max_size=40,
)


def _age_for(in_window, rnd):
    """Deterministic-ish age chosen from the window-relative class."""
    if in_window:
        return rnd  # in [0, WINDOW_SECONDS]
    return WINDOW_SECONDS + 1 + rnd  # strictly outside


@settings(max_examples=200)
@given(
    raw=_events_strategy,
    ages=st.lists(st.floats(min_value=0.0, max_value=WINDOW_SECONDS), min_size=40, max_size=40),
    window_seconds=st.integers(min_value=60, max_value=600),
)
def test_window_bounded_counting(raw, ages, window_seconds):
    """Operations seen only outside the window never reach ``commands``;
    in-window operations do.

    Validates: Requirements 2.1, 2.3.
    """
    cfg = WindowConfig(window_seconds=window_seconds, loop_threshold=3, allowlist=())

    events = []
    for i, (op, in_window) in enumerate(raw):
        # age relative to now: inside => <= window_seconds; outside => > window
        base = ages[i % len(ages)]
        if in_window:
            age = min(base, float(window_seconds))  # within [0, window]
        else:
            age = float(window_seconds) + 1.0 + base  # strictly beyond window
        ts = NOW - age
        events.append({"action": op, "ts": ts, "_expected_in": in_window})

    def clock_of(item):
        return item.get("ts")

    bundle = build_signal_bundle(
        observations=[],
        events=events,
        allowed_globs=[],
        cfg=cfg,
        now=NOW,
        clock_of=clock_of,
    )
    commands = bundle["commands"]

    # Independent oracle: the in-window commands, computed directly from the
    # window-relative classification (not from the builder's filter logic).
    in_window_ops = [e["action"] for e in events if e["_expected_in"]]
    out_only_ops = {
        e["action"] for e in events if not e["_expected_in"]
    } - set(in_window_ops)

    # 1. Commands multiset equals the in-window operations multiset (R2.1:
    #    counting is window-bounded, not over all history).
    assert Counter(commands) == Counter(in_window_ops)

    # 2. No operation that appears ONLY outside the window reaches commands
    #    (hence it cannot be counted toward loop detection; R2.1, R2.3).
    for op in out_only_ops:
        assert op not in commands

    # 3. Every in-window operation is present in commands.
    for op in set(in_window_ops):
        assert op in commands


@settings(max_examples=200)
@given(
    op=_OPERATIONS,
    repeats=st.integers(min_value=5, max_value=30),
)
def test_out_of_window_repetition_not_counted(op, repeats):
    """An operation repeated many times but entirely outside the window yields
    zero in-window count, so it is never counted toward loop detection.

    Validates: Requirements 2.1, 2.3.
    """
    cfg = WindowConfig(window_seconds=WINDOW_SECONDS, loop_threshold=3, allowlist=())

    # All occurrences strictly outside the window.
    events = [
        {"action": op, "ts": NOW - (WINDOW_SECONDS + 10 + i)}
        for i in range(repeats)
    ]

    bundle = build_signal_bundle(
        observations=[],
        events=events,
        allowed_globs=[],
        cfg=cfg,
        now=NOW,
        clock_of=lambda item: item.get("ts"),
    )

    # Out-of-window operation does not appear at all -> count is 0, below any
    # threshold, so it cannot be flagged as execution.loop.
    assert op not in bundle["commands"]
    assert bundle["frequency"] == 0


if __name__ == "__main__":
    test_window_bounded_counting()
    test_out_of_window_repetition_not_counted()
    print("ok")
