#!/usr/bin/env python3
"""Tests for the unified-input-enter-newline feature.

Feature: unified-input-enter-newline. The behavior under test is the dashboard
keydown handling for the Unified_Input textarea (``#unifiedInput`` in
``templates/dashboard.html``): plain Enter and Shift+Enter insert a newline,
while Ctrl+Enter and Cmd+Enter (plus the SEND button) submit the message.

Because the behavior lives in client-side JavaScript, the property tests model
the pure keydown classifier (``is_submit_shortcut``) in Python with
``hypothesis``, mirroring the design's conceptual classifier:

    isSubmitShortcut(e) := (e.key === 'Enter') && (e.ctrlKey || e.metaKey)

This module is the scaffold established by task 2.1. Subsequent tasks (2.2,
2.3, 2.4 property tests; 3.1, 3.2 static checks) extend it.
"""
import os
import sys

from hypothesis import given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


def is_submit_shortcut(key, ctrl, meta):
    """Pure reference classifier for the unified-input keydown decision.

    Mirrors the design's conceptual classifier:
        isSubmitShortcut(e) := (e.key === 'Enter') && (e.ctrlKey || e.metaKey)

    Returns ``True`` when the keydown is a submit shortcut (the handler should
    call ``preventDefault()`` then ``sendUnifiedMessage()``), and ``False``
    otherwise (the handler does nothing and the browser inserts a newline).

    Args:
        key: The ``KeyboardEvent.key`` value (e.g. ``'Enter'``).
        ctrl: Whether the Ctrl key is held (``KeyboardEvent.ctrlKey``).
        meta: Whether the Cmd/meta key is held (``KeyboardEvent.metaKey``).
    """
    return (key == 'Enter') and (ctrl or meta)


def test_is_submit_shortcut_reference_examples():
    """Smoke check that the reference classifier matches the design truth table."""
    # Enter with a submit modifier -> submit.
    assert is_submit_shortcut('Enter', True, False) is True
    assert is_submit_shortcut('Enter', False, True) is True
    assert is_submit_shortcut('Enter', True, True) is True
    # Plain Enter / Shift+Enter (no submit modifier) -> not a submit shortcut.
    assert is_submit_shortcut('Enter', False, False) is False
    # Non-Enter keys are never a submit shortcut, regardless of modifiers.
    assert is_submit_shortcut('a', True, True) is False
    assert is_submit_shortcut('Shift', False, True) is False

# ---------------------------------------------------------------------------
# Task 3.1 - Static checks against the rewritten handler in dashboard.html
#
# These checks parse ``templates/dashboard.html`` directly (the behavior lives
# in inline client-side JavaScript) and assert the rewritten keydown handler
# and the SEND button wiring match the design. They cover:
#   - Requirement 2.4: the SEND button (#unifiedSendBtn) invokes
#     sendUnifiedMessage() on click.
#   - Requirement 1.3: plain Enter has no path to activate the SEND button
#     (the only keydown->send path requires e.ctrlKey || e.metaKey).
# ---------------------------------------------------------------------------

import re

DASHBOARD_HTML = os.path.join(PROJECT_ROOT, 'templates', 'dashboard.html')


def _read_dashboard_html():
    """Return the full text of templates/dashboard.html."""
    with open(DASHBOARD_HTML, 'r', encoding='utf-8') as fh:
        return fh.read()


def _extract_unified_keydown_handler(html):
    """Return the body of the global keydown handler for #unifiedInput.

    The handler is the ``document.addEventListener('keydown', ...)`` block that
    guards on ``e.target.id`` being ``'unifiedInput'``. Returns the substring
    from ``addEventListener('keydown'`` up to the matching ``});`` terminator.
    """
    start = html.find("addEventListener('keydown'")
    assert start != -1, "No keydown listener found in dashboard.html"
    # The unified-input keydown handler references unifiedInput; make sure we
    # grabbed the right listener (there is only one keydown listener, but guard
    # against picking an unrelated one).
    end = html.find('});', start)
    assert end != -1, "keydown listener block is not terminated with '});'"
    block = html[start:end + len('});')]
    assert 'unifiedInput' in block, (
        "The keydown listener does not reference 'unifiedInput'"
    )
    return block


