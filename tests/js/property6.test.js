'use strict';

/**
 * Property test — Property 6: Sorting is a client-side permutation with no data
 * requests (task 6.7).
 *
 * Feature: sortable-table-headers, Property 6: Sorting is a client-side
 * permutation with no data requests — for any rendered table and any sequence of
 * sort clicks, the resulting set of <tbody> rows is a permutation of the original
 * rows (no row element is added, removed, or mutated) and no network/data
 * request is issued during sorting.
 *
 * Validates: Requirements 6.2
 *
 * Two invariants are checked after every click sequence:
 *   1. Permutation of row identity — the exact same set of <tr> element objects
 *      that existed before sorting is present after sorting; none is created,
 *      dropped, or replaced. Each row is tagged with a stable identity before
 *      sorting so we can compare element sets independent of order.
 *   2. Row content is unmutated — each row's cells keep their original
 *      innerHTML; sorting only re-appends whole <tr> nodes, it never rewrites
 *      cell content.
 *   3. No data request — global fetch / XMLHttpRequest are replaced with spies
 *      that record calls; the count must be zero across the whole click
 *      sequence.
 */

const test = require('node:test');
const assert = require('node:assert');
const fc = require('fast-check');

const {
    window,
    buildTable,
    clickHeader,
    sortHelper,
} = require('./harness');

const { makeSortable } = sortHelper;

// A pool of representative cell values across the column types the design
// exercises: text, numeric (incl. currency / separators / duration), dates,
// and placeholder/blank values (edge cases).
const CELL_VALUE_POOL = [
    'alpha', 'bravo', 'Charlie', 'delta',
    '1', '10', '2', '42', '1024',
    '$1.2345', '1,024', '45m',
    '2024-01-15', '2023-11-02', 'Jan 5, 2022',
    '', '-', 'N/A',
];

const cellValueArb = fc.constantFrom(...CELL_VALUE_POOL);

/**
 * Generate a random table shape: `dataCols` sortable data columns plus a
 * trailing "Actions" column, filled with `rowCount` rows from the value pool.
 */
const tableShapeArb = fc
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
            rows: fc.array(cellArb, {
                minLength: rowCount,
                maxLength: rowCount,
            }),
        });
    });

/**
 * Build a table with `dataCols` data columns named Col0..ColN plus a trailing
 * "Actions" column (auto-excluded). Rows come straight from the value matrix.
 */
function buildFromShape(shape) {
    const headers = [];
    for (let i = 0; i < shape.dataCols; i++) headers.push('Col' + i);
    headers.push('Actions');
    return buildTable(headers, shape.rows, { className: 'users-table', attach: true });
}

/** Header indices that are sortable after makeSortable attaches. */
function sortableIndices(table) {
    const ths = Array.from(table.querySelectorAll('thead th'));
    const out = [];
    ths.forEach((th, i) => {
        if (th.getAttribute('data-sortable') === 'true') out.push(i);
    });
    return out;
}

/** Current <tbody> row elements, in DOM order. */
function bodyRows(table) {
    return Array.from(table.querySelectorAll('tbody > tr'));
}

/**
 * Install spies on any data-request primitives and return a getter for the
 * total number of calls plus a restore function. Covers fetch and
 * XMLHttpRequest on both the jsdom window and the Node globals, so a call
 * through any of them is recorded.
 */
function installRequestSpies() {
    let calls = 0;
    const record = () => { calls += 1; };
    const saved = [];

    const targets = [global, window];
    for (const target of targets) {
        if (!target) continue;

        // fetch
        const originalFetch = target.fetch;
        saved.push({ target, key: 'fetch', value: originalFetch });
        target.fetch = function spyFetch() {
            record();
            return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
        };

        // XMLHttpRequest — count on send() (an actual request being issued).
        const OriginalXHR = target.XMLHttpRequest;
        saved.push({ target, key: 'XMLHttpRequest', value: OriginalXHR });
        target.XMLHttpRequest = function SpyXHR() {
            return {
                open() {},
                setRequestHeader() {},
                send() { record(); },
                abort() {},
                addEventListener() {},
            };
        };
    }

    return {
        getCalls: () => calls,
        restore() {
            for (const { target, key, value } of saved) {
                if (value === undefined) {
                    delete target[key];
                } else {
                    target[key] = value;
                }
            }
        },
    };
}

