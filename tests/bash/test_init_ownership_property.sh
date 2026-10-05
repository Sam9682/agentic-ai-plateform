#!/bin/bash
# ---------------------------------------------------------------------------
# test_init_ownership_property.sh
#   Spec:  init-pltf-root-ownership-fix  (Task 4 — PROPERTY-BASED coverage)
#
#   Property-based tests driven through property_harness.sh, which builds a
#   RANDOMLY SHAPED clone tree (seed-driven) under REPO_DIR plus the home
#   artifacts, applies a run context, invokes the helper, and reports the
#   pre/post owner:group of EVERY node recursively.
#
#   P1 — Fix (Property 1): for random BUG contexts (EUID 0 via fakeroot, a
#        valid non-root SUDO_USER, the whole tree forced root:root), assert
#        EVERY node ends owned by the invoking user:group, with the group
#        resolved via id -gn.                     (Requirements 2.1, 2.2, 2.4)
#   P2 — Preservation (Property 2): for random NON-BUG contexts (EUID != 0, or
#        SUDO_USER unset/root under EUID 0), assert ownership is IDENTICAL to
#        the pre-run state (post == pre for every node) AND chown_calls == 0.
#                                                 (Requirements 3.1, 3.2)
#
#   The "property" is checked over many generated inputs: a sweep of random
#   seeds (tree shapes) crossed with the context dimensions. fakeroot
#   virtualizes EUID/chown/stat, so no real privilege is needed.
# ---------------------------------------------------------------------------
set -u

HARNESS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HARNESS="${HARNESS_DIR}/property_harness.sh"
INVOKER="$(id -un)"
INVOKER_OWNER="$(id -un):$(id -gn)"

# Number of random tree shapes per context (kept modest so the suite is quick
# but still spans many layouts).
SEEDS=(1 7 42 101 999)

PASS=0
FAIL=0
pass() { echo "  [PASS] $1"; PASS=$((PASS + 1)); }
fail() { echo "  [FAIL] $1"; FAIL=$((FAIL + 1)); }

field() { printf '%s\n' "$1" | sed -n "s/.*$2=\\([^ ]*\\).*/\\1/p" | head -n1; }

# Run harness. $1=euid_mode(root|user) $2=SUDO_USER(or UNSET) $3=FORCE_ROOT ...
run_ctx() {
    local euid_mode="$1" su="$2"; shift 2
    local runner=(bash "${HARNESS}")
    [ "${euid_mode}" = "root" ] && runner=(fakeroot bash "${HARNESS}")
    if [ "${su}" = "UNSET" ]; then
        env -u SUDO_USER "$@" "${runner[@]}" 2>/dev/null
    else
        env SUDO_USER="${su}" "$@" "${runner[@]}" 2>/dev/null
    fi
}

# For a captured run, count nodes whose post != EXPECT (bug mode) and return
# the mismatch count via echo.
count_post_ne() {
    # $1 = output, $2 = expected owner
    printf '%s\n' "$1" | awk -v want="$2" '
        $1=="PROBE" && $2=="node" {
            post=""; for (i=1;i<=NF;i++){ if ($i ~ /^post=/){ sub(/^post=/,"",$i); post=$i } }
            if (post != want) c++
        }
        END { print c+0 }'
}
# Count nodes whose post != pre (preservation mode).
count_changed() {
    printf '%s\n' "$1" | awk '
        $1=="PROBE" && $2=="node" {
            pre=""; post="";
            for (i=1;i<=NF;i++){
                if ($i ~ /^pre=/){ sub(/^pre=/,"",$i); pre=$i }
                if ($i ~ /^post=/){ sub(/^post=/,"",$i); post=$i }
            }
            if (pre != post) c++
        }
        END { print c+0 }'
}

echo "=================================================================="
echo "Task 4 — PROPERTY-BASED coverage"
echo "Invoking user: ${INVOKER_OWNER}   seeds: ${SEEDS[*]}"
echo "=================================================================="

