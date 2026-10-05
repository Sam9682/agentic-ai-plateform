'use strict';

/**
 * Smoke checks for the single reusable Sort_Helper interface (task 9.3).
 *
 * These verify that:
 *   - exactly one `makeSortable` function is declared in
 *     templates/dashboard_functions.js (the single reusable interface,
 *     Requirement 6.1 — the implementation lives once in that file), and
 *   - that same helper is the function invoked by every wired render function
 *     in templates/dashboard.html (Requirement 5.3 — one interface used by both
 *     the fixed-column tables and the generic Database Management table).
 *
 * The checks read the template files as text (they are Jinja-templated HTML/JS,
 * not requireable modules) and assert structural facts, plus confirm the
 * exported `sortHelper.makeSortable` interface is a single callable function.
 *
 * Requirements: 5.3, 6.1
 */

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const { sortHelper } = require('./harness');

const TEMPLATES_DIR = path.resolve(__dirname, '..', '..', 'templates');
const FUNCTIONS_JS = path.join(TEMPLATES_DIR, 'dashboard_functions.js');
const DASHBOARD_HTML = path.join(TEMPLATES_DIR, 'dashboard.html');

// The render functions that the design wires the helper into. `makeSortable`
// must be invoked at least once per wired panel; loadAppManagement and
// loadAvailableApplications both render an applications table.
const WIRED_PANELS = [
    'loadUsers',
    'loadServers',
    'loadAppManagement',
    'loadAvailableApplications',
    'loadBillingSummary',
    'loadBillingActivities',
    'loadInvoices',
    'loadDeploymentsTable',
    'displayTableData',
];

function readTemplate(file) {
    return fs.readFileSync(file, 'utf8');
}

function countOccurrences(haystack, pattern) {
    const matches = haystack.match(pattern);
    return matches ? matches.length : 0;
}

test('exactly one makeSortable function is declared in dashboard_functions.js', () => {
    const source = readTemplate(FUNCTIONS_JS);
    const declarations = countOccurrences(source, /function\s+makeSortable\s*\(/g);
    assert.strictEqual(
        declarations,
        1,
        'expected a single `function makeSortable(` declaration, found ' + declarations
    );
});

test('the single exported sortHelper.makeSortable interface is a function', () => {
    assert.strictEqual(
        typeof sortHelper.makeSortable,
        'function',
        'expected sortHelper.makeSortable to be exported as a function'
    );
});

test('makeSortable is invoked in dashboard.html by the wired render functions', () => {
    const html = readTemplate(DASHBOARD_HTML);

    // The helper must be called; count the call sites (invocations, excluding
    // any bare declaration — dashboard.html contains no declaration).
    const callSites = countOccurrences(html, /makeSortable\s*\(/g);
    assert.ok(
        callSites >= WIRED_PANELS.length,
        'expected at least ' + WIRED_PANELS.length + ' makeSortable(...) call sites in ' +
            'dashboard.html (one per wired panel), found ' + callSites
    );

    // dashboard.html invokes the helper but does not re-declare it: the single
    // implementation stays in dashboard_functions.js (Requirement 6.1).
    const declarationsInHtml = countOccurrences(html, /function\s+makeSortable\s*\(/g);
    assert.strictEqual(
        declarationsInHtml,
        0,
        'makeSortable must not be re-declared in dashboard.html; it is the single ' +
            'reusable helper defined in dashboard_functions.js'
    );
});

test('the deployments table wiring excludes the listbox columns', () => {
    const html = readTemplate(DASHBOARD_HTML);
    // loadDeploymentsTable wires the helper with excludeColumns for the two
    // <select> listbox columns (Modification History / Backups History).
    assert.match(
        html,
        /excludeColumns\s*:\s*\[\s*9\s*,\s*10\s*\]/,
        'expected a makeSortable(..., { excludeColumns: [9, 10] }) call for the ' +
            'deployments table'
    );
    // and confirm that exclusion is passed to makeSortable specifically.
    assert.match(
        html,
        /makeSortable\([\s\S]*?excludeColumns/,
        'the excludeColumns option must be passed into a makeSortable(...) call'
    );
});
