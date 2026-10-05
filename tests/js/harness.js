'use strict';

/**
 * jsdom-based test harness for the dashboard Sort_Helper.
 *
 * Provides:
 *   - a jsdom document/window shared by tests,
 *   - access to the Sort_Helper functions exported from
 *     templates/dashboard_functions.js,
 *   - buildTable(headers, rows, options): construct a table matching the markup
 *     shape the dashboard render functions produce, and
 *   - clickHeader(table, colIndex): dispatch a click event on a header cell.
 */

const path = require('path');
const { JSDOM } = require('jsdom');

// Spin up a jsdom environment and publish the usual browser globals so that
// dashboard_functions.js (and the harness helpers) can build DOM nodes.
const dom = new JSDOM('<!DOCTYPE html><html><body></body></html>', {
    url: 'http://localhost/',
});

const { window } = dom;
const { document } = window;

// Expose the globals the module code touches when constructing DOM nodes.
global.window = window;
global.document = document;
if (!global.Node) global.Node = window.Node;
if (!global.HTMLElement) global.HTMLElement = window.HTMLElement;

// Load the Sort_Helper functions. dashboard_functions.js guards its
// module.exports so requiring it here yields the sort helpers as plain
// functions. Nothing in that module runs browser-only code at load time.
const sortHelperPath = path.resolve(
    __dirname,
    '..',
    '..',
    'templates',
    'dashboard_functions.js'
);
const sortHelper = require(sortHelperPath);

/**
 * Build a table whose markup matches what the dashboard render functions
 * produce: a <table> containing a <thead> with a single header row of <th>
 * cells, and a <tbody> with one <tr> of <td> cells per row.
 *
 * Each row entry may be:
 *   - a string  -> becomes the cell's text content, or
 *   - an object { html } -> the cell's innerHTML is set to the provided markup
 *     (used to reproduce nested markup like <span>, <a>, <select> that the
 *     render functions emit).
 *
 * @param {string[]} headers - column header labels.
 * @param {Array<Array<string|{html:string}>>} rows - body rows.
 * @param {Object} [opts]
 * @param {string} [opts.className] - class attribute for the <table>
 *        (e.g. 'users-table', 'database-table').
 * @param {Document} [opts.doc] - document to build in (defaults to the harness doc).
 * @param {boolean} [opts.attach=false] - append the table to document.body.
 * @returns {HTMLTableElement}
 */
function buildTable(headers, rows, opts) {
    const options = opts || {};
    const doc = options.doc || document;

    const table = doc.createElement('table');
    if (options.className) {
        table.className = options.className;
    }

    const thead = doc.createElement('thead');
    const headerRow = doc.createElement('tr');
    for (const label of headers) {
        const th = doc.createElement('th');
        th.textContent = label;
        headerRow.appendChild(th);
    }
    thead.appendChild(headerRow);
    table.appendChild(thead);

    const tbody = doc.createElement('tbody');
    for (const row of rows) {
        const tr = doc.createElement('tr');
        for (const cell of row) {
            const td = doc.createElement('td');
            if (cell && typeof cell === 'object' && 'html' in cell) {
                td.innerHTML = cell.html;
            } else {
                td.textContent = cell == null ? '' : String(cell);
            }
            tr.appendChild(td);
        }
        tbody.appendChild(tr);
    }
    table.appendChild(tbody);

    if (options.attach) {
        doc.body.appendChild(table);
    }

    return table;
}

/**
 * Dispatch a bubbling click event on the header cell at colIndex.
 *
 * @param {HTMLTableElement} table
 * @param {number} colIndex
 * @returns {void}
 */
function clickHeader(table, colIndex) {
    const headerCells = table.querySelectorAll('thead th');
    const th = headerCells[colIndex];
    if (!th) {
        throw new Error('No header cell at index ' + colIndex);
    }
    const evt = new window.Event('click', { bubbles: true, cancelable: true });
    th.dispatchEvent(evt);
}

/**
 * Return the trimmed text content of each cell in the given column across all
 * <tbody> rows, in current DOM order. Useful for asserting row ordering.
 *
 * @param {HTMLTableElement} table
 * @param {number} colIndex
 * @returns {string[]}
 */
function getColumnTexts(table, colIndex) {
    const rows = table.querySelectorAll('tbody > tr');
    return Array.from(rows).map((tr) => {
        const cell = tr.children[colIndex];
        return cell ? (cell.textContent || '').trim() : '';
    });
}

module.exports = {
    window,
    document,
    dom,
    buildTable,
    clickHeader,
    getColumnTexts,
    sortHelper,
};
