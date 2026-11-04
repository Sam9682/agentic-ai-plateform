"""Thread-safe registry of active Agentic_Runs keyed by ``user_id``.

The subprocess launched by ``api_request_dev_ai_for_app()`` lives inside the
streaming closure of one request thread, while a stop request arrives on a
*different* request thread. This module bridges the two: the streaming thread
registers its process on launch and removes it on any exit, and the stop
endpoint looks up the caller's entry to terminate it. All mutation is
serialized through a single lock so the two threads never race.

Scope is strictly per-user, current-run-only: ``register`` overwrites any
prior entry for the same ``user_id`` and a stop affects only the entry
registered under the requester's own ``user_id``.

Requirements: 3.1, 3.2
"""

from __future__ import annotations

import os
import signal
import threading
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RunEntry:
    """A single user's active Agentic_Run."""

    pid: int                       # child process pid
    pgid: int                      # process group id (== pid due to setsid)
    process: object                # the subprocess.Popen handle
    stop_requested: threading.Event = field(default_factory=threading.Event)


class ProcessRegistry:
    """Thread-safe registry of active Agentic_Runs keyed by ``user_id``.

    All mutation goes through the internal lock so the streaming thread
    (register/unregister) and the stop endpoint (lookup/remove) never race.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._runs: dict[str, RunEntry] = {}

    def register(self, user_id: str, process) -> RunEntry:
        """Record a newly launched process, replacing any stale entry.

        Computes the process group id up front via ``os.getpgid`` (equal to the
        pid because the child was launched with ``os.setsid``) and overwrites
        any prior entry for the same user, keeping only the current run.
        """
        pgid = os.getpgid(process.pid)
        entry = RunEntry(pid=process.pid, pgid=pgid, process=process)
        with self._lock:
            self._runs[str(user_id)] = entry
        return entry

    def get(self, user_id: str) -> Optional[RunEntry]:
        """Return the active run for ``user_id`` (or ``None``)."""
        with self._lock:
            return self._runs.get(str(user_id))

    def unregister(self, user_id: str) -> None:
        """Idempotent removal. Safe to call from any exit path."""
        with self._lock:
            self._runs.pop(str(user_id), None)

    def request_stop(self, user_id: str) -> Optional[RunEntry]:
        """Mark a user's run for stop and return its entry (or ``None``).

        Sets the cooperative stop flag and returns the entry to terminate in a
        single locked operation, avoiding a lookup/mutate race.
        """
        with self._lock:
            entry = self._runs.get(str(user_id))
            if entry is not None:
                entry.stop_requested.set()
            return entry


def force_terminate(entry: RunEntry, grace_seconds: float = 5.0) -> None:
    """SIGTERM the process group, then SIGKILL if still alive.

    Mirrors the timeout teardown already used in ``api_request_dev_ai_for_app``:
    send ``SIGTERM`` to the recorded process group, wait ``grace_seconds`` for a
    graceful shutdown, then escalate to ``SIGKILL`` only if the process has not
    exited.

    Raises ``ProcessLookupError`` only if the group is already gone, which the
    caller treats as "already terminated" (success).

    Requirements: 2.2, 2.3
    """
    os.killpg(entry.pgid, signal.SIGTERM)
    time.sleep(grace_seconds)
    if entry.process.poll() is None:
        os.killpg(entry.pgid, signal.SIGKILL)


# Single process-wide instance imported by the routes.
process_registry = ProcessRegistry()
