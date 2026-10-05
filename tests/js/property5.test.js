'use strict';

/**
 * Property test — Property 5: The Actions column is never sortable (task 6.6).
 *
 * Feature: sortable-table-headers, Property 5: The Actions column is never
 * sortable — for any rendered table that has a trailing Actions column (or any
 * column named in excludeColumns), that header registers no sort behavior:
 * clicking it does not reorder rows and adds no Sort_Indicator to any header.
 *
 * Validates: Requirements 1.4
 *
 * After makeSortable attaches, a sortable header carries data-sortable="true"
 * and a dedicated <span class="sort-indicator">; an excluded header (the
 * trailing Actions column or any index in options.excludeColumns) carries no
 * such marker, no click listener, no pointer cursor, and never receives an
 * indicator. Clicking such a header must be a complete no-op: row order is
 * unchanged and no header in the table shows a ▲/▼ glyph.
 */

const test = require('node:test');
const assert = require('node:assert');
const fc = require('fast-check');

const {
    buildTable,
    clickHeader,
    getColumnTexts,
    sortHelper,
} = require('./harness');

const { makeSortable } = sortHelper;

/**
 * Snapshot the full <tbody> row ordering as a matrix of trimmed cell texts,
 * one array per row. Used to assert that clicking an excluded header leaves the
 * row order (and cell contents) untouched.
 *
 * @param {HTMLTableElement} table
 * @param {number} colCount
 * @returns {string[][]}
 */
function snapshotRows(table, colCount) {
    const rows = Array.from(table.querySelectorAll('tbody > tr'));
    return rows.map((tr) =>
        Array.from({ length: colCount }, (_, c) => {
            const cell = tr.children[c];
            return cell ? (cell.textContent || '').trim() : '';
        })
    );
}

/**
 * The trimmed indicator glyph for each header cell, or '' when the header has
 * no indicator span or an empty one.
 *
 * @param {HTMLTableElement} table
 * @returns {string[]}
 */
function indicatorGlyphs(table) {
    const ths = Array.from(table.querySelectorAll('thead th'));
    return ths.map((th) => {
        const span = th.querySelector('span.sort-indicator');
        return span ? (span.textContent || '').trim() : '';
    });
}

/**
 * Header indices marked sortable (data-sortable="true") after makeSortable.
 *
 * @param {HTMLTableElement} table
 * @returns {number[]}
 */
function sortableIndices(table) {
    const ths = Array.from(table.querySelectorAll('thead th'));
    const out = [];
    ths.forEach((th, i) => {
        if (th.getAttribute('data-sortable') === 'true') out.push(i);
    });
    return out;
}

// Representative cell values across the column types the design exercises:
// text, numeric (incl. currency / separators / duration), dates, and
// placeholder/blank values.
const CELL_VALUE_POOL = [
    'alpha', 'bravo', 'Charlie', 'delta',
    '1', '10', '2', '42', '1024',
    '$1.2345', '1,024', '45m',
    '2024-01-15', '2023-11-02', 'Jan 5, 2022',
    '', '-', 'N/A',
];

const cellValueArb = fc.constantFrom(...CELL_VALUE_POOL);

// -----------------------------------------------------------------------------
// Property 5a: a trailing "Actions" column is never sortable.
// -----------------------------------------------------------------------------

/**
 * Generate a table shape with 1..4 data columns plus a trailing "Actions"
 * column, and 0..6 rows filled from the value pool.
 */
const actionsShapeArb = fc
    .record({
        dataCols: fc.integer({ min: 1, max: 4 }),
        rowCount: fc.integer({ min: 0, max: 6 }),
    })
    .chain(({ dataCols, rowCount }) => {
        const totalCols = dataCols + 1; // + Actions
        const cellArb = fc.array(cellValueArb, {
            minLength: totalCols,
            maxLength: totalCols,
        });
        return fc.record({
            dataCols: fc.constant(dataCols),
            rows: fc.array(cellArb, { minLength: rowCount, maxLength: rowCount }),
        });
    });

function buildActionsTable(shape) {
    const headers = [];
    for (let i = 0; i < shape.dataCols; i++) headers.push('Col' + i);
    headers.push('Actions');
    return buildTable(headers, shape.rows, { className: 'users-table', attach: true });
}

test('Feature: sortable-table-headers, Property 5: The Actions column is never sortable', () => {
    fc.assert(
        fc.property(actionsShapeArb, (shape) => {
            const table = buildActionsTable(shape);
            const totalCols = shape.dataCols + 1;
            const actionsIndex = totalCols - 1;

            makeSortable(table);

            // The trailing Actions header must not be marked sortable.
            const sortables = sortableIndices(table);
            assert.ok(
                !sortables.includes(actionsIndex),
                'the trailing Actions column must never be sortable'
            );
            const actionsTh = table.querySelectorAll('thead th')[actionsIndex];
            assert.notStrictEqual(
                actionsTh.getAttribute('data-sortable'),
                'true',
                'the Actions header must not carry data-sortable="true"'
            );

            // Capture order + indicators before clicking the Actions header.
            const before = snapshotRows(table, totalCols);

            // Clicking the Actions header is a complete no-op.
            clickHeader(table, actionsIndex);

            const after = snapshotRows(table, totalCols);
            assert.deepStrictEqual(
                after,
                before,
                'clicking the Actions header must not reorder rows'
            );

            const glyphs = indicatorGlyphs(table);
            assert.ok(
                glyphs.every((g) => g === ''),
                'clicking the Actions header must add no Sort_Indicator to any header'
            );

            return true;
        }),
        { numRuns: 150 }
    );
});

