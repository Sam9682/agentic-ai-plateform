#!/bin/bash
# ---------------------------------------------------------------------------
# test_init_ownership_integration.sh
#   Spec:  init-pltf-root-ownership-fix  (Task 4 — INTEGRATION coverage)
#
#   End-to-end integration tests for the ownership-restore flow:
#
#   T1 — Full ownership-restore flow (Requirements 2.1, 2.2, 2.3): a temp tree
#        mirroring REPO_DIR (shared, .venv, logs, conf/deploy.ini) plus ~/.aws
#        and ~/deployments/admin, under a simulated BUG context, flips to the
#        invoking user in ONE pass. Driven through the existing
#        ownership_harness.sh (reused, not duplicated).
#
#   T2 — Context-switching (Requirements 2.1, 3.1): the SAME sourced helper is
#        invoked first under a NON-BUG context (tree A, natural ownership) and
#        then under a BUG context (tree B, forced root:root). Each tree is
#        handled independently — A is a no-op (untouched), B is fully restored —
#        and the bug-context call does not touch tree A. Driven through
#        integration_harness.sh.
#
#   T3 — Sourcing side-effect-free (Requirements 3.3, 3.4, 3.5, 3.6): sourcing
#        init_pltf.sh DEFINES the helper without executing the installer body
#        and without performing any chown. Driven through integration_harness.sh.
#
#   fakeroot virtualizes EUID/chown/stat.
# ---------------------------------------------------------------------------
set -u

HARNESS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OWNERSHIP_HARNESS="${HARNESS_DIR}/ownership_harness.sh"
INTEGRATION_HARNESS="${HARNESS_DIR}/integration_harness.sh"
INVOKER="$(id -un)"
EXPECT_OWNER="${INVOKER}:$(id -gn)"

PASS=0
FAIL=0
pass() { echo "  [PASS] $1"; PASS=$((PASS + 1)); }
fail() { echo "  [FAIL] $1"; FAIL=$((FAIL + 1)); }

field() { printf '%s\n' "$1" | sed -n "s/.*$2=\\([^ ]*\\).*/\\1/p" | head -n1; }

echo "=================================================================="
echo "Task 4 — INTEGRATION coverage"
echo "Invoking user: ${EXPECT_OWNER}"
echo "=================================================================="

# ---------------------------------------------------------------------------
# T1 — Full ownership-restore flow (req 2.1, 2.2, 2.3)
#   Reuse ownership_harness.sh: it builds the full mirror tree + home
#   artifacts, forces root:root (the sudo bug), invokes the helper, and reports
#   every node's resulting owner. Assert the WHOLE tree flipped to the invoking
#   user in one pass.
# ---------------------------------------------------------------------------
echo "--- T1: full restore flow — whole tree flips in one pass (req 2.1, 2.2, 2.3) ---"
OUT="$(SUDO_USER="${INVOKER}" BUILD_HOME_ART=true fakeroot bash "${OWNERSHIP_HARNESS}" 2>/dev/null)"
euid="$(field "${OUT}" euid)"
helper="$(field "${OUT}" helper_defined)"
if [ "${euid}" != "0" ] || [ "${helper}" != "1" ]; then
    fail "T1 context not realized (euid=${euid}, helper_defined=${helper})"
else
    pass "T1 bug context realized (EUID 0, helper present)"
    mism=0
    for node in clone shared venv venv_bin logs deploy_ini readme aws aws_creds deployments admin; do
        o="$(printf '%s\n' "${OUT}" | awk -v l="${node}" '$1=="PROBE" && $2==l {print}' | sed -n 's/.*owner=\([^ ]*\).*/\1/p' | head -n1)"
        if [ "${o}" != "${EXPECT_OWNER}" ]; then
            mism=$((mism + 1))
            echo "        ${node} owner=${o} (expected ${EXPECT_OWNER})"
        fi
    done
    if [ "${mism}" -eq 0 ]; then
        pass "T1 every mirror + home node owned by ${EXPECT_OWNER}"
    else
        fail "T1 ${mism} node(s) not owned by ${EXPECT_OWNER}"
    fi
fi

# ---------------------------------------------------------------------------
# T2 + T3 — context-switching and sourcing side-effect-free.
#   The integration harness runs under fakeroot so the bug-context branch can
#   realize EUID 0. It sources once, exercises both contexts, and emits PROBEs.
# ---------------------------------------------------------------------------
IOUT="$(REAL_INVOKER="${INVOKER}" REAL_INVOKER_GROUP="$(id -gn)" fakeroot bash "${INTEGRATION_HARNESS}" 2>/dev/null)"

