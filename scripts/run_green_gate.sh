#!/usr/bin/env bash
#
# run_green_gate.sh — Phase 6 single aggregate green gate.
#
# The outermost release gate. In one invocation it drives all three test
# runners and reduces their results to a single PASS/FAIL:
#
#   1. pytest   — tests/ + scripts/test_*.py, with the integration harness env
#                 set so the Integration_Pytest_Tests and the DB_Coupled_Scripts
#                 execute rather than skip.
#   2. node     — `node --test` in tests/js.
#   3. bash     — the bash harness suites in tests/bash (the test_*.sh drivers).
#
# The result-combining logic is the pure `aggregate` function:
#
#   aggregate PYTEST NODE BASH
#     -> prints "PASS" and returns 0  iff all three == PASS
#     -> prints "FAIL (<runner>[, <runner>...])" and returns 1 otherwise
#
# The gate exits 0 on PASS and non-zero on FAIL.
#
# End-state guarantees (Requirements 7.4, 7.5): with the harness env set, the
# four Pre_Existing_Failures are cleared (the three Docker-API probe cases and
# the SHAI unicode case) and the three previously-skipped integration tests
# (traefik docker-api-version integration, traefik control-plane, e2e governed
# scenario) execute and pass.
#
# Secrets are referenced by key name only; this script never emits a secret
# value (Requirements 7.* , 9.5). The live-cloud gate `ZAF_LIVE_OPENSTACK` is
# deliberately left unset so the E2E scenario stays fully mocked and no cloud
# credentials are required.
#
# This script is dual-purpose: run directly it executes the full gate, but when
# sourced (BASH_SOURCE[0] != $0) it defines `aggregate` without running
# anything, so the Property 7 test (task 7.2) can source it and exercise the
# pure result-combining function in isolation.
#
# CLI contract:
#   run_green_gate.sh [--skip-harness-env] [-h|--help]
#     exit 0  -> PASS: pytest AND node AND bash all passed
#     exit !0 -> FAIL: at least one runner failed (message names which)
#
# Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 9.5
#
set -uo pipefail

