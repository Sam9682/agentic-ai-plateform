#!/usr/bin/env python3
"""Tests for SSO token hash integrity via a keyed MAC (Phase 3, Task 15.1).

Feature: phase3-zaf-enforcement (Harden SSO, R7.1/R7.5).

Validates:
* generate_sso_token stores token_mac = hmac_sha256(SSO_MAC_KEY, token_hash)
  and still returns the clear token exactly once (R7.1, R7.5).
* validate_sso_token recomputes the MAC over the stored hash and verifies it
  with hmac.compare_digest before accepting (R7.1).
* A stored hash/MAC tampered with in the DB fails the MAC check (R7.1).
* A pre-existing token with NULL token_mac is accepted during the grace window.
* The expires_at > NOW() SQL predicate is preserved verbatim (R7.5).
* _get_sso_mac_key fails closed when SSO_MAC_KEY is unset.

Run via pytest:
    pytest tests/test_sso_token_mac.py
"""
import hashlib
import hmac
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("SSO_MAC_KEY", "unit-test-sso-mac-key")

from src import auth  # noqa: E402


_MAC_KEY = "unit-test-sso-mac-key"


def _mac(token_hash):
    return hmac.new(
        _MAC_KEY.encode("utf-8"), token_hash.encode("utf-8"), hashlib.sha256
    ).hexdigest()


class _FakeConn:
    """Captures the INSERT performed by generate_sso_token."""

    def __init__(self, sink):
        self._sink = sink

    def cursor(self):
        return self

    def execute(self, sql, params=None):
        self._sink.setdefault("calls", []).append((" ".join(sql.split()), params))

    def commit(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeDbManager:
    """Stub standing in for database_postgres.db_manager."""

    def __init__(self):
        self.sink = {}
        self.query_result = None
        self.last_query = None
        self.last_params = None

    def get_db_connection(self):
        return _FakeConn(self.sink)

    def execute_query(self, sql, params=None, fetch_one=False, fetch_all=False):
        self.last_query = " ".join(sql.split())
        self.last_params = params
        return self.query_result


def _wire(monkeypatch):
    monkeypatch.setenv("SSO_MAC_KEY", _MAC_KEY)
    fake = _FakeDbManager()
    monkeypatch.setattr(auth, "db_manager", fake)
    return fake


# --------------------------------------------------------------------------- #
# MAC key helper
# --------------------------------------------------------------------------- #
def test_get_sso_mac_key_fails_closed(monkeypatch):
    monkeypatch.delenv("SSO_MAC_KEY", raising=False)
    try:
        auth._get_sso_mac_key()
        assert False, "expected RuntimeError when SSO_MAC_KEY unset"
    except RuntimeError:
        pass


def test_compute_token_mac_matches_hmac(monkeypatch):
    monkeypatch.setenv("SSO_MAC_KEY", _MAC_KEY)
    token_hash = hashlib.sha256(b"abc").hexdigest()
    assert auth._compute_token_mac(token_hash) == _mac(token_hash)


# --------------------------------------------------------------------------- #
# generate_sso_token
# --------------------------------------------------------------------------- #
def test_generate_stores_mac_and_returns_clear_token_once(monkeypatch):
    fake = _wire(monkeypatch)

    token = auth.generate_sso_token(user_id=42)

    # Clear token returned exactly once and is non-empty.
    assert isinstance(token, str) and token

    # Find the INSERT call and assert it stores token_mac = mac(token_hash).
    insert = [c for c in fake.sink["calls"] if "INSERT INTO auth_tokens" in c[0]]
    assert len(insert) == 1
    sql, params = insert[0]
    assert "token_mac" in sql
    user_id, token_hash, token_mac, _expires = params
    assert user_id == 42
    assert token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert token_mac == _mac(token_hash)
    # The clear token itself must never be stored.
    assert token not in (token_hash, token_mac)


# --------------------------------------------------------------------------- #
# validate_sso_token
# --------------------------------------------------------------------------- #
def _row(token_hash, token_mac):
    # (id, username, email, first_name, last_name, expires_at, token_mac)
    return (1, "alice", "a@example.com", "Alice", "Smith", "2999-01-01", token_mac)


def test_validate_accepts_matching_mac(monkeypatch):
    fake = _wire(monkeypatch)
    token = "clear-token-value"
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    fake.query_result = _row(token_hash, _mac(token_hash))

    info = auth.validate_sso_token(token)
    assert info is not None
    assert info["id"] == 1 and info["username"] == "alice"
    # SQL-level expiry predicate preserved (R7.5).
    assert "expires_at > NOW()" in fake.last_query


def test_validate_rejects_tampered_mac(monkeypatch):
    fake = _wire(monkeypatch)
    token = "clear-token-value"
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    fake.query_result = _row(token_hash, "deadbeef" * 8)  # wrong MAC

    assert auth.validate_sso_token(token) is None


def test_validate_rejects_tampered_hash(monkeypatch):
    # A hash tampered with in the DB (so the row matches a different hash than
    # the one the MAC was computed over) fails the MAC check.
    fake = _wire(monkeypatch)
    token = "clear-token-value"
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    other_hash = hashlib.sha256(b"different").hexdigest()
    # Row returns a MAC bound to a DIFFERENT hash than token_hash.
    fake.query_result = _row(token_hash, _mac(other_hash))

    assert auth.validate_sso_token(token) is None


def test_validate_accepts_null_mac_grace_window(monkeypatch):
    fake = _wire(monkeypatch)
    token = "legacy-token"
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    fake.query_result = _row(token_hash, None)  # pre-existing token, NULL mac

    info = auth.validate_sso_token(token)
    assert info is not None and info["username"] == "alice"


def test_validate_returns_none_when_no_row(monkeypatch):
    fake = _wire(monkeypatch)
    fake.query_result = None
    assert auth.validate_sso_token("missing") is None


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
