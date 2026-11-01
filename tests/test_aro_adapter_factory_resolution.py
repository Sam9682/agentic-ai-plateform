#!/usr/bin/env python3
"""Property test for MCP adapter resolution end-to-end (Phase 2 ARO, Task 8.2).

Feature: phase2-aro-completion, Property 21.

Exercises the *factory portion* of Property 21 ("MCP protocol resolves to the
MCP adapter"): given a runtime definition whose launchable kind is ``mcp`` (its
``supported_protocols`` include ``mcp`` and no higher-precedence protocol, i.e.
no ``acp``), ``runtime_registry_service.resolve_adapter(...)`` must return a
concrete :class:`~src.aro.adapters.mcp_adapter.McpAdapter` instance. The pure
resolver portion (``resolve_adapter_kind`` returning the right kind) is covered
separately by Task 2.8 in ``test_aro_adapter_kind_resolution.py``.

The test also pins the full protocol->adapter mapping the factory binds:

    mcp        -> McpAdapter
    acp        -> KiroAcpAdapter
    cli        -> ShaiCliAdapter
    http / sse -> ShaiHttpSseAdapter

across arbitrary protocol subsets, consistent with the deterministic precedence
``("acp","mcp","http","sse","cli")``. Each constructor gets the context it
requires: a ``container_ref`` for the stdio/CLI adapters (mcp/acp/cli) and a
``base_url`` + ``http_client`` for the HTTP/SSE adapter.

Validates: Requirements 5.1, 5.2

Run directly:
    python3 tests/test_aro_adapter_factory_resolution.py
Or via pytest:
    pytest tests/test_aro_adapter_factory_resolution.py -v
"""
import os
import sys

from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.aro import runtime_registry_service as svc  # noqa: E402
from src.aro.adapters.mcp_adapter import McpAdapter  # noqa: E402
from src.aro.adapters.kiro_acp import KiroAcpAdapter  # noqa: E402
from src.aro.adapters.shai_cli import ShaiCliAdapter  # noqa: E402
from src.aro.adapters.shai_http_sse import ShaiHttpSseAdapter, HttpClient  # noqa: E402

# Deterministic precedence the factory resolves over (highest first), mirroring
# the resolver. Every recognized protocol is launchable, so this equals
# ``SUPPORTED_PROTOCOLS``.
PRECEDENCE = ("acp", "mcp", "http", "sse", "cli")
ALL_PROTOCOLS = sorted(svc.SUPPORTED_PROTOCOLS)

# Expected concrete adapter class for each resolved kind. http and sse share the
# SHAI HTTP/SSE adapter (SSE is HTTP's event transport).
EXPECTED_CLASS = {
    "mcp": McpAdapter,
    "acp": KiroAcpAdapter,
    "cli": ShaiCliAdapter,
    "http": ShaiHttpSseAdapter,
    "sse": ShaiHttpSseAdapter,
}

CONTAINER_REF = "agent-ctr-1"


class _FakeHttpClient(HttpClient):
    """Inert HTTP client so the HTTP/SSE adapter can be constructed in tests."""

    def stream_post(self, url, json_body, headers):  # pragma: no cover - never called
        return iter(())

    def get(self, url, headers):  # pragma: no cover - never called
        return (200, "")

    def post(self, url, json_body, headers):  # pragma: no cover - never called
        return (200, "")


def _expected_kind(protocols):
    """Reference precedence rule for cross-checking the factory's choice."""
    for p in PRECEDENCE:
        if p in protocols:
            return p
    return None


def _build(definition):
    """Build an adapter via the factory, supplying every adapter's context.

    The stdio/CLI adapters (mcp/acp/cli) need a ``container_ref``; the HTTP/SSE
    adapter needs a ``base_url`` + ``http_client``. We hand the factory a single
    shared context bag containing all of them — it forwards only the keys the
    chosen adapter accepts — exactly as a real caller would.
    """
    return svc.resolve_adapter(
        definition,
        CONTAINER_REF,
        base_url="http://127.0.0.1:8080",
        http_client=_FakeHttpClient(),
    )


