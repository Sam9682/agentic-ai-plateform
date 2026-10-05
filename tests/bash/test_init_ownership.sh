#!/bin/bash
# ---------------------------------------------------------------------------
# test_init_ownership.sh
#   Spec:  init-pltf-root-ownership-fix  (Task 1)
#   Property 1 (Bug Condition): the clone destination and the user-space
#   artifacts created by init_pltf.sh are left root-owned when the installer
#   runs under sudo (EUID 0 with a real non-root SUDO_USER), because no step
#   restores ownership to the invoking user.
#
#   Validates: Requirements 1.1, 1.2, 1.3, 1.4
#
# This is a BUG-CONDITION EXPLORATION test. It encodes the EXPECTED (post-fix)
# behavior and is run against the UNFIXED init_pltf.sh, where it MUST FAIL —
# that failure is the success criterion: it demonstrates the bug exists. The
# same test is re-run after the fix (Task 3.3) and must then PASS.
#
# Scoped property-based enumeration: the bug is deterministic for the sudo
# context, so the "property" is checked over the concrete failing cases
# demanded by the design's Test Plan — the clone root, its nested artifacts,
# the home artifacts, and the group-resolution edge (user whose primary group
# name differs from the username).
#
# Ownership is virtualized with fakeroot, so no real privilege is needed:
# fakeroot reports EUID 0 (realizing the bug context) and makes chown/stat
# operate on a virtual ownership table.
# ---------------------------------------------------------------------------
set -u

HARNESS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HARNESS="${HARNESS_DIR}/ownership_harness.sh"

# Pick a real, non-root invoking user for the main cases: whoever runs the
# test (its passwd entry is guaranteed to exist).
INVOKER="$(id -un)"

PASS=0
FAIL=0
pass() { echo "  [PASS] $1"; PASS=$((PASS + 1)); }
fail() { echo "  [FAIL] $1"; FAIL=$((FAIL + 1)); }

# Run the harness under fakeroot with a given SUDO_USER and capture PROBEs.
run_ctx() {
    # $1 = SUDO_USER, $2 = BUILD_HOME_ART
    SUDO_USER="$1" BUILD_HOME_ART="$2" fakeroot bash "${HARNESS}" 2>/dev/null
}

# Extract "owner=<val>" for a given PROBE label from captured output.
owner_of() {
    # $1 = probe output, $2 = label
    printf '%s\n' "$1" | awk -v l="$2" '$1=="PROBE" && $2==l {print}' \
        | sed -n 's/.*owner=\([^ ]*\).*/\1/p' | head -n1
}
field() {
    # $1 = probe output, $2 = key (e.g. expect_owner)
    printf '%s\n' "$1" | sed -n "s/.*$2=\\([^ ]*\\).*/\\1/p" | head -n1
}

echo "=================================================================="
echo "Property 1 (Bug Condition) exploration — UNFIXED init_pltf.sh"
echo "Invoking user for main cases: ${INVOKER}"
echo "=================================================================="

# ---------------------------------------------------------------------------
# Guard: sourcing init_pltf.sh must not run the installer body, and on unfixed
# code restore_invoking_user_ownership is undefined (or at worst a no-op).
# ---------------------------------------------------------------------------
OUT="$(run_ctx "${INVOKER}" true)"
HELPER_DEFINED="$(field "${OUT}" helper_defined)"
EXPECT_OWNER="$(field "${OUT}" expect_owner)"
SIM_EUID="$(field "${OUT}" euid)"

echo "--- Context: EUID=${SIM_EUID}, SUDO_USER=${INVOKER} (bug condition) ---"
echo "    helper_defined=${HELPER_DEFINED}  expected owner=${EXPECT_OWNER}"

# Sanity: the simulated bug context must actually have EUID 0 (fakeroot).
if [ "${SIM_EUID}" = "0" ]; then
    pass "bug context realized (EUID == 0 via fakeroot)"
else
    fail "bug context NOT realized (EUID=${SIM_EUID}); fakeroot missing?"
fi

# ---------------------------------------------------------------------------
# Test case 1 — Clone root-owned
#   Requirement 1.1 / Expected 2.1: the clone destination must end up owned by
#   the invoking user. On unfixed code it stays root:root.
# ---------------------------------------------------------------------------
echo "--- Test case 1: clone destination ownership (req 1.1) ---"
CLONE_OWNER="$(owner_of "${OUT}" clone)"
echo "    clone owner=${CLONE_OWNER}  (expected ${EXPECT_OWNER})"
if [ "${CLONE_OWNER}" = "${EXPECT_OWNER}" ]; then
    pass "clone owned by invoking user"
else
    fail "clone owned by ${CLONE_OWNER}, expected ${EXPECT_OWNER}"
fi

