'use strict';

/**
 * Rendering-invariant property tests for the "agent-lifecycle-controls" bugfix
 * (task 3.6 — fast-check property-based coverage of the new pure helpers).
 *
 * The fix adds a dedicated Instances renderer, renderAgentInstanceRows(agents),
 * and a pure status -> legal-controls mapping, lifecycleControlState(status).
 * This suite drives both with randomized inputs to pin down two invariants that
 * example-based unit tests cannot fully cover:
 *
 *   Property A (renderAgentInstanceRows over random agent lists, incl. XSS):
 *     - emits exactly one <tr> row per agent, in input order;
 *     - never emits an unescaped "<script>" substring (XSS-y names/identities
 *       are escaped to text, not markup);
 *     - sets each control's enabled/disabled state EXACTLY per
 *       lifecycleControlState(agent.status): a disabled attribute iff the
 *       mapping says that control is NOT enabled.
 *
 *   Property B (lifecycleControlState over random statuses):
 *     - only ever enables a control for a state from which the backend
 *       transition graph legally permits that transition, cross-checked against
 *       the documented legal sets:
 *         start   ∈ { READY, STOPPED, FAILED }
 *         stop    ∈ { RUNNING, UNHEALTHY }
 *         restart ∈ { RUNNING, READY, STOPPED, FAILED, UNHEALTHY }
 *
 * The helpers under test are pure (they return <tr> HTML strings); to count
 * rows and inspect buttons robustly we parse the produced markup inside a fresh
 * jsdom container, mirroring the approach in tests/js/property1.test.js. The
 * header row is never part of renderAgentInstanceRows' output, so every <tr>
 * parsed here corresponds to an agent row (no header row to exclude).
 *
 * Validates: Requirements 2.1, 2.5
 */

const test = require('node:test');
const assert = require('node:assert');
const fc = require('fast-check');

const { document, sortHelper } = require('./harness');

const { renderAgentInstanceRows, lifecycleControlState } = sortHelper;

// Documented legal transition sets (the backend transition graph the UI mirrors
// so a would-be-409 action is presented disabled). Kept independent of the
// implementation so the property cross-checks against the contract, not itself.
const LEGAL = {
    start: new Set(['READY', 'STOPPED', 'FAILED']),
    stop: new Set(['RUNNING', 'UNHEALTHY']),
    restart: new Set(['RUNNING', 'READY', 'STOPPED', 'FAILED', 'UNHEALTHY']),
};

const KNOWN_STATES = [
    'READY', 'STOPPED', 'FAILED', 'RUNNING', 'UNHEALTHY',
    'REGISTERED', 'INSTALLING', 'INSTALLED', 'CONFIGURING', 'STARTING',
    'STOPPING', 'QUARANTINED', 'TERMINATED',
];

// A grab-bag of XSS-y / markup-y strings to force through escaped cells.
const XSS_STRINGS = [
    '<script>alert(1)</script>',
    '"><script>alert(document.cookie)</script>',
    "<img src=x onerror=alert('x')>",
    '</td></tr><script>evil()</script>',
    '<script src="//evil.example/x.js"></script>',
    '<SCRIPT>alert(1)</SCRIPT>',
    '"><svg/onload=alert(1)>',
    "'; DROP TABLE agents; --",
    '<a href="javascript:alert(1)">x</a>',
];

// A status generator mixing the known lifecycle states with arbitrary strings
// (including XSS-y ones), so the property covers transient/unknown values too.
const statusArb = fc.oneof(
    fc.constantFrom(...KNOWN_STATES),
    fc.string(),
    fc.constantFrom(...XSS_STRINGS)
);

// A single agent whose name/identity can be arbitrary (incl. XSS-y) strings and
// whose status is drawn from the mixed status generator above.
const agentArb = fc.record({
    id: fc.oneof(fc.integer({ min: 0, max: 1_000_000 }), fc.string()),
    identity: fc.oneof(fc.string(), fc.constantFrom(...XSS_STRINGS)),
    name: fc.oneof(fc.string(), fc.constantFrom(...XSS_STRINGS)),
    status: statusArb,
});

const agentListArb = fc.array(agentArb, { minLength: 0, maxLength: 12 });

/**
 * Render agent-row HTML into a fresh jsdom container and return it so tests can
 * query <tr> rows and <button> controls. renderAgentInstanceRows returns bare
 * <tr> strings, so wrap them in a <table> before parsing (jsdom requires a
 * table context to materialize <tr>/<td> nodes).
 */
function renderRowsContainer(agents) {
    const rowsHtml = renderAgentInstanceRows(agents);
    const container = document.createElement('div');
    container.innerHTML = '<table><tbody>' + rowsHtml + '</tbody></table>';
    return { container, rowsHtml };
}

/**
 * For a parsed row element, return a map op -> button element for the three
 * lifecycle controls, matched by the triggerAgentLifecycle(id, 'op') handler
 * the renderer wires onto each button's inline onclick.
 */
