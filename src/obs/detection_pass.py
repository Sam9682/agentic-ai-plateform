"""OBS detection pass (Phase 5, Task 4.1). Deterministic, no LLM/ML.

The asynchronous stage added to the Phase 2 agent-worker poll loop. It pulls a
recent observation window per monitored agent/runtime, builds the behavioral
``signals`` bundle (:mod:`src.obs.signal_bundle`), runs the existing
deterministic :func:`src.obs.anomaly_engine.analyze` + Risk_Scoring (reused
unchanged), persists each finding through :mod:`src.obs.obs_repository`, and
routes by severity: a ``CRITICAL`` finding is auto-quarantined through the
Phase 3 governance quarantine coordinator; ``HIGH``/``MEDIUM`` findings are
persisted and surfaced for review (R1, R3).

``DetectionPass`` takes **injected collaborators only** (an OBS repo, a
runtime-monitor repo, the ``analyze``/``score_of`` callables, a governance
``quarantine`` callable, a ``WindowConfig``, a ``clock``, and an
``agents_source`` provider), so it is unit-testable with mocks and needs no
live DB or ZAF (R14.1). It runs no LLM and no ML model (R1.6, R13.7).

On ANY failure during detection or quarantine the pass logs the exception and
re-raises a :class:`DetectionError` so the worker never continues with
enforcement silently disabled (R1.8, R3.3).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from ..aro import event_service
from .signal_bundle import analyze_thresholds, build_signal_bundle

logger = logging.getLogger(__name__)


class DetectionError(Exception):
    """Raised when a detection cycle (or its quarantine routing) fails.

    Propagated out of :meth:`DetectionPass.run_cycle` so the Agent_Worker
    surfaces the failure rather than treating the cycle as a normal empty poll
    (R1.8). The original exception is chained for debugging.
    """


# Severity -> recommended enforcement action (deterministic lookup, R1.3).
_RECOMMENDED_ACTION = {
    "CRITICAL": "QUARANTINE",
    "HIGH": "REVIEW",
    "MEDIUM": "MONITOR",
    "LOW": "MONITOR",
    "INFO": "MONITOR",
}


def _recommend(severity: str) -> str:
    return _RECOMMENDED_ACTION.get((severity or "").upper(), "MONITOR")


class DetectionPass:
    """One deterministic OBS detection cycle over the current windows (R1.1)."""

    def __init__(
        self,
        *,
        tenant_id: int,
        obs_repo: Any,
        rt_repo: Any,
        analyze: Callable[..., Dict[str, Any]],
        score_of: Optional[Callable[..., Any]],
        quarantine: Callable[..., Any],
        cfg: Any,
        clock: Callable[[], float],
        agents_source: Callable[[], List[Dict[str, Any]]],
    ) -> None:
        self._tenant_id = tenant_id
        self._obs_repo = obs_repo
        self._rt_repo = rt_repo
        self._analyze = analyze
        self._score_of = score_of
        self._quarantine = quarantine
        self._cfg = cfg
        self._clock = clock
        self._agents_source = agents_source

    def run_cycle(self) -> List[Dict[str, Any]]:
        """Run one deterministic detection cycle; return persisted records.

        For each monitored agent/runtime:
          1. load the recent observation window + in-window events
          2. ``signals = build_signal_bundle(...)``
          3. ``result = analyze(signals, thresholds={repeat_command_threshold: ...})``
          4. for each finding: persist + route by severity.

        Deterministic detection completes here and returns BEFORE the worker's
        optional ML scoring hook runs (R1.7); this method performs no ML.

        On ANY failure the exception is logged and re-raised as a
        :class:`DetectionError` so enforcement is never left disabled (R1.8).
        """
        try:
            records: List[Dict[str, Any]] = []
            now = self._clock()
            thresholds = analyze_thresholds(self._cfg)
            for agent in self._agents_source() or []:
                runtime_id = agent.get("runtime_id")
                session_id = agent.get("session_id")
                observations, events = self._load_window(agent, now)
                signals = build_signal_bundle(
                    observations=observations,
                    events=events,
                    allowed_globs=agent.get("allowed_globs", []),
                    cfg=self._cfg,
                    now=now,
                    clock_of=self._clock_of,
                )
                result = self._analyze(signals, thresholds)
                risk = result.get("risk", {}) or {}
                for finding in result.get("anomalies", []) or []:
                    records.append(
                        self._persist_and_route(
                            agent, runtime_id, session_id, finding, risk
                        )
                    )
            return records
        except DetectionError:
            # Already logged at the raise site; propagate without re-wrapping.
            raise
        except Exception as exc:  # pragma: no cover - exercised via mocks
            logger.exception("detection cycle failed for tenant %s", self._tenant_id)
            raise DetectionError("detection cycle failed") from exc

    def _persist_and_route(
        self,
        agent: Dict[str, Any],
        runtime_id: Optional[str],
        session_id: Optional[str],
        finding: Dict[str, Any],
        risk: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Persist one finding then route it by severity (R1.2, R1.3, R3.*).

        Evidence is redacted via ``event_service.redact`` before persistence
        (R6.3), so a command shape that happens to embed a token is masked.
        CRITICAL -> quarantine with the anomaly as evidence then
        ``enforcement_status='quarantined'`` (R3.1); HIGH/MEDIUM -> persist and
        surface with ``'surfaced'`` and no quarantine (R3.2). A quarantine
        failure is logged and re-raised (R3.3).
        """
        severity = finding.get("severity", "")
        recommended_action = _recommend(severity)
        evidence = event_service.redact(finding.get("evidence", []))
        risk_score = int(risk.get("score", 0) or 0)

        # record_anomaly persists the engine finding (reused unchanged).
        anomaly_db_id = self._obs_repo.record_anomaly(
            self._tenant_id,
            agent.get("identity"),
            finding.get("rule_id"),
            severity,
            risk_score,
            evidence,
        )

        record = {
            "anomaly_id": f"anom-{uuid.uuid4().hex[:12]}",  # stable business id
            "db_id": anomaly_db_id,
            "agent_id": agent.get("identity"),
            "runtime_id": runtime_id,
            "session_id": session_id,
            "severity": severity,
            "rule_id": finding.get("rule_id"),
            "evidence": evidence,
            "detected_at": self._clock_iso(),  # detection timestamp
            "recommended_action": recommended_action,
            "enforcement_status": "pending",
        }

        if (severity or "").upper() == "CRITICAL":  # R3.1
            try:
                self._quarantine(
                    evidence=record, agent=agent, reason=finding.get("rule_id")
                )
                record["enforcement_status"] = "quarantined"
            except Exception as exc:
                logger.exception(
                    "quarantine failed for %s", agent.get("identity")
                )
                raise DetectionError("quarantine failed") from exc  # R3.3
        else:  # HIGH/MEDIUM/lower -> surface only (R3.2)
            record["enforcement_status"] = "surfaced"

        # Persist the enforcement/routing columns on the just-inserted row (R3.4).
        self._obs_repo.set_enforcement(
            self._tenant_id,
            anomaly_db_id,
            record["enforcement_status"],
            runtime_id=runtime_id,
            session_id=session_id,
            recommended_action=recommended_action,
        )
        return record

    # -- window loading / timestamps (injected-collaborator seams) -----------

    def _load_window(
        self, agent: Dict[str, Any], now: float
    ) -> (List[Dict[str, Any]], List[Dict[str, Any]]):
        """Load the recent observation window + in-window events for an agent.

        Reads only from the injected ``rt_repo``/``obs_repo`` seams so the pass
        stays mockable with no live runtime-monitor DB. An agent entry may carry
        its own ``observations``/``events`` (already-windowed inputs, used by
        tests and callers that pre-load), otherwise they are pulled from the
        runtime-monitor repo by container primary key.
        """
        observations = agent.get("observations")
        if observations is None and self._rt_repo is not None:
            container_pk = agent.get("container_pk")
            if container_pk is not None:
                observations = self._rt_repo.get_recent_observations(
                    container_pk, limit=agent.get("window_limit", 50)
                )
        events = agent.get("events") or []
        return list(observations or []), list(events)

    def _clock_of(self, item: Dict[str, Any]) -> Optional[float]:
        """Extract an epoch-seconds timestamp from an observation/event dict."""
        ts = item.get("ts")
        if ts is None:
            ts = item.get("timestamp")
        if ts is None:
            return None
        if isinstance(ts, (int, float)):
            return float(ts)
        if isinstance(ts, datetime):
            return ts.timestamp()
        if isinstance(ts, str):
            try:
                return datetime.fromisoformat(ts).timestamp()
            except ValueError:
                return None
        return None

    def _clock_iso(self) -> str:
        """Detection timestamp as an ISO-8601 UTC string from the injected clock."""
        return datetime.fromtimestamp(self._clock(), tz=timezone.utc).isoformat()
