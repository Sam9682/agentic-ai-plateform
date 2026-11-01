"""Shared execution policy (Phase 4, R1).

A single, pure, synchronous policy that unifies the platform's two parallel
execution engines (the ARO worker and the serverless worker) and the
orchestrator's remote-command paths behind one timeout / bounded-retry /
cancellation contract. It is **factored from** — not a rewrite of — the already
correct and tested Phase 2 reference semantics:

* ``src/aro/agent_worker.py:execute_claimed_task`` — the injected ``clock``,
  the wall-clock deadline (``clock() + timeout_seconds``, ``None`` when the
  budget is missing/non-positive), and the ``cancel_probe`` checked before and
  during execution.
* ``src/aro/execution_manager.py:launch`` — the bounded transient-retry loop
  (``1 + max_retries`` attempts; policy gates stay *outside* the retry) and the
  transient classifier ``_is_transient_failure`` / ``_TRANSIENT_MARKERS``.

Everything that touches wall-clock time or randomness is injected (``clock``,
``sleep``, ``rand``), so timeout / retry / backoff / cancellation are fully
exercised by a fake ``op`` plus a virtual clock with no Docker, PostgreSQL, or
SSH (R1.11, R8.2).

The transient classifier is **reused, not re-implemented**: :func:`ssh_is_transient`
matches ``str(exc)`` against ``src.aro.execution_manager._TRANSIENT_MARKERS``
(R8.2), so SSH connect/timeout/reset/unreachable/DNS/broken-pipe failures are
retryable while a changed host key, auth failure, policy violation, or a
non-zero application exit are deterministic and never retried.
"""

from __future__ import annotations

import random as _random_mod
import time as _time_mod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Optional


class OutcomeStatus(Enum):
    """Terminal classification of a :func:`run_with_policy` run.

    Maps 1:1 to the ARO reference terminals so a caller can route an
    :class:`Outcome` onto its existing finalize logic without translation:

    * ``SUCCEEDED`` — the op returned a value (R1.1).
    * ``FAILED`` — a deterministic (non-transient) failure, or a transient
      failure whose retries were exhausted at ``max_attempts`` (R1.4, R1.5).
    * ``TIMED_OUT`` — the wall-clock budget was exhausted before the op
      completed, or the op reported a deadline/timeout (R1.2).
    * ``CANCELLED`` — cooperative cancellation was observed before an attempt
      or reported by the op mid-flight (R1.7).
    """

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class Outcome:
    """Immutable terminal result of :func:`run_with_policy`.

    Attributes:
        status: The terminal :class:`OutcomeStatus`.
        value: The op's return value on ``SUCCEEDED`` (``None`` otherwise).
        error: The exception that produced a non-success terminal, when one was
            raised (``None`` for ``SUCCEEDED`` and for a budget-exhausted
            ``TIMED_OUT`` that raised nothing).
        attempts: The number of op invocations actually performed.
    """

    status: OutcomeStatus
    value: Any = None
    error: Optional[BaseException] = None
    attempts: int = 0


@dataclass(frozen=True)
class BackoffParams:
    """Parameters for :func:`compute_backoff` (exponential backoff + jitter).

    Attributes:
        base: Base delay in seconds for the first retry (index 0).
        multiplier: Exponential growth factor applied per retry index.
        jitter_fraction: Symmetric jitter as a fraction of the deterministic
            delay; the applied jitter lies in ``[-jitter_fraction, +jitter_fraction]``
            of the deterministic delay.
        cap: Hard ceiling (seconds) on both the deterministic delay and the
            final jittered delay.
    """

    base: float = 0.5
    multiplier: float = 2.0
    jitter_fraction: float = 0.1
    cap: float = 30.0


def compute_backoff(
    index: int,
    p: BackoffParams,
    rand: Callable[[], float] = _random_mod.random,
) -> float:
    """Return the retry delay (seconds) for the retry at 0-based ``index``.

    Pure given ``rand``. Deterministic component grows exponentially but is
    capped; bounded jitter is added and the result is clamped to ``[0, cap]``::

        deterministic = min(cap, base * multiplier ** index)
        jitter        = deterministic * jitter_fraction * (2 * rand() - 1)
        delay         = clamp(deterministic + jitter, 0.0, cap)

    ``rand`` is expected to yield a value in ``[0, 1)`` (the ``random.random``
    contract), so ``2 * rand() - 1`` lies in ``[-1, 1)`` and the jitter never
    exceeds ``±jitter_fraction`` of the deterministic delay. The final clamp
    guarantees ``0 <= delay <= cap`` for every input (R1.6).
    """
    deterministic = min(p.cap, p.base * (p.multiplier ** index))
    jitter = deterministic * p.jitter_fraction * (2.0 * rand() - 1.0)
    return max(0.0, min(p.cap, deterministic + jitter))


