'use strict';

/**
 * Unit tests for the Agent Management "Instances" lifecycle helpers
 * (task 3.5 of the agent-lifecycle-controls bugfix spec).
 *
 * Helpers under test (all exported from templates/dashboard_functions.js and
 * loaded here via the jsdom harness):
 *   - lifecycleControlState(status)
 *   - renderAgentInstanceRows(agents)
 *   - renderAgentInstancesTable(containerId, data, feedbackId)
 *   - amPostLifecycle(agentId, op)   (exercised indirectly via the handler)
 *   - triggerAgentLifecycle(agentId, op)
 *
 * Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5
 *
 * The tests do NOT modify production code. They stub global.fetch where the
 * handler issues requests and restore it after each test, and they provide the
 * #amInstancesContent / #amInstancesFeedback DOM elements the handler needs.
 */

const test = require('node:test');
const assert = require('node:assert');

const { window, document, sortHelper } = require('./harness');

const {
    lifecycleControlState,
    renderAgentInstanceRows,
    renderAgentInstancesTable,
    triggerAgentLifecycle,
} = sortHelper;

// ---------------------------------------------------------------------------
// Mapping contract (the documented legal sets), used to drive the table tests.
// ---------------------------------------------------------------------------

// States that enable Start (and therefore Restart).
const START_STATES = ['READY', 'STOPPED', 'FAILED'];
// States that enable Stop (and therefore Restart).
const STOP_STATES = ['RUNNING', 'UNHEALTHY'];
// Transient / unknown states that enable nothing.
const INERT_STATES = [
    'REGISTERED', 'INSTALLING', 'INSTALLED', 'CONFIGURING',
    'STARTING', 'STOPPING', 'QUARANTINED', 'TERMINATED',
    'TOTALLY_UNKNOWN', '', 'running', 'ready',
];

/** Expected {start,stop,restart} for a status, per the documented contract. */
function expectedState(status) {
    const start = START_STATES.indexOf(status) !== -1;
    const stop = STOP_STATES.indexOf(status) !== -1;
    const restart = start || stop; // restart legal from every start- or stop-able state
    return { start, stop, restart };
}

// ---------------------------------------------------------------------------
// fetch stub helpers
// ---------------------------------------------------------------------------

/**
 * Build a Response-like object that supports BOTH .json() (used by amGet during
 * the refresh) and .text() (used by amPostLifecycle). This lets one stub serve
 * both the POST and the follow-up GET /api/v1/agents/.
 */
function makeResponse({ ok = true, status = 200, body = {} } = {}) {
    const text = typeof body === 'string' ? body : JSON.stringify(body);
    return {
        ok,
        status,
        json: () => Promise.resolve(typeof body === 'string' ? JSON.parse(text || '{}') : body),
        text: () => Promise.resolve(text),
    };
}

/**
 * Install a fetch stub on both global and the jsdom window. `handler(url, opts)`
 * returns either a Response-like object, a value to resolve with, or throws /
 * returns a rejected promise to simulate a network failure. Returns a restore().
 */
function installFetch(handler) {
    const savedGlobal = Object.prototype.hasOwnProperty.call(global, 'fetch')
        ? { has: true, value: global.fetch }
        : { has: false };
    const savedWindow = Object.prototype.hasOwnProperty.call(window, 'fetch')
        ? { has: true, value: window.fetch }
        : { has: false };

    const calls = [];
    const stub = function (url, opts) {
        calls.push({ url, opts });
        try {
            return Promise.resolve(handler(url, opts));
        } catch (e) {
            return Promise.reject(e);
        }
    };
    global.fetch = stub;
    window.fetch = stub;

    return {
        calls,
        restore() {
            if (savedGlobal.has) global.fetch = savedGlobal.value;
            else delete global.fetch;
            if (savedWindow.has) window.fetch = savedWindow.value;
            else delete window.fetch;
        },
    };
}

