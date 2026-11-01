#!/usr/bin/env python3
"""Property test for no-sensitive-fields in the built signal bundle.

Feature: phase5-obs-supervisor, Property 16 (bundle half).

Validates: Requirements 6.1, 6.2.

Task 2.5 (Phase 5, Half A). The signal-bundle builder
``src.obs.signal_bundle.build_signal_bundle`` turns a window of observations and
events into the behavioral ``signals`` dict that ``anomaly_engine.analyze``
expects. By design the bundle carries *behavioral shape only* -- operation
identifiers, counts, resource samples, and governance context -- and never agent
prompts (R6.1) or sensitive payload values (R6.2: payloads, credentials,
secrets, env values, message bodies, API keys, file contents).

Property 16 (bundle half) (design.md): *for any* observations/events that ALSO
carry sensitive fields alongside their behavioral fields, the built bundle
(1) exposes only keys drawn from a fixed allowed *behavioral* set -- no
``prompt``/``payload``/``credential``-style keys appear -- and (2) contains none
of the injected sentinel secret values anywhere in its recursively serialized
string content.

The test generates observations and events that mix legitimate behavioral fields
with sensitive fields holding unique sentinel secret tokens, builds the bundle,
and asserts both the key-subset invariant and the no-sentinel-leak invariant.
Pure function; no live Docker, PostgreSQL, or SSH, and no LLM/ML.

Run directly:
    python3 tests/test_phase5_bundle_no_sensitive_fields.py
Or via pytest:
    pytest tests/test_phase5_bundle_no_sensitive_fields.py
"""
import os
import sys

from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.obs.signal_bundle import WindowConfig, build_signal_bundle  # noqa: E402


# --------------------------------------------------------------------------- #
# Invariants under test
# --------------------------------------------------------------------------- #
# The bundle's keys must be exactly a subset of this behavioral-only set
# (design/Task 2.1). No prompt/payload/credential keys are permitted.
ALLOWED_KEYS = frozenset(
    {
        "commands",
        "failures",
        "process_lines",
        "cpu_percent",
        "memory_bytes",
        "requested_actions",
        "allowed_globs",
        "authz_failures",
        "action",
        "resource",
        "decision",
        "frequency",
    }
)

# Sensitive field names that must NEVER appear as bundle keys (R6.1, R6.2).
SENSITIVE_KEYS = [
    "prompt",
    "payload",
    "credentials",
    "secret",
    "env",
    "message_body",
    "api_key",
    "token",
    "password",
    "file_contents",
]

# A distinctive marker embedded in every injected secret so we can detect any
# leak into the serialized bundle regardless of how the value is nested.
SENTINEL_MARK = "S3NT1NEL_SECRET"

NOW = 1_000_000.0

_OPERATIONS = st.sampled_from(["op_a", "op_b", "op_c", "op_d", "op_e"])
_GLOBS = st.sampled_from(["repo/**", "src/*.py", "conf/*.ini", "data/**"])


def _sentinel(label):
    """A unique sentinel secret value carrying the shared detection marker."""
    return f"{SENTINEL_MARK}::{label}"


def _inject_sensitive(base, idx):
    """Return ``base`` augmented with sensitive fields holding sentinel secrets.

    The sentinels are placed both at the top level and nested inside a dict/list
    so the recursive leak check has something to find if the builder ever copied
    them through.
    """
    poisoned = dict(base)
    for k in SENSITIVE_KEYS:
        poisoned[k] = _sentinel(f"{k}_{idx}")
    # Nested structures also carry sentinels.
    poisoned["nested"] = {
        "inner_prompt": _sentinel(f"nested_prompt_{idx}"),
        "deep": [_sentinel(f"deep_{idx}"), {"k": _sentinel(f"deepk_{idx}")}],
    }
    return poisoned


