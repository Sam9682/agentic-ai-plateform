'use strict';

/**
 * Unit tests for detectColumnType (task 2.4).
 *
 * Verifies that the Sort_Helper classifies representative numeric, date, and
 * text columns correctly by parsing the displayed cell text, that numeric
 * detection runs before date detection (so "2024" stays numeric), and that
 * placeholder/blank values ('', '-', 'N/A') are ignored when deciding the type.
 *
 * Requirements: 2.1, 2.2, 2.3, 2.4
 */

const test = require('node:test');
const assert = require('node:assert');

const { sortHelper } = require('./harness');

const { detectColumnType } = sortHelper;

test('detectColumnType classifies plain integer columns as numeric (Req 2.1)', () => {
    assert.strictEqual(detectColumnType(['1', '2', '10', '42']), 'numeric');
});

test('detectColumnType classifies decimal / currency / separator / duration values as numeric (Req 2.1, 2.4)', () => {
    // Representative numeric renderings the templates emit: currency, decimals,
    // thousands separators, and short duration suffixes.
    assert.strictEqual(
        detectColumnType(['$1.2345', '12', '1,024', '45m']),
        'numeric'
    );
});

test('detectColumnType classifies locale date strings as dates (Req 2.2)', () => {
    // Values shaped like toLocaleDateString() / toLocaleString() output.
    assert.strictEqual(
        detectColumnType(['1/15/2024', '3/2/2024', '12/31/2023']),
        'date'
    );
    assert.strictEqual(
        detectColumnType(['2024-01-15', '2023-12-31']),
        'date'
    );
});

test('detectColumnType classifies non-numeric, non-date values as text (Req 2.3)', () => {
    assert.strictEqual(
        detectColumnType(['alpha', 'Bravo', 'charlie']),
        'text'
    );
});

test('detectColumnType falls back to text for mixed numeric/text columns (Req 2.3, 2.4)', () => {
    assert.strictEqual(detectColumnType(['1', 'alpha', '3']), 'text');
});

test('detectColumnType keeps a purely numeric "2024" column numeric, not date (numeric-before-date, Req 2.1, 2.4)', () => {
    // A four-digit year on its own parses as a date, but numeric detection must
    // win so year-like counts sort numerically.
    assert.strictEqual(detectColumnType(['2024', '1999', '2001']), 'numeric');
});

test('detectColumnType ignores blank/placeholder values when deciding type (Req 2.4)', () => {
    // A few blanks / placeholders must not force an otherwise-numeric column to text.
    assert.strictEqual(
        detectColumnType(['', '-', 'N/A', '5', '10']),
        'numeric'
    );
    // Same for an otherwise-date column.
    assert.strictEqual(
        detectColumnType(['-', '1/15/2024', 'N/A', '3/2/2024']),
        'date'
    );
});

test('detectColumnType returns text when only blanks/placeholders are present (Req 2.4)', () => {
    assert.strictEqual(detectColumnType(['', '-', 'N/A']), 'text');
    assert.strictEqual(detectColumnType([]), 'text');
});

test('detectColumnType handles missing/undefined input without throwing (Req 2.4)', () => {
    assert.strictEqual(detectColumnType(undefined), 'text');
});
