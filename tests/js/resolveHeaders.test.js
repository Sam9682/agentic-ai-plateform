'use strict';

/**
 * Unit tests for resolveHeaders (task 4.2).
 *
 * resolveHeaders(table, options) locates a table's <th> cells and returns
 * per-column metadata { index, th, sortable, excluded }, marking the trailing
 * Actions column (by header label) and any options.excludeColumns indices as
 * non-sortable.
 *
 * _Requirements: 1.4_
 */

const test = require('node:test');
const assert = require('node:assert');

const { buildTable, sortHelper } = require('./harness');

const { resolveHeaders } = sortHelper;

/** Convenience: return the array of sortable booleans keyed by column index. */
function sortableFlags(meta) {
    return meta.map((m) => m.sortable);
}

test('trailing "Actions" header is excluded; other columns stay sortable', () => {
    const table = buildTable(
        ['Name', 'Count', 'Actions'],
        [['alpha', '2', ''], ['bravo', '10', '']],
        { className: 'users-table' }
    );

    const meta = resolveHeaders(table);

    assert.strictEqual(meta.length, 3);
    // Metadata carries index + the actual <th> element.
    assert.strictEqual(meta[0].index, 0);
    assert.strictEqual(meta[2].th.textContent, 'Actions');
    // Only the trailing Actions column is excluded.
    assert.deepStrictEqual(sortableFlags(meta), [true, true, false]);
    assert.strictEqual(meta[2].excluded, true);
});

test('trailing Actions match is case-insensitive and trims whitespace', () => {
    const table = buildTable(
        ['Name', '  ACTIONS  '],
        [['alpha', ''], ['bravo', '']]
    );

    const meta = resolveHeaders(table);

    assert.deepStrictEqual(sortableFlags(meta), [true, false]);
});

test('a localized Actions label is excluded via actionHeaderLabels', () => {
    // Templates may render the localized get_text('actions') value; the caller
    // extends the default label list so that localized header is excluded too.
    const table = buildTable(
        ['Nom', 'Nombre', 'Actions'],
        [['alpha', '2', ''], ['bravo', '10', '']]
    );

    const meta = resolveHeaders(table, { actionHeaderLabels: ['actions'] });

    assert.deepStrictEqual(sortableFlags(meta), [true, true, false]);
});

test('a non-default localized Actions label is excluded when provided', () => {
    // French localization: the trailing header reads a translated label. When
    // that label is supplied via actionHeaderLabels it is treated as Actions.
    const table = buildTable(
        ['Nom', 'Nombre', 'Opérations'],
        [['alpha', '2', ''], ['bravo', '10', '']]
    );

    const meta = resolveHeaders(table, { actionHeaderLabels: ['opérations'] });

    assert.deepStrictEqual(sortableFlags(meta), [true, true, false]);
});

test('a table without an Actions column has every header sortable', () => {
    // e.g. the billing activities table: no trailing Actions column.
    const table = buildTable(
        ['Date', 'Description', 'Amount'],
        [['2024-01-01', 'x', '$1.00'], ['2024-01-02', 'y', '$2.00']],
        { className: 'billing-table' }
    );

    const meta = resolveHeaders(table);

    assert.deepStrictEqual(sortableFlags(meta), [true, true, true]);
    assert.ok(meta.every((m) => m.excluded === false));
});

test('an "Actions" label that is not the trailing column is NOT excluded', () => {
    // Only the trailing header qualifies as the Actions column.
    const table = buildTable(
        ['Actions', 'Name', 'Count'],
        [['', 'alpha', '2'], ['', 'bravo', '10']]
    );

    const meta = resolveHeaders(table);

    // "Actions" appears first, not last, so it is still sortable.
    assert.deepStrictEqual(sortableFlags(meta), [true, true, true]);
});

test('options.excludeColumns indices are marked non-sortable', () => {
    // e.g. deployments table: listbox columns 9 and 10 excluded.
    const table = buildTable(
        ['A', 'B', 'C', 'D'],
        [['1', '2', '3', '4']]
    );

    const meta = resolveHeaders(table, { excludeColumns: [1, 3] });

    assert.deepStrictEqual(sortableFlags(meta), [true, false, true, false]);
    assert.strictEqual(meta[1].excluded, true);
    assert.strictEqual(meta[3].excluded, true);
});

test('excludeColumns combines with the trailing Actions exclusion', () => {
    const table = buildTable(
        ['A', 'B', 'C', 'Actions'],
        [['1', '2', '3', '']]
    );

    const meta = resolveHeaders(table, { excludeColumns: [0] });

    // Column 0 excluded explicitly, column 3 excluded as trailing Actions.
    assert.deepStrictEqual(sortableFlags(meta), [false, true, true, false]);
});

test('an out-of-range excludeColumns index does not affect real columns', () => {
    const table = buildTable(['A', 'B'], [['1', '2']]);

    const meta = resolveHeaders(table, { excludeColumns: [5] });

    assert.strictEqual(meta.length, 2);
    assert.deepStrictEqual(sortableFlags(meta), [true, true]);
});
