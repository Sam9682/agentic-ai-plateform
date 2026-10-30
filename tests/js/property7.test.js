'use strict';

/**
 * Preservation property tests for the "agent-lifecycle-controls" bugfix
 * (Property 2: Preservation).
 *
 * The fix adds per-agent Start/Stop/Restart controls to the Agent Management
 * "Instances" panel. It introduces a dedicated Instances renderer and a POST
 * helper, and rewires loadAmInstances() to use them — but it MUST NOT change
 * anything outside the Instances lifecycle controls. In particular:
 *
 *   - the shared amRenderTable() helper is NOT modified and keeps rendering
 *     every consumer table (runtimes, tasks, policies, mcp, approvals,
 *     observability, incidents) byte-for-byte as before;
 *   - the seven amRenderTable-backed loadAm* loaders keep fetching their
 *     existing endpoints and passing their existing column sets;
 *   - loadAmInstances() keeps calling GET /api/v1/agents/ and keeps showing the
 *     ID/Identity/Name/Status columns;
 *   - the Instances empty-state ("No agents registered.") and error-state
 *     ("Failed to load (…).") messages are preserved;
 *   - the jsdom module.exports harness contract is preserved: requiring the
 *     module is idempotent and runs no browser-only code at load time.
 *
 * Observation-first methodology: every asserted output below was recorded by
 * running the UNFIXED templates code (see the inline "observed" notes), so
 * these tests PASS on the baseline and must continue to pass after the fix.
 *
 * Property-based testing with fast-check (already a dev dependency) generates
 * many agent lists and statuses to give a strong guarantee that non-bug inputs
 * are unchanged.
 *
 * Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 2.6
 */

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const fc = require('fast-check');

const { document, sortHelper } = require('./harness');

const TEMPLATES_PATH = path.resolve(
    __dirname, '..', '..', 'templates', 'dashboard_functions.js');

// ---------------------------------------------------------------------------
// Baseline reference implementations.
//
// These re-implement the UNFIXED amRenderTable() and escapeHtml() behavior
// exactly as observed in templates/dashboard_functions.js at the time this
// preservation suite was written. They are the golden model: a property test
// asserts the live amRenderTable() output equals this reference for random
// inputs. Because the fix does NOT touch amRenderTable(), the equality must
// continue to hold after the fix.
// ---------------------------------------------------------------------------

function refEscapeHtml(text) {
    // Mirrors escapeHtml(): append a text node and read innerHTML. Using the
    // same jsdom document keeps entity encoding identical to the live helper.
    const div = document.createElement('div');
    div.appendChild(document.createTextNode(text));
    return div.innerHTML;
}

function refAmRenderTable(columns, rows, emptyMsg) {
    // Returns the innerHTML amRenderTable() writes into its container, for the
    // three branches: __error, empty, and a populated table. Observed verbatim
    // from the unfixed source.
    if (rows && rows.__error) {
        return '<p style="color:red;">Failed to load ('
            + refEscapeHtml(String(rows.__error)) + ').</p>';
    }
    const list = Array.isArray(rows) ? rows : [];
    if (list.length === 0) {
        return '<p style="color:orange;">'
            + refEscapeHtml(emptyMsg || 'Nothing to show.') + '</p>';
    }
    let html = '<table style="width:100%; border-collapse:collapse;">'
        + '<tr style="border-bottom:1px solid #ddd;">';
    for (const c of columns) {
        html += '<th style="text-align:left; padding:5px;">'
            + refEscapeHtml(c.label) + '</th>';
    }
    html += '</tr>';
    for (const row of list) {
        html += '<tr style="border-bottom:1px solid #eee;">';
        for (const c of columns) {
            const v = row[c.key];
            html += '<td style="padding:5px;">'
                + refEscapeHtml(v === undefined || v === null ? '' : String(
                    typeof v === 'object' ? JSON.stringify(v) : v)) + '</td>';
        }
        html += '</tr>';
    }
    html += '</table>';
    return html;
}