/** Ensure #amInstancesContent and #amInstancesFeedback exist in the jsdom DOM. */
function setupInstancesDom(contentHtml) {
    let content = document.getElementById('amInstancesContent');
    if (!content) {
        content = document.createElement('div');
        content.id = 'amInstancesContent';
        document.body.appendChild(content);
    }
    content.innerHTML = contentHtml || '';

    let feedback = document.getElementById('amInstancesFeedback');
    if (!feedback) {
        feedback = document.createElement('div');
        feedback.id = 'amInstancesFeedback';
        document.body.appendChild(feedback);
    }
    feedback.innerHTML = '';
    return { content, feedback };
}

function teardownInstancesDom() {
    for (const id of ['amInstancesContent', 'amInstancesFeedback']) {
        const el = document.getElementById(id);
        if (el && el.parentNode) el.parentNode.removeChild(el);
    }
}

// ===========================================================================
// lifecycleControlState — table-driven over all states (Req 2.5)
// ===========================================================================

test('lifecycleControlState: READY / STOPPED / FAILED enable Start + Restart (not Stop)', () => {
    for (const status of START_STATES) {
        assert.deepStrictEqual(
            lifecycleControlState(status),
            { start: true, stop: false, restart: true },
            'unexpected control state for ' + status
        );
    }
});

test('lifecycleControlState: RUNNING / UNHEALTHY enable Stop + Restart (not Start)', () => {
    for (const status of STOP_STATES) {
        assert.deepStrictEqual(
            lifecycleControlState(status),
            { start: false, stop: true, restart: true },
            'unexpected control state for ' + status
        );
    }
});

test('lifecycleControlState: transient and unknown states enable nothing', () => {
    for (const status of INERT_STATES) {
        assert.deepStrictEqual(
            lifecycleControlState(status),
            { start: false, stop: false, restart: false },
            'transient/unknown state should enable nothing: "' + status + '"'
        );
    }
});

test('lifecycleControlState: null / undefined status enable nothing', () => {
    assert.deepStrictEqual(lifecycleControlState(undefined), { start: false, stop: false, restart: false });
    assert.deepStrictEqual(lifecycleControlState(null), { start: false, stop: false, restart: false });
});

// ===========================================================================
// renderAgentInstanceRows — rows, columns, buttons, escaping (Req 2.1, 2.5)
// ===========================================================================

/** Parse a <tr> fragment string into DOM rows via a detached tbody. */
function parseRows(html) {
    const table = document.createElement('table');
    const tbody = document.createElement('tbody');
    tbody.innerHTML = html;
    table.appendChild(tbody);
    return Array.from(tbody.querySelectorAll('tr'));
}

test('renderAgentInstanceRows: emits one row per agent', () => {
    const agents = [
        { id: 1, identity: 'svc-a', name: 'Agent A', status: 'READY' },
        { id: 2, identity: 'svc-b', name: 'Agent B', status: 'RUNNING' },
        { id: 3, identity: 'svc-c', name: 'Agent C', status: 'STARTING' },
    ];
    const rows = parseRows(renderAgentInstanceRows(agents));
    assert.strictEqual(rows.length, 3, 'one <tr> per agent');
});

test('renderAgentInstanceRows: empty / non-array input yields no rows', () => {
    assert.strictEqual(renderAgentInstanceRows([]), '');
    assert.strictEqual(renderAgentInstanceRows(undefined), '');
    assert.strictEqual(renderAgentInstanceRows(null), '');
});

test('renderAgentInstanceRows: columns render ID / Identity / Name / Status in order', () => {
    const agents = [{ id: 7, identity: 'ident-7', name: 'Lucky', status: 'STOPPED' }];
    const rows = parseRows(renderAgentInstanceRows(agents));
    const cells = rows[0].querySelectorAll('td');
    // 4 data columns + 1 Actions column.
    assert.strictEqual(cells.length, 5, 'five <td> cells: ID, Identity, Name, Status, Actions');
    assert.strictEqual(cells[0].textContent.trim(), '7');
    assert.strictEqual(cells[1].textContent.trim(), 'ident-7');
    assert.strictEqual(cells[2].textContent.trim(), 'Lucky');
    assert.strictEqual(cells[3].textContent.trim(), 'STOPPED');
});

