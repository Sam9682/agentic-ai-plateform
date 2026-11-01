#!/usr/bin/env python3
"""Property test for canonical session events (Task 11.7).

Feature: phase2-aro-completion, Property 20: Session events use the canonical
schema.

Session state changes (``agent.started`` / ``agent.stopped`` /
``agent.unhealthy`` and the rest of the ``agent.*`` session family) are emitted
through ``event_service.emit`` -> ``events_repository.append_event`` using
``build_event`` (``src/aro/event_service.py``). Requirement 4.5 says these
session events must flow through the existing event service with the canonical
``build_event`` shape and no schema change.

Validates: Requirements 4.5

This drives arbitrary session event emissions through ``event_service.emit``
with a capturing repository fake. For any session-family ``event_type``,
``tenant_id``, ``agent_id``, ``execution_id``, and ``action`` payload (including
secret-like values), the stored event ALWAYS has exactly the canonical event
shape (every canonical field present, no extras) and secret-like action content
is redacted — no plaintext credential survives into the stored audit record.

Run directly:
    python3 tests/test_aro_session_events.py
Or via pytest:
    pytest tests/test_aro_session_events.py
"""
import os
import sys

from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.aro import event_service as es  # noqa: E402

# The exact canonical event shape produced by build_event.
_CANONICAL_FIELDS = {
    "event_id", "tenant_id", "agent_id", "execution_id", "event_type",
    "source", "action", "decision", "risk_score", "severity",
    "correlation_id", "occurred_at",
}

# The agent.* session lifecycle family routed through the event service.
_SESSION_EVENT_TYPES = [
    "agent.started",
    "agent.stopped",
    "agent.unhealthy",
    "agent.recovered",
    "agent.released",
    "agent.reconnected",
    "agent.start.failed",
    "agent.install.failed",
]

# Secret-like values that must never survive into a stored audit record.
_SECRET_VALUES = [
    "AKIA1234567890ABCDEF1234567890ABCDEF1234",          # long base64-ish blob
    "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload",  # bearer token
    "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",            # long hex
    "-----BEGIN RSA PRIVATE KEY-----\nMIIabc\n-----END RSA PRIVATE KEY-----",
]

# Keys whose name alone forces redaction regardless of the value.
_SECRET_KEYS = ["password", "secret", "api_key", "token", "authorization", "credential"]


class CapturingRepo:
    """Repository fake: ``append_event`` records the stored event verbatim.

    Mirrors the ``append_event(event) -> event`` contract that
    ``event_service.emit`` depends on (see ``events_repository.append_event``),
    so what we capture is exactly what would be persisted to ``agent_events``.
    """

    def __init__(self):
        self.events = []
        self._next_id = 1

    def append_event(self, event):
        stored = dict(event)
        stored["id"] = self._next_id
        self._next_id += 1
        self.events.append(stored)
        return stored


def _contains_plaintext_secret(value):
    """True if any known secret marker survives unredacted inside ``value``."""
    if isinstance(value, dict):
        return any(_contains_plaintext_secret(v) for v in value.values())
    if isinstance(value, list):
        return any(_contains_plaintext_secret(v) for v in value)
    if isinstance(value, str):
        for secret in _SECRET_VALUES:
            if secret in value:
                return True
    return False


# A session action payload: innocuous keys, secret-named keys, and innocuous
# keys carrying secret-shaped values — all of which must be redacted on store.
_action_strategy = st.fixed_dictionaries(
    {
        "operation": st.sampled_from(["start", "stop", "reconnect", "health"]),
        "note": st.text(max_size=20),
    },
    optional={
        secret_key: st.sampled_from(_SECRET_VALUES)
        for secret_key in _SECRET_KEYS
    }
    | {
        "handle": st.sampled_from(_SECRET_VALUES),   # secret value, innocuous key
        "detail": st.sampled_from(_SECRET_VALUES),
    },
)


@given(
    event_type=st.sampled_from(_SESSION_EVENT_TYPES),
    tenant_id=st.integers(min_value=1, max_value=10_000),
    agent_id=st.text(min_size=1, max_size=24),
    execution_id=st.text(min_size=1, max_size=24),
    action=_action_strategy,
)
@settings(max_examples=100)
def test_property_session_events_use_canonical_schema(
    event_type, tenant_id, agent_id, execution_id, action
):
    """Feature: phase2-aro-completion, Property 20: Session events use the canonical schema.

    Validates: Requirements 4.5
    """
    repo = CapturingRepo()

    returned = es.emit(
        repo,
        tenant_id,
        event_type,
        "lifecycle",
        agent_id=agent_id,
        execution_id=execution_id,
        action=action,
    )

    # The emission went through the repository exactly once.
    assert len(repo.events) == 1
    stored = repo.events[0]

    # The stored event matches what emit returned (minus repo-assigned id).
    assert returned == stored

    # Canonical shape: exactly the canonical fields, nothing missing, nothing
    # extra beyond the repository-assigned primary key.
    assert set(stored.keys()) == _CANONICAL_FIELDS | {"id"}

    # Identifiers and routing are carried through faithfully.
    assert stored["event_type"] == event_type
    assert stored["tenant_id"] == tenant_id
    assert stored["agent_id"] == agent_id
    assert stored["execution_id"] == execution_id
    assert stored["source"] == "lifecycle"

    # Enum / numeric fields are always present and valid.
    assert stored["severity"] in es.VALID_SEVERITIES
    assert stored["decision"] in es.VALID_DECISIONS
    assert 0 <= stored["risk_score"] <= 100

    # Correlation + identity defaults are populated.
    assert stored["event_id"]
    assert stored["correlation_id"]
    assert stored["occurred_at"] is not None

    # Secret-like action content is redacted: secret-named keys are masked and
    # no plaintext secret value survives anywhere in the stored action.
    stored_action = stored["action"]
    for secret_key in _SECRET_KEYS:
        if secret_key in stored_action:
            assert stored_action[secret_key] == es._REDACTED
    assert not _contains_plaintext_secret(stored_action)


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
