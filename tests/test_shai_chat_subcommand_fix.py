"""Bug condition exploration test for the shai `chat` subcommand defect.

Spec: .kiro/specs/shai-chat-subcommand-fix

Property 1 (Bug Condition): shai invoked with its supported headless form.

This test drives BOTH agentic invocation sites in ``src/routes/genai_routes.py``
(the developer / MODIFY_CODE path and the virtual operator START/STOP path) with
``agentic_engine = "shai"`` and no ``agentic_command``. It intercepts
``subprocess.Popen`` to capture the command the branch builds and asserts that it
is the supported headless form ``[engine_cmd, '-p', l_prompt]`` -- NOT the obsolete
``['shai', 'chat', '--trust-all-tools', <prompt>]`` form.

CRITICAL (bugfix exploration test): on UNFIXED code this test is EXPECTED TO FAIL.
The failure confirms the bug exists. Once the fix is applied the same test passes.

Validates: Requirements 1.1, 1.2, 1.3, 2.1, 2.2, 2.3
"""

import json
from unittest import mock

import pytest
from flask import Flask
from hypothesis import given, settings, strategies as st

from src.routes import genai_routes


def _make_app():
    """Build a minimal Flask app hosting only the genai blueprint.

    We avoid ``create_app`` so the test does not drag in the full application
    stack (flask_cors and every other blueprint); the command-building code
    under test lives entirely in ``genai_routes``.
    """
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.config["TESTING"] = True
    return app


# A known, resolved shai path so we can assert the branch uses the resolved
# ``engine_cmd`` and not the bare literal ``"shai"``.
RESOLVED_SHAI_PATH = "/home/tester/.local/bin/shai"


class _FakeProcess:
    """Minimal stand-in for ``subprocess.Popen`` that yields a few lines and
    then exits with a configurable (non-zero) return code."""

    def __init__(self, returncode=1, lines=None):
        self.returncode = returncode
        self.pid = 4242
        self._lines = list(lines or ["shai output line 1\n", "shai output line 2\n"])
        self.stdout = self

    # stdout.readline() protocol used by ``iter(process.stdout.readline, '')``
    def readline(self):
        if self._lines:
            return self._lines.pop(0)
        return ""

    def wait(self, timeout=None):
        return self.returncode

    def poll(self):
        return self.returncode


def _fake_execute_query(query, params=None, fetch_one=False, **kwargs):
    """Canned DB responses so the route handlers never touch a real database.

    - configuration lookups -> None (fall through to request-supplied values)
    - users lookup -> a fake user tuple
    - everything else -> None
    """
    q = " ".join(query.split())
    if "FROM users" in q:
        return ("tester", "tester@example.com", "Test", "User")
    # configuration table / deployments / anything else
    return None


def _collect_popen_calls():
    """Return (recorder_list, popen_side_effect) capturing every Popen cmd."""
    recorded = []

    def _popen(cmd_args, *args, **kwargs):
        recorded.append(list(cmd_args))
        return _FakeProcess(returncode=1)

    return recorded, _popen


def _drive_route(route_func, json_body):
    """Invoke a streaming route handler and return (events, popen_cmds).

    The handler is called inside a real Flask request+session context with
    the database, shai-path resolution and ``subprocess.Popen`` all patched so
    the command-building branch runs deterministically without external deps.
    """
    app = _make_app()

    recorded_cmds, popen_side_effect = _collect_popen_calls()

    events = []

    with app.test_request_context(json=json_body):
        # Authenticated session.
        from flask import session as flask_session
        flask_session["user_id"] = 1

        with mock.patch.object(genai_routes.db_manager, "execute_query",
                               side_effect=_fake_execute_query), \
             mock.patch("src.config_postgres.get_shai_paths",
                        return_value=RESOLVED_SHAI_PATH), \
             mock.patch("subprocess.Popen", side_effect=popen_side_effect), \
             mock.patch("os.setsid", create=True, return_value=0), \
             mock.patch("os.getpgid", create=True, return_value=4242), \
             mock.patch("os.killpg", create=True, return_value=None), \
             mock.patch.object(genai_routes, "return_prompt_for_operator",
                               return_value=("EXECUTE THE START ACTION NOW", True)):
            response = route_func()

            # The handler returns either a streaming Response (happy path) or a
            # (json, status) tuple for early validation errors.
            if isinstance(response, tuple):
                raise AssertionError(f"route returned early error: {response}")

            chunks = []
            for chunk in response.response:
                if isinstance(chunk, bytes):
                    chunk = chunk.decode("utf-8")
                chunks.append(chunk)
            body = "".join(chunks)

    for block in body.split("\n\n"):
        block = block.strip()
        if block.startswith("data: "):
            try:
                events.append(json.loads(block[len("data: "):]))
            except json.JSONDecodeError:
                pass

    return events, recorded_cmds


