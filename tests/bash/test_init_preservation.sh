#!/bin/bash
# ---------------------------------------------------------------------------
# test_init_preservation.sh
#   Spec:  init-pltf-root-ownership-fix  (Task 2)
#   Property 2 (Preservation): for every run where the bug condition does NOT
#   hold — a direct non-root run (EUID != 0), a genuine root login with
#   SUDO_USER unset, SUDO_USER == root, or an EUID-0 run whose SUDO_USER is
#   absent from the passwd database — the fixed script must behave exactly as
#   the original: ownership is left as the pre-run state produced it, no
#   `chown` is attempted, no invalid `chown` is run, and the helper is a no-op.
#
#   Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6
#
# OBSERVATION-FIRST METHODOLOGY
# This test was authored by first running the UNFIXED (helper-absent) path on
# each non-bug context and recording the actual ownership outcome, then
# asserting exactly that. Observed on unfixed init_pltf.sh (helper_defined=0):
#   - non-root (EUID 1000), SUDO_USER unset  : tree owned by invoking user,
#                                              before == after, no chown.
#   - non-root (EUID 1000), SUDO_USER=<user> : same — before == after, no chown.
#   - bare-root (fakeroot EUID 0), SUDO_USER unset : tree owned root:root,
#                                              before == after, no chown.
#   - root (fakeroot EUID 0), SUDO_USER=root : before == after, no chown.
#   - root (fakeroot EUID 0), SUDO_USER=ghost (absent) : before == after,
#                                              no chown.
# The property asserted is therefore: for every non-bug context, every node's
# post-run owner:group equals its pre-run owner:group AND zero `chown` calls
# were made. These assertions PASS on the UNFIXED code (helper absent → no-op)
# and must keep PASSING after the fix (helper early-returns before any chown).
#
# PROPERTY-BASED APPROACH
# Preservation is checked over a GENERATED space of non-bug contexts: the EUID
# dimension (0 via fakeroot / non-0), the SUDO_USER dimension (unset / root /
# a real non-root user / a nonexistent user — all non-bug except the real
# non-root user is only non-bug when EUID != 0), the home-artifact dimension
# (present / absent), and the tree-shape dimension (min / full). Each generated
# context asserts ownership is identical to the pre-run state and no chown is
# attempted.
#
# Ownership and EUID are virtualized with fakeroot where EUID 0 is needed, so
# no real privilege is required.
# ---------------------------------------------------------------------------
set -u

HARNESS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HARNESS="${HARNESS_DIR}/preservation_harness.sh"
INVOKER="$(id -un)"

PASS=0
FAIL=0
pass() { echo "  [PASS] $1"; PASS=$((PASS + 1)); }
fail() { echo "  [FAIL] $1"; FAIL=$((FAIL + 1)); }

# Run the harness in a non-bug context and capture PROBEs.
#   $1 = euid_mode : "root" (fakeroot EUID 0) | "user" (real non-root EUID)
#   $2 = sudo_user : literal "UNSET" to leave SUDO_USER unset, else the value
#   $3 = build_home: "true" | "false"
#   $4 = tree_shape: "min" | "full"
run_ctx() {
    local euid_mode="$1" su="$2" home="$3" tree="$4"
    local runner=(bash "${HARNESS}")
    [ "${euid_mode}" = "root" ] && runner=(fakeroot bash "${HARNESS}")
    if [ "${su}" = "UNSET" ]; then
        env -u SUDO_USER BUILD_HOME_ART="${home}" TREE_SHAPE="${tree}" "${runner[@]}" 2>/dev/null
    else
        SUDO_USER="${su}" BUILD_HOME_ART="${home}" TREE_SHAPE="${tree}" "${runner[@]}" 2>/dev/null
    fi
}

field() { printf '%s\n' "$1" | sed -n "s/.*$2=\\([^ ]*\\).*/\\1/p" | head -n1; }

# Assert, for one captured run: chown_calls == 0 AND every node's pre == post.
assert_preserved() {
    local label="$1" out="$2"
    local chowns helper
    chowns="$(field "${out}" chown_calls)"
    helper="$(field "${out}" helper_defined)"

    if [ "${chowns}" = "0" ]; then
        pass "${label}: no chown attempted (chown_calls=0)"
    else
        fail "${label}: ${chowns} chown call(s) attempted; expected 0"
    fi

    # Every "PROBE <node> pre=X post=Y" line must have X == Y.
    local mism=0 total=0 line node pre post
    while IFS= read -r line; do
        case "${line}" in
            "PROBE "*" pre="*" post="*)
                node="$(printf '%s' "${line}" | awk '{print $2}')"
                pre="$(printf '%s' "${line}"  | sed -n 's/.* pre=\([^ ]*\).*/\1/p')"
                post="$(printf '%s' "${line}" | sed -n 's/.* post=\([^ ]*\).*/\1/p')"
                total=$((total + 1))
                if [ "${pre}" != "${post}" ]; then
                    mism=$((mism + 1))
                    echo "        node=${node} pre=${pre} post=${post} (CHANGED)"
                fi
                ;;
        esac
    done <<< "${out}"

    if [ "${total}" -eq 0 ]; then
        fail "${label}: no node PROBE lines captured (harness error?)"
    elif [ "${mism}" -eq 0 ]; then
        pass "${label}: ownership identical to pre-run state across ${total} nodes"
    else
        fail "${label}: ${mism}/${total} nodes changed ownership"
    fi
}

