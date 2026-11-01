#!/usr/bin/env python3
"""Property test for registry pinning/integrity rejection (Phase 2 ARO, Task 8.3).

Feature: phase2-aro-completion, Property 22.

Exercises Property 22 ("Registry preserves pinned-version and integrity
rejection") over ``validate_definition`` in
``src/aro/runtime_registry_service.py``. Task 8.1 wired a protocol->adapter
factory into this module while leaving ``validate_definition``, ``_is_pinned``,
and ``_validate_install_method`` unchanged; this property pins that the
security contract still holds:

* AC 5.3 — a definition whose version is unpinned (``latest`` / ``*`` / ``head``
  / ``main`` / ``master`` / empty, case-insensitively) is rejected with
  ``RuntimeValidationError``.
* AC 5.4 — a definition whose ``install_method`` carries no integrity material
  (neither a truthy ``sha256`` nor a truthy ``digest``) is rejected with
  ``RuntimeValidationError``.
* A well-formed definition — pinned version plus an allowed install kind bearing
  integrity material — validates successfully and round-trips its identity.

Validates: Requirements 5.3, 5.4

Run directly:
    python3 tests/test_aro_registry_pinning_integrity.py
Or via pytest:
    pytest tests/test_aro_registry_pinning_integrity.py -v
"""
import os
import sys

from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.aro import runtime_registry_service as svc  # noqa: E402

# The tokens ``_is_pinned`` rejects (compared case-insensitively after strip).
UNPINNED_TOKENS = ("latest", "*", "head", "main", "master", "")
# Install kinds the registry accepts (ALLOWED_INSTALL_KINDS); anything else is
# rejected as an "arbitrary install script".
ALLOWED_KINDS = sorted(svc.ALLOWED_INSTALL_KINDS)
# A protocol the registry recognizes, used to keep every generated definition
# valid in every dimension except the one under test.
SUPPORTED = sorted(svc.SUPPORTED_PROTOCOLS)


# --------------------------------------------------------------------------- #
# Generators
# --------------------------------------------------------------------------- #
# Non-empty identifier/name after strip. Keep the alphabet simple so the only
# variable under test is the pinning / integrity dimension.
_idents = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789-_", min_size=1, max_size=24
).filter(lambda s: s.strip() != "")
# Pinned versions: anything non-empty after strip that is not an unpinned token.
_pinned_versions = st.text(
    alphabet="0123456789.v-abcdef", min_size=1, max_size=16
).map(lambda s: s.strip()).filter(
    lambda v: v != "" and v.lower() not in UNPINNED_TOKENS
)
# Integrity material: a non-empty hex-ish string (truthy sha256/digest value).
_integrity = st.text(
    alphabet="0123456789abcdef", min_size=1, max_size=64
).filter(lambda s: s != "")


def _base_valid(ident, name, version, protocol, kind, integrity_key, integrity_val):
    """A fully valid definition parameterized on each dimension."""
    return {
        "identifier": ident,
        "name": name,
        "version": version,
        "supported_protocols": [protocol],
        "install_method": {"kind": kind, integrity_key: integrity_val},
    }


# --------------------------------------------------------------------------- #
# AC 5.3 — unpinned version is rejected
# --------------------------------------------------------------------------- #
@settings(max_examples=200, deadline=None)
@given(
    ident=_idents,
    name=_idents,
    # The unpinned token, optionally surrounded by whitespace and recased, since
    # ``_is_pinned`` strips and lowercases before comparing.
    token=st.sampled_from(UNPINNED_TOKENS),
    pad_left=st.sampled_from(["", " ", "  ", "\t"]),
    pad_right=st.sampled_from(["", " ", "  ", "\t"]),
    upper=st.booleans(),
    protocol=st.sampled_from(SUPPORTED),
    kind=st.sampled_from(ALLOWED_KINDS),
    integrity=_integrity,
)
def test_unpinned_version_rejected(
    ident, name, token, pad_left, pad_right, upper, protocol, kind, integrity
):
    """AC 5.3: any definition whose version is an unpinned token — regardless of
    surrounding whitespace or letter case — is rejected with
    ``RuntimeValidationError``, even when every other field is well-formed.

    Feature: phase2-aro-completion, Property 22.
    Validates: Requirements 5.3
    """
    version = pad_left + (token.upper() if upper else token) + pad_right
    payload = _base_valid(ident, name, version, protocol, kind, "sha256", integrity)
    try:
        svc.validate_definition(payload)
        assert False, f"expected rejection for unpinned version {version!r}"
    except svc.RuntimeValidationError:
        pass


# --------------------------------------------------------------------------- #
# AC 5.4 — install method lacking integrity material is rejected
# --------------------------------------------------------------------------- #
@settings(max_examples=200, deadline=None)
@given(
    ident=_idents,
    name=_idents,
    version=_pinned_versions,
    protocol=st.sampled_from(SUPPORTED),
    kind=st.sampled_from(ALLOWED_KINDS),
    # Falsy / absent integrity values: missing key, empty string, or explicit
    # None — none of these count as integrity material.
    sha_val=st.sampled_from([None, ""]),
    digest_val=st.sampled_from([None, ""]),
)
def test_install_without_integrity_rejected(
    ident, name, version, protocol, kind, sha_val, digest_val
):
    """AC 5.4: a pinned definition whose ``install_method`` carries no truthy
    ``sha256`` or ``digest`` is rejected with ``RuntimeValidationError``.

    Feature: phase2-aro-completion, Property 22.
    Validates: Requirements 5.4
    """
    install_method = {"kind": kind}
    if sha_val is not None:
        install_method["sha256"] = sha_val
    if digest_val is not None:
        install_method["digest"] = digest_val
    payload = {
        "identifier": ident,
        "name": name,
        "version": version,
        "supported_protocols": [protocol],
        "install_method": install_method,
    }
    try:
        svc.validate_definition(payload)
        assert False, "expected rejection for install_method lacking integrity"
    except svc.RuntimeValidationError:
        pass


# --------------------------------------------------------------------------- #
# Positive: well-formed pinned + integrity-bearing definition validates
# --------------------------------------------------------------------------- #
@settings(max_examples=200, deadline=None)
@given(
    ident=_idents,
    name=_idents,
    version=_pinned_versions,
    protocol=st.sampled_from(SUPPORTED),
    kind=st.sampled_from(ALLOWED_KINDS),
    # Exercise both integrity keys the validator accepts.
    integrity_key=st.sampled_from(["sha256", "digest"]),
    integrity=_integrity,
)
def test_wellformed_definition_validates(
    ident, name, version, protocol, kind, integrity_key, integrity
):
    """A pinned version with an allowed install kind carrying integrity material
    validates successfully and normalizes with its identity preserved.

    Feature: phase2-aro-completion, Property 22.
    Validates: Requirements 5.3, 5.4
    """
    payload = _base_valid(
        ident, name, version, protocol, kind, integrity_key, integrity
    )
    normalized = svc.validate_definition(payload)
    assert normalized["identifier"] == ident.strip()
    assert normalized["name"] == name.strip()
    assert normalized["version"] == version.strip()
    assert protocol in normalized["supported_protocols"]
    assert normalized["install_method"][integrity_key] == integrity


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([os.path.abspath(__file__), "-v"]))
