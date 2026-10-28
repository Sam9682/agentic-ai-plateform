"""Preservation property tests for the shai `chat` subcommand fix.

Spec: .kiro/specs/shai-chat-subcommand-fix

Property 2 (Preservation): Non-shai paths and success reporting unchanged.

These tests capture the BASELINE behavior that the shai fix must NOT change.
Following the observation-first methodology, they encode the outputs that were
observed by running the UNFIXED code for inputs where the bug condition does NOT
hold (``isBugCondition`` returns false):

- A non-shai engine (e.g. ``agentic_engine = "qchat"``) builds
  ``[engine_cmd, 'chat', '--trust-all-tools', l_prompt]``.
- A session with a non-empty ``agentic_command`` builds
  ``[deployControlPlan.sh, agentic_command]``.
- A clean (zero) exit reports ``success: true`` at both invocation sites.
- An unresolved shai path (``get_shai_paths()`` returns falsy) yields the
  "not found for SHAI" error with no process started.

On UNFIXED code these tests are EXPECTED TO PASS -- they confirm the baseline
behavior to preserve. After the fix they must still pass (no regressions).

Validates: Requirements 3.1, 3.2, 3.3, 3.4
"""

import json
from unittest import mock

import pytest
from flask import Flask
from hypothesis import given, settings, strategies as st

from src.routes import genai_routes


def _make_app():
    """Minimal Flask app hosting only the genai blueprint (see task 1 harness)."""
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.config["TESTING"] = True
    return app


# Known, resolved engine paths so we can assert the branch uses the resolved
# ``engine_cmd`` rather than a bare literal.
RESOLVED_QCHAT_PATH = "/home/tester/.local/bin/qchat"
RESOLVED_SHAI_PATH = "/home/tester/.local/bin/shai"

class _FakeProcess:
    """Stand-in for ``subprocess.Popen`` yielding a few lines then exiting with
    a configurable return code (defaults to a clean zero exit)."""

    def __init__(self, returncode=0, lines=None):
        self.returncode = returncode
        self.pid = 4242
        self._lines = list(lines or ["engine output line 1\n", "engine output line 2\n"])
        self.stdout = self

    def readline(self):
        if self._lines:
            return self._lines.pop(0)
        return ""

    def wait(self, timeout=None):
        return self.returncode

    def poll(self):
        return self.returncode


def _fake_execute_query(query, params=None, fetch_one=False, **kwargs):
    """Canned DB responses so handlers never touch a real database."""
    q = " ".join(query.split())
    if "FROM users" in q:
        return ("tester", "tester@example.com", "Test", "User")
    return None


def _drive_route(route_func, json_body, *, returncode=0,
                 shai_path=RESOLVED_SHAI_PATH, qchat_path=RESOLVED_QCHAT_PATH):
    """Invoke a streaming route handler and return (events, popen_cmds).

    Patches the database, both engine-path resolvers and ``subprocess.Popen``
    (plus the process-group os calls) so the command-building branch runs
    deterministically without external dependencies. ``returncode`` controls
    the stubbed process exit code; ``shai_path``/``qchat_path`` control what the
    resolvers return (use ``None`` to simulate an unresolved path).
    """
    app = _make_app()

    recorded_cmds = []

    def _popen(cmd_args, *args, **kwargs):
        recorded_cmds.append(list(cmd_args))
        return _FakeProcess(returncode=returncode)

    events = []

    with app.test_request_context(json=json_body):
        from flask import session as flask_session
        flask_session["user_id"] = 1

        with mock.patch.object(genai_routes.db_manager, "execute_query",
                               side_effect=_fake_execute_query), \
             mock.patch("src.config_postgres.get_shai_paths",
                        return_value=shai_path), \
             mock.patch("src.config_postgres.get_qchat_paths",
                        return_value=qchat_path), \
             mock.patch("subprocess.Popen", side_effect=_popen), \
             mock.patch("os.setsid", create=True, return_value=0), \
             mock.patch("os.getpgid", create=True, return_value=4242), \
             mock.patch("os.killpg", create=True, return_value=None), \
             mock.patch.object(genai_routes, "return_prompt_for_operator",
                               return_value=("EXECUTE THE START ACTION NOW", True)):
            response = route_func()

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


def _error_event(events):
    for ev in events:
        if "error" in ev:
            return ev
    return None


def _dev_body(**overrides):
    body = {
        "message": "do something",
        "application_name": "",
        "application_folder": "",
        "action_operation": "MODIFY_CODE",
    }
    body.update(overrides)
    return body


