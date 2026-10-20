#!/usr/bin/env python3
"""Property-based tests for Proxy_Manager failure handling without partial writes.

Feature: nginx-to-traefik-migration

Property 8: Failed route operations return a failure indicator without partial
writes. *For any* Proxy_Manager operation whose underlying route write or delete
fails, the function returns ``False`` and leaves no partially written route file.

Validates: Requirements 8.6

These tests inject write/delete failures into ``src/nginx_manager.py`` and assert
that:
  * ``insert_location_block`` returns ``False`` on a write failure and leaves no
    ``app-{user}-{app}.yml`` target file and no leftover ``*.tmp`` artifact; and
  * ``remove_location_block`` returns ``False`` on a non-``FileNotFoundError``
    delete error and leaves no partial/temp artifact behind.

Run directly:
    python3 tests/test_traefik_failure_handling.py
Or via pytest:
    pytest tests/test_traefik_failure_handling.py
"""
import glob
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from hypothesis import given, settings, strategies as st

from src import nginx_manager


# ---------------------------------------------------------------------------
# Generation strategies
# ---------------------------------------------------------------------------
# User/app names are DNS-label-style identifiers (lowercase alphanumerics and
# hyphens), matching the platform's identifier space so the derived file name
# ``app-{user}-{app}.yml`` is well-formed.
_DNS_LABEL = st.from_regex(r"[a-z0-9][a-z0-9-]{0,20}", fullmatch=True)
_DOMAIN = st.lists(_DNS_LABEL, min_size=1, max_size=3).map(".".join)

# A URL carrying a host and an HTTPS-style port so ``insert_location_block``
# derives a backend host/port and reaches the write step.
_URL = st.builds(
    lambda host, port: f"https://{host}:{port}",
    _DNS_LABEL,
    st.integers(min_value=2, max_value=65535),
)

# How the write is forced to fail. Each mode breaks ``_write_route_file`` at a
# different stage so both the "fail before any temp file" path and the "fail
# after the temp file exists" (cleanup) path are exercised.
#   yaml      -> yaml.safe_dump raises (before mkstemp: no temp file created)
#   makedirs  -> os.makedirs raises (target dir whose parent is a regular file)
#   replace   -> os.replace raises (temp file exists; must be cleaned up)
_WRITE_FAIL_MODE = st.sampled_from(["yaml", "makedirs", "replace"])


def _dir_is_clean(directory, user_name, app_name):
    """Return True iff no target route file and no leftover temp artifact exist."""
    target = os.path.join(directory, f"app-{user_name}-{app_name}.yml")
    leftover_tmp = glob.glob(os.path.join(directory, "*.tmp"))
    # Hidden temp files are created with prefix ".{basename}." and suffix
    # ".tmp"; glob("*.tmp") skips dotfiles, so also match them explicitly.
    leftover_tmp += glob.glob(os.path.join(directory, ".*.tmp"))
    return (not os.path.exists(target)) and (len(leftover_tmp) == 0)


