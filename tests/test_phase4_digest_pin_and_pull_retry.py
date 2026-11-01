#!/usr/bin/env python3
"""Property tests: digest-pin gate and bounded, transient-gated pull retry (Task 7.6).

Feature: phase4-runtime-execution-hardening, Property 16 and Property 17.

These tests exercise :meth:`src.serverless.container_runtime.DockerRuntime.pull_image`,
which guards the pull with ``assert_image_pinned`` (reused from
``src.aro.execution_manager``) and wraps the pull itself in the shared
``run_with_policy(..., is_transient=ssh_is_transient)`` with a bounded attempt
count (``PULL_MAX_ATTEMPTS``).

Property 16 — Images are digest-pinned before execution (Validates Requirements
5.2): for a digest-pinned image (``name@sha256:...``) the pin gate passes and
the pull proceeds (``subprocess.run`` is invoked); for an unpinned reference
(tag-less, bare tag, or ``:latest``) the gate raises an
``ExecutionPolicyError`` deterministically and NO pull is attempted
(``subprocess.run`` is never called, so there is no pull and no retry).

Property 17 — Pull retry is bounded and transient-gated (Validates Requirements
5.3): a transient pull failure (connection reset/timeout/refused registry
stderr) is retried through the policy up to ``PULL_MAX_ATTEMPTS`` invocations
and then fails terminally; a deterministic pull failure (manifest unknown,
denied) is not retried (exactly one invocation). In every case the number of
pull attempts never exceeds ``max_attempts``.

No live Docker / registry / SSH: ``subprocess.run`` is faked and the policy's
injected ``sleep`` is stubbed so the bounded backoff never actually waits.

Run directly:
    python3 tests/test_phase4_digest_pin_and_pull_retry.py
Or via pytest:
    pytest tests/test_phase4_digest_pin_and_pull_retry.py
"""
import os
import sys
from unittest import mock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("FLASK_ENV", "development")

from src import execution_policy  # noqa: E402
from src.aro.execution_manager import ExecutionPolicyError  # noqa: E402
from src.serverless import container_runtime  # noqa: E402
from src.serverless.container_runtime import (  # noqa: E402
    PULL_MAX_ATTEMPTS,
    DockerRuntime,
)


# --------------------------------------------------------------------------- #
# Strategies
# --------------------------------------------------------------------------- #
# An image NAME (repository/path with an optional registry host), no tag/digest.
_image_name = st.builds(
    lambda host, path: f"{host}{path}",
    host=st.sampled_from(
        ["", "docker.io/library/", "ghcr.io/org/", "registry.internal:5000/"]
    ),
    path=st.sampled_from(["python", "alpine", "node", "my-app", "busybox"]),
)

# A 64-hex-character sha256 digest body.
_digest = st.text(alphabet="0123456789abcdef", min_size=64, max_size=64)

# Mutable, non-digest tags that the pin gate must reject.
_mutable_tag = st.sampled_from(
    ["latest", "LATEST", "3.11", "v1.2.3", "stable", "edge", "main"]
)


@st.composite
def _pinned_image(draw):
    """A digest-pinned reference ``name@sha256:<64hex>`` (accepted)."""
    return f"{draw(_image_name)}@sha256:{draw(_digest)}"


@st.composite
def _unpinned_image(draw):
    """An unpinned reference the pin gate rejects deterministically.

    Covers the three rejection shapes of ``assert_image_pinned``:
    tag-less (no digest), ``:latest`` (mutable), and a bare non-latest tag.
    """
    name = draw(_image_name)
    kind = draw(st.sampled_from(["bare", "latest", "tag"]))
    if kind == "bare":
        return name
    if kind == "latest":
        return f"{name}:latest"
    return f"{name}:{draw(_mutable_tag.filter(lambda t: t.lower() != 'latest'))}"


# Registry stderr fragments that ``ssh_is_transient`` classifies as transient
# (retryable) — these mirror ``execution_manager._TRANSIENT_MARKERS``.
_transient_stderr = st.sampled_from(
    [
        "connection refused",
        "connection reset by peer",
        "i/o timeout",
        "net/http: request canceled (Client.Timeout exceeded)",
        "dial tcp: connection timed out",
        "no route to host",
        "network is unreachable",
        "TLS handshake timeout: operation timed out",
    ]
)

# Registry stderr fragments that are deterministic (NOT retryable): no transient
# marker appears in them.
_deterministic_stderr = st.sampled_from(
    [
        "manifest unknown: manifest unknown",
        "denied: requested access to the resource is denied",
        "unauthorized: authentication required",
        "pull access denied, repository does not exist",
        "manifest for image not found",
    ]
)


def _fake_completed(returncode, stderr=""):
    """Build a stand-in for ``subprocess.CompletedProcess``."""
    return mock.Mock(returncode=returncode, stdout="", stderr=stderr)


