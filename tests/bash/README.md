# Bash tests — `stop-command-not-stopping-fix`

Tests for the bugfix spec `stop-command-not-stopping-fix`. They exercise the
real `stop_services` / `backup_database` functions from `deployControlPlan.sh`.

## Files

- `stop_services_harness.sh` — extracts the real `stop_services` and
  `backup_database` function bodies from `deployControlPlan.sh` (by name, via
  brace counting) and runs `stop_services` under `set -e` in a sandbox. All
  external commands (`pg_isready`, `pg_dump`, `aws`, ...) and the
  service-stopping functions are stubbed. It records which stop commands ran
  and prints a `PROBE` line.

  Parameters (env vars):
  - `MODE` = `locally` | `docker` | `default` → sets `LOCAL_MODE`
  - `FAIL_MODE` = `pg_isready` | `pg_dump` | `none` → how `backup_database` fails
  - `LOGS_FAIL` = `true` | `false` (default `false`) → when `true`, exercises the
    REAL `backup_logs` against a real `./logs` dir with an `aws` stub that fails
    specifically on the logs `s3 sync ./logs …` path (facet 2 of the bug — the
    bare `aws s3 sync ./logs` inside `backup_logs`, e.g. `SignatureDoesNotMatch`
    from invalid/expired S3 credentials), while the DB backup sync succeeds.

- `test_stop_backup_failure.sh` — **Property 1 (Bug Condition), facet 1
  (database backup)** test. Scoped property-based enumeration over
  `MODE × FAIL_MODE` for the bug-condition input space (`backup_database` exit
  code ≠ 0). Asserts the Expected Behavior: the script does not abort early, all
  applicable stop commands run, and a warning is logged.

- `test_stop_logs_backup_failure.sh` — **Property 1 (Bug Condition), facet 2
  (logs backup)** test. Scoped property-based enumeration over `MODE` with
  `LOGS_FAIL=true` (DB backup succeeds, the bare `aws s3 sync ./logs` fails).
  Asserts the same Expected Behavior for the logs-backup facet: the script does
  not abort early, all applicable stop commands run, and a warning is logged.
  On the pre-fix `backup_logs` (bare sync) it reports `ABORTED_EARLY`; after the
  fix (`if/else`-guarded sync + best-effort call site) it PASSES.

- `test_stop_preservation.sh` — **Property 2 (Preservation)** test. Part A
  asserts the successful-backup stop sequence (now `backup,logs,<stop cmds>`),
  Part B the standalone `backup_db` exit code (3.4), and Part C the successful
  logs-backup path (3.5): `backup_logs` prints "Logs backup completed" on a
  succeeding sync and skips cleanly with no `logs` dir.

## Running

```bash
bash tests/bash/test_stop_backup_failure.sh
bash tests/bash/test_stop_logs_backup_failure.sh
bash tests/bash/test_stop_preservation.sh
```

## Bug condition exploration — result (Task 1)

Run on the **UNFIXED** `deployControlPlan.sh`: the test **FAILS**, which is the
expected/success outcome for an exploration test — it proves the bug exists.

### Counterexamples (6/6 bug-condition cases fail)

For every `MODE ∈ {locally, docker, default}` and every backup-failure path
`FAIL_MODE ∈ {pg_isready, pg_dump}`:

```
PROBE result=ABORTED_EARLY flask=0 nginx=0 docker=0 gitea=0 warning=0 (child_exit=1)
```

- **Root cause confirmed:** inside `stop_services()`, `backup_database` is
  called as a bare statement. With `set -e` active (line 6), a non-zero return
  from `backup_database` (failed `pg_isready` connection test, or failed
  complete `pg_dump`) aborts the whole script **before** any
  `stop_flask_service` / `stop_nginx_service` / `stop_docker_services` /
  `confirm_gitea_stop` runs. No stop command is recorded and no warning is
  logged.

### Control case (sanity, not part of the bug condition)

With `FAIL_MODE=none` (backup succeeds) the harness reports `COMPLETED` and the
correct mode-specific stop commands run (`locally` → flask/nginx/gitea,
`docker` → docker, `default` → all four). This proves the harness can produce
passing probes and is genuinely discriminating.

The fix (Task 3) makes the pre-stop backup best-effort
(`backup_database || echo -e "  ⚠️ ..."`); after that this same test is expected
to PASS.

## Logs-backup facet exploration — result (facet 2)

