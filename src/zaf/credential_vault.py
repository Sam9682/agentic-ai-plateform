"""Encrypted-at-rest credential vault + scoped token minting (Task 3).

Infrastructure credentials are stored as AEAD ciphertext (Fernet, from the
``cryptography`` package) keyed by ``ZAF_SECRET_KEY``; plaintext never touches
the database (SRS §4.6, §9). Per-execution, a short-lived **scoped token** is
minted that references a credential and carries a narrow scope + TTL, so an
agent is handed an expiring capability rather than the raw secret.

The crypto core (:class:`Cipher`, :func:`encrypt`/:func:`decrypt`) is pure and
testable without a DB. The ``store``/``get``/``rotate``/``revoke`` and
``mint_scoped_token``/``verify_token`` functions use the shared ``db_manager``.
Credential usage is audited through the unified event stream (Task 2).
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from cryptography.fernet import Fernet, InvalidToken

_ENV_KEY = "ZAF_SECRET_KEY"

# Current at-rest encryption scheme for NEW writes (R4.3). Legacy ciphertext
# written before versioning (no ``vN$`` prefix) is read as v0 (R4.4).
CURRENT_KEY_VERSION = "v1"

# v1 KDF parameters (PBKDF2-HMAC-SHA256 with a per-ciphertext salt). A salted KDF
# means two encryptions of the same plaintext differ and a stolen DB does not
# expose the derived key for other ciphertexts.
_V1_SALT_BYTES = 16
_V1_PBKDF2_ITERATIONS = 200_000


class VaultError(Exception):
    """Raised for vault misuse (e.g. attempting to store empty plaintext)."""


class SecretWrapper:
    """A non-leaking holder for a secret plaintext value (R4.5, R12.1).

    The wrapped value is accessible only through an explicit :meth:`reveal`
    opt-in. Every implicit stringification (``repr``/``str``/f-strings/logging)
    renders ``***REDACTED***`` rather than the secret, and serialization is
    refused (``__reduce__`` raises), so a ``SecretWrapper`` cannot be pickled or
    coerced into a JSON-friendly form. There is no ``__iter__`` and no default
    ``__dict__`` (``__slots__`` is set), so there is no incidental way to read
    the value back out other than :meth:`reveal`.
    """

    __slots__ = ("_value",)

    _REDACTED = "***REDACTED***"

    def __init__(self, value: str):
        object.__setattr__(self, "_value", value)

    def reveal(self) -> str:
        """Return the wrapped plaintext. Explicit, auditable opt-in."""
        return self._value

    def zeroize(self) -> None:
        """Clear the wrapped value in place (best-effort scrubbing)."""
        object.__setattr__(self, "_value", "")

    def __repr__(self) -> str:
        return f"SecretWrapper({self._REDACTED})"

    __str__ = __repr__

    def __reduce__(self):
        # Refuse pickling / copy so the secret can never be serialized out.
        raise TypeError("SecretWrapper is not serializable")

    def __setattr__(self, name, value):
        raise AttributeError("SecretWrapper is immutable")

    def __eq__(self, other):
        # Avoid leaking via equality probing against arbitrary values; only two
        # wrappers with identical plaintext compare equal.
        if not isinstance(other, SecretWrapper):
            return NotImplemented
        return self._value == other._value

    def __hash__(self):
        # Hash the identity, not the secret, so the value is not exposed via
        # hash collisions and the object remains usable as a dict/set member.
        return object.__hash__(self)


def _derive_fernet_key(raw: str) -> bytes:
    """Derive a urlsafe-base64 32-byte Fernet key from an arbitrary secret.

    **Legacy v0 path (R4.4).** ``ZAF_SECRET_KEY`` may be any string; Fernet
    requires a 32-byte urlsafe base64 key. We hash the secret to 32 bytes with
    unsalted SHA-256 and base64-encode it. This is deterministic so ciphertext
    written with a given secret decrypts across restarts.

    This function is preserved EXACTLY so credential ciphertext written before
    versioning (no ``vN$`` prefix) still decrypts.
    """
    digest = hashlib.sha256(raw.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _derive_key_v1(raw: str, salt: bytes) -> bytes:
    """Derive a urlsafe-base64 32-byte Fernet key via a salted KDF (v1, R4.3).

    Uses PBKDF2-HMAC-SHA256 over the secret with a per-ciphertext ``salt`` so
    the same plaintext encrypts to different ciphertext each time and the
    derived key is unique per record.
    """
    digest = hashlib.pbkdf2_hmac(
        "sha256", raw.encode("utf-8"), salt, _V1_PBKDF2_ITERATIONS, dklen=32
    )
    return base64.urlsafe_b64encode(digest)


def _get_secret() -> str:
    secret = os.environ.get(_ENV_KEY)
    if not secret:
        # Fail closed on crypto: refuse to operate with a default/empty key so a
        # misconfiguration can't silently store weakly/again-decryptably.
        raise VaultError(
            f"{_ENV_KEY} is not set; refusing to encrypt/decrypt credentials"
        )
    return secret


class Cipher:
    """Thin AEAD wrapper (Fernet) around the legacy v0 derived key. Pure, DB-free.

    Retained for the legacy unsalted path and so ``Cipher()`` still fails closed
    when ``ZAF_SECRET_KEY`` is unset. New writes go through the module-level
    :func:`encrypt`, which emits the versioned v1 envelope.
    """

    def __init__(self, secret: Optional[str] = None):
        self._fernet = Fernet(_derive_fernet_key(secret or _get_secret()))

    def encrypt(self, plaintext: str) -> str:
        if not isinstance(plaintext, str) or plaintext == "":
            raise VaultError("refusing to encrypt empty credential plaintext")
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
        except InvalidToken as exc:  # wrong key / tampered ciphertext
            raise VaultError("credential ciphertext could not be decrypted") from exc


def _decrypt_v0_legacy(ciphertext: str, secret: Optional[str] = None) -> str:
    """Decrypt a legacy (v0) ciphertext via the preserved unsalted-SHA256 path."""
    return Cipher(secret).decrypt(ciphertext)


def encrypt(plaintext: str, secret: Optional[str] = None) -> str:
    """Encrypt plaintext to a storable ``v1$<b64salt>$<fernet_ct>`` envelope (R4.3).

    New writes always use the current (v1) salted-KDF scheme. A fresh random
    salt per call means two encryptions of the same plaintext differ.
    """
    if not isinstance(plaintext, str) or plaintext == "":
        raise VaultError("refusing to encrypt empty credential plaintext")
    salt = secrets.token_bytes(_V1_SALT_BYTES)
    fernet = Fernet(_derive_key_v1(secret or _get_secret(), salt))
    ct = fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")
    b64salt = base64.urlsafe_b64encode(salt).decode("ascii")
    return f"{CURRENT_KEY_VERSION}${b64salt}${ct}"


def decrypt(stored: str, secret: Optional[str] = None) -> str:
    """Decrypt a stored envelope, dispatching on the version tag (R4.3, R4.4).

    ``v1$``-prefixed values take the salted path; anything else is treated as a
    legacy v0 ciphertext and decrypted via the preserved unsalted-SHA256 path.
    """
    if stored.startswith(f"{CURRENT_KEY_VERSION}$"):
        try:
            _, b64salt, ct = stored.split("$", 2)
            salt = base64.urlsafe_b64decode(b64salt.encode("ascii"))
        except Exception as exc:  # malformed envelope
            raise VaultError("credential ciphertext could not be decrypted") from exc
        fernet = Fernet(_derive_key_v1(secret or _get_secret(), salt))
        try:
            return fernet.decrypt(ct.encode("ascii")).decode("utf-8")
        except InvalidToken as exc:  # wrong key / tampered ciphertext
            raise VaultError("credential ciphertext could not be decrypted") from exc
    # Legacy v0: no version prefix -> preserved unsalted-SHA256 path (R4.4).
    return _decrypt_v0_legacy(stored, secret)


def _hash_token(token: str) -> str:
    """Return the SHA-256 hex digest of a token (what we persist)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _get_db():
    from ..database_postgres import db_manager
    return db_manager