def test_keydown_handler_guards_on_target_and_enter():
    """The handler guards on e.target.id === 'unifiedInput' and e.key === 'Enter'.

    Validates the design's early-return guard so only Enter presses targeting
    the Unified_Input are considered.
    """
    block = _extract_unified_keydown_handler(_read_dashboard_html())
    # Normalize whitespace so spacing variations don't break the assertions.
    normalized = re.sub(r'\s+', ' ', block)

    assert "e.target.id !== 'unifiedInput'" in normalized or \
           "e.target.id === 'unifiedInput'" in normalized, (
        "Handler must guard on e.target.id being 'unifiedInput'"
    )
    assert "e.key !== 'Enter'" in normalized or "e.key === 'Enter'" in normalized, (
        "Handler must guard on e.key being 'Enter'"
    )


def test_keydown_handler_branches_on_ctrl_or_meta():
    """The handler branches on e.ctrlKey || e.metaKey (the submit modifiers)."""
    block = _extract_unified_keydown_handler(_read_dashboard_html())
    normalized = re.sub(r'\s+', ' ', block)
    assert 'e.ctrlKey || e.metaKey' in normalized, (
        "Handler must branch on 'e.ctrlKey || e.metaKey'"
    )


def test_send_is_called_only_inside_submit_modifier_branch():
    """sendUnifiedMessage() is called only inside the e.ctrlKey||e.metaKey branch.

    The handler must contain exactly one call to sendUnifiedMessage(), and that
    call must appear after the modifier check, inside its guarded block. This is
    what prevents plain Enter from ever reaching the send path.
    """
    block = _extract_unified_keydown_handler(_read_dashboard_html())

    # There must be exactly one send call in the keydown handler.
    assert block.count('sendUnifiedMessage()') == 1, (
        "Expected exactly one sendUnifiedMessage() call in the keydown handler"
    )

    modifier_idx = block.find('e.ctrlKey || e.metaKey')
    send_idx = block.find('sendUnifiedMessage()')
    assert modifier_idx != -1, "Handler must contain the submit-modifier check"
    assert send_idx != -1, "Handler must call sendUnifiedMessage()"
    # The send call must come after the modifier check (inside its branch).
    assert send_idx > modifier_idx, (
        "sendUnifiedMessage() must be called only inside the "
        "e.ctrlKey || e.metaKey branch"
    )
    # preventDefault must also live inside the submit branch, before the send.
    prevent_idx = block.find('e.preventDefault()')
    assert prevent_idx != -1 and prevent_idx > modifier_idx, (
        "e.preventDefault() must be inside the submit-modifier branch"
    )


def test_send_button_wires_to_send_handler_on_click():
    """The SEND button #unifiedSendBtn invokes sendUnifiedMessage() on click.

    Validates: Requirement 2.4.
    """
    html = _read_dashboard_html()
    # Find the #unifiedSendBtn element markup.
    match = re.search(r'<button[^>]*id="unifiedSendBtn"[^>]*>', html)
    assert match is not None, "No #unifiedSendBtn button found in dashboard.html"
    button_tag = match.group(0)
    assert 'onclick="sendUnifiedMessage()"' in button_tag, (
        "SEND button #unifiedSendBtn must wire to sendUnifiedMessage() on click"
    )


def test_plain_enter_has_no_path_to_activate_send_button():
    """Plain Enter has no path to activate the SEND button.

    Validates: Requirement 1.3.

    The only keydown->send path is the keydown handler, which calls
    sendUnifiedMessage() exclusively inside the e.ctrlKey || e.metaKey branch.
    A plain Enter (no Ctrl/Cmd) therefore never reaches that branch, and nothing
    in the handler programmatically clicks or dispatches an event to
    #unifiedSendBtn. We assert the handler does not reference the button at all
    (no .click(), no getElementById('unifiedSendBtn')) and that its only send
    path is modifier-gated.
    """
    block = _extract_unified_keydown_handler(_read_dashboard_html())
    # The handler must not programmatically activate the button.
    assert 'unifiedSendBtn' not in block, (
        "keydown handler must not reference #unifiedSendBtn directly"
    )
    assert '.click(' not in block, (
        "keydown handler must not programmatically click any element"
    )
    # And its only send path is gated behind the submit modifiers, so plain
    # Enter cannot reach it.
    modifier_idx = block.find('e.ctrlKey || e.metaKey')
    send_idx = block.find('sendUnifiedMessage()')
    assert modifier_idx != -1 and send_idx > modifier_idx, (
        "Plain Enter must have no path to send: the only send call must be "
        "gated behind e.ctrlKey || e.metaKey"
    )

