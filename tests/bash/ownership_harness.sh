#!/bin/bash
# ---------------------------------------------------------------------------
# ownership_harness.sh — shared harness for the init-pltf-root-ownership-fix
# bug-condition exploration test (Task 1).
#
# It sources the REAL init_pltf.sh under the source guard
# (BASH_SOURCE[0] != $0), so only the function definitions above the guard are
# loaded and the destructive installer body never runs. It then builds a
# temporary directory tree that mirrors the clone destination (REPO_DIR) with
# `shared`, `.venv`, `logs`, `conf/deploy.ini`, plus the home artifacts
# `~/.aws` and `~/deployments/admin`, simulates the sudo bug context
# (EUID == 0 — provided by fakeroot — and SUDO_USER set to a real, non-root
# user), optionally invokes `restore_invoking_user_ownership` if the fix has
# defined it, and finally reports the resulting owner:group of every node.
#
# The harness performs NO assertions itself; it emits machine-readable PROBE
# lines consumed by test_init_ownership.sh. All chown / stat calls are
# virtualized by fakeroot, so no real privilege is required.
# ---------------------------------------------------------------------------
set -u

# --- locate the repo root (two levels up from tests/bash) ------------------
HARNESS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${HARNESS_DIR}/../.." && pwd)"
INIT_SCRIPT="${REPO_ROOT}/init_pltf.sh"

# --- parameters (env-driven) -----------------------------------------------
# SUDO_USER        : the simulated invoking user (real passwd user, non-root)
# BUG_EUID         : "0" for the bug context (default), anything else for ¬C
# BUILD_HOME_ART   : "true" to also build ~/.aws and ~/deployments/admin
SIM_USER="${SUDO_USER:-}"
BUILD_HOME_ART="${BUILD_HOME_ART:-true}"

# --- source the installer so the helper (if any) is loaded -----------------
# Sourcing must NOT run the installer body. We assert that by trapping any
# attempt to run the heavy steps is unnecessary: the source guard returns.
# shellcheck disable=SC1090
source "${INIT_SCRIPT}"

# Did sourcing define the fix helper?
if declare -F restore_invoking_user_ownership >/dev/null 2>&1; then
    HELPER_DEFINED=1
else
    HELPER_DEFINED=0
fi

# --- build the simulated clone tree (REPO_DIR) -----------------------------
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

# --- build the simulated home artifacts ------------------------------------
# The real fix resolves the invoking user's home from the passwd database
# (getent passwd). To keep the test hermetic we build the artifacts inside a
# sandbox home and expose it to the (future) helper via the SIM_HOME override
# that the helper reads only when set (falling back to the passwd entry). On
# UNFIXED code the helper is absent so SIM_HOME is simply ignored.
SIM_HOME="${SANDBOX}/home"
export SIM_HOME
mkdir -p "${SIM_HOME}"
if [ "${BUILD_HOME_ART}" = "true" ]; then
    mkdir -p "${SIM_HOME}/.aws"
    printf '[default]\n' > "${SIM_HOME}/.aws/config"
    printf '[default]\n' > "${SIM_HOME}/.aws/credentials"
    mkdir -p "${SIM_HOME}/deployments/admin"
fi

# --- simulate the sudo run: everything created as root ---------------------
# Under fakeroot this is a virtual chown; it models the real installer having
# run every user-space step as root (EUID 0) and left root-owned paths.
chown -R root:root "${REPO_DIR}"
if [ "${BUILD_HOME_ART}" = "true" ]; then
    chown -R root:root "${SIM_HOME}/.aws" "${SIM_HOME}/deployments"
fi

# --- resolve the EXPECTED post-fix owner:group independently ---------------
# This is what Property 1 (Expected Behavior) demands: ownership resolved from
# the invoking user and that user's PRIMARY GROUP (via id -gn), NOT a naive
# user:user assumption.
EXPECT_USER="${SIM_USER}"
EXPECT_GROUP="$(id -gn "${SIM_USER}" 2>/dev/null)"
echo "PROBE helper_defined=${HELPER_DEFINED} sim_user=${SIM_USER} expect_owner=${EXPECT_USER}:${EXPECT_GROUP} euid=${EUID}"

# --- invoke the fix helper if it exists ------------------------------------
# On UNFIXED code this branch is skipped entirely (helper absent), so no
# ownership restoration happens and the root-owned tree persists.
if [ "${HELPER_DEFINED}" = "1" ]; then
    restore_invoking_user_ownership || echo "PROBE helper_exit=$?"
fi

# --- report resulting ownership of every node ------------------------------
report_owner() {
    local label="$1" path="$2"
    if [ -e "${path}" ]; then
        echo "PROBE ${label} owner=$(stat -c '%U:%G' "${path}")"
    else
        echo "PROBE ${label} owner=<missing>"
    fi
}

report_owner clone        "${REPO_DIR}"
report_owner shared       "${REPO_DIR}/shared"
report_owner venv         "${REPO_DIR}/.venv"
report_owner venv_bin     "${REPO_DIR}/.venv/bin/activate"
report_owner logs         "${REPO_DIR}/logs"
report_owner deploy_ini   "${REPO_DIR}/conf/deploy.ini"
report_owner readme       "${REPO_DIR}/README.md"
if [ "${BUILD_HOME_ART}" = "true" ]; then
    report_owner aws         "${SIM_HOME}/.aws"
    report_owner aws_creds   "${SIM_HOME}/.aws/credentials"
    report_owner deployments "${SIM_HOME}/deployments"
    report_owner admin       "${SIM_HOME}/deployments/admin"
fi

# cleanup
rm -rf "${SANDBOX}"
