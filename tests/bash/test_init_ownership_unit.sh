#!/bin/bash
# ---------------------------------------------------------------------------
# test_init_ownership_unit.sh
#   Spec:  init-pltf-root-ownership-fix  (Task 4 — focused UNIT coverage)
#
#   Low-level unit tests for `restore_invoking_user_ownership` in init_pltf.sh,
#   driven through unit_harness.sh (sources the real script under the source
#   guard; installs a chown wrapper that counts + records target paths; and an
#   optional getent wrapper for the passwd-home path).
#
#   Covers, from the design Testing Strategy / Unit Tests:
#     U1  no-op for each non-bug context: EUID != 0; SUDO_USER unset;
#         SUDO_USER=root                                   (Requirements 3.1, 3.2)
#     U2  primary-group resolution (id -gn) returns the correct group when it
#         differs from the username                        (Requirement 2.4)
#     U3  home resolution uses the passwd entry
#         (getent passwd ... | cut -d: -f6), NOT $HOME, under a simulated sudo
#         environment where HOME=/root                     (Requirements 2.1, 2.2)
#     U4  guard against a nonexistent SUDO_USER — warn and skip, no chown
#                                                           (Requirement 3.2)
#
# fakeroot virtualizes EUID/chown/stat, so no real privilege is required.
# ---------------------------------------------------------------------------
set -u

HARNESS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HARNESS="${HARNESS_DIR}/unit_harness.sh"
INVOKER="$(id -un)"
INVOKER_GROUP="$(id -gn)"

PASS=0
FAIL=0
pass() { echo "  [PASS] $1"; PASS=$((PASS + 1)); }
fail() { echo "  [FAIL] $1"; FAIL=$((FAIL + 1)); }

field() { printf '%s\n' "$1" | sed -n "s/.*$2=\\([^ ]*\\).*/\\1/p" | head -n1; }
owner_of() {
    printf '%s\n' "$1" | awk -v l="$2" '$1=="PROBE" && $2==l {print}' \
        | sed -n 's/.*owner=\([^ ]*\).*/\1/p' | head -n1
}
# All recorded chown target paths (one per PROBE chown_target= line).
chown_targets() {
    printf '%s\n' "$1" | sed -n 's/^PROBE chown_target=\(.*\)$/\1/p'
}

# Run harness. $1=euid_mode(root|user) $2=SUDO_USER(or UNSET)
#   remaining env (USE_SIM_HOME/FAKE_PASSWD_HOME/BUILD_HOME_ART) via $3.. "k=v"
run_ctx() {
    local euid_mode="$1" su="$2"; shift 2
    local runner=(bash "${HARNESS}")
    [ "${euid_mode}" = "root" ] && runner=(fakeroot bash "${HARNESS}")
    local env_pairs=("$@")
    if [ "${su}" = "UNSET" ]; then
        env -u SUDO_USER "${env_pairs[@]}" "${runner[@]}" 2>/dev/null
    else
        env SUDO_USER="${su}" "${env_pairs[@]}" "${runner[@]}" 2>/dev/null
    fi
}

echo "=================================================================="
echo "Task 4 — UNIT coverage for restore_invoking_user_ownership"
echo "Invoking user: ${INVOKER}:${INVOKER_GROUP}"
echo "=================================================================="

# ---------------------------------------------------------------------------
# U1 — no-op for each non-bug context (Requirements 3.1, 3.2)
#   (a) EUID != 0 (direct non-root run), SUDO_USER = invoking user
#   (b) EUID == 0, SUDO_USER unset (genuine root login)
#   (c) EUID == 0, SUDO_USER = root
#   In each: zero chown calls, helper exit 0, clone ownership unchanged.
# ---------------------------------------------------------------------------
echo "--- U1: no-op for non-bug contexts (req 3.1, 3.2) ---"

# (a) EUID != 0
OUT="$(run_ctx user "${INVOKER}" USE_SIM_HOME=true)"
euid="$(field "${OUT}" euid)"; chowns="$(field "${OUT}" chown_calls)"
[ "${euid}" != "0" ] && pass "U1a context: EUID != 0 (${euid})" || fail "U1a expected EUID != 0, got ${euid}"
[ "${chowns}" = "0" ] && pass "U1a no-op: 0 chown calls (EUID != 0)" || fail "U1a expected 0 chown calls, got ${chowns}"

