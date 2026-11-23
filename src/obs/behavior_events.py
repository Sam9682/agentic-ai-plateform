"""Normalized agent behavior events — validation for runtime-reported telemetry.

ABF/AET event foundation (Phase 1). Pure and deterministic: no I/O, no Flask,
so every rule here is unit-testable.

An agent runtime (Kiro, SHAI, a custom runtime, an agent calling a remote LLM)
reports what it did through the authenticated ingestion endpoint. That input is
**untrusted**:

* The agent identity and tenant are NEVER read from the payload. They come
  from the ingest token the control plane issued (see ``telemetry_ingest``).
* The agent cannot choose the event type. It submits a ``category`` and an
  ``action``; the server derives ``event_type = "telemetry.<category>"``. This
  makes control-plane event types (``governance.*``, ``zaf.*``, ``approval.*``,
  ``agent.*``, ``task.*`` ...) impossible to forge.
* ``SECURITY`` and ``RUNTIME`` categories are reserved for the control plane:
  security decisions and lifecycle facts are only ever recorded by the platform.
* Any severity / risk / decision the agent supplies is ignored. Risk is
  classified server-side from the normalized action and resource.
* Client event ids are namespaced per agent, so one agent cannot collide with
  (or pre-empt) another agent's or the control plane's event ids.
* Timestamps outside a configurable skew window are rejected (replay of stale
  events, or future-dated events that would distort timelines).
* Sizes are bounded: metadata, strings and nesting depth are capped.

Metadata is stored as inert data. Nothing in it is ever interpreted as a policy
instruction (prompt-injection safety): the only fields that influence
classification are the normalized ``category``, ``action`` and ``resource``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from ..aro.event_service import VALID_CATEGORIES, VALID_OUTCOMES
from . import risk_scoring

# Categories a runtime may report. SECURITY/RUNTIME are control-plane only.
CONTROL_PLANE_ONLY_CATEGORIES = frozenset({"SECURITY", "RUNTIME"})
RUNTIME_CATEGORIES = tuple(c for c in VALID_CATEGORIES if c not in CONTROL_PLANE_ONLY_CATEGORIES)

# Fields an agent might send that the server deliberately ignores (it never
# trusts an agent's own assessment of its behavior).
IGNORED_CLIENT_FIELDS = ("severity", "risk_score", "risk_level", "decision",
                         "agent_id", "agent_identity", "tenant_id", "source",
                         "event_type", "ingest_source")

_ID_RE = re.compile(r"^[A-Za-z0-9._:\-]{1,128}$")
_ACTION_RE = re.compile(r"[^a-z0-9_.:\-]+")


@dataclass(frozen=True)
class IngestLimits:
    """Bounds applied to runtime-reported events."""

    max_future_skew_seconds: int = 300        # 5 min clock drift tolerated
    max_age_seconds: int = 24 * 3600          # older events are rejected
    max_metadata_bytes: int = 16 * 1024
    max_metadata_depth: int = 6
    max_string_length: int = 4096
    max_resource_length: int = 1024
    max_duration_ms: int = 7 * 24 * 3600 * 1000


class ValidationError(ValueError):
    """A runtime-reported event failed validation (message is safe to return)."""


def _parse_ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        ts = value
    elif isinstance(value, str) and value:
        raw = value.strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            ts = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise ValidationError("occurred_at must be an ISO-8601 timestamp") from exc
    else:
        raise ValidationError("occurred_at must be an ISO-8601 timestamp")
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)  # naive -> interpreted as UTC
    return ts.astimezone(timezone.utc)


def normalize_action(action: Any) -> str:
    """Lowercase, restrict charset to ``[a-z0-9_.:-]``, collapse runs, cap length."""
    if not isinstance(action, str) or not action.strip():
        raise ValidationError("action is required")
    norm = _ACTION_RE.sub("_", action.strip().lower()).strip("_")
    if not norm:
        raise ValidationError("action is required")
    return norm[:128]


def _depth(value: Any, level: int = 0) -> int:
    if isinstance(value, dict):
        return max([level + 1] + [_depth(v, level + 1) for v in value.values()])
    if isinstance(value, list):
        return max([level + 1] + [_depth(v, level + 1) for v in value])
    return level


def _truncate_strings(value: Any, max_len: int) -> Any:
    if isinstance(value, str):
        return value if len(value) <= max_len else value[:max_len] + "…[truncated]"
    if isinstance(value, dict):
        return {str(k)[:128]: _truncate_strings(v, max_len) for k, v in value.items()}
    if isinstance(value, list):
        return [_truncate_strings(v, max_len) for v in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:max_len]


def _optional_id(raw: Dict[str, Any], key: str) -> Optional[str]:
    value = raw.get(key)
    if value in (None, ""):
        return None
    if not isinstance(value, str) or not _ID_RE.match(value):
        raise ValidationError(f"{key} must match [A-Za-z0-9._:-]{{1,128}}")
    return value


def namespaced_event_id(agent_db_id: int, client_event_id: Optional[str]) -> Optional[str]:
    """Scope a client-chosen event id to the reporting agent (``rt-<agent>-<id>``)."""
    if not client_event_id:
        return None
    return f"rt-{int(agent_db_id)}-{client_event_id}"


def classify(category: str, action: str, resource: Optional[str],
             outcome: Optional[str]) -> Dict[str, Any]:
    """Server-side, explainable risk classification of an observed action.

    Reuses the deterministic OBS :func:`risk_scoring.score` (action sensitivity
    + resource criticality). A failed or denied outcome adds no inferred
    malice; it is recorded as a fact. ABF behavioral rules (Phase 2) refine
    this per sequence of events; this is only the per-event baseline.
    """
    explanation = risk_scoring.score(action=f"{category.lower()}.{action}",
                                     resource=resource or "")
    return {
        "risk_score": explanation.score,
        "severity": explanation.severity,
        "risk_basis": "server_side_static_classification",
        "risk_factors": [{"name": n, "points": p} for n, p in explanation.factors],
    }


def validate_runtime_event(
    raw: Any,
    *,
    now: datetime,
    limits: IngestLimits = IngestLimits(),
) -> Dict[str, Any]:
    """Validate and normalize one runtime-reported event.

    Returns the keyword arguments for :func:`event_service.build_event` (minus
    tenant / agent / provenance, which the ingestion service binds from the
    token), plus ``client_event_id`` and ``ignored_fields``. Raises
    :class:`ValidationError` with a client-safe message on invalid input.
    """
    if not isinstance(raw, dict):
        raise ValidationError("each event must be a JSON object")

    category = str(raw.get("category") or "").upper()
    if category in CONTROL_PLANE_ONLY_CATEGORIES:
        raise ValidationError(f"category {category} is reserved for the control plane")
    if category not in RUNTIME_CATEGORIES:
        raise ValidationError("category must be one of: " + ", ".join(RUNTIME_CATEGORIES))

    action = normalize_action(raw.get("action"))

    resource = raw.get("resource")
    if resource is not None:
        if not isinstance(resource, str):
            raise ValidationError("resource must be a string")
        resource = resource[: limits.max_resource_length] or None

    outcome = raw.get("outcome")
    if outcome is not None:
        outcome = str(outcome).upper()
        if outcome not in VALID_OUTCOMES:
            raise ValidationError("outcome must be one of: " + ", ".join(VALID_OUTCOMES))

    duration_ms = raw.get("duration_ms")
    if duration_ms is not None:
        if isinstance(duration_ms, bool) or not isinstance(duration_ms, (int, float)):
            raise ValidationError("duration_ms must be a number")
        duration_ms = int(duration_ms)
        if duration_ms < 0 or duration_ms > limits.max_duration_ms:
            raise ValidationError("duration_ms out of range")

    if raw.get("occurred_at") in (None, ""):
        occurred_at = now
    else:
        occurred_at = _parse_ts(raw.get("occurred_at"))
        if occurred_at > now + timedelta(seconds=limits.max_future_skew_seconds):
            raise ValidationError("occurred_at is too far in the future")
        if occurred_at < now - timedelta(seconds=limits.max_age_seconds):
            raise ValidationError("occurred_at is older than the accepted window")

    metadata = raw.get("metadata")
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        raise ValidationError("metadata must be a JSON object")
    if _depth(metadata) > limits.max_metadata_depth:
        raise ValidationError("metadata is nested too deeply")
    try:
        encoded = json.dumps(metadata, default=str)
    except (TypeError, ValueError) as exc:
        raise ValidationError("metadata must be JSON-serializable") from exc
    if len(encoded.encode("utf-8")) > limits.max_metadata_bytes:
        raise ValidationError("metadata exceeds the size limit")
    metadata = _truncate_strings(metadata, limits.max_string_length)

    ignored = sorted(k for k in IGNORED_CLIENT_FIELDS if k in raw)

    return {
        "client_event_id": _optional_id(raw, "event_id"),
        "category": category,
        "normalized_action": action,
        "resource": resource,
        "outcome": outcome,
        "duration_ms": duration_ms,
        "occurred_at": occurred_at,
        "trace_id": _optional_id(raw, "trace_id"),
        "session_id": _optional_id(raw, "session_id"),
        "task_id": _optional_id(raw, "task_id"),
        "parent_event_id": _optional_id(raw, "parent_event_id"),
        "metadata": metadata,
        "ignored_fields": ignored,
    }


def runtime_event_type(category: str) -> str:
    """Event type the server assigns to a runtime-reported event."""
    return f"telemetry.{category.lower()}"


def split_known(raw_events: Any, max_batch: int) -> Tuple[list, Optional[str]]:
    """Return ``(events, error)`` for a request body's ``events`` array."""
    if not isinstance(raw_events, list):
        return [], "events must be a JSON array"
    if not raw_events:
        return [], "events must not be empty"
    if len(raw_events) > max_batch:
        return [], f"batch exceeds {max_batch} events"
    return raw_events, None