def _ops_body(**overrides):
    body = {
        "message": "start my app",
        "application_name": "myapp",
        "application_folder": "/tmp/myapp",
        "action_operation": "START",
    }
    body.update(overrides)
    return body


# ---------------------------------------------------------------------------
# 3.1 - qchat (non-shai) command preservation
#   Observed on UNFIXED code: [engine_cmd, 'chat', '--trust-all-tools', prompt]
# ---------------------------------------------------------------------------

# Assorted non-shai engine selectors. Anything whose lowercase form is not
# 'shai' takes the default qchat branch.
_non_shai_engines = st.sampled_from([
    "qchat", "QCHAT", "q", "kiro", "kiro-cli", "amazonq", "default", "gpt", "other",
])


def _assert_qchat_form(cmd_args):
    """Non-shai engines preserve the chat --trust-all-tools form with resolved path."""
    assert cmd_args[0] == RESOLVED_QCHAT_PATH, (
        f"qchat command should use resolved engine_cmd: {cmd_args}")
    assert cmd_args[1] == "chat", f"qchat command missing 'chat' subcommand: {cmd_args}"
    assert cmd_args[2] == "--trust-all-tools", (
        f"qchat command missing '--trust-all-tools' flag: {cmd_args}")
    assert len(cmd_args) == 4, (
        f"qchat command should be [engine_cmd, 'chat', '--trust-all-tools', prompt]: {cmd_args}")


@settings(max_examples=25, deadline=None)
@given(engine=_non_shai_engines)
def test_developer_non_shai_preserves_chat_form(engine):
    """Developer path: non-shai engine keeps chat --trust-all-tools unchanged.

    Validates: Requirements 3.1
    """
    events, cmds = _drive_route(
        genai_routes.api_request_dev_ai_for_app,
        _dev_body(agentic_engine=engine),
    )
    assert cmds, "developer path never invoked subprocess.Popen"
    _assert_qchat_form(cmds[0])


@settings(max_examples=25, deadline=None)
@given(engine=_non_shai_engines)
def test_operator_non_shai_preserves_chat_form(engine):
    """Operator path: non-shai engine keeps chat --trust-all-tools unchanged.

    Validates: Requirements 3.1
    """
    events, cmds = _drive_route(
        genai_routes.api_request_ops_ai_for_app,
        _ops_body(agentic_engine=engine),
    )
    assert cmds, "operator path never invoked subprocess.Popen"
    _assert_qchat_form(cmds[0])


# ---------------------------------------------------------------------------
# 3.2 - agentic_command (deployControlPlan.sh) preservation
#   Observed on UNFIXED code: the branch builds cmd_args =
#   [deployControlPlan.sh, agentic_command] and announces it via a
#   "Executing deployControlPlan.sh with command: <command>" chunk.
#
#   NOTE (observation-first): on UNFIXED code the agentic_command branch does
#   NOT reach subprocess.Popen -- it hits a pre-existing, unrelated defect
#   (``engine_cmd`` is never assigned in this branch, so the subsequent
#   "Found ... at: {engine_cmd}" line raises NameError, caught by the outer
#   handler and surfaced as an error event). That defect is outside the scope
#   of this shai fix. The preserved baseline we assert on is therefore the
#   built command as announced in the chunk, which is immune to the unrelated
#   crash and faithfully reflects observed behavior.
# ---------------------------------------------------------------------------

_commands = st.text(
    # Keep to a safe, printable subset: the command is echoed into a JSON chunk
    # and compared verbatim, so avoid control chars / whitespace-only values
    # that the route's own string handling could normalize.
    alphabet=st.characters(min_codepoint=33, max_codepoint=126),
    min_size=1,
    max_size=40,
)


def _deploy_chunk(events):
    """Return the 'Executing deployControlPlan.sh with command: ...' chunk text."""
    marker = "Executing deployControlPlan.sh with command: "
    for ev in events:
        chunk = ev.get("chunk", "")
        if chunk.startswith(marker):
            return chunk[len(marker):]
    return None