# ---------------------------------------------------------------------------
# P1 — random BUG contexts: every node ends owned by invoking user:group.
#   Two invoking users are swept: the current user, and (when available)
#   `nobody` whose primary group `nogroup` differs from the username — so the
#   property also pins the id -gn group resolution (req 2.4).
# ---------------------------------------------------------------------------
echo "--- P1: random bug contexts -> all nodes owned by invoking user:group (req 2.1, 2.2, 2.4) ---"

declare -a BUG_USERS=("${INVOKER}")
NOBODY_GROUP="$(id -gn nobody 2>/dev/null || true)"
if [ -n "${NOBODY_GROUP}" ] && [ "${NOBODY_GROUP}" != "nobody" ]; then
    BUG_USERS+=("nobody")
fi

for u in "${BUG_USERS[@]}"; do
    expect="${u}:$(id -gn "${u}" 2>/dev/null)"
    for s in "${SEEDS[@]}"; do
        OUT="$(run_ctx root "${u}" FORCE_ROOT=true SEED="${s}" USE_SIM_HOME=true)"
        euid="$(field "${OUT}" euid)"
        nodes="$(field "${OUT}" nodes)"
        helper="$(field "${OUT}" helper_defined)"
        if [ "${euid}" != "0" ] || [ "${helper}" != "1" ]; then
            fail "P1 user=${u} seed=${s}: context not realized (euid=${euid}, helper=${helper})"
            continue
        fi
        mism="$(count_post_ne "${OUT}" "${expect}")"
        if [ "${mism}" = "0" ]; then
            pass "P1 user=${u} seed=${s}: all ${nodes} nodes owned by ${expect}"
        else
            fail "P1 user=${u} seed=${s}: ${mism}/${nodes} nodes NOT owned by ${expect}"
            printf '%s\n' "${OUT}" | awk -v want="${expect}" '$1=="PROBE" && $2=="node"{for(i=1;i<=NF;i++){if($i ~ /^post=/){p=$i;sub(/^post=/,"",p)}}; if(p!=want) print "        "$0}' | head -5
        fi
    done
done

# ---------------------------------------------------------------------------
# P2 — random NON-BUG contexts: ownership identical to pre-run, no chown.
#   Context dimensions: EUID (non-root / fakeroot-root) x SUDO_USER
#   (unset / root) — all non-bug — crossed with random tree shapes.
# ---------------------------------------------------------------------------
echo "--- P2: random non-bug contexts -> ownership unchanged, 0 chown (req 3.1, 3.2) ---"

# (euid_mode, sudo_user) pairs that are all NON-bug by construction.
NONBUG_CTX=("user UNSET" "user ${INVOKER}" "root UNSET" "root root")

for ctx in "${NONBUG_CTX[@]}"; do
    set -- ${ctx}
    emode="$1"; su="$2"
    for s in "${SEEDS[@]}"; do
        OUT="$(run_ctx "${emode}" "${su}" FORCE_ROOT=false SEED="${s}" USE_SIM_HOME=true)"
        euid="$(field "${OUT}" euid)"
        nodes="$(field "${OUT}" nodes)"
        chowns="$(field "${OUT}" chown_calls)"
        changed="$(count_changed "${OUT}")"
        label="P2 ctx=[${emode},SUDO_USER=${su}] seed=${s}"
        if [ "${chowns}" = "0" ] && [ "${changed}" = "0" ]; then
            pass "${label}: ${nodes} nodes unchanged, 0 chown (euid=${euid})"
        else
            fail "${label}: changed=${changed}/${nodes}, chown_calls=${chowns}"
        fi
    done
done

echo "=================================================================="
echo "RESULT: ${PASS} passed, ${FAIL} failed"
echo "=================================================================="
if [ "${FAIL}" -gt 0 ]; then
    echo "PROPERTY OUTCOME: FAILED"
    exit 1
fi
echo "PROPERTY OUTCOME: PASSED"
exit 0