test('renderAgentInstanceRows: Actions cell carries exactly three buttons (Start/Stop/Restart)', () => {
    const agents = [{ id: 1, identity: 'x', name: 'y', status: 'READY' }];
    const rows = parseRows(renderAgentInstanceRows(agents));
    const buttons = rows[0].querySelectorAll('button');
    assert.strictEqual(buttons.length, 3, 'three lifecycle buttons');
    assert.deepStrictEqual(
        Array.from(buttons).map((b) => b.textContent.trim()),
        ['Start', 'Stop', 'Restart']
    );
});

test('renderAgentInstanceRows: each button disabled state matches lifecycleControlState', () => {
    const allStates = START_STATES.concat(STOP_STATES, INERT_STATES.filter((s) => s !== ''));
    for (const status of allStates) {
        const rows = parseRows(renderAgentInstanceRows([{ id: 1, identity: 'i', name: 'n', status }]));
        const buttons = rows[0].querySelectorAll('button');
        const exp = expectedState(status);
        // Button order is Start, Stop, Restart.
        assert.strictEqual(buttons[0].disabled, !exp.start, 'Start disabled mismatch for ' + status);
        assert.strictEqual(buttons[1].disabled, !exp.stop, 'Stop disabled mismatch for ' + status);
        assert.strictEqual(buttons[2].disabled, !exp.restart, 'Restart disabled mismatch for ' + status);
    }
});

test('renderAgentInstanceRows: disabled buttons carry an explanatory title; enabled ones do not', () => {
    const rows = parseRows(renderAgentInstanceRows([{ id: 1, identity: 'i', name: 'n', status: 'READY' }]));
    const buttons = rows[0].querySelectorAll('button');
    // READY -> Start enabled (no title), Stop disabled (has title), Restart enabled (no title).
    assert.strictEqual(buttons[0].getAttribute('title'), null);
    assert.ok(buttons[1].getAttribute('title'), 'disabled Stop button should have a title');
    assert.strictEqual(buttons[2].getAttribute('title'), null);
});

test('renderAgentInstanceRows: an XSS attempt in Name/Identity renders as text, not markup', () => {
    const xss = '<script>window.__pwned=1<\/script>';
    const imgXss = '<img src=x onerror="window.__pwned=1">';
    const agents = [{ id: 99, identity: imgXss, name: xss, status: 'READY' }];
    const html = renderAgentInstanceRows(agents);

    // No raw <script> or <img ...onerror> survives in the emitted markup.
    assert.ok(html.indexOf('<script>') === -1, 'no raw <script> in output');
    assert.ok(html.toLowerCase().indexOf('<img') === -1, 'no raw <img> in output');

    // When parsed, the payloads appear as text content, not as live elements.
    const rows = parseRows(html);
    const cells = rows[0].querySelectorAll('td');
    assert.strictEqual(cells[1].querySelector('img'), null, 'identity cell must not create an <img>');
    assert.strictEqual(cells[2].querySelector('script'), null, 'name cell must not create a <script>');
    assert.strictEqual(cells[1].textContent, imgXss, 'identity payload preserved as text');
    assert.strictEqual(cells[2].textContent, xss, 'name payload preserved as text');
});

