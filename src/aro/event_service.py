"""Surface-agnostic unified event model for ARO/ZAF (Task 2).

Holds the pure logic for building, validating and redacting events so it is
unit- and property-testable without Flask or a live database (mirrors the style
of ``agent_control_service.py``). The repository (:mod:`events_repository`)
performs the append-only persistence; this module never touches the DB.

Key guarantees:
* **Redaction before storage.** Secret-like values (keys whose name looks like a
  credential, plus values that look like tokens) are masked so no plaintext
  secret is ever written to ``agent_events`` or logs (SRS §6, §9).
* **Stable schema.** :func:`build_event` always returns every field of the
  canonical event shape, so downstream consumers and the DB insert are stable.
* **Immutable-append semantics.** There is intentionally no update/delete here.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

VALID_DECISIONS = (None, "ALLOW", "DENY", "REQUIRE_APPROVAL", "QUARANTINE")
VALID_SEVERITIES = ("INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL")

# Keys whose name implies a secret value; their values are always masked.
_SECRET_KEY_PATTERN = re.compile(
    r"(pass(word)?|secret|token|api[_-]?key|private[_-]?key|credential|"
    r"authorization|auth[_-]?token|access[_-]?key|session|cookie)",
    re.IGNORECASE,
)

# Value shapes that look like secrets even under an innocuous key: bearer
# tokens, long base64/hex blobs, PEM private-key headers.
_SECRET_VALUE_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._\-]+", re.IGNORECASE),
    re.compile(r"\b[A-Fa-f0-9]{32,}\b"),  # long hex (api keys / hashes)
    re.compile(r"\b[A-Za-z0-9+/]{40,}={0,2}\b"),  # long base64 blobs
)

_REDACTED = "***REDACTED***"


def _redact_value(value: Any) -> Any:
    """Mask a scalar value that looks like a secret; recurse into containers."""
    if isinstance(value, dict):
        return redact(value)
    if isinstance(value, list):
        return [_redact_value(v) for v in value]
    if isinstance(value, str):
        for pat in _SECRET_VALUE_PATTERNS:
            if pat.search(value):
                return _REDACTED
        return value
    return value


def redact(payload: Any) -> Any:
    """Return a deep copy of ``payload`` with secret-like data masked.

    A dict entry is masked when its key name matches a credential pattern OR its
    value matches a secret-value pattern. Lists and nested dicts are handled
    recursively. Non-container inputs are returned via value-level redaction.

    This is intentionally conservative (mask-on-suspicion): it is better to mask
    a benign value than to leak a credential into an immutable audit record.
    """
    if not isinstance(payload, dict):
        return _redact_value(payload)
    out: Dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(key, str) and _SECRET_KEY_PATTERN.search(key):
            out[key] = _REDACTED
        else:
            out[key] = _redact_value(value)
    return out


def _normalize_severity(severity: Optional[str]) -> str:
    s = (severity or "INFO").upper()
    return s if s in VALID_SEVERITIES else "INFO"


def _normalize_decision(decision: Optional[str]) -> Optional[str]:
    if decision is None:
        return None
    d = decision.upper()
    return d if d in VALID_DECISIONS else None


def _clamp_risk(risk_score: Any) -> int:
    try:
        r = int(risk_score)
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, r))


def build_event(
    tenant_id: int,
    event_type: str,
    source: str,
    *,
    agent_id: Optional[str] = None,
    execution_id: Optional[str] = None,
    action: Optional[Dict[str, Any]] = None,
    decision: Optional[str] = None,
    risk_score: Any = 0,
    severity: Optional[str] = None,
    correlation_id: Optional[str] = None,
    event_id: Optional[str] = None,
    occurred_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Build a canonical, redacted, validated event dict (never raises on data).

    All free-form content (``action``) is redacted. Missing identifiers are
    generated: ``event_id`` defaults to a UUID, ``correlation_id`` defaults to
    the ``event_id`` (so a standalone event correlates to itself), and
    ``occurred_at`` defaults to now (UTC). Enum fields are normalized to a valid
    value rather than raising, so a malformed caller can never break the audit
    path.

    Returns:
        A dict with exactly the canonical event fields, ready for the repository.
    """
    eid = event_id or f"evt-{uuid.uuid4().hex}"
    ts = occurred_at or datetime.now(timezone.utc)
    return {
        "event_id": eid,
        "tenant_id": tenant_id,
        "agent_id": agent_id,
        "execution_id": execution_id,
        "event_type": event_type,
        "source": source,
        "action": redact(action or {}),
        "decision": _normalize_decision(decision),
        "risk_score": _clamp_risk(risk_score),
        "severity": _normalize_severity(severity),
        "correlation_id": correlation_id or eid,
        "occurred_at": ts,
    }


def emit(
    repository,
    tenant_id: int,
    event_type: str,
    source: str,
    **kwargs,
) -> Dict[str, Any]:
    """Build an event and append it through ``repository``.

    ``repository`` must expose ``append_event(event_dict) -> event_dict``. The
    built event is returned (with any repository-assigned id) so callers can
    chain a correlation_id into subsequent events.
    """
    event = build_event(tenant_id, event_type, source, **kwargs)
    return repository.append_event(event)