def _walk_strings(value):
    """Yield every string found anywhere in a nested dict/list/scalar structure."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            if isinstance(k, str):
                yield k
            yield from _walk_strings(v)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _walk_strings(item)


# --------------------------------------------------------------------------- #
# Strategies
# --------------------------------------------------------------------------- #
@st.composite
def _observation(draw, idx):
    base = {
        "ts": NOW - draw(st.floats(min_value=0.0, max_value=250.0)),
        "cpu_percent": draw(st.one_of(st.none(), st.floats(min_value=0.0, max_value=100.0))),
        "memory_bytes": draw(st.one_of(st.none(), st.integers(min_value=0, max_value=10**9))),
        "process_summary": {
            "processes": [
                {
                    "comm": draw(st.sampled_from(["python", "bash", "node", "curl"])),
                    "args": draw(st.sampled_from(["-u main.py", "run", "-lah", "https://x"])),
                }
            ]
        },
    }
    return _inject_sensitive(base, f"obs{idx}")


@st.composite
def _event(draw, idx):
    base = {
        "ts": NOW - draw(st.floats(min_value=0.0, max_value=250.0)),
        "action": draw(_OPERATIONS),
        "resource": draw(_GLOBS),
        "decision": draw(st.sampled_from(["ALLOW", "DENY", "QUARANTINE"])),
        "outcome": draw(st.sampled_from(["success", "failure"])),
    }
    return _inject_sensitive(base, f"ev{idx}")


@st.composite
def _inputs(draw):
    n_obs = draw(st.integers(min_value=0, max_value=8))
    n_ev = draw(st.integers(min_value=0, max_value=12))
    observations = [draw(_observation(i)) for i in range(n_obs)]
    events = [draw(_event(i)) for i in range(n_ev)]
    allowed_globs = draw(st.lists(_GLOBS, min_size=0, max_size=4, unique=True))
    return observations, events, allowed_globs


# --------------------------------------------------------------------------- #
# Property
# --------------------------------------------------------------------------- #
@settings(max_examples=200)
@given(data=_inputs(), window_seconds=st.integers(min_value=60, max_value=600))
def test_bundle_has_no_sensitive_fields(data, window_seconds):
    """The built bundle exposes only behavioral keys and leaks no sentinel
    secret values from prompts/payloads/credentials.

    Validates: Requirements 6.1, 6.2.
    """
    observations, events, allowed_globs = data
    cfg = WindowConfig(window_seconds=window_seconds, loop_threshold=3, allowlist=())

    bundle = build_signal_bundle(
        observations=observations,
        events=events,
        allowed_globs=allowed_globs,
        cfg=cfg,
        now=NOW,
        clock_of=lambda item: item.get("ts"),
    )

    # (1) Key-subset invariant: only behavioral keys, no sensitive keys.
    bundle_keys = set(bundle.keys())
    assert bundle_keys <= ALLOWED_KEYS, (
        f"bundle exposed unexpected keys: {bundle_keys - ALLOWED_KEYS}"
    )
    for sk in SENSITIVE_KEYS:
        assert sk not in bundle, f"sensitive key {sk!r} leaked into the bundle"

    # (2) No-leak invariant: no injected sentinel secret appears anywhere in the
    #     recursively serialized bundle content (R6.1 prompts, R6.2 payloads).
    for s in _walk_strings(bundle):
        assert SENTINEL_MARK not in s, (
            f"sentinel secret value leaked into the bundle: {s!r}"
        )


@settings(max_examples=200)
@given(
    op=_OPERATIONS,
    prompt=st.text(min_size=0, max_size=40),
    payload=st.text(min_size=0, max_size=40),
)
def test_single_poisoned_event_keeps_bundle_behavioral(op, prompt, payload):
    """Even a single event whose prompt/payload equal the behavioral operation
    value does not cause those sensitive keys to surface in the bundle.

    Validates: Requirements 6.1, 6.2.
    """
    cfg = WindowConfig(window_seconds=300, loop_threshold=3, allowlist=())
    event = {
        "ts": NOW - 1.0,
        "action": op,
        "resource": "repo/**",
        "decision": "ALLOW",
        "prompt": _sentinel("one_prompt") + prompt,
        "payload": _sentinel("one_payload") + payload,
        "credentials": _sentinel("one_cred"),
    }

    bundle = build_signal_bundle(
        observations=[],
        events=[event],
        allowed_globs=["repo/**"],
        cfg=cfg,
        now=NOW,
        clock_of=lambda item: item.get("ts"),
    )

    assert set(bundle.keys()) <= ALLOWED_KEYS
    assert "prompt" not in bundle
    assert "payload" not in bundle
    assert "credentials" not in bundle
    for s in _walk_strings(bundle):
        assert SENTINEL_MARK not in s
    # The behavioral operation identifier still flows through.
    assert op in bundle["commands"]


if __name__ == "__main__":
    test_bundle_has_no_sensitive_fields()
    test_single_poisoned_event_keeps_bundle_behavioral()
    print("ok")
