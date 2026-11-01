#!/usr/bin/env python3
"""Property test for redaction on the OBS detection write path.

Feature: phase5-obs-supervisor, Property 16 (redaction half).

Validates: Requirements 6.1, 6.2, 6.3.

Task 4.6 (Phase 5, Half A). Where Property 16 (bundle half) proves the *read*
side never collects prompts/payloads (R6.1, R6.2), this redaction half proves
the *write* side: before any anomaly finding is persisted, its evidence is run
through the existing ``src.aro.event_service.redact`` so no plaintext secret is
ever written to ``agent_anomalies`` (R6.3 -- reuse the existing Event_Service
redaction before persistence).

``src.obs.detection_pass.DetectionPass._persist_and_route`` computes
``evidence = event_service.redact(finding["evidence"])`` and passes THAT value
(not the raw finding evidence) as the ``evidence`` argument to
``obs_repo.record_anomaly``. Property 16 (redaction half) (design.md): *for any*
finding whose evidence embeds secret-like keys (``api_key``, ``password``,
``token``, ``authorization``, ...) and/or secret-like values (bearer tokens,
long hex/base64 blobs, PEM private-key headers), the evidence actually persisted
by ``record_anomaly`` equals ``event_service.redact(raw_evidence)`` and contains
none of the raw secret values.

The test drives the pass with:
  * an injected ``analyze`` that returns findings carrying the generated,
    secret-laden evidence (so detection logic is bypassed and we isolate the
    write-path redaction),
  * a mock ``obs_repo`` that captures every ``evidence`` argument handed to
    ``record_anomaly``,
  * an agent carrying pre-loaded (empty) windows so no live runtime-monitor DB
    is touched.

It then asserts, for each captured evidence object, (1) it equals
``event_service.redact(raw)`` exactly, and (2) no raw secret sentinel survives
anywhere in the recursively serialized persisted evidence. Pure/mocked; no live
Docker, PostgreSQL, SSH, LLM, or ML.

Run directly:
    python3 tests/test_phase5_redaction_write_path.py
Or via pytest:
    pytest tests/test_phase5_redaction_write_path.py
"""
import os
import sys

from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.aro import event_service  # noqa: E402
from src.obs.detection_pass import DetectionPass  # noqa: E402
from src.obs.signal_bundle import WindowConfig  # noqa: E402

NOW = 1_000_000.0
_REDACTED = "***REDACTED***"


# --------------------------------------------------------------------------- #
# Test doubles
# --------------------------------------------------------------------------- #
class _CapturingObsRepo:
    """Mock OBS repo capturing the evidence persisted via record_anomaly.

    ``record_anomaly`` mirrors the real signature
    ``(tenant_id, agent_identity, rule_id, severity, risk_score, evidence)`` and
    records the ``evidence`` argument it was actually handed so the test can
    assert what would hit ``agent_anomalies``. ``set_enforcement`` is a no-op
    stub (its behavior is covered by other tasks).
    """

    def __init__(self):
        self.captured_evidence = []
        self._next_id = 1

    def record_anomaly(self, tenant_id, agent_identity, rule_id, severity,
                        risk_score, evidence):
        self.captured_evidence.append(evidence)
        db_id = self._next_id
        self._next_id += 1
        return db_id

    def set_enforcement(self, tenant_id, anomaly_db_id, status, *,
                        runtime_id=None, session_id=None,
                        recommended_action=None):
        return None


def _make_pass(findings, obs_repo):
    """Build a DetectionPass whose injected analyze yields ``findings``.

    Only HIGH/MEDIUM severities are used so routing stays on the surface-only
    path and never invokes the quarantine seam (that path is covered by other
    tasks); the redaction under test runs identically for every severity.
    """
    def analyze(signals, thresholds):
        return {"anomalies": list(findings), "risk": {"score": 0}}

    def quarantine(**kwargs):  # never reached for HIGH/MEDIUM findings
        raise AssertionError("quarantine must not be called for HIGH/MEDIUM")

    agent = {
        "identity": "agent-redact",
        "runtime_id": "rt-1",
        "session_id": "sess-1",
        "allowed_globs": [],
        # Pre-loaded (empty) windows -> no runtime-monitor DB access.
        "observations": [],
        "events": [],
    }

    return DetectionPass(
        tenant_id=1,
        obs_repo=obs_repo,
        rt_repo=None,
        analyze=analyze,
        score_of=None,
        quarantine=quarantine,
        cfg=WindowConfig(window_seconds=300, loop_threshold=3, allowlist=()),
        clock=lambda: NOW,
        agents_source=lambda: [agent],
    )


# --------------------------------------------------------------------------- #
# Secret generation + leak detection
# --------------------------------------------------------------------------- #
SENTINEL = "R4W_SECRET"

# Key names event_service treats as credential-bearing (value always masked).
_SECRET_KEYS = st.sampled_from(
    ["api_key", "apikey", "password", "passwd", "token", "auth_token",
     "access_key", "secret", "private_key", "credential", "authorization",
     "session", "cookie"]
)
# Innocuous keys whose values are only masked if the VALUE looks like a secret.
_PLAIN_KEYS = st.sampled_from(["command", "action", "resource", "note", "label"])


def _secret_shaped_value(draw, label):
    """A value that MATCHES a secret *shape* (bearer/hex/base64/PEM).

    These are masked by ``event_service`` regardless of the key they sit under,
    so placing them beneath an innocuous key still yields redaction. Each
    carries the ``SENTINEL`` marker (except the fixed-shape hex/base64 blobs,
    which are intrinsically secret-looking) so a leak is detectable.
    """
    kind = draw(st.sampled_from(["bearer", "hex", "base64", "pem"]))
    if kind == "bearer":
        return f"Bearer {SENTINEL}{label}abcDEF123456"
    if kind == "hex":
        return "a" * 40  # long hex blob -> masked by value pattern
    if kind == "base64":
        return "A" * 50 + "=="  # long base64 blob -> masked by value pattern
    return "-----BEGIN RSA PRIVATE KEY-----\n" + SENTINEL + label