# --------------------------------------------------------------------------- #
# Credential storage
# --------------------------------------------------------------------------- #
def store(
    tenant_id: int,
    name: str,
    plaintext: str,
    *,
    kind: str = "generic",
    scope: str = "",
    agent_id: Optional[str] = None,
) -> int:
    """Encrypt and store a credential; return its id. Plaintext is never stored.

    On a duplicate ``(tenant_id, name)`` the ciphertext is rotated in place
    (update), so re-storing a credential with a new value rotates it.
    """
    ciphertext = encrypt(plaintext)
    db = _get_db()
    row = db.execute_query(
        """
        INSERT INTO agent_credentials (tenant_id, agent_id, name, kind, scope, ciphertext, key_version)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (tenant_id, name) DO UPDATE SET
            ciphertext = EXCLUDED.ciphertext,
            kind = EXCLUDED.kind,
            scope = EXCLUDED.scope,
            agent_id = EXCLUDED.agent_id,
            key_version = EXCLUDED.key_version,
            status = 'active',
            rotated_at = CURRENT_TIMESTAMP
        RETURNING id
        """,
        (tenant_id, agent_id, name, kind, scope, ciphertext, CURRENT_KEY_VERSION),
        fetch_one=True,
    )
    return int(row[0])


def get(tenant_id: int, credential_id: int) -> Optional[Dict[str, Any]]:
    """Return a credential's decrypted plaintext + metadata, tenant-scoped.

    Returns None when the credential does not exist, belongs to another tenant,
    or has been revoked. The returned ``plaintext`` is a :class:`SecretWrapper`
    (R4.5): callers must call ``.reveal()`` explicitly at the point of use, so
    the secret cannot leak through logging, f-strings, or JSON serialization.
    """
    db = _get_db()
    row = db.execute_query(
        """
        SELECT id, tenant_id, agent_id, name, kind, scope, ciphertext, status
        FROM agent_credentials WHERE id = %s AND tenant_id = %s
        """,
        (credential_id, tenant_id),
        fetch_one=True,
    )
    if not row or row[7] != "active":
        return None
    return {
        "id": int(row[0]),
        "tenant_id": int(row[1]),
        "agent_id": row[2],
        "name": row[3],
        "kind": row[4],
        "scope": row[5],
        "plaintext": SecretWrapper(decrypt(row[6])),
        "status": row[7],
    }


