'use strict';

/**
 * Integration / wiring tests for each panel that calls makeSortable
 * (task 9.2).
 *
 * For each wired render function this suite builds a table with the SAME
 * markup shape the render function produces (headers + rows, trailing Actions
 * column where applicable, and for deployments the two <select> listbox columns
 * at indices 9 and 10), calls makeSortable with the SAME options the render
 * function uses, then confirms that:
 *   - the sortable headers are clickable (marked data-sortable / cursor pointer,
 *     and carry a click listener), and
 *   - a header click reorders the <tbody> rows.
 *
 * These are 1-3 example assertions per panel, not property-based.
 *
 * _Requirements: 5.1, 5.2_
 */

const test = require('node:test');
const assert = require('node:assert');

const {
    buildTable,
    clickHeader,
    getColumnTexts,
    sortHelper,
} = require('./harness');

const { makeSortable } = sortHelper;

/** True when the header at colIndex has been made clickable by makeSortable. */
function headerIsClickable(table, colIndex) {
    const th = table.querySelectorAll('thead th')[colIndex];
    return !!th && th.getAttribute('data-sortable') === 'true';
}

/** True when the header at colIndex was left non-sortable (Actions/excluded). */
function headerIsNotSortable(table, colIndex) {
    const th = table.querySelectorAll('thead th')[colIndex];
    return !!th && th.getAttribute('data-sortable') !== 'true';
}

// ---------------------------------------------------------------------------
// loadUsers — .users-table
// Columns: ID, Username, Email, First Name, Last Name, Status, 2FA, Created, Actions
// makeSortable(table)  (trailing Actions auto-excluded)
// ---------------------------------------------------------------------------

test('loadUsers panel: headers clickable and a click reorders rows (Req 5.1)', () => {
    const headers = [
        'ID', 'Username', 'Email', 'First Name', 'Last Name',
        'Status', '2FA', 'Created', 'Actions',
    ];
    const table = buildTable(
        headers,
        [
            ['3', 'charlie', 'c@x.com', 'Carol', 'Zed', { html: '<span class="status-active">Active</span>' }, 'No', 'Jan 3, 2024', ''],
            ['1', 'alice', 'a@x.com', 'Alice', 'Ash', { html: '<span class="status-active">Active</span>' }, 'Yes', 'Jan 1, 2024', ''],
            ['2', 'bob', 'b@x.com', 'Bob', 'Bay', { html: '<span class="status-inactive">Inactive</span>' }, 'No', 'Jan 2, 2024', ''],
        ],
        { className: 'users-table', attach: true }
    );

    makeSortable(table);

    // Every data column is clickable; the trailing Actions column is not.
    assert.ok(headerIsClickable(table, 0), 'ID header should be clickable');
    assert.ok(headerIsClickable(table, 1), 'Username header should be clickable');
    assert.ok(headerIsNotSortable(table, 8), 'Actions header must not be sortable');

    // Numeric ID column sorts by value.
    clickHeader(table, 0);
    assert.deepStrictEqual(getColumnTexts(table, 0), ['1', '2', '3']);

    // Username text column sorts alphabetically.
    clickHeader(table, 1);
    assert.deepStrictEqual(getColumnTexts(table, 1), ['alice', 'bob', 'charlie']);
});

// ---------------------------------------------------------------------------
// loadServers — .servers-table
// Columns: ID, IP, Name, Max Users, Max Apps, Status, Type, Created, Actions
// makeSortable(table)
// ---------------------------------------------------------------------------

