#!/bin/bash
# ---------------------------------------------------------------------------
# unit_harness.sh — shared harness for the init-pltf-root-ownership-fix
# focused UNIT tests (Task 4).
#
# Like the Task-1/2 harnesses it sources the REAL init_pltf.sh under the
# source guard (BASH_SOURCE[0] != $0), so only the function definitions load
# and the destructive installer body never runs. It then exercises
# `restore_invoking_user_ownership` in isolation under a single, caller-chosen
# context and emits machine-readable PROBE lines.
#
# Unlike the integration/property harnesses it is deliberately low-level: it
# installs a `chown` shell-function wrapper that COUNTS every invocation AND
# RECORDS the exact target path of each call (one `PROBE chown_target=<path>`
# line per call), so a driver can assert both "no chown happened" (no-op
# contexts) and "chown hit the passwd-resolved home, not $HOME" (home
# resolution). It also installs an optional `getent` wrapper so the
# passwd-home resolution path can be driven hermetically WITHOUT the SIM_HOME
# override (SIM_HOME is left unset so the helper genuinely reads the passwd
# entry via `getent passwd ... | cut -d: -f6`).
#
# Context parameters (env-driven):
#   BUG_EUID        : "0" when the caller runs this under fakeroot (EUID 0).
#   SUDO_USER       : the simulated invoking user (unset / "root" / real /
#                     nonexistent), as the caller sets it.
#   USE_SIM_HOME    : "true" (default) exports SIM_HOME to the sandbox home so
#                     the helper takes the override path. "false" leaves
#                     SIM_HOME UNSET so the helper takes the passwd-database
#                     path (getent passwd | cut -d: -f6).
#   FAKE_PASSWD_HOME: when non-empty AND USE_SIM_HOME=false, installs a `getent`
#                     wrapper that returns a synthetic passwd line whose home
#                     field (field 6) is this path — letting the test point the
#                     passwd-home resolution at the sandbox without touching the
#                     real passwd database. HOME is also forced to /root so the
#                     test proves the helper does NOT fall back to $HOME.
#   BUILD_HOME_ART  : "true" (default) to also build .aws and deployments under
#                     the resolved home.
# ---------------------------------------------------------------------------
set -u

HARNESS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${HARNESS_DIR}/../.." && pwd)"
INIT_SCRIPT="${REPO_ROOT}/init_pltf.sh"

SIM_USER="${SUDO_USER:-}"
USE_SIM_HOME="${USE_SIM_HOME:-true}"
FAKE_PASSWD_HOME="${FAKE_PASSWD_HOME:-}"
BUILD_HOME_ART="${BUILD_HOME_ART:-true}"

# --- sandbox ---------------------------------------------------------------
SANDBOX="$(mktemp -d)"
REPO_DIR="${SANDBOX}/clone"
export REPO_DIR
mkdir -p "${REPO_DIR}/shared" "${REPO_DIR}/.venv/bin" "${REPO_DIR}/logs" "${REPO_DIR}/conf"
printf 'PLTF_NAME=demo\nPLTF_FOLDER=demo\n' > "${REPO_DIR}/conf/deploy.ini"
: > "${REPO_DIR}/README.md"

# The sandbox home that stands in for the invoking user's home directory.
SANDBOX_HOME="${SANDBOX}/home"
mkdir -p "${SANDBOX_HOME}"
if [ "${BUILD_HOME_ART}" = "true" ]; then
    mkdir -p "${SANDBOX_HOME}/.aws"
    printf '[default]\n' > "${SANDBOX_HOME}/.aws/credentials"
    mkdir -p "${SANDBOX_HOME}/deployments/admin"
fi

# A decoy home that must NEVER be touched (models $HOME=/root under sudo). The
# home-resolution unit test asserts nothing here gets chowned.
DECOY_HOME="${SANDBOX}/root_home"
mkdir -p "${DECOY_HOME}/.aws" "${DECOY_HOME}/deployments/admin"
printf '[default]\n' > "${DECOY_HOME}/.aws/credentials"

# The sentinel __SANDBOX__ means "point the fake passwd home at this harness's
# own sandbox home" — the driver cannot know the mktemp path in advance.
if [ "${FAKE_PASSWD_HOME}" = "__SANDBOX__" ]; then
    FAKE_PASSWD_HOME="${SANDBOX_HOME}"
fi

