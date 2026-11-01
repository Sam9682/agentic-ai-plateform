#!/usr/bin/env python3
"""Unit tests for ``src.gitea_auth.redact_credential_url``.

Feature: phase3-zaf-enforcement (task 2.3)
Validates: Requirements 3.6

The redaction-on-read helper masks any ``userinfo`` component of a URL
(``scheme://user:pass@host/...`` -> ``scheme://***@host/...``) while leaving
the remaining URL structure intact. Values without a credential are returned
unchanged.
"""
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src.gitea_auth import redact_credential_url  # noqa: E402


def test_masks_user_and_password():
    assert (
        redact_credential_url(
            "http://gitadmin:password@localhost:3000/gitadmin/branch"
        )
        == "http://***@localhost:3000/gitadmin/branch"
    )


def test_masks_user_only():
    assert redact_credential_url("scheme://user@host/x") == "scheme://***@host/x"


def test_preserves_port_path_query_fragment():
    assert (
        redact_credential_url("https://user:p%40ss@host:8443/path?q=1#frag")
        == "https://***@host:8443/path?q=1#frag"
    )


def test_url_without_userinfo_is_unchanged():
    url = "http://localhost:3000/gitadmin/branch"
    assert redact_credential_url(url) == url


def test_https_host_only_unchanged():
    url = "https://host/path"
    assert redact_credential_url(url) == url


def test_non_url_inputs_unchanged():
    assert redact_credential_url("") == ""
    assert redact_credential_url(None) is None
    assert redact_credential_url("not a url") == "not a url"
    assert redact_credential_url("/relative/path") == "/relative/path"


def test_is_pure_no_mutation():
    original = "http://u:p@host/x"
    before = original
    redact_credential_url(original)
    assert original == before
