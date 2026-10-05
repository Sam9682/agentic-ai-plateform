'use strict';

/**
 * Unit tests for applySort and updateIndicators (task 5.3).
 *
 * applySort(table, colIndex) reads/toggles table._sortState, reorders the
 * <tbody> rows by the clicked column's displayed cell text (type-aware, stable
 * tiebreak on original index), and calls updateIndicators.
 *
 * updateIndicators(table, activeIndex, dir) clears the indicator span on every
 * sortable header and writes ▲ (asc) / ▼ (desc) into the active header's
 * dedicated <span class="sort-indicator"> so exactly one header shows a glyph.
 *
 * _Requirements: 1.1, 1.2, 1.3, 3.1, 3.2, 3.3_
 */

const test = require('node:test');
const assert = require('node:assert');

const { buildTable, clickHeader, getColumnTexts, sortHelper } = require('./harness');

const { makeSortable, applySort, updateIndicators } = sortHelper;

/** Return the trimmed indicator-span text for each header (empty if none). */
function indicatorTexts(table) {
    const ths = table.querySelectorAll('thead th');
    return Array.from(ths).map((th) => {
        const span = th.querySelector('span.sort-indicator');
        return span ? (span.textContent || '').trim() : '';
    });
}

// ---------------------------------------------------------------------------
// applySort — reordering (Req 1.1) and initial ascending direction (Req 1.2)
// ---------------------------------------------------------------------------

test('applySort reorders text rows ascending on a new column (Req 1.1, 1.2)', () => {
    const table = buildTable(
        ['Name', 'Actions'],
        [['charlie', ''], ['alpha', ''], ['bravo', '']],
        { className: 'users-table' }
    );
    makeSortable(table);

    applySort(table, 0);

    assert.deepStrictEqual(getColumnTexts(table, 0), ['alpha', 'bravo', 'charlie']);
    assert.strictEqual(table._sortState.colIndex, 0);
    assert.strictEqual(table._sortState.dir, 'asc');
});

test('applySort orders a numeric column by value, not lexically (Req 1.1)', () => {
    const table = buildTable(
        ['Count', 'Actions'],
        [['10', ''], ['2', ''], ['1', '']],
        { className: 'users-table' }
    );
    makeSortable(table);

    applySort(table, 0);

    // Numeric ordering: 1, 2, 10 (a lexical sort would give 1, 10, 2).
    assert.deepStrictEqual(getColumnTexts(table, 0), ['1', '2', '10']);
});

test('applySort orders a date column chronologically (Req 1.1)', () => {
    const table = buildTable(
        ['When', 'Actions'],
        [['Mar 3, 2024', ''], ['Jan 1, 2024', ''], ['Feb 2, 2024', '']],
        { className: 'users-table' }
    );
    makeSortable(table);

    applySort(table, 0);

    assert.deepStrictEqual(
        getColumnTexts(table, 0),
        ['Jan 1, 2024', 'Feb 2, 2024', 'Mar 3, 2024']
    );
});

// ---------------------------------------------------------------------------
// applySort — toggle behavior (Req 1.3)
// ---------------------------------------------------------------------------

test('a second click on the same column toggles to descending (Req 1.3)', () => {
    const table = buildTable(
        ['Name', 'Actions'],
        [['charlie', ''], ['alpha', ''], ['bravo', '']],
        { className: 'users-table' }
    );
    makeSortable(table);

    applySort(table, 0);
    assert.deepStrictEqual(getColumnTexts(table, 0), ['alpha', 'bravo', 'charlie']);
    assert.strictEqual(table._sortState.dir, 'asc');

    applySort(table, 0);
    assert.deepStrictEqual(getColumnTexts(table, 0), ['charlie', 'bravo', 'alpha']);
    assert.strictEqual(table._sortState.dir, 'desc');
});

test('odd clicks are ascending and even clicks are descending (Req 1.3)', () => {
    const table = buildTable(
        ['Count', 'Actions'],
        [['3', ''], ['1', ''], ['2', '']],
        { className: 'users-table' }
    );
    makeSortable(table);

    applySort(table, 0); // 1st -> asc
    assert.deepStrictEqual(getColumnTexts(table, 0), ['1', '2', '3']);
    applySort(table, 0); // 2nd -> desc
    assert.deepStrictEqual(getColumnTexts(table, 0), ['3', '2', '1']);
    applySort(table, 0); // 3rd -> asc
    assert.deepStrictEqual(getColumnTexts(table, 0), ['1', '2', '3']);
});

test('sorting a different column resets direction to ascending (Req 1.2, 1.3)', () => {
    const table = buildTable(
        ['Name', 'Count', 'Actions'],
        [['bravo', '2', ''], ['alpha', '3', ''], ['charlie', '1', '']],
        { className: 'users-table' }
    );
    makeSortable(table);

    applySort(table, 0);
    applySort(table, 0); // Name now descending
    assert.strictEqual(table._sortState.dir, 'desc');

    applySort(table, 1); // switch to Count -> starts ascending
    assert.strictEqual(table._sortState.colIndex, 1);
    assert.strictEqual(table._sortState.dir, 'asc');
    assert.deepStrictEqual(getColumnTexts(table, 1), ['1', '2', '3']);
});

