#!/usr/bin/env python3
"""Property test for adapter-kind resolution (Phase 2 ARO, Task 2.8).

Feature: phase2-aro-completion, Property 21.

Exercises the *resolver portion* of Property 21 ("MCP protocol resolves to the
MCP adapter") over the pure ``resolve_adapter_kind`` resolver in
``src/aro/runtime_registry_service.py``. The factory portion (that an ``mcp``
definition yields an ``McpAdapter``) is covered separately by Task 8.2.

The resolver applies a deterministic precedence over
``("acp", "mcp", "http", "sse", "cli")`` reading ``definition["supported_protocols"]``
and raises ``RuntimeValidationError`` when no launchable protocol is present.

Validates: Requirements 5.1, 5.2

Run directly:
    python3 tests/test_aro_adapter_kind_resolution.py
Or via pytest:
    pytest tests/test_aro_adapter_kind_resolution.py -v
"""
import os
import sys

from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.aro import runtime_registry_service as svc  # noqa: E402

# The deterministic precedence the resolver walks (highest first). Only these
# protocols are launchable; "cli" is the lowest-precedence launchable kind.
PRECEDENCE = ("acp", "mcp", "http", "sse", "cli")
# The full set of protocols the registry recognizes (SUPPORTED_PROTOCOLS). Every
# recognized protocol is launchable here, so the precedence list == the support
# set; this guards the two staying in sync.
ALL_PROTOCOLS = sorted(svc.SUPPORTED_PROTOCOLS)


def _expected_kind(protocols):
    """Reference implementation of the precedence rule for cross-checking."""
    for p in PRECEDENCE:
        if p in protocols:
            return p
    return None


def test_precedence_list_matches_support_set():
    """The resolver's precedence set is exactly the registry's launchable set.

    Keeps the generator's input space honest: if a new launchable protocol is
    added to ``SUPPORTED_PROTOCOLS`` without a precedence rank, this fails loudly
    instead of the property silently skipping it.

    Validates: Requirements 5.1
    """
    assert set(PRECEDENCE) == svc.SUPPORTED_PROTOCOLS


@settings(max_examples=200, deadline=None)
@given(
    # Arbitrary non-empty subsets of the supported protocols, order shuffled so
    # the resolver cannot depend on list order — only on its own precedence.
    protocols=st.lists(
        st.sampled_from(ALL_PROTOCOLS), min_size=1, max_size=len(ALL_PROTOCOLS), unique=True
    ),
)
def test_resolver_returns_highest_precedence_protocol(protocols):
    """For any non-empty subset of launchable protocols, ``resolve_adapter_kind``
    returns the highest-precedence member of ``("acp","mcp","http","sse","cli")``
    that is present — regardless of the order they appear in the definition.

    Feature: phase2-aro-completion, Property 21.
    Validates: Requirements 5.1, 5.2
    """
    definition = {"supported_protocols": list(protocols)}
    kind = svc.resolve_adapter_kind(definition)
    assert kind == _expected_kind(protocols)
    # The resolved kind is always one that was actually declared.
    assert kind in protocols


@settings(max_examples=200, deadline=None)
@given(
    # Subsets guaranteed to contain mcp but NOT acp (the only higher-precedence
    # protocol), so mcp must win. Extra lower-precedence protocols are allowed.
    lower=st.lists(
        st.sampled_from(["http", "sse", "cli"]), max_size=3, unique=True
    ),
)
def test_mcp_resolves_to_mcp_when_no_acp_present(lower):
    """Property 21 (resolver): any definition whose protocols include ``mcp`` and
    no higher-precedence protocol (i.e. no ``acp``) resolves to ``mcp`` — the kind
    the factory binds to the MCP adapter.

    Feature: phase2-aro-completion, Property 21.
    Validates: Requirements 5.1, 5.2
    """
    protocols = ["mcp"] + lower
    definition = {"supported_protocols": protocols}
    assert svc.resolve_adapter_kind(definition) == "mcp"


@settings(max_examples=200, deadline=None)
@given(
    # Any subset that DOES contain acp: acp outranks mcp, so mcp never wins.
    others=st.lists(
        st.sampled_from(["mcp", "http", "sse", "cli"]), max_size=4, unique=True
    ),
)
def test_acp_outranks_mcp(others):
    """``acp`` has strictly higher precedence than ``mcp``: whenever both are
    declared, the resolver picks ``acp``. Confirms the precedence is a total order
    and ``mcp`` only wins in acp's absence.

    Feature: phase2-aro-completion, Property 21.
    Validates: Requirements 5.1
    """
    protocols = ["acp"] + others
    assert svc.resolve_adapter_kind(definition={"supported_protocols": protocols}) == "acp"


@settings(max_examples=200, deadline=None)
@given(
    # Only non-launchable / unknown tokens, plus the explicit empty case handled
    # by min_size=0. None of these appear in the precedence list.
    junk=st.lists(
        st.sampled_from(["telepathy", "grpc", "", "ACP", "Mcp", "soap", "ftp"]),
        max_size=5,
        unique=True,
    ),
)
def test_no_launchable_protocol_raises(junk):
    """When the definition declares no launchable protocol (empty list or only
    unknown/non-launchable tokens), ``resolve_adapter_kind`` raises
    ``RuntimeValidationError`` rather than returning a bogus kind.

    Feature: phase2-aro-completion, Property 21.
    Validates: Requirements 5.1
    """
    definition = {"supported_protocols": list(junk)}
    try:
        svc.resolve_adapter_kind(definition)
        assert False, "expected RuntimeValidationError for no launchable protocol"
    except svc.RuntimeValidationError:
        pass


def test_missing_supported_protocols_key_raises():
    """A definition with no ``supported_protocols`` key (treated as empty) raises
    ``RuntimeValidationError`` — the resolver never defaults to a launchable kind.

    Validates: Requirements 5.1
    """
    try:
        svc.resolve_adapter_kind({})
        assert False, "expected RuntimeValidationError for missing protocols"
    except svc.RuntimeValidationError:
        pass


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([os.path.abspath(__file__), "-v"]))
