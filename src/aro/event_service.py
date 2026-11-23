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

# Normalized behavioral event taxonomy (ABF/AET event foundation). Mirrors the
# CHECK constraint in migration/add_event_foundation.sql.
VALID_CATEGORIES = (
    "PROCESS", "SHELL", "FILESYSTEM", "NETWORK", "MCP", "LLM", "API",
    "DATABASE", "RUNTIME", "SECURITY", "RESOURCE",
)
VALID_OUTCOMES = ("SUCCESS", "FAILURE", "DENIED", "UNKNOWN")

# Event provenance. ``control_plane`` = observed by the platform itself;
# ``runtime_reported`` = submitted by an agent runtime through authenticated
# ingestion (untrusted: never allowed to improve a governance score alone).
INGEST_CONTROL_PLANE = "control_plane"
INGEST_RUNTIME_REPORTED = "runtime_reported"
VALID_INGEST_SOURCES = (INGEST_CONTROL_PLANE, INGEST_RUNTIME_REPORTED)

# Optional normalized/correlation fields. They are added to a built event only
# when supplied, so the legacy canonical shape stays byte-for-byte stable for
# existing emitters.
EXTENDED_FIELDS = (
    "trace_id", "session_id", "task_id", "parent_event_id", "category",
    "normalized_action", "resource", "outcome", "duration_ms",
    "ingest_source", "ingest_principal",
)

# Category of control-plane events, derived from the event_type prefix so that
# legacy emitters are classified without changing their call sites.
_EVENT_TYPE_CATEGORY_PREFIXES = (
    ("governance.", "SECURITY"),
    ("zaf.", "SECURITY"),
    ("approval.", "SECURITY"),
    ("security.", "SECURITY"),
    ("abf.", "SECURITY"),
    ("mcp.", "MCP"),
    ("llm.", "LLM"),
    ("agent.", "RUNTIME"),
    ("task.", "RUNTIME"),
    ("runtime.", "RUNTIME"),
    ("session.", "RUNTIME"),
    ("execution.", "RUNTIME"),
    ("supervisor.", "RUNTIME"),
)


def category_for_event_type(event_type: Optional[str]) -> Optional[str]:
    """Return the normalized category implied by a control-plane event_type.

    ``telemetry.<category>`` (runtime-reported) maps to that category. Unknown
    prefixes return ``None`` rather than guessing.
    """
    et = (event_type or "").lower()
    if et.startswith("telemetry."):
        cat = et.split(".", 2)[1].upper() if "." in et else ""
        return cat if cat in VALID_CATEGORIES else None
    for prefix, category in _EVENT_TYPE_CATEGORY_PREFIXES:
        if et.startswith(prefix):
            return category
    return None

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

# Secrets embedded INSIDE a larger string (a shell command line, a URL, a log
# line). Only the secret part is masked so the rest of the command stays useful
# as evidence. Applied when no whole-value pattern above matched.
_QUOTED_OR_BARE = r"(\"[^\"]*\"|'[^']*'|\S+)"
_SECRET_ASSIGNMENT_KEY = re.compile(
    r"PASS(?:WORD|WD)?|SECRET|TOKEN|API_?KEY|PRIVATE_?KEY|ACCESS_?KEY|CREDENTIAL",
    re.IGNORECASE,
)
_INLINE_SECRET_PATTERNS = (
    # URL userinfo: scheme://user:pass@host -> scheme://***@host
    (re.compile(r"([a-z][a-z0-9+.\-]*://)[^\s/@:]+(?::[^\s/@]*)?@", re.IGNORECASE),
     r"\1***@"),
    # KEY=VALUE where KEY names a secret (env exports, inline assignments).
    # The identifier is matched with a bounded quantifier and the keyword is
    # checked in a callback, which keeps matching linear on adversarial input
    # (agent-supplied strings reach this path). Purely numeric values (e.g.
    # max_tokens=100) are not secrets.
    (re.compile(
        r"\b([A-Za-z0-9_]{1,128})(\s*=\s*)(?!\d+(?:\s|$))" + _QUOTED_OR_BARE),
     lambda m: (m.group(1) + m.group(2) + _REDACTED)
     if _SECRET_ASSIGNMENT_KEY.search(m.group(1)) else m.group(0)),
    # CLI flags carrying a secret: --password=x, --token x, -password x
    (re.compile(
        r"((?:^|\s)--?(?:password|passwd|pass|pwd|token|secret|api[-_]?key|"
        r"access[-_]?key|auth[-_]?token)(?:=|\s+))" + _QUOTED_OR_BARE,
        re.IGNORECASE),
     r"\1" + _REDACTED),
    # HTTP Authorization header values (Basic/Bearer/raw).
    (re.compile(
        r"(authorization\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|[^\s,;\"']+(?:\s+[^\s,;\"']+)?)",
        re.IGNORECASE),
     r"\1" + _REDACTED),
)