@st.composite
def _secret_mapping(draw, depth=0):
    """A dict mixing secret-keyed entries, plain entries, and nested secrets."""
    out = {}
    n_secret = draw(st.integers(min_value=1, max_value=3))
    for i in range(n_secret):
        key = draw(_SECRET_KEYS)
        out[f"{key}_{i}"] = draw(st.sampled_from(
            [f"{SENTINEL}::sk{i}", "plain-looking-but-under-secret-key"]
        ))
    # Values under innocuous keys carry the sentinel ONLY via a secret *shape*
    # (bearer/hex/base64/PEM); event_service masks those by value, so the
    # no-leak invariant holds. A plain sentinel string under an innocuous key is
    # intentionally NOT generated here -- redact correctly preserves it.
    n_plain = draw(st.integers(min_value=0, max_value=2))
    for i in range(n_plain):
        out[draw(_PLAIN_KEYS) + f"_{i}"] = _secret_shaped_value(draw, f"pv{i}")
    if depth < 2 and draw(st.booleans()):
        out["nested"] = draw(_secret_mapping(depth=depth + 1))
    if depth < 2 and draw(st.booleans()):
        out["list"] = [_secret_shaped_value(draw, f"li{i}") for i in range(2)]
    return out


@st.composite
def _evidence(draw):
    """Secret-laden evidence shaped as a dict, a list, or a nested mix."""
    shape = draw(st.sampled_from(["dict", "list"]))
    if shape == "dict":
        return draw(_secret_mapping())
    return [draw(_secret_mapping()) for _ in range(draw(st.integers(1, 3)))]


@st.composite
def _findings(draw):
    """One or more HIGH/MEDIUM findings, each with secret-laden evidence."""
    n = draw(st.integers(min_value=1, max_value=4))
    findings = []
    for i in range(n):
        findings.append({
            "rule_id": draw(st.sampled_from(
                ["execution.loop", "authz.denied", "resource.spike"])),
            "severity": draw(st.sampled_from(["HIGH", "MEDIUM", "LOW", "INFO"])),
            "evidence": draw(_evidence()),
        })
    return findings


def _walk_strings(value):
    """Yield every string found anywhere in a nested dict/list/scalar."""
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
# Property
# --------------------------------------------------------------------------- #
@settings(max_examples=150, deadline=None)
@given(findings=_findings())
def test_persisted_evidence_is_redacted(findings):
    """Evidence persisted via record_anomaly equals event_service.redact(raw)
    and leaks no raw secret sentinel.

    Validates: Requirements 6.1, 6.2, 6.3.
    """
    repo = _CapturingObsRepo()
    detection = _make_pass(findings, repo)

    records = detection.run_cycle()

    # One persisted evidence per finding, in order.
    assert len(repo.captured_evidence) == len(findings)
    assert len(records) == len(findings)

    for finding, persisted in zip(findings, repo.captured_evidence):
        raw = finding["evidence"]
        expected = event_service.redact(raw)

        # (1) The write path persisted exactly the redacted form (R6.3).
        assert persisted == expected, (
            "persisted evidence does not match event_service.redact(raw)"
        )

        # (2) No raw sentinel secret survives anywhere in persisted evidence.
        for s in _walk_strings(persisted):
            assert SENTINEL not in s, (
                f"raw secret sentinel leaked into persisted evidence: {s!r}"
            )

        # (3) Every secret-named key's value is the redaction marker.
        if isinstance(persisted, dict):
            for key, val in persisted.items():
                if event_service._SECRET_KEY_PATTERN.search(key):
                    assert val == _REDACTED, (
                        f"secret-named key {key!r} was not masked"
                    )

    # The record returned to callers also carries the redacted evidence, never
    # the raw secret -- the surfaced row shows no plaintext secret either.
    for record in records:
        for s in _walk_strings(record["evidence"]):
            assert SENTINEL not in s


@settings(max_examples=150, deadline=None)
@given(label=st.text(alphabet="abcdefABCDEF0123456789", min_size=1, max_size=12))
def test_known_secret_shapes_are_masked(label):
    """A finding whose evidence embeds a known secret shape under both a
    secret-named key and an innocuous key is persisted fully masked.

    Validates: Requirements 6.1, 6.2, 6.3.
    """
    raw = {
        "api_key": f"{SENTINEL}::{label}",          # masked by key name
        "authorization": f"Bearer {SENTINEL}{label}",  # masked by key name
        "command": f"Bearer {SENTINEL}{label}tok",  # masked by value shape
        "note": "a" * 40,                            # long hex -> value mask
        "benign": "just a normal string",            # preserved
    }
    findings = [{"rule_id": "execution.loop", "severity": "HIGH",
                 "evidence": raw}]
    repo = _CapturingObsRepo()
    detection = _make_pass(findings, repo)

    detection.run_cycle()

    persisted = repo.captured_evidence[0]
    assert persisted == event_service.redact(raw)
    assert persisted["api_key"] == _REDACTED
    assert persisted["authorization"] == _REDACTED
    assert persisted["command"] == _REDACTED
    assert persisted["note"] == _REDACTED
    assert persisted["benign"] == "just a normal string"
    for s in _walk_strings(persisted):
        assert SENTINEL not in s


if __name__ == "__main__":
    test_persisted_evidence_is_redacted()
    test_known_secret_shapes_are_masked()
    print("ok")
