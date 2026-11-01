#!/bin/bash
# ---------------------------------------------------------------------------
# test_init_superset_markers.sh
#   Spec:  phase1-foundation-consolidation  (Task 8.3)
#   Superset-marker smoke test for the single-bootstrap consolidation.
#
#   Requirement 2 reconciles init_pltf.sh and init_pltf_fixed.sh into one
#   canonical script (init_pltf.sh), folding in the _fixed-only Docker/Kata
#   install blocks (2.2) and the submodule-URL resolution blocks (2.3), then
#   deleting the forked variant (2.4). This test asserts the merged script is a
#   SUPERSET of both originals: every install/action marker and every function
#   name present in EITHER original must still be present in the merged
#   init_pltf.sh.
#
#   Validates: Requirements 2.1, 2.2, 2.3
#
# WHY A CHECKED-IN MARKER LIST (not a live extraction)
#   init_pltf_fixed.sh was DELETED in Task 8.2, so it cannot be read at test
#   runtime. The superset check therefore uses a FIXED, CHECKED-IN list of the
#   known markers that existed in the two originals, captured during Task 8.1's
#   diff/merge (the folded capabilities). Each marker below was additionally
#   verified to be present in the current merged init_pltf.sh at authoring time,
#   so this test passes on the real merged file and would fail (correctly) if a
#   future edit dropped any folded capability.
#
# RUNNING
#   bash tests/bash/test_init_superset_markers.sh
#   (plain bash; no fakeroot, sudo, or network required.)
# ---------------------------------------------------------------------------
set -u

# --- Resolve repo root robustly ------------------------------------------
# The test lives at <repo>/tests/bash/; the merged script at <repo>/init_pltf.sh.
TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${TEST_DIR}/../.." && pwd)"
INIT_SCRIPT="${REPO_ROOT}/init_pltf.sh"

PASS=0
FAIL=0
pass() { echo "  [PASS] $1"; PASS=$((PASS + 1)); }
fail() { echo "  [FAIL] $1"; FAIL=$((FAIL + 1)); }

echo "=================================================================="
echo "Task 8.3 — superset-marker smoke test for merged init_pltf.sh"
echo "Repo root: ${REPO_ROOT}"
echo "Merged script: ${INIT_SCRIPT}"
echo "=================================================================="

# --- Precondition: the merged script exists and is readable ---------------
if [ ! -f "${INIT_SCRIPT}" ]; then
    echo "  [FATAL] merged script not found: ${INIT_SCRIPT}"
    echo "RESULT: 0 passed, 1 failed"
    echo "OUTCOME: FAILED — merged init_pltf.sh missing."
    exit 1
fi

# Read the merged script once into a variable for fixed-string searches.
SCRIPT_CONTENT="$(cat "${INIT_SCRIPT}")"

# --- Checked-in marker list (from Task 8.1's diff/merge report) -----------
# Install/action markers folded in from BOTH originals. Matched as literal
# fixed strings (grep -F) so regex metacharacters in URLs/paths are literal.
MARKERS=(
    # --- Docker install block (Req 2.2) ---
    "get.docker.com"
    "chmod +x get-docker.sh"
    "usermod -aG docker"
    "docker/compose/releases/latest/download/docker-compose"
    "Failed to download Docker installation script"
    # --- Kata Containers install block (Req 2.2) ---
    "kata-static-3.32.0"
    "containerd-shim-kata-v2"
    "daemon.json"
    "systemctl reload docker"
    "Failed to download Kata Containers"
    "Failed to decompress Kata Containers archive"
    "Failed to extract Kata Containers"
    # --- Submodule / URL resolution block (Req 2.3) ---
    "git submodule add"
    "git submodule update --init --recursive"
    "SUBMODULE_URL"
    "DEFAULT_SUBMODULE_URL"
    "_resolve_default"
    "resolve_platform_defaults"
    "agentic-ai-plateform--skills"
    # --- Other shared install/action markers (Req 2.1) ---
    "docker network create swautomorph-shared"
    "traefik/dynamic"
)

# --- Function-name set present in BOTH originals --------------------------
FUNCTIONS=(
    print_step
    print_success
    print_error
    print_warning
    is_valid_slug
    prompt_platform_identity
    set_ini_value
    get_ini_value
    _resolve_default
    resolve_platform_defaults
    restore_invoking_user_ownership
)

# --- 1. Assert every checked-in marker is present (fixed-string) ----------
echo "--- Install/action markers (every marker from either original) ---"
for m in "${MARKERS[@]}"; do
    if printf '%s' "${SCRIPT_CONTENT}" | grep -qF -- "${m}"; then
        pass "marker present: ${m}"
    else
        fail "marker MISSING from merged init_pltf.sh: ${m}"
    fi
done

# --- 2. Extract the function-name set actually defined in init_pltf.sh ----
# Accept both 'name()' and 'function name' definition styles, anchored at the
# start of the line (ignoring leading whitespace), so comments mentioning a
# name are not mistaken for a definition.
extract_defined_functions() {
    grep -Eo '^[[:space:]]*(function[[:space:]]+[A-Za-z_][A-Za-z0-9_]*|[A-Za-z_][A-Za-z0-9_]*[[:space:]]*\(\))' "${INIT_SCRIPT}" \
        | sed -E 's/^[[:space:]]*//; s/^function[[:space:]]+//; s/[[:space:]]*\(\).*//' \
        | sort -u
}

DEFINED_FUNCS="$(extract_defined_functions)"
echo "--- Defined functions in merged init_pltf.sh ---"
echo "${DEFINED_FUNCS}" | sed 's/^/        /'

# --- 3. Assert the known function set is a SUBSET of the defined set ------
echo "--- Function-name superset check (known set ⊆ defined set) ---"
is_defined() {
    printf '%s\n' "${DEFINED_FUNCS}" | grep -qx -- "$1"
}
for fn in "${FUNCTIONS[@]}"; do
    if is_defined "${fn}"; then
        pass "function defined: ${fn}()"
    else
        fail "function MISSING from merged init_pltf.sh: ${fn}()"
    fi
done

# --- Result ---------------------------------------------------------------
echo "=================================================================="
echo "RESULT: ${PASS} passed, ${FAIL} failed"
echo "=================================================================="
if [ "${FAIL}" -gt 0 ]; then
    echo "OUTCOME: FAILED — merged init_pltf.sh is missing a folded capability."
    echo "  (A missing marker may indicate the 8.1 merge dropped something;"
    echo "   investigate rather than deleting the marker to go green.)"
    exit 1
fi
echo "OUTCOME: PASSED — merged init_pltf.sh is a superset of both originals."
exit 0