`test_stop_logs_backup_failure.sh` drives the second facet. Run against the
**pre-fix** `backup_logs` (bare `aws s3 sync ./logs`) with the DB backup
best-effort: the test **FAILS**, confirming the bug.

### Counterexamples (3/3 mode cases)

For every `MODE ∈ {locally, docker, default}` with `LOGS_FAIL=true`:

```
PROBE result=ABORTED_EARLY flask=0 nginx=0 docker=0 gitea=0 warning=0 backup=1 logs=1 seq=backup,logs (child_exit=1)
```

- **Root cause confirmed (facet 2):** inside `backup_logs()`, `aws s3 sync ./logs …`
  was a bare command. With `set -e` active, an S3 failure (`SignatureDoesNotMatch`)
  makes `backup_logs` return non-zero, and the bare `backup_logs` call inside
  `stop_services` then aborts the whole script — *after* the (now best-effort) DB
  backup (`seq=backup,logs`) but *before* any stop command runs.

### After the fix

`backup_logs` guards the sync with `if/else` (warning + return 0) and the
`stop_services` call site is `backup_logs || echo -e "  ⚠️ …"`. The test then
**PASSES**: `result=COMPLETED`, all applicable stop commands run, `warning=1`.

## Full suite

All three tests PASS on the fixed `deployControlPlan.sh`:

- `test_stop_backup_failure.sh` — 6/6 (facet 1 fix checking)
- `test_stop_logs_backup_failure.sh` — 3/3 (facet 2 fix checking)
- `test_stop_preservation.sh` — 11/11 (Property 2 preservation)


---

# Bash tests — `init-pltf-path-fix`

Bug condition exploration test for the bugfix spec `init-pltf-path-fix`.

## Files

- `test_init_path_resolution.sh` — **Property 1 (Bug Condition)** exploration
  test. Scoped property-based enumeration over `(launchDir, cloneDir)` pairs
  (with `launchDir != cloneDir`) modelling `isBugCondition(input)` from
  `design.md`: a repository-relative step (`venv_pip_install`, `final_chmod`)
  whose target resolves relative to the current working directory, where
  `resolve(cwd, target)` does NOT exist yet `resolve(cloneDir, target)` does.
  It builds a temporary fake clone containing `requirements.txt` and
  `setup_modsecurity_config.sh`, sets CWD to an unrelated launch directory
  (the state left by the stray `cd - > /dev/null`), and asserts the EXPECTED
  behavior (targets resolve against the clone, failures are not masked, the
  stray `cd -` is gone, and the steps are anchored on `${REPO_DIR}`).

  Test cases:
  1. pip requirements resolution — `./requirements.txt` must resolve against
     the clone (fails on unfixed logic).
  2. chmod target resolution — `setup_modsecurity_config.sh` must resolve
     against the clone and `chmod +x` succeed (fails on unfixed logic).
  3. masked success — a genuine pip/chmod failure must not be reported as
     `[OK] ...` (requirement 1.3; fails on unfixed logic).
  4. edge case — when CWD already equals the clone the relative lookups
     succeed (confirms the bug is CWD-dependent, not a missing file; passes
     both before and after the fix).
  Plus static root-cause assertions: the stray `cd - > /dev/null` is removed
  from the Kata block, and the venv/final steps reference
  `"${REPO_DIR}/requirements.txt"` / `"${REPO_DIR}/setup_modsecurity_config.sh"`.

- `test_init_preservation.sh` — **Property 2 (Preservation)** test.
  **Validates: Requirements 3.1, 3.2, 3.3, 3.4**. Captures the baseline,
  non-path-resolution behavior of the UNFIXED `init_pltf.sh` that the fix must
  leave untouched. Following observation-first methodology, the unfixed outputs
  were observed first, then encoded as property assertions:

  - **propA** — `CLONE_DEST = "${INSTALL_DIR%/}/${PLTF_FOLDER}"` preserved
    across 120 generated `(INSTALL_DIR, PLTF_FOLDER)` tuples (nested segments
    and 0–2 trailing slashes). Encodes the observed invariant that exactly ONE
    trailing slash is stripped from `INSTALL_DIR`.
  - **propB** — destination computation is stable for explicit trailing-slash
    and nested-segment cases (`/opt/` → `/opt/myplat`, `/opt//` → `/opt//myplat`,
    `/a/b/c` → `/a/b/c/nested-plat`, etc.).
  - **propC** — `set_ini_value` / `get_ini_value` round-trip for `PLTF_NAME`
    and `PLTF_FOLDER` across 120 generated values: value read back identically,
    no key duplication, and `DOMAIN` / `VERSION` / `LINUX_USER_INSTALLATION`
    preserved (uses the REAL sourced functions).
  - **propD** — directory-creation outcomes preserved across 40 generated
    `(clone, home)` layouts: `logs` (under the clone), `~/deployments`, and
    `~/deployments/admin` are all created.
  - static assertions — the Kata download/unzstd/extract/move/`daemon.json`/
    reload/cleanup steps, the clone + submodule + `deploy.ini` writes, and the
    final directory creation + completion banner text are all present.

