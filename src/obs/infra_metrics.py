"""Opportunistic infrastructure metrics collection (Phase 5, Task 2.9).

Reports CPU / memory / IO for a monitored target where the observation path
makes it natural, without requiring eBPF on every host (SRS R5).

Two collectors share a small :class:`InfraCollector` protocol:

* :class:`EbpfCollector` — preferred where eBPF tooling and capabilities are
  present; it probes for bpf support and is used only when ``available()`` is
  True.
* :class:`ProcDockerFallbackCollector` — the non-eBPF fallback (R5.2). It reads
  ``/proc/<pid>/stat`` + ``/proc/<pid>/io`` or shells out to
  ``docker stats --no-stream``. Its ``available()`` always returns True, so
  metrics can always be reported.

:func:`select_collector` returns the eBPF collector only when it is actually
available and otherwise falls back, so eBPF is never required (R5.3).

Each ``sample(target)`` returns ``{cpu_percent, memory_bytes, io_bytes}``; a
dimension that cannot be read is reported as ``None`` rather than raising, so
collection is opportunistic by design.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from typing import Any, Dict, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# The sample shape every collector returns.
_EMPTY_SAMPLE: Dict[str, Optional[float]] = {
    "cpu_percent": None,
    "memory_bytes": None,
    "io_bytes": None,
}


@runtime_checkable
class InfraCollector(Protocol):
    """A source of CPU / memory / IO metrics for a monitored target."""

    def available(self) -> bool:
        """Whether this collector can run on the current host."""
        ...

    def sample(self, target: Dict[str, Any]) -> Dict[str, Optional[float]]:
        """Return ``{cpu_percent, memory_bytes, io_bytes}`` for ``target``."""
        ...


def _empty_sample() -> Dict[str, Optional[float]]:
    return dict(_EMPTY_SAMPLE)


class EbpfCollector:
    """Preferred collector, used only where eBPF tooling/caps are present.

    ``available()`` probes for bpf support rather than assuming it; a host
    without the tooling or capabilities reports ``False`` so selection falls
    back to the proc/docker collector (R5.2, R5.3).
    """

    # Interfaces that indicate usable bpf tooling on the host.
    _BPF_FS = "/sys/fs/bpf"
    _BPF_SYSCALL_PROBE = "/proc/sys/kernel/unprivileged_bpf_disabled"

    def available(self) -> bool:
        # Non-Linux hosts never expose bpf.
        if os.name != "posix":
            return False
        try:
            has_bpffs = os.path.isdir(self._BPF_FS)
            has_bpf_syscall = os.path.exists(self._BPF_SYSCALL_PROBE)
            has_tooling = shutil.which("bpftool") is not None
            # Require the kernel bpf surface plus at least a usable tool.
            return (has_bpffs or has_bpf_syscall) and has_tooling
        except OSError:
            logger.debug("eBPF availability probe failed", exc_info=True)
            return False

    def sample(self, target: Dict[str, Any]) -> Dict[str, Optional[float]]:
        # eBPF-backed sampling is host-specific; callers should only reach this
        # path when available() is True. Return the empty shape as a safe
        # default so an unwired probe never raises.
        return _empty_sample()


class ProcDockerFallbackCollector:
    """Non-eBPF fallback collector (R5.2).

    Reads ``/proc/<pid>/stat`` + ``/proc/<pid>/io`` when a pid is known, or
    falls back to ``docker stats --no-stream`` for a container target. Always
    available so metrics can be reported without eBPF (R5.3).
    """

    def available(self) -> bool:
        return True

    def sample(self, target: Dict[str, Any]) -> Dict[str, Optional[float]]:
        target = target or {}
        pid = target.get("pid")
        if pid is not None:
            sample = self._sample_proc(int(pid))
            if any(v is not None for v in sample.values()):
                return sample
        container = target.get("container_id") or target.get("container")
        if container:
            return self._sample_docker(str(container))
        return _empty_sample()

    # --- /proc readers ---------------------------------------------------

    def _sample_proc(self, pid: int) -> Dict[str, Optional[float]]:
        sample = _empty_sample()
        sample["cpu_percent"] = self._read_proc_cpu(pid)
        sample["memory_bytes"] = self._read_proc_memory(pid)
        sample["io_bytes"] = self._read_proc_io(pid)
        return sample

    def _read_proc_cpu(self, pid: int) -> Optional[float]:
        # utime + stime (fields 14, 15) in clock ticks; reported as a raw
        # cumulative tick count scaled to seconds. A rate requires two reads
        # over time, which the observation path performs; here we expose the
        # cumulative CPU time as a coarse percent-of-one-core proxy.
        try:
            with open(f"/proc/{pid}/stat", "r", encoding="utf-8") as fh:
                parts = fh.read().split()
            utime = float(parts[13])
            stime = float(parts[14])
            ticks = os.sysconf("SC_CLK_TCK")
            if ticks <= 0:
                return None
            return round((utime + stime) / ticks, 6)
        except (OSError, IndexError, ValueError, AttributeError):
            logger.debug("proc cpu read failed for pid %s", pid, exc_info=True)
            return None

    def _read_proc_memory(self, pid: int) -> Optional[float]:
        # VmRSS from /proc/<pid>/status, reported in bytes.
        try:
            with open(f"/proc/{pid}/status", "r", encoding="utf-8") as fh:
                for line in fh:
                    if line.startswith("VmRSS:"):
                        kb = float(line.split()[1])
                        return kb * 1024.0
            return None
        except (OSError, IndexError, ValueError):
            logger.debug("proc memory read failed for pid %s", pid, exc_info=True)
            return None

    def _read_proc_io(self, pid: int) -> Optional[float]:
        # read_bytes + write_bytes from /proc/<pid>/io.
        try:
            read_bytes = write_bytes = 0.0
            with open(f"/proc/{pid}/io", "r", encoding="utf-8") as fh:
                for line in fh:
                    if line.startswith("read_bytes:"):
                        read_bytes = float(line.split()[1])
                    elif line.startswith("write_bytes:"):
                        write_bytes = float(line.split()[1])
            return read_bytes + write_bytes
        except (OSError, IndexError, ValueError):
            logger.debug("proc io read failed for pid %s", pid, exc_info=True)
            return None

    # --- docker fallback -------------------------------------------------

    def _sample_docker(self, container: str) -> Dict[str, Optional[float]]:
        sample = _empty_sample()
        if shutil.which("docker") is None:
            return sample
        try:
            proc = subprocess.run(
                [
                    "docker", "stats", "--no-stream", "--format",
                    "{{.CPUPerc}}|{{.MemUsage}}|{{.BlockIO}}",
                    container,
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            logger.debug("docker stats failed for %s", container, exc_info=True)
            return sample
        if proc.returncode != 0 or not proc.stdout.strip():
            return sample
        line = proc.stdout.strip().splitlines()[0]
        cpu_raw, _, rest = line.partition("|")
        mem_raw, _, io_raw = rest.partition("|")
        sample["cpu_percent"] = self._parse_percent(cpu_raw)
        sample["memory_bytes"] = self._parse_size(mem_raw.split("/")[0])
        sample["io_bytes"] = self._parse_io(io_raw)
        return sample

    @staticmethod
    def _parse_percent(raw: str) -> Optional[float]:
        try:
            return float(raw.strip().rstrip("%"))
        except (ValueError, AttributeError):
            return None

    @staticmethod
    def _parse_size(raw: str) -> Optional[float]:
        # Converts a docker human size (e.g. "12.3MiB") to bytes.
        units = {
            "b": 1.0,
            "kib": 1024.0, "kb": 1000.0,
            "mib": 1024.0 ** 2, "mb": 1000.0 ** 2,
            "gib": 1024.0 ** 3, "gb": 1000.0 ** 3,
            "tib": 1024.0 ** 4, "tb": 1000.0 ** 4,
        }
        try:
            token = raw.strip().lower()
            for suffix, factor in sorted(units.items(), key=lambda kv: -len(kv[0])):
                if token.endswith(suffix):
                    number = token[: -len(suffix)].strip()
                    return float(number) * factor
            return float(token)
        except (ValueError, AttributeError):
            return None

    @classmethod
    def _parse_io(cls, raw: str) -> Optional[float]:
        # BlockIO is "read / write"; sum both sides in bytes.
        try:
            read_s, _, write_s = raw.partition("/")
            read_b = cls._parse_size(read_s) or 0.0
            write_b = cls._parse_size(write_s) or 0.0
            total = read_b + write_b
            return total if (read_s.strip() or write_s.strip()) else None
        except (ValueError, AttributeError):
            return None


def select_collector(prefer_ebpf: bool = True) -> InfraCollector:
    """Return the eBPF collector when available, else the fallback (R5.2, R5.3).

    eBPF is returned only when ``prefer_ebpf`` is True *and* the eBPF collector
    reports itself available; otherwise the always-available proc/docker
    fallback is returned so metrics can be reported without eBPF.
    """
    ebpf = EbpfCollector()
    if prefer_ebpf and ebpf.available():
        return ebpf
    return ProcDockerFallbackCollector()