# --- chown wrapper (installed just before the helper call below) -----------
# The wrapper that counts + records target paths is (re)installed right before
# invoking the helper, so it reliably shadows `chown` for the helper's run and
# records into a temp file that survives the command-substitution subshell.

# --- optional getent wrapper for the passwd-home path ----------------------
# Only installed when we are exercising the passwd-based resolution
# (USE_SIM_HOME=false) and a FAKE_PASSWD_HOME is supplied. It intercepts
# `getent passwd <user>` and returns a synthetic line whose home field points
# at the sandbox home; everything else forwards to the real getent.
if [ "${USE_SIM_HOME}" = "false" ] && [ -n "${FAKE_PASSWD_HOME}" ]; then
    getent() {
        if [ "${1:-}" = "passwd" ]; then
            local u="${2:-}"
            # name:passwd:uid:gid:gecos:home:shell  (home = field 6)
            printf '%s:x:12345:12345::%s:/bin/bash\n' "${u}" "${FAKE_PASSWD_HOME}"
            return 0
        fi
        command getent "$@"
    }
    # Force $HOME to a bogus value so we PROVE the helper does not use it.
    export HOME="/root"
fi

# --- SIM_HOME override, per the chosen resolution path ---------------------
if [ "${USE_SIM_HOME}" = "true" ]; then
    SIM_HOME="${SANDBOX_HOME}"
    export SIM_HOME
else
    unset SIM_HOME || true
fi

# --- source the installer so the helper (if any) loads ---------------------
# shellcheck disable=SC1090
source "${INIT_SCRIPT}"

if declare -F restore_invoking_user_ownership >/dev/null 2>&1; then
    HELPER_DEFINED=1
else
    HELPER_DEFINED=0
fi

# Resolve the expected owner independently (primary group via id -gn).
EXPECT_USER="${SIM_USER}"
EXPECT_GROUP="$(id -gn "${SIM_USER}" 2>/dev/null)"

echo "PROBE context helper_defined=${HELPER_DEFINED} sim_user=[${SIM_USER:-UNSET}] euid=${EUID} use_sim_home=${USE_SIM_HOME} expect_owner=${EXPECT_USER}:${EXPECT_GROUP}"
echo "PROBE paths sandbox_home=${SANDBOX_HOME} decoy_home=${DECOY_HOME} repo_dir=${REPO_DIR}"

# --- invoke the helper and capture its exit + output -----------------------
# The helper is run so its (virtualized) chowns take effect in THIS process
# (fakeroot's ownership table is process-wide). Its stdout/stderr — which
# includes the `PROBE chown_target=` lines emitted by the chown wrapper and any
# `[WARNING]` text — is captured, then re-emitted so the driver can inspect it.
# Counting happens via a temp file because command substitution runs in a
# subshell (CHOWN_CALLS incremented there would not survive).
CALLS_FILE="${SANDBOX}/.chown_calls"
: > "${CALLS_FILE}"
chown() {
    echo x >> "${CALLS_FILE}"
    echo "PROBE chown_target=${!#}"
    command chown "$@"
}

if [ "${HELPER_DEFINED}" = "1" ]; then
    HELPER_OUT="$(restore_invoking_user_ownership 2>&1)"
    HELPER_EXIT=$?
    # Re-emit captured output so the driver sees PROBE chown_target lines.
    printf '%s\n' "${HELPER_OUT}"
    echo "PROBE helper_exit=${HELPER_EXIT}"
    if printf '%s' "${HELPER_OUT}" | grep -qi 'warning'; then
        echo "PROBE helper_warned=1"
    else
        echo "PROBE helper_warned=0"
    fi
fi

CHOWN_CALLS="$(wc -l < "${CALLS_FILE}" | tr -d ' ')"
echo "PROBE chown_calls=${CHOWN_CALLS}"

# --- report resulting ownership of key nodes -------------------------------
report() {
    local label="$1" path="$2"
    if [ -e "${path}" ]; then
        echo "PROBE ${label} owner=$(stat -c '%U:%G' "${path}")"
    else
        echo "PROBE ${label} owner=<missing>"
    fi
}
report clone        "${REPO_DIR}"
report shared       "${REPO_DIR}/shared"
report sandbox_aws  "${SANDBOX_HOME}/.aws"
report sandbox_depl "${SANDBOX_HOME}/deployments"
report decoy_aws    "${DECOY_HOME}/.aws"
report decoy_depl   "${DECOY_HOME}/deployments"

rm -rf "${SANDBOX}"