def test_precedence_list_matches_support_set():
    """The factory's precedence set is exactly the registry's launchable set.

    Keeps the generator honest: a new launchable protocol added to
    ``SUPPORTED_PROTOCOLS`` without a precedence/mapping entry fails here instead
    of being silently skipped by the property.

    Validates: Requirements 5.1
    """
    assert set(PRECEDENCE) == svc.SUPPORTED_PROTOCOLS
    assert set(EXPECTED_CLASS) == svc.SUPPORTED_PROTOCOLS


@settings(max_examples=200, deadline=None)
@given(
    # Subsets guaranteed to contain mcp but NOT acp (the only higher-precedence
    # protocol), so the resolved kind is always mcp. Extra lower-precedence
    # protocols are allowed and must not change the outcome.
    lower=st.lists(
        st.sampled_from(["http", "sse", "cli"]), max_size=3, unique=True
    ),
)
def test_mcp_definition_yields_mcp_adapter(lower):
    """Property 21 (factory): any definition whose protocols include ``mcp`` and
    no higher-precedence protocol (no ``acp``) resolves, through the factory, to a
    concrete ``McpAdapter`` instance.

    Feature: phase2-aro-completion, Property 21.
    Validates: Requirements 5.1, 5.2
    """
    protocols = ["mcp"] + lower
    definition = {"supported_protocols": protocols}
    adapter = _build(definition)
    assert isinstance(adapter, McpAdapter)
    assert adapter.adapter_id == "mcp"


@settings(max_examples=200, deadline=None)
@given(
    # Arbitrary non-empty subsets of the supported protocols, shuffled so the
    # factory cannot depend on list order — only on its own precedence.
    protocols=st.lists(
        st.sampled_from(ALL_PROTOCOLS), min_size=1, max_size=len(ALL_PROTOCOLS), unique=True
    ),
)
def test_factory_binds_full_protocol_to_adapter_mapping(protocols):
    """For any non-empty subset of launchable protocols, the factory constructs
    the concrete adapter bound to the highest-precedence declared protocol:
    mcp->McpAdapter, acp->KiroAcpAdapter, cli->ShaiCliAdapter,
    http/sse->ShaiHttpSseAdapter. Confirms the factory agrees with the resolver
    across the whole input space.

    Feature: phase2-aro-completion, Property 21.
    Validates: Requirements 5.1, 5.2
    """
    definition = {"supported_protocols": list(protocols)}
    kind = _expected_kind(protocols)
    # Factory choice must agree with the pure resolver.
    assert svc.resolve_adapter_kind(definition) == kind
    adapter = _build(definition)
    assert isinstance(adapter, EXPECTED_CLASS[kind])


@settings(max_examples=200, deadline=None)
@given(
    # Any subset containing acp: acp outranks mcp, so the factory never returns an
    # McpAdapter — it must build the ACP adapter instead.
    others=st.lists(
        st.sampled_from(["mcp", "http", "sse", "cli"]), max_size=4, unique=True
    ),
)
def test_acp_outranks_mcp_in_factory(others):
    """When both ``acp`` and ``mcp`` are declared, the factory builds the ACP
    adapter, never the MCP adapter — the precedence is a strict total order.

    Feature: phase2-aro-completion, Property 21.
    Validates: Requirements 5.1
    """
    definition = {"supported_protocols": ["acp"] + others}
    adapter = _build(definition)
    assert isinstance(adapter, KiroAcpAdapter)
    assert not isinstance(adapter, McpAdapter)


def test_mcp_without_container_ref_raises():
    """The MCP adapter runs its server as an in-container subprocess, so the
    factory requires a ``container_ref`` for an ``mcp`` definition and raises
    ``RuntimeValidationError`` when it is missing.

    Validates: Requirements 5.1, 5.2
    """
    definition = {"supported_protocols": ["mcp"]}
    try:
        svc.resolve_adapter(definition, None)
        assert False, "expected RuntimeValidationError when container_ref is missing"
    except svc.RuntimeValidationError:
        pass


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([os.path.abspath(__file__), "-v"]))
