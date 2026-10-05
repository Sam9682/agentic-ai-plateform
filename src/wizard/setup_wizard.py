"""Guided Setup Wizard step engine for the Onboarding Experience (Requirement 4).

``SetupWizard`` owns the ordered wizard steps, the per-field input validators,
and the ``advance`` transition. It holds no Flask coupling of its own: wizard
state lives in a session-like ``dict`` that is injected (constructor or method
argument) so the engine is testable without a live Flask request. When Flask is
available and no session is supplied it defaults to ``flask.session`` (Req 4.2,
4.6, 4.8).

The validators are pure functions (``@staticmethod``) so the property tests can
exercise them directly (Req 4.3, 4.4, 4.7). ``advance`` implements the
retain-on-failure / persist-on-success behavior: when every field of the
current step is valid, the entered values are persisted to the session and the
result points at the next step; otherwise the wizard stays on the current step,
retains the entered values, and reports exactly the invalid fields (Req 4.2,
4.6).
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Ordered wizard steps (Req 4.1). The order is authoritative: ``advance`` moves
# the pointer strictly forward through this list.
STEP_ORDER = ["domain", "email", "gitea_version", "ssl", "admin_user", "database"]

# Field bounds (Req 4.1, 4.3, 4.4, 4.7).
DOMAIN_MIN_LEN = 1
DOMAIN_MAX_LEN = 253
EMAIL_MIN_LEN = 1
EMAIL_MAX_LEN = 254
PASSWORD_MIN_LEN = 12

# Session key under which the wizard persists collected values + the pointer.
SESSION_KEY = "wizard_state"

# Hostname validation (Req 4.3). A valid hostname is a dot-separated sequence of
# labels; each label is 1..63 chars of letters/digits/hyphen, not starting or
# ending with a hyphen. A single trailing dot (FQDN root) is permitted. The
# overall length bound (1..253) is enforced separately so the reason for a
# rejection stays attributable to the length rule.
_HOSTNAME_LABEL = r"(?!-)[A-Za-z0-9-]{1,63}(?<!-)"
_HOSTNAME_RE = re.compile(
    r"^" + _HOSTNAME_LABEL + r"(?:\." + _HOSTNAME_LABEL + r")*\.?$"
)

# Email validation (Req 4.4). Deliberately pragmatic (not a full RFC 5322
# grammar): exactly one ``@``, a non-empty local part without whitespace, and a
# hostname-shaped domain with at least one dot. The length bound (1..254) is
# enforced separately.
_EMAIL_LOCAL_RE = re.compile(r"^[^@\s]+$")


@dataclass
class StepResult:
    """Outcome of a :meth:`SetupWizard.advance` call.

    ``ok`` is True when every field of the submitted step was valid and the
    wizard advanced. ``next_step`` is the step the wizard now sits on (the
    following step on success, or the same step on failure). ``errors`` maps
    each invalid field name to a message, and its keys are exactly the set of
    fields that were actually invalid (Req 4.6). ``values`` is the retained,
    accumulated set of collected values across all steps so far (Req 4.2).
    """

    ok: bool
    next_step: Optional[str]
    errors: Dict[str, str] = field(default_factory=dict)
    values: Dict[str, Any] = field(default_factory=dict)

    @property
    def invalid_fields(self) -> List[str]:
        """The set of invalid field names (Req 4.6)."""
        return list(self.errors.keys())


def _default_session() -> Optional[dict]:
    """Return ``flask.session`` when Flask is importable and in a context, else None."""
    try:
        from flask import session  # imported lazily so the engine works headless
        return session
    except Exception:  # pragma: no cover - Flask not installed / no app context
        return None


class SetupWizard:
    """Ordered, validated Setup Wizard step engine (Req 4)."""

    STEP_ORDER = STEP_ORDER

    def __init__(self, session: Optional[dict] = None):
        """
        :param session: a session-like mapping used to persist wizard state. When
            omitted, defaults to ``flask.session`` if available, otherwise an
            in-memory dict so the engine is usable/testable without Flask.
        """
        if session is None:
            session = _default_session()
        if session is None:
            session = {}
        self.session = session

    # ------------------------------------------------------------------
    # Validators (pure, static -> directly exercisable by property tests)
    # ------------------------------------------------------------------
    @staticmethod
    def validate_domain(value: Any) -> bool:
        """Return ``True`` iff ``value`` is a valid hostname AND length 1..253 (Req 4.3)."""
        if not isinstance(value, str):
            return False
        if not (DOMAIN_MIN_LEN <= len(value) <= DOMAIN_MAX_LEN):
            return False
        return bool(_HOSTNAME_RE.match(value))

    @staticmethod
    def validate_email(value: Any) -> bool:
        """Return ``True`` iff ``value`` is a valid email AND length 1..254 (Req 4.4)."""
        if not isinstance(value, str):
            return False
        if not (EMAIL_MIN_LEN <= len(value) <= EMAIL_MAX_LEN):
            return False
        if value.count("@") != 1:
            return False
        local, _, domain = value.partition("@")
        if not _EMAIL_LOCAL_RE.match(local):
            return False
        # The domain part must be a valid hostname with at least one dot so bare
        # hostnames (e.g. "a@b") are rejected as email addresses.
        if "." not in domain:
            return False
        if not (DOMAIN_MIN_LEN <= len(domain) <= DOMAIN_MAX_LEN):
            return False
        return bool(_HOSTNAME_RE.match(domain))

    @staticmethod
    def validate_password(value: Any) -> bool:
        """Return ``True`` iff ``value`` has length >= 12 (Req 4.7)."""
        if not isinstance(value, str):
            return False
        return len(value) >= PASSWORD_MIN_LEN

    # ------------------------------------------------------------------
    # Per-step validation dispatch
    # ------------------------------------------------------------------
    def _validate_step(self, step: str, inputs: Dict[str, Any]) -> Dict[str, str]:
        """Return a mapping of ``field -> message`` for every invalid field.

        Only fields that a step is responsible for are validated. Steps without
        constrained fields (``gitea_version``, ``ssl``, ``database``) accept any
        inputs here; their content-specific validation lives in dedicated flows
        (e.g. SSL is handled by :class:`SslConfigurator`).
        """
        errors: Dict[str, str] = {}
        inputs = inputs or {}

        if step == "domain":
            if not self.validate_domain(inputs.get("domain")):
                errors["domain"] = "Domain is not a valid hostname (1-253 characters)."

        elif step == "email":
            if not self.validate_email(inputs.get("email")):
                errors["email"] = "Email is not a valid address (1-254 characters)."

        elif step == "admin_user":
            # Username must be present; password must meet the minimum length.
            username = inputs.get("admin_username")
            if not isinstance(username, str) or not username.strip():
                errors["admin_username"] = "Administrator username is required."
            if not self.validate_password(inputs.get("admin_password")):
                errors["admin_password"] = (
                    f"Password must be at least {PASSWORD_MIN_LEN} characters."
                )

        # gitea_version / ssl / database: no field-level constraints enforced here.
        return errors

    # ------------------------------------------------------------------
    # State access
    # ------------------------------------------------------------------
    def _load_state(self) -> Dict[str, Any]:
        """Return the persisted wizard state, initializing it if absent."""
        state = self.session.get(SESSION_KEY)
        if not isinstance(state, dict):
            state = {"pointer": STEP_ORDER[0], "values": {}}
            self.session[SESSION_KEY] = state
        state.setdefault("pointer", STEP_ORDER[0])
        state.setdefault("values", {})
        return state

    def _save_state(self, state: Dict[str, Any]) -> None:
        self.session[SESSION_KEY] = state
        # Flask sessions need an explicit modified flag to persist mutations.
        try:
            self.session.modified = True  # type: ignore[attr-defined]
        except Exception:
            pass

    @property
    def values(self) -> Dict[str, Any]:
        """The accumulated collected values retained across steps (Req 4.2)."""
        return dict(self._load_state().get("values", {}))

    @property
    def current_step(self) -> str:
        """The step the wizard currently sits on."""
        return self._load_state().get("pointer", STEP_ORDER[0])

    @staticmethod
    def next_step_of(step: str) -> Optional[str]:
        """Return the step following ``step`` in :data:`STEP_ORDER`, or None if last."""
        try:
            idx = STEP_ORDER.index(step)
        except ValueError:
            return None
        if idx + 1 < len(STEP_ORDER):
            return STEP_ORDER[idx + 1]
        return None

    # ------------------------------------------------------------------
    # Advance (Req 4.2, 4.6, 4.8)
    # ------------------------------------------------------------------
    def advance(self, step: str, inputs: Dict[str, Any]) -> StepResult:
        """Attempt to advance from ``step`` with the submitted ``inputs``.

        On all-valid: persist the step's inputs into the retained values, move
        the pointer to the next step, and return ``ok=True`` with the retained
        values (Req 4.2, 4.8). On any invalid field: stay on ``step``, retain
        the already-collected values (the invalid submission is not persisted),
        and return ``ok=False`` with ``errors`` keyed by exactly the invalid
        fields (Req 4.6).
        """
        if step not in STEP_ORDER:
            raise ValueError(f"unknown wizard step: {step!r}")

        state = self._load_state()
        retained = dict(state.get("values", {}))
        inputs = inputs or {}

        errors = self._validate_step(step, inputs)
        if errors:
            # Stay on the current step; retain prior values unchanged (Req 4.6).
            logger.info(
                "Wizard step '%s' rejected; invalid fields: %s",
                step,
                ", ".join(errors.keys()),
            )
            return StepResult(
                ok=False,
                next_step=step,
                errors=errors,
                values=retained,
            )

        # All valid: persist this step's inputs, advance the pointer (Req 4.2, 4.8).
        retained.update(inputs)
        next_step = self.next_step_of(step)
        state["values"] = retained
        state["pointer"] = next_step if next_step is not None else step
        if next_step is None:
            # Final step completed: flag completion (Req 4.8).
            state["completed"] = True
        self._save_state(state)

        return StepResult(
            ok=True,
            next_step=next_step,
            errors={},
            values=dict(retained),
        )

    def is_complete(self) -> bool:
        """True once the final step has been advanced with all-valid inputs (Req 4.8)."""
        return bool(self._load_state().get("completed"))

    def reset(self) -> None:
        """Clear all wizard state (fresh start)."""
        state = {"pointer": STEP_ORDER[0], "values": {}}
        self._save_state(state)