# ---------------------------------------------------------------------------
# Test case 2 — Nested artifacts
#   Requirement 1.2 / Expected 2.2: shared, .venv, logs, conf/deploy.ini must
#   be owned by the invoking user, recursively. On unfixed code: root:root.
# ---------------------------------------------------------------------------
echo "--- Test case 2: nested artifacts ownership (req 1.2) ---"
for node in shared venv venv_bin logs deploy_ini readme; do
    o="$(owner_of "${OUT}" "${node}")"
    echo "    ${node} owner=${o}  (expected ${EXPECT_OWNER})"
    if [ "${o}" = "${EXPECT_OWNER}" ]; then
        pass "${node} owned by invoking user"
    else
        fail "${node} owned by ${o}, expected ${EXPECT_OWNER}"
    fi
done

# ---------------------------------------------------------------------------
# Test case 3 — Home artifacts
#   Requirement 1.2 / Expected 2.2: ~/.aws and ~/deployments/admin must be
#   owned by the invoking user. On unfixed code: root:root.
# ---------------------------------------------------------------------------
echo "--- Test case 3: home artifacts ownership (req 1.2) ---"
for node in aws aws_creds deployments admin; do
    o="$(owner_of "${OUT}" "${node}")"
    echo "    ${node} owner=${o}  (expected ${EXPECT_OWNER})"
    if [ "${o}" = "${EXPECT_OWNER}" ]; then
        pass "${node} owned by invoking user"
    else
        fail "${node} owned by ${o}, expected ${EXPECT_OWNER}"
    fi
done

# ---------------------------------------------------------------------------
# Requirement 1.3 — invoking user cannot modify/deploy without sudo.
# Modeled: if the clone is still root-owned under the bug context, a non-root
# invoking user has no ownership of it (the practical blocker reported).
# ---------------------------------------------------------------------------
echo "--- Test case: usability without sudo (req 1.3) ---"
CLONE_USER="${CLONE_OWNER%%:*}"
if [ "${CLONE_USER}" = "${INVOKER}" ]; then
    pass "clone usable by invoking user without sudo"
else
    fail "clone owned by ${CLONE_USER}, invoking user ${INVOKER} would need sudo"
fi

# ---------------------------------------------------------------------------
# Requirement 1.4 — no step restores ownership.
# On unfixed code the helper is undefined, so no restoration can occur; the
# tree remains exactly as the simulated root run left it (root:root).
# ---------------------------------------------------------------------------
echo "--- Test case: ownership restoration performed (req 1.4) ---"
if [ "${HELPER_DEFINED}" = "1" ]; then
    pass "restore_invoking_user_ownership is defined (fix present)"
else
    fail "no ownership-restoration step exists (restore_invoking_user_ownership undefined)"
fi

# ---------------------------------------------------------------------------
# Test case 4 — Group-resolution edge
#   Requirement 2.4: for an invoking user whose PRIMARY GROUP name differs from
#   the username, the fix must apply user:<primary-group> (resolved via id -gn),
#   not a naive user:user. We pick the `nobody` user (primary group `nogroup`)
#   when available. On unfixed code the tree stays root-owned, so this fails;
#   it also guards against a naive user:user fix once implemented.
# ---------------------------------------------------------------------------
echo "--- Test case 4: group-resolution edge (req 2.4) ---"
EDGE_USER="nobody"
EDGE_GROUP="$(id -gn "${EDGE_USER}" 2>/dev/null)"
if [ -z "${EDGE_GROUP}" ]; then
    echo "    [SKIP] user '${EDGE_USER}' not present; cannot exercise group edge"
elif [ "${EDGE_GROUP}" = "${EDGE_USER}" ]; then
    echo "    [SKIP] '${EDGE_USER}' primary group equals username; no edge to test"
else
    EOUT="$(run_ctx "${EDGE_USER}" false)"
    EDGE_CLONE_OWNER="$(owner_of "${EOUT}" clone)"
    EXPECT_EDGE="${EDGE_USER}:${EDGE_GROUP}"
    NAIVE="${EDGE_USER}:${EDGE_USER}"
    echo "    clone owner=${EDGE_CLONE_OWNER}  expected ${EXPECT_EDGE}  (naive wrong = ${NAIVE})"
    if [ "${EDGE_CLONE_OWNER}" = "${EXPECT_EDGE}" ]; then
        pass "group resolved via primary group (${EXPECT_EDGE})"
    else
        fail "clone owner ${EDGE_CLONE_OWNER}, expected ${EXPECT_EDGE} (resolved primary group)"
    fi
fi

echo "=================================================================="
echo "RESULT: ${PASS} passed, ${FAIL} failed"
echo "=================================================================="
if [ "${FAIL}" -gt 0 ]; then
    echo "EXPLORATION OUTCOME: test FAILED on unfixed code (expected) — bug confirmed."
    exit 1
fi
echo "EXPLORATION OUTCOME: test PASSED — ownership restored (fix present)."
exit 0
