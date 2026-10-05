#!/bin/bash
# ---------------------------------------------------------------------------
# property_harness.sh — shared harness for the init-pltf-root-ownership-fix
# PROPERTY-BASED tests (Task 4).
#
# Sources the REAL init_pltf.sh under the source guard (so only the function
# definitions load, the installer body never runs). It then builds a RANDOMLY
# SHAPED directory tree under REPO_DIR (random breadth/depth of dirs and files,
# seed-driven for reproducibility) plus the home artifacts, applies a
# caller-chosen run context, optionally invokes `restore_invoking_user_ownership`
# if present, and reports — for the WHOLE tree, recursively — the single most
# important fact for each node: its resulting owner:group.
#
# It emits:
#   PROBE context ...                      (helper_defined, sim_user, euid, seed)
#   PROBE node pre=<o:g> post=<o:g> path=<p>   (one per node, recursively)
#   PROBE chown_calls=N
#
# Two property modes are supported by the two drivers:
#   - BUG mode  (forced root:root, EUID 0 via fakeroot, valid non-root
#     SUDO_USER): the driver asserts EVERY node's post == invoking user:group.
#   - NONBUG mode (natural ownership, a non-bug context): the driver asserts
#     EVERY node's post == its pre AND chown_calls == 0.
#
# Context parameters (env-driven):
#   SEED            : integer seed for the random tree shape (reproducibility).
#   SUDO_USER       : simulated invoking user (unset / root / real / ghost).
#   FORCE_ROOT      : "true" to chown -R root:root the whole tree before the
#                     run (models the sudo bug). "false" leaves natural
#                     ownership (preservation). Default "false".
#   USE_SIM_HOME    : "true" (default) to point the helper's home-artifact
#                     restore at the sandbox home via SIM_HOME.
#   BUILD_HOME_ART  : "true" (default) to also build ~/.aws and ~/deployments.
# ---------------------------------------------------------------------------
set -u

HARNESS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${HARNESS_DIR}/../.." && pwd)"
INIT_SCRIPT="${REPO_ROOT}/init_pltf.sh"

SEED="${SEED:-1}"
SIM_USER="${SUDO_USER:-}"
FORCE_ROOT="${FORCE_ROOT:-false}"
USE_SIM_HOME="${USE_SIM_HOME:-true}"
BUILD_HOME_ART="${BUILD_HOME_ART:-true}"

RANDOM=${SEED}

# --- chown counter (survives the command-substitution subshell) ------------
SANDBOX="$(mktemp -d)"
CALLS_FILE="${SANDBOX}/.chown_calls"
: > "${CALLS_FILE}"
chown() {
    echo x >> "${CALLS_FILE}"
    command chown "$@"
}

# --- source the installer so the helper (if any) loads ---------------------
# shellcheck disable=SC1090
source "${INIT_SCRIPT}"

if declare -F restore_invoking_user_ownership >/dev/null 2>&1; then
    HELPER_DEFINED=1
else
    HELPER_DEFINED=0
fi

# --- build a RANDOMLY SHAPED clone tree ------------------------------------
REPO_DIR="${SANDBOX}/clone"
export REPO_DIR
# Always include the canonical artifacts the design calls out, so the shape is
# "random PLUS the real structure".
mkdir -p "${REPO_DIR}/shared" "${REPO_DIR}/.venv/bin" "${REPO_DIR}/logs" "${REPO_DIR}/conf"
printf 'PLTF_NAME=demo\nPLTF_FOLDER=demo\n' > "${REPO_DIR}/conf/deploy.ini"
printf '#!/bin/sh\n' > "${REPO_DIR}/.venv/bin/activate"
: > "${REPO_DIR}/README.md"

# Recursively grow a random subtree: random number of files and subdirs at
# each level, bounded depth. Deterministic for a given SEED.
grow() {
    local dir="$1" depth="$2"
    local nfiles=$((RANDOM % 4))      # 0..3 files here
    local i
    for ((i = 0; i < nfiles; i++)); do
        : > "${dir}/f${depth}_${i}_$((RANDOM % 1000))"
    done
    [ "${depth}" -le 0 ] && return 0
    local ndirs=$((RANDOM % 3))       # 0..2 subdirs here
    for ((i = 0; i < ndirs; i++)); do
        local sub="${dir}/d${depth}_${i}_$((RANDOM % 1000))"
        mkdir -p "${sub}"
        grow "${sub}" $((depth - 1))
    done
}
grow "${REPO_DIR}" 3
grow "${REPO_DIR}/shared" 2

# --- home artifacts --------------------------------------------------------
SANDBOX_HOME="${SANDBOX}/home"
mkdir -p "${SANDBOX_HOME}"
if [ "${BUILD_HOME_ART}" = "true" ]; then
    mkdir -p "${SANDBOX_HOME}/.aws"
    printf '[default]\n' > "${SANDBOX_HOME}/.aws/credentials"
    mkdir -p "${SANDBOX_HOME}/deployments/admin"
fi
if [ "${USE_SIM_HOME}" = "true" ]; then
    SIM_HOME="${SANDBOX_HOME}"
    export SIM_HOME
fi

# --- optionally force root:root (models the sudo bug) ----------------------
if [ "${FORCE_ROOT}" = "true" ]; then
    command chown -R root:root "${REPO_DIR}"
    [ "${BUILD_HOME_ART}" = "true" ] && command chown -R root:root "${SANDBOX_HOME}/.aws" "${SANDBOX_HOME}/deployments"
fi

# --- enumerate every node of interest (clone tree + home artifacts) --------
mapfile -t NODES < <(find "${REPO_DIR}"; \
    [ "${BUILD_HOME_ART}" = "true" ] && find "${SANDBOX_HOME}/.aws" "${SANDBOX_HOME}/deployments")

declare -A PRE
for p in "${NODES[@]}"; do
    PRE["${p}"]="$(stat -c '%U:%G' "${p}")"
done

echo "PROBE context helper_defined=${HELPER_DEFINED} sim_user=[${SIM_USER:-UNSET}] euid=${EUID} seed=${SEED} nodes=${#NODES[@]} force_root=${FORCE_ROOT}"

# --- invoke the helper if present ------------------------------------------
if [ "${HELPER_DEFINED}" = "1" ]; then
    restore_invoking_user_ownership >/dev/null 2>&1 || echo "PROBE helper_exit=$?"
fi

CHOWN_CALLS="$(wc -l < "${CALLS_FILE}" | tr -d ' ')"
echo "PROBE chown_calls=${CHOWN_CALLS}"

# --- report pre/post ownership for every node ------------------------------
for p in "${NODES[@]}"; do
    post="<missing>"
    [ -e "${p}" ] && post="$(stat -c '%U:%G' "${p}")"
    echo "PROBE node pre=${PRE[${p}]} post=${post} path=${p}"
done

rm -rf "${SANDBOX}"