test('renderAgentInstanceRows: non-numeric id coerces the onclick argument to 0', () => {
    // The raw id string is rendered (escaped) as inert text in the ID cell, but
    // the inline-onclick argument must be the numeric coercion (0), so attacker
    // text in the id can never break out into executable handler markup.
    const html = renderAgentInstanceRows([{ id: 'abc"); alert(1);(', identity: 'i', name: 'n', status: 'READY' }]);
    assert.ok(
        html.indexOf("triggerAgentLifecycle(0, 'start')") !== -1,
        'non-numeric id should render as numeric 0 in the inline handler'
    );
    // The attacker payload must not appear inside any triggerAgentLifecycle(...)
    // call — only the numeric 0 is ever passed as the id argument.
    const onclickCalls = (html.match(/triggerAgentLifecycle\([^)]*\)/g) || []);
    assert.strictEqual(onclickCalls.length, 3, 'three onclick handlers, one per button');
    for (const call of onclickCalls) {
        assert.ok(call.indexOf('alert(1)') === -1, 'attacker id markup must not leak into the onclick: ' + call);
        assert.ok(/^triggerAgentLifecycle\(0, '(start|stop|restart)'\)$/.test(call), 'onclick uses numeric id 0: ' + call);
    }
});

// ===========================================================================
// triggerAgentLifecycle — guards, success refresh, error handling
// (Req 2.2, 2.3, 2.4)
// ===========================================================================

test('triggerAgentLifecycle: rejects an invalid op without issuing any request', async () => {
    const fetchStub = installFetch(() => makeResponse({ body: {} }));
    setupInstancesDom('<table id="orig"></table>');
    try {
        await triggerAgentLifecycle(1, 'destroy');
        assert.strictEqual(fetchStub.calls.length, 0, 'no fetch for a bad op');
        // Table untouched, no feedback written.
        assert.ok(document.getElementById('orig'), 'original table left intact');
        assert.strictEqual(document.getElementById('amInstancesFeedback').innerHTML, '');
    } finally {
        fetchStub.restore();
        teardownInstancesDom();
    }
});

test('triggerAgentLifecycle: rejects a missing id without issuing any request', async () => {
    const fetchStub = installFetch(() => makeResponse({ body: {} }));
    setupInstancesDom('<table id="orig"></table>');
    try {
        await triggerAgentLifecycle('', 'start');
        await triggerAgentLifecycle(null, 'stop');
        await triggerAgentLifecycle(undefined, 'restart');
        assert.strictEqual(fetchStub.calls.length, 0, 'no fetch for a missing id');
        assert.ok(document.getElementById('orig'), 'original table left intact');
        assert.strictEqual(document.getElementById('amInstancesFeedback').innerHTML, '');
    } finally {
        fetchStub.restore();
        teardownInstancesDom();
    }
});

test('triggerAgentLifecycle: success POSTs, refreshes the panel, and writes success feedback', async () => {
    // First call (POST) succeeds; second call (GET refresh) returns a fresh list.
    const fetchStub = installFetch((url, opts) => {
        if (opts && opts.method === 'POST') {
            assert.strictEqual(url, '/api/v1/agents/5/start', 'POST hits the lifecycle endpoint');
            return makeResponse({ ok: true, status: 200, body: { ok: true } });
        }
        // GET /api/v1/agents/ refresh.
        assert.strictEqual(url, '/api/v1/agents/');
        return makeResponse({
            ok: true,
            status: 200,
            body: { agents: [{ id: 5, identity: 'svc', name: 'Agent', status: 'RUNNING' }] },
        });
    });
    setupInstancesDom('');
    try {
        await triggerAgentLifecycle(5, 'start');

        // Both the POST and the refresh GET were issued.
        assert.strictEqual(fetchStub.calls.length, 2, 'POST then refresh GET');
        assert.strictEqual(fetchStub.calls[0].opts.method, 'POST');

        // Panel refreshed with the new status.
        const content = document.getElementById('amInstancesContent');
        assert.ok(content.querySelector('table'), 'panel re-rendered a table');
        assert.ok(content.textContent.indexOf('RUNNING') !== -1, 'refreshed status shown');

        // Success feedback written.
        const fb = document.getElementById('amInstancesFeedback');
        assert.ok(fb.textContent.toLowerCase().indexOf('succeeded') !== -1, 'success message present');
        const span = fb.querySelector('span');
        assert.ok(span && /green/.test(span.getAttribute('style') || ''), 'success feedback styled green');
    } finally {
        fetchStub.restore();
        teardownInstancesDom();
    }
});