test('loadServers panel: headers clickable and a click reorders rows (Req 5.1)', () => {
    const headers = [
        'ID', 'IP', 'Name', 'Max Users', 'Max Apps',
        'Status', 'Type', 'Created', 'Actions',
    ];
    const table = buildTable(
        headers,
        [
            ['10', '10.0.0.10', 'srv-z', '100', '20', 'online', 'gpu', 'Mar 1, 2024', ''],
            ['2', '10.0.0.2', 'srv-a', '50', '10', 'offline', 'cpu', 'Jan 1, 2024', ''],
            ['1', '10.0.0.1', 'srv-m', '75', '15', 'online', 'cpu', 'Feb 1, 2024', ''],
        ],
        { className: 'servers-table', attach: true }
    );

    makeSortable(table);

    assert.ok(headerIsClickable(table, 3), 'Max Users header should be clickable');
    assert.ok(headerIsNotSortable(table, 8), 'Actions header must not be sortable');

    // Numeric ID: 1, 2, 10 (not lexical 1, 10, 2).
    clickHeader(table, 0);
    assert.deepStrictEqual(getColumnTexts(table, 0), ['1', '2', '10']);

    // Date Created column sorts chronologically.
    clickHeader(table, 7);
    assert.deepStrictEqual(
        getColumnTexts(table, 7),
        ['Jan 1, 2024', 'Feb 1, 2024', 'Mar 1, 2024']
    );
});

// ---------------------------------------------------------------------------
// loadAppManagement — applications table
// Columns: ID, Name, URL, Description, Git URL, Git Size, Build, Start, Stop,
//          PS, SwAutoMorph URL, Actions
// makeSortable(table)
// ---------------------------------------------------------------------------

test('loadAppManagement panel: headers clickable and a click reorders rows (Req 5.1)', () => {
    const headers = [
        'ID', 'Name', 'URL', 'Description', 'Git URL', 'Git Size',
        'Build', 'Start', 'Stop', 'PS', 'SwAutoMorph URL', 'Actions',
    ];
    const table = buildTable(
        headers,
        [
            ['2', 'zeta', { html: '<a href="https://z">https://z</a>' }, 'desc z', { html: '<a href="https://g/z">git-z</a>' }, '10', '', '', '', '', '', ''],
            ['1', 'alpha', { html: '<a href="https://a">https://a</a>' }, 'desc a', { html: '<a href="https://g/a">git-a</a>' }, '5', '', '', '', '', '', ''],
        ],
        { className: 'applications-table', attach: true }
    );

    makeSortable(table);

    assert.ok(headerIsClickable(table, 1), 'Name header should be clickable');
    assert.ok(headerIsNotSortable(table, 11), 'Actions header must not be sortable');

    // Name text column sorts alphabetically (nested <a> text flattened).
    clickHeader(table, 1);
    assert.deepStrictEqual(getColumnTexts(table, 1), ['alpha', 'zeta']);
});

// ---------------------------------------------------------------------------
// loadAvailableApplications — .applications-table
// Columns: ID, Name, Description, Actions
// makeSortable(table)
// ---------------------------------------------------------------------------

test('loadAvailableApplications panel: headers clickable and a click reorders rows (Req 5.1)', () => {
    const table = buildTable(
        ['ID', 'Name', 'Description', 'Actions'],
        [
            ['3', 'gamma', 'third', ''],
            ['1', 'alpha', 'first', ''],
            ['2', 'beta', 'second', ''],
        ],
        { className: 'applications-table', attach: true }
    );

    makeSortable(table);

    assert.ok(headerIsClickable(table, 1), 'Name header should be clickable');
    assert.ok(headerIsNotSortable(table, 3), 'Actions header must not be sortable');

    clickHeader(table, 1);
    assert.deepStrictEqual(getColumnTexts(table, 1), ['alpha', 'beta', 'gamma']);
});

// ---------------------------------------------------------------------------
// loadBillingSummary — billing table (NO Actions column)
// Columns: User, Application, Duration, Cost
// makeSortable(table)  (all headers sortable)
// ---------------------------------------------------------------------------

