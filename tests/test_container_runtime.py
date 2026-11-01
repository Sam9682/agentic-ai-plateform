#!/usr/bin/env python3
"""Tests for the serverless container runtime hardening (Phase 4, task 7.1).

Feature: phase4-runtime-execution-hardening

Covers the three behavioral changes to
``src/serverless/container_runtime.py``:

* ``get_logs`` runs ``docker logs <id>`` once and attributes the subprocess's
  stdout/stderr to the requested logical stream, dropping the old bogus
  ``--stdout``/``--stderr`` flags (R5.1).
* ``pull_image`` rejects an unpinned image as a deterministic failure before any
  pull runs (R5.2).
* ``pull_image`` retries a transient registry failure through the shared
  execution policy and fails immediately on a deterministic one (R5.3).

Run directly:
    python3 tests/test_container_runtime.py
Or via pytest:
    pytest tests/test_container_runtime.py
"""
import os
import subprocess
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src import execution_policy as ep  # noqa: E402
from src.aro.execution_manager import ExecutionPolicyError  # noqa: E402
from src.serverless import container_runtime as cr  # noqa: E402
from src.serverless.container_runtime import DockerRuntime  # noqa: E402


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    """Keep backoff sleeps instant so retry tests do not actually wait."""
    monkeypatch.setattr(ep._time_mod, "sleep", lambda _s: None)

PINNED = "docker.io/library/python@sha256:" + "a" * 64


def _completed(args, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args, returncode, stdout=stdout, stderr=stderr)


# --------------------------------------------------------------------------
# get_logs: correct stdout/stderr attribution (R5.1)
# --------------------------------------------------------------------------

def test_get_logs_attributes_stdout(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return _completed(cmd, stdout="out-text", stderr="err-text")

    monkeypatch.setattr(cr.subprocess, "run", fake_run)
    out = DockerRuntime().get_logs("c123", stream="stdout")

    assert out == "out-text"
    # One invocation, no bogus --stdout/--stderr flags, bounded by a timeout.
    assert captured["cmd"] == ["docker", "logs", "c123"]
    assert "--stdout" not in captured["cmd"] and "--stderr" not in captured["cmd"]
    assert captured["kwargs"].get("timeout") == cr.LOGS_TIMEOUT_DEFAULT


def test_get_logs_attributes_stderr(monkeypatch):
    def fake_run(cmd, **kwargs):
        return _completed(cmd, stdout="out-text", stderr="err-text")

    monkeypatch.setattr(cr.subprocess, "run", fake_run)
    err = DockerRuntime().get_logs("c123", stream="stderr")

    # The container's stderr comes from the subprocess's stderr stream, not the
    # docker CLI's own error channel as the old --stderr branch returned.
    assert err == "err-text"


def test_get_logs_runs_command_once(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _completed(cmd, stdout="o", stderr="e")

    monkeypatch.setattr(cr.subprocess, "run", fake_run)
    DockerRuntime().get_logs("c123", stream="stdout")
    assert len(calls) == 1


# --------------------------------------------------------------------------
# pull_image: digest pin gate (R5.2)
# --------------------------------------------------------------------------

@pytest.mark.parametrize("image", ["python", "python:latest", "python:3.11"])
def test_pull_image_rejects_unpinned_without_pulling(monkeypatch, image):
    calls = []

    def fake_run(cmd, **kwargs):  # pragma: no cover - must never run
        calls.append(cmd)
        return _completed(cmd)

    monkeypatch.setattr(cr.subprocess, "run", fake_run)

    with pytest.raises(ExecutionPolicyError):
        DockerRuntime().pull_image(image)
    # Deterministic policy failure: no pull was attempted.
    assert calls == []


def test_pull_image_accepts_pinned(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _completed(cmd, returncode=0)

    monkeypatch.setattr(cr.subprocess, "run", fake_run)
    DockerRuntime().pull_image(PINNED)

    assert calls == [["docker", "pull", PINNED]]


# --------------------------------------------------------------------------
# pull_image: retry through the shared policy (R5.3)
# --------------------------------------------------------------------------

def test_pull_image_retries_transient_then_succeeds(monkeypatch):
    attempts = {"n": 0}

    def fake_run(cmd, **kwargs):
        attempts["n"] += 1
        if attempts["n"] == 1:
            # A transient registry failure (connection reset) -> retry.
            return _completed(cmd, returncode=1, stderr="connection reset by peer")
        return _completed(cmd, returncode=0)

    monkeypatch.setattr(cr.subprocess, "run", fake_run)

    DockerRuntime().pull_image(PINNED)
    assert attempts["n"] == 2


def test_pull_image_deterministic_failure_not_retried(monkeypatch):
    attempts = {"n": 0}

    def fake_run(cmd, **kwargs):
        attempts["n"] += 1
        # An unknown manifest is deterministic -> no retry.
        return _completed(cmd, returncode=1, stderr="manifest unknown: not found")

    monkeypatch.setattr(cr.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError):
        DockerRuntime().pull_image(PINNED)
    assert attempts["n"] == 1


def test_pull_image_exhausts_retries_then_raises(monkeypatch):
    attempts = {"n": 0}

    def fake_run(cmd, **kwargs):
        attempts["n"] += 1
        return _completed(cmd, returncode=1, stderr="connection timed out")

    monkeypatch.setattr(cr.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError):
        DockerRuntime().pull_image(PINNED)
    assert attempts["n"] == cr.PULL_MAX_ATTEMPTS


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