test('triggerAgentLifecycle: 409 writes an error into feedback and leaves the table intact', async () => {
    const fetchStub = installFetch(() => makeResponse({ ok: false, status: 409, body: {} }));
    const origHtml = '<table id="orig"><tbody><tr id="r1"><td>keep</td></tr></tbody></table>';
    setupInstancesDom(origHtml);
    try {
        await triggerAgentLifecycle(8, 'stop');

        // Only the POST was issued (no refresh on error).
        assert.strictEqual(fetchStub.calls.length, 1, 'only the POST, no refresh on error');

        // Table untouched.
        assert.ok(document.getElementById('r1'), 'existing table row preserved on error');
        assert.strictEqual(document.getElementById('amInstancesContent').innerHTML, origHtml);

        // Error feedback written, referencing the 409.
        const fb = document.getElementById('amInstancesFeedback');
        assert.ok(fb.textContent.toLowerCase().indexOf('failed') !== -1, 'error message present');
        assert.ok(fb.textContent.indexOf('409') !== -1, 'status code surfaced');
        const span = fb.querySelector('span');
        assert.ok(span && /red/.test(span.getAttribute('style') || ''), 'error feedback styled red');
    } finally {
        fetchStub.restore();
        teardownInstancesDom();
    }
});

test('triggerAgentLifecycle: 404 writes an error into feedback and leaves the table intact', async () => {
    const fetchStub = installFetch(() => makeResponse({ ok: false, status: 404, body: {} }));
    const origHtml = '<table id="orig"><tbody><tr id="r1"><td>keep</td></tr></tbody></table>';
    setupInstancesDom(origHtml);
    try {
        await triggerAgentLifecycle(8, 'restart');
        assert.strictEqual(fetchStub.calls.length, 1, 'only the POST, no refresh on error');
        assert.ok(document.getElementById('r1'), 'existing table row preserved on error');
        assert.strictEqual(document.getElementById('amInstancesContent').innerHTML, origHtml);
        const fb = document.getElementById('amInstancesFeedback');
        assert.ok(fb.textContent.indexOf('404') !== -1, 'status code surfaced');
    } finally {
        fetchStub.restore();
        teardownInstancesDom();
    }
});

test('triggerAgentLifecycle: network failure writes an escaped error and leaves the table intact', async () => {
    const fetchStub = installFetch(() => {
        throw new Error('boom');
    });
    const origHtml = '<table id="orig"><tbody><tr id="r1"><td>keep</td></tr></tbody></table>';
    setupInstancesDom(origHtml);
    try {
        await triggerAgentLifecycle(8, 'start');
        assert.strictEqual(fetchStub.calls.length, 1, 'only the POST attempt');
        assert.ok(document.getElementById('r1'), 'existing table row preserved on network error');
        assert.strictEqual(document.getElementById('amInstancesContent').innerHTML, origHtml);
        const fb = document.getElementById('amInstancesFeedback');
        assert.ok(fb.textContent.toLowerCase().indexOf('network') !== -1, 'network error surfaced');
    } finally {
        fetchStub.restore();
        teardownInstancesDom();
    }
});

test('triggerAgentLifecycle: error feedback escapes the operation string (no markup injected)', async () => {
    // op is guarded to start/stop/restart, so feedback text is controlled; this
    // asserts the feedback is written as escaped text via a <span>, never raw.
    const fetchStub = installFetch(() => makeResponse({ ok: false, status: 409, body: {} }));
    setupInstancesDom('');
    try {
        await triggerAgentLifecycle(3, 'stop');
        const fb = document.getElementById('amInstancesFeedback');
        // Exactly one span, and no injected child elements beyond it.
        const span = fb.querySelector('span');
        assert.ok(span, 'feedback rendered inside a span');
        assert.strictEqual(span.querySelectorAll('*').length, 0, 'no nested markup inside feedback span');
    } finally {
        fetchStub.restore();
        teardownInstancesDom();
    }
});
