#!/usr/bin/env python3
"""Property test for deterministic detection output.

Feature: phase5-obs-supervisor, Property 1.

Validates: Requirements 1.6, 13.7.

Task 4.2 (Phase 5, Half A). The OBS detection pass
(:class:`src.obs.detection_pass.DetectionPass`) is built from injected
collaborators only (an OBS repo, a runtime-monitor repo, the ``analyze`` /
``score_of`` callables, a governance ``quarantine`` callable, a
``WindowConfig``, a ``clock``, and an ``agents_source`` provider) so it runs
with no live DB or ZAF (R14.1). It builds the behavioral signal bundle via
:func:`src.obs.signal_bundle.build_signal_bundle` and runs the reused, unchanged
deterministic :func:`src.obs.anomaly_engine.analyze`. No LLM and no ML model is
ever invoked in the detection path (R1.6, R13.7).

Property 1 (design.md): *for any* observation/event window, two invocations of
``run_cycle()`` over the same inputs produce an identical sequence of anomaly
records -- the same ``rule_id`` / ``severity`` / ``evidence`` per finding and
the same aggregate ``risk`` score -- and no LLM/ML collaborator is invoked. The
only non-deterministic surface (the per-record ``anomaly_id`` nonce) is excluded
from the determinism comparison; every substantive detection output is stable.

The test generates a random set of agent observation/event windows, constructs a
``DetectionPass`` with recording mock repos (so no persistence side effect leaks
and every collaborator call is observable) and the REAL deterministic
``analyze``, calls ``run_cycle()`` twice over the same inputs, and asserts the
returned anomaly records are identical across runs on all deterministic fields.
It also asserts no LLM/ML collaborator is ever invoked: the injected
collaborators are exactly the deterministic ones (``analyze`` is the real
engine callable, ``quarantine`` is a plain recorder) and the pass exposes no ML
hook. Pure/deterministic collaborators only; no live Docker, PostgreSQL, SSH,
or LLM/ML.

Run directly:
    python3 tests/test_phase5_deterministic_detection.py
Or via pytest:
    pytest tests/test_phase5_deterministic_detection.py
"""
import os
import sys

from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.obs.anomaly_engine import analyze  # noqa: E402
from src.obs.detection_pass import DetectionPass  # noqa: E402
from src.obs.signal_bundle import WindowConfig  # noqa: E402

NOW = 1_000_000.0
WINDOW_SECONDS = 300
TENANT_ID = 42


class RecordingObsRepo:
    """Mock OBS repo recording persistence calls; returns stable db ids.

    ``record_anomaly`` hands back a deterministic surrogate db id (the call
    index) so two identical cycles yield identical ids -- any non-determinism in
    the comparison then comes from the pass itself, not the mock.
    """

    def __init__(self):
        self.recorded = []
        self.enforced = []

    def record_anomaly(self, tenant_id, identity, rule_id, severity, risk, evidence):
        db_id = len(self.recorded) + 1
        self.recorded.append(
            {
                "tenant_id": tenant_id,
                "identity": identity,
                "rule_id": rule_id,
                "severity": severity,
                "risk": risk,
                "evidence": evidence,
            }
        )
        return db_id

    def set_enforcement(self, tenant_id, db_id, status, *, runtime_id,
                        session_id, recommended_action):
        self.enforced.append(
            {
                "tenant_id": tenant_id,
                "db_id": db_id,
                "status": status,
                "runtime_id": runtime_id,
                "session_id": session_id,
                "recommended_action": recommended_action,
            }
        )


class RecordingQuarantine:
    """Deterministic governance quarantine recorder (no LLM/ML, cannot fail)."""

    def __init__(self):
        self.calls = []

    def __call__(self, *, evidence, agent, reason):
        self.calls.append({"evidence": evidence, "agent": agent, "reason": reason})


def _comparable_quarantine(calls):
    """Project quarantine calls, dropping the ``anomaly_id`` nonce in evidence.

    The pass passes the full record (which carries a random ``anomaly_id``) as
    quarantine evidence; strip that single random field so the comparison tracks
    only deterministic routing content.
    """
    out = []
    for c in calls:
        ev = dict(c["evidence"])
        ev.pop("anomaly_id", None)
        out.append({"evidence": ev, "agent": c["agent"], "reason": c["reason"]})
    return out


def _comparable(records):
    """Project records onto their deterministic detection-output fields.

    Excludes the per-record ``anomaly_id`` nonce (a ``uuid4`` by design) which is
    intentionally random; everything else (rule_id / severity / evidence /
    recommended_action / enforcement_status / agent + runtime identity) must be
    identical across two runs over the same window.
    """
    return [
        {
            "agent_id": r["agent_id"],
            "runtime_id": r["runtime_id"],
            "session_id": r["session_id"],
            "rule_id": r["rule_id"],
            "severity": r["severity"],
            "evidence": r["evidence"],
            "recommended_action": r["recommended_action"],
            "enforcement_status": r["enforcement_status"],
            "db_id": r["db_id"],
        }
        for r in records
    ]


