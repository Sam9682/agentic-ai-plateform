'use strict';

/**
 * Property test (task 6.2).
 *
 * Feature: sortable-table-headers, Property 1: Type-aware ascending ordering
 *
 * For any rendered table and any sortable column, clicking that column when it
 * is not the active column reorders the <tbody> rows into ascending order under
 * the column's detected type -- numeric columns by numeric value, date columns
 * by chronological value, and all other columns alphabetically -- where the
 * ordering key of each row is the displayed text of its cell in that column.
 *
 * Validates: Requirements 1.1, 1.2, 2.1, 2.2, 2.3, 2.4
 *
 * Strategy: generate tables with random numeric / date / text columns (plus the
 * edge cases called out in the design: blanks, '-', 'N/A', currency $1.2345,
 * thousands separators, duration suffixes like 45m, locale dates, mixed-case
 * text, and ragged rows). Build the table via the harness, attach makeSortable,
 * then clickHeader on a not-yet-active sortable column and compare the resulting
 * displayed column order against an independent ascending oracle keyed by the
 * displayed cell text.
 */

const test = require('node:test');
const assert = require('node:assert');
const fc = require('fast-check');

const { buildTable, clickHeader, getColumnTexts, sortHelper } = require('./harness');

const { makeSortable } = sortHelper;

const PROPERTY_TAG =
    'Feature: sortable-table-headers, Property 1: Type-aware ascending ordering';

// ---------------------------------------------------------------------------
// Independent oracle. These mirror the type-detection / comparison rules stated
// in the design (numeric-before-date, placeholders ignored for detection and
// sorted to the end for comparison, text via locale-insensitive compare) but are
// implemented here from scratch so the test does not simply re-run the code
// under test.
// ---------------------------------------------------------------------------

const PLACEHOLDERS = ['', '-', 'N/A'];

function isBlank(v) {
    return PLACEHOLDERS.indexOf(v) !== -1;
}

function oracleIsNumeric(v) {
    if (typeof v !== 'string') return false;
    const stripped = v.replace(/[$,\s]/g, '').replace(/(m|s|h)$/i, '');
    return stripped !== '' && !isNaN(Number(stripped));
}

function oracleToNumber(v) {
    return parseFloat(String(v).replace(/[^0-9.\-]/g, ''));
}

function oracleIsDate(v) {
    return !oracleIsNumeric(v) && !Number.isNaN(Date.parse(v));
}

function oracleToDate(v) {
    return Date.parse(v);
}

function oracleDetectType(values) {
    const meaningful = values.filter(function (v) {
        return !isBlank(v);
    });
    if (meaningful.length === 0) return 'text';
    if (meaningful.every(oracleIsNumeric)) return 'numeric';
    if (meaningful.every(oracleIsDate)) return 'date';
    return 'text';
}

/**
 * Produce the expected ascending order of displayed column texts. Rows are
 * carried with their original index so the ordering uses the same stable
 * tiebreaker (original position) the implementation applies to equal keys.
 */
function oracleAscending(values) {
    const type = oracleDetectType(values);
    const decorated = values.map(function (v, i) {
        return { key: v, index: i };
    });

    decorated.sort(function (a, b) {
        const aBlank = isBlank(a.key);
        const bBlank = isBlank(b.key);
        // Blanks/placeholders sort to the end regardless of type/direction.
        if (aBlank && bBlank) return a.index - b.index;
        if (aBlank) return 1;
        if (bBlank) return -1;

        let c;
        if (type === 'numeric') {
            c = oracleToNumber(a.key) - oracleToNumber(b.key);
        } else if (type === 'date') {
            c = oracleToDate(a.key) - oracleToDate(b.key);
        } else {
            c = a.key.localeCompare(b.key, undefined, {
                numeric: false,
                sensitivity: 'base',
            });
        }
        if (c !== 0) return c;
        return a.index - b.index; // stable tiebreaker
    });

    return decorated.map(function (d) {
        return d.key;
    });
}

// ---------------------------------------------------------------------------
// Generators. Each column has a "kind" and produces cell texts of that kind,
// interspersed with placeholder values to exercise the blank-handling path.
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

// Locale date strings shaped like toLocaleDateString() / ISO output.
const dateValueArb = fc
    .date({ min: new Date('2000-01-01'), max: new Date('2035-12-31') })
    .map(function (d) {
        const mm = d.getUTCMonth() + 1;
        const dd = d.getUTCDate();
        const yyyy = d.getUTCFullYear();
        return mm + '/' + dd + '/' + yyyy;
    });

// Mixed-case text tokens (kept free of leading/trailing whitespace so trimming
// in getCellText/getColumnTexts does not change the compared value).
const textValueArb = fc
    .stringMatching(/^[A-Za-z][A-Za-z0-9]{0,9}$/)
    .filter(function (s) {
        // Exclude values the detector would read as numeric/date so a "text"
        // column stays genuinely text-typed.
        return !oracleIsNumeric(s) && !oracleIsDate(s);
    });

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
 * cell values) plus optional ragged rows. Returns { headers, rows, columnKinds }.
 */
const tableSpecArb = fc
    .record({
        columnKinds: fc.array(columnKindArb, { minLength: 1, maxLength: 4 }),
        rowCount: fc.integer({ min: 1, max: 12 }),
        ragged: fc.boolean(),
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
            // columns[c][r] -> value; assemble row-major cell matrix.
            const rows = [];
            for (let r = 0; r < shape.rowCount; r++) {
                const row = [];
                for (let c = 0; c < shape.columnKinds.length; c++) {
                    row.push(columns[c][r]);
                }
                rows.push(row);
            }

            // Optionally make one row ragged (fewer cells) to cover the
            // ragged-rows edge case; only when there is more than one column so
            // at least one sortable column with data remains.
            if (shape.ragged && shape.columnKinds.length > 1 && rows.length > 0) {
                rows[rows.length - 1] = rows[rows.length - 1].slice(0, 1);
            }

            const headers = shape.columnKinds.map(function (_kind, i) {
                return 'Col' + i;
            });

            return { headers: headers, rows: rows };
        });
    });

// ---------------------------------------------------------------------------
// Property.
// ---------------------------------------------------------------------------

test(PROPERTY_TAG, () => {
    fc.assert(
        fc.property(
            tableSpecArb,
            fc.integer({ min: 0, max: 100 }),
            function (spec, colSelector) {
                const table = buildTable(spec.headers, spec.rows, {
                    className: 'property1-table',
                    attach: true,
                });

                makeSortable(table);

                // Pick a sortable column. With generic 'ColN' headers none match
                // 'actions', so every column is sortable. Choose deterministically
                // from the random selector so different columns are exercised.
                const colCount = spec.headers.length;
                const colIndex = colSelector % colCount;

                // Snapshot the displayed key of each row for this column, then
                // compute the independent ascending expectation.
                const before = getColumnTexts(table, colIndex);
                const expected = oracleAscending(before);

                // The column is not currently active (fresh makeSortable), so a
                // single click sorts ascending (Req 1.2).
                clickHeader(table, colIndex);

                const after = getColumnTexts(table, colIndex);

                assert.deepStrictEqual(
                    after,
                    expected,
                    'ascending order mismatch for column ' +
                        colIndex +
                        ' (keys before: ' +
                        JSON.stringify(before) +
                        ')'
                );

                // Cleanup so attached tables don't accumulate across runs.
                if (table.parentNode) {
                    table.parentNode.removeChild(table);
                }
            }
        ),
        { numRuns: 200 }
    );
});