echo "=================================================================="
echo "Property 2 (Preservation) — UNFIXED init_pltf.sh"
echo "Invoking user: ${INVOKER}"
echo "=================================================================="

# ---------------------------------------------------------------------------
# Guard: on unfixed code the helper is absent; sourcing must not run the body.
# (On fixed code the helper is present but must still perform no chown here.)
# ---------------------------------------------------------------------------
OUT="$(run_ctx user UNSET true full)"
HELPER_DEFINED="$(field "${OUT}" helper_defined)"
echo "--- Harness sanity (helper_defined=${HELPER_DEFINED}) ---"
if [ -n "${HELPER_DEFINED}" ]; then
    pass "harness sourced init_pltf.sh and emitted a context probe"
else
    fail "harness produced no context probe (source/exec failure?)"
fi

# ---------------------------------------------------------------------------
# Case 3.1 — Non-root preservation (EUID != 0).
#   A direct non-root run leaves a pre-populated tree with its original
#   (invoking-user) ownership and performs no chown.
#   Generated over SUDO_USER ∈ {unset, invoking user} × tree ∈ {min, full}
#   × home ∈ {true, false} — all non-bug because EUID != 0.
# ---------------------------------------------------------------------------
echo "--- Case 3.1: non-root preservation (EUID != 0) ---"
for su in UNSET "${INVOKER}"; do
    for tree in min full; do
        for home in true false; do
            OUT="$(run_ctx user "${su}" "${home}" "${tree}")"
            euid="$(field "${OUT}" euid)"
            [ "${euid}" != "0" ] \
                && pass "non-root context realized (EUID=${euid}, SUDO_USER=${su})" \
                || fail "expected EUID != 0 but got ${euid} (SUDO_USER=${su})"
            assert_preserved "non-root SUDO_USER=${su} tree=${tree} home=${home}" "${OUT}"
        done
    done
done

# ---------------------------------------------------------------------------
# Case 3.2 — Bare-root preservation (EUID == 0, SUDO_USER unset).
#   Genuine root login: no chown attempted, completes without error, tree
#   ownership unchanged.
# ---------------------------------------------------------------------------
echo "--- Case 3.2: bare-root preservation (EUID 0, SUDO_USER unset) ---"
for tree in min full; do
    for home in true false; do
        OUT="$(run_ctx root UNSET "${home}" "${tree}")"
        euid="$(field "${OUT}" euid)"
        [ "${euid}" = "0" ] \
            && pass "bare-root context realized (EUID=0 via fakeroot)" \
            || fail "expected EUID 0 but got ${euid}"
        assert_preserved "bare-root tree=${tree} home=${home}" "${OUT}"
    done
done

# ---------------------------------------------------------------------------
# Case 3.3 — SUDO_USER=root preservation (EUID == 0, SUDO_USER == root).
#   Treated as a non-bug context: no chown attempted.
# ---------------------------------------------------------------------------
echo "--- Case 3.3: SUDO_USER=root preservation (EUID 0) ---"
for tree in min full; do
    OUT="$(run_ctx root root true "${tree}")"
    euid="$(field "${OUT}" euid)"
    su="$(field "${OUT}" sim_user)"
    [ "${euid}" = "0" ] \
        && pass "SUDO_USER=root context realized (EUID=0, sim_user=${su})" \
        || fail "expected EUID 0 but got ${euid}"
    assert_preserved "SUDO_USER=root tree=${tree}" "${OUT}"
done

# ---------------------------------------------------------------------------
# Case 3.4 — Nonexistent invoking user (EUID == 0, SUDO_USER absent from
#   passwd). A malformed bug context: the helper must warn/skip and attempt no
#   (invalid) chown. On unfixed code the helper is absent → trivially no chown.
# ---------------------------------------------------------------------------
echo "--- Case 3.4: nonexistent SUDO_USER (EUID 0) ---"
GHOST="ghost_$$_nouser"
# Make sure the chosen user genuinely does not exist in the passwd database.
if id -u "${GHOST}" >/dev/null 2>&1; then
    echo "    [SKIP] generated user '${GHOST}' unexpectedly exists; skipping"
else
    for tree in min full; do
        OUT="$(run_ctx root "${GHOST}" true "${tree}")"
        euid="$(field "${OUT}" euid)"
        [ "${euid}" = "0" ] \
            && pass "nonexistent-SUDO_USER context realized (EUID=0, SUDO_USER=${GHOST})" \
            || fail "expected EUID 0 but got ${euid}"
        assert_preserved "nonexistent SUDO_USER=${GHOST} tree=${tree}" "${OUT}"
    done
fi

echo "=================================================================="
echo "RESULT: ${PASS} passed, ${FAIL} failed"
echo "=================================================================="
if [ "${FAIL}" -gt 0 ]; then
    echo "PRESERVATION OUTCOME: FAILED — baseline not preserved."
    exit 1
fi
echo "PRESERVATION OUTCOME: PASSED — non-bug behavior preserved (no chown, ownership unchanged)."
exit 0
