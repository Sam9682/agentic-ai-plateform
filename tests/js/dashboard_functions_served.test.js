'use strict';

/**
 * Bug condition exploration tests for the Agent Management undefined-functions
 * bugfix (Task 1).
 *
 * These tests load the SERVED copy of the dashboard script
 * (static/js/dashboard_functions.js) — the file the browser actually executes
 * via url_for('static', filename='js/dashboard_functions.js') — and assert that
 * the Agent Management panel globals are defined and invokable.
 *
 * CRITICAL: On the UNFIXED code these tests are EXPECTED TO FAIL. The served
 * copy is a stale snapshot (1551 lines) that ends after wireAgentEvidenceTooltip
 * and never defines AM_PANELS / showAmPanel / amRenderTable / loadAgentManagement
 * / the loadAm* loaders, while the source-of-truth templates/dashboard_functions.js
 * (1857 lines) does. A failing test here is the correct outcome: it confirms the
 * bug (script drift — stale served copy missing the Agent Management globals).
 *
 * These assertions encode the Expected Behavior (design Property 1 / Correctness
 * Properties) and will validate the fix once the served copy is synced to the
 * source and they pass.
 *
 * Bug Condition (bugfix.md):
 *   isBugCondition(X) = NOT isDefined(X, 'loadAgentManagement')
 *                    OR NOT isDefined(X, 'showAmPanel')
 *                    OR NOT isDefined(X, 'AM_PANELS')
 *                    OR NOT isDefined(X, 'amRenderTable')
 *
 * Requirements: 1.1, 1.2, 1.3, 1.4
 */

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM } = require('jsdom');

// Spin up a jsdom environment and publish the usual browser globals so that the
// served dashboard script (and any DOM-building helper it defines) can run.
// This mirrors the setup in tests/js/harness.js, but points require() at the
// SERVED static copy instead of the templates source-of-truth copy.
const dom = new JSDOM('<!DOCTYPE html><html><body></body></html>', {
    url: 'http://localhost/',
});
const { window } = dom;
const { document } = window;

global.window = window;
global.document = document;
if (!global.Node) global.Node = window.Node;
if (!global.HTMLElement) global.HTMLElement = window.HTMLElement;
// fetch is referenced by the loadAm* loaders; provide a no-op stub so invoking
// a loader does not throw for a missing fetch (the point of these tests is the
// ReferenceError on the undefined globals, not network behavior).
if (!global.fetch) {
    global.fetch = () =>
        Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve([]) });
}

const STATIC_JS = path.resolve(
    __dirname,
    '..',
    '..',
    'static',
    'js',
    'dashboard_functions.js'
);
const TEMPLATES_JS = path.resolve(
    __dirname,
    '..',
    '..',
    'templates',
    'dashboard_functions.js'
);

// Load the served copy through its module.exports guard, exactly as the harness
// loads the templates copy. The exported set is the runtime contract the browser
// gets; on the unfixed served file it omits the Agent Management globals.
const served = require(STATIC_JS);

const LOAD_AM_LOADERS = [
    'loadAmDashboard',
    'loadAmRuntimes',
    'loadAmInstances',
    'loadAmTasks',
    'loadAmPolicies',
    'loadAmMcp',
    'loadAmApprovals',
    'loadAmObservability',
    'loadAmIncidents',
];

// Test case 1 — Bug Condition: isDefined(input, 'loadAgentManagement')
test('served script defines loadAgentManagement (Req 1.1, 2.1)', () => {
    assert.strictEqual(
        typeof served.loadAgentManagement,
        'function',
        'EXPECTED-FAIL-ON-UNFIXED: the served static/js/dashboard_functions.js ' +
            'must define loadAgentManagement as a function; on the stale served ' +
            'copy it is undefined, which is why the Agent Management tab throws ' +
            '"Uncaught ReferenceError: loadAgentManagement is not defined".'
    );
});

// Test case 2 — Bug Condition: isDefined(input, 'showAmPanel') and
// isDefined(input, 'AM_PANELS'); showAmPanel('dashboard') must not ReferenceError.
test('served script defines showAmPanel and AM_PANELS, and showAmPanel runs (Req 1.2, 2.2)', () => {
    assert.strictEqual(
        typeof served.showAmPanel,
        'function',
        'EXPECTED-FAIL-ON-UNFIXED: served script must define showAmPanel; the ' +
            'stale copy omits it, so sub-nav onclick="showAmPanel(...)" throws ' +
            'ReferenceError.'
    );
    assert.notStrictEqual(
        typeof served.AM_PANELS,
        'undefined',
        'EXPECTED-FAIL-ON-UNFIXED: served script must define AM_PANELS; the stale ' +
            'copy omits it.'
    );
    assert.doesNotThrow(() => {
        served.showAmPanel('dashboard');
    }, ReferenceError,
        'EXPECTED-FAIL-ON-UNFIXED: invoking showAmPanel("dashboard") must not ' +
            'throw a ReferenceError once the served globals are defined.');
});

// Test case 3 — Bug Condition: isDefined(input, 'amRenderTable') plus the loadAm* loaders.
test('served script defines amRenderTable and all loadAm* loaders (Req 1.1, 1.4, 2.4)', () => {
    assert.strictEqual(
        typeof served.amRenderTable,
        'function',
        'EXPECTED-FAIL-ON-UNFIXED: served script must define amRenderTable; the ' +
            'stale copy omits it.'
    );
    for (const name of LOAD_AM_LOADERS) {
        assert.strictEqual(
            typeof served[name],
            'function',
            'EXPECTED-FAIL-ON-UNFIXED: served script must define ' + name +
                ' as a function; the stale copy omits it.'
        );
    }
});

// Test case 4 (edge case) — Expected Behavior: after the fix the served copy and
// the source-of-truth copy are identical (drift eliminated). On the UNFIXED code
// they differed (1551 vs 1857 lines); the fix (task 3.1) syncs the served copy to
// the source, so the two files must now be byte-for-byte identical.
test('served and templates dashboard scripts are identical — drift eliminated (Req 2.4)', () => {
    const servedSrc = fs.readFileSync(STATIC_JS, 'utf8');
    const templatesSrc = fs.readFileSync(TEMPLATES_JS, 'utf8');
    const servedLines = servedSrc.split('\n').length;
    const templatesLines = templatesSrc.split('\n').length;
    // Post-fix Expected Behavior: the served copy is synced to the source of
    // truth, so the two files no longer differ. The drift-guard test
    // (tests/js/dashboard_functions_sync.test.js, task 3.2) enforces this going
    // forward.
    assert.strictEqual(
        servedSrc,
        templatesSrc,
        'EXPECTED-IDENTICAL-POST-FIX: the served copy (' + servedLines + ' lines) ' +
            'and the source-of-truth templates copy (' + templatesLines + ' lines) ' +
            'must be byte-for-byte identical after the sync; any difference means ' +
            'the drift returned. served lines=' +
            servedLines + ', templates lines=' + templatesLines
    );
});