test('Feature: sortable-table-headers, Property 6: Sorting is a client-side permutation with no data requests', () => {
    const spies = installRequestSpies();
    try {
        fc.assert(
            fc.property(
                tableShapeArb,
                // A sequence of clicks; each entry selects a sortable header by
                // position within the sortable set (mapped to a real column).
                fc.array(fc.integer({ min: 0, max: 10 }), { minLength: 0, maxLength: 8 }),
                (shape, clickSeq) => {
                    const table = buildFromShape(shape);
                    makeSortable(table);

                    // Snapshot the original rows and tag each with a stable
                    // identity and a snapshot of its cell markup so we can detect
                    // additions, removals, or mutations.
                    const originalRows = bodyRows(table);
                    const originalSet = new Set(originalRows);
                    originalRows.forEach((tr, i) => {
                        tr.setAttribute('data-row-id', String(i));
                        tr._cellSnapshot = Array.from(tr.children).map(
                            (td) => td.innerHTML
                        );
                    });

                    const sortables = sortableIndices(table);

                    // Replay the click sequence (no-op when nothing is sortable).
                    for (const raw of clickSeq) {
                        if (sortables.length === 0) break;
                        const colIndex = sortables[raw % sortables.length];
                        clickHeader(table, colIndex);
                    }

                    const afterRows = bodyRows(table);

                    // (1) Same count — no row added or removed.
                    assert.strictEqual(
                        afterRows.length,
                        originalRows.length,
                        'row count must be unchanged after sorting'
                    );

                    // (2) Permutation of identity — every resulting row is one of
                    // the original element objects, and the sets match exactly.
                    const afterSet = new Set(afterRows);
                    assert.strictEqual(
                        afterSet.size,
                        afterRows.length,
                        'no duplicate row elements after sorting'
                    );
                    for (const tr of afterRows) {
                        assert.ok(
                            originalSet.has(tr),
                            'every resulting row must be an original row element'
                        );
                    }
                    for (const tr of originalRows) {
                        assert.ok(
                            afterSet.has(tr),
                            'no original row element may be dropped'
                        );
                    }

                    // (3) Rows are not mutated — cell markup is preserved.
                    for (const tr of afterRows) {
                        const snap = tr._cellSnapshot;
                        const now = Array.from(tr.children).map((td) => td.innerHTML);
                        assert.deepStrictEqual(
                            now,
                            snap,
                            'row cell content must be unchanged by sorting'
                        );
                    }

                    // (4) No data request was issued during any of the sorts.
                    assert.strictEqual(
                        spies.getCalls(),
                        0,
                        'sorting must not issue any network/data request'
                    );

                    // Clean up the attached table so document.body does not grow.
                    if (table.parentNode) table.parentNode.removeChild(table);

                    return true;
                }
            ),
            { numRuns: 200 }
        );
    } finally {
        spies.restore();
    }
});

test('Feature: sortable-table-headers, Property 6: permutation holds for placeholder-heavy and empty tables (edge cases)', () => {
    const spies = installRequestSpies();
    try {
        // A few explicit edge shapes: an empty table, an all-placeholder table,
        // and a single-row table — each clicked across every sortable column.
        const edgeShapes = [
            { dataCols: 2, rows: [] },
            { dataCols: 2, rows: [['', ''], ['-', 'N/A'], ['', '-']] },
            { dataCols: 3, rows: [['alpha', '1', '2024-01-15']] },
        ];

        for (const shape of edgeShapes) {
            const table = buildFromShape(shape);
            makeSortable(table);

            const originalRows = bodyRows(table);
            const originalSet = new Set(originalRows);
            originalRows.forEach((tr, i) => {
                tr._cellSnapshot = Array.from(tr.children).map((td) => td.innerHTML);
                tr.setAttribute('data-row-id', String(i));
            });

            const sortables = sortableIndices(table);
            // Click every sortable column twice (asc then desc).
            for (const colIndex of sortables) {
                clickHeader(table, colIndex);
                clickHeader(table, colIndex);
            }

            const afterRows = bodyRows(table);
            assert.strictEqual(afterRows.length, originalRows.length);
            const afterSet = new Set(afterRows);
            for (const tr of afterRows) {
                assert.ok(originalSet.has(tr));
            }
            for (const tr of originalRows) {
                assert.ok(afterSet.has(tr));
            }
            for (const tr of afterRows) {
                const now = Array.from(tr.children).map((td) => td.innerHTML);
                assert.deepStrictEqual(now, tr._cellSnapshot);
            }

            if (table.parentNode) table.parentNode.removeChild(table);
        }

        assert.strictEqual(
            spies.getCalls(),
            0,
            'no data request should be issued for any edge-case table'
        );
    } finally {
        spies.restore();
    }
});