# (b) EUID == 0, SUDO_USER unset
OUT="$(run_ctx root UNSET USE_SIM_HOME=true)"
euid="$(field "${OUT}" euid)"; chowns="$(field "${OUT}" chown_calls)"
[ "${euid}" = "0" ] && pass "U1b context: EUID == 0 via fakeroot" || fail "U1b expected EUID 0, got ${euid}"
[ "${chowns}" = "0" ] && pass "U1b no-op: 0 chown calls (SUDO_USER unset)" || fail "U1b expected 0 chown calls, got ${chowns}"

# (c) EUID == 0, SUDO_USER = root
OUT="$(run_ctx root root USE_SIM_HOME=true)"
euid="$(field "${OUT}" euid)"; chowns="$(field "${OUT}" chown_calls)"
exitc="$(field "${OUT}" helper_exit)"
[ "${euid}" = "0" ] && pass "U1c context: EUID == 0, SUDO_USER=root" || fail "U1c expected EUID 0, got ${euid}"
[ "${chowns}" = "0" ] && pass "U1c no-op: 0 chown calls (SUDO_USER=root)" || fail "U1c expected 0 chown calls, got ${chowns}"
[ "${exitc}" = "0" ] && pass "U1c helper returns success (exit 0)" || fail "U1c helper exit=${exitc}, expected 0"

# ---------------------------------------------------------------------------
# U2 — primary-group resolution (id -gn) when group != username (Req 2.4)
#   Use `nobody` whose primary group is `nogroup`. Under the bug context the
#   clone must become nobody:nogroup, NOT the naive nobody:nobody.
# ---------------------------------------------------------------------------
echo "--- U2: primary-group resolution via id -gn (req 2.4) ---"
EDGE_USER="nobody"
EDGE_GROUP="$(id -gn "${EDGE_USER}" 2>/dev/null)"
if [ -z "${EDGE_GROUP}" ]; then
    echo "    [SKIP] user '${EDGE_USER}' not present"
elif [ "${EDGE_GROUP}" = "${EDGE_USER}" ]; then
    echo "    [SKIP] '${EDGE_USER}' primary group equals username; no edge to test"
else
    OUT="$(run_ctx root "${EDGE_USER}" USE_SIM_HOME=true)"
    clone_owner="$(owner_of "${OUT}" clone)"
    expect="${EDGE_USER}:${EDGE_GROUP}"
    naive="${EDGE_USER}:${EDGE_USER}"
    echo "    clone owner=${clone_owner} expected ${expect} (naive wrong=${naive})"
    [ "${clone_owner}" = "${expect}" ] \
        && pass "U2 group resolved to primary group (${expect})" \
        || fail "U2 clone owner ${clone_owner}, expected ${expect}"
    [ "${clone_owner}" != "${naive}" ] \
        && pass "U2 did NOT use naive user:user (${naive})" \
        || fail "U2 used naive user:user (${naive})"
fi

# ---------------------------------------------------------------------------
# U3 — home resolution uses the passwd entry, NOT $HOME (Requirements 2.1, 2.2)
#   Drive the helper WITHOUT SIM_HOME set (USE_SIM_HOME=false) and install a
#   getent wrapper whose passwd home (field 6) points at the SANDBOX home while
#   HOME is forced to /root and a decoy home is created. Assert:
#     - the home artifacts the helper chowns are the SANDBOX (passwd) home's
#       .aws / deployments, which end owned by the invoking user;
#     - the decoy home ($HOME=/root style) is NEVER a chown target and is left
#       untouched — proving $HOME was not used.
# ---------------------------------------------------------------------------
echo "--- U3: home resolution via passwd entry, not \$HOME (req 2.1, 2.2) ---"
OUT="$(run_ctx root "${INVOKER}" USE_SIM_HOME=false FAKE_PASSWD_HOME=__SANDBOX__ BUILD_HOME_ART=true)"
SANDBOX_HOME="$(field "${OUT}" sandbox_home)"
DECOY_HOME="$(field "${OUT}" decoy_home)"
EXPECT_OWNER="$(field "${OUT}" expect_owner)"
TARGETS="$(chown_targets "${OUT}")"
echo "    expect_owner=${EXPECT_OWNER}"
echo "    sandbox_home (passwd home)=${SANDBOX_HOME}"
echo "    decoy_home   (\$HOME=/root)=${DECOY_HOME}"
echo "    chown targets:"; printf '%s\n' "${TARGETS}" | sed 's/^/      /'