class CancelToken:
    """Cooperative cancellation signal (mirrors ``agent_worker``'s cancel probe).

    ``cancelled()`` is polled by :func:`run_with_policy` before each attempt and
    is also meant to be passed into the op so a long-running op can honor it
    mid-flight. Cancellation can be driven two ways:

    * explicitly, by calling :meth:`cancel` (sets a sticky local flag), and/or
    * externally, via an injected ``probe`` callable (e.g. a DB
      ``is_cancel_requested`` check) consulted on every poll.

    The local flag is sticky: once :meth:`cancel` is called the token stays
    cancelled regardless of what ``probe`` later reports.
    """

    def __init__(self, probe: Optional[Callable[[], bool]] = None) -> None:
        self._flag = False
        self._probe = probe

    def cancel(self) -> None:
        """Mark the token cancelled (sticky)."""
        self._flag = True

    def cancelled(self) -> bool:
        """Return ``True`` when cancellation has been requested.

        Checks the sticky local flag first, then the injected ``probe`` (when
        one was provided). Never raises on behalf of the probe's return value.
        """
        if self._flag:
            return True
        return bool(self._probe()) if self._probe is not None else False


class CancelledError(Exception):
    """Raised by an op to signal cooperative cancellation mid-flight (R1.7).

    Distinct from the standard-library ``concurrent.futures.CancelledError`` /
    ``asyncio.CancelledError``; :func:`run_with_policy` maps it to
    :attr:`OutcomeStatus.CANCELLED`.
    """


class DeadlineExceeded(Exception):
    """Raised by an op to signal its own deadline was exceeded (R1.2).

    :func:`run_with_policy` maps it — like the built-in ``TimeoutError`` — to
    :attr:`OutcomeStatus.TIMED_OUT`.
    """