/**
 * Render through the LIVE amRenderTable() into a scratch container and return
 * the resulting innerHTML. jsdom normalizes the markup (e.g. it wraps rows in a
 * <tbody>), so we normalize the reference model the same way by assigning it to
 * a throwaway element's innerHTML and reading it back.
 */
function liveRender(columns, rows, emptyMsg) {
    const c = document.createElement('div');
    c.id = '__amPreservationScratch';
    document.body.appendChild(c);
    try {
        sortHelper.amRenderTable('__amPreservationScratch', columns, rows, emptyMsg);
        return c.innerHTML;
    } finally {
        c.remove();
    }
}

function normalize(html) {
    // Round-trip the string through a detached element so the reference model
    // and the live output are compared after identical DOM normalization.
    const d = document.createElement('div');
    d.innerHTML = html;
    return d.innerHTML;
}

// ===========================================================================
// 1. amRenderTable() is unmodified — identical output for random inputs
//    (Req 3.4; underpins the seven other panels in Req 3.1).
// ===========================================================================

// Column sets actually used by the seven amRenderTable-backed panels plus the
// Instances columns, so the property exercises the real key/label shapes.
const COLUMN_SETS = [
    // runtimes
    [{ key: 'identifier', label: 'Identifier' }, { key: 'name', label: 'Name' },
     { key: 'version', label: 'Version' }, { key: 'supported_protocols', label: 'Protocols' },
     { key: 'status', label: 'Status' }],
    // tasks
    [{ key: 'task_ref', label: 'Task' }, { key: 'operation', label: 'Operation' },
     { key: 'status', label: 'Status' }],
    // policies
    [{ key: 'name', label: 'Name' }, { key: 'version', label: 'Version' },
     { key: 'scope', label: 'Scope' }, { key: 'enabled', label: 'Enabled' }],
    // mcp
    [{ key: 'action', label: 'Action' }, { key: 'resource', label: 'Resource' },
     { key: 'decision', label: 'Decision' }, { key: 'decided_at', label: 'When' }],
    // approvals
    [{ key: 'id', label: 'ID' }, { key: 'action', label: 'Action' },
     { key: 'resource', label: 'Resource' }, { key: 'status', label: 'Status' }],
    // observability
    [{ key: 'event_type', label: 'Event' }, { key: 'agent_id', label: 'Agent' },
     { key: 'decision', label: 'Decision' }, { key: 'severity', label: 'Severity' },
     { key: 'occurred_at', label: 'When' }],
    // incidents
    [{ key: 'id', label: 'ID' }, { key: 'kind', label: 'Kind' },
     { key: 'severity', label: 'Severity' }, { key: 'summary', label: 'Summary' },
     { key: 'status', label: 'Status' }],
    // instances
    [{ key: 'id', label: 'ID' }, { key: 'identity', label: 'Identity' },
     { key: 'name', label: 'Name' }, { key: 'status', label: 'Status' }],
];

// A cell-value generator covering strings (incl. XSS-y / entity-y text),
// numbers, booleans, null/undefined, and nested objects (which amRenderTable
// JSON.stringifies). These are the value shapes real panels feed in.
const cellValueArb = fc.oneof(
    fc.string(),
    fc.constantFrom('<script>alert(1)</script>', '<b>&amp;</b>', 'a & b', '"q"', "<>"),
    fc.integer(),
    fc.boolean(),
    fc.constant(null),
    fc.constant(undefined),
    fc.object({ maxDepth: 2 }));

function rowArbForColumns(columns) {
    // Build an object row with a random subset/overlap of the column keys plus
    // occasional extra keys that the renderer must ignore.
    const keys = columns.map((c) => c.key);
    return fc.dictionary(
        fc.oneof(fc.constantFrom(...keys), fc.string()),
        cellValueArb);
}

