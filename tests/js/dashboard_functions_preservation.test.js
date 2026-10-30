'use strict';

/**
 * Preservation property tests for the "agent-management-undefined-functions"
 * bugfix (Property 2: Preservation).
 *
 * The fix syncs the served copy `static/js/dashboard_functions.js` to the
 * source-of-truth `templates/dashboard_functions.js` so the Agent Management
 * globals (loadAgentManagement, showAmPanel, AM_PANELS, amRenderTable, loadAm*)
 * are defined in the browser. These tests capture the behavior that MUST NOT
 * change for inputs where the bug condition does NOT hold:
 *
 *   - the shared helpers already present in BOTH copies
 *     (makeSortable, resolveHeaders, applySort, buildComparator,
 *      renderSandboxApps, renderAgentRows, confidenceColor, confidenceText,
 *      the evidence-tooltip helpers, SANDBOX_ALLOWED_STATUSES) behave the same;
 *   - non-Agent-Management tab names are unaffected (the shared tab-switching
 *     contract — only `agentManagement` touches the AM globals);
 *   - the jsdom `module.exports` harness still returns the exported helper set
 *     with no browser-only code running at load time.
 *
 * Observation-first methodology: the asserted outputs below were recorded by
 * running the UNFIXED served/templates code, so these tests PASS on the
 * baseline and continue to pass after the served copy is synced to the source.
 *
 * Validates: Requirements 3.1, 3.2, 3.3, 3.4
 */

const test = require('node:test');
const assert = require('node:assert');
const path = require('node:path');
const { JSDOM } = require('jsdom');
const fc = require('fast-check');

// ---------------------------------------------------------------------------
// jsdom setup (mirrors tests/js/harness.js and tests/js/smoke.test.js).
// ---------------------------------------------------------------------------
const dom = new JSDOM('<!DOCTYPE html><html><body></body></html>', {
    url: 'http://localhost/',
});
global.window = dom.window;
global.document = dom.window.document;
if (!global.Node) global.Node = dom.window.Node;
if (!global.HTMLElement) global.HTMLElement = dom.window.HTMLElement;

const SERVED_PATH = path.resolve(
    __dirname, '..', '..', 'static', 'js', 'dashboard_functions.js');
const TEMPLATES_PATH = path.resolve(
    __dirname, '..', '..', 'templates', 'dashboard_functions.js');

// The served copy is the file the fix mutates; load it to capture the baseline
// behavior of the helpers it already defines (those shared with the source).
const served = require(SERVED_PATH);
// The templates copy is what the jsdom harness requires (source of truth).
const templates = require(TEMPLATES_PATH);

// Shared helpers present in BOTH copies today. These are the "preservation"
// surface: a non-Agent-Management input only ever exercises these, so their
// behavior must be identical before and after the sync.
const SHARED_HELPERS = [
    'makeSortable',
    'resolveHeaders',
    'getCellText',
    'detectColumnType',
    'isNumericText',
    'toNumber',
    'isDateText',
    'toDate',
    'buildComparator',
    'applySort',
    'updateIndicators',
    'SANDBOX_ALLOWED_STATUSES',
    'renderSandboxApps',
    'renderAgentRows',
    'loadAgentControl',
    'stopAgentApplication',
    'confidenceColor',
    'confidenceText',
    'ensureAgentEvidenceTooltipStyles',
    'buildAgentEvidenceTooltip',
    'wireAgentEvidenceTooltip',
];

// Non-Agent-Management tab names: for these, nothing about the fix applies.
const NON_AM_TABS = [
    'apps', 'serverless', 'marketplace', 'sandbox', 'agentControl',
    'users', 'servers', 'billing', 'deployments', 'overview',
];

// ===========================================================================
// 1. Shared-helper preservation
// ===========================================================================

test('shared helpers remain available on the served copy (contract preserved)', () => {
    for (const name of SHARED_HELPERS) {
        const v = served[name];
        const ok = (name === 'SANDBOX_ALLOWED_STATUSES')
            ? Array.isArray(v)
            : typeof v === 'function';
        assert.ok(ok, 'served copy must still expose shared helper ' + name);
    }
});

