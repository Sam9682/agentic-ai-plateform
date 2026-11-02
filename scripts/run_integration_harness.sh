#!/usr/bin/env bash
#
# run_integration_harness.sh — Phase 6 reproducible integration harness.
#
# Stands up the credential-free live environment (PostgreSQL, the Flask app, and
# Traefik), waits for every service to report healthy, exports the opt-in gates
# that unblock the previously-gated suites, runs those suites, and tears the
# environment down.
#
# No real cloud-provider credentials are configured, read, or required. The
# E2E gate `ZAF_LIVE_OPENSTACK` is deliberately left unset so the governed
# scenario stays fully mocked. Secrets are referenced by key name only; this
# script never emits a secret value.
#
# CLI contract:
#   run_integration_harness.sh [--profile <name>] [--keep-up] [--health-timeout <sec>]
#     exit 0  -> all gated suites executed and passed
#     exit !0 -> a service failed health, a prerequisite is missing, or a gated
#                suite failed
#
# Requirements: 1.1, 1.2, 1.3, 1.6, 9.3, 9.4, 9.5
#
set -euo pipefail

# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_FILE="${REPO_ROOT}/docker-compose.yml"

# The external Docker network the compose `traefik` service attaches to.
# (networks: swautomorph-shared: external: true)
REQUIRED_NETWORK="swautomorph-shared"

# Services the harness brings up (their declared deps come along automatically).
HARNESS_SERVICES=(postgres app traefik)

# ---------------------------------------------------------------------------
# Defaults / CLI options
# ---------------------------------------------------------------------------
PROFILE=""
KEEP_UP=0
HEALTH_TIMEOUT=180   # seconds to wait for all services to become healthy

