'use strict';

/**
 * Property and example tests for the dashboard-running-app-highlight feature.
 *
 * These tests exercise the state -> color mapping used by the dashboard's
 * inline status-styling block, via the importable helpers added in task 1.1
 * (resolveAppCardStatus / statusToBackgroundColor / resolveAppCardBackgroundColor
 * plus the RUNNING_BACKGROUND_COLOR / NOT_RUNNING_BACKGROUND_COLOR constants).
 *
 * The mapping is applied to a lightweight fake `appCard` exposing
 * `style.backgroundColor`, mirroring what the real template does
 * (`appCard.style.backgroundColor = <color>`), so no full DOM is required.
 *
 * Tasks covered: 4.1, 4.2, 4.3, 4.4, 5.1.
 */

const test = require('node:test');
const assert = require('node:assert');
const fc = require('fast-check');

const { sortHelper } = require('./harness');

const {
    RUNNING_BACKGROUND_COLOR,
    NOT_RUNNING_BACKGROUND_COLOR,
    resolveAppCardStatus,
    resolveAppCardBackgroundColor,
} = sortHelper;

const SOFT_GREEN = '#d4edda';
const SOFT_RED = '#f8d7da';

// ---------------------------------------------------------------------------
// Fake AppCard: a minimal object exposing style.backgroundColor, matching the
// only surface the styling logic touches. applyStyling mirrors the template's
// `appCard.style.backgroundColor = resolveAppCardBackgroundColor(logs)` for the
// running/not-running branches, and leaves the background untouched for Other
// (the resolver returns '' meaning "no highlight / unchanged").
// ---------------------------------------------------------------------------

function makeFakeAppCard(initialColor) {
    return {
        style: { backgroundColor: initialColor === undefined ? '' : initialColor },
    };
}

/**
 * Apply the state->color styling to a fake appCard for the given raw logs.
 * Only assigns the background when the resolver yields a highlight color, so an
 * Other_State genuinely leaves the pre-existing background "unchanged" (matching
 * Requirement 2.2 / design: the Other branches keep their existing assignment).
 */
function applyStyling(appCard, logs) {
    const color = resolveAppCardBackgroundColor(logs);
    if (color !== '') {
        appCard.style.backgroundColor = color;
    }
    return appCard.style.backgroundColor;
}

// ---------------------------------------------------------------------------
// Generators. Each produces raw `logs` text that resolves to a specific state
// through the same paths the real resolver uses (JSON docker_compose_ps after a
// STDOUT: marker, or raw IS_RUNNING / IS_NOT_RUNNING substring fallback).
// ---------------------------------------------------------------------------

// Arbitrary free-form noise that does NOT itself trigger any state marker.
const noiseArb = fc
    .string({ maxLength: 40 })
    .filter(function (s) {
        const lower = s.toLowerCase();
        return (
            !s.includes('IS_RUNNING') &&
            !s.includes('IS_NOT_RUNNING') &&
            !lower.includes('deployapp.sh not found') &&
            !lower.includes('application not deployed') &&
            !lower.includes('clone it first')
        );
    });

// Running_State inputs: JSON path and raw-substring fallback path.
const runningJsonArb = noiseArb.map(function (prefix) {
    return prefix + '\nSTDOUT:\n' + JSON.stringify({ docker_compose_ps: 'IS_RUNNING' });
});
const runningRawArb = noiseArb.map(function (prefix) {
    return prefix + ' IS_RUNNING';
});
const runningArb = fc.oneof(runningJsonArb, runningRawArb);

// Not_Running_State inputs: JSON path and raw-substring fallback path.
const notRunningJsonArb = noiseArb.map(function (prefix) {
    return prefix + '\nSTDOUT:\n' + JSON.stringify({ docker_compose_ps: 'IS_NOT_RUNNING' });
});
const notRunningRawArb = noiseArb.map(function (prefix) {
    return prefix + ' IS_NOT_RUNNING';
});
const notRunningArb = fc.oneof(notRunningJsonArb, notRunningRawArb);

