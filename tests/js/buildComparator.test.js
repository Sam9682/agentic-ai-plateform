'use strict';

/**
 * Unit tests for buildComparator (task 3.2).
 *
 * buildComparator(type, dir) returns a compare function suitable for
 * Array.prototype.sort. These tests validate the comparator by sorting a small
 * array of displayed cell texts and asserting the resulting order:
 *   - numeric columns order by numeric value (via toNumber),
 *   - date columns order chronologically (via toDate),
 *   - text columns order alphabetically (via localeCompare), and
 *   - empty/placeholder keys ('', '-', 'N/A') sort to the end regardless of
 *     the requested direction.
 *
 * Requirements: 2.1, 2.2, 2.3
 */

const test = require('node:test');
const assert = require('node:assert');

const { sortHelper } = require('./harness');

const { buildComparator } = sortHelper;

/** Sort a copy of `values` with a fresh comparator and return the new order. */
function sortedWith(type, dir, values) {
    return values.slice().sort(buildComparator(type, dir));
}

// --- Numeric ordering (Req 2.1) -------------------------------------------

test('numeric ascending orders by numeric value, not lexicographically (Req 2.1)', () => {
    // Lexicographic order would put '10' before '2'; numeric must not.
    const input = ['10', '2', '1', '42'];
    assert.deepStrictEqual(
        sortedWith('numeric', 'asc', input),
        ['1', '2', '10', '42']
    );
});

test('numeric descending reverses numeric order (Req 2.1)', () => {
    const input = ['10', '2', '1', '42'];
    assert.deepStrictEqual(
        sortedWith('numeric', 'desc', input),
        ['42', '10', '2', '1']
    );
});

test('numeric ordering parses currency, separators, and duration suffixes (Req 2.1)', () => {
    // $1.2345 -> 1.2345, 1,024 -> 1024, 45m -> 45, 12 -> 12
    const input = ['1,024', '$1.2345', '45m', '12'];
    assert.deepStrictEqual(
        sortedWith('numeric', 'asc', input),
        ['$1.2345', '12', '45m', '1,024']
    );
});

// --- Date ordering (Req 2.2) ----------------------------------------------

test('date ascending orders chronologically (Req 2.2)', () => {
    const input = ['3/2/2024', '1/15/2024', '12/31/2023'];
    assert.deepStrictEqual(
        sortedWith('date', 'asc', input),
        ['12/31/2023', '1/15/2024', '3/2/2024']
    );
});

test('date descending reverses chronological order (Req 2.2)', () => {
    const input = ['3/2/2024', '1/15/2024', '12/31/2023'];
    assert.deepStrictEqual(
        sortedWith('date', 'desc', input),
        ['3/2/2024', '1/15/2024', '12/31/2023']
    );
});

// --- Text ordering (Req 2.3) ----------------------------------------------

test('text ascending orders alphabetically, case-insensitively (Req 2.3)', () => {
    const input = ['charlie', 'Alpha', 'bravo'];
    assert.deepStrictEqual(
        sortedWith('text', 'asc', input),
        ['Alpha', 'bravo', 'charlie']
    );
});

test('text descending reverses alphabetical order (Req 2.3)', () => {
    const input = ['charlie', 'Alpha', 'bravo'];
    assert.deepStrictEqual(
        sortedWith('text', 'desc', input),
        ['charlie', 'bravo', 'Alpha']
    );
});

// --- Placeholder/blank keys sort to the end regardless of direction -------

test('blank/placeholder keys sort to the end in numeric ascending (Req 2.1)', () => {
    const input = ['5', '', '2', '-', '10', 'N/A'];
    const result = sortedWith('numeric', 'asc', input);
    // Meaningful values ascending, then all placeholders trail.
    assert.deepStrictEqual(result.slice(0, 3), ['2', '5', '10']);
    assert.deepStrictEqual(result.slice(3).sort(), ['', '-', 'N/A']);
});

test('blank/placeholder keys still sort to the end in numeric descending (Req 2.1)', () => {
    const input = ['5', '', '2', '-', '10', 'N/A'];
    const result = sortedWith('numeric', 'desc', input);
    assert.deepStrictEqual(result.slice(0, 3), ['10', '5', '2']);
    assert.deepStrictEqual(result.slice(3).sort(), ['', '-', 'N/A']);
});

test('blank/placeholder keys sort to the end for date columns in both directions (Req 2.2)', () => {
    const input = ['1/15/2024', '-', '12/31/2023', 'N/A', '3/2/2024', ''];

    const asc = sortedWith('date', 'asc', input);
    assert.deepStrictEqual(asc.slice(0, 3), ['12/31/2023', '1/15/2024', '3/2/2024']);
    assert.deepStrictEqual(asc.slice(3).sort(), ['', '-', 'N/A']);

    const desc = sortedWith('date', 'desc', input);
    assert.deepStrictEqual(desc.slice(0, 3), ['3/2/2024', '1/15/2024', '12/31/2023']);
    assert.deepStrictEqual(desc.slice(3).sort(), ['', '-', 'N/A']);
});

test('blank/placeholder keys sort to the end for text columns in both directions (Req 2.3)', () => {
    const input = ['bravo', 'N/A', 'Alpha', '', 'charlie', '-'];

    const asc = sortedWith('text', 'asc', input);
    assert.deepStrictEqual(asc.slice(0, 3), ['Alpha', 'bravo', 'charlie']);
    assert.deepStrictEqual(asc.slice(3).sort(), ['', '-', 'N/A']);

    const desc = sortedWith('text', 'desc', input);
    assert.deepStrictEqual(desc.slice(0, 3), ['charlie', 'bravo', 'Alpha']);
    assert.deepStrictEqual(desc.slice(3).sort(), ['', '-', 'N/A']);
});

test('a column of only placeholders compares as equal (all keys blank)', () => {
    const cmp = buildComparator('numeric', 'asc');
    assert.strictEqual(cmp('', '-'), 0);
    assert.strictEqual(cmp('N/A', ''), 0);
    assert.strictEqual(cmp('-', 'N/A'), 0);
});
