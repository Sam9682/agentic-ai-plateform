"""PostgreSQL advisory-lock helpers for cross-process coordination.

Phase 4 (runtime-execution-hardening) replaces the orchestrator's in-process
``threading.Lock`` with a session-scoped PostgreSQL advisory lock so that
reconciliation is serialized *across processes* (not just across threads in a
single interpreter) without introducing any new infrastructure.

The public surface is intentionally tiny and pure/injectable so it can be
unit-tested with a fake connection whose cursor merely records the
``pg_advisory_lock`` / ``pg_try_advisory_lock`` / ``pg_advisory_unlock`` calls
(no live PostgreSQL required).

Requirements: 3.4, 3.5, 7.2, 7.3, 8.3
"""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
from typing import Iterator

# 'WA' (Weaviate/Workload Agentic platform namespace tag). Folded into the key
# derivation so advisory keys minted here are unlikely to collide with keys
# chosen by unrelated tooling sharing the same database.
RECONCILE_LOCK_NAMESPACE = 0x5741

# PostgreSQL advisory locks use a signed 64-bit integer key. These bounds are
# used to fold an arbitrary hash into the valid range.
_INT64_MIN = -(2 ** 63)
_INT64_MAX = (2 ** 63) - 1
_UINT64_MOD = 2 ** 64


def _acquire(conn, key: int, blocking: bool) -> bool:
    """Acquire the advisory lock identified by ``key`` on ``conn``.

    Blocking acquisition uses ``pg_advisory_lock`` (which waits until the lock
    is available and therefore always succeeds). Non-blocking acquisition uses
    ``pg_try_advisory_lock`` and returns ``False`` immediately if another
    session already holds the lock.

    Returns ``True`` when the lock was acquired, ``False`` otherwise.
    """
    cursor = conn.cursor()
    if blocking:
        cursor.execute("SELECT pg_advisory_lock(%s)", (key,))
        cursor.fetchone()
        return True
    cursor.execute("SELECT pg_try_advisory_lock(%s)", (key,))
    row = cursor.fetchone()
    return bool(row and row[0])


def _release(conn, key: int) -> None:
    """Release the advisory lock identified by ``key`` on ``conn``."""
    cursor = conn.cursor()
    cursor.execute("SELECT pg_advisory_unlock(%s)", (key,))
    cursor.fetchone()


@contextmanager
def advisory_lock(conn, key: int, *, blocking: bool = True) -> Iterator[bool]:
    """Session-scoped PostgreSQL advisory lock context manager.

    On enter, attempts to acquire the lock for ``key``:

    * ``blocking=True``  -> ``pg_advisory_lock``     (waits, always acquires)
    * ``blocking=False`` -> ``pg_try_advisory_lock``  (skips if already held)

    Yields whether the lock was acquired. The lock is released in ``finally``
    *only* when it was actually acquired, so a failed non-blocking try never
    issues a spurious unlock.

    Usage::

        with advisory_lock(conn, reconcile_lock_key(), blocking=False) as acquired:
            if not acquired:
                return  # another process is reconciling; skip this pass
            ...  # critical section
    """
    acquired = _acquire(conn, key, blocking)
    try:
        yield acquired
    finally:
        if acquired:
            _release(conn, key)


def reconcile_lock_key(scope: str = "global") -> int:
    """Derive a deterministic 64-bit signed advisory-lock key for ``scope``.

    The key is a pure function of ``scope`` (and the fixed namespace), so every
    process deriving a key for the same scope obtains the *same* integer and
    therefore contends on the *same* advisory lock. This is what lets separate
    orchestrator processes serialize reconciliation against one another.

    The derivation hashes a stable ``"<namespace>:<scope>"`` string and folds
    the digest into PostgreSQL's signed ``bigint`` range ([-2**63, 2**63-1]).
    """
    seed = f"{RECONCILE_LOCK_NAMESPACE:#x}:{scope}".encode("utf-8")
    digest = hashlib.sha256(seed).digest()
    unsigned = int.from_bytes(digest[:8], byteorder="big", signed=False)
    # Fold unsigned 64-bit value into the signed 64-bit range.
    signed = (unsigned % _UINT64_MOD)
    if signed > _INT64_MAX:
        signed -= _UINT64_MOD
    assert _INT64_MIN <= signed <= _INT64_MAX
    return signed