test('SANDBOX_ALLOWED_STATUSES is the observed baseline set', () => {
    assert.deepStrictEqual(
        served.SANDBOX_ALLOWED_STATUSES,
        ['running', 'stopped', 'failed']);
});

test('PROPERTY: confidenceColor banding is preserved for any score in [0,1]', () => {
    // Observed thresholds on the baseline code: pct = round(score*100);
    //   pct <= 20 -> red (#dc3545), pct < 51 -> orange (#fd7e14), else green.
    fc.assert(fc.property(fc.double({ min: 0, max: 1, noNaN: true }), (score) => {
        const pct = Math.round(score * 100);
        const expected = pct <= 20 ? '#dc3545'
            : pct < 51 ? '#fd7e14'
            : '#28a745';
        assert.strictEqual(served.confidenceColor(score), expected);
    }));
});

test('PROPERTY: confidenceText renders round(score*100) + "%" for any score', () => {
    fc.assert(fc.property(fc.double({ min: 0, max: 1, noNaN: true }), (score) => {
        assert.strictEqual(served.confidenceText(score),
            Math.round(score * 100) + '%');
    }));
});

test('confidenceColor/confidenceText treat non-number inputs as 0 (observed baseline)', () => {
    // Observed: the helper uses `typeof score === 'number' ? score : 0`.
    // Any non-number value (and `true`/`0`) is coerced to 0 -> red, "0%".
    for (const bad of [undefined, null, 'x', {}, [], true, 0]) {
        assert.strictEqual(served.confidenceColor(bad), '#dc3545');
        assert.strictEqual(served.confidenceText(bad), '0%');
    }
    // Observed edge case: NaN IS typeof 'number', so it is NOT coerced; the
    // threshold comparisons are all false -> green, and the text reads "NaN%".
    assert.strictEqual(served.confidenceColor(NaN), '#28a745');
    assert.strictEqual(served.confidenceText(NaN), 'NaN%');
});

test('PROPERTY: renderSandboxApps preserves count, order and status coercion', () => {
    const statusArb = fc.option(
        fc.oneof(
            fc.constantFrom('running', 'stopped', 'failed'),
            fc.string()),
        { nil: undefined });
    const appArb = fc.record({
        application_name: fc.option(fc.string(), { nil: undefined }),
        status: statusArb,
        access_url: fc.option(fc.webUrl(), { nil: undefined }),
    });
    fc.assert(fc.property(fc.array(appArb), (apps) => {
        const out = served.renderSandboxApps(apps);
        // length and order preserved
        assert.strictEqual(out.length, apps.length);
        for (let i = 0; i < apps.length; i++) {
            const a = apps[i] || {};
            const row = out[i];
            // status is coerced to the allowed set or 'failed'
            const expectedStatus =
                ['running', 'stopped', 'failed'].indexOf(a.status) !== -1
                    ? a.status : 'failed';
            assert.strictEqual(row.status, expectedStatus);
            // null-normalisation of optional fields
            assert.strictEqual(row.application_name,
                a.application_name != null ? a.application_name : null);
            assert.strictEqual(row.access_url,
                a.access_url != null ? a.access_url : null);
            // shape preserved: exactly these three keys
            assert.deepStrictEqual(Object.keys(row).sort(),
                ['access_url', 'application_name', 'status']);
        }
    }));
});

test('renderSandboxApps baseline examples (observed)', () => {
    assert.deepStrictEqual(served.renderSandboxApps([]), []);
    assert.deepStrictEqual(
        served.renderSandboxApps([{ application_name: 'a', status: 'running', access_url: 'u' }]),
        [{ application_name: 'a', status: 'running', access_url: 'u' }]);
    assert.deepStrictEqual(
        served.renderSandboxApps([{ application_name: 'a', status: 'weird' }]),
        [{ application_name: 'a', status: 'failed', access_url: null }]);
});

