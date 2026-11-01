#!/usr/bin/env python3
"""ABC-integrity test for the ARO runtime adapters (Task 4.11).

Feature: phase2-aro-completion

Guards the "extend, never rewrite" contract for the AgentRuntimeAdapter ABC
(SRS Req 7.5):

* Every concrete adapter (MCP, Kiro ACP, SHAI CLI, SHAI HTTP/SSE) must remain a
  subclass of ``AgentRuntimeAdapter``.
* The public API of ``src/aro/adapters/base.py`` must be unchanged — the
  ``Capability`` enum members, the error hierarchy
  (``AdapterError``/``CapabilityError``/``ExecutionError``), the
  ``ExecutionHandle``/``ExecutionResult``/``ExecutionChunk`` types, and the
  ``AgentRuntimeAdapter`` abstract methods are all present and well-formed. This
  is a regression guard against an accidental rewrite of the shared contract.

_Requirements: 7.5_

Run directly:
    python3 tests/test_aro_abc_integrity.py
Or via pytest:
    pytest tests/test_aro_abc_integrity.py
"""
import enum
import inspect
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.aro.adapters import base  # noqa: E402
from src.aro.adapters.base import (  # noqa: E402
    AdapterError,
    AgentRuntimeAdapter,
    Capability,
    CapabilityError,
    ExecutionChunk,
    ExecutionError,
    ExecutionHandle,
    ExecutionResult,
)
from src.aro.adapters.mcp_adapter import McpAdapter  # noqa: E402
from src.aro.adapters.kiro_acp import KiroAcpAdapter  # noqa: E402
from src.aro.adapters.shai_cli import ShaiCliAdapter  # noqa: E402
from src.aro.adapters.shai_http_sse import ShaiHttpSseAdapter  # noqa: E402


# --------------------------------------------------------------------------- #
# Expected public API of base.py (the frozen contract).
# --------------------------------------------------------------------------- #
EXPECTED_CAPABILITY_MEMBERS = {
    "INSTALL": "install",
    "START": "start",
    "STOP": "stop",
    "STATUS": "status",
    "EXECUTE": "execute",
    "STREAMING": "streaming",
    "CANCELLATION": "cancellation",
    "LOGS": "logs",
    "HEALTH_CHECK": "health_check",
}

EXPECTED_ADAPTER_ABSTRACT_METHODS = {
    "get_capabilities",
    "install",
    "start",
    "stop",
    "get_status",
    "execute",
    "get_logs",
    "health_check",
}

EXPECTED_HANDLE_ABSTRACT_METHODS = {"stream", "cancel", "result"}

CONCRETE_ADAPTERS = (McpAdapter, KiroAcpAdapter, ShaiCliAdapter, ShaiHttpSseAdapter)


# --------------------------------------------------------------------------- #
# 1. Concrete adapters remain AgentRuntimeAdapter subclasses.
# --------------------------------------------------------------------------- #
def test_concrete_adapters_are_subclasses():
    for adapter_cls in CONCRETE_ADAPTERS:
        assert issubclass(adapter_cls, AgentRuntimeAdapter), (
            f"{adapter_cls.__name__} must subclass AgentRuntimeAdapter"
        )


def test_mcp_adapter_is_subclass():
    assert issubclass(McpAdapter, AgentRuntimeAdapter)


def test_kiro_acp_adapter_is_subclass():
    assert issubclass(KiroAcpAdapter, AgentRuntimeAdapter)


def test_shai_cli_adapter_is_subclass():
    assert issubclass(ShaiCliAdapter, AgentRuntimeAdapter)


def test_shai_http_sse_adapter_is_subclass():
    assert issubclass(ShaiHttpSseAdapter, AgentRuntimeAdapter)


# --------------------------------------------------------------------------- #
# 2. base.py public symbols are unchanged.
# --------------------------------------------------------------------------- #
def test_public_symbols_present():
    for name in (
        "Capability",
        "AdapterError",
        "CapabilityError",
        "ExecutionError",
        "ExecutionChunk",
        "ExecutionResult",
        "ExecutionHandle",
        "AgentRuntimeAdapter",
    ):
        assert hasattr(base, name), f"base.py must export public symbol {name!r}"


def test_capability_is_enum_with_expected_members():
    assert issubclass(Capability, enum.Enum)
    actual = {m.name: m.value for m in Capability}
    assert actual == EXPECTED_CAPABILITY_MEMBERS, (
        "Capability enum members/values changed; expected "
        f"{EXPECTED_CAPABILITY_MEMBERS}, got {actual}"
    )


def test_error_hierarchy_unchanged():
    assert issubclass(AdapterError, Exception)
    assert issubclass(CapabilityError, AdapterError)
    assert issubclass(ExecutionError, AdapterError)


def test_capability_error_carries_capability():
    err = CapabilityError(Capability.EXECUTE)
    assert err.capability is Capability.EXECUTE
    assert Capability.EXECUTE.value in str(err)


def test_execution_result_shape():
    # Required success flag plus the documented optional/extra fields.
    result = ExecutionResult(success=True)
    assert result.success is True
    assert result.returncode is None
    assert result.output == ""
    assert result.error is None
    assert result.extra == {}
    d = result.as_dict()
    for key in ("success", "returncode", "output", "error"):
        assert key in d


def test_execution_chunk_shape():
    chunk = ExecutionChunk(data="x")
    assert chunk.data == "x"
    assert chunk.channel == "stdout"
    assert chunk.done is False


def test_execution_handle_abstract_methods():
    assert inspect.isabstract(ExecutionHandle)
    assert set(ExecutionHandle.__abstractmethods__) == EXPECTED_HANDLE_ABSTRACT_METHODS


def test_agent_runtime_adapter_is_abstract_with_expected_methods():
    assert inspect.isabstract(AgentRuntimeAdapter)
    assert set(AgentRuntimeAdapter.__abstractmethods__) == (
        EXPECTED_ADAPTER_ABSTRACT_METHODS
    )


def test_agent_runtime_adapter_helpers_present():
    # Non-abstract helpers that callers depend on must remain available.
    assert callable(AgentRuntimeAdapter.supports)
    assert callable(AgentRuntimeAdapter._require)
    assert hasattr(AgentRuntimeAdapter, "adapter_id")


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([os.path.abspath(__file__), "-v"]))