test('PROPERTY: amRenderTable renders populated tables identically to the baseline model (Req 3.4)', () => {
    fc.assert(fc.property(
        fc.integer({ min: 0, max: COLUMN_SETS.length - 1 }),
        fc.array(fc.integer({ min: 0, max: COLUMN_SETS.length - 1 }), { minLength: 1, maxLength: 6 }),
        fc.string(),
        (colIdx, _rowSel, emptyMsg) => {
            const columns = COLUMN_SETS[colIdx];
            return fc.assert(fc.property(
                fc.array(rowArbForColumns(columns), { minLength: 1, maxLength: 6 }),
                (rows) => {
                    const live = normalize(liveRender(columns, rows, emptyMsg));
                    const ref = normalize(refAmRenderTable(columns, rows, emptyMsg));
                    assert.strictEqual(live, ref,
                        'amRenderTable output must match the unmodified baseline model');
                }), { numRuns: 20 });
        }), { numRuns: 20 });
});

test('PROPERTY: amRenderTable empty-state matches the baseline model for any columns/message (Req 3.3, 3.4)', () => {
    fc.assert(fc.property(
        fc.integer({ min: 0, max: COLUMN_SETS.length - 1 }),
        fc.string(),
        (colIdx, emptyMsg) => {
            const columns = COLUMN_SETS[colIdx];
            const live = normalize(liveRender(columns, [], emptyMsg));
            const ref = normalize(refAmRenderTable(columns, [], emptyMsg));
            assert.strictEqual(live, ref);
        }), { numRuns: 100 });
});

test('PROPERTY: amRenderTable error-state matches the baseline model for any __error (Req 3.3, 3.4)', () => {
    const errArb = fc.oneof(
        fc.integer({ min: 100, max: 599 }),
        fc.constantFrom('network', 'timeout'),
        fc.string({ minLength: 1 }));
    fc.assert(fc.property(
        fc.integer({ min: 0, max: COLUMN_SETS.length - 1 }),
        errArb,
        (colIdx, err) => {
            const columns = COLUMN_SETS[colIdx];
            const live = normalize(liveRender(columns, { __error: err }, 'ignored'));
            const ref = normalize(refAmRenderTable(columns, { __error: err }, 'ignored'));
            assert.strictEqual(live, ref);
        }), { numRuns: 100 });
});

// ===========================================================================
// 2. Other render helpers unchanged (shared with the preservation surface).
//    renderSandboxApps / renderAgentRows are pure helpers the fix never
//    touches; a property asserts their documented baseline invariants hold.
//    (Req 3.1 — non-Instances rendering behavior is preserved.)
// ===========================================================================

test('PROPERTY: renderSandboxApps preserves count, order and status coercion (Req 3.1)', () => {
    const appArb = fc.record({
        application_name: fc.option(fc.string(), { nil: undefined }),
        status: fc.option(fc.oneof(
            fc.constantFrom('running', 'stopped', 'failed'), fc.string()), { nil: undefined }),
        access_url: fc.option(fc.webUrl(), { nil: undefined }),
    });
    fc.assert(fc.property(fc.array(appArb), (apps) => {
        const out = sortHelper.renderSandboxApps(apps);
        assert.strictEqual(out.length, apps.length);
        for (let i = 0; i < apps.length; i++) {
            const a = apps[i] || {};
            const expectedStatus =
                ['running', 'stopped', 'failed'].indexOf(a.status) !== -1
                    ? a.status : 'failed';
            assert.strictEqual(out[i].status, expectedStatus);
        }
    }));
});

test('PROPERTY: renderAgentRows fills baseline defaults and preserves order (Req 3.1)', () => {
    const containerArb = fc.record({
        name: fc.option(fc.string(), { nil: undefined }),
        state: fc.option(fc.string(), { nil: undefined }),
    }, { requiredKeys: [] });
    fc.assert(fc.property(fc.array(containerArb), (containers) => {
        const out = sortHelper.renderAgentRows(containers);
        assert.strictEqual(out.length, containers.length);
        for (let i = 0; i < containers.length; i++) {
            const c = containers[i] || {};
            assert.strictEqual(out[i].name, c.name || '(unnamed)');
            assert.strictEqual(out[i].state, c.state || 'unknown');
            assert.strictEqual(out[i].classification, 'unclassified');
            assert.strictEqual(out[i].confidence, 0);
        }
    }));
});