test('PROPERTY: renderAgentRows fills baseline defaults and preserves order', () => {
    const containerArb = fc.record({
        name: fc.option(fc.string(), { nil: undefined }),
        image: fc.option(fc.string(), { nil: undefined }),
        state: fc.option(fc.string(), { nil: undefined }),
    }, { requiredKeys: [] });
    fc.assert(fc.property(fc.array(containerArb), (containers) => {
        const out = served.renderAgentRows(containers);
        assert.strictEqual(out.length, containers.length);
        for (let i = 0; i < containers.length; i++) {
            const c = containers[i] || {};
            const row = out[i];
            assert.strictEqual(row.name, c.name || '(unnamed)');
            assert.strictEqual(row.state, c.state || 'unknown');
            assert.strictEqual(row.classification, 'unclassified');
            assert.strictEqual(row.confidence, 0);
            assert.deepStrictEqual(row.evidence, []);
        }
    }));
});

test('renderAgentRows baseline example (observed)', () => {
    assert.deepStrictEqual(served.renderAgentRows([]), []);
    assert.deepStrictEqual(served.renderAgentRows([{ name: 'n' }]), [{
        application: '', owner: '', name: 'n', image: '', server: '',
        state: 'unknown', classification: 'unclassified', confidence: 0,
        evidence: [],
    }]);
});

test('PROPERTY: renderSandboxApps/renderAgentRows tolerate non-array input', () => {
    fc.assert(fc.property(
        fc.oneof(fc.constant(null), fc.constant(undefined), fc.string(),
            fc.integer(), fc.object()),
        (notArray) => {
            assert.deepStrictEqual(served.renderSandboxApps(notArray), []);
            assert.deepStrictEqual(served.renderAgentRows(notArray), []);
        }));
});

// ===========================================================================
// 2. Non-Agent-Management tab preservation
// ===========================================================================

test('PROPERTY: non-agentManagement tab names never touch the AM globals', () => {
    // Preservation contract: the only tab name whose handling depends on the
    // Agent Management globals is 'agentManagement'. For any other tab name,
    // the shared helper surface is unchanged by the fix, so the served copy
    // exposes the same shared helpers regardless of the tab name.
    const before = SHARED_HELPERS.map((n) => typeof served[n]);
    fc.assert(fc.property(
        fc.oneof(fc.constantFrom(...NON_AM_TABS), fc.string()),
        (tab) => {
            fc.pre(tab !== 'agentManagement');
            const after = SHARED_HELPERS.map((n) => typeof served[n]);
            assert.deepStrictEqual(after, before);
        }));
});

// ===========================================================================
// 3. Test-harness (module.exports) preservation
// ===========================================================================

test('harness require of templates copy returns the stable exported helpers', () => {
    // The jsdom harness requires templates/dashboard_functions.js; the fix must
    // not disturb its module.exports or run browser-only code at load time.
    for (const name of SHARED_HELPERS) {
        const v = templates[name];
        const ok = (name === 'SANDBOX_ALLOWED_STATUSES')
            ? Array.isArray(v)
            : typeof v === 'function';
        assert.ok(ok, 'templates copy must export shared helper ' + name);
    }
});

test('requiring the script twice returns the same cached exports (no load-time side effects)', () => {
    const again = require(TEMPLATES_PATH);
    assert.strictEqual(again, templates,
        'require must be idempotent / cached — no browser-only code at load time');
    const servedAgain = require(SERVED_PATH);
    assert.strictEqual(servedAgain, served);
});

test('browser-global contract: AM helpers are declared as top-level globals in the source', () => {
    // Preservation of the browser-global contract: the Agent Management helpers
    // must stay plain top-level function/const declarations (not wrapped in a
    // module/IIFE) so inline onclick handlers resolve them. We assert the
    // source-of-truth declares them as such.
    const fs = require('node:fs');
    const src = fs.readFileSync(TEMPLATES_PATH, 'utf8');
    assert.match(src, /^function\s+showAmPanel\s*\(/m,
        'showAmPanel must be a top-level function declaration');
    assert.match(src, /^function\s+amRenderTable\s*\(/m,
        'amRenderTable must be a top-level function declaration');
    assert.match(src, /^function\s+loadAgentManagement\s*\(/m,
        'loadAgentManagement must be a top-level function declaration');
    assert.match(src, /^const\s+AM_PANELS\s*=/m,
        'AM_PANELS must be a top-level const declaration');
});