# Keys that match the secret-key pattern by name but carry plain usage counters
# (LLM token accounting). Exempted ONLY when the value is numeric, so a string
# value under one of these keys is still masked.
_NUMERIC_NON_SECRET_KEYS = frozenset({
    "input_tokens", "output_tokens", "total_tokens", "prompt_tokens",
    "completion_tokens", "cached_tokens", "max_tokens", "tokens",
    "token_count", "cache_read_input_tokens", "cache_creation_input_tokens",
})


def redact_text(value: str) -> str:
    """Mask secrets in a free-form string (command line, URL, log line)."""
    if not isinstance(value, str):
        return value
    for pat in _SECRET_VALUE_PATTERNS:
        if pat.search(value):
            return _REDACTED
    for pat, repl in _INLINE_SECRET_PATTERNS:
        value = pat.sub(repl, value)
    return value


def _redact_value(value: Any) -> Any:
    """Mask a scalar value that looks like a secret; recurse into containers."""
    if isinstance(value, dict):
        return redact(value)
    if isinstance(value, list):
        return [_redact_value(v) for v in value]
    if isinstance(value, str):
        return redact_text(value)
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
        if (isinstance(key, str) and key.lower() in _NUMERIC_NON_SECRET_KEYS
                and isinstance(value, (int, float)) and not isinstance(value, bool)):
            out[key] = value
        elif isinstance(key, str) and _SECRET_KEY_PATTERN.search(key):
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
    trace_id: Optional[str] = None,
    session_id: Optional[str] = None,
    task_id: Optional[str] = None,
    parent_event_id: Optional[str] = None,
    category: Optional[str] = None,
    normalized_action: Optional[str] = None,
    resource: Optional[str] = None,
    outcome: Optional[str] = None,
    duration_ms: Optional[int] = None,
    ingest_source: Optional[str] = None,
    ingest_principal: Optional[str] = None,
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
    event = {
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
    extended = _normalize_extended(
        trace_id=trace_id, session_id=session_id, task_id=task_id,
        parent_event_id=parent_event_id, category=category,
        normalized_action=normalized_action, resource=resource,
        outcome=outcome, duration_ms=duration_ms,
        ingest_source=ingest_source, ingest_principal=ingest_principal,
    )
    event.update(extended)
    return event


def _normalize_extended(**fields: Any) -> Dict[str, Any]:
    """Validate the optional normalized fields; drop the ones not supplied.

    Invalid enum values are dropped (never raised) so a malformed caller can
    never break the audit path. ``resource`` is free text and is redacted.
    """
    out: Dict[str, Any] = {}
    for key in ("trace_id", "session_id", "task_id", "parent_event_id",
                "normalized_action", "ingest_principal"):
        value = fields.get(key)
        if value is not None and str(value) != "":
            out[key] = str(value)[:255]
    resource = fields.get("resource")
    if resource is not None and str(resource) != "":
        out["resource"] = redact_text(str(resource))[:2048]
    category = fields.get("category")
    if category is not None and str(category).upper() in VALID_CATEGORIES:
        out["category"] = str(category).upper()
    outcome = fields.get("outcome")
    if outcome is not None and str(outcome).upper() in VALID_OUTCOMES:
        out["outcome"] = str(outcome).upper()
    duration = fields.get("duration_ms")
    if duration is not None:
        try:
            d = int(duration)
            if d >= 0:
                out["duration_ms"] = d
        except (TypeError, ValueError):
            pass
    source = fields.get("ingest_source")
    if source is not None and source in VALID_INGEST_SOURCES:
        out["ingest_source"] = source
    return out


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