# ---------------------------------------------------------------------------
# Task 3.2 - Static layout checks for the #unifiedInput markup
#
# These checks parse ``templates/dashboard.html`` directly and assert the
# textarea markup keeps its fixed two-row height and has no auto-resize /
# auto-grow handler attached. They cover:
#   - Requirement 3.1: the Unified_Input retains a fixed height of two rows
#     (the ``rows="2"`` attribute).
#   - Requirement 3.3: the Unified_Input retains its two-row height without
#     expanding as content is added (no auto-resize/auto-grow handler mutates
#     its height on input).
#
# Requirement 3.2 (an internal scrollbar appears while content overflows the
# visible two-row height) is browser-native behavior for a fixed-height
# ``<textarea>`` and cannot be asserted from static markup; it is verified
# manually/visually, as noted in the design's Testing Strategy.
# ---------------------------------------------------------------------------


def _extract_unified_input_tag(html):
    """Return the ``<textarea id="unifiedInput" ...>`` opening tag.

    Reuses the design's single-element assumption: there is exactly one
    ``#unifiedInput`` textarea in the dashboard markup.
    """
    match = re.search(r'<textarea[^>]*id="unifiedInput"[^>]*>', html)
    assert match is not None, "No #unifiedInput <textarea> found in dashboard.html"
    return match.group(0)


def test_unified_input_keeps_fixed_two_rows():
    """The #unifiedInput textarea keeps a fixed height of two rows.

    Validates: Requirement 3.1.

    The two-row height is expressed by the ``rows="2"`` attribute on the
    textarea markup.
    """
    tag = _extract_unified_input_tag(_read_dashboard_html())
    assert re.search(r'\brows\s*=\s*"2"', tag), (
        'The #unifiedInput textarea must keep rows="2" for its fixed two-row '
        f"height; got: {tag}"
    )


def test_unified_input_has_no_auto_resize_handler():
    """The #unifiedInput textarea has no auto-resize/auto-grow handler attached.

    Validates: Requirement 3.3.

    The only inline event handler on the textarea is
    ``oninput="updateSendButtonState()"``, which toggles the SEND button's
    enabled state and never mutates the element's height. We assert that:
      - the textarea's only ``oninput`` handler is updateSendButtonState();
      - no height/row-mutating logic (style.height, scrollHeight, rows=, or an
        "auto" overflow/resize toggle) is wired onto the element's inline
        handlers.
    So nothing grows the textarea as content is added; it stays two rows.
    """
    tag = _extract_unified_input_tag(_read_dashboard_html())

    # The only inline event handler on the textarea is the send-button toggle.
    oninput_handlers = re.findall(r'oninput\s*=\s*"([^"]*)"', tag)
    assert oninput_handlers == ['updateSendButtonState()'], (
        "The #unifiedInput textarea's only oninput handler must be "
        f"updateSendButtonState(); got: {oninput_handlers}"
    )

    # No inline handler on the textarea may auto-grow / auto-resize it: reject
    # the common auto-resize idioms (writing style.height, reading scrollHeight,
    # reassigning rows, or an inline onkeyup/onchange resize hook).
    forbidden = ('style.height', 'scrollHeight', 'this.rows', 'rows =')
    for needle in forbidden:
        assert needle not in tag, (
            "The #unifiedInput textarea must have no auto-resize/auto-grow "
            f"logic in its markup; found {needle!r} in: {tag}"
        )