# ---- T3: sourcing side-effect-free (req 3.3, 3.4, 3.5, 3.6) ----------------
echo "--- T3: sourcing defines helper, no body, no chown (req 3.3-3.6) ---"
s_helper="$(printf '%s\n' "${IOUT}" | sed -n 's/^PROBE source .*helper_defined=\([0-9]*\).*/\1/p' | head -n1)"
s_chown="$(printf '%s\n' "${IOUT}" | sed -n 's/^PROBE source .*chown_after_source=\([0-9]*\).*/\1/p' | head -n1)"
s_body="$(printf '%s\n' "${IOUT}" | sed -n 's/^PROBE source .*body_ran=\([0-9]*\).*/\1/p' | head -n1)"
s_ret="$(printf '%s\n' "${IOUT}" | sed -n 's/^PROBE source .*returned=\([0-9]*\).*/\1/p' | head -n1)"
echo "    helper_defined=${s_helper} chown_after_source=${s_chown} body_ran=${s_body} returned=${s_ret}"
[ "${s_helper}" = "1" ] && pass "T3 sourcing defines restore_invoking_user_ownership" || fail "T3 helper not defined after sourcing"
[ "${s_chown}" = "0" ]  && pass "T3 sourcing performed no chown (chown_after_source=0)" || fail "T3 sourcing performed ${s_chown} chown(s)"
[ "${s_body}" = "0" ]   && pass "T3 installer body did not run on source" || fail "T3 installer body appears to have run on source"
[ "${s_ret}" = "1" ]    && pass "T3 source returned via the source guard" || fail "T3 source did not return cleanly"

# ---- T2: context-switching (req 2.1, 3.1) ----------------------------------
echo "--- T2: context-switching — non-bug then bug, handled independently (req 2.1, 3.1) ---"
switchA_delta="$(printf '%s\n' "${IOUT}" | sed -n 's/^PROBE switchA chown_delta=\([0-9-]*\).*/\1/p' | head -n1)"
switchB_delta="$(printf '%s\n' "${IOUT}" | sed -n 's/^PROBE switchB chown_delta=\([0-9-]*\).*/\1/p' | head -n1)"
exp_owner_sw="$(field "${IOUT}" expect_owner)"
echo "    non-bug (tree A) chown_delta=${switchA_delta}; bug (tree B) chown_delta=${switchB_delta}; expect=${exp_owner_sw}"

# (a) Non-bug call made zero chowns.
[ "${switchA_delta}" = "0" ] && pass "T2 non-bug context: no chown (tree A untouched)" || fail "T2 non-bug context performed ${switchA_delta} chown(s)"

# (b) Bug call made at least one chown.
if [ -n "${switchB_delta}" ] && [ "${switchB_delta}" -ge 1 ]; then
    pass "T2 bug context: chown performed (${switchB_delta} call(s))"
else
    fail "T2 bug context performed no chown (delta=${switchB_delta})"
fi

# (c) Tree A nodes: pre == post (untouched across BOTH calls). Compared by
# exact path using a single awk that joins A_pre and A_after_B on path.
A_CMP="$(printf '%s\n' "${IOUT}" | awk '
    $1=="PROBE" && ($2=="A_pre" || $2=="A_after_B") {
        owner=""; path="";
        for (i=1;i<=NF;i++){
            if ($i ~ /^owner=/){ o=$i; sub(/^owner=/,"",o); owner=o }
            if ($i ~ /^path=/){ p=$i; sub(/^path=/,"",p); path=p }
        }
        if ($2=="A_pre")      pre[path]=owner;
        if ($2=="A_after_B")  post[path]=owner;
    }
    END {
        total=0; mism=0;
        for (k in pre){ total++; if (pre[k] != post[k]){ mism++; print "CHANGED " k " " pre[k] " -> " post[k] } }
        print "SUMMARY total=" total " mism=" mism;
    }')"
printf '%s\n' "${A_CMP}" | grep '^CHANGED ' | sed 's/^/        /'
total_a="$(printf '%s\n' "${A_CMP}" | sed -n 's/^SUMMARY total=\([0-9]*\).*/\1/p')"
mism_a="$(printf '%s\n' "${A_CMP}" | sed -n 's/^SUMMARY .*mism=\([0-9]*\).*/\1/p')"
if [ "${total_a:-0}" -gt 0 ] && [ "${mism_a:-1}" -eq 0 ]; then
    pass "T2 tree A unchanged across both contexts (${total_a} nodes)"
else
    fail "T2 tree A changed on ${mism_a}/${total_a} nodes"
fi

# (d) Tree B nodes: all owned by invoking user after the bug-context call.
B_CMP="$(printf '%s\n' "${IOUT}" | awk -v want="${exp_owner_sw}" '
    $1=="PROBE" && $2=="B_post" {
        owner="";
        for (i=1;i<=NF;i++){ if ($i ~ /^owner=/){ o=$i; sub(/^owner=/,"",o); owner=o } }
        total++;
        if (owner != want){ mism++; print "NOTREST " $0 }
    }
    END { print "SUMMARY total=" total+0 " mism=" mism+0 }')"
printf '%s\n' "${B_CMP}" | grep '^NOTREST ' | sed 's/^NOTREST /        B node not restored: /'
total_b="$(printf '%s\n' "${B_CMP}" | sed -n 's/^SUMMARY total=\([0-9]*\).*/\1/p')"
mism_b="$(printf '%s\n' "${B_CMP}" | sed -n 's/^SUMMARY .*mism=\([0-9]*\).*/\1/p')"
if [ "${total_b:-0}" -gt 0 ] && [ "${mism_b:-1}" -eq 0 ]; then
    pass "T2 tree B fully restored to ${exp_owner_sw} (${total_b} nodes)"
else
    fail "T2 tree B restore incomplete: ${mism_b}/${total_b} nodes"
fi

echo "=================================================================="
echo "RESULT: ${PASS} passed, ${FAIL} failed"
echo "=================================================================="
if [ "${FAIL}" -gt 0 ]; then
    echo "INTEGRATION OUTCOME: FAILED"
    exit 1
fi
echo "INTEGRATION OUTCOME: PASSED"
exit 0
