#!/usr/bin/env python3
"""Property test for the deduped ``/logs`` handler response equivalence.

Feature: phase1-foundation-consolidation, Property 3 -- "``/logs`` handler
response equivalence across the input space".

Spec: .kiro/specs/phase1-foundation-consolidation (task 4.3)

Context
-------
Phase 1 de-duplicated the shadowed ``GET /api/deployments/<int:deployment_id>/logs``
route: the ``genai_routes`` copy was removed and the ``api_routes`` definition
(``api.api_deployment_logs``) is retained as the single handler. The retained
handler validates deployment paths with
``is_under_deployments(LINUX_USER_INSTALLATION, path)``; the removed genai copy
used the hardcoded-prefix predicate. The two were proven behaviorally
equivalent (Property 2), so the retained handler must return the SAME status
code and JSON key shape as the pre-change effective (genai) handler for every
input.

This test drives the REAL deduped route through a Flask test client. A minimal
app registers the real ``api_bp`` blueprint (``url_prefix='/api'``), so the
client exercises the actual ``api.api_deployment_logs`` route and its real body.
The database (``db_manager.execute_query``), filesystem (``os.path.exists`` /
``open``) and the session are the only things mocked, so the handler is driven
over the full input space without a real DB/FS.

Over the input space (auth state x ownership x path validity x file presence,
plus a read-error dimension), a reference ORACLE encodes the documented
contract:

- No 'user_id' in session               -> 401 {'error'}
- Deployment not found for the user      -> 404 {'error'}
- deploy_path fails is_under_deployments  -> 400 {'error'}
- log_file path fails is_under_deployments-> 400 {'error'}  (co-occurs with the above)
- file present, read ok                   -> 200 {'logs'}
- file present, exception during read      -> 500 {'error'}
- file absent (never read)                 -> 200 {'logs': 'No logs available'}

The test asserts the real response's status code and the SET of top-level JSON
keys match the oracle (key SHAPE, not message text).

Validates: Requirements 4.5, 6.3
"""
import os
import sys
from unittest import mock

from flask import Flask
from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src.routes import api_routes  # noqa: E402
from src.routes.api_routes import api_bp  # noqa: E402
from src.config_postgres import (  # noqa: E402
    LINUX_USER_INSTALLATION,
    deployments_prefix,
)

_VALID_USER = LINUX_USER_INSTALLATION

# DNS-label-safe path segments, matching the platform user/app naming rules.
_segments = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-", min_size=1, max_size=20)


def _valid_deploy_path(user_seg, app_seg):
    """A path ACCEPTED by is_under_deployments(LINUX_USER_INSTALLATION, p):
    starts with the deployments prefix and has no '..' traversal component."""
    return f"{deployments_prefix(_VALID_USER)}{user_seg}/{app_seg}"


# Paths REJECTED by is_under_deployments: either outside the prefix entirely or
# containing a '..' traversal component. Both must yield the same 400 verdict.
_invalid_deploy_paths = st.one_of(
    st.sampled_from(["/etc/passwd", "/tmp/evil", "", "relative/path"]),
    st.builds(lambda s: f"{deployments_prefix(_VALID_USER)}../{s}", _segments),
)


def _make_app():
    """Build a minimal Flask app hosting ONLY the real api blueprint.

    Registering the real ``api_bp`` (url_prefix='/api') wires the actual
    ``api.api_deployment_logs`` route at ``/api/deployments/<int:id>/logs`` --
    i.e. the deduped handler under test -- without dragging in the full
    create_app() stack (flask_cors + every other blueprint). The handler body
    is the real retained code; nothing about it is reimplemented here.
    """
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.config["TESTING"] = True
    app.register_blueprint(api_bp)
    return app


