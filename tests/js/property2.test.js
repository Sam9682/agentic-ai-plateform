'use strict';

/**
 * Property test — Property 2: Direction toggles on repeated clicks (task 6.3).
 *
 * Property 2 (design.md): For any rendered table and any sortable column, a
 * second consecutive click on the same header reverses the ordering relative to
 * the first click (ascending becomes descending), and a further click reverses
 * it again, so odd clicks yield ascending and even clicks yield descending;
 * equal-keyed rows retain their relative order under the stable tiebreaker.
 *
 * Validates: Requirements 1.3
 * Tag: Feature: sortable-table-headers, Property 2
 *
 * Strategy: build tables from randomized numeric / date / text columns
 * (including the design's edge-case values: '', '-', 'N/A' placeholders,
 * currency '$1.2345', thousands separators '1,024', duration suffixes '45m',
 * locale date strings, and mixed-case text), attach makeSortable, then click a
 * sortable header N times. After each click the observed row order is compared
 * against an independently computed reference order: a stable decorate-sort of
 * the ORIGINAL rows using the helper's own comparator with the expected
 * direction (asc on odd clicks, desc on even clicks) and the original row index
 * as tiebreaker. Because equal keys break ties by original index in both the
 * implementation and the reference, matching the reference simultaneously
 * proves the odd/even direction toggle and the stable relative order of
 * equal-keyed rows.
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

const { makeSortable, detectColumnType, buildComparator } = sortHelper;

const NUM_RUNS = 200; // >= 100 iterations required by the design.

// A unique tag per row so we can track individual rows through reorders and
// assert relative-order stability of equal-keyed rows. Placed in an extra
// (non-sorted) column so it never influences the sort of the target column.
const TAG_HEADER = '__rowtag__';

// ---------------------------------------------------------------------------
// Generators — one per column type, seeded with the design's edge cases.
// ---------------------------------------------------------------------------

// Numeric renderings the templates emit, plus plain ints/decimals.
const numericValue = fc.oneof(
    fc.integer({ min: -500, max: 500 }).map(String),
    fc.float({ min: -100, max: 100, noNaN: true }).map((n) => n.toFixed(2)),
    fc.constantFrom('$1.2345', '$0.99', '$12.00', '1,024', '2,048', '45m', '30s', '2h'),
);

// Locale-ish date strings shaped like toLocaleDateString()/ISO output.
const dateValue = fc.constantFrom(
    '1/15/2024', '3/2/2024', '12/31/2023', '2024-01-15', '2023-12-31',
    '6/1/2022', '2025-07-04', '11/30/2021', '2020-02-29',
);

// Mixed-case text values.
const textValue = fc.constantFrom(
    'alpha', 'Bravo', 'charlie', 'Delta', 'echo', 'ECHO', 'foxtrot',
    'golf', 'Hotel', 'india',
);

// Placeholder / blank values that must sort to the end regardless of direction.
const placeholder = fc.constantFrom('', '-', 'N/A');

/**
 * Build a generator that yields { type, values } where `values` is the array of
 * sort-column cell texts (some replaced by placeholders) and `type` records the
 * intended base column type for documentation.
 */
function columnArb() {
    return fc.integer({ min: 2, max: 8 }).chain((rowCount) => {
        const base = fc.oneof(
            fc.record({ kind: fc.constant('numeric'), gen: fc.constant(numericValue) }),
            fc.record({ kind: fc.constant('date'), gen: fc.constant(dateValue) }),
            fc.record({ kind: fc.constant('text'), gen: fc.constant(textValue) }),
        );
        return base.chain(({ kind, gen }) => {
            // Each cell is either a real value of the chosen kind or (rarely) a
            // placeholder, so columns mix meaningful and blank keys.
            const cell = fc.oneof(
                { weight: 5, arbitrary: gen },
                { weight: 1, arbitrary: placeholder },
            );
            return fc
                .array(cell, { minLength: rowCount, maxLength: rowCount })
                .map((values) => ({ kind, values }));
        });
    });
}

// ---------------------------------------------------------------------------
// Reference order: an independent stable sort of the ORIGINAL rows, matching
// the helper's own decorate-sort (comparator + original-index tiebreaker).
// ---------------------------------------------------------------------------

/**
 * Compute the expected sort-column text order after `clicks` clicks on a fresh
 * column, given the original column values.
 *
 * @param {string[]} originalValues
 * @param {number} clicks - number of consecutive clicks (>= 1).
 * @returns {string[]} expected column texts, in the expected DOM order.
 */
function expectedOrder(originalValues, clicks) {
    // A new column starts ascending; each subsequent click toggles. So odd
    // clicks are ascending, even clicks are descending.
    const dir = clicks % 2 === 1 ? 'asc' : 'desc';
    const type = detectColumnType(originalValues);
    const cmp = buildComparator(type, dir);

    const decorated = originalValues.map((key, index) => ({ key, index }));
    decorated.sort((a, b) => {
        const c = cmp(a.key, b.key);
        if (c !== 0) return c;
        return a.index - b.index; // stable tiebreaker on ORIGINAL index
    });
    return decorated.map((d) => d.key);
}

// ---------------------------------------------------------------------------
// Property 2 test.
// ---------------------------------------------------------------------------

test(
    'Feature: sortable-table-headers, Property 2: Direction toggles on repeated clicks',
    () => {
        fc.assert(
            fc.property(
                columnArb(),
                fc.integer({ min: 1, max: 6 }), // number of consecutive clicks
                ({ values }, clicks) => {
                    // Sort column is column 0; a trailing tag column (never
                    // sorted) tracks each row's identity for the stability check.
                    const headers = ['Value', TAG_HEADER];
                    const rows = values.map((v, i) => [v, 'row' + i]);

                    const table = buildTable(headers, rows, { attach: true });
                    makeSortable(table);

                    // Click the sortable header the chosen number of times.
                    for (let i = 0; i < clicks; i++) {
                        clickHeader(table, 0);
                    }

                    // 1) Odd clicks => ascending, even clicks => descending:
                    //    observed order must equal the independently computed
                    //    reference order for the expected direction.
                    const observed = getColumnTexts(table, 0);
                    const expected = expectedOrder(values, clicks);
                    assert.deepStrictEqual(
                        observed,
                        expected,
                        'column order after ' + clicks + ' click(s) must match the ' +
                            (clicks % 2 === 1 ? 'ascending' : 'descending') + ' reference order',
                    );

                    // 2) Equal-keyed rows retain their relative order under the
                    //    stable tiebreaker: for rows sharing the same sort key,
                    //    their original tag order (row0, row1, ...) is preserved.
                    const tags = getColumnTexts(table, 1);
                    const keyByTag = {};
                    rows.forEach((r) => {
                        keyByTag[r[1]] = r[0];
                    });
                    const seenIndexByKey = {};
                    for (let i = 0; i < tags.length; i++) {
                        const key = keyByTag[tags[i]];
                        const origIndex = Number(tags[i].slice(3)); // 'row12' -> 12
                        if (key in seenIndexByKey) {
                            assert.ok(
                                origIndex > seenIndexByKey[key],
                                'equal-keyed rows must keep original relative order (key "' +
                                    key + '")',
                            );
                        }
                        seenIndexByKey[key] = origIndex;
                    }

                    // Clean up so the shared jsdom body doesn't accumulate tables.
                    table.remove();
                    return true;
                },
            ),
            { numRuns: NUM_RUNS },
        );
    },
);