def run_with_policy(
    op: Callable[["CancelToken"], Any],
    *,
    timeout: Optional[float],
    max_attempts: int,
    backoff: BackoffParams = BackoffParams(),
    is_transient: Callable[[BaseException], bool],
    cancel_token: Optional[CancelToken] = None,
    clock: Callable[[], float] = _time_mod.monotonic,
    sleep: Callable[[float], None] = _time_mod.sleep,
    rand: Callable[[], float] = _random_mod.random,
) -> Outcome:
    """Run ``op`` under a wall-clock timeout, bounded transient retry, cancel.

    ``op`` is called as ``op(token)`` where ``token`` is the active
    :class:`CancelToken`, so the op may honor cancellation mid-flight. All time
    and randomness are injected (``clock``/``sleep``/``rand``) so the whole
    contract is unit-testable with a virtual clock and a scripted op.

    Semantics (map 1:1 to the ARO reference):

    * **Cancellation (R1.7).** The token is checked before each attempt; if it
      reports cancelled, no (further) attempt is made and the result is
      ``Outcome(CANCELLED)``. An op that observes the token and raises
      :class:`CancelledError` — or returns after cancelling — is likewise
      reported as ``CANCELLED``.
    * **Timeout (R1.2).** With ``timeout`` set, the deadline is
      ``start + timeout`` measured on ``clock``. If the budget is already
      exhausted before an attempt, or the op raises ``TimeoutError`` /
      :class:`DeadlineExceeded`, the result is ``Outcome(TIMED_OUT)``.
      ``timeout=None`` imposes no wall-clock bound (parity with
      ``agent_worker``'s "no deadline" branch).
    * **Success (R1.1).** The op's return value yields ``Outcome(SUCCEEDED)``.
    * **Failure (R1.3/R1.4/R1.5).** On any other exception, ``is_transient(exc)``
      decides: a deterministic failure is an immediate ``Outcome(FAILED)``;
      a transient failure with attempts remaining sleeps
      ``compute_backoff(index)`` (subject to the remaining budget) and retries;
      a transient failure at the ``max_attempts`` bound is ``Outcome(FAILED)``.

    Args:
        op: The unit of work; called ``op(token)`` and returns a value or raises.
        timeout: Wall-clock budget in seconds, or ``None`` for no bound.
        max_attempts: Maximum number of op invocations (``>= 1``; a value below
            1 is clamped to 1 so the op always runs at least once).
        backoff: :class:`BackoffParams` controlling retry delays.
        is_transient: Predicate classifying an exception as transient
            (retryable) vs deterministic (terminal).
        cancel_token: Optional cooperative-cancellation token; a fresh,
            never-cancelled token is used when omitted.
        clock: Monotonic time source (injected for tests).
        sleep: Delay function (injected for tests).
        rand: ``[0, 1)`` randomness source for jitter (injected for tests).

    Returns:
        A terminal :class:`Outcome`.
    """
    token = cancel_token if cancel_token is not None else CancelToken()
    attempts_cap = max(1, int(max_attempts))

    start = clock()
    deadline = (start + timeout) if (timeout is not None) else None

    attempts = 0
    last_error: Optional[BaseException] = None

    while True:
        # Cancellation is checked before every attempt (R1.7).
        if token.cancelled():
            return Outcome(OutcomeStatus.CANCELLED, attempts=attempts)

        # The remaining wall-clock budget bounds this attempt; an already
        # exhausted budget is a timeout before the op ever runs (R1.2).
        if deadline is not None and clock() >= deadline:
            return Outcome(OutcomeStatus.TIMED_OUT, error=last_error, attempts=attempts)

        attempts += 1
        try:
            value = op(token)
        except CancelledError as exc:
            # An op that honored the token mid-flight (R1.7).
            return Outcome(OutcomeStatus.CANCELLED, error=exc, attempts=attempts)
        except (TimeoutError, DeadlineExceeded) as exc:
            # The op reported it ran out of time (R1.2).
            return Outcome(OutcomeStatus.TIMED_OUT, error=exc, attempts=attempts)
        except BaseException as exc:  # noqa: BLE001 - classify then route
            last_error = exc
            # A cancel observed concurrently with a failure is reported as
            # cancelled — a deliberate cancel is never masked by retry.
            if token.cancelled():
                return Outcome(OutcomeStatus.CANCELLED, error=exc, attempts=attempts)
            # Deterministic failure: immediate terminal, no retry (R1.5).
            if not is_transient(exc):
                return Outcome(OutcomeStatus.FAILED, error=exc, attempts=attempts)
            # Transient failure at the attempt bound: terminal FAILED (R1.4).
            if attempts >= attempts_cap:
                return Outcome(OutcomeStatus.FAILED, error=exc, attempts=attempts)
            # Transient failure with attempts left: back off then retry (R1.3).
            delay = compute_backoff(attempts - 1, backoff, rand=rand)
            # Never sleep past the deadline; an exhausted budget after the
            # failure is a timeout rather than another attempt (R1.2).
            if deadline is not None:
                remaining = deadline - clock()
                if remaining <= 0:
                    return Outcome(
                        OutcomeStatus.TIMED_OUT, error=exc, attempts=attempts
                    )
                delay = min(delay, remaining)
            if delay > 0:
                sleep(delay)
            continue
        else:
            # A success that coincides with a cancel is reported as cancelled
            # (the op chose to stop early); otherwise it is a clean success.
            if token.cancelled():
                return Outcome(OutcomeStatus.CANCELLED, value=value, attempts=attempts)
            return Outcome(OutcomeStatus.SUCCEEDED, value=value, attempts=attempts)


def ssh_is_transient(exc: BaseException) -> bool:
    """Classify an SSH/remote-exec exception as transient (retryable). Pure.

    Reuses the existing, tested markers in
    ``src.aro.execution_manager._TRANSIENT_MARKERS`` (connect/timeout/reset/
    unreachable/DNS/broken-pipe) against ``str(exc)`` — the markers are **not**
    re-implemented here (R8.2). A changed host key
    (``REMOTE HOST IDENTIFICATION HAS CHANGED`` / ``Host key verification
    failed``), an auth failure, a policy violation, and a non-zero application
    exit are not matched, so they are deterministic and never retried.

    When the exception carries a ``stderr`` attribute (e.g. the typed
    ``SSHTransientError``/``SSHDeterministicError`` raised by the hardened
    ``ssh_utils``), that text is included in the classified string so the
    remote stderr drives the decision just as it does in
    ``execution_manager._is_transient_failure``.
    """
    from .aro.execution_manager import _TRANSIENT_MARKERS

    text = str(exc or "")
    stderr = getattr(exc, "stderr", None)
    if stderr:
        text = f"{text}\n{stderr}"
    text = text.lower()
    return any(marker in text for marker in _TRANSIENT_MARKERS)