// ===========================================================================
// 3. loadAmInstances still GETs /api/v1/agents/ and shows ID/Identity/Name/
//    Status columns (Req 3.2).
// ===========================================================================

/**
 * Drive loadAmInstances() with a stubbed fetch and an #amInstancesContent
 * container; return { urls, opts, html }. Restores fetch afterwards.
 */
async function runLoadAmInstances(responseBody) {
    const c = document.createElement('div');
    c.id = 'amInstancesContent';
    document.body.appendChild(c);
    // Some fix variants add a feedback element; provide it so the loader has a
    // place to write without affecting this baseline-preserving assertion.
    const fb = document.createElement('div');
    fb.id = 'amInstancesFeedback';
    document.body.appendChild(fb);

    const urls = [];
    const opts = [];
    const savedFetch = global.fetch;
    global.fetch = (url, o) => {
        urls.push(url);
        opts.push(o);
        // amGet derives {__error:'network'} ONLY when fetch itself throws, and
        // {__error: resp.status} when the response is not ok. Model both paths
        // faithfully so the error token this test asserts matches production.
        if (responseBody && responseBody.__network) {
            return Promise.reject(new Error('network down'));
        }
        const httpStatus = (responseBody && responseBody.__status) || 200;
        return Promise.resolve({
            ok: httpStatus >= 200 && httpStatus < 300,
            status: httpStatus,
            json: () => Promise.resolve(responseBody),
        });
    };
    try {
        await sortHelper.loadAmInstances();
        return { urls, opts, html: c.innerHTML };
    } finally {
        global.fetch = savedFetch;
        c.remove();
        fb.remove();
    }
}

test('loadAmInstances still fetches GET /api/v1/agents/ with same-origin credentials (Req 3.2)', async () => {
    const { urls, opts } = await runLoadAmInstances({ agents: [] });
    assert.deepStrictEqual(urls, ['/api/v1/agents/'],
        'exactly the agents list endpoint is fetched');
    assert.strictEqual(opts[0].method, 'GET');
    assert.strictEqual(opts[0].credentials, 'same-origin');
});

test('PROPERTY: loadAmInstances always renders ID/Identity/Name/Status headers for any agent list (Req 3.2)', async () => {
    const agentArb = fc.record({
        id: fc.integer({ min: 1, max: 100000 }),
        identity: fc.string(),
        name: fc.string(),
        status: fc.constantFrom('READY', 'RUNNING', 'STOPPED', 'FAILED',
            'UNHEALTHY', 'STARTING', 'STOPPING', 'REGISTERED', 'TERMINATED'),
    });
    await fc.assert(fc.asyncProperty(
        fc.array(agentArb, { minLength: 1, maxLength: 5 }),
        async (agents) => {
            const { html } = await runLoadAmInstances({ agents });
            // The ID/Identity/Name/Status header labels must be present.
            for (const label of ['ID', 'Identity', 'Name', 'Status']) {
                assert.ok(html.includes('>' + label + '<'),
                    'instances table must carry the ' + label + ' column header');
            }
            // Each agent id and status text is present in the rendered output.
            for (const a of agents) {
                assert.ok(html.includes(String(a.id)),
                    'agent id ' + a.id + ' must appear in the table');
                assert.ok(html.includes(a.status),
                    'agent status ' + a.status + ' must appear in the table');
            }
        }), { numRuns: 40 });
});

// ===========================================================================
// 4. Instances empty-state and error-state messages preserved (Req 3.3).
// ===========================================================================

