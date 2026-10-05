'use strict';

/**
 * Property test — Property 3: Exactly one direction-correct indicator (task 6.4).
 *
 * Feature: sortable-table-headers, Property 3: Exactly one direction-correct
 * indicator — before any header is clicked no header carries a Sort_Indicator;
 * and after any sequence of sortable-header clicks, exactly one header carries an
 * indicator (the most recently clicked column), showing ▲ when its direction is
 * ascending and ▼ when descending, with every previously sorted header's
 * indicator removed.
 *
 * Validates: Requirements 3.1, 3.2, 3.3, 4.2
 *
 * The Sort_Indicator is rendered as the text ' ▲' / ' ▼' inside a dedicated
 * <span class="sort-indicator"> on the active sortable header; every other
 * sortable header's indicator span is empty.
 */

const test = require('node:test');
const assert = require('node:assert');
const fc = require('fast-check');

const {
    buildTable,
    clickHeader,
    sortHelper,
} = require('./harness');

const { makeSortable } = sortHelper;

const ASC = ' ▲';
const DESC = ' ▼';

/**
 * Read the current indicator glyph for each header cell. Returns the trimmed
 * textContent of a header's span.sort-indicator, or '' when the header has no
 * indicator span or an empty one.
 *
 * @param {HTMLTableElement} table
 * @returns {string[]} one entry per <th>, e.g. '▲', '▼', or ''
 */
function indicatorGlyphs(table) {
    const ths = Array.from(table.querySelectorAll('thead th'));
    return ths.map((th) => {
        const span = th.querySelector('span.sort-indicator');
        if (!span) return '';
        return (span.textContent || '').trim();
    });
}

/**
 * Raw (untrimmed) indicator text per header, used to assert the exact ' ▲' /
 * ' ▼' string the implementation writes.
 */
function rawIndicators(table) {
    const ths = Array.from(table.querySelectorAll('thead th'));
    return ths.map((th) => {
        const span = th.querySelector('span.sort-indicator');
        return span ? (span.textContent || '') : '';
    });
}

/**
 * Which header indices are sortable (carry a data-sortable="true" marker after
 * makeSortable attaches). The trailing Actions column and excluded columns are
 * never sortable and never carry an indicator.
 */
function sortableIndices(table) {
    const ths = Array.from(table.querySelectorAll('thead th'));
    const out = [];
    ths.forEach((th, i) => {
        if (th.getAttribute('data-sortable') === 'true') out.push(i);
    });
    return out;
}

// A pool of representative cell values across the column types the design
// exercises: text, numeric (incl. currency / separators / duration), dates,
// and placeholder/blank values.
const CELL_VALUE_POOL = [
    'alpha', 'bravo', 'Charlie', 'delta',
    '1', '10', '2', '42', '1024',
    '$1.2345', '1,024', '45m',
    '2024-01-15', '2023-11-02', 'Jan 5, 2022',
    '', '-', 'N/A',
];

const cellValueArb = fc.constantFrom(...CELL_VALUE_POOL);

/**
 * Generate a random table shape: header labels (last one is the trailing
 * "Actions" column so at least one column is always non-sortable) and a set of
 * body rows filled from the value pool.
 */
const tableShapeArb = fc
    .record({
        // 1..4 sortable data columns plus a trailing Actions column.
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
 * Build a table with `dataCols` data columns named Col0..ColN and a trailing
 * "Actions" column. Rows come straight from the generated value matrix. The
 * Actions cell (last) is always blank markup so it is never meaningfully sorted.
 */
function buildFromShape(shape) {
    const headers = [];
    for (let i = 0; i < shape.dataCols; i++) headers.push('Col' + i);
    headers.push('Actions');
    return buildTable(headers, shape.rows, { className: 'users-table', attach: true });
}

test('Feature: sortable-table-headers, Property 3: Exactly one direction-correct indicator', () => {
    fc.assert(
        fc.property(
            tableShapeArb,
            // A sequence of clicks; each entry selects a sortable header by its
            // position within the sortable set (mapped to a real column later).
            fc.array(fc.integer({ min: 0, max: 10 }), { minLength: 0, maxLength: 8 }),
            (shape, clickSeq) => {
                const table = buildFromShape(shape);
                makeSortable(table);

                const sortables = sortableIndices(table);

                // --- Before any click: no header carries an indicator (Req 4.2).
                const initial = indicatorGlyphs(table);
                assert.ok(
                    initial.every((g) => g === ''),
                    'before any click no header should carry a Sort_Indicator'
                );

                // Guard: with no sortable columns there is nothing to click and
                // the no-indicator invariant already held above.
                if (sortables.length === 0) return true;

                // Track expected active column + direction as we replay clicks,
                // mirroring the helper's per-column asc-first / toggle rules.
                let expectedCol = null;
                let expectedDir = null; // 'asc' | 'desc'

                for (const raw of clickSeq) {
                    const colIndex = sortables[raw % sortables.length];

                    if (colIndex === expectedCol) {
                        expectedDir = expectedDir === 'asc' ? 'desc' : 'asc';
                    } else {
                        expectedCol = colIndex;
                        expectedDir = 'asc';
                    }

                    clickHeader(table, colIndex);

                    const glyphs = indicatorGlyphs(table);
                    const raws = rawIndicators(table);

                    // Exactly one header carries a (non-empty) indicator.
                    const marked = glyphs
                        .map((g, i) => (g !== '' ? i : -1))
                        .filter((i) => i >= 0);
                    assert.strictEqual(
                        marked.length,
                        1,
                        'exactly one header should carry an indicator after a click'
                    );

                    // ...and it is the most recently clicked column.
                    assert.strictEqual(
                        marked[0],
                        expectedCol,
                        'the indicator should be on the most recently clicked column'
                    );

                    // Direction-correct glyph: ▲ ascending, ▼ descending (Req 3.1/3.2).
                    const expectedGlyph = expectedDir === 'asc' ? '▲' : '▼';
                    assert.strictEqual(
                        glyphs[expectedCol],
                        expectedGlyph,
                        'indicator glyph must match the current direction'
                    );
                    assert.strictEqual(
                        raws[expectedCol],
                        expectedDir === 'asc' ? ASC : DESC,
                        'indicator text must be the exact " ▲"/" ▼" the helper writes'
                    );

                    // Every previously sorted / non-active header's indicator was
                    // removed (Req 3.3): all other headers are empty.
                    glyphs.forEach((g, i) => {
                        if (i !== expectedCol) {
                            assert.strictEqual(
                                g,
                                '',
                                'non-active header ' + i + ' must carry no indicator'
                            );
                        }
                    });

                    // The Actions column (and any non-sortable header) never
                    // carries an indicator.
                    glyphs.forEach((g, i) => {
                        if (!sortables.includes(i)) {
                            assert.strictEqual(
                                g,
                                '',
                                'non-sortable header ' + i + ' must never carry an indicator'
                            );
                        }
                    });
                }

                return true;
            }
        ),
        { numRuns: 200 }
    );
});

test('Feature: sortable-table-headers, Property 3: no indicator before the first click (edge cases)', () => {
    fc.assert(
        fc.property(tableShapeArb, (shape) => {
            const table = buildFromShape(shape);
            makeSortable(table);
            const glyphs = indicatorGlyphs(table);
            assert.ok(
                glyphs.every((g) => g === ''),
                'no header should carry an indicator until a sortable header is clicked'
            );
            return true;
        }),
        { numRuns: 100 }
    );
});