def _expected(authed, owns_deployment, path_valid, file_present, read_error):
    """Reference oracle: (status_code, frozenset_of_top_level_json_keys).

    Encodes the documented contract of api.api_deployment_logs. Pure function of
    the five input dimensions; it never touches Flask or the real handler.
    """
    # 1. Authentication gate.
    if not authed:
        return 401, frozenset({"error"})
    # 2. User-scoped deployment lookup.
    if not owns_deployment:
        return 404, frozenset({"error"})
    # 3. Path-traversal validation (deploy_path, then log_file -- same verdict).
    if not path_valid:
        return 400, frozenset({"error"})
    # 4. Read behavior. The handler only opens the file when it exists, so a
    #    read error can only arise when the file is present; an absent file
    #    short-circuits to the 'No logs available' 200 response and never reads.
    if file_present and read_error:
        return 500, frozenset({"error"})
    # file present -> {'logs': <content>}; absent -> {'logs': 'No logs available'}
    return 200, frozenset({"logs"})


# The four contract dimensions are booleans; the generated deployment_id and
# path segments / invalid-path choices widen the input space so the property
# runs the required >=100 iterations rather than exhausting a 32-value space.
@settings(max_examples=200, deadline=None)
@given(
    authed=st.booleans(),
    owns_deployment=st.booleans(),
    path_valid=st.booleans(),
    file_present=st.booleans(),
    read_error=st.booleans(),
    deployment_id=st.integers(min_value=1, max_value=10_000),
    user_seg=_segments,
    app_seg=_segments,
    invalid_path=_invalid_deploy_paths,
)
def test_logs_handler_response_equivalence(
    authed, owns_deployment, path_valid, file_present, read_error,
    deployment_id, user_seg, app_seg, invalid_path,
):
    """Feature: phase1-foundation-consolidation, Property 3.

    Validates: Requirements 4.5, 6.3

    Drive the real deduped ``/logs`` handler across (auth x ownership x path
    validity x file presence x read-error) and assert the status code and the
    SET of top-level JSON keys match the reference oracle encoding the contract.
    """
    exp_status, exp_keys = _expected(
        authed, owns_deployment, path_valid, file_present, read_error
    )

    # --- DB mock: user-scoped deployment lookup returns a row or None. ---
    # The handler calls db_manager.execute_query(..., fetch_one=True) and reads
    # deployment[0] as the deploy_path. Returning None models "not found".
    deploy_path = (
        _valid_deploy_path(user_seg, app_seg) if path_valid else invalid_path
    )
    db_row = (deploy_path,) if owns_deployment else None

    def _fake_execute_query(query, params=None, fetch_one=False, **kwargs):
        return db_row

    # --- FS mocks: os.path.exists / open gate the read behavior. ---
    def _fake_exists(path):
        return file_present

    def _fake_open(*args, **kwargs):
        if read_error:
            raise IOError("boom")
        return mock.mock_open(read_data="log line 1\nlog line 2\n")(*args, **kwargs)

    app = _make_app()
    client = app.test_client()

    if authed:
        with client.session_transaction() as sess:
            sess["user_id"] = 1

    with mock.patch.object(
        api_routes.db_manager, "execute_query", side_effect=_fake_execute_query
    ), mock.patch.object(api_routes.os.path, "exists", side_effect=_fake_exists), \
            mock.patch.object(api_routes, "open", _fake_open, create=True):
        resp = client.get(f"/api/deployments/{deployment_id}/logs")

    # Status code equivalence.
    assert resp.status_code == exp_status, (
        f"status mismatch for (authed={authed}, owns={owns_deployment}, "
        f"path_valid={path_valid}, file_present={file_present}, "
        f"read_error={read_error}): got {resp.status_code}, expected {exp_status}"
    )

    # JSON key SHAPE equivalence (compare the SET of top-level keys, not text).
    body = resp.get_json(silent=True)
    assert isinstance(body, dict), f"expected a JSON object body, got {body!r}"
    assert frozenset(body.keys()) == exp_keys, (
        f"json key shape mismatch for (authed={authed}, owns={owns_deployment}, "
        f"path_valid={path_valid}, file_present={file_present}, "
        f"read_error={read_error}): got {set(body.keys())}, expected {set(exp_keys)}"
    )
