#!/usr/bin/env python3
"""Tests for the agent runtime adapter interface + capability model (Task 5).

Feature: ARO runtime adapter abstraction (SRS §2.1, §3.2).

Validates:
* capability reporting: FakeAdapter supports the full set; NullAdapter none.
* capability gating: an unsupported operation raises CapabilityError (the
  platform records limitations rather than faking behavior).
* execute -> stream -> cancel cycle on the fake adapter.
* error surface: no raw/unexpected exception types escape the contract.

Run directly:
    python3 tests/test_aro_adapter_base.py
Or via pytest:
    pytest tests/test_aro_adapter_base.py
"""
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.aro.adapters.base import (  # noqa: E402
    Capability,
    CapabilityError,
    FakeAdapter,
    NullAdapter,
)


def test_fake_supports_everything():
    a = FakeAdapter()
    for cap in Capability:
        assert a.supports(cap)


def test_null_supports_nothing():
    a = NullAdapter()
    for cap in Capability:
        assert not a.supports(cap)


def test_null_operations_raise_capability_error():
    a = NullAdapter()
    for call in (
        lambda: a.install({}),
        lambda: a.start("x", {}),
        lambda: a.stop("x"),
        lambda: a.get_status("x"),
        lambda: a.execute("x", {}),
        lambda: a.get_logs("x"),
        lambda: a.health_check(),
    ):
        try:
            call()
            assert False, "expected CapabilityError"
        except CapabilityError:
            pass


def test_partial_capability_gating():
    # An adapter that only supports STATUS must reject EXECUTE.
    a = FakeAdapter(capabilities=[Capability.STATUS])
    assert a.get_status("x") == "UNKNOWN"
    try:
        a.execute("x", {"prompt": "hi"})
        assert False
    except CapabilityError as exc:
        assert exc.capability == Capability.EXECUTE


def test_lifecycle_status_transitions():
    a = FakeAdapter()
    a.start("agent-1", {})
    assert a.get_status("agent-1") == "RUNNING"
    a.stop("agent-1")
    assert a.get_status("agent-1") == "STOPPED"


def test_execute_stream_to_completion():
    a = FakeAdapter()
    handle = a.execute("agent-1", {"prompt": "hello"})
    chunks = list(handle.stream())
    assert any("echo: hello" in c.data for c in chunks)
    assert chunks[-1].done is True
    result = handle.result()
    assert result.success is True
    assert "echo: hello" in result.output


def test_execute_cancel_before_stream():
    a = FakeAdapter()
    handle = a.execute("agent-1", {"prompt": "hello"})
    assert handle.cancel() is True
    chunks = list(handle.stream())
    # After cancel, streaming emits a terminal cancelled event.
    assert chunks[-1].done is True
    result = handle.result()
    assert result.success is False
    assert result.error == "cancelled"


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
