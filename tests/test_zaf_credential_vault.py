#!/usr/bin/env python3
"""Tests for the ZAF credential vault (Task 3).

Feature: ZAF credential management (SRS §4.6, §9).

Validates:
* crypto round-trip: decrypt(encrypt(x)) == x for arbitrary text.
* ciphertext never equals plaintext and is not trivially reversible.
* empty-plaintext storage is refused (fail closed).
* wrong key cannot decrypt (tamper/rotation safety).
* DB layer (stub db_manager): store writes ciphertext only; get round-trips;
  revoke blocks get; mint + verify respects TTL / revocation.

Run directly:
    python3 tests/test_zaf_credential_vault.py
Or via pytest:
    pytest tests/test_zaf_credential_vault.py
"""
import os
import sys

from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("ZAF_SECRET_KEY", "unit-test-secret-key")

from src.zaf import credential_vault as vault  # noqa: E402


# --------------------------------------------------------------------------- #
# Pure crypto core
# --------------------------------------------------------------------------- #
@given(plaintext=st.text(min_size=1, max_size=200))
@settings(max_examples=100)
def test_encrypt_decrypt_roundtrip(plaintext):
    ct = vault.encrypt(plaintext, secret="k1")
    assert ct != plaintext
    assert vault.decrypt(ct, secret="k1") == plaintext


def test_meaningful_secret_not_verbatim_in_ciphertext():
    # A real credential (long, structured) must not appear verbatim in the
    # ciphertext. (A single coincidental char can appear in base64, so this
    # substring guarantee is asserted only for a non-trivial secret.)
    secret_value = "openstack-app-cred-abc123XYZ-super-secret-0987654321"
    ct = vault.encrypt(secret_value, secret="k1")
    assert secret_value not in ct


def test_empty_plaintext_refused():
    try:
        vault.encrypt("", secret="k1")
        assert False, "expected VaultError"
    except vault.VaultError:
        pass


def test_wrong_key_cannot_decrypt():
    ct = vault.encrypt("topsecret", secret="k1")
    try:
        vault.decrypt(ct, secret="k2")
        assert False, "expected VaultError on wrong key"
    except vault.VaultError:
        pass


def test_missing_env_key_fails_closed(monkeypatch):
    monkeypatch.delenv("ZAF_SECRET_KEY", raising=False)
    try:
        vault.Cipher()  # no explicit secret -> must read env -> must fail
        assert False, "expected VaultError when ZAF_SECRET_KEY unset"
    except vault.VaultError:
        pass