# ---------------------------------------------------------------------------
# Property 8 (insert): a write failure yields False and no partial write.
# Feature: nginx-to-traefik-migration, Property 8
# Validates: Requirements 8.6
# ---------------------------------------------------------------------------
@settings(max_examples=120)
@given(
    user_name=_DNS_LABEL,
    app_name=_DNS_LABEL,
    url=_URL,
    domain=_DOMAIN,
    fail_mode=_WRITE_FAIL_MODE,
    monkeypatch_seed=st.integers(),  # keeps examples distinct; value unused
)
def test_property_8_insert_write_failure_no_partial_write(
    tmp_path_factory, user_name, app_name, url, domain, fail_mode,
    monkeypatch_seed,
):
    """Feature: nginx-to-traefik-migration, Property 8.

    When the underlying route write fails, ``insert_location_block`` returns
    ``False`` and leaves the dynamic directory with no ``app-{user}-{app}.yml``
    target file and no leftover ``*.tmp`` artifact. Validates Requirements 8.6.
    """
    base = tmp_path_factory.mktemp("traefik_dyn")

    # Save originals so we can restore after each example (hypothesis re-runs
    # this function many times in the same process; a MonkeyPatch fixture is
    # not available inside @given, so patch/restore manually in finally).
    orig_dir = nginx_manager.TRAEFIK_DYNAMIC_DIR
    orig_safe_dump = nginx_manager.yaml.safe_dump
    orig_makedirs = nginx_manager.os.makedirs
    orig_replace = nginx_manager.os.replace

    if fail_mode == "makedirs":
        # Point the dynamic dir at a path whose parent is a regular file so
        # os.makedirs fails; nothing is ever created in a real directory.
        parent_file = base / "not-a-dir"
        parent_file.write_text("x")
        dynamic_dir = str(parent_file / "dynamic")
    else:
        dynamic_dir = str(base / "dynamic")
        os.makedirs(dynamic_dir, exist_ok=True)

    nginx_manager.TRAEFIK_DYNAMIC_DIR = dynamic_dir

    def _boom(*args, **kwargs):
        raise OSError("injected write failure")

    try:
        if fail_mode == "yaml":
            nginx_manager.yaml.safe_dump = _boom
        elif fail_mode == "replace":
            nginx_manager.os.replace = _boom
        # makedirs mode needs no monkeypatch; the bad path makes it fail.

        result = nginx_manager.insert_location_block(
            user_name, app_name, url, url
        )

        assert result is False, (
            f"insert_location_block must return False on {fail_mode} failure"
        )

        # For makedirs mode the directory may not exist at all, which is
        # trivially clean. Otherwise it exists and must be free of artifacts.
        if os.path.isdir(dynamic_dir):
            assert _dir_is_clean(dynamic_dir, user_name, app_name), (
                f"partial write left behind after {fail_mode} failure: "
                f"{os.listdir(dynamic_dir)}"
            )
    finally:
        nginx_manager.TRAEFIK_DYNAMIC_DIR = orig_dir
        nginx_manager.yaml.safe_dump = orig_safe_dump
        nginx_manager.os.makedirs = orig_makedirs
        nginx_manager.os.replace = orig_replace


# ---------------------------------------------------------------------------
# Property 8 (remove): a delete error yields False and no partial artifact.
# Feature: nginx-to-traefik-migration, Property 8
# Validates: Requirements 8.6
# ---------------------------------------------------------------------------
@settings(max_examples=120)
@given(
    user_name=_DNS_LABEL,
    app_name=_DNS_LABEL,
    file_exists=st.booleans(),
    monkeypatch_seed=st.integers(),  # keeps examples distinct; value unused
)
def test_property_8_remove_delete_failure_returns_false(
    tmp_path_factory, user_name, app_name, file_exists, monkeypatch_seed,
):
    """Feature: nginx-to-traefik-migration, Property 8.

    When the underlying delete raises a non-``FileNotFoundError`` ``OSError``,
    ``remove_location_block`` returns ``False`` and leaves no partial/temp
    artifact in the dynamic directory. Validates Requirements 8.6.
    """
    base = tmp_path_factory.mktemp("traefik_dyn_rm")
    dynamic_dir = str(base / "dynamic")
    os.makedirs(dynamic_dir, exist_ok=True)

    orig_dir = nginx_manager.TRAEFIK_DYNAMIC_DIR
    orig_remove = nginx_manager.os.remove
    nginx_manager.TRAEFIK_DYNAMIC_DIR = dynamic_dir

    target = os.path.join(dynamic_dir, f"app-{user_name}-{app_name}.yml")
    if file_exists:
        # Seed an existing route file so the delete actually attempts removal.
        with open(target, "w") as f:
            f.write("http: {}\n")

    def _boom(*args, **kwargs):
        raise OSError("injected delete failure")

    try:
        nginx_manager.os.remove = _boom

        result = nginx_manager.remove_location_block(user_name, app_name)

        assert result is False, (
            "remove_location_block must return False when delete raises OSError"
        )

        # No new partial/temp artifacts may have appeared. (A pre-seeded target
        # may remain since the delete was blocked; that is not a *partial* write.)
        leftover_tmp = glob.glob(os.path.join(dynamic_dir, "*.tmp"))
        leftover_tmp += glob.glob(os.path.join(dynamic_dir, ".*.tmp"))
        assert len(leftover_tmp) == 0, (
            f"delete failure left temp artifacts behind: {leftover_tmp}"
        )
    finally:
        nginx_manager.TRAEFIK_DYNAMIC_DIR = orig_dir
        nginx_manager.os.remove = orig_remove


if __name__ == "__main__":
    test_property_8_insert_write_failure_no_partial_write()
    print("Property 8 (insert write failure, no partial write): OK")
    test_property_8_remove_delete_failure_returns_false()
    print("Property 8 (remove delete failure returns False): OK")
