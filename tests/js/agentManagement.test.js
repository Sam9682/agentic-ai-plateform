'use strict';

/**
 * Tests for the Agent Management (ARO + ZAF) dashboard panels (Task 18).
 *
 * Verifies:
 *   - the dashboard markup declares an #agentManagementSection and all nine
 *     am-panel sub-panels, and switchTab wires an 'agentManagement' branch;
 *   - base.html exposes the Agent Management nav entry and maps it in
 *     updateNavActive;
 *   - showAmPanel toggles exactly one panel visible and hides the rest;
 *   - amRenderTable renders rows, an empty-state, and an error-state, and
 *     escapes interpolated values.
 *
 * Structural assertions read the templates as text (Jinja HTML/JS); behavioral
 * assertions drive the exported helpers against the shared jsdom document.
 */

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const { document, sortHelper } = require('./harness');

const TEMPLATES_DIR = path.resolve(__dirname, '..', '..', 'templates');
const DASHBOARD_HTML = fs.readFileSync(path.join(TEMPLATES_DIR, 'dashboard.html'), 'utf8');
const BASE_HTML = fs.readFileSync(path.join(TEMPLATES_DIR, 'base.html'), 'utf8');

const AM_PANELS = ['dashboard', 'runtimes', 'instances', 'tasks', 'policies',
    'mcp', 'approvals', 'observability', 'incidents'];

test('dashboard declares the Agent Management section and panels', () => {
    assert.ok(DASHBOARD_HTML.includes('id="agentManagementSection"'),
        'agentManagementSection present');
    for (const p of AM_PANELS) {
        assert.ok(DASHBOARD_HTML.includes('id="amPanel-' + p + '"'),
            'panel amPanel-' + p + ' present');
    }
});

test('switchTab wires the agentManagement branch and hide line', () => {
    assert.ok(DASHBOARD_HTML.includes("tab === 'agentManagement'"),
        'switchTab has an agentManagement branch');
    assert.ok(DASHBOARD_HTML.includes("getElementById('agentManagementSection')"),
        'switchTab hides agentManagementSection');
});

test('base.html exposes the nav entry and active-state mapping', () => {
    assert.ok(BASE_HTML.includes("showTab('agentManagement')"),
        'nav entry calls showTab(agentManagement)');
    assert.ok(BASE_HTML.includes('agentManagement:'),
        'updateNavActive maps agentManagement');
});

test('showAmPanel toggles exactly one panel visible', () => {
    // Build the panel DOM the dashboard provides.
    for (const p of AM_PANELS) {
        const div = document.createElement('div');
        div.id = 'amPanel-' + p;
        div.style.display = 'none';
        document.body.appendChild(div);
    }
    try {
        sortHelper.showAmPanel('runtimes');
        for (const p of AM_PANELS) {
            const el = document.getElementById('amPanel-' + p);
            assert.strictEqual(el.style.display, p === 'runtimes' ? 'block' : 'none',
                'panel ' + p + ' visibility');
        }
    } finally {
        for (const p of AM_PANELS) {
            const el = document.getElementById('amPanel-' + p);
            if (el) el.remove();
        }
    }
});

test('amRenderTable renders rows, empty-state and error-state', () => {
    const container = document.createElement('div');
    container.id = 'amTestContainer';
    document.body.appendChild(container);
    try {
        // rows
        sortHelper.amRenderTable('amTestContainer',
            [{ key: 'name', label: 'Name' }, { key: 'status', label: 'Status' }],
            [{ name: 'a1', status: 'RUNNING' }], 'empty');
        assert.ok(container.innerHTML.includes('a1'));
        assert.ok(container.innerHTML.includes('RUNNING'));

        // empty-state
        sortHelper.amRenderTable('amTestContainer', [{ key: 'x', label: 'X' }], [], 'nothing here');
        assert.ok(container.innerHTML.includes('nothing here'));

        // error-state
        sortHelper.amRenderTable('amTestContainer', [{ key: 'x', label: 'X' }],
            { __error: 500 }, 'empty');
        assert.ok(container.innerHTML.toLowerCase().includes('failed'));
    } finally {
        container.remove();
    }
});

test('amRenderTable escapes interpolated values', () => {
    const container = document.createElement('div');
    container.id = 'amEscapeContainer';
    document.body.appendChild(container);
    try {
        sortHelper.amRenderTable('amEscapeContainer',
            [{ key: 'name', label: 'Name' }],
            [{ name: '<script>alert(1)</script>' }], 'empty');
        assert.ok(!container.innerHTML.includes('<script>alert(1)</script>'),
            'raw script must not appear unescaped');
        assert.ok(container.innerHTML.includes('&lt;script&gt;'),
            'value is HTML-escaped');
    } finally {
        container.remove();
    }
});