// Other_State inputs: cloned-but-not-compliant, not-cloned, and generic noise
// with no running markers at all.
const otherArb = fc.oneof(
    noiseArb.map(function (s) {
        return s + ' deployApp.sh not found';
    }),
    noiseArb.map(function (s) {
        return s + ' Application not deployed';
    }),
    noiseArb.map(function (s) {
        return s + ' clone it first';
    }),
    noiseArb // plain noise -> no marker -> Other
);

// ---------------------------------------------------------------------------
// Task 4.1 - Property 1: Running state yields Soft_Green (idempotent).
// ---------------------------------------------------------------------------

test('Feature: dashboard-running-app-highlight, Property 1: Running state yields Soft_Green (idempotent)', () => {
    // Guard the constant matches the design value so the mapping is meaningful.
    assert.strictEqual(RUNNING_BACKGROUND_COLOR, SOFT_GREEN);

    fc.assert(
        fc.property(runningArb, fc.integer({ min: 1, max: 5 }), function (logs, repeats) {
            // Sanity: the generated input actually resolves to Running.
            assert.strictEqual(resolveAppCardStatus(logs), 'Running');

            const appCard = makeFakeAppCard('');

            // Apply once.
            applyStyling(appCard, logs);
            assert.strictEqual(appCard.style.backgroundColor, SOFT_GREEN);

            // Apply repeatedly while state remains Running -> stays Soft_Green.
            for (let i = 0; i < repeats; i++) {
                applyStyling(appCard, logs);
                assert.strictEqual(appCard.style.backgroundColor, SOFT_GREEN);
            }
        }),
        { numRuns: 200 }
    );
});

// ---------------------------------------------------------------------------
// Task 4.2 - Property 2: Not_Running state yields Soft_Red.
// ---------------------------------------------------------------------------

test('Feature: dashboard-running-app-highlight, Property 2: Not_Running state yields Soft_Red', () => {
    assert.strictEqual(NOT_RUNNING_BACKGROUND_COLOR, SOFT_RED);

    fc.assert(
        fc.property(notRunningArb, function (logs) {
            assert.strictEqual(resolveAppCardStatus(logs), 'NotRunning');

            const appCard = makeFakeAppCard('');
            applyStyling(appCard, logs);
            assert.strictEqual(appCard.style.backgroundColor, SOFT_RED);
        }),
        { numRuns: 200 }
    );
});

// ---------------------------------------------------------------------------
// Task 4.3 - Property 3: Other states never use the running/not-running colors.
// ---------------------------------------------------------------------------

test('Feature: dashboard-running-app-highlight, Property 3: Other states never use the running/not-running highlight colors', () => {
    fc.assert(
        fc.property(otherArb, fc.constantFrom('', 'blue', 'rgb(1,2,3)'), function (logs, initialColor) {
            assert.strictEqual(resolveAppCardStatus(logs), 'Other');

            const appCard = makeFakeAppCard(initialColor);
            applyStyling(appCard, logs);

            // Background is never a highlight color...
            assert.notStrictEqual(appCard.style.backgroundColor, SOFT_GREEN);
            assert.notStrictEqual(appCard.style.backgroundColor, SOFT_RED);
            // ...and is left unchanged from its pre-existing value.
            assert.strictEqual(appCard.style.backgroundColor, initialColor);
        }),
        { numRuns: 200 }
    );
});

// ---------------------------------------------------------------------------
// Task 4.4 - Property 4: Final resolved state determines the background across
// transitions.
// ---------------------------------------------------------------------------

test('Feature: dashboard-running-app-highlight, Property 4: Final resolved state determines the background across transitions', () => {
    // A step is a Running or NotRunning evaluation paired with its logs.
    const stepArb = fc.oneof(
        runningArb.map(function (logs) {
            return { state: 'Running', logs: logs };
        }),
        notRunningArb.map(function (logs) {
            return { state: 'NotRunning', logs: logs };
        })
    );

    fc.assert(
        fc.property(fc.array(stepArb, { minLength: 1, maxLength: 10 }), function (steps) {
            const appCard = makeFakeAppCard('');

            for (const step of steps) {
                applyStyling(appCard, step.logs);
            }

            const finalStep = steps[steps.length - 1];
            const expected = finalStep.state === 'Running' ? SOFT_GREEN : SOFT_RED;
            assert.strictEqual(
                appCard.style.backgroundColor,
                expected,
                'final state ' + finalStep.state + ' should map to ' + expected
            );
        }),
        { numRuns: 200 }
    );
});