## Running

```bash
bash tests/bash/test_init_path_resolution.sh
bash tests/bash/test_init_preservation.sh
```

## Bug condition exploration — result (Task 1)

Run on the **UNFIXED** `init_pltf.sh`: the test **FAILS** (6/7 assertions),
which is the expected/success outcome for an exploration test — it proves the
bug exists.

### Counterexamples

- `pip`: resolves `./requirements.txt` under the launch dir
  (`Could not open requirements file: './requirements.txt'`) while
  `${clone}/requirements.txt` exists.
- `chmod`: `chmod: cannot access './setup_modsecurity_config.sh'` while
  `${clone}/setup_modsecurity_config.sh` exists.
- Masked success: despite both failures, the unfixed sequence still reaches
  `[OK] Python environment ready` and `[OK] Installation completed
  successfully!` (requirement 1.3).
- Static: the stray `cd - > /dev/null` is still present in the Kata block, and
  the pip/chmod steps are CWD-relative rather than anchored on `${REPO_DIR}`.

### Control / edge case (¬C)

Test case 4 (CWD already equals the clone) **PASSES** — the relative lookups
resolve correctly, confirming the bug is working-directory-dependent rather
than a genuinely missing file. This proves the harness is discriminating.

After the fix (Task 3) removes the stray `cd -` and anchors the
repository-relative steps on `${REPO_DIR}`, this same test is expected to
**PASS**.

## Preservation — result (Task 2)

Run on the **UNFIXED** `init_pltf.sh`: `test_init_preservation.sh` **PASSES**
(21/21 assertions), confirming the baseline that the fix must preserve.

### Observed baseline (unfixed code)

- `CLONE_DEST = "${INSTALL_DIR%/}/${PLTF_FOLDER}"` — strips exactly ONE
  trailing slash from `INSTALL_DIR`; nested segments preserved:
  `/opt` + `myplat` → `/opt/myplat`, `/opt/` + `myplat` → `/opt/myplat`,
  `/opt//` + `myplat` → `/opt//myplat`, `/a/b/c` + `nested-plat` →
  `/a/b/c/nested-plat`.
- `set_ini_value` / `get_ini_value` round-trips `PLTF_NAME` and `PLTF_FOLDER`
  exactly, with no duplication and `DOMAIN` / `VERSION` / … preserved.
- `logs` (under the clone), `~/deployments`, and `~/deployments/admin` are all
  created; the `[OK] Installation completed successfully!` banner and the full
  Kata install/extract/cleanup sequence are present.

After the fix (Task 3.3) this same test is re-run and must still **PASS**
(no regressions in the Kata sequence, clone/submodule/`deploy.ini` writes, or
directory creation).

---

# Bash tests — `init-pltf-root-ownership-fix`

Bug-condition exploration test for the bugfix spec
`init-pltf-root-ownership-fix`. `init_pltf.sh` is run under `sudo` (it performs
privileged host provisioning), so every unprivileged step — `git clone`,
submodule init, `python3 -m venv`, `mkdir logs`, writing `conf/deploy.ini`, and
the `~/.aws` / `~/deployments/admin` creations — runs as root and leaves
root-owned paths. The script contains no `chown` and never references
`SUDO_USER`, so the invoking user cannot edit or deploy from the clone without
more `sudo`.

## Files

