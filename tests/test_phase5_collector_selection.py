#!/usr/bin/env python3
"""Unit tests for opportunistic infra-metrics collector selection.

Feature: phase5-obs-supervisor.

Validates: Requirements 5.2, 5.3.

Task 2.10 (Phase 5, Half A). ``src.obs.infra_metrics.select_collector`` returns
the preferred :class:`EbpfCollector` only when eBPF is actually available on the
host, and otherwise falls back to the always-available
:class:`ProcDockerFallbackCollector` so metrics can be reported without eBPF
ever being required (R5.2, R5.3).

These are plain example/edge-case unit tests (not property tests):

  * eBPF available (forced True)   -> ``select_collector()`` -> ``EbpfCollector``
  * eBPF unavailable (forced False)-> ``select_collector()`` -> fallback
  * ``ProcDockerFallbackCollector().available()`` is always True
  * ``select_collector(prefer_ebpf=False)`` -> fallback even if eBPF available
  * each collector's ``sample(target)`` returns a dict with the keys
    ``cpu_percent`` / ``memory_bytes`` / ``io_bytes`` (values may be None here)

Pure selection logic; no live eBPF, Docker, or PostgreSQL required. Availability
is forced via monkeypatch so the test is host-independent.

Run directly:
    python3 tests/test_phase5_collector_selection.py
Or via pytest:
    pytest tests/test_phase5_collector_selection.py -q
"""
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.obs.infra_metrics import (  # noqa: E402
    EbpfCollector,
    ProcDockerFallbackCollector,
    select_collector,
)

_SAMPLE_KEYS = {"cpu_percent", "memory_bytes", "io_bytes"}


# --------------------------------------------------------------------------- #
# select_collector: eBPF availability drives the choice (R5.2, R5.3)
# --------------------------------------------------------------------------- #
def test_select_returns_ebpf_when_available(monkeypatch):
    """eBPF available -> select_collector returns an EbpfCollector (R5.2)."""
    monkeypatch.setattr(EbpfCollector, "available", lambda self: True)
    collector = select_collector()
    assert isinstance(collector, EbpfCollector)


def test_select_returns_fallback_when_ebpf_unavailable(monkeypatch):
    """eBPF unavailable -> select_collector returns the fallback (R5.2, R5.3)."""
    monkeypatch.setattr(EbpfCollector, "available", lambda self: False)
    collector = select_collector()
    assert isinstance(collector, ProcDockerFallbackCollector)


def test_select_prefer_ebpf_false_returns_fallback_even_if_available(monkeypatch):
    """prefer_ebpf=False -> fallback even when eBPF is available (R5.3)."""
    monkeypatch.setattr(EbpfCollector, "available", lambda self: True)
    collector = select_collector(prefer_ebpf=False)
    assert isinstance(collector, ProcDockerFallbackCollector)


# --------------------------------------------------------------------------- #
# Fallback is always available so eBPF is never required (R5.3)
# --------------------------------------------------------------------------- #
def test_fallback_is_always_available():
    """ProcDockerFallbackCollector.available() is always True (R5.3)."""
    assert ProcDockerFallbackCollector().available() is True


# --------------------------------------------------------------------------- #
# Every collector returns the agreed sample shape
# --------------------------------------------------------------------------- #
def test_ebpf_sample_shape():
    """EbpfCollector.sample returns the cpu/memory/io key set."""
    sample = EbpfCollector().sample({"pid": os.getpid()})
    assert isinstance(sample, dict)
    assert set(sample.keys()) == _SAMPLE_KEYS


def test_fallback_sample_shape():
    """ProcDockerFallbackCollector.sample returns the cpu/memory/io key set."""
    sample = ProcDockerFallbackCollector().sample({"pid": os.getpid()})
    assert isinstance(sample, dict)
    assert set(sample.keys()) == _SAMPLE_KEYS


def test_selected_collector_sample_shape(monkeypatch):
    """A selected collector (either branch) yields the agreed sample shape."""
    monkeypatch.setattr(EbpfCollector, "available", lambda self: False)
    sample = select_collector().sample({})
    assert set(sample.keys()) == _SAMPLE_KEYS


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([os.path.abspath(__file__), "-q"]))
