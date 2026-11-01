#!/usr/bin/env python3
"""Property test for correct stdout/stderr attribution in ``get_logs``.

Feature: phase4-runtime-execution-hardening, Property 13.

Property 13: Correct stdout/stderr attribution.
  * ``docker logs <id>`` is run ONCE and multiplexes the container's stdout onto
    the subprocess stdout and the container's stderr onto the subprocess stderr.
  * ``get_logs(id, 'stdout')`` returns exactly the captured subprocess stdout.
  * ``get_logs(id, 'stderr')`` returns exactly the captured subprocess stderr.
  * The docker argv is ``[binary, 'logs', <id>]`` and NEVER carries the bogus
    ``--stdout`` / ``--stderr`` flags (the old branch filtered on docker's own
    CLI error channel rather than the container's stream).

Validates: Requirements 5.1

The test injects a fake ``subprocess.run`` that records every invocation and
returns a scripted ``CompletedProcess(stdout, stderr)`` carrying arbitrary text
for each stream. No real process, no live Docker, and no network is ever
touched. The two logical streams are driven from the SAME single capture so the
per-stream attribution is the only variable under test.

Run directly:
    python3 tests/test_container_runtime_log_attribution.py
Or via pytest:
    pytest tests/test_container_runtime_log_attribution.py
"""
import os
import subprocess
import sys
from unittest import mock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.serverless import container_runtime  # noqa: E402
from src.serverless.container_runtime import DockerRuntime, PodmanRuntime  # noqa: E402


# --------------------------------------------------------------------------- #
# Fakes / helpers
# --------------------------------------------------------------------------- #
class _FakeRunner:
    """A fake ``subprocess.run`` recording calls and scripting a result.

    Returns a ``CompletedProcess`` carrying the scripted ``stdout``/``stderr``
    for every invocation, mirroring how a real ``docker logs`` run multiplexes
    the two container streams onto the two subprocess streams.
    """

    def __init__(self, stdout, stderr):
        self._stdout = stdout
        self._stderr = stderr
        self.calls = []  # list of (args, kwargs)

    def __call__(self, args, *_a, **kwargs):
        self.calls.append((args, kwargs))
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=self._stdout,
            stderr=self._stderr,
        )

    @property
    def last_args(self):
        return self.calls[-1][0]


# Arbitrary container stdout/stderr text, including empty and multi-line blobs.
_log_text = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)),
    max_size=200,
)
# Container identifiers: hex-ish ids and names.
_container_ids = st.text(
    alphabet=st.characters(
        whitelist_categories=("Ll", "Lu", "Nd"),
        whitelist_characters="-_",
    ),
    min_size=1,
    max_size=40,
)
_runtimes = st.sampled_from([DockerRuntime, PodmanRuntime])


def _assert_no_stream_flags(argv):
    """The docker argv must never carry the bogus --stdout/--stderr flags."""
    assert "--stdout" not in argv, f"argv leaked --stdout: {argv!r}"
    assert "--stderr" not in argv, f"argv leaked --stderr: {argv!r}"


# --------------------------------------------------------------------------- #
# Property 13 — per-stream attribution
# --------------------------------------------------------------------------- #
@given(
    runtime_cls=_runtimes,
    container_id=_container_ids,
    stdout=_log_text,
    stderr=_log_text,
)
@settings(max_examples=200, deadline=None)
def test_get_logs_attributes_each_stream_correctly(
    runtime_cls, container_id, stdout, stderr
):
    """Feature: phase4-runtime-execution-hardening, Property 13.

    Validates: Requirements 5.1

    For the SAME scripted ``CompletedProcess(stdout, stderr)``, requesting the
    ``'stdout'`` stream returns the captured stdout and requesting ``'stderr'``
    returns the captured stderr. Each call runs ``docker logs <id>`` once with
    no ``--stdout``/``--stderr`` flag on the argv.
    """
    runtime = runtime_cls()
    binary = runtime_cls._binary

    # stdout attribution
    runner_out = _FakeRunner(stdout, stderr)
    with mock.patch.object(container_runtime.subprocess, "run", runner_out):
        out = runtime.get_logs(container_id, "stdout")
    assert out == stdout, "stdout request must return the container stdout"
    assert len(runner_out.calls) == 1, "docker logs must run exactly once"
    assert runner_out.last_args == [binary, "logs", container_id]
    _assert_no_stream_flags(runner_out.last_args)

    # stderr attribution — same scripted capture, opposite stream.
    runner_err = _FakeRunner(stdout, stderr)
    with mock.patch.object(container_runtime.subprocess, "run", runner_err):
        err = runtime.get_logs(container_id, "stderr")
    assert err == stderr, "stderr request must return the container stderr"
    assert len(runner_err.calls) == 1, "docker logs must run exactly once"
    assert runner_err.last_args == [binary, "logs", container_id]
    _assert_no_stream_flags(runner_err.last_args)


@given(
    runtime_cls=_runtimes,
    container_id=_container_ids,
    stdout=_log_text,
    stderr=_log_text,
)
@settings(max_examples=200, deadline=None)
def test_get_logs_streams_are_not_crossed(
    runtime_cls, container_id, stdout, stderr
):
    """Feature: phase4-runtime-execution-hardening, Property 13.

    Validates: Requirements 5.1

    When the two captured streams differ, the attribution never crosses: the
    stdout request does not return the stderr text and vice versa. Equal-text
    examples are skipped because they cannot distinguish a crossed wiring.
    """
    if stdout == stderr:
        return

    runtime = runtime_cls()

    runner_out = _FakeRunner(stdout, stderr)
    with mock.patch.object(container_runtime.subprocess, "run", runner_out):
        out = runtime.get_logs(container_id, "stdout")

    runner_err = _FakeRunner(stdout, stderr)
    with mock.patch.object(container_runtime.subprocess, "run", runner_err):
        err = runtime.get_logs(container_id, "stderr")

    assert out == stdout and out != stderr, "stdout stream must not be crossed"
    assert err == stderr and err != stdout, "stderr stream must not be crossed"


@given(
    runtime_cls=_runtimes,
    container_id=_container_ids,
    stdout=_log_text,
    stderr=_log_text,
    stream=st.text(min_size=1, max_size=10).filter(lambda s: s != "stdout"),
)
@settings(max_examples=150, deadline=None)
def test_get_logs_non_stdout_stream_returns_stderr(
    runtime_cls, container_id, stdout, stderr, stream
):
    """Feature: phase4-runtime-execution-hardening, Property 13.

    Validates: Requirements 5.1

    Attribution keys strictly on ``stream == 'stdout'``: any other requested
    stream name maps to the subprocess stderr capture, matching the
    implementation contract (``'stdout'`` => stdout, else => stderr).
    """
    runtime = runtime_cls()
    runner = _FakeRunner(stdout, stderr)
    with mock.patch.object(container_runtime.subprocess, "run", runner):
        result = runtime.get_logs(container_id, stream)
    assert result == stderr
    assert len(runner.calls) == 1
    _assert_no_stream_flags(runner.last_args)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