test('loadAmInstances preserves the empty-state message "No agents registered." (Req 3.3)', async () => {
    const { html } = await runLoadAmInstances({ agents: [] });
    assert.ok(html.includes('No agents registered.'),
        'empty-state text must be preserved');
    assert.ok(html.includes('color:orange'),
        'empty-state styling (orange) must be preserved');
});

test('loadAmInstances error-state: the "Failed to load (…)." message is produced by amRenderTable for an __error input (Req 3.3)', () => {
    // amRenderTable is the component that owns the error-state text. Assert the
    // exact observed message for an __error rows argument (the fix reuses the
    // same amRenderTable error-state convention, so this must be preserved).
    const html = normalize(liveRender(
        [{ key: 'id', label: 'ID' }], { __error: 500 }, 'No agents registered.'));
    assert.ok(html.includes('Failed to load (500).'),
        'error-state message must be preserved verbatim');
    assert.ok(html.includes('color:red'),
        'error-state styling (red) must be preserved');
    const net = normalize(liveRender(
        [{ key: 'id', label: 'ID' }], { __error: 'network' }, 'No agents registered.'));
    assert.ok(net.includes('Failed to load (network).'),
        'network error-state message must be preserved verbatim');
});

test('PROPERTY: loadAmInstances shows the empty-state on a failed/empty load — observed baseline (Req 3.3)', async () => {
    // OBSERVED BASELINE: loadAmInstances passes `data && data.agents` to the
    // renderer. On any load failure `data` is an {__error} object, so
    // `data && data.agents` is undefined and amRenderTable renders the EMPTY
    // state ("No agents registered."), NOT its error state. This pass-through
    // is preserved by the fix (design: "still passes data && data.agents so the
    // error/empty states are preserved"). We assert the empty-state message is
    // shown for both an empty list and any HTTP/network failure.
    const errArb = fc.oneof(
        fc.constant({ agents: [] }),
        fc.record({ __status: fc.integer({ min: 400, max: 599 }) }),
        fc.constant({ __network: true }));
    await fc.assert(fc.asyncProperty(errArb, async (body) => {
        const { html } = await runLoadAmInstances(body);
        assert.ok(html.includes('No agents registered.'),
            'empty/failed load must show the preserved empty-state message');
        assert.ok(!html.includes('<table'),
            'no table is rendered for an empty/failed load');
    }), { numRuns: 40 });
});

// ===========================================================================
// 5. module.exports harness contract preserved (Req 2.6).
// ===========================================================================

test('requiring the templates module is idempotent (no browser-only code at load) (Req 2.6)', () => {
    const a = require(TEMPLATES_PATH);
    const b = require(TEMPLATES_PATH);
    assert.strictEqual(a, b,
        'require must be cached/idempotent — no load-time side effects');
    // The shared helpers and the preserved AM surface must still be exported.
    for (const name of ['amRenderTable', 'loadAmInstances', 'loadAmRuntimes',
        'loadAmTasks', 'loadAmPolicies', 'loadAmMcp', 'loadAmApprovals',
        'loadAmObservability', 'loadAmIncidents', 'showAmPanel',
        'loadAgentManagement']) {
        assert.strictEqual(typeof a[name], 'function',
            'export ' + name + ' must remain a function');
    }
    assert.ok(Array.isArray(a.AM_PANELS), 'AM_PANELS export must remain an array');
});

test('module.exports stays guarded so it is a no-op in the browser (Req 2.6)', () => {
    const src = fs.readFileSync(TEMPLATES_PATH, 'utf8');
    assert.match(src, /if\s*\(\s*typeof module !== 'undefined' && module\.exports\s*\)/,
        'the exports block must stay guarded by a typeof module check');
    // The shared, unmodified helper must stay a top-level function declaration
    // so inline onclick handlers resolve it in the browser.
    assert.match(src, /^function\s+amRenderTable\s*\(/m,
        'amRenderTable must remain a top-level function declaration');
});
