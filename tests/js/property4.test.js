'use strict';

/**
 * Property test (task 6.5).
 *
 * Feature: sortable-table-headers, Property 4: Attaching preserves the initial order
 *
 * For any rendered table, invoking makeSortable without any subsequent header
 * click leaves the <tbody> row order identical to the order produced by the
 * render function.
 *
 * Validates: Requirements 4.1
 *
 * Strategy: generate tables with random numeric / date / text columns (plus the
 * edge cases called out in the design: blanks, '-', 'N/A', currency $1.2345,
 * thousands separators, duration suffixes like 45m, locale dates, mixed-case
 * text, and ragged rows). Snapshot the exact <tr> element sequence the harness
 * produced, invoke makeSortable, and assert that the <tbody> row order -- both
 * the identity of each <tr> element and its displayed cell texts -- is unchanged
 * (no sort and no indicator are applied at attach time).
 */

const test = require('node:test');
const assert = require('node:assert');
const fc = require('fast-check');

const { buildTable, sortHelper } = require('./harness');

const { makeSortable } = sortHelper;

const PROPERTY_TAG =
    'Feature: sortable-table-headers, Property 4: Attaching preserves the initial order';

// ---------------------------------------------------------------------------
// Generators. Reused shape from the design's testing strategy: columns carry a
// kind (numeric / date / text) whose cell renderings exercise the edge cases
// the templates emit, interspersed with placeholder values, plus an optional
// ragged row for the generic-table case.
// ---------------------------------------------------------------------------

const placeholderArb = fc.constantFrom('', '-', 'N/A');

// Numeric renderings the templates emit: plain ints/decimals, currency,
// thousands separators, and short duration suffixes.
const numericValueArb = fc.oneof(
    fc.integer({ min: -10000, max: 10000 }).map(String),
    fc.integer({ min: -1000000, max: 1000000 }).map(function (n) {
        return (n / 1000).toFixed(4);
    }),
    fc.integer({ min: 0, max: 5000000 }).map(function (n) {
        return '$' + (n / 1000).toFixed(4);
    }),
    fc.integer({ min: 1000, max: 9999999 }).map(function (n) {
        return n.toLocaleString('en-US'); // thousands separators e.g. 1,024
    }),
    fc.integer({ min: 0, max: 240 }).map(function (n) {
        return n + 'm'; // duration suffix e.g. 45m
    })
);

// Locale date strings shaped like toLocaleDateString() output.
const dateValueArb = fc
    .date({ min: new Date('2000-01-01'), max: new Date('2035-12-31') })
    .map(function (d) {
        const mm = d.getUTCMonth() + 1;
        const dd = d.getUTCDate();
        const yyyy = d.getUTCFullYear();
        return mm + '/' + dd + '/' + yyyy;
    });

// Mixed-case text tokens (no leading/trailing whitespace so trimming does not
// change the compared value).
const textValueArb = fc.stringMatching(/^[A-Za-z][A-Za-z0-9]{0,9}$/);

function columnArb(valueArb) {
    // Mostly meaningful values with an occasional placeholder mixed in.
    return fc.oneof(
        { arbitrary: valueArb, weight: 5 },
        { arbitrary: placeholderArb, weight: 1 }
    );
}

const columnKindArb = fc.constantFrom('numeric', 'date', 'text');

/**
 * Build a spec describing a table: a set of columns (each with a kind and its
 * cell values) plus optional ragged rows. Returns { headers, rows }.
 */
const tableSpecArb = fc
    .record({
        columnKinds: fc.array(columnKindArb, { minLength: 1, maxLength: 4 }),
        rowCount: fc.integer({ min: 1, max: 12 }),
        ragged: fc.boolean(),
        // Randomly include a trailing Actions column so attach-time behavior is
        // exercised both with and without an excluded header.
        withActions: fc.boolean(),
    })
    .chain(function (shape) {
        const perColumnArbs = shape.columnKinds.map(function (kind) {
            const valueArb =
                kind === 'numeric'
                    ? numericValueArb
                    : kind === 'date'
                        ? dateValueArb
                        : textValueArb;
            return fc.array(columnArb(valueArb), {
                minLength: shape.rowCount,
                maxLength: shape.rowCount,
            });
        });

        return fc.tuple.apply(fc, perColumnArbs).map(function (columns) {
            // columns[c][r] -> value; assemble the row-major cell matrix.
            const rows = [];
            for (let r = 0; r < shape.rowCount; r++) {
                const row = [];
                for (let c = 0; c < shape.columnKinds.length; c++) {
                    row.push(columns[c][r]);
                }
                if (shape.withActions) {
                    // Action cells hold markup like the templates emit.
                    row.push({ html: '<button>Edit</button>' });
                }
                rows.push(row);
            }

            // Optionally make one row ragged (fewer cells) to cover the
            // ragged-rows edge case, only when there is more than one column.
            if (shape.ragged && rows.length > 0 && rows[0].length > 1) {
                rows[rows.length - 1] = rows[rows.length - 1].slice(0, 1);
            }

            const headers = shape.columnKinds.map(function (_kind, i) {
                return 'Col' + i;
            });
            if (shape.withActions) {
                headers.push('Actions');
            }

            return { headers: headers, rows: rows };
        });
    });

// ---------------------------------------------------------------------------
// Helpers to snapshot the tbody state.
// ---------------------------------------------------------------------------

function tbodyRowElements(table) {
    return Array.from(table.querySelectorAll('tbody > tr'));
}

function rowTexts(tr) {
    return Array.from(tr.children).map(function (td) {
        return (td.textContent || '').trim();
    });
}

// ---------------------------------------------------------------------------
// Property.
// ---------------------------------------------------------------------------

test(PROPERTY_TAG, () => {
    fc.assert(
        fc.property(tableSpecArb, function (spec) {
            const table = buildTable(spec.headers, spec.rows, {
                className: 'property4-table',
                attach: true,
            });

            // Snapshot the exact <tr> element sequence and their displayed
            // cell texts BEFORE attaching the helper.
            const beforeRows = tbodyRowElements(table);
            const beforeTexts = beforeRows.map(rowTexts);

            // Attaching must not reorder rows (Req 4.1) and must add no
            // indicator (guarded by Property 3, checked here only for order).
            makeSortable(table);

            const afterRows = tbodyRowElements(table);

            // Same number of rows, same <tr> element identity in the same
            // positions -- the render function's order is preserved exactly.
            assert.strictEqual(
                afterRows.length,
                beforeRows.length,
                'row count changed after attaching makeSortable'
            );
            for (let i = 0; i < beforeRows.length; i++) {
                assert.strictEqual(
                    afterRows[i],
                    beforeRows[i],
                    'row element at position ' +
                        i +
                        ' changed identity/order after attaching makeSortable'
                );
                assert.deepStrictEqual(
                    rowTexts(afterRows[i]),
                    beforeTexts[i],
                    'row text at position ' +
                        i +
                        ' changed after attaching makeSortable'
                );
            }

            // Cleanup so attached tables don't accumulate across runs.
            if (table.parentNode) {
                table.parentNode.removeChild(table);
            }
        }),
        { numRuns: 200 }
    );
});