# --------------------------------------------------------------------------- #
# Property 16 — digest pin gate before any pull
# --------------------------------------------------------------------------- #
@settings(max_examples=150, deadline=None)
@given(image=_pinned_image())
def test_pinned_image_proceeds_to_pull(image):
    """Feature: phase4-runtime-execution-hardening, Property 16.

    A digest-pinned image passes the pin gate and the pull proceeds: the faked
    ``subprocess.run`` is invoked exactly once with the ``docker pull <image>``
    argv (a clean success means no retry). Validates Requirements 5.2.
    """
    runtime = DockerRuntime()
    fake_run = mock.Mock(return_value=_fake_completed(0))

    with mock.patch.object(container_runtime.subprocess, "run", fake_run):
        # Should not raise: the image is pinned and the pull succeeds.
        runtime.pull_image(image)

    # The pull was actually attempted (gate passed) exactly once.
    assert fake_run.call_count == 1
    argv = fake_run.call_args.args[0]
    assert argv == ["docker", "pull", image]


@settings(max_examples=150, deadline=None)
@given(image=_unpinned_image())
def test_unpinned_image_rejected_before_any_pull(image):
    """Feature: phase4-runtime-execution-hardening, Property 16.

    An unpinned reference (tag-less, ``:latest``, or a bare mutable tag) is
    rejected by the pin gate as a deterministic ``ExecutionPolicyError`` BEFORE
    any pull: the faked ``subprocess.run`` is never called, so there is no pull
    and no retry. Validates Requirements 5.2.
    """
    runtime = DockerRuntime()
    fake_run = mock.Mock(return_value=_fake_completed(0))

    with mock.patch.object(container_runtime.subprocess, "run", fake_run):
        with pytest.raises(ExecutionPolicyError):
            runtime.pull_image(image)

    # Deterministic rejection before execution: no pull was ever attempted.
    assert fake_run.call_count == 0


# --------------------------------------------------------------------------- #
# Property 17 — pull retry is bounded and transient-gated
# --------------------------------------------------------------------------- #
@settings(max_examples=150, deadline=None)
@given(image=_pinned_image(), stderr=_transient_stderr)
def test_transient_pull_failure_retried_up_to_bound(image, stderr):
    """Feature: phase4-runtime-execution-hardening, Property 17.

    A pull that always fails with a transient registry error is retried through
    the Execution_Policy up to the bound: the faked ``subprocess.run`` is
    invoked exactly ``PULL_MAX_ATTEMPTS`` times (never more), and the pull then
    fails terminally with the registry stderr surfaced. The injected policy
    ``sleep`` is stubbed so the bounded backoff never actually waits.
    Validates Requirements 5.3.
    """
    runtime = DockerRuntime()
    fake_run = mock.Mock(return_value=_fake_completed(1, stderr=stderr))

    with mock.patch.object(container_runtime.subprocess, "run", fake_run), \
            mock.patch.object(execution_policy._time_mod, "sleep", lambda _s: None):
        with pytest.raises(RuntimeError) as excinfo:
            runtime.pull_image(image)

    # Retried up to — and never beyond — the configured attempt bound.
    assert fake_run.call_count == PULL_MAX_ATTEMPTS
    assert fake_run.call_count <= PULL_MAX_ATTEMPTS
    # The terminal error carries the registry stderr that drove the retry.
    assert stderr in str(excinfo.value)


@settings(max_examples=150, deadline=None)
@given(image=_pinned_image(), stderr=_deterministic_stderr)
def test_deterministic_pull_failure_not_retried(image, stderr):
    """Feature: phase4-runtime-execution-hardening, Property 17.

    A pull that fails with a deterministic registry error (manifest unknown,
    denied, unauthorized) is NOT retried: the faked ``subprocess.run`` is
    invoked exactly once and the pull fails terminally immediately. The attempt
    count never exceeds the bound. Validates Requirements 5.3.
    """
    runtime = DockerRuntime()
    fake_run = mock.Mock(return_value=_fake_completed(1, stderr=stderr))

    with mock.patch.object(container_runtime.subprocess, "run", fake_run), \
            mock.patch.object(execution_policy._time_mod, "sleep", lambda _s: None):
        with pytest.raises(RuntimeError) as excinfo:
            runtime.pull_image(image)

    # Deterministic failure: exactly one attempt, no retry.
    assert fake_run.call_count == 1
    assert fake_run.call_count <= PULL_MAX_ATTEMPTS
    assert stderr in str(excinfo.value)


@settings(max_examples=150, deadline=None)
@given(
    image=_pinned_image(),
    transient=_transient_stderr,
    succeed_on=st.integers(min_value=1, max_value=PULL_MAX_ATTEMPTS),
)
def test_transient_then_success_within_bound(image, transient, succeed_on):
    """Feature: phase4-runtime-execution-hardening, Property 17.

    A pull that fails transiently for the first ``succeed_on - 1`` attempts and
    then succeeds completes successfully within the bound: the number of
    invocations equals ``succeed_on`` and never exceeds ``PULL_MAX_ATTEMPTS``.
    Validates Requirements 5.3.
    """
    runtime = DockerRuntime()
    calls = {"n": 0}

    def _side_effect(*_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] < succeed_on:
            return _fake_completed(1, stderr=transient)
        return _fake_completed(0)

    fake_run = mock.Mock(side_effect=_side_effect)

    with mock.patch.object(container_runtime.subprocess, "run", fake_run), \
            mock.patch.object(execution_policy._time_mod, "sleep", lambda _s: None):
        runtime.pull_image(image)  # should not raise

    assert fake_run.call_count == succeed_on
    assert fake_run.call_count <= PULL_MAX_ATTEMPTS


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