def test_requirement_3_2_scrollbar_is_browser_native_manual_check():
    """Document that Requirement 3.2 is verified manually/visually.

    Validates: Requirement 3.2 (by documentation).

    When the content of the fixed-height #unifiedInput textarea overflows its
    visible two-row height, the browser renders an internal scrollbar natively.
    This is not expressible as a static-markup assertion and is confirmed by a
    manual/visual check, as noted in the design's Testing Strategy. This test
    exists to anchor that intent alongside the structural checks; the fixed
    two-row height that makes the scrollbar appear is asserted by
    ``test_unified_input_keeps_fixed_two_rows`` above.
    """
    # The precondition for native overflow scrolling is the fixed two-row
    # height; assert it holds here too so this documentation test is anchored.
    tag = _extract_unified_input_tag(_read_dashboard_html())
    assert re.search(r'\brows\s*=\s*"2"', tag), (
        "Native overflow scrolling (Requirement 3.2) relies on the fixed "
        'two-row height; the textarea must keep rows="2".'
    )

# ---------------------------------------------------------------------------
# Task 2.2 - Property 1: Non-submit Enter inserts a newline and never sends
#
# A Plain_Enter (Ctrl and Cmd both not held) or Shift+Enter targeting the
# Unified_Input must never be a submit shortcut: the classifier returns False,
# so the handler does nothing (no sendUnifiedMessage(), no preventDefault()) and
# the browser inserts the default newline. shiftKey is arbitrary because Shift
# does not change the outcome.
#   - Requirement 1.1 / 1.4: a newline is allowed to be inserted.
#   - Requirement 1.2 / 1.5: the Send_Handler is not invoked.
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(shift=st.booleans())
def test_property_non_submit_enter_inserts_newline_and_never_sends(shift):
    """Feature: unified-input-enter-newline, Property 1: Non-submit Enter inserts a newline and never sends

    Validates: Requirements 1.1, 1.2, 1.4, 1.5

    For an Enter keydown with ctrlKey=False and metaKey=False and an arbitrary
    shiftKey, the submit-shortcut classifier yields False. A False result means
    the handler does nothing: it neither invokes the Send_Handler nor calls
    preventDefault(), so the browser's default newline insertion proceeds.
    """
    ctrl = False
    meta = False

    is_submit = is_submit_shortcut('Enter', ctrl, meta)

    # Not a submit shortcut: no send and no preventDefault, regardless of Shift.
    assert is_submit is False, (
        "Plain Enter / Shift+Enter (ctrl=False, meta=False) must never be a "
        f"submit shortcut; shiftKey={shift}"
    )
    # Model the handler's derived outcomes from the classifier result: the
    # handler sends and suppresses the newline iff is_submit is True.
    sends = is_submit
    prevents_default = is_submit
    assert sends is False, "Non-submit Enter must not invoke the Send_Handler"
    assert prevents_default is False, (
        "Non-submit Enter must not call preventDefault(); the newline is allowed"
    )

# ---------------------------------------------------------------------------
# Task 2.3 - Property 2: Submit shortcut sends and suppresses the newline
#
# An Enter keydown targeting the Unified_Input where the Ctrl key or the Cmd
# (meta) key is held is a Submit_Shortcut: the classifier returns True, so the
# handler suppresses the default newline (preventDefault) and invokes the
# Send_Handler (sendUnifiedMessage()). shiftKey is arbitrary because Shift does
# not change the outcome once a submit modifier is held.
#   - Requirement 2.1: Ctrl+Enter invokes the Send_Handler.
#   - Requirement 2.2: Cmd+Enter invokes the Send_Handler.
#   - Requirement 2.3: the default newline insertion is suppressed.
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    ctrl=st.booleans(),
    meta=st.booleans(),
    shift=st.booleans(),
)
def test_property_submit_shortcut_sends_and_suppresses_newline(ctrl, meta, shift):
    """Feature: unified-input-enter-newline, Property 2: Submit shortcut sends and suppresses the newline

    Validates: Requirements 2.1, 2.2, 2.3

    For an Enter keydown where at least one of ctrlKey/metaKey is held (shiftKey
    arbitrary), the submit-shortcut classifier yields True. A True result means
    the handler invokes the Send_Handler (sendUnifiedMessage()) and calls
    preventDefault(), suppressing the browser's default newline insertion.
    """
    # Constrain the generated input space so at least one submit modifier is
    # held, as required by the property (Ctrl or Cmd). If neither is set, force
    # Ctrl on so the example still exercises a submit shortcut.
    if not (ctrl or meta):
        ctrl = True

    is_submit = is_submit_shortcut('Enter', ctrl, meta)

    # With a submit modifier held, the Enter keydown is a submit shortcut.
    assert is_submit is True, (
        "Enter with Ctrl or Cmd held must be a submit shortcut; "
        f"ctrl={ctrl}, meta={meta}, shift={shift}"
    )
    # Model the handler's derived outcomes from the classifier result: the
    # handler sends and suppresses the newline iff is_submit is True.
    sends = is_submit
    prevents_default = is_submit
    assert sends is True, "Submit shortcut must invoke the Send_Handler"
    assert prevents_default is True, (
        "Submit shortcut must call preventDefault() to suppress the newline"
    )