- `ownership_harness.sh` — sources the REAL `init_pltf.sh` under the source
  guard (`BASH_SOURCE[0] != $0`), so only the function definitions load and the
  destructive installer body never runs. It builds a temporary tree mirroring
  the clone destination (`REPO_DIR` with `shared`, `.venv`, `logs`,
  `conf/deploy.ini`, plus `README.md`) and the home artifacts (`~/.aws`,
  `~/deployments/admin`), simulates the sudo run by `chown -R root:root` over
  the tree, optionally invokes `restore_invoking_user_ownership` if the fix has
  defined it, and emits machine-readable `PROBE` lines reporting the resulting
  owner of every node. Ownership is virtualized by **fakeroot**, which reports
  `EUID 0` (realizing the bug context) and makes `chown`/`stat` operate on a
  virtual ownership table — so no real privilege is needed.

- `test_init_ownership.sh` — **Property 1 (Bug Condition)** exploration test.
  **Validates: Requirements 1.1, 1.2, 1.3, 1.4** (and exercises the group-edge
  of 2.4). Scoped property-based enumeration over the concrete bug cases from
  the design Test Plan: the clone root, its nested artifacts, the home
  artifacts, and the group-resolution edge. It encodes the EXPECTED (post-fix)
  behavior — every node owned by the invoking `user:group`, with the group
  resolved via `id -gn` — and asserts it against the UNFIXED script, where it
  MUST FAIL.

  Test cases:
  1. Clone root-owned (req 1.1) — the clone destination must end owned by the
     invoking user.
  2. Nested artifacts (req 1.2) — `shared`, `.venv`, `.venv/bin/activate`,
     `logs`, `conf/deploy.ini`, `README.md` must be owned by the invoking user,
     recursively.
  3. Home artifacts (req 1.2) — `~/.aws`, `~/.aws/credentials`,
     `~/deployments`, `~/deployments/admin` must be owned by the invoking user.
  4. Group-resolution edge (req 2.4) — invoking user `nobody` (primary group
     `nogroup`) must resolve to `nobody:nogroup`, not the naive `nobody:nobody`.
  Plus guards: the bug context is actually realized (`EUID == 0`), usability
  without sudo (req 1.3), and that an ownership-restoration step exists at all
  (req 1.4 — `restore_invoking_user_ownership` defined).

- `preservation_harness.sh` — **Property 2 (Preservation)** harness. Reuses the
  Task-1 pattern (sources the real `init_pltf.sh` under the source guard,
  mirrors `REPO_DIR` + home artifacts), but leaves the tree with its NATURAL
  creation ownership instead of forcing `root:root`, because preservation is
  about leaving that pre-run ownership untouched. It installs a `chown`
  shell-function wrapper that COUNTS every invocation (forwarding to
  `command chown`), records each node's pre-run `owner:group`, optionally
  invokes `restore_invoking_user_ownership` if the fix defined it, then emits
  `PROBE … pre=… post=…` lines plus `PROBE chown_calls=N`. Context is env-driven
  (`BUG_EUID` via fakeroot or not, `SUDO_USER` present/absent/`root`/nonexistent,
  `BUILD_HOME_ART`, `TREE_SHAPE` = `min`|`full`).

- `test_init_preservation.sh` — **Property 2 (Preservation)** test.
  **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6**. Observation-first:
  the unfixed (helper-absent) outcome was recorded for each non-bug context,
  then asserted exactly. Property-based over the non-bug input space — EUID
  (0 via fakeroot / non-0), `SUDO_USER` (unset / `root` / invoking user /
  nonexistent), home artifacts (present / absent), tree shape (min / full).
  For every generated context it asserts `chown_calls == 0` AND every node's
  `post == pre`. Cases: 3.1 non-root (EUID != 0), 3.2 bare-root (EUID 0,
  `SUDO_USER` unset), 3.3 `SUDO_USER=root`, 3.4 nonexistent `SUDO_USER`
  (malformed bug context the fix must treat as no-chown).

## Running

```bash
# fakeroot virtualizes EUID/chown/stat; no real root needed.
bash tests/bash/test_init_ownership.sh
bash tests/bash/test_init_preservation.sh
```

## Bug condition exploration — result (Task 1)

Run on the **UNFIXED** `init_pltf.sh`: the test **FAILS** (1 passed, 14 failed),
which is the expected/success outcome for an exploration test — it proves the
bug exists. The single PASS is the harness sanity check (the bug context is
genuinely realized, `EUID == 0`), which proves the test is discriminating
rather than failing for an unrelated reason.

### Counterexamples (14 failing assertions)

Simulated bug context `EUID == 0`, `SUDO_USER=slepetre` (non-root), the clone
and home artifacts created as root. `restore_invoking_user_ownership` is
`undefined` (`helper_defined=0`), so no restoration occurs and every node stays
`root:root` where `slepetre:slepetre` was expected:

- **Clone root-owned (req 1.1):** `REPO_DIR` → `root:root`, expected
  `slepetre:slepetre`. This is the reported defect
  (`sudo ./init_pltf.sh` by `slepetre` leaves the clone `root:root` instead of
  `slepetre:slepetre`).
- **Nested artifacts (req 1.2):** `shared`, `.venv`, `.venv/bin/activate`,
  `logs`, `conf/deploy.ini`, `README.md` all → `root:root`.
- **Home artifacts (req 1.2):** `~/.aws`, `~/.aws/credentials`, `~/deployments`,
  `~/deployments/admin` all → `root:root`.
- **Usability without sudo (req 1.3):** the clone is `root`-owned, so the
  invoking user `slepetre` would need `sudo` to modify or deploy from it.
- **No restoration step (req 1.4):** `restore_invoking_user_ownership` is
  undefined — nothing hands the root-created paths back to the invoking user.
- **Group-resolution edge (req 2.4):** with `SUDO_USER=nobody` the clone is
  `root:root`, expected `nobody:nogroup` (the resolved primary group), and in
  particular NOT the naive `nobody:nobody` — motivating group resolution via
  `id -gn` in the fix.

### Root cause confirmed

The script runs as a single linear body under one UID; launched with `sudo`
that UID is `0`, so every user-space step produces root-owned paths. There is no
`chown` anywhere and no use of `SUDO_USER`, so ownership is never restored.

### After the fix

Task 3 adds `restore_invoking_user_ownership` (defined above the source guard,
guarded to the bug condition, resolving the primary group via `id -gn` and the
home via `getent passwd`) and invokes it in the "Final configuration" step. Task
3.3 re-runs this same test; it is then expected to **PASS** (every node owned by
the invoking `user:group`).

## Preservation — result (Task 2)

Run on the **UNFIXED** `init_pltf.sh`: `test_init_preservation.sh` **PASSES**
(49/49 assertions), confirming the baseline that the fix must preserve. The
helper is absent on unfixed code (`helper_defined=0`), so no restoration runs
and the pre-run ownership persists in every non-bug context.

### Observed baseline (unfixed code, helper absent)

Following observation-first methodology, the unfixed outcome was recorded for
each non-bug context and then asserted exactly:

- **Non-root (EUID 1000), `SUDO_USER` unset or = invoking user** — the
  pre-populated tree keeps its original invoking-user ownership
  (`slepetre:slepetre`); `before == after` for every node; `chown_calls=0`.
- **Bare-root (fakeroot EUID 0), `SUDO_USER` unset** — the tree is created
  `root:root` and stays `root:root`; `before == after`; `chown_calls=0`;
  completes without error.
- **Root (fakeroot EUID 0), `SUDO_USER=root`** — treated as non-bug;
  `before == after`; `chown_calls=0`.
- **Root (fakeroot EUID 0), `SUDO_USER=<nonexistent>`** — malformed bug
  context; no (invalid) `chown` attempted; `before == after`; `chown_calls=0`.

Each case is exercised across tree shapes (`min`/`full`) and with/without the
home artifacts (`~/.aws`, `~/deployments/admin`), so the property spans varied
layouts. The `chown` wrapper counts every attempt (forwarding to
`command chown`), so `chown_calls=0` is a direct, stronger proof that no
ownership change was attempted — not merely that ownership happened to match.

After the fix (Task 3.4) this same test is re-run and must still **PASS**: the
helper's single bug-condition guard early-returns before any `chown` for every
non-bug context, so ownership stays identical and `chown_calls` stays 0.

## Focused unit / property / integration coverage (Task 4)

Task 4 adds three focused test files that run against the **fixed**
`init_pltf.sh` and must all PASS. They reuse the Task-1/2 harnesses where
sensible and add dedicated harnesses only where finer control is needed. All
ownership/EUID is virtualized by **fakeroot** (no real privilege required).

### New files