def _done_event(events):
    for ev in events:
        if ev.get("done"):
            return ev
    return None


# ---------------------------------------------------------------------------
# Property 1 - Bug Condition (scoped PBT over the prompt domain)
# ---------------------------------------------------------------------------

# Generate assorted prompts to cover the prompt domain. The developer prompt is
# built internally from the message, so we vary the ``message`` that feeds it.
_messages = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters="\x00"),
    min_size=1,
    max_size=40,
)


def _assert_shai_headless(cmd_args):
    """Property 1 assertions on a single built shai command."""
    # The supported headless form uses -p, not the chat subcommand.
    assert "chat" not in cmd_args, (
        f"obsolete 'chat' subcommand present in shai command: {cmd_args}")
    assert "--trust-all-tools" not in cmd_args, (
        f"unsupported '--trust-all-tools' flag present in shai command: {cmd_args}")
    # cmd_args[0] must be the resolved engine_cmd path, not the bare name.
    assert cmd_args[0] == RESOLVED_SHAI_PATH, (
        f"shai command uses bare name instead of resolved engine_cmd: {cmd_args}")
    # Exact supported shape: [engine_cmd, '-p', l_prompt].
    assert cmd_args[:2] == [RESOLVED_SHAI_PATH, "-p"], (
        f"shai command is not the headless form [engine_cmd, '-p', prompt]: {cmd_args}")
    assert len(cmd_args) == 3, (
        f"shai command should be exactly [engine_cmd, '-p', prompt]: {cmd_args}")


@settings(max_examples=25, deadline=None)
@given(message=_messages)
def test_developer_shai_uses_supported_headless_form(message):
    """Developer / MODIFY_CODE path builds [engine_cmd, '-p', prompt] for shai.

    Validates: Requirements 1.1, 1.3, 2.1, 2.3
    """
    body = {
        "message": message,
        "application_name": "",
        "application_folder": "",
        "action_operation": "MODIFY_CODE",
        "agentic_engine": "shai",
        # no agentic_command -> bug-condition branch
    }
    events, cmds = _drive_route(genai_routes.api_request_dev_ai_for_app, body)

    assert cmds, "developer path never invoked subprocess.Popen"
    _assert_shai_headless(cmds[0])


@settings(max_examples=25, deadline=None)
@given(message=_messages)
def test_operator_shai_uses_supported_headless_form(message):
    """Virtual operator START/STOP path builds [engine_cmd, '-p', prompt] for shai.

    Validates: Requirements 1.1, 1.3, 2.1, 2.3
    """
    body = {
        "message": message,
        "application_name": "myapp",
        "application_folder": "/tmp/myapp",
        "action_operation": "START",
        "agentic_engine": "shai",
        # no agentic_command -> bug-condition branch
    }
    events, cmds = _drive_route(genai_routes.api_request_ops_ai_for_app, body)

    assert cmds, "operator path never invoked subprocess.Popen"
    _assert_shai_headless(cmds[0])


def test_operator_shai_nonzero_exit_reports_failure():
    """Edge case: a stubbed shai process exiting non-zero must surface failure.

    The emitted ``done`` event must report ``success == false`` and the
    non-zero ``returncode``.

    Validates: Requirements 1.2, 2.2
    """
    body = {
        "message": "start my app",
        "application_name": "myapp",
        "application_folder": "/tmp/myapp",
        "action_operation": "START",
        "agentic_engine": "shai",
    }
    events, cmds = _drive_route(genai_routes.api_request_ops_ai_for_app, body)

    done = _done_event(events)
    assert done is not None, f"no done event emitted; events={events}"
    assert done.get("success") is False, (
        f"non-zero exit should report success=false, got {done}")
    assert done.get("returncode") not in (0, None), (
        f"non-zero return code should be surfaced, got {done}")