@settings(max_examples=25, deadline=None)
@given(command=_commands, engine=st.sampled_from(["shai", "qchat", "kiro"]))
def test_developer_agentic_command_preserves_deploy_script(command, engine):
    """Developer path: non-empty agentic_command routes through deployControlPlan.sh.

    The engine value is irrelevant here -- agentic_command takes precedence over
    every engine branch, so we vary it (including 'shai') to confirm the branch
    short-circuits regardless. We assert on the observed deploy chunk because the
    unfixed branch never reaches Popen (see module note).

    Validates: Requirements 3.2
    """
    events, cmds = _drive_route(
        genai_routes.api_request_dev_ai_for_app,
        _dev_body(agentic_engine=engine, agentic_command=command),
    )
    assert _deploy_chunk(events) == command, (
        f"agentic_command should route through deployControlPlan.sh with the "
        f"given command; events={events}")


@settings(max_examples=25, deadline=None)
@given(command=_commands, engine=st.sampled_from(["shai", "qchat", "kiro"]))
def test_operator_agentic_command_preserves_deploy_script(command, engine):
    """Operator path: non-empty agentic_command routes through deployControlPlan.sh.

    Validates: Requirements 3.2
    """
    events, cmds = _drive_route(
        genai_routes.api_request_ops_ai_for_app,
        _ops_body(agentic_engine=engine, agentic_command=command),
    )
    assert _deploy_chunk(events) == command, (
        f"agentic_command should route through deployControlPlan.sh with the "
        f"given command; events={events}")


# ---------------------------------------------------------------------------
# 3.3 - success == (returncode == 0) preservation at both sites
#   Observed on UNFIXED code: done event success mirrors the process exit code.
# ---------------------------------------------------------------------------

_return_codes = st.integers(min_value=-5, max_value=5)


@settings(max_examples=25, deadline=None)
@given(returncode=_return_codes)
def test_developer_success_mirrors_returncode(returncode):
    """Developer path: done.success == (returncode == 0) across return codes.

    Driven through the qchat branch (a resolvable path) so a process always
    starts; the stubbed process exits with the generated return code.

    Validates: Requirements 3.3
    """
    events, cmds = _drive_route(
        genai_routes.api_request_dev_ai_for_app,
        _dev_body(agentic_engine="qchat"),
        returncode=returncode,
    )
    done = _done_event(events)
    assert done is not None, f"no done event emitted; events={events}"
    assert done.get("success") == (returncode == 0), (
        f"success should equal (returncode == 0); returncode={returncode}, done={done}")
    assert done.get("returncode") == returncode, (
        f"returncode should be surfaced unchanged; returncode={returncode}, done={done}")


@settings(max_examples=25, deadline=None)
@given(returncode=_return_codes)
def test_operator_success_mirrors_returncode(returncode):
    """Operator path: done.success == (returncode == 0) across return codes.

    Validates: Requirements 3.3
    """
    events, cmds = _drive_route(
        genai_routes.api_request_ops_ai_for_app,
        _ops_body(agentic_engine="qchat"),
        returncode=returncode,
    )
    done = _done_event(events)
    assert done is not None, f"no done event emitted; events={events}"
    assert done.get("success") == (returncode == 0), (
        f"success should equal (returncode == 0); returncode={returncode}, done={done}")
    assert done.get("returncode") == returncode, (
        f"returncode should be surfaced unchanged; returncode={returncode}, done={done}")


# ---------------------------------------------------------------------------
# 3.4 - "not found for SHAI" early return preservation (no process started)
#   Observed on UNFIXED code: unresolved shai path -> error event, no Popen.
# ---------------------------------------------------------------------------

def test_developer_unresolved_shai_reports_not_found_and_starts_no_process():
    """Developer path: unresolved shai path yields not-found error, no process.

    Validates: Requirements 3.4
    """
    events, cmds = _drive_route(
        genai_routes.api_request_dev_ai_for_app,
        _dev_body(agentic_engine="shai"),
        shai_path=None,
    )
    assert not cmds, f"no process should start when shai is unresolved; cmds={cmds}"
    err = _error_event(events)
    assert err is not None, f"expected a not-found error event; events={events}"
    assert "not found for SHAI" in err["error"], (
        f"expected 'not found for SHAI' error, got {err}")


def test_operator_unresolved_shai_reports_not_found_and_starts_no_process():
    """Operator path: unresolved shai path yields not-found error, no process.

    Validates: Requirements 3.4
    """
    events, cmds = _drive_route(
        genai_routes.api_request_ops_ai_for_app,
        _ops_body(agentic_engine="shai"),
        shai_path=None,
    )
    assert not cmds, f"no process should start when shai is unresolved; cmds={cmds}"
    err = _error_event(events)
    assert err is not None, f"expected a not-found error event; events={events}"
    assert "not found for SHAI" in err["error"], (
        f"expected 'not found for SHAI' error, got {err}")