# A pool of operation identifiers; repeating one past the loop threshold makes
# the deterministic engine emit an execution.loop anomaly.
_OPS = ["op_a", "op_b", "op_c", "op_d", "op_e"]
# Process lines that deterministically trigger suspicious/privilege/socket rules.
_PROC_LINES = ["nc 10.0.0.1 4444", "sudo rm -rf /", "cat /var/run/docker.sock"]


@st.composite
def _agent_windows(draw):
    """Generate a list of agents each carrying an in-window event/obs window."""
    n_agents = draw(st.integers(min_value=1, max_value=4))
    agents = []
    for a in range(n_agents):
        n_events = draw(st.integers(min_value=0, max_value=12))
        events = []
        for _ in range(n_events):
            op = draw(st.sampled_from(_OPS))
            age = draw(st.integers(min_value=0, max_value=WINDOW_SECONDS))
            ev = {"action": op, "ts": NOW - age}
            if draw(st.booleans()):
                ev["outcome"] = "failure"
            if draw(st.booleans()):
                ev["decision"] = "DENY"
                ev["resource"] = draw(st.sampled_from(["res_x", "res_y"]))
            events.append(ev)

        proc = draw(st.lists(st.sampled_from(_PROC_LINES), max_size=2))
        observations = [
            {
                "ts": NOW - draw(st.integers(min_value=0, max_value=WINDOW_SECONDS)),
                "process_summary": list(proc),
                "cpu_percent": draw(st.sampled_from([None, 10.0, 95.0])),
                "memory_bytes": draw(st.sampled_from([None, 1024, (1 << 31)])),
            }
        ]
        agents.append(
            {
                "identity": f"agent-{a}",
                "runtime_id": f"rt-{a}",
                "session_id": f"sess-{a}",
                "allowed_globs": ["op_a", "op_b"],
                "observations": observations,
                "events": events,
            }
        )
    return agents


def _build_pass(agents):
    """Construct a DetectionPass over ``agents`` with recording collaborators.

    ``analyze`` is the REAL deterministic engine; ``quarantine`` is a plain
    recorder. The clock is fixed at ``NOW`` so no wall-clock time leaks into the
    output -- the only random surface left is the ``anomaly_id`` nonce, which the
    comparison excludes.
    """
    obs_repo = RecordingObsRepo()
    quarantine = RecordingQuarantine()
    dp = DetectionPass(
        tenant_id=TENANT_ID,
        obs_repo=obs_repo,
        rt_repo=None,
        analyze=analyze,
        score_of=None,
        quarantine=quarantine,
        cfg=WindowConfig(window_seconds=WINDOW_SECONDS, loop_threshold=3,
                         allowlist=()),
        clock=lambda: NOW,
        agents_source=lambda: agents,
    )
    return dp, obs_repo, quarantine


@settings(max_examples=100, deadline=None)
@given(agents=_agent_windows())
def test_run_cycle_is_deterministic_and_no_llm_ml(agents):
    """Two invocations over the same window produce identical anomaly records
    and risk, and no LLM/ML collaborator is ever invoked.

    Validates: Requirements 1.6, 13.7.
    """
    dp1, obs1, quar1 = _build_pass(agents)
    first = dp1.run_cycle()

    dp2, obs2, quar2 = _build_pass(agents)
    second = dp2.run_cycle()

    # Deterministic detection output: identical records across the two runs.
    assert _comparable(first) == _comparable(second)

    # Persistence side effects are identical too (same findings, same routing).
    assert obs1.recorded == obs2.recorded
    assert obs1.enforced == obs2.enforced
    assert _comparable_quarantine(quar1.calls) == _comparable_quarantine(quar2.calls)

    # No LLM/ML collaborator exists on the pass: the only callables injected are
    # the deterministic engine ``analyze`` and a plain quarantine recorder, and
    # no ML scoring hook is present (score_of is None by construction here).
    assert dp1._analyze is analyze
    assert dp1._score_of is None
    assert dp1._quarantine is quar1
    assert not hasattr(dp1, "model")
    assert not hasattr(dp1, "llm")


@settings(max_examples=100, deadline=None)
@given(agents=_agent_windows())
def test_same_rules_and_risk_per_finding(agents):
    """Every finding's rule_id/severity/evidence and the recorded risk score are
    stable across two runs (the engine is a pure function of the window).

    Validates: Requirements 1.6, 13.7.
    """
    dp1, obs1, _ = _build_pass(agents)
    dp1.run_cycle()
    dp2, obs2, _ = _build_pass(agents)
    dp2.run_cycle()

    # Risk scores recorded per finding must match element-wise.
    assert [r["risk"] for r in obs1.recorded] == [r["risk"] for r in obs2.recorded]
    assert [r["rule_id"] for r in obs1.recorded] == \
        [r["rule_id"] for r in obs2.recorded]
    assert [r["severity"] for r in obs1.recorded] == \
        [r["severity"] for r in obs2.recorded]


if __name__ == "__main__":
    test_run_cycle_is_deterministic_and_no_llm_ml()
    test_same_rules_and_risk_per_finding()
    print("ok")
