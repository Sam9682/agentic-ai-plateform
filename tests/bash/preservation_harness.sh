#!/bin/bash
# ---------------------------------------------------------------------------
# preservation_harness.sh — shared harness for the
# init-pltf-root-ownership-fix PRESERVATION property tests (Task 2).
#
# Property 2 (Preservation): for every run where the bug condition does NOT
# hold, the fixed script must behave exactly as the original — ownership is
# left as the pre-run state produced it, no `chown` is attempted, no invalid
# `chown` is run, and the helper is a no-op.
#
# This harness reuses the Task-1 pattern (ownership_harness.sh): it sources
# the REAL init_pltf.sh under the source guard (BASH_SOURCE[0] != $0), so only
# the function definitions above the guard load and the destructive installer
# body never runs. It then builds a temporary tree mirroring the clone
# destination (REPO_DIR with `shared`, `.venv`, `logs`, `conf/deploy.ini`,
# `README.md`) plus the home artifacts (`~/.aws`, `~/deployments/admin`).
#
# Unlike the Task-1 harness (which forces root:root to model the bug), this
# harness leaves the tree with its NATURAL creation ownership — i.e. whatever
# the simulated non-bug context produces — because preservation is about
# leaving that natural ownership untouched. It records that pre-run ownership,
# optionally invokes `restore_invoking_user_ownership` if the fix has defined
# it, and reports the post-run ownership of every node.
#
# To prove the stronger invariant "no chown is attempted", the harness installs
# a `chown` shell-function wrapper that counts every invocation (and forwards to
# the real chown so the fix, once present, still works in bug contexts). In a
# non-bug context the count MUST stay 0.
#
# Context parameters (env-driven):
#   BUG_EUID        : "0" runs under fakeroot (EUID 0); otherwise the real
#                     non-root EUID is used. The caller selects fakeroot vs not.
#   SUDO_USER       : the simulated SUDO_USER; may be unset, "root", a real
#                     non-root user, or a nonexistent user. Non-bug contexts
#                     are: EUID != 0, OR SUDO_USER unset, OR SUDO_USER == root.
#                     (A nonexistent SUDO_USER under EUID 0 is a malformed bug
#                     context the fix must also treat as no-chown.)
#   BUILD_HOME_ART  : "true" (default) to also build ~/.aws and ~/deployments.
#   TREE_SHAPE      : "min" | "full" (default "full") — varied tree shapes so
#                     the property is checked over different layouts.
#
# All assertions live in the test driver; the harness only emits PROBE lines.
# ---------------------------------------------------------------------------
set -u

# --- locate the repo root (two levels up from tests/bash) ------------------
HARNESS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${HARNESS_DIR}/../.." && pwd)"
INIT_SCRIPT="${REPO_ROOT}/init_pltf.sh"

SIM_USER="${SUDO_USER:-}"
BUILD_HOME_ART="${BUILD_HOME_ART:-true}"
TREE_SHAPE="${TREE_SHAPE:-full}"

# --- chown wrapper: count every attempt, then forward to the real chown ----
# Defined BEFORE sourcing so it shadows `chown` for any code the helper runs.
# The real chown is still reachable via `command chown` so bug-context fixes
# keep working; in non-bug contexts the helper must never reach a chown call.
CHOWN_CALLS=0
chown() {
    CHOWN_CALLS=$((CHOWN_CALLS + 1))
    command chown "$@"
}

# --- source the installer so the helper (if any) is loaded -----------------
# Sourcing must NOT run the installer body (source guard returns).
# shellcheck disable=SC1090
source "${INIT_SCRIPT}"

if declare -F restore_invoking_user_ownership >/dev/null 2>&1; then
    HELPER_DEFINED=1
else
    HELPER_DEFINED=0
fi

# --- build the simulated clone tree (REPO_DIR) with NATURAL ownership ------
# No forced `chown`: the tree keeps whatever ownership this context creates it
# with (invoking user when EUID != 0; root under fakeroot EUID 0). Preservation
# requires that this pre-run ownership be left untouched.
SANDBOX="$(mktemp -d)"
REPO_DIR="${SANDBOX}/clone"
export REPO_DIR
mkdir -p "${REPO_DIR}/shared" \
         "${REPO_DIR}/.venv/bin" \
         "${REPO_DIR}/logs" \
         "${REPO_DIR}/conf"