// ---------------------------------------------------------------------------
// applySort — stable tiebreak (design: original index tiebreaker, Req 1.1/1.3)
// ---------------------------------------------------------------------------

test('equal keys retain their original relative order (stable tiebreak)', () => {
    // Sort by the "Group" column; rows with equal group keep input order,
    // observed through the unique Id column.
    const table = buildTable(
        ['Group', 'Id', 'Actions'],
        [
            ['b', 'r1', ''],
            ['a', 'r2', ''],
            ['b', 'r3', ''],
            ['a', 'r4', ''],
            ['b', 'r5', ''],
        ],
        { className: 'users-table' }
    );
    makeSortable(table);

    applySort(table, 0);

    // Ascending by group: all 'a' rows (r2, r4) then all 'b' rows (r1, r3, r5),
    // each preserving original relative order.
    assert.deepStrictEqual(getColumnTexts(table, 0), ['a', 'a', 'b', 'b', 'b']);
    assert.deepStrictEqual(getColumnTexts(table, 1), ['r2', 'r4', 'r1', 'r3', 'r5']);
});

test('descending toggle is a clean stable reverse of equal keys', () => {
    const table = buildTable(
        ['Group', 'Id', 'Actions'],
        [
            ['a', 'r1', ''],
            ['a', 'r2', ''],
            ['b', 'r3', ''],
            ['b', 'r4', ''],
        ],
        { className: 'users-table' }
    );
    makeSortable(table);

    applySort(table, 0); // asc: a(r1,r2), b(r3,r4)
    assert.deepStrictEqual(getColumnTexts(table, 1), ['r1', 'r2', 'r3', 'r4']);

    applySort(table, 0); // desc: b group first, equal keys still stable
    assert.deepStrictEqual(getColumnTexts(table, 0), ['b', 'b', 'a', 'a']);
    assert.deepStrictEqual(getColumnTexts(table, 1), ['r3', 'r4', 'r1', 'r2']);
});

// ---------------------------------------------------------------------------
// updateIndicators — single direction-correct indicator (Req 3.1, 3.2, 3.3)
// ---------------------------------------------------------------------------

test('applySort shows exactly one ▲ ascending indicator (Req 3.1)', () => {
    const table = buildTable(
        ['Name', 'Count', 'Actions'],
        [['bravo', '2', ''], ['alpha', '1', '']],
        { className: 'users-table' }
    );
    makeSortable(table);

    applySort(table, 0);

    const indicators = indicatorTexts(table);
    assert.deepStrictEqual(indicators, ['▲', '', '']);
    assert.strictEqual(indicators.filter((t) => t !== '').length, 1);
});

test('a toggle to descending shows ▼ on the active header (Req 3.2)', () => {
    const table = buildTable(
        ['Name', 'Count', 'Actions'],
        [['bravo', '2', ''], ['alpha', '1', '']],
        { className: 'users-table' }
    );
    makeSortable(table);

    applySort(table, 0); // asc -> ▲
    applySort(table, 0); // desc -> ▼

    assert.deepStrictEqual(indicatorTexts(table), ['▼', '', '']);
});

test('sorting a new column moves the indicator and clears the old one (Req 3.3)', () => {
    const table = buildTable(
        ['Name', 'Count', 'Actions'],
        [['bravo', '2', ''], ['alpha', '1', '']],
        { className: 'users-table' }
    );
    makeSortable(table);

    applySort(table, 0);
    assert.deepStrictEqual(indicatorTexts(table), ['▲', '', '']);

    applySort(table, 1);
    const indicators = indicatorTexts(table);
    // Old indicator removed, exactly one shown on the newly sorted column.
    assert.deepStrictEqual(indicators, ['', '▲', '']);
    assert.strictEqual(indicators.filter((t) => t !== '').length, 1);
});

test('updateIndicators never adds a glyph to the excluded Actions column (Req 3.3)', () => {
    const table = buildTable(
        ['Name', 'Actions'],
        [['bravo', ''], ['alpha', '']],
        { className: 'users-table' }
    );
    makeSortable(table);

    // Even if asked directly, the trailing Actions column carries no indicator.
    updateIndicators(table, 1, 'asc');

    assert.deepStrictEqual(indicatorTexts(table), ['', '']);
});

test('clicking a header via the harness reorders and shows the indicator (Req 1.1, 3.1)', () => {
    const table = buildTable(
        ['Name', 'Actions'],
        [['charlie', ''], ['alpha', ''], ['bravo', '']],
        { className: 'users-table', attach: true }
    );
    makeSortable(table);

    clickHeader(table, 0);

    assert.deepStrictEqual(getColumnTexts(table, 0), ['alpha', 'bravo', 'charlie']);
    assert.deepStrictEqual(indicatorTexts(table), ['▲', '']);
});