# ===========================================================================
# Pure result-combining function (Property 7).
#
# aggregate <pytest_result> <node_result> <bash_result>
#   Each argument is the string "PASS" or "FAIL".
#   Prints "PASS" and returns 0 iff all three are exactly "PASS".
#   Otherwise prints "FAIL (<failing runner>[, ...])" and returns 1, naming
#   every runner that did not pass, in the fixed order pytest, node, bash.
#
# The function is total and side-effect-free apart from its single stdout line,
# so it can be unit/property tested across all 8 result tuples.
# ===========================================================================
aggregate() {
    local pytest_result="${1:-FAIL}"
    local node_result="${2:-FAIL}"
    local bash_result="${3:-FAIL}"

    local failed=()
    [[ "${pytest_result}" == "PASS" ]] || failed+=("pytest")
    [[ "${node_result}"   == "PASS" ]] || failed+=("node")
    [[ "${bash_result}"   == "PASS" ]] || failed+=("bash")

    if [[ ${#failed[@]} -eq 0 ]]; then
        echo "PASS"
        return 0
    fi

    # Join the failing-runner names with ", ". `${arr[*]}` uses only the first
    # char of IFS, so build the comma-space list explicitly.
    local joined="${failed[0]}"
    local i
    for (( i = 1; i < ${#failed[@]}; i++ )); do
        joined="${joined}, ${failed[i]}"
    done
    echo "FAIL (${joined})"
    return 1
}

# When sourced, stop here: expose `aggregate` without running the gate.
# (In a sourced file, ${BASH_SOURCE[0]} differs from $0.)
if [[ "${BASH_SOURCE[0]}" != "${0}" ]]; then
    return 0 2>/dev/null || true
fi

# ===========================================================================
# Full gate (direct invocation only).
# ===========================================================================

# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
JS_TESTS_DIR="${REPO_ROOT}/tests/js"
BASH_TESTS_DIR="${REPO_ROOT}/tests/bash"

# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------
SKIP_HARNESS_ENV=0

usage() {
    cat <<'EOF'
Usage: run_green_gate.sh [--skip-harness-env] [-h|--help]

Runs all three test runners in a single invocation and reduces their results
to one PASS/FAIL:
  pytest (tests/ + scripts/test_*.py), node --test (tests/js), bash (tests/bash).

Options:
  --skip-harness-env   Do NOT export the opt-in harness gates before pytest.
                       Only use this when the environment is already prepared
                       by run_integration_harness.sh; otherwise the previously
                       gated suites will skip and the gate cannot confirm them.
  -h, --help           Show this help and exit.

Exit status:
  0   PASS  (pytest AND node AND bash all passed)
  !0  FAIL  (at least one runner failed; the message names which)
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-harness-env)
            SKIP_HARNESS_ENV=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "ERROR: unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

log()  { echo "[green-gate] $*"; }
err()  { echo "[green-gate] ERROR: $*" >&2; }

# ---------------------------------------------------------------------------
# Opt-in harness env for the pytest runner.
#
# Mirrors run_integration_harness.sh so the Integration_Pytest_Tests and the
# DB_Coupled_Scripts execute instead of skipping. ZAF_LIVE_OPENSTACK stays
# unset — the E2E scenario remains fully mocked and credential-free. Secrets
# are referenced by key name only; no value is ever printed.
# ---------------------------------------------------------------------------
export_harness_env() {
    if [[ "${SKIP_HARNESS_ENV}" -eq 1 ]]; then
        log "--skip-harness-env set; assuming the harness already exported the opt-in gates."
        return 0
    fi

    export RUN_TRAEFIK_INTEGRATION=1
    export RUN_TRAEFIK_LOCALLY_INTEGRATION=1
    export USE_POSTGRES=true

    # Non-cloud, local service connection settings (key name only; no values
    # are logged). Pass through anything already set.
    export POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
    export POSTGRES_PORT="${POSTGRES_PORT:-5432}"
    export POSTGRES_DB="${POSTGRES_DB:-ai_swautomorph}"
    export POSTGRES_USER="${POSTGRES_USER:-swautomorph}"
    export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-swautomorph_password}"

    # Keep the live-cloud gate unset so the scenario stays mocked.
    unset ZAF_LIVE_OPENSTACK || true

    log "Exported opt-in gates: RUN_TRAEFIK_INTEGRATION, RUN_TRAEFIK_LOCALLY_INTEGRATION, USE_POSTGRES=true"
    log "ZAF_LIVE_OPENSTACK left unset (E2E scenario stays mocked; no cloud credentials required)."
}

# ---------------------------------------------------------------------------
# Runner 1: pytest (tests/ + scripts/test_*.py)
# ---------------------------------------------------------------------------
run_pytest() {
    local py
    if command -v python3 >/dev/null 2>&1; then
        py=python3
    elif command -v python >/dev/null 2>&1; then
        py=python
    else
        err "no python3/python on PATH; cannot run the pytest runner."
        return 1
    fi

    log "Running pytest (tests/ + scripts/test_*.py)..."
    # tests/ plus the DB-coupled scripts/test_*.py. pytest collects the
    # scripts/test_*.py modules by glob; harness env lets the gated ones run.
    ( cd "${REPO_ROOT}" && "${py}" -m pytest tests scripts -o 'python_files=test_*.py' )
}

# ---------------------------------------------------------------------------
# Runner 2: node --test (tests/js)
# ---------------------------------------------------------------------------
run_node() {
    if ! command -v node >/dev/null 2>&1; then
        err "node is not on PATH; cannot run the node --test runner."
        return 1
    fi
    if [[ ! -d "${JS_TESTS_DIR}" ]]; then
        err "tests/js directory not found at ${JS_TESTS_DIR}."
        return 1
    fi

    log "Running node --test (tests/js)..."
    ( cd "${JS_TESTS_DIR}" && node --test )
}

# ---------------------------------------------------------------------------
# Runner 3: bash harness suites (tests/bash/test_*.sh)
# ---------------------------------------------------------------------------
run_bash() {
    if [[ ! -d "${BASH_TESTS_DIR}" ]]; then
        err "tests/bash directory not found at ${BASH_TESTS_DIR}."
        return 1
    fi

    log "Running bash harness suites (tests/bash/test_*.sh)..."
    local rc=0
    local any=0
    local suite
    # The test_*.sh files are the runnable drivers; the *_harness.sh files are
    # shared libraries they source and must not be invoked directly.
    for suite in "${BASH_TESTS_DIR}"/test_*.sh; do
        [[ -e "${suite}" ]] || continue
        any=1
        log "  bash suite: $(basename "${suite}")"
        if ! bash "${suite}"; then
            err "  bash suite failed: $(basename "${suite}")"
            rc=1
        fi
    done

    if [[ "${any}" -eq 0 ]]; then
        err "no bash harness suites found under ${BASH_TESTS_DIR}."
        return 1
    fi
    return "${rc}"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    log "Repo root: ${REPO_ROOT}"
    export_harness_env

    # Run all three runners; capture each result independently so the final
    # aggregate names every failing runner rather than short-circuiting.
    local pytest_result node_result bash_result

    if run_pytest; then pytest_result="PASS"; else pytest_result="FAIL"; fi
    if run_node;   then node_result="PASS";   else node_result="FAIL";   fi
    if run_bash;   then bash_result="PASS";   else bash_result="FAIL";   fi

    log "Runner results: pytest=${pytest_result} node=${node_result} bash=${bash_result}"

    local verdict
    verdict="$(aggregate "${pytest_result}" "${node_result}" "${bash_result}")"
    local gate_rc=$?

    if [[ "${gate_rc}" -eq 0 ]]; then
        log "GREEN GATE: ${verdict}"
    else
        err "GREEN GATE: ${verdict}"
    fi
    exit "${gate_rc}"
}

main "$@"
