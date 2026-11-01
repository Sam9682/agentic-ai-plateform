#!/bin/bash
# ---------------------------------------------------------------------------
# test_bootstrap_file_absence.sh
#   Spec:  phase1-foundation-consolidation  (Task 8.4 — file-absence smoke test)
#
#   Standalone additive smoke test for the single-bootstrap-script
#   consolidation. After merging `init_pltf_fixed.sh` into `init_pltf.sh`
#   (Task 8.1) and deleting the forked variant (Task 8.2), exactly one
#   bootstrap script must remain at the repository root.
#
#   Assertions:
#     A1  `init_pltf_fixed.sh` is ABSENT at the repo root (the redundant
#         forked variant was removed).
#     A2  `init_pltf.sh`       is PRESENT at the repo root (the single
#         canonical bootstrap script is retained).
#
#   Validates: Requirements 2.4
#     "THE Platform SHALL retain exactly one bootstrap script file after
#      reconciliation, removing the redundant variant."
#
#   This is an independent, additive check: it is NOT part of the 57-count
#   init_ownership baseline drivers and needs no fakeroot or harness. Run it
#   plainly:  bash tests/bash/test_bootstrap_file_absence.sh
# ---------------------------------------------------------------------------
set -u

# Resolve the repo root robustly: prefer git, fall back to two levels up from
# this script's own location (tests/bash/<this> -> repo root).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if ROOT="$(git -C "${SCRIPT_DIR}" rev-parse --show-toplevel 2>/dev/null)" && [ -n "${ROOT}" ]; then
    :
else
    ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
fi

PASS=0
FAIL=0
pass() { echo "  [PASS] $1"; PASS=$((PASS + 1)); }
fail() { echo "  [FAIL] $1"; FAIL=$((FAIL + 1)); }

FIXED="${ROOT}/init_pltf_fixed.sh"
CANONICAL="${ROOT}/init_pltf.sh"

echo "=================================================================="
echo "Task 8.4 — bootstrap file-absence smoke test (req 2.4)"
echo "Repo root: ${ROOT}"
echo "=================================================================="

# --- A1: the forked variant must be ABSENT -------------------------------
if [ ! -e "${FIXED}" ]; then
    pass "A1 forked variant absent: init_pltf_fixed.sh does not exist"
else
    fail "A1 forked variant still present: ${FIXED}"
fi

# --- A2: the canonical script must be PRESENT ----------------------------
if [ -f "${CANONICAL}" ]; then
    pass "A2 canonical bootstrap present: init_pltf.sh exists"
else
    fail "A2 canonical bootstrap missing: ${CANONICAL}"
fi

echo "=================================================================="
echo "RESULT: ${PASS} passed, ${FAIL} failed"
echo "=================================================================="
if [ "${FAIL}" -gt 0 ]; then
    echo "SMOKE OUTCOME: FAILED"
    exit 1
fi
echo "SMOKE OUTCOME: PASSED"
exit 0