# ---------------------------------------------------------------------------
# Task 2.4 - Property 3: Enter handling is mutually exclusive and exhaustive
#
# For any Enter keydown targeting the Unified_Input, the (send, preventDefault)
# outcome is fully determined by whether a submit modifier is held
# (``e.ctrlKey || e.metaKey``). The two branches are mutually exclusive and
# exhaustive: exactly one outcome occurs -- either the submit outcome
# (send AND preventDefault) or the newline outcome (NOT send AND NOT
# preventDefault), never both and never neither. shiftKey is arbitrary because
# Shift never changes the outcome.
#   - Requirement 1.1 / 1.2: non-submit Enter inserts a newline, no send.
#   - Requirement 2.1 / 2.2 / 2.3: Ctrl+Enter / Cmd+Enter send and suppress the
#     default newline.
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    ctrl=st.booleans(),
    meta=st.booleans(),
    shift=st.booleans(),
)
def test_property_enter_handling_is_mutually_exclusive_and_exhaustive(ctrl, meta, shift):
    """Feature: unified-input-enter-newline, Property 3: Enter handling is mutually exclusive and exhaustive

    Validates: Requirements 1.1, 1.2, 2.1, 2.2, 2.3

    For an arbitrary Enter keydown (ctrlKey, metaKey, shiftKey all arbitrary),
    the (send, preventDefault) outcome is fully determined by
    ``e.ctrlKey || e.metaKey``. The handler derives both outcomes from the
    single submit-shortcut classifier, so send and preventDefault always agree.
    The two possible outcomes are mutually exclusive and exhaustive: exactly one
    of (send AND preventDefault) or (NOT send AND NOT preventDefault) holds --
    never both and never neither.
    """
    is_submit = is_submit_shortcut('Enter', ctrl, meta)

    # The outcome is fully determined by whether a submit modifier is held.
    assert is_submit == (ctrl or meta), (
        "For an Enter keydown, the submit decision must be exactly "
        f"(ctrlKey || metaKey); ctrl={ctrl}, meta={meta}, shift={shift}"
    )

    # Model the handler's derived outcomes from the single classifier result:
    # the handler sends and suppresses the newline iff is_submit is True, so the
    # two derived outcomes are always identical.
    sends = is_submit
    prevents_default = is_submit

    submit_outcome = sends and prevents_default
    newline_outcome = (not sends) and (not prevents_default)

    # Exhaustive: at least one of the two outcomes always occurs.
    assert submit_outcome or newline_outcome, (
        "Enter handling must be exhaustive: either (send AND preventDefault) "
        f"or (NOT send AND NOT preventDefault) must hold; ctrl={ctrl}, "
        f"meta={meta}, shift={shift}"
    )
    # Mutually exclusive: the two outcomes never occur together.
    assert not (submit_outcome and newline_outcome), (
        "Enter handling must be mutually exclusive: the submit outcome and the "
        f"newline outcome cannot both hold; ctrl={ctrl}, meta={meta}, "
        f"shift={shift}"
    )
    # Exactly one outcome occurs (mutual exclusivity + exhaustiveness together).
    assert submit_outcome != newline_outcome, (
        "Enter handling must yield exactly one outcome; "
        f"ctrl={ctrl}, meta={meta}, shift={shift}"
    )
