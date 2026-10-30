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


class VaultError(Exception):
    """Raised for vault misuse (e.g. attempting to store empty plaintext)."""


def _derive_fernet_key(raw: str) -> bytes:
    """Derive a urlsafe-base64 32-byte Fernet key from an arbitrary secret.

    ``ZAF_SECRET_KEY`` may be any string; Fernet requires a 32-byte urlsafe
    base64 key. We hash the secret to 32 bytes and base64-encode it. This is
    deterministic so ciphertext written with a given secret decrypts across
    restarts.
    """
    digest = hashlib.sha256(raw.encode("utf-8")).digest()
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
    """Thin AEAD wrapper (Fernet) around a derived key. Pure, DB-free."""

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


def encrypt(plaintext: str, secret: Optional[str] = None) -> str:
    """Encrypt plaintext to a storable ciphertext string."""
    return Cipher(secret).encrypt(plaintext)


def decrypt(ciphertext: str, secret: Optional[str] = None) -> str:
    """Decrypt a ciphertext string produced by :func:`encrypt`."""
    return Cipher(secret).decrypt(ciphertext)


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
        INSERT INTO agent_credentials (tenant_id, agent_id, name, kind, scope, ciphertext)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (tenant_id, name) DO UPDATE SET
            ciphertext = EXCLUDED.ciphertext,
            kind = EXCLUDED.kind,
            scope = EXCLUDED.scope,
            agent_id = EXCLUDED.agent_id,
            status = 'active',
            rotated_at = CURRENT_TIMESTAMP
        RETURNING id
        """,
        (tenant_id, agent_id, name, kind, scope, ciphertext),
        fetch_one=True,
    )
    return int(row[0])


def get(tenant_id: int, credential_id: int) -> Optional[Dict[str, Any]]:
    """Return a credential's decrypted plaintext + metadata, tenant-scoped.

    Returns None when the credential does not exist, belongs to another tenant,
    or has been revoked. Callers must treat the returned ``plaintext`` as a
    secret (never log or event it unredacted).
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
        "plaintext": decrypt(row[6]),
        "status": row[7],
    }


def rotate(tenant_id: int, credential_id: int, new_plaintext: str) -> bool:
    """Replace a credential's ciphertext with a freshly encrypted value."""
    ciphertext = encrypt(new_plaintext)
    rows = _get_db().execute_query(
        """
        UPDATE agent_credentials
        SET ciphertext = %s, rotated_at = CURRENT_TIMESTAMP, status = 'active'
        WHERE id = %s AND tenant_id = %s
        """,
        (ciphertext, credential_id, tenant_id),
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

    Returns ``{token, expires_at, scope}``. The clear-text token is returned to
    the caller exactly once; only its hash is stored. Minting a token for a
    revoked/missing credential raises :class:`VaultError` (fail closed).
    """
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