test('loadBillingSummary panel: all headers clickable and a click reorders rows (Req 5.1)', () => {
    const table = buildTable(
        ['User', 'Application', 'Duration', 'Cost'],
        [
            ['carol', 'app-z', '45m', '$3.0000'],
            ['alice', 'app-a', '10m', '$1.0000'],
            ['bob', 'app-m', '30m', '$2.0000'],
        ],
        { className: 'billing-table', attach: true }
    );

    makeSortable(table);

    // No Actions column: every header is sortable.
    for (let i = 0; i < 4; i++) {
        assert.ok(headerIsClickable(table, i), `column ${i} should be clickable`);
    }

    // Cost column with currency values sorts numerically.
    clickHeader(table, 3);
    assert.deepStrictEqual(
        getColumnTexts(table, 3),
        ['$1.0000', '$2.0000', '$3.0000']
    );

    // Duration column with the "m" suffix sorts numerically too.
    clickHeader(table, 2);
    assert.deepStrictEqual(getColumnTexts(table, 2), ['10m', '30m', '45m']);
});

// ---------------------------------------------------------------------------
// loadBillingActivities — .billing-table (NO Actions column)
// Columns: User, Application, Action, Started, Stopped, Duration, Cost
// makeSortable(table)  (all headers sortable)
// ---------------------------------------------------------------------------

test('loadBillingActivities panel: all headers clickable and a click reorders rows (Req 5.1)', () => {
    const headers = ['User', 'Application', 'Action', 'Started', 'Stopped', 'Duration', 'Cost'];
    const table = buildTable(
        headers,
        [
            ['bob', 'app-b', 'stop', 'Feb 2, 2024', 'Feb 2, 2024', '20m', '$2.0000'],
            ['alice', 'app-a', 'start', 'Jan 1, 2024', 'Jan 1, 2024', '10m', '$1.0000'],
        ],
        { className: 'billing-table', attach: true }
    );

    makeSortable(table);

    // No Actions column: every header is sortable.
    for (let i = 0; i < headers.length; i++) {
        assert.ok(headerIsClickable(table, i), `column ${i} should be clickable`);
    }

    // User text column sorts alphabetically.
    clickHeader(table, 0);
    assert.deepStrictEqual(getColumnTexts(table, 0), ['alice', 'bob']);

    // Started date column sorts chronologically.
    clickHeader(table, 3);
    assert.deepStrictEqual(getColumnTexts(table, 3), ['Jan 1, 2024', 'Feb 2, 2024']);
});

// ---------------------------------------------------------------------------
// loadDeploymentsTable — .database-table with excludeColumns [9, 10]
// Columns: ID, User ID, App ID, App Name, Status, Path, Git URL, Server ID,
//          SwAutoMorph URL, Modification History (<select>),
//          Backups History (<select>), Actions
// makeSortable(table, { excludeColumns: [9, 10] })
// ---------------------------------------------------------------------------

test('loadDeploymentsTable panel: data headers clickable, listbox+Actions excluded (Req 5.1)', () => {
    const headers = [
        'ID', 'User ID', 'App ID', 'App Name', 'Status', 'Path',
        'Git URL', 'Server ID', 'SwAutoMorph URL',
        'Modification History', 'Backups History', 'Actions',
    ];
    const modSelect = '<select size="3"><option value="v1">branch-a</option></select>';
    const bakSelect = '<select size="3"><option value="b1">2024-01-01 (10MB)</option></select>';
    const table = buildTable(
        headers,
        [
            ['3', '30', '300', 'zeta', 'RUNNING', '/z', { html: '<a href="#">git-z</a>' }, '2', { html: '<a href="#">url-z</a>' }, { html: modSelect }, { html: bakSelect }, ''],
            ['1', '10', '100', 'alpha', 'STOPPED', '/a', { html: '<a href="#">git-a</a>' }, '1', { html: '<a href="#">url-a</a>' }, { html: modSelect }, { html: bakSelect }, ''],
            ['2', '20', '200', 'mu', 'RUNNING', '/m', { html: '<a href="#">git-m</a>' }, '3', { html: '<a href="#">url-m</a>' }, { html: modSelect }, { html: bakSelect }, ''],
        ],
        { className: 'database-table', attach: true }
    );

    makeSortable(table, { excludeColumns: [9, 10] });

    // Data columns clickable; the two listbox columns and Actions are not.
    assert.ok(headerIsClickable(table, 0), 'ID header should be clickable');
    assert.ok(headerIsClickable(table, 3), 'App Name header should be clickable');
    assert.ok(headerIsNotSortable(table, 9), 'Modification History must be excluded');
    assert.ok(headerIsNotSortable(table, 10), 'Backups History must be excluded');
    assert.ok(headerIsNotSortable(table, 11), 'Actions must not be sortable');

    // Numeric ID column sorts by value.
    clickHeader(table, 0);
    assert.deepStrictEqual(getColumnTexts(table, 0), ['1', '2', '3']);

    // App Name text column sorts alphabetically.
    clickHeader(table, 3);
    assert.deepStrictEqual(getColumnTexts(table, 3), ['alpha', 'mu', 'zeta']);
});