// ---------------------------------------------------------------------------
// Task 5.1 - Example / edge-case tests: resolution paths and malformed status.
// ---------------------------------------------------------------------------

test('Example: JSON docker_compose_ps path resolves Running and NotRunning', () => {
    const runningLogs =
        'some header\nSTDOUT:\n' + JSON.stringify({ docker_compose_ps: 'IS_RUNNING', extra: 1 });
    const notRunningLogs =
        'some header\nSTDOUT:\n' + JSON.stringify({ docker_compose_ps: 'IS_NOT_RUNNING' });

    assert.strictEqual(resolveAppCardStatus(runningLogs), 'Running');
    assert.strictEqual(resolveAppCardStatus(notRunningLogs), 'NotRunning');

    const runningCard = makeFakeAppCard('');
    applyStyling(runningCard, runningLogs);
    assert.strictEqual(runningCard.style.backgroundColor, SOFT_GREEN);

    const notRunningCard = makeFakeAppCard('');
    applyStyling(notRunningCard, notRunningLogs);
    assert.strictEqual(notRunningCard.style.backgroundColor, SOFT_RED);
});

test('Example: log-substring fallback path resolves Running and NotRunning', () => {
    // No parseable JSON -> resolver falls back to raw substring matching.
    const runningLogs = 'container status output: IS_RUNNING (up 3 minutes)';
    const notRunningLogs = 'container status output: IS_NOT_RUNNING (exited)';

    assert.strictEqual(resolveAppCardStatus(runningLogs), 'Running');
    assert.strictEqual(resolveAppCardStatus(notRunningLogs), 'NotRunning');

    const runningCard = makeFakeAppCard('');
    applyStyling(runningCard, runningLogs);
    assert.strictEqual(runningCard.style.backgroundColor, SOFT_GREEN);

    const notRunningCard = makeFakeAppCard('');
    applyStyling(notRunningCard, notRunningLogs);
    assert.strictEqual(notRunningCard.style.backgroundColor, SOFT_RED);
});

test('Example: malformed JSON after STDOUT falls back gracefully without a highlight', () => {
    // STDOUT marker present but the following content is not valid JSON and has
    // no running markers -> graceful resolution to Other (no highlight color).
    const logs = 'header\nSTDOUT:\n{ this is : not, valid json ]';
    assert.strictEqual(resolveAppCardStatus(logs), 'Other');

    const appCard = makeFakeAppCard('teal');
    applyStyling(appCard, logs);
    assert.notStrictEqual(appCard.style.backgroundColor, SOFT_GREEN);
    assert.notStrictEqual(appCard.style.backgroundColor, SOFT_RED);
    assert.strictEqual(appCard.style.backgroundColor, 'teal');
});

test('Example: empty and null/undefined status resolve to a non-highlight state', () => {
    for (const logs of ['', null, undefined]) {
        assert.strictEqual(resolveAppCardStatus(logs), 'Other');

        const appCard = makeFakeAppCard('');
        applyStyling(appCard, logs);
        assert.notStrictEqual(appCard.style.backgroundColor, SOFT_GREEN);
        assert.notStrictEqual(appCard.style.backgroundColor, SOFT_RED);
        assert.strictEqual(appCard.style.backgroundColor, '');
    }
});

test('Example: cloned-but-not-compliant and not-cloned resolve to Other', () => {
    const casesOther = [
        'ERROR: deployApp.sh not found in repository',
        'Application not deployed yet',
        'Repository present, clone it first',
    ];
    for (const logs of casesOther) {
        assert.strictEqual(resolveAppCardStatus(logs), 'Other');
        const appCard = makeFakeAppCard('');
        applyStyling(appCard, logs);
        assert.strictEqual(appCard.style.backgroundColor, '');
    }
});
