# Dashboard JavaScript tests

jsdom-based test harness for the client-side JavaScript in `templates/`, starting
with the sortable-table-headers feature (`makeSortable` and its helpers in
`templates/dashboard_functions.js`).

## Setup

Requires Node.js (tested with Node 22) and npm.

```bash
cd tests/js
npm install
```

## Running the tests

```bash
cd tests/js
npm test
```

This runs Node's built-in test runner (`node --test`) over every `*.test.js`
file in this directory.

## Harness

`harness.js` boots a jsdom environment, loads the Sort_Helper functions from
`templates/dashboard_functions.js`, and exposes helpers:

- `buildTable(headers, rows, options)` — build a table matching the markup shape
  the dashboard render functions produce. Row cells may be plain strings or
  `{ html }` objects to reproduce nested markup (`<span>`, `<a>`, `<select>`).
- `clickHeader(table, colIndex)` — dispatch a `click` on a header cell.
- `getColumnTexts(table, colIndex)` — read a column's cell texts in DOM order.
- `sortHelper` — the exported Sort_Helper functions.

`fast-check` is available for the property tests defined by later tasks.