test('loadDeploymentsTable panel: clicking an excluded listbox header does not reorder', () => {
    const headers = [
        'ID', 'User ID', 'App ID', 'App Name', 'Status', 'Path',
        'Git URL', 'Server ID', 'SwAutoMorph URL',
        'Modification History', 'Backups History', 'Actions',
    ];
    const sel = '<select size="3"><option value="v">x</option></select>';
    const table = buildTable(
        headers,
        [
            ['2', '20', '200', 'zeta', 'RUNNING', '/z', 'g', '2', 'u', { html: sel }, { html: sel }, ''],
            ['1', '10', '100', 'alpha', 'STOPPED', '/a', 'g', '1', 'u', { html: sel }, { html: sel }, ''],
        ],
        { className: 'database-table', attach: true }
    );

    makeSortable(table, { excludeColumns: [9, 10] });

    const before = getColumnTexts(table, 0);
    clickHeader(table, 9); // excluded listbox column — no-op
    assert.deepStrictEqual(getColumnTexts(table, 0), before, 'excluded column click must not reorder');
});

// ---------------------------------------------------------------------------
// displayTableData — generic .database-table (dynamic columns) + Actions
// makeSortable(table)
// ---------------------------------------------------------------------------

test('displayTableData panel: dynamic headers clickable and a click reorders rows (Req 5.2)', () => {
    // Generic Database Management table: arbitrary columns plus a trailing
    // Actions column.
    const headers = ['id', 'name', 'created_at', 'Actions'];
    const table = buildTable(
        headers,
        [
            ['30', 'gamma', 'Mar 3, 2024', ''],
            ['10', 'alpha', 'Jan 1, 2024', ''],
            ['20', 'beta', 'Feb 2, 2024', ''],
        ],
        { className: 'database-table', attach: true }
    );

    makeSortable(table);

    assert.ok(headerIsClickable(table, 0), 'id header should be clickable');
    assert.ok(headerIsClickable(table, 2), 'created_at header should be clickable');
    assert.ok(headerIsNotSortable(table, 3), 'Actions header must not be sortable');

    // Numeric id column sorts by value.
    clickHeader(table, 0);
    assert.deepStrictEqual(getColumnTexts(table, 0), ['10', '20', '30']);

    // Date column sorts chronologically.
    clickHeader(table, 2);
    assert.deepStrictEqual(
        getColumnTexts(table, 2),
        ['Jan 1, 2024', 'Feb 2, 2024', 'Mar 3, 2024']
    );
});

test('displayTableData panel: ragged rows do not throw and still sort (Req 5.2)', () => {
    // The generic table may produce rows shorter than the header count; missing
    // cells read as '' and sort to the end without raising.
    const table = buildTable(
        ['id', 'name', 'Actions'],
        [
            ['2', 'beta', ''],
            ['1'], // ragged: missing name + actions cells
            ['3', 'alpha', ''],
        ],
        { className: 'database-table', attach: true }
    );

    makeSortable(table);

    assert.doesNotThrow(() => clickHeader(table, 0));
    assert.deepStrictEqual(getColumnTexts(table, 0), ['1', '2', '3']);
});