// -----------------------------------------------------------------------------
// Property 5b: any column named in options.excludeColumns is never sortable.
// -----------------------------------------------------------------------------

/**
 * Generate a table shape plus a subset of column indices to exclude. Columns
 * are named Col0..ColN with a trailing "Actions" column; excludeColumns picks
 * from the data-column indices so we exercise interior/leading exclusions too.
 */
const excludeShapeArb = fc
    .record({
        dataCols: fc.integer({ min: 2, max: 5 }),
        rowCount: fc.integer({ min: 0, max: 6 }),
    })
    .chain(({ dataCols, rowCount }) => {
        const totalCols = dataCols + 1; // + Actions
        const cellArb = fc.array(cellValueArb, {
            minLength: totalCols,
            maxLength: totalCols,
        });
        // Exclude 1..dataCols distinct data-column indices (0..dataCols-1).
        const excludeArb = fc.uniqueArray(
            fc.integer({ min: 0, max: dataCols - 1 }),
            { minLength: 1, maxLength: dataCols }
        );
        return fc.record({
            dataCols: fc.constant(dataCols),
            rows: fc.array(cellArb, { minLength: rowCount, maxLength: rowCount }),
            excludeColumns: excludeArb,
        });
    });

function buildExcludeTable(shape) {
    const headers = [];
    for (let i = 0; i < shape.dataCols; i++) headers.push('Col' + i);
    headers.push('Actions');
    return buildTable(headers, shape.rows, { className: 'database-table', attach: true });
}

test('Feature: sortable-table-headers, Property 5: columns in excludeColumns register no sort behavior', () => {
    fc.assert(
        fc.property(excludeShapeArb, (shape) => {
            const table = buildExcludeTable(shape);
            const totalCols = shape.dataCols + 1;

            makeSortable(table, { excludeColumns: shape.excludeColumns });

            const sortables = sortableIndices(table);
            const ths = Array.from(table.querySelectorAll('thead th'));

            // Every excluded index (and the trailing Actions column) must be
            // non-sortable and carry no data-sortable marker.
            for (const idx of shape.excludeColumns) {
                assert.ok(
                    !sortables.includes(idx),
                    'excluded column ' + idx + ' must never be sortable'
                );
                assert.notStrictEqual(
                    ths[idx].getAttribute('data-sortable'),
                    'true',
                    'excluded column ' + idx + ' must not carry data-sortable="true"'
                );
            }

            // Clicking each excluded header (and the Actions header) is a no-op:
            // rows never reorder and no indicator ever appears anywhere.
            const before = snapshotRows(table, totalCols);
            const clickTargets = shape.excludeColumns.concat([totalCols - 1]);
            for (const idx of clickTargets) {
                clickHeader(table, idx);
                assert.deepStrictEqual(
                    snapshotRows(table, totalCols),
                    before,
                    'clicking excluded/Actions header ' + idx + ' must not reorder rows'
                );
                assert.ok(
                    indicatorGlyphs(table).every((g) => g === ''),
                    'clicking excluded/Actions header ' + idx + ' must add no indicator'
                );
            }

            return true;
        }),
        { numRuns: 150 }
    );
});

// -----------------------------------------------------------------------------
// Edge case: a table WITHOUT an Actions column has all headers sortable, so no
// column is excluded on that basis. This guards against over-eager exclusion.
// -----------------------------------------------------------------------------

const noActionsShapeArb = fc
    .record({
        dataCols: fc.integer({ min: 1, max: 4 }),
        // At least one row: makeSortable no-ops on an empty <tbody>, so the
        // "all headers sortable" invariant is only observable once rows exist.
        rowCount: fc.integer({ min: 1, max: 6 }),
    })
    .chain(({ dataCols, rowCount }) => {
        const cellArb = fc.array(cellValueArb, {
            minLength: dataCols,
            maxLength: dataCols,
        });
        return fc.record({
            dataCols: fc.constant(dataCols),
            rows: fc.array(cellArb, { minLength: rowCount, maxLength: rowCount }),
        });
    });

test('Feature: sortable-table-headers, Property 5: a table without an Actions column excludes no column (edge case)', () => {
    fc.assert(
        fc.property(noActionsShapeArb, (shape) => {
            const headers = [];
            for (let i = 0; i < shape.dataCols; i++) headers.push('Col' + i);
            const table = buildTable(headers, shape.rows, {
                className: 'billing-table',
                attach: true,
            });

            makeSortable(table);

            const sortables = sortableIndices(table);
            // With no trailing "Actions" header and no excludeColumns, every
            // header is sortable.
            assert.strictEqual(
                sortables.length,
                shape.dataCols,
                'a table without an Actions column should have all headers sortable'
            );
            return true;
        }),
        { numRuns: 100 }
    );
});
