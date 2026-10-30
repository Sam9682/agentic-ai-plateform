'use strict';

/**
 * Bug-condition exploration tests — Property 1 (bugfix: agent-lifecycle-controls).
 *
 * Feature: agent-lifecycle-controls, Property 1: Bug Condition — the Agent
 * Management "Instances" panel lists agents but exposes NO wired, state-aware
 * lifecycle controls.
 *
 *   isBugCondition(X) = X.panel = "instances"
 *                       AND X.hasAgents = true
 *                       AND NOT X.offersLifecycleControls
 *
 * These tests encode the EXPECTED (post-fix) behavior described in Property 1
 * of the design: for every agent row the Instances renderer SHALL emit
 * Start/Stop/Restart controls wired to POST /api/v1/agents/<id>/{start|stop|
 * restart}, enabled/disabled per lifecycleControlState(status), with a
 * per-panel feedback element (#amInstancesFeedback).
 *
 * **CRITICAL**: On the UNFIXED code these tests MUST FAIL. The failure is the
 * SUCCESS case — it confirms the bug exists (the shared text-only renderer emits
 * no buttons, there is no amPostLifecycle POST helper, no lifecycleControlState
 * mapping, and no #amInstancesFeedback element). Do NOT "fix" these tests or the
 * code here; the fix is implemented in a later task and these same tests will
 * then pass.
 *
 * Validates: Requirements 1.1, 1.2, 1.3
 */

const test = require('node:test');
const assert = require('node:assert');

const {
    document,
    sortHelper,
} = require('./harness');

/**
 * Render the current Instances path for a given set of agents into a fresh
 * container, using whatever the module exports. Returns the container element
 * so tests can inspect the produced DOM.
 *
 * It prefers the fixed, dedicated renderer (renderAgentInstancesTable) when it
 * exists; otherwise it falls back to the shared text-only renderer that
 * loadAmInstances currently uses (amRenderTable) so the test can still render
 * SOMETHING on unfixed code and assert the absence of controls.
 */
function renderInstances(agents) {
    const containerId = 'amInstancesContent';
    const feedbackId = 'amInstancesFeedback';

    // Fresh container each call.
    const existing = document.getElementById(containerId);
    if (existing && existing.parentNode) existing.parentNode.removeChild(existing);
    const container = document.createElement('div');
    container.id = containerId;
    document.body.appendChild(container);

    if (typeof sortHelper.renderAgentInstancesTable === 'function') {
        // Fixed path: dedicated renderer writes the table + feedback element.
        sortHelper.renderAgentInstancesTable(containerId, agents, feedbackId);
    } else {
        // Unfixed path: the shared text-only renderer loadAmInstances uses today.
        sortHelper.amRenderTable(
            containerId,
            [
                { key: 'id', label: 'ID' },
                { key: 'identity', label: 'Identity' },
                { key: 'name', label: 'Name' },
                { key: 'status', label: 'Status' },
            ],
            agents,
            'No agents registered.'
        );
    }
    return container;
}

/**
 * Collect per-row lifecycle controls from a rendered Instances container.
 * A "control" is a <button> whose inline onclick POSTs to one of the agent
 * lifecycle endpoints. Returns a map op -> array of matching button elements.
 */
function lifecycleButtons(container) {
    const buttons = Array.from(container.querySelectorAll('button'));
    const byOp = { start: [], stop: [], restart: [] };
    for (const btn of buttons) {
        const onclick = btn.getAttribute('onclick') || '';
        for (const op of ['start', 'stop', 'restart']) {
            // Wired either by an explicit endpoint reference or by the
            // triggerAgentLifecycle(id, 'op') handler the design specifies.
            const endpointRe = new RegExp('/api/v1/agents/\\d+/' + op);
            const handlerRe = new RegExp("triggerAgentLifecycle\\([^,]+,\\s*['\"]" + op + "['\"]");
            if (endpointRe.test(onclick) || handlerRe.test(onclick)) {
                byOp[op].push(btn);
            }
        }
    }
    return byOp;
}