def rotate(tenant_id: int, credential_id: int, new_plaintext: str) -> bool:
    """Replace a credential's ciphertext with a freshly encrypted value.

    ``encrypt`` always emits the current v1 envelope, so rotating a credential
    that was stored under the legacy v0 scheme re-encrypts it forward to v1
    (and stamps ``key_version = 'v1'``) without any data loss (R4.4).
    """
    ciphertext = encrypt(new_plaintext)
    rows = _get_db().execute_query(
        """
        UPDATE agent_credentials
        SET ciphertext = %s, key_version = %s, rotated_at = CURRENT_TIMESTAMP, status = 'active'
        WHERE id = %s AND tenant_id = %s
        """,
        (ciphertext, CURRENT_KEY_VERSION, credential_id, tenant_id),
    )
    return bool(rows)


def revoke(tenant_id: int, credential_id: int) -> bool:
    """Revoke a credential and all scoped tokens minted from it."""
    db = _get_db()
    db.execute_query(
        "UPDATE agent_scoped_tokens SET revoked = TRUE WHERE credential_id = %s AND tenant_id = %s",
        (credential_id, tenant_id),
    )
    rows = db.execute_query(
        "UPDATE agent_credentials SET status = 'revoked' WHERE id = %s AND tenant_id = %s",
        (credential_id, tenant_id),
    )
    return bool(rows)


# --------------------------------------------------------------------------- #
# Scoped token minting / verification
# --------------------------------------------------------------------------- #
def mint_scoped_token(
    tenant_id: int,
    credential_id: int,
    scope: str,
    ttl_seconds: int = 300,
    *,
    agent_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Mint a short-lived scoped token bound to a credential.

    Returns ``{token, expires_at, scope}`` — only the scoped-token handle, never
    the stored credential plaintext (R4.1, R4.6), so an audit event built from
    this result can carry no secret. The clear-text token is returned to the
    caller exactly once; only its hash is stored. Minting a token for a
    revoked/missing credential raises :class:`VaultError` (fail closed).
    """
    # Existence/liveness check only; the resolved SecretWrapper plaintext is
    # intentionally NOT read or returned here.
    cred = get(tenant_id, credential_id)
    if cred is None:
        raise VaultError("cannot mint token for missing or revoked credential")
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=max(1, int(ttl_seconds)))
    _get_db().execute_query(
        """
        INSERT INTO agent_scoped_tokens
            (tenant_id, credential_id, agent_id, token_hash, scope, expires_at)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (tenant_id, credential_id, agent_id, _hash_token(token), scope, expires_at),
    )
    return {"token": token, "expires_at": expires_at.isoformat(), "scope": scope}


def verify_token(tenant_id: int, token: str) -> Optional[Dict[str, Any]]:
    """Verify a scoped token; return its row when valid, else None (fail closed).

    A token is valid only when it exists for the tenant, is not revoked and has
    not expired. Comparison is by hash — the clear token is never stored.
    """
    row = _get_db().execute_query(
        """
        SELECT id, credential_id, agent_id, scope, expires_at, revoked
        FROM agent_scoped_tokens
        WHERE tenant_id = %s AND token_hash = %s
        """,
        (tenant_id, _hash_token(token)),
        fetch_one=True,
    )
    if not row or bool(row[5]):
        return None
    expires_at = row[4]
    if expires_at is not None:
        now = datetime.now(timezone.utc)
        exp = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=timezone.utc)
        if exp <= now:
            return None
    return {
        "id": int(row[0]),
        "credential_id": int(row[1]),
        "agent_id": row[2],
        "scope": row[3],
        "expires_at": expires_at.isoformat() if expires_at else None,
    }
