#!/usr/bin/env python3
"""Table-driven tests for the explainable agent classifier.

Covers an ordinary web service (low score, unclassified), a clearly agentic
container (high score with specific evidence), an externally-launched agent, and
borderline cases. Asserts the evidence list is populated and explainable.
"""
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from src.runtime_monitor import agent_classifier as ac


WEB_SERVICE = {
    "name": "web-service-02",
    "image": "nginx:1.27-alpine",
    "env": {"NGINX_HOST": "localhost"},
    "processes": [{"pid": "1", "comm": "nginx", "args": "nginx -g daemon off;"}],
    "network_summary": {"egress": ["cdn.example.com"]},
    "status": "Up 10 minutes",
}

CLEAR_AGENT = {
    "name": "coding-worker-01",
    "image": "ghcr.io/acme/coding-agent:latest",
    "env": {"OPENAI_API_KEY": "sk-xxx", "ROLE": "agent"},
    "processes": [{"pid": "12", "comm": "python", "args": "python -m langchain.agent run"}],
    "network_summary": {"egress": ["api.openai.com"]},
    "status": "Up 3 hours",
}

EXTERNAL_AGENT = {
    "name": "task-runner-03",
    "image": "kiro-runtime:dev",
    "env": {"ANTHROPIC_API_KEY": "xxx"},
    "processes": [{"pid": "9", "comm": "node", "args": "node index.js --loop"}],
    "network_summary": {"egress": ["api.anthropic.com"]},
    "status": "Up 2 days",
    "is_platform_managed": False,
}

BORDERLINE_NAME_ONLY = {
    "name": "data-agent-cache",  # 'agent' token in name only
    "image": "redis:7-alpine",
    "env": {},
    "processes": [{"pid": "1", "comm": "redis-server", "args": "redis-server"}],
    "network_summary": {},
    "status": "Up 1 hour",
}

PLAIN_PYTHON_JOB = {
    "name": "report-builder",
    "image": "python:3.11",
    "env": {"REPORT_DATE": "2026-01-01"},
    "processes": [{"pid": "1", "comm": "python", "args": "python build_report.py"}],
    "network_summary": {"egress": ["s3.amazonaws.com"]},
    "status": "Up 5 minutes",
}


def test_web_service_is_unclassified_low_score():
    r = ac.classify(WEB_SERVICE)
    assert r["classification"] == ac.UNCLASSIFIED
    assert r["score"] < ac.AGENT_THRESHOLD
    print(f"ok web_service -> {r['classification']} score={r['score']} evidence={r['evidence']}")


def test_clear_agent_high_score_with_evidence():
    r = ac.classify(CLEAR_AGENT)
    assert r["classification"] == ac.PROBABLE_AGENT
    assert r["score"] >= ac.AGENT_THRESHOLD
    joined = " | ".join(r["evidence"])
    assert "agent token" in joined
    assert "LLM/agent config" in joined or "LLM client libs" in joined
    assert "api.openai.com" in joined
    assert len(r["evidence"]) >= 3
    print(f"ok clear_agent -> score={r['score']}")
    for line in r["evidence"]:
        print("   evidence:", line)


def test_external_agent_detected_without_platform_label():
    r = ac.classify(EXTERNAL_AGENT)
    assert r["classification"] == ac.PROBABLE_AGENT
    joined = " | ".join(r["evidence"])
    assert "kiro" in joined
    assert "api.anthropic.com" in joined
    print(f"ok external_agent -> score={r['score']}")


def test_borderline_name_token_only_stays_unclassified():
    # A single weak signal (name token) must not cross the threshold alone.
    r = ac.classify(BORDERLINE_NAME_ONLY)
    assert r["classification"] == ac.UNCLASSIFIED, r
    assert r["score"] < ac.AGENT_THRESHOLD
    assert any("name" in e for e in r["evidence"])  # still explains the one signal
    print(f"ok borderline_name_only -> score={r['score']} evidence={r['evidence']}")


def test_plain_python_job_not_flagged():
    r = ac.classify(PLAIN_PYTHON_JOB)
    assert r["classification"] == ac.UNCLASSIFIED
    print(f"ok plain_python_job -> score={r['score']} evidence={r['evidence']}")


def test_score_clamped_and_evidence_empty_when_no_signal():
    r = ac.classify({"name": "x", "image": "busybox", "env": {}, "processes": [],
                     "network_summary": {}, "status": "Up 1 minute"})
    assert r["score"] == 0.0
    assert r["evidence"] == []
    assert r["classification"] == ac.UNCLASSIFIED
    print("ok no_signal -> empty evidence, score 0.0")


def main():
    test_web_service_is_unclassified_low_score()
    test_clear_agent_high_score_with_evidence()
    test_external_agent_detected_without_platform_label()
    test_borderline_name_token_only_stays_unclassified()
    test_plain_python_job_not_flagged()
    test_score_clamped_and_evidence_empty_when_no_signal()
    print("\nAll classifier tests passed.")


if __name__ == "__main__":
    main()