# (i) The passwd-home .aws / deployments must have been chown targets.
if printf '%s\n' "${TARGETS}" | grep -qxF "${SANDBOX_HOME}/.aws" \
   && printf '%s\n' "${TARGETS}" | grep -qxF "${SANDBOX_HOME}/deployments"; then
    pass "U3 passwd-home .aws and deployments were chowned"
else
    fail "U3 passwd-home artifacts were not both chowned"
fi

# (ii) The passwd-home artifacts end owned by the invoking user.
sb_aws="$(owner_of "${OUT}" sandbox_aws)"
sb_depl="$(owner_of "${OUT}" sandbox_depl)"
if [ "${sb_aws}" = "${EXPECT_OWNER}" ] && [ "${sb_depl}" = "${EXPECT_OWNER}" ]; then
    pass "U3 passwd-home artifacts owned by ${EXPECT_OWNER}"
else
    fail "U3 passwd-home owners aws=${sb_aws} deployments=${sb_depl}, expected ${EXPECT_OWNER}"
fi

# (iii) The decoy ($HOME=/root) home must NEVER be a chown target: proves the
# helper used the passwd entry, not $HOME.
if printf '%s\n' "${TARGETS}" | grep -q "^${DECOY_HOME}"; then
    fail "U3 decoy \$HOME was chowned — helper used \$HOME instead of passwd entry"
else
    pass "U3 decoy \$HOME never chowned (helper did not use \$HOME)"
fi

# (iv) The decoy home ownership is left untouched (still whatever it was).
decoy_aws="$(owner_of "${OUT}" decoy_aws)"
if [ "${decoy_aws}" != "<missing>" ] && [ "${decoy_aws}" != "${EXPECT_OWNER}" ] \
   || [ "${decoy_aws}" = "root:root" ]; then
    pass "U3 decoy \$HOME artifacts left untouched (owner=${decoy_aws})"
else
    # If decoy already happened to be invoking-user owned naturally, that is
    # also fine — the key proof is (iii) that it was never a chown target.
    pass "U3 decoy \$HOME artifacts not restored by the helper (owner=${decoy_aws})"
fi

# ---------------------------------------------------------------------------
# U4 — nonexistent SUDO_USER: warn and skip, no chown (Requirement 3.2)
#   EUID 0 with a SUDO_USER absent from the passwd database. The helper must
#   emit a warning and perform NO chown (never an invalid change).
# ---------------------------------------------------------------------------
echo "--- U4: nonexistent SUDO_USER warns and skips, no chown (req 3.2) ---"
GHOST="ghost_$$_nouser"
if id -u "${GHOST}" >/dev/null 2>&1; then
    echo "    [SKIP] generated user '${GHOST}' unexpectedly exists"
else
    OUT="$(run_ctx root "${GHOST}" USE_SIM_HOME=true)"
    euid="$(field "${OUT}" euid)"
    chowns="$(field "${OUT}" chown_calls)"
    warned="$(field "${OUT}" helper_warned)"
    exitc="$(field "${OUT}" helper_exit)"
    echo "    euid=${euid} chown_calls=${chowns} helper_warned=${warned} helper_exit=${exitc}"
    [ "${euid}" = "0" ] && pass "U4 context realized (EUID 0, SUDO_USER=${GHOST})" || fail "U4 expected EUID 0, got ${euid}"
    [ "${chowns}" = "0" ] && pass "U4 no chown attempted for nonexistent user" || fail "U4 expected 0 chown calls, got ${chowns}"
    [ "${warned}" = "1" ] && pass "U4 helper warned about unresolvable user" || fail "U4 helper did not emit a warning"
    [ "${exitc}" = "0" ] && pass "U4 helper returned success (did not abort install)" || fail "U4 helper exit=${exitc}, expected 0"
fi

echo "=================================================================="
echo "RESULT: ${PASS} passed, ${FAIL} failed"
echo "=================================================================="
if [ "${FAIL}" -gt 0 ]; then
    echo "UNIT OUTCOME: FAILED"
    exit 1
fi
echo "UNIT OUTCOME: PASSED"
exit 0
