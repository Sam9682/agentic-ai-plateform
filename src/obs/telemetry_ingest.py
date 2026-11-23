"""Authenticated runtime telemetry ingestion (ABF/AET event foundation, Phase 1).

Agent runtimes that the control plane cannot observe through Docker (remote-LLM
agents, Kiro/SHAI sessions, custom runtimes) report their actions here. The
service turns an untrusted batch into normalized, redacted, provenance-tagged
rows in the unified ``agent_events`` stream.

Security properties (spec §10):

* **Authenticated sources.** Every request carries a per-agent ingest token
  (``ingest_tokens``). Unknown, expired and revoked tokens get 401.
* **Identity binding.** Tenant and agent identity come from the token only;
  any ``agent_id`` / ``tenant_id`` in the payload is ignored.
* **Forgery resistance.** Event types are server-assigned
  (``telemetry.<category>``); SECURITY/RUNTIME categories are refused;
  agent-supplied severity/risk/decision are ignored; every row is tagged
  ``ingest_source='runtime_reported'`` with the token as ``ingest_principal``.
* **Trace integrity.** An event claiming a ``task_id`` that belongs to another
  agent is rejected.
* **Replay / duplicates.** Client event ids are namespaced per agent and are
  idempotent (``ON CONFLICT DO NOTHING``); duplicates are reported, not
  re-counted. Stale and future-dated events are rejected.
* **Backpressure.** Bounded batch size (413) and a per-token request rate
  (429 + ``Retry-After``). The limiter is in-process (per worker), which bounds
  load per process but is not a global quota (documented limitation).

Collaborators are injected so the service is unit-testable without a DB.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from ..aro import event_service
from ..zaf.mcp_gateway import RateLimiter
from . import behavior_events as be
from . import ingest_tokens

RUNTIME_SOURCE = "runtime-telemetry"
DEFAULT_MAX_BATCH = 500
DEFAULT_REQUESTS_PER_MINUTE = 120


@dataclass
class IngestResult:
    status_code: int
    payload: Dict[str, Any]
    headers: Dict[str, str] = field(default_factory=dict)


def _default_task_owner(tenant_id: int, task_ref: str) -> Optional[int]:
    from ..aro import task_repository
    return task_repository.get_task_agent_by_ref(tenant_id, task_ref)


class TelemetryIngestService:
    """Validates and persists a batch of runtime-reported events."""

    def __init__(
        self,
        *,
        verify_token: Callable[[Any], Optional[Dict[str, Any]]] = ingest_tokens.verify,
        touch_token: Callable[[int], None] = ingest_tokens.touch,
        events_repo: Any = None,
        task_owner: Callable[[int, str], Optional[int]] = _default_task_owner,
        rate_limiter: Optional[RateLimiter] = None,
        limits: be.IngestLimits = be.IngestLimits(),
        max_batch: int = DEFAULT_MAX_BATCH,
        requests_per_minute: int = DEFAULT_REQUESTS_PER_MINUTE,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        inspector: Optional[Callable[[int, int, Optional[str], List[Dict[str, Any]]], Any]] = None,
        sealer: Optional[Callable[[int], Any]] = None,
    ):
        if events_repo is None:
            from ..aro import events_repository as _er
            events_repo = _er
        self._verify = verify_token
        self._touch = touch_token
        self._events = events_repo
        self._task_owner = task_owner
        self._rate = rate_limiter or RateLimiter()
        self._limits = limits
        self._max_batch = int(max_batch)
        self._rpm = int(requests_per_minute)
        self._clock = clock
        # ABF detection on the accepted events (Phase 2) and audit-chain sealing.
        # Both run after persistence and can never fail or slow-reject ingestion.
        self._inspector = inspector
        self._sealer = sealer

    # ------------------------------------------------------------------ #
    def ingest(self, token: Optional[str], body: Any) -> IngestResult:
        binding = self._verify(token) if token else None
        if binding is None:
            return IngestResult(401, {"error": "invalid or expired ingest token"})

        key = (f"ingest-token:{binding['token_id']}", "telemetry")
        if not self._rate.allow(key, self._rpm):
            return IngestResult(429, {"error": "rate limit exceeded"}, {"Retry-After": "60"})

        if not isinstance(body, dict):
            return IngestResult(400, {"error": "body must be a JSON object with an events array"})
        raw_events = body.get("events")
        if isinstance(raw_events, list) and len(raw_events) > self._max_batch:
            return IngestResult(413, {"error": f"batch exceeds {self._max_batch} events",
                                      "max_batch": self._max_batch})
        events, err = be.split_known(raw_events, self._max_batch)
        if err:
            return IngestResult(400, {"error": err})

        now = self._clock()
        results: List[Dict[str, Any]] = []
        owner_cache: Dict[str, Optional[int]] = {}
        counts = {"accepted": 0, "duplicate": 0, "rejected": 0}
        accepted_events: List[Dict[str, Any]] = []

        for index, raw in enumerate(events):
            try:
                outcome = self._ingest_one(binding, raw, now, owner_cache)
            except be.ValidationError as exc:
                outcome = {"index": index, "status": "rejected", "error": str(exc)}
            stored_event = outcome.pop("_event", None)
            if outcome["status"] == "accepted" and stored_event is not None:
                accepted_events.append(stored_event)
            outcome["index"] = index
            counts[outcome["status"]] += 1
            results.append(outcome)

        self._touch(binding["token_id"])
        if accepted_events and self._inspector is not None:
            try:
                # Detection results are deliberately not returned to the agent:
                # a runtime must not learn which rules fired.
                self._inspector(binding["tenant_id"], binding["agent_db_id"],
                                binding["agent_identity"], accepted_events)
            except Exception:  # noqa: BLE001 - telemetry continues
                pass
        if accepted_events and self._sealer is not None:
            try:
                self._sealer(binding["tenant_id"])
            except Exception:  # noqa: BLE001
                pass
        return IngestResult(200, {
            "agent_identity": binding["agent_identity"],
            "accepted": counts["accepted"],
            "duplicates": counts["duplicate"],
            "rejected": counts["rejected"],
            "results": results,
        })

    # ------------------------------------------------------------------ #
    def _ingest_one(self, binding: Dict[str, Any], raw: Any, now: datetime,
                    owner_cache: Dict[str, Optional[int]]) -> Dict[str, Any]:
        fields = be.validate_runtime_event(raw, now=now, limits=self._limits)
        tenant_id = binding["tenant_id"]
        agent_db_id = binding["agent_db_id"]

        task_ref = fields["task_id"]
        if task_ref is not None:
            if task_ref not in owner_cache:
                owner_cache[task_ref] = self._task_owner(tenant_id, task_ref)
            if owner_cache[task_ref] != agent_db_id:
                raise be.ValidationError("task_id does not belong to this agent")

        event_id = (be.namespaced_event_id(agent_db_id, fields["client_event_id"])
                    or f"rt-{agent_db_id}-{uuid.uuid4().hex}")
        parent = fields["parent_event_id"]
        if parent is not None and not parent.startswith(("evt-", "rt-")):
            # A bare client id refers to one of this agent's own events.
            parent = be.namespaced_event_id(agent_db_id, parent)

        risk = be.classify(fields["category"], fields["normalized_action"],
                           fields["resource"], fields["outcome"])
        payload = {
            "metadata": fields["metadata"],
            "risk_basis": risk["risk_basis"],
            "risk_factors": risk["risk_factors"],
            "agent_status_at_ingest": binding.get("agent_status"),
        }
        if fields["ignored_fields"]:
            payload["ignored_client_fields"] = fields["ignored_fields"]

        event = event_service.build_event(
            tenant_id,
            be.runtime_event_type(fields["category"]),
            RUNTIME_SOURCE,
            agent_id=binding["agent_identity"],
            execution_id=task_ref,
            action=payload,
            risk_score=risk["risk_score"],
            severity=risk["severity"],
            correlation_id=fields["trace_id"] or (f"task-{task_ref}" if task_ref else None),
            event_id=event_id,
            occurred_at=fields["occurred_at"],
            trace_id=fields["trace_id"],
            session_id=fields["session_id"],
            task_id=task_ref,
            parent_event_id=parent,
            category=fields["category"],
            normalized_action=fields["normalized_action"],
            resource=fields["resource"],
            outcome=fields["outcome"],
            duration_ms=fields["duration_ms"],
            ingest_source=event_service.INGEST_RUNTIME_REPORTED,
            ingest_principal=f"ingest-token:{binding['token_id']}",
        )
        stored = self._events.append_event(event)
        status = "accepted" if stored.get("inserted", True) else "duplicate"
        return {"status": status, "event_id": event_id,
                "severity": risk["severity"], "risk_score": risk["risk_score"],
                "_event": event}
