'use strict';

/**
 * Drift-guard test for the Agent Management undefined-functions bugfix
 * (Task 3.2, design Option A — recommended).
 *
 * Root cause of the bug: the served copy of the dashboard script
 * (static/js/dashboard_functions.js) drifted from the source-of-truth copy
 * (templates/dashboard_functions.js). The served copy went stale (1551 lines)
 * and lost the Agent Management panel globals (AM_PANELS, showAmPanel,
 * amRenderTable, loadAgentManagement, loadAm*), so the browser threw
 * "Uncaught ReferenceError: loadAgentManagement is not defined".
 *
 * Task 3.1 synced the served copy to the source so the two files are now
 * byte-for-byte identical. This test locks that in: it reads both files and
 * asserts their contents are identical, failing CI the moment they diverge
 * again. That keeps the served Agent Management globals from silently
 * disappearing a second time.
 *
 * This is the lowest-friction guard for a repo with no JS build pipeline: it
 * needs no build tooling and runs under the existing Node test runner.
 *
 * Source of truth: templates/dashboard_functions.js
 *
 * Requirements: 2.4
 */

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

// The file the browser actually executes (served via
// url_for('static', filename='js/dashboard_functions.js')).
const SERVED_JS = path.resolve(
    __dirname,
    '..',
    '..',
    'static',
    'js',
    'dashboard_functions.js'
);

// The single source of truth the Node/jsdom test harness requires.
const SOURCE_JS = path.resolve(
    __dirname,
    '..',
    '..',
    'templates',
    'dashboard_functions.js'
);

test('served and source dashboard scripts are byte-for-byte identical (Req 2.4)', () => {
    const servedSrc = fs.readFileSync(SERVED_JS, 'utf8');
    const sourceSrc = fs.readFileSync(SOURCE_JS, 'utf8');

    const servedLines = servedSrc.split('\n').length;
    const sourceLines = sourceSrc.split('\n').length;

    assert.strictEqual(
        servedSrc,
        sourceSrc,
        'DRIFT DETECTED: static/js/dashboard_functions.js (served, ' +
            servedLines +
            ' lines) has diverged from the source of truth ' +
            'templates/dashboard_functions.js (' +
            sourceLines +
            ' lines). The served copy is what the browser executes; if it ' +
            'falls behind, the Agent Management globals (loadAgentManagement, ' +
            'showAmPanel, AM_PANELS, amRenderTable, loadAm*) can silently ' +
            'disappear and the dashboard will throw ReferenceError again. ' +
            'Re-sync by copying templates/dashboard_functions.js (the source ' +
            'of truth) over static/js/dashboard_functions.js.'
    );
});
