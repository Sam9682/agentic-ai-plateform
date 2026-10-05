#!/bin/bash
# ---------------------------------------------------------------------------
# integration_harness.sh — shared harness for the init-pltf-root-ownership-fix
# INTEGRATION tests (Task 4).
#
# A single sourced process that exercises the END-TO-END ownership-restore
# flow across MULTIPLE trees and contexts, so the driver can assert the three
# integration behaviours from the design Testing Strategy:
#
#   I-source  : sourcing init_pltf.sh defines the helper WITHOUT running the
#               installer body and WITHOUT performing any chown. We prove this
#               by installing a chown counter BEFORE sourcing and emitting a
#               marker the installer body would print if it ran.
#   I-switch  : context-switching — the SAME sourced helper is invoked first
#               under a NON-BUG context (separate tree A, natural ownership) and
#               then under a BUG context (separate tree B, forced root:root).
#               Each tree is handled independently: A untouched, B fully
#               restored.
#
# The full-flow integration case (whole mirror tree + home artifacts flips in
# one pass under a bug context) is driven by the existing ownership_harness.sh,
# reused by the driver rather than duplicated here.
#
# Emits machine-readable PROBE lines; all assertions live in the driver.
# fakeroot virtualizes EUID/chown/stat.
# ---------------------------------------------------------------------------
set -u

HARNESS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${HARNESS_DIR}/../.." && pwd)"
INIT_SCRIPT="${REPO_ROOT}/init_pltf.sh"

# The REAL invoking user must be supplied by the driver (which runs OUTSIDE
# fakeroot). Under fakeroot `id -un` returns root, which would wrongly collapse
# the bug context (SUDO_USER=root is non-bug), so we never derive it here.
INVOKER="${REAL_INVOKER:?REAL_INVOKER must be set by the driver}"
INVOKER_GROUP="${REAL_INVOKER_GROUP:?REAL_INVOKER_GROUP must be set by the driver}"

# --- chown counter installed BEFORE sourcing -------------------------------
# If merely sourcing the script performed any chown (installer body running),
# this counter would be non-zero immediately after the source.
SANDBOX="$(mktemp -d)"
CALLS_FILE="${SANDBOX}/.chown_calls"
: > "${CALLS_FILE}"
chown() {
    echo x >> "${CALLS_FILE}"
    command chown "$@"
}

# A sentinel the installer body echoes (its first print_step). If sourcing ran
# the body we would see installer output. We capture stdout of the source.
SRC_OUT="$(source "${INIT_SCRIPT}"; echo "__SOURCE_RETURNED__")"
# Re-source for real so the helper is defined in THIS shell (the subshell above
# only proved the body does not run / return a marker without side effects).
# shellcheck disable=SC1090
source "${INIT_SCRIPT}"

CHOWN_AFTER_SOURCE="$(wc -l < "${CALLS_FILE}" | tr -d ' ')"

if declare -F restore_invoking_user_ownership >/dev/null 2>&1; then
    HELPER_DEFINED=1
else
    HELPER_DEFINED=0
fi

# Did the sourced subshell print anything that looks like installer execution?
# The installer body's first visible action is a print_step banner ("Collect
# platform identity ..."/"Starting ..."). Its total absence (only our marker)
# demonstrates the body did not run.
if printf '%s' "${SRC_OUT}" | grep -qE 'Installation|Starting|Collect|apt |docker '; then
    BODY_RAN=1
else
    BODY_RAN=0
fi

echo "PROBE source helper_defined=${HELPER_DEFINED} chown_after_source=${CHOWN_AFTER_SOURCE} body_ran=${BODY_RAN} returned=$(printf '%s' "${SRC_OUT}" | grep -c __SOURCE_RETURNED__)"

