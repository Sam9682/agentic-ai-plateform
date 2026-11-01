#!/usr/bin/env python3
"""Unit tests for the credential-free Gitea auth helpers.

Feature: phase3-zaf-enforcement (task 2.5)
Validates: Requirements 3.1, 3.2

``gitea_clone_url`` builds a clean ``http://<host>/<path>`` URL with no embedded
``user:pass@`` authority. ``gitea_credentials`` sources the Gitea credential
from the environment/secret store and returns it inside a ``SecretWrapper``,
failing closed with ``GiteaAuthError`` when nothing is configured — never a
static literal.
"""
import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("ZAF_SECRET_KEY", "unit-test-secret-key")

from src.gitea_auth import (  # noqa: E402
    GiteaAuthError,
    gitea_clone_url,
    gitea_credentials,
)
from src.zaf.credential_vault import SecretWrapper  # noqa: E402


# --------------------------------------------------------------------------- #
# gitea_clone_url
# --------------------------------------------------------------------------- #

def test_builds_clean_url():
    assert (
        gitea_clone_url("localhost:3000", "gitadmin/my-branch")
        == "http://localhost:3000/gitadmin/my-branch"
    )


def test_no_embedded_credentials_in_output():
    url = gitea_clone_url("localhost:3000", "gitadmin/branch")
    assert "@" not in url
    assert ":password@" not in url


def test_leading_slash_on_path_is_normalized():
    assert (
        gitea_clone_url("host:3000", "/gitadmin/branch")
        == "http://host:3000/gitadmin/branch"
    )


def test_strips_scheme_from_host():
    assert (
        gitea_clone_url("http://host:3000", "gitadmin/x")
        == "http://host:3000/gitadmin/x"
    )


def test_strips_embedded_userinfo_from_host():
    # Even if a caller accidentally passes a credential-bearing authority, the
    # result must never carry it.
    url = gitea_clone_url("user:pass@host:3000", "gitadmin/x")
    assert url == "http://host:3000/gitadmin/x"
    assert "user" not in url
    assert "pass" not in url
    assert "@" not in url


def test_handles_empty_path():
    assert gitea_clone_url("host", "") == "http://host/"


# --------------------------------------------------------------------------- #
# gitea_credentials
# --------------------------------------------------------------------------- #

def test_returns_secret_wrapper_from_env(monkeypatch):
    monkeypatch.setenv("GITEA_TOKEN", "s3cr3t-token")
    cred = gitea_credentials()
    assert isinstance(cred, SecretWrapper)
    assert cred.reveal() == "s3cr3t-token"


def test_credential_does_not_leak_in_repr(monkeypatch):
    monkeypatch.setenv("GITEA_TOKEN", "s3cr3t-token")
    cred = gitea_credentials()
    assert "s3cr3t-token" not in repr(cred)
    assert "s3cr3t-token" not in str(cred)


def test_fails_closed_when_no_credential(monkeypatch):
    monkeypatch.delenv("GITEA_TOKEN", raising=False)
    with pytest.raises(GiteaAuthError):
        gitea_credentials()


def test_fails_closed_on_empty_credential(monkeypatch):
    # An empty value is not a usable credential; fail closed rather than
    # returning a wrapper around an empty string.
    monkeypatch.setenv("GITEA_TOKEN", "")
    with pytest.raises(GiteaAuthError):
        gitea_credentials()


def test_never_returns_static_literal(monkeypatch):
    # With no credential configured the function raises; it must not silently
    # return a default/placeholder value.
    monkeypatch.delenv("GITEA_TOKEN", raising=False)
    try:
        result = gitea_credentials()
    except GiteaAuthError:
        return
    pytest.fail(f"expected GiteaAuthError, got a value: {result!r}")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