- `unit_harness.sh` + `test_init_ownership_unit.sh` — **UNIT** coverage for
  `restore_invoking_user_ownership`. The harness sources the real script under
  the source guard and installs (a) a `chown` wrapper that counts calls AND
  records every target path (recorded to a temp file so counts survive the
  command-substitution subshell the helper runs in) and (b) an optional
  `getent` wrapper so the passwd-home resolution path can be driven WITHOUT the
  `SIM_HOME` override. Cases:
  - **U1** — no-op for each non-bug context: `EUID != 0`; `SUDO_USER` unset;
    `SUDO_USER=root`. Zero chown calls, helper exit 0, ownership unchanged.
    _(Requirements 3.1, 3.2)_
  - **U2** — primary-group resolution via `id -gn`: invoking user `nobody`
    (primary group `nogroup`) resolves to `nobody:nogroup`, NOT the naive
    `nobody:nobody`. _(Requirement 2.4)_
  - **U3** — home resolution uses the passwd entry, not `$HOME`: driven with
    `SIM_HOME` UNSET and a `getent` wrapper whose passwd home (field 6) points
    at the sandbox home, while `HOME=/root` and a decoy `/root`-style home is
    present. Asserts the passwd-home `.aws`/`deployments` are the chown targets
    and end owned by the invoking user, and the decoy `$HOME` is NEVER a chown
    target — genuinely proving `$HOME` is not used. _(Requirements 2.1, 2.2)_
  - **U4** — nonexistent `SUDO_USER` (absent from passwd under EUID 0): the
    helper warns and skips, performs no chown, and returns success (does not
    abort the install). _(Requirement 3.2)_

- `property_harness.sh` + `test_init_ownership_property.sh` — **PROPERTY-BASED**
  coverage. The harness builds a RANDOMLY SHAPED clone tree (seed-driven random
  breadth/depth of dirs and files, plus the canonical `shared`/`.venv`/`logs`/
  `conf/deploy.ini` structure) and reports the pre/post `owner:group` of EVERY
  node recursively. Swept over seeds `{1, 7, 42, 101, 999}` (trees of ~18–32
  nodes):
  - **P1** — random BUG contexts (EUID 0, forced `root:root`, valid non-root
    `SUDO_USER`): every node ends owned by the invoking `user:group`. Swept over
    invoking users `{current user, nobody}` so the `id -gn` group resolution is
    also pinned. _(Requirements 2.1, 2.2, 2.4)_
  - **P2** — random NON-BUG contexts (`EUID != 0`, or `SUDO_USER` unset/`root`
    under EUID 0): ownership is identical to the pre-run state (`post == pre`
    for every node) AND `chown_calls == 0`. _(Requirements 3.1, 3.2)_

- `integration_harness.sh` + `test_init_ownership_integration.sh` —
  **INTEGRATION** coverage. The driver passes the REAL invoking user to the
  harness via `REAL_INVOKER`/`REAL_INVOKER_GROUP` (the harness runs under
  fakeroot where `id -un` would otherwise report `root`). Cases:
  - **T1** — full ownership-restore flow: reuses `ownership_harness.sh` (mirror
    tree `shared`/`.venv`/`logs`/`conf/deploy.ini` plus `~/.aws` and
    `~/deployments/admin`) under a bug context; the whole tree flips to the
    invoking user in one pass. _(Requirements 2.1, 2.2, 2.3)_
  - **T2** — context-switching: the SAME sourced helper is invoked first under a
    NON-BUG context (tree A, natural ownership → no-op, 0 chowns) then under a
    BUG context (tree B, forced `root:root` → fully restored, 3 chowns:
    `REPO_DIR` + `.aws` + `deployments`). Tree A stays untouched across both
    calls; the trees are handled independently. _(Requirements 2.1, 3.1)_
  - **T3** — sourcing side-effect-free: sourcing `init_pltf.sh` defines the
    helper (`helper_defined=1`) WITHOUT running the installer body
    (`body_ran=0`) and WITHOUT performing any chown (`chown_after_source=0`),
    returning cleanly via the source guard. _(Requirements 3.3, 3.4, 3.5, 3.6)_

### Running

```bash
# fakeroot virtualizes EUID/chown/stat; no real root needed.
bash tests/bash/test_init_ownership_unit.sh
bash tests/bash/test_init_ownership_property.sh
bash tests/bash/test_init_ownership_integration.sh
```

### Result (Task 4 — against the FIXED init_pltf.sh)

All three new files PASS, as do the re-run Task-1/2 tests (no regressions):

- `test_init_ownership_unit.sh` — 17/17
- `test_init_ownership_property.sh` — 30/30
- `test_init_ownership_integration.sh` — 10/10
- `test_init_ownership.sh` (Task 1, now fix-checking) — 15/15
- `test_init_preservation.sh` (Task 2) — 49/49