# --- build two independent trees -------------------------------------------
build_tree() {
    # $1 = root dir to create
    local r="$1"
    mkdir -p "${r}/shared" "${r}/.venv/bin" "${r}/logs" "${r}/conf"
    printf 'PLTF_NAME=demo\nPLTF_FOLDER=demo\n' > "${r}/conf/deploy.ini"
    printf '#!/bin/sh\n' > "${r}/.venv/bin/activate"
    : > "${r}/README.md"
}

TREE_A="${SANDBOX}/treeA/clone"   # non-bug context tree (must stay untouched)
TREE_B="${SANDBOX}/treeB/clone"   # bug context tree (must be fully restored)
build_tree "${TREE_A}"
build_tree "${TREE_B}"

HOME_A="${SANDBOX}/treeA/home"
HOME_B="${SANDBOX}/treeB/home"
mkdir -p "${HOME_A}/.aws" "${HOME_A}/deployments/admin"
mkdir -p "${HOME_B}/.aws" "${HOME_B}/deployments/admin"
printf '[default]\n' > "${HOME_A}/.aws/credentials"
printf '[default]\n' > "${HOME_B}/.aws/credentials"

report_tree() {
    # $1 = tag, $2 = clone root, $3 = home
    local tag="$1" clone="$2" home="$3" p
    while IFS= read -r p; do
        echo "PROBE ${tag} owner=$(stat -c '%U:%G' "${p}") path=${p}"
    done < <(find "${clone}"; find "${home}/.aws" "${home}/deployments")
}

# ---------------------------------------------------------------------------
# STEP 1 — context switch: NON-BUG context against TREE_A.
#   Under this harness's natural (non-root) invocation, EUID != 0 so the helper
#   is a no-op. We additionally force SUDO_USER unset to be explicit. Tree A
#   keeps its natural (invoking-user) ownership.
# ---------------------------------------------------------------------------
# Snapshot pre-ownership of tree A.
PRE_A="$(report_tree A_pre "${TREE_A}" "${HOME_A}")"
echo "${PRE_A}"

CALLS_BEFORE_A="$(wc -l < "${CALLS_FILE}" | tr -d ' ')"
(
    REPO_DIR="${TREE_A}"; export REPO_DIR
    SIM_HOME="${HOME_A}"; export SIM_HOME
    unset SUDO_USER || true
    restore_invoking_user_ownership
) >/dev/null 2>&1
CALLS_AFTER_A="$(wc -l < "${CALLS_FILE}" | tr -d ' ')"
echo "PROBE switchA chown_delta=$((CALLS_AFTER_A - CALLS_BEFORE_A))"
report_tree A_post "${TREE_A}" "${HOME_A}"

# ---------------------------------------------------------------------------
# STEP 2 — context switch: BUG context against TREE_B.
#   Force tree B root:root (models the sudo run), set SUDO_USER to the invoking
#   user, and invoke the SAME helper. Tree B must be fully restored to the
#   invoking user:group in one pass; tree A must remain untouched by this call.
# ---------------------------------------------------------------------------
command chown -R root:root "${TREE_B}" "${HOME_B}/.aws" "${HOME_B}/deployments"
echo "PROBE expect_owner=${INVOKER}:${INVOKER_GROUP}"

CALLS_BEFORE_B="$(wc -l < "${CALLS_FILE}" | tr -d ' ')"
(
    REPO_DIR="${TREE_B}"; export REPO_DIR
    SIM_HOME="${HOME_B}"; export SIM_HOME
    SUDO_USER="${INVOKER}"; export SUDO_USER
    restore_invoking_user_ownership
) >/dev/null 2>&1
CALLS_AFTER_B="$(wc -l < "${CALLS_FILE}" | tr -d ' ')"
echo "PROBE switchB chown_delta=$((CALLS_AFTER_B - CALLS_BEFORE_B))"
report_tree B_post "${TREE_B}" "${HOME_B}"
# Re-report tree A to prove the bug-context call did not touch it.
report_tree A_after_B "${TREE_A}" "${HOME_A}"

rm -rf "${SANDBOX}"