printf 'PLTF_NAME=demo\nPLTF_FOLDER=demo\n' > "${REPO_DIR}/conf/deploy.ini"
printf '#!/bin/sh\n' > "${REPO_DIR}/.venv/bin/activate"
: > "${REPO_DIR}/shared/.gitkeep"
: > "${REPO_DIR}/README.md"
# A deeper / varied shape when requested, so the property spans tree shapes.
if [ "${TREE_SHAPE}" = "full" ]; then
    mkdir -p "${REPO_DIR}/shared/sub/deep" "${REPO_DIR}/logs/old"
    : > "${REPO_DIR}/shared/sub/deep/file.txt"
    : > "${REPO_DIR}/logs/old/app.log"
fi

# --- build the simulated home artifacts ------------------------------------
SIM_HOME="${SANDBOX}/home"
export SIM_HOME
mkdir -p "${SIM_HOME}"
if [ "${BUILD_HOME_ART}" = "true" ]; then
    mkdir -p "${SIM_HOME}/.aws"
    printf '[default]\n' > "${SIM_HOME}/.aws/config"
    printf '[default]\n' > "${SIM_HOME}/.aws/credentials"
    mkdir -p "${SIM_HOME}/deployments/admin"
fi

# --- record the PRE-RUN ownership of every node (the baseline to preserve) --
declare -A PRE
record_pre() {
    local label="$1" path="$2"
    if [ -e "${path}" ]; then
        PRE["${label}"]="$(stat -c '%U:%G' "${path}")"
    else
        PRE["${label}"]="<missing>"
    fi
}
NODES=(clone shared venv venv_bin logs deploy_ini readme)
[ "${TREE_SHAPE}" = "full" ] && NODES+=(deep deep_file logs_old)
if [ "${BUILD_HOME_ART}" = "true" ]; then
    NODES+=(aws aws_creds deployments admin)
fi

path_of() {
    case "$1" in
        clone)       echo "${REPO_DIR}" ;;
        shared)      echo "${REPO_DIR}/shared" ;;
        venv)        echo "${REPO_DIR}/.venv" ;;
        venv_bin)    echo "${REPO_DIR}/.venv/bin/activate" ;;
        logs)        echo "${REPO_DIR}/logs" ;;
        deploy_ini)  echo "${REPO_DIR}/conf/deploy.ini" ;;
        readme)      echo "${REPO_DIR}/README.md" ;;
        deep)        echo "${REPO_DIR}/shared/sub/deep" ;;
        deep_file)   echo "${REPO_DIR}/shared/sub/deep/file.txt" ;;
        logs_old)    echo "${REPO_DIR}/logs/old/app.log" ;;
        aws)         echo "${SIM_HOME}/.aws" ;;
        aws_creds)   echo "${SIM_HOME}/.aws/credentials" ;;
        deployments) echo "${SIM_HOME}/deployments" ;;
        admin)       echo "${SIM_HOME}/deployments/admin" ;;
    esac
}

for n in "${NODES[@]}"; do
    record_pre "${n}" "$(path_of "${n}")"
done

echo "PROBE context helper_defined=${HELPER_DEFINED} sim_user=[${SIM_USER:-UNSET}] euid=${EUID} tree=${TREE_SHAPE}"

# --- invoke the fix helper if it exists ------------------------------------
# On UNFIXED code the helper is absent, so nothing runs and no chown occurs.
# On FIXED code the helper runs but, in a non-bug context, must early-return
# BEFORE any chown (so CHOWN_CALLS stays 0).
if [ "${HELPER_DEFINED}" = "1" ]; then
    restore_invoking_user_ownership || echo "PROBE helper_exit=$?"
fi

echo "PROBE chown_calls=${CHOWN_CALLS}"

# --- report PRE and POST ownership of every node ---------------------------
for n in "${NODES[@]}"; do
    p="$(path_of "${n}")"
    if [ -e "${p}" ]; then
        post="$(stat -c '%U:%G' "${p}")"
    else
        post="<missing>"
    fi
    echo "PROBE ${n} pre=${PRE[${n}]} post=${post}"
done

# cleanup
rm -rf "${SANDBOX}"