// Test case 1 — No controls in the rendered Instances table (expected post-fix:
// each row exposes wired Start/Stop/Restart controls). FAILS on unfixed code.
test('Property 1 (bug condition): READY agent row exposes wired Start/Stop/Restart controls', () => {
    const agents = [
        { id: 7, identity: 'agent-ready', name: 'Ready Agent', status: 'READY' },
    ];
    const container = renderInstances(agents);
    const byOp = lifecycleButtons(container);

    // Expected behavior (Property 1a/1b): one of each control, wired to the
    // existing endpoints. On unfixed code the renderer emits only text cells,
    // so these arrays are empty and the assertions fail — confirming the bug.
    assert.strictEqual(byOp.start.length, 1,
        'expected exactly one Start control wired to POST /api/v1/agents/<id>/start');
    assert.strictEqual(byOp.stop.length, 1,
        'expected exactly one Stop control wired to POST /api/v1/agents/<id>/stop');
    assert.strictEqual(byOp.restart.length, 1,
        'expected exactly one Restart control wired to POST /api/v1/agents/<id>/restart');

    // State-aware (Property 1b): for a READY agent Start and Restart are
    // enabled; Stop is disabled (illegal while not RUNNING/UNHEALTHY → 409).
    assert.ok(!byOp.start[0].disabled, 'Start must be enabled for a READY agent');
    assert.ok(!byOp.restart[0].disabled, 'Restart must be enabled for a READY agent');
    assert.ok(byOp.stop[0].disabled, 'Stop must be disabled for a READY agent');

    // Feedback path (Property 1c/1d): a dedicated per-panel feedback element.
    const feedback = document.getElementById('amInstancesFeedback');
    assert.ok(feedback, 'expected a #amInstancesFeedback element for success/error feedback');
});

// Test case 2 — No lifecycle POST helper exported (expected post-fix: present).
test('Property 1 (bug condition): amPostLifecycle POST helper is exported', () => {
    assert.strictEqual(
        typeof sortHelper.amPostLifecycle,
        'function',
        'expected amPostLifecycle(agentId, op) to be exported to wire POST /api/v1/agents/<id>/{start|stop|restart}'
    );
});

// Test case 3 — No status→controls mapping exported (expected post-fix: present).
test('Property 1 (bug condition): lifecycleControlState status→controls mapping is exported', () => {
    assert.strictEqual(
        typeof sortHelper.lifecycleControlState,
        'function',
        'expected lifecycleControlState(status) to be exported to map agent.status to legal controls'
    );
});

// Test case 4 — Edge case transient state (expected post-fix: all three controls
// present but disabled for a STARTING agent, with a feedback path). FAILS on
// unfixed code where no control exists at all.
test('Property 1 (bug condition, edge): STARTING agent yields all three controls present but disabled', () => {
    const agents = [
        { id: 11, identity: 'agent-starting', name: 'Starting Agent', status: 'STARTING' },
    ];
    const container = renderInstances(agents);
    const byOp = lifecycleButtons(container);

    assert.strictEqual(byOp.start.length, 1, 'expected a Start control present for a STARTING agent');
    assert.strictEqual(byOp.stop.length, 1, 'expected a Stop control present for a STARTING agent');
    assert.strictEqual(byOp.restart.length, 1, 'expected a Restart control present for a STARTING agent');

    // Transient state: no actionable control — all three disabled.
    assert.ok(byOp.start[0].disabled, 'Start must be disabled for a STARTING (transient) agent');
    assert.ok(byOp.stop[0].disabled, 'Stop must be disabled for a STARTING (transient) agent');
    assert.ok(byOp.restart[0].disabled, 'Restart must be disabled for a STARTING (transient) agent');

    // A feedback path must still exist even when no control is actionable.
    const feedback = document.getElementById('amInstancesFeedback');
    assert.ok(feedback, 'expected a #amInstancesFeedback element even for transient-state agents');
});