usage() {
    cat <<'EOF'
Usage: run_integration_harness.sh [--profile <name>] [--keep-up] [--health-timeout <sec>]

Options:
  --profile <name>        Select an optional compose profile (e.g. "integration")
                          so only the harness-relevant subset of services starts.
  --keep-up               Leave the compose services running after the suites
                          finish (skip teardown). Useful for debugging.
  --health-timeout <sec>  Max seconds to wait for all services to report healthy
                          before aborting. Default: 180.
  -h, --help              Show this help and exit.

Exit status:
  0   all gated suites executed and passed
  !0  a service failed health, a prerequisite is missing, or a suite failed
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --profile)
            [[ $# -ge 2 ]] || { echo "ERROR: --profile requires a value" >&2; exit 2; }
            PROFILE="$2"
            shift 2
            ;;
        --keep-up)
            KEEP_UP=1
            shift
            ;;
        --health-timeout)
            [[ $# -ge 2 ]] || { echo "ERROR: --health-timeout requires a value" >&2; exit 2; }
            HEALTH_TIMEOUT="$2"
            shift 2
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

if ! [[ "${HEALTH_TIMEOUT}" =~ ^[0-9]+$ ]]; then
    echo "ERROR: --health-timeout must be a positive integer (got '${HEALTH_TIMEOUT}')" >&2
    exit 2
fi

# ---------------------------------------------------------------------------
# docker compose shim (support both `docker compose` and `docker-compose`)
# ---------------------------------------------------------------------------
if docker compose version >/dev/null 2>&1; then
    DC=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
    DC=(docker-compose)
else
    echo "ERROR: neither 'docker compose' nor 'docker-compose' is available on PATH." >&2
    exit 1
fi

COMPOSE_ARGS=(-f "${COMPOSE_FILE}")
if [[ -n "${PROFILE}" ]]; then
    COMPOSE_ARGS+=(--profile "${PROFILE}")
fi

compose() {
    "${DC[@]}" "${COMPOSE_ARGS[@]}" "$@"
}

log()  { echo "[harness] $*"; }
err()  { echo "[harness] ERROR: $*" >&2; }

# ---------------------------------------------------------------------------
# Teardown
# ---------------------------------------------------------------------------
teardown() {
    if [[ "${KEEP_UP}" -eq 1 ]]; then
        log "--keep-up set; leaving services running."
        log "Tear down manually with: ${DC[*]} ${COMPOSE_ARGS[*]} down"
        return 0
    fi
    log "Tearing down compose services..."
    compose down --remove-orphans >/dev/null 2>&1 || true
}
trap teardown EXIT

# ---------------------------------------------------------------------------
# Prerequisite: external network
# ---------------------------------------------------------------------------
# The compose `traefik` service attaches to the external `swautomorph-shared`
# network. If it is absent, compose fails to start Traefik. Detect it up front
# and report the documented remedy instead of surfacing a raw compose error.
check_required_network() {
    if ! docker network inspect "${REQUIRED_NETWORK}" >/dev/null 2>&1; then
        err "required external Docker network '${REQUIRED_NETWORK}' is missing."
        err "This network is a prerequisite for the compose 'traefik' service."
        err "Create it first with:  docker network create ${REQUIRED_NETWORK}"
        return 1
    fi
    return 0
}

# ---------------------------------------------------------------------------
# Health waits
# ---------------------------------------------------------------------------
cid_for() {
    # Print the container id for a compose service, or empty if not running.
    compose ps -q "$1" 2>/dev/null | head -n1
}

# Report a compose service's container health: "healthy" | "unhealthy" |
# "starting" | "none" (no healthcheck defined) | "missing" (no container).
container_health() {
    local cid
    cid="$(cid_for "$1")"
    if [[ -z "${cid}" ]]; then
        echo "missing"
        return 0
    fi
    docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' \
        "${cid}" 2>/dev/null || echo "missing"
}

# Wait for PostgreSQL using its own pg_isready, independent of compose health
# cadence, so the DB is accepting connections before any DB-coupled suite runs.
pg_is_ready() {
    local cid
    cid="$(cid_for postgres)"
    [[ -n "${cid}" ]] || return 1
    docker exec "${cid}" pg_isready -U swautomorph -d ai_swautomorph >/dev/null 2>&1
}

# Probe the app's /api/auth/status endpoint from inside the app container so we
# do not depend on host port mapping.
app_is_ready() {
    local cid
    cid="$(cid_for app)"
    [[ -n "${cid}" ]] || return 1
    local port="${HTTP_PORT:-6000}"
    docker exec "${cid}" curl -fsS "http://localhost:${port}/api/auth/status" >/dev/null 2>&1
}

# Traefik is ready once its container reports healthy, or — when no container
# healthcheck is defined — once its admin ping / entrypoint is reachable.
traefik_is_ready() {
    local cid
    cid="$(cid_for traefik)"
    [[ -n "${cid}" ]] || return 1
    local status
    status="$(container_health traefik)"
    if [[ "${status}" == "healthy" ]]; then
        return 0
    fi
    if [[ "${status}" == "none" ]]; then
        # No compose healthcheck; treat a running container with a reachable
        # web entrypoint as ready.
        docker exec "${cid}" traefik healthcheck --ping >/dev/null 2>&1 && return 0
        docker exec "${cid}" wget -q -O /dev/null "http://localhost:80/" >/dev/null 2>&1 && return 0
        # Running but unprobeable: accept running state as ready for scaffolding.
        [[ "$(docker inspect --format '{{.State.Running}}' "${cid}" 2>/dev/null)" == "true" ]]
        return $?
    fi
    return 1
}

# Wait until every harness service is ready, or abort non-zero naming the first
# service still unhealthy when the timeout elapses.
wait_for_health() {
    local deadline=$(( SECONDS + HEALTH_TIMEOUT ))
    log "Waiting up to ${HEALTH_TIMEOUT}s for services to become healthy: ${HARNESS_SERVICES[*]}"

    while :; do
        local unhealthy=""

        if ! pg_is_ready;      then unhealthy="postgres"; fi
        if [[ -z "${unhealthy}" ]] && ! app_is_ready;     then unhealthy="app"; fi
        if [[ -z "${unhealthy}" ]] && ! traefik_is_ready; then unhealthy="traefik"; fi

        if [[ -z "${unhealthy}" ]]; then
            log "All services healthy (postgres, app, traefik)."
            return 0
        fi

        if (( SECONDS >= deadline )); then
            err "service '${unhealthy}' did not become healthy within ${HEALTH_TIMEOUT}s."
            err "Aborting before running any gated suite."
            # Surface recent logs of the unhealthy service to aid diagnosis
            # (compose log output references env by key name, not secret values).
            compose logs --tail=40 "${unhealthy}" 2>/dev/null || true
            return 1
        fi

        sleep 3
    done
}

# ---------------------------------------------------------------------------
# Opt-in gates for the gated suites
# ---------------------------------------------------------------------------
# These unblock the previously-gated suites. ZAF_LIVE_OPENSTACK is intentionally
# NOT set, keeping the E2E governed scenario fully mocked and credential-free.
export_opt_in_gates() {
    export RUN_TRAEFIK_INTEGRATION=1
    export RUN_TRAEFIK_LOCALLY_INTEGRATION=1
    export USE_POSTGRES=true

    # Non-cloud service connection settings sourced from the compose defaults.
    # Values are local, non-cloud, and referenced by key name only.
    export POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
    export POSTGRES_PORT="${POSTGRES_PORT:-5432}"
    export POSTGRES_DB="${POSTGRES_DB:-ai_swautomorph}"
    export POSTGRES_USER="${POSTGRES_USER:-swautomorph}"
    # POSTGRES_PASSWORD is passed through from the environment / compose default
    # if already set; the harness never prints its value.
    export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-swautomorph_password}"

    # Make absolutely sure the live-cloud gate stays unset.
    unset ZAF_LIVE_OPENSTACK || true

    log "Exported opt-in gates: RUN_TRAEFIK_INTEGRATION, RUN_TRAEFIK_LOCALLY_INTEGRATION, USE_POSTGRES=true"
    log "ZAF_LIVE_OPENSTACK left unset (E2E scenario stays mocked; no cloud credentials required)."
}

# ---------------------------------------------------------------------------
# Gated suite execution
# ---------------------------------------------------------------------------
# Resolve the Python interpreter once (prefer python3, fall back to python),
# mirroring the resolution in run_green_gate.sh so both runners agree.
resolve_python() {
    if command -v python3 >/dev/null 2>&1; then
        echo python3
    elif command -v python >/dev/null 2>&1; then
        echo python
    else
        return 1
    fi
}

# Runs the previously-gated suites against the now-healthy harness, with the
# opt-in gates already exported by export_opt_in_gates(). This is the single
# point where each suite's exit status is captured so a failure propagates as
# the harness exit code.
#
# Contract: run-all-then-propagate. Every suite runs even if an earlier one
# failed; any non-zero exit sets rc=1 so the harness exits non-zero. We do NOT
# short-circuit — running all suites surfaces every failure in one pass.
#
# Suites:
#   Integration_Pytest_Tests (gated by RUN_TRAEFIK_INTEGRATION /
#   RUN_TRAEFIK_LOCALLY_INTEGRATION, and ZAF_LIVE_OPENSTACK left unset):
#     tests/test_traefik_docker_api_version_integration.py
#     tests/test_traefik_control_plane.py
#     tests/test_e2e_governed_scenario.py
#   DB_Coupled_Scripts (gated by USE_POSTGRES=true against the live DB):
#     scripts/test_backups_history.py
#     scripts/test_orchestrator.py
# (scripts/test_port_calculation_py.py is pure port arithmetic — not DB-coupled —
#  so it is intentionally excluded here.)
run_gated_suites() {
    log "Running gated suites..."
    local rc=0

    local py
    if ! py="$(resolve_python)"; then
        err "no python3/python on PATH; cannot run the gated suites."
        err "Install Python 3 (with pytest available) and retry."
        return 1
    fi

    # --- Integration_Pytest_Tests --------------------------------------------
    # One pytest invocation over the three integration-marked modules. With the
    # opt-in gates exported these execute their assertions rather than skip at
    # import/collection.
    log "Running Integration_Pytest_Tests (Traefik integration, control-plane, E2E governed scenario)..."
    if ! ( cd "${REPO_ROOT}" && "${py}" -m pytest \
            tests/test_traefik_docker_api_version_integration.py \
            tests/test_traefik_control_plane.py \
            tests/test_e2e_governed_scenario.py ); then
        err "Integration_Pytest_Tests failed."
        rc=1
    fi

    # --- DB_Coupled_Scripts ---------------------------------------------------
    # Invoked via pytest so their test_* functions are collected and run against
    # the live PostgreSQL service. -o python_files lets pytest collect the
    # script-style scripts/test_*.py modules (whose names pytest ignores by
    # default). These require USE_POSTGRES=true and a healthy live DB.
    log "Running DB_Coupled_Scripts against live PostgreSQL (USE_POSTGRES=true)..."
    if ! ( cd "${REPO_ROOT}" && "${py}" -m pytest -o 'python_files=test_*.py' \
            scripts/test_backups_history.py \
            scripts/test_orchestrator.py ); then
        err "DB_Coupled_Scripts failed."
        rc=1
    fi

    if [[ "${rc}" -ne 0 ]]; then
        err "one or more gated suites failed."
    else
        log "Gated suites completed."
    fi
    return "${rc}"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    log "Repo root: ${REPO_ROOT}"
    log "Compose file: ${COMPOSE_FILE}"
    [[ -n "${PROFILE}" ]] && log "Compose profile: ${PROFILE}"

    check_required_network || exit 1

    log "Bringing up services: ${HARNESS_SERVICES[*]} (+ declared deps)"
    if ! compose up -d "${HARNESS_SERVICES[@]}"; then
        err "compose failed to bring up services."
        err "If this is a missing-network error, create it with: docker network create ${REQUIRED_NETWORK}"
        exit 1
    fi

    wait_for_health || exit 1

    export_opt_in_gates

    run_gated_suites
    local suites_rc=$?

    if [[ "${suites_rc}" -ne 0 ]]; then
        err "harness finished with failing gated suites (exit ${suites_rc})."
        exit "${suites_rc}"
    fi

    log "Harness completed successfully: all gated suites executed and passed."
    exit 0
}

main "$@"
