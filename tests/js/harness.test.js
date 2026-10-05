'use strict';

/**
 * Smoke tests for the jsdom test harness and the Sort_Helper stubs (task 1.1).
 *
 * These confirm the harness is wired up correctly and can exercise the stubs
 * without error. Behavioral assertions come with later tasks once the stubs
 * gain real implementations.
 */

const test = require('node:test');
const assert = require('node:assert');

const {
    buildTable,
    clickHeader,
    getColumnTexts,
    sortHelper,
} = require('./harness');

const SORT_HELPER_FUNCTIONS = [
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
];

test('Sort_Helper exports all expected functions', () => {
    for (const name of SORT_HELPER_FUNCTIONS) {
        assert.strictEqual(
            typeof sortHelper[name],
            'function',
            'expected ' + name + ' to be exported as a function'
        );
    }
});

test('buildTable produces the render-function markup shape', () => {
    const table = buildTable(
        ['Name', 'Count', 'Actions'],
        [
            ['bravo', '2', ''],
            ['alpha', '10', ''],
        ],
        { className: 'users-table' }
    );

    assert.strictEqual(table.tagName, 'TABLE');
    assert.ok(table.classList.contains('users-table'));

    const headers = table.querySelectorAll('thead th');
    assert.strictEqual(headers.length, 3);
    assert.strictEqual(headers[0].textContent, 'Name');
    assert.strictEqual(headers[2].textContent, 'Actions');

    const bodyRows = table.querySelectorAll('tbody > tr');
    assert.strictEqual(bodyRows.length, 2);
    assert.strictEqual(bodyRows[0].children.length, 3);

    assert.deepStrictEqual(getColumnTexts(table, 0), ['bravo', 'alpha']);
});

test('buildTable supports nested cell markup via { html }', () => {
    const table = buildTable(
        ['Status'],
        [[{ html: '<span class="status-active">Active</span>' }]]
    );
    const cell = table.querySelector('tbody > tr > td');
    assert.ok(cell.querySelector('span.status-active'));
    assert.strictEqual((cell.textContent || '').trim(), 'Active');
});

test('makeSortable stub runs on a built table without throwing', () => {
    const table = buildTable(
        ['Name', 'Actions'],
        [['alpha', ''], ['bravo', '']],
        { className: 'users-table', attach: true }
    );
    assert.doesNotThrow(() => sortHelper.makeSortable(table));
    // no-op guard: also safe with null / options
    assert.doesNotThrow(() => sortHelper.makeSortable(null));
    assert.doesNotThrow(() => sortHelper.makeSortable(table, { excludeColumns: [1] }));
});

test('clickHeader dispatches a header click without throwing (stub is a no-op)', () => {
    const table = buildTable(
        ['Name', 'Actions'],
        [['alpha', ''], ['bravo', '']],
        { attach: true }
    );
    sortHelper.makeSortable(table);
    const before = getColumnTexts(table, 0);
    assert.doesNotThrow(() => clickHeader(table, 0));
    // stub does nothing, so order is preserved
    assert.deepStrictEqual(getColumnTexts(table, 0), before);
});
