'use strict';

/**
 * Unit tests for the Sort_Helper's getCellText(row, colIndex) (task 2.2).
 *
 * getCellText reads the displayed text of a body cell, flattening nested
 * markup via textContent, and returns '' for a missing/out-of-range column.
 *
 * _Requirements: 2.4_
 */

const test = require('node:test');
const assert = require('node:assert');

const { buildTable, sortHelper } = require('./harness');

const { getCellText } = sortHelper;

/** Grab the single <tbody> row of a built table. */
function firstBodyRow(table) {
    return table.querySelector('tbody > tr');
}

test('getCellText flattens <span class="status-active">Active</span> to "Active"', () => {
    const table = buildTable(
        ['Status'],
        [[{ html: '<span class="status-active">Active</span>' }]]
    );
    assert.strictEqual(getCellText(firstBodyRow(table), 0), 'Active');
});

test('getCellText returns the text of an <a> URL link', () => {
    const table = buildTable(
        ['URL'],
        [[{ html: '<a href="https://example.com/app">https://example.com/app</a>' }]]
    );
    assert.strictEqual(
        getCellText(firstBodyRow(table), 0),
        'https://example.com/app'
    );
});

test('getCellText reads the selected-option text of a <select>', () => {
    const table = buildTable(
        ['History'],
        [[{
            html:
                '<select>' +
                '<option value="1" selected>v1.2.3</option>' +
                '</select>',
        }]]
    );
    assert.strictEqual(getCellText(firstBodyRow(table), 0), 'v1.2.3');
});

test('getCellText returns "" for an out-of-range column', () => {
    const table = buildTable(['Name'], [['alpha']]);
    // Column index 5 does not exist on a single-column row.
    assert.strictEqual(getCellText(firstBodyRow(table), 5), '');
});

test('getCellText trims surrounding whitespace from flattened text', () => {
    const table = buildTable(
        ['Status'],
        [[{ html: '<span class="status-active">  Active  </span>' }]]
    );
    assert.strictEqual(getCellText(firstBodyRow(table), 0), 'Active');
});