function controlsForRow(tr) {
    const byOp = { start: null, stop: null, restart: null };
    const buttons = Array.from(tr.querySelectorAll('button'));
    for (const btn of buttons) {
        const onclick = btn.getAttribute('onclick') || '';
        for (const op of ['start', 'stop', 'restart']) {
            const handlerRe = new RegExp("triggerAgentLifecycle\\([^,]*,\\s*['\"]" + op + "['\"]\\)");
            if (handlerRe.test(onclick)) byOp[op] = btn;
        }
    }
    return byOp;
}

// ===========================================================================
// Property A — renderAgentInstanceRows rendering invariants (Req 2.1, 2.5).
// ===========================================================================

test('Property A: renderAgentInstanceRows emits exactly one <tr> per agent, in input order', () => {
    fc.assert(
        fc.property(agentListArb, (agents) => {
            const { container } = renderRowsContainer(agents);
            const rows = container.querySelectorAll('tr');

            // One row per agent, no header row in this helper's output.
            assert.strictEqual(
                rows.length, agents.length,
                'expected one <tr> per agent (no header row from renderAgentInstanceRows)'
            );

            // Input order preserved: the first cell holds the (escaped) id, so
            // the rendered id text must equal the input id coerced to string.
            for (let i = 0; i < agents.length; i++) {
                const expectedId = agents[i].id === undefined || agents[i].id === null
                    ? '' : String(agents[i].id);
                const firstCell = rows[i].children[0];
                const actualId = firstCell ? (firstCell.textContent || '') : '';
                assert.strictEqual(
                    actualId, expectedId,
                    'row ' + i + ' is out of order: id cell "' + actualId
                        + '" !== expected "' + expectedId + '"'
                );
            }
        }),
        { numRuns: 300 }
    );
});

test('Property A: renderAgentInstanceRows never emits an unescaped <script> (XSS-safe)', () => {
    fc.assert(
        fc.property(agentListArb, (agents) => {
            const { rowsHtml } = renderRowsContainer(agents);
            // The raw emitted markup must never contain a literal opening
            // <script tag — all attacker-controlled cell values are escaped.
            assert.ok(
                !/<script/i.test(rowsHtml),
                'rendered rows contain an unescaped <script> tag: ' + rowsHtml
            );
        }),
        { numRuns: 300 }
    );
});

test('Property A: each control is disabled iff lifecycleControlState says it is not enabled', () => {
    fc.assert(
        fc.property(agentListArb, (agents) => {
            const { container } = renderRowsContainer(agents);
            const rows = container.querySelectorAll('tr');

            for (let i = 0; i < agents.length; i++) {
                const status = agents[i].status === undefined || agents[i].status === null
                    ? '' : String(agents[i].status);
                const state = lifecycleControlState(status);
                const byOp = controlsForRow(rows[i]);

                for (const op of ['start', 'stop', 'restart']) {
                    const btn = byOp[op];
                    assert.ok(btn, 'row ' + i + ' missing a ' + op + ' control');
                    // disabled attribute present iff the control is NOT enabled.
                    const hasDisabled = btn.hasAttribute('disabled');
                    assert.strictEqual(
                        hasDisabled, !state[op],
                        'row ' + i + ' (' + status + '): ' + op
                            + ' disabled=' + hasDisabled
                            + ' but mapping enabled=' + state[op]
                    );
                }
            }
        }),
        { numRuns: 300 }
    );
});

// ===========================================================================
// Property B — lifecycleControlState enables only legal transitions (Req 2.5).
// ===========================================================================

test('Property B: lifecycleControlState enables a control only for a legally-permitted state', () => {
    fc.assert(
        fc.property(statusArb, (status) => {
            const s = status === undefined || status === null ? '' : String(status);
            const state = lifecycleControlState(s);

            for (const op of ['start', 'stop', 'restart']) {
                if (state[op]) {
                    // If enabled, the state MUST be in the documented legal set.
                    assert.ok(
                        LEGAL[op].has(s),
                        op + ' enabled for illegal state "' + s + '"'
                    );
                }
            }
            // Returns exactly the three boolean flags.
            assert.deepStrictEqual(
                Object.keys(state).sort(),
                ['restart', 'start', 'stop'],
                'lifecycleControlState must return { start, stop, restart }'
            );
        }),
        { numRuns: 500 }
    );
});

test('Property B: every legal state enables its control (coverage of the forward direction)', () => {
    // Complements the above: for each documented legal state, the matching
    // control must be enabled. Keeps the mapping from trivially disabling all.
    for (const op of ['start', 'stop', 'restart']) {
        for (const s of LEGAL[op]) {
            const state = lifecycleControlState(s);
            assert.ok(
                state[op],
                op + ' must be enabled for legal state "' + s + '"'
            );
        }
    }
});
