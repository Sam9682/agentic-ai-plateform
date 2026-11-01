#!/usr/bin/env python3
"""Property test for adapter capability gating (Task 4.2).

Feature: phase2-aro-completion, Property 8: Adapter capabilities gate exactly
the reported set.

Validates: Requirements 2.3.

The ``McpAdapter`` in ``src/aro/adapters/mcp_adapter.py`` reports a capability
set via ``get_capabilities()`` and gates every operation through ``_require(cap)``
(inherited from ``base.AgentRuntimeAdapter``), raising ``CapabilityError`` for
anything outside that set. The property under test:

    For any adapter whose reported capability set is S, every operation whose
    required capability is in S is permitted (the gate raises no
    CapabilityError), and every operation whose required capability is NOT in S
    raises CapabilityError.

We drive this against a real ``McpAdapter`` whose reported set is forced to an
arbitrary subset of the ``Capability`` enum (via ``get_capabilities``), then
exercise the ``_require`` gate for every capability and confirm the gate's
behavior matches membership in the reported set exactly. We also confirm the
reported-set accessors (``supports`` / ``get_capabilities``) agree with the
gate, so the gate truly reflects "exactly the reported set".

Run directly:
    python3 tests/test_aro_capability_gating.py
Or via pytest:
    pytest tests/test_aro_capability_gating.py
"""
import os
import sys

from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.aro.adapters.base import Capability, CapabilityError  # noqa: E402
from src.aro.adapters.mcp_adapter import McpAdapter  # noqa: E402


_ALL_CAPS = list(Capability)

# Arbitrary subsets of the Capability enum (including the empty set and the
# full set) as the adapter's reported capability set S.
_CAP_SUBSETS = st.lists(
    st.sampled_from(_ALL_CAPS), unique=True, min_size=0, max_size=len(_ALL_CAPS)
).map(frozenset)


def _adapter_reporting(caps):
    """A real McpAdapter whose reported capability set is forced to ``caps``.

    Only ``get_capabilities`` is overridden; the gating (``_require`` /
    ``supports``) is the unmodified inherited implementation, so the test
    exercises the production gate against an arbitrary reported set.
    """
    adapter = McpAdapter("c1", server_cmd=["mcp-server"])
    reported = list(caps)
    adapter.get_capabilities = lambda: list(reported)  # type: ignore[assignment]
    return adapter


@given(caps=_CAP_SUBSETS)
@settings(max_examples=200)
def test_capability_gate_matches_reported_set(caps):
    """Feature: phase2-aro-completion, Property 8: Adapter capabilities gate
    exactly the reported set.

    Validates: Requirements 2.3.
    """
    adapter = _adapter_reporting(caps)

    # The gate must admit exactly the reported set: in-set capabilities pass
    # the gate silently, out-of-set capabilities raise CapabilityError.
    for cap in _ALL_CAPS:
        in_set = cap in caps

        # supports() and the reported set agree (the gate's source of truth).
        assert adapter.supports(cap) is in_set
        assert (cap in set(adapter.get_capabilities())) is in_set

        if in_set:
            # Permitted: the gate raises nothing.
            assert adapter._require(cap) is None
        else:
            # Not permitted: the gate raises CapabilityError naming the cap.
            try:
                adapter._require(cap)
                assert False, f"expected CapabilityError for {cap}"
            except CapabilityError as exc:
                assert exc.capability is cap


@given(caps=_CAP_SUBSETS)
@settings(max_examples=200)
def test_gate_partitions_capabilities_exactly(caps):
    """The set of gate-permitted capabilities equals the reported set exactly
    (no capability outside S is admitted, none inside S is rejected).

    Feature: phase2-aro-completion, Property 8: Adapter capabilities gate
    exactly the reported set.

    Validates: Requirements 2.3.
    """
    adapter = _adapter_reporting(caps)

    permitted = set()
    rejected = set()
    for cap in _ALL_CAPS:
        try:
            adapter._require(cap)
            permitted.add(cap)
        except CapabilityError:
            rejected.add(cap)

    assert permitted == set(caps)
    assert rejected == set(_ALL_CAPS) - set(caps)
    # Partition is total and disjoint.
    assert permitted.isdisjoint(rejected)
    assert permitted | rejected == set(_ALL_CAPS)


def test_default_mcp_adapter_gates_its_declared_set():
    """Concrete anchor: the unmodified McpAdapter gates exactly its declared
    capability set — operations inside pass the gate, those outside raise.

    Feature: phase2-aro-completion, Property 8: Adapter capabilities gate
    exactly the reported set.

    Validates: Requirements 2.3.
    """
    adapter = McpAdapter("c1", server_cmd=["mcp-server"])
    reported = set(adapter.get_capabilities())
    for cap in _ALL_CAPS:
        if cap in reported:
            assert adapter._require(cap) is None
        else:
            try:
                adapter._require(cap)
                assert False, f"expected CapabilityError for {cap}"
            except CapabilityError as exc:
                assert exc.capability is cap


def test_empty_capability_set_rejects_everything():
    """An adapter reporting no capabilities rejects every operation."""
    adapter = _adapter_reporting(frozenset())
    for cap in _ALL_CAPS:
        try:
            adapter._require(cap)
            assert False, f"expected CapabilityError for {cap}"
        except CapabilityError:
            pass


def test_full_capability_set_permits_everything():
    """An adapter reporting the full set admits every operation."""
    adapter = _adapter_reporting(frozenset(_ALL_CAPS))
    for cap in _ALL_CAPS:
        assert adapter._require(cap) is None


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