# --------------------------------------------------------------------------- #
# DB-backed operations against an in-memory stub
# --------------------------------------------------------------------------- #
class StubDb:
    """In-memory stand-in supporting the vault's exact SQL shapes."""

    def __init__(self):
        self.creds = {}       # id -> dict
        self.tokens = {}      # token_hash -> dict
        self._cid = 1

    def execute_query(self, sql, params=None, fetch_one=False, fetch_all=False):
        s = " ".join(sql.split()).upper()
        if s.startswith("INSERT INTO AGENT_CREDENTIALS"):
            tenant_id, agent_id, name, kind, scope, ciphertext = params
            # emulate ON CONFLICT (tenant_id, name) upsert
            for c in self.creds.values():
                if c["tenant_id"] == tenant_id and c["name"] == name:
                    c.update(ciphertext=ciphertext, kind=kind, scope=scope,
                             agent_id=agent_id, status="active")
                    return (c["id"],)
            cid = self._cid
            self._cid += 1
            self.creds[cid] = dict(id=cid, tenant_id=tenant_id, agent_id=agent_id,
                                   name=name, kind=kind, scope=scope,
                                   ciphertext=ciphertext, status="active")
            return (cid,)
        if s.startswith("SELECT ID, TENANT_ID, AGENT_ID, NAME, KIND, SCOPE, CIPHERTEXT, STATUS"):
            cid, tenant_id = params
            c = self.creds.get(cid)
            if not c or c["tenant_id"] != tenant_id:
                return None
            return (c["id"], c["tenant_id"], c["agent_id"], c["name"], c["kind"],
                    c["scope"], c["ciphertext"], c["status"])
        if s.startswith("UPDATE AGENT_CREDENTIALS SET CIPHERTEXT"):
            ciphertext, cid, tenant_id = params
            c = self.creds.get(cid)
            if c and c["tenant_id"] == tenant_id:
                c["ciphertext"] = ciphertext
                c["status"] = "active"
                return 1
            return 0
        if s.startswith("UPDATE AGENT_SCOPED_TOKENS SET REVOKED"):
            credential_id, tenant_id = params
            for t in self.tokens.values():
                if t["credential_id"] == credential_id and t["tenant_id"] == tenant_id:
                    t["revoked"] = True
            return 1
        if s.startswith("UPDATE AGENT_CREDENTIALS SET STATUS = 'REVOKED'"):
            cid, tenant_id = params
            c = self.creds.get(cid)
            if c and c["tenant_id"] == tenant_id:
                c["status"] = "revoked"
                return 1
            return 0
        if s.startswith("INSERT INTO AGENT_SCOPED_TOKENS"):
            tenant_id, credential_id, agent_id, token_hash, scope, expires_at = params
            self.tokens[token_hash] = dict(id=len(self.tokens) + 1, tenant_id=tenant_id,
                                           credential_id=credential_id, agent_id=agent_id,
                                           scope=scope, expires_at=expires_at, revoked=False)
            return 1
        if s.startswith("SELECT ID, CREDENTIAL_ID, AGENT_ID, SCOPE, EXPIRES_AT, REVOKED"):
            tenant_id, token_hash = params
            t = self.tokens.get(token_hash)
            if not t or t["tenant_id"] != tenant_id:
                return None
            return (t["id"], t["credential_id"], t["agent_id"], t["scope"],
                    t["expires_at"], t["revoked"])
        return None


def _wire(monkeypatch):
    stub = StubDb()
    monkeypatch.setattr(vault, "_get_db", lambda: stub)
    return stub


def test_store_writes_ciphertext_only(monkeypatch):
    stub = _wire(monkeypatch)
    cid = vault.store(1, "os-cred", "super-secret-value", kind="openstack",
                      scope="openstack:compute:read")
    stored = stub.creds[cid]["ciphertext"]
    assert "super-secret-value" not in stored  # plaintext never persisted
    got = vault.get(1, cid)
    assert got["plaintext"] == "super-secret-value"
    assert got["kind"] == "openstack"


def test_get_is_tenant_scoped(monkeypatch):
    _wire(monkeypatch)
    cid = vault.store(1, "c", "v")
    assert vault.get(2, cid) is None  # other tenant cannot read


def test_revoke_blocks_get(monkeypatch):
    _wire(monkeypatch)
    cid = vault.store(1, "c", "v")
    assert vault.revoke(1, cid) is True
    assert vault.get(1, cid) is None


def test_mint_and_verify_token(monkeypatch):
    _wire(monkeypatch)
    cid = vault.store(1, "c", "v", scope="openstack:compute:read")
    minted = vault.mint_scoped_token(1, cid, "openstack:compute:read", ttl_seconds=300)
    assert "token" in minted
    verified = vault.verify_token(1, minted["token"])
    assert verified is not None
    assert verified["credential_id"] == cid
    assert verified["scope"] == "openstack:compute:read"


def test_expired_token_rejected(monkeypatch):
    _wire(monkeypatch)
    cid = vault.store(1, "c", "v")
    minted = vault.mint_scoped_token(1, cid, "s", ttl_seconds=1)
    # Force expiry by rewriting the stored expires_at into the past.
    import datetime as _dt
    for t in list(vault._get_db().tokens.values()):
        t["expires_at"] = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(seconds=10)
    assert vault.verify_token(1, minted["token"]) is None


def test_mint_for_revoked_credential_fails_closed(monkeypatch):
    _wire(monkeypatch)
    cid = vault.store(1, "c", "v")
    vault.revoke(1, cid)
    try:
        vault.mint_scoped_token(1, cid, "s")
        assert False, "expected VaultError"
    except vault.VaultError:
        pass


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
