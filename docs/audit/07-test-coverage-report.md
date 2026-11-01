# 07 — Test Coverage Report

- **Title:** Test Coverage Report
- **Audit date:** 2026-10-31
- **Requirement coverage:** R7.1, R7.2, R7.3, R7.4, R7.5, R7.6, R11.1
- **Method:** Enumerate every test file under `tests/`, `tests/js/`, `tests/bash/`, and `tests/runtime_monitor/`, plus `tests/conftest.py`, and map each file to the Subsystem or module it exercises — inferred from the filename and the `import`/`from src...` statements in the file. Each test is typed as `unit`, `property`, or `integration`: a file is `property` when it drives inputs through Hypothesis (`from hypothesis import given`) for Python or fast-check-style generators for JS, `integration` when it wires multiple subsystems/components together or spins an end-to-end flow, and `unit` otherwise. Inspection is read/search only; no application or test code was modified and no live service (PostgreSQL, Docker, Traefik) was started in this task. The baseline run itself is performed in task 7.2.

## Inspected Sources

Every file/dir below was read or enumerated for this artifact and is recorded as inspected for the purposes of R11.1.

- `tests/` (all `test_*.py`)
- `tests/js/` (all `*.test.js`)
- `tests/bash/` (all `*.sh` harnesses and tests)
- `tests/runtime_monitor/` (all `test_*.py`)
- `tests/conftest.py` (shared pytest fixtures / path bootstrap)

## 1. Inventory — Python tests (`tests/*.py`)

| Test File | Subsystem/Module | Type (unit/property/integration) |
|-----------|------------------|----------------------------------|
| `tests/test_aro_adapter_base.py` | ARO / `src/aro/adapters/base.py` (Capability, CapabilityError) | unit |
| `tests/test_aro_shai_adapters.py` | ARO / `src/aro/adapters/` (`shai_cli.py`, `shai_http_sse.py`, `sse_parser.py`, `base.py`) | unit |
| `tests/test_aro_kiro_acp.py` | ARO / `src/aro/adapters/` (`kiro_acp.py`, `acp_protocol.py`, `base.py`) | unit |
| `tests/test_aro_authz.py` | ARO/Security / `src/authz.py` (role hierarchy, tenant resolution, decorators) | property |
| `tests/test_aro_lifecycle.py` | ARO / `src/aro/lifecycle.py`, `src/aro/lifecycle_service.py` | property |
| `tests/test_aro_execution_manager.py` | ARO / `src/aro/execution_manager.py` | property |
| `tests/test_aro_events.py` | ARO / `src/aro/event_service.py`, `src/aro/events_repository.py` | property |
| `tests/test_aro_runtime_registry.py` | ARO / `src/aro/runtime_registry_service.py`, `src/aro/runtime_registry_repository.py` | unit |
| `tests/test_aro_runtime_scanner.py` | ARO / `src/aro/runtime_scanner.py` | unit |
| `tests/test_aro_task_worker.py` | ARO / Agent Supervisor — `src/aro/agent_worker.py`, `src/aro/task_repository.py` | unit |
| `tests/test_zaf_policy_engine.py` | ZAF / `src/zaf/policy_engine.py` | property |
| `tests/test_zaf_mcp_gateway.py` | ZAF / `src/zaf/mcp_gateway.py` (McpGateway, RateLimiter, validate_params), `policy_engine.py` | unit |
| `tests/test_zaf_infra_proxy.py` | ZAF / `src/zaf/infra_proxy.py`, `policy_engine.py`, `providers/openstack.py` | unit |
| `tests/test_zaf_approvals.py` | ZAF / `src/zaf/approval_service.py`, `src/zaf/governance_service.py` | unit |
| `tests/test_zaf_response.py` | ZAF / `src/zaf/response_service.py` | unit |
| `tests/test_zaf_credential_vault.py` | ZAF / `src/zaf/credential_vault.py` | property |
| `tests/test_obs_anomaly_risk.py` | OBS / `src/obs/anomaly_engine.py`, `src/obs/risk_scoring.py` | property |
| `tests/test_e2e_governed_scenario.py` | ARO + ZAF (cross-subsystem) / `src/aro/*` + `src/zaf/*` end-to-end governed flow | integration |
| `tests/test_shai_chat_subcommand_fix.py` | Infrastructure Orchestrator / `src/routes/genai_routes.py` (SHAI chat subcommand) | property |
| `tests/test_shai_chat_subcommand_fix_preservation.py` | Infrastructure Orchestrator / `src/routes/genai_routes.py` (preservation of chat form) | property |
| `tests/test_base_path_injection.py` | Infrastructure Orchestrator / `src/template_deploy.py` (BASE_PATH injection) | property |
| `tests/test_proxy_manager_api_surface.py` | Infrastructure Orchestrator / `src/frontend_manager.py` (proxy manager API surface) | unit |
| `tests/test_traefik_proxy_manager.py` | Infrastructure Orchestrator / `src/frontend_manager.py` (`_build_route_config`) | property |
| `tests/test_traefik_sync.py` | Infrastructure Orchestrator / Traefik sync reconciliation (`frontend_manager`) | property |
| `tests/test_traefik_timeouts.py` | Infrastructure Orchestrator / Traefik router timeouts (`frontend_manager`) | property |
| `tests/test_traefik_tls.py` | Infrastructure Orchestrator / Traefik TLS cert config (`frontend_manager`) | property |
| `tests/test_traefik_stripprefix.py` | Infrastructure Orchestrator / `src/frontend_manager.py` (`_prefix_path`, `_router_name`) | property |
| `tests/test_traefik_roundtrip.py` | Infrastructure Orchestrator / Traefik config roundtrip (`frontend_manager`) | property |
| `tests/test_traefik_failure_handling.py` | Infrastructure Orchestrator / `src/frontend_manager.py` failure handling | property |
| `tests/test_traefik_no_nginx_directives.py` | Infrastructure Orchestrator / Traefik config (no nginx directives) | property |
| `tests/test_traefik_no_nginx_writes.py` | Infrastructure Orchestrator / `frontend_manager` (no nginx file writes) | property |
| `tests/test_traefik_secondary_domains.py` | Infrastructure Orchestrator / `src/frontend_manager.py` (secondary domains) | property |
| `tests/test_traefik_api_version_pin.py` | Infrastructure Orchestrator / Traefik Docker API version pin | unit |
| `tests/test_traefik_api_version_pbt.py` | Infrastructure Orchestrator / Traefik Docker API version pin | property |
| `tests/test_traefik_api_version_preservation.py` | Infrastructure Orchestrator / Traefik API version preservation | property |
| `tests/test_traefik_docker_api_version.py` | Infrastructure Orchestrator / Traefik Docker API version negotiation | property |
| `tests/test_traefik_docker_api_version_integration.py` | Infrastructure Orchestrator / Traefik Docker API version (integration) | integration |
| `tests/test_traefik_control_plane.py` | Infrastructure Orchestrator / Traefik control-plane wiring | integration |
| `tests/test_traefik_compose_shape.py` | Infrastructure Orchestrator / Traefik docker-compose shape | unit |

> Note: `tests/conftest.py` is a shared fixture/path-bootstrap module, not a test file; it is recorded as inspected but carries no test cases of its own and therefore no type.

## 2. Inventory — JavaScript tests (`tests/js/*.test.js`)

The JS suite exercises the frontend dashboard logic (`templates/`-served JS: sorting, column detection, header resolution, agent management, dashboard lifecycle/preservation). The numbered `propertyN.test.js` files are generator-driven property tests; `*.test.js` fixtures around specific helpers are unit tests; `integration.test.js` wires the dashboard pieces together.

| Test File | Subsystem/Module | Type (unit/property/integration) |
|-----------|------------------|----------------------------------|
| `tests/js/applySort.test.js` | Frontend dashboard JS / `applySort` helper | unit |
| `tests/js/buildComparator.test.js` | Frontend dashboard JS / `buildComparator` helper | unit |
| `tests/js/detectColumnType.test.js` | Frontend dashboard JS / `detectColumnType` helper | unit |
| `tests/js/getCellText.test.js` | Frontend dashboard JS / `getCellText` helper | unit |
| `tests/js/resolveHeaders.test.js` | Frontend dashboard JS / `resolveHeaders` helper | unit |
| `tests/js/agentManagement.test.js` | Frontend dashboard JS / agent management UI logic | unit |
| `tests/js/dashboard-running-app-highlight.test.js` | Frontend dashboard JS / running-app highlight | unit |
| `tests/js/dashboard_functions_sync.test.js` | Frontend dashboard JS / dashboard functions (sync) | unit |
| `tests/js/dashboard_functions_lifecycle.test.js` | Frontend dashboard JS / dashboard functions (lifecycle) | unit |
| `tests/js/dashboard_functions_preservation.test.js` | Frontend dashboard JS / dashboard functions (preservation) | unit |
| `tests/js/dashboard_functions_served.test.js` | Frontend dashboard JS / dashboard functions (served markup parity) | unit |
| `tests/js/smoke.test.js` | Frontend dashboard JS / smoke sanity | unit |
| `tests/js/harness.test.js` | Frontend dashboard JS / test harness self-check (`harness.js`) | unit |
| `tests/js/integration.test.js` | Frontend dashboard JS / cross-helper dashboard integration | integration |
| `tests/js/property1.test.js` | Frontend dashboard JS / property 1 | property |
| `tests/js/property2.test.js` | Frontend dashboard JS / property 2 | property |
| `tests/js/property3.test.js` | Frontend dashboard JS / property 3 | property |
| `tests/js/property4.test.js` | Frontend dashboard JS / property 4 | property |
| `tests/js/property5.test.js` | Frontend dashboard JS / property 5 | property |
| `tests/js/property6.test.js` | Frontend dashboard JS / property 6 | property |
| `tests/js/property7.test.js` | Frontend dashboard JS / property 7 | property |
| `tests/js/property8.test.js` | Frontend dashboard JS / property 8 | property |

> Supporting (non-test) files in `tests/js/`: `harness.js` (test harness), `package.json` / `package-lock.json` (Node runner config), `README.md`, `.gitignore`, and `node_modules/` (vendored deps). These are recorded as inspected but are not test cases.

## 3. Inventory — Bash tests (`tests/bash/*.sh`)

The shell suite exercises the init/ownership/preservation behavior of the platform bootstrap (`init_pltf.sh` and related infrastructure scripts). Harness files (`*_harness.sh`) are runners that drive one or more `test_*.sh` files; the individual `test_*.sh` files carry the assertions, typed by their `_unit` / `_property` / `_integration` suffix.

| Test File | Subsystem/Module | Type (unit/property/integration) |
|-----------|------------------|----------------------------------|
| `tests/bash/test_init_ownership_unit.sh` | Infrastructure Orchestrator / init ownership (`init_pltf.sh`) | unit |
| `tests/bash/test_init_ownership_property.sh` | Infrastructure Orchestrator / init ownership (`init_pltf.sh`) | property |
| `tests/bash/test_init_ownership_integration.sh` | Infrastructure Orchestrator / init ownership (`init_pltf.sh`) | integration |
| `tests/bash/test_init_ownership.sh` | Infrastructure Orchestrator / init ownership (aggregate) | unit |
| `tests/bash/test_init_preservation.sh` | Infrastructure Orchestrator / init preservation (`init_pltf.sh`) | unit |
| `tests/bash/unit_harness.sh` | Infrastructure Orchestrator / runner for unit shell tests | unit (harness) |
| `tests/bash/property_harness.sh` | Infrastructure Orchestrator / runner for property shell tests | property (harness) |
| `tests/bash/integration_harness.sh` | Infrastructure Orchestrator / runner for integration shell tests | integration (harness) |
| `tests/bash/ownership_harness.sh` | Infrastructure Orchestrator / runner for ownership shell tests | integration (harness) |
| `tests/bash/preservation_harness.sh` | Infrastructure Orchestrator / runner for preservation shell tests | integration (harness) |

> `tests/bash/README.md` documents the harnesses and is recorded as inspected but is not a test case.

## 4. Inventory — Runtime monitor tests (`tests/runtime_monitor/*.py`)

These exercise OBS runtime-monitoring modules under `src/runtime_monitor/`.

| Test File | Subsystem/Module | Type (unit/property/integration) |
|-----------|------------------|----------------------------------|
| `tests/runtime_monitor/test_classifier.py` | OBS / `src/runtime_monitor/agent_classifier.py` | unit |
| `tests/runtime_monitor/test_collector.py` | OBS / `src/runtime_monitor/runtime_collector.py` | unit |
| `tests/runtime_monitor/test_repository.py` | OBS / `src/runtime_monitor/` repository persistence | unit |

> `tests/runtime_monitor/__init__.py` is a package marker (not a test) and is recorded as inspected.

## 5. Coverage summary by subsystem

| Subsystem | Test files mapped |
|-----------|-------------------|
| ARO (`src/aro/`) | `test_aro_adapter_base.py`, `test_aro_shai_adapters.py`, `test_aro_kiro_acp.py`, `test_aro_authz.py`, `test_aro_lifecycle.py`, `test_aro_execution_manager.py`, `test_aro_events.py`, `test_aro_runtime_registry.py`, `test_aro_runtime_scanner.py`, `test_aro_task_worker.py` |
| ZAF (`src/zaf/`) | `test_zaf_policy_engine.py`, `test_zaf_mcp_gateway.py`, `test_zaf_infra_proxy.py`, `test_zaf_approvals.py`, `test_zaf_response.py`, `test_zaf_credential_vault.py` |
| OBS (`src/obs/`, `src/runtime_monitor/`) | `test_obs_anomaly_risk.py`, `runtime_monitor/test_classifier.py`, `runtime_monitor/test_collector.py`, `runtime_monitor/test_repository.py` |
| Infrastructure Orchestrator | all `test_traefik_*.py`, `test_proxy_manager_api_surface.py`, `test_base_path_injection.py`, `test_shai_chat_subcommand_fix*.py`, all `tests/bash/*.sh`, all `tests/js/*.test.js` (dashboard frontend) |
| Agent Supervisor | `test_aro_task_worker.py` (shared with ARO: `agent_worker.py`), `test_e2e_governed_scenario.py` (cross-subsystem governed flow) |

## 6. Baseline Results

Baseline run performed by task 7.2 on the unmodified tree, using single-run invocations only (no watch mode, no server-starting commands, no live-service provisioning). No PostgreSQL, Docker, or Traefik daemon was started. No application, migration, test, or infrastructure code was modified.

### 6.1 Runner discovery

| Runner | Discovery | Availability | Version |
|--------|-----------|--------------|---------|
| Python / `pytest` | `python3 -m pytest` | available | `pytest 9.0.3` on `Python 3.11.3` (invoked under WSL `Python 3.12` site-packages) |
| Node / `node --test` | `tests/js/package.json` → `"test": "node --test"` | available | `node v22.13.0` (devDeps: `fast-check ^3.23.2`, `jsdom ^25.0.1`) |
| Bash harnesses | `tests/bash/{unit,property,integration}_harness.sh` | available | `GNU bash 5.2.21`; `fakeroot` present at `/usr/bin/fakeroot` |

All three runners are available, so no runner is recorded as `blocked — environment unavailable`.

### 6.2 Invocations (single-run, non-live-service)

- **Python:** `python3 -m pytest -q tests/` — scoped to the inventoried `tests/` tree. A bare `python3 -m pytest -q` aborts during collection with `ImportError: cannot import name 'DatabaseManager' from 'src.database_postgres'` raised by `scripts/test_backups_history.py` (a DB-coupled script outside the audited `tests/` inventory), so the run is scoped to `tests/` — the directory the task targets.
- **JavaScript:** `node --test` run from `tests/js/`.
- **Bash:** `bash tests/bash/unit_harness.sh`, `bash tests/bash/property_harness.sh`, and `REAL_INVOKER=… REAL_INVOKER_GROUP=… fakeroot bash tests/bash/integration_harness.sh`. The three harnesses are PROBE-emitting fixtures whose pass/fail assertions live in their driver scripts (`test_init_ownership_{unit,property,integration}.sh`); each harness ran to completion (exit 0) and the drivers were run to capture the actual verdicts. All execute entirely in `mktemp` sandboxes under `/tmp` with `fakeroot` virtualizing `chown`/EUID — no Docker, no DB, no Traefik.

### 6.3 Baseline results table

| Check | Runner | Result (pass/fail/blocked) | Reason |
|-------|--------|----------------------------|--------|
| `pytest -q tests/` (whole `tests/` suite) | `python3 -m pytest 9.0.3` | **fail** (suite) | `4 failed, 254 passed, 3 skipped in 69.76s`. 254 passing; 3 skipped are the `integration`-marked live-service tests (auto-skipped by default, see §6.4); 4 failing are itemized below. |
| `tests/test_traefik_docker_api_version.py::test_property1_expected_behavior_on_unfixed_configs[docker-mode-no-pin]` | pytest | **fail** | By-design bug-condition exploration test: `AssertionError: [docker mode] negotiated API 1.24 is below the daemon minimum 1.40`. The test docstring states it "MUST FAIL" on the unfixed tree as the counterexample proving the bug — pre-existing baseline failure, not a regression. No code changed. |
| `tests/test_traefik_docker_api_version.py::test_property1_expected_behavior_on_unfixed_configs[locally-mode-plain-export]` | pytest | **fail** | Same by-design bug-condition exploration: `AssertionError: [locally mode] negotiated API 1.24 is below the daemon minimum 1.40`. Pre-existing baseline failure. No code changed. |
| `tests/test_traefik_docker_api_version.py::test_property1_expected_behavior_on_unfixed_configs[locally-mode-no-pin]` | pytest | **fail** | Same by-design bug-condition exploration: `AssertionError: [locally mode] negotiated API 1.24 is below the daemon minimum 1.40`. Pre-existing baseline failure. No code changed. |
| `tests/test_shai_chat_subcommand_fix.py::test_developer_shai_uses_supported_headless_form` | pytest (Hypothesis) | **fail** | Property test falsified: `AssertionError: route returned early error: (<Response 29 bytes [200 OK]>, 400)`; falsifying example `message='\x85'`. The SHAI developer-chat route returns a 400 early-validation error for certain control/unicode messages instead of building the headless command. Pre-existing baseline failure observed on the unmodified tree; making it pass would require an application-code change, so it is recorded as-is (R7.6, R12.4) rather than fixed. |
| `node --test` (all `tests/js/*.test.js`) | `node v22.13.0` | **pass** | `tests 150 / pass 150 / fail 0 / skipped 0` in `~4.76s`. Covers the dashboard sortable-headers, agent-management, and lifecycle property/unit suites. |
| `bash tests/bash/unit_harness.sh` (driver `test_init_ownership_unit.sh`) | `bash 5.2.21` + `fakeroot` | **pass** | Harness emitted PROBE lines and exited 0; driver verdict `RESULT: 17 passed, 0 failed` / `UNIT OUTCOME: PASSED`. |
| `bash tests/bash/property_harness.sh` (driver `test_init_ownership_property.sh`) | `bash 5.2.21` + `fakeroot` | **pass** | Harness emitted PROBE lines over seeds 1/7/42/101/999 and exited 0; driver verdict `RESULT: 30 passed, 0 failed` / `PROPERTY OUTCOME: PASSED`. |
| `bash tests/bash/integration_harness.sh` (driver `test_init_ownership_integration.sh`) | `bash 5.2.21` + `fakeroot` | **pass** | Harness (run with `REAL_INVOKER`/`REAL_INVOKER_GROUP` under `fakeroot`, as its driver does) emitted PROBE lines and exited 0; driver verdict `RESULT: 10 passed, 0 failed` / `INTEGRATION OUTCOME: PASSED`. |

### 6.4 Not run in this baseline (require a live service)

The following were intentionally not executed because they require infrastructure the non-destructive scope forbids starting. They are carried here for completeness and are formally classified as `Blocked_Check`s in §7 (task 7.3).

| Check | Runner | Result | Reason |
|-------|--------|--------|--------|
| `integration`-marked pytest tests (incl. `tests/test_traefik_docker_api_version_integration.py`, `tests/test_traefik_control_plane.py`) | pytest | **blocked** | `blocked — environment unavailable`: marked `integration` per `tests/conftest.py`; require a live Traefik/Docker daemon and explicit opt-in env vars. Auto-skipped by default (contributes to the 3 skipped above where collected under `tests/`); not run — Docker/Traefik not provisioned per non-destructive scope. |
| `scripts/test_backups_history.py` and other DB-coupled `scripts/test_*.py` | pytest | **blocked** | `blocked — environment unavailable`: import/collection requires `src.database_postgres` DB wiring (`ImportError: cannot import name 'DatabaseManager'`) and a live PostgreSQL instance on the configured host; not provisioned per non-destructive scope. Outside the audited `tests/` inventory. |

### 6.5 Baseline summary

- **pytest (`tests/`):** 254 passed, 4 failed, 3 skipped. The 4 failures are pre-existing on the unmodified tree (3 are by-design bug-condition exploration tests from the Traefik Docker-API-version bugfix spec; 1 is a Hypothesis-falsified SHAI chat route validation). None were introduced by this audit.
- **node (`tests/js/`):** 150 passed, 0 failed.
- **bash (`tests/bash/`):** unit 17/0, property 30/0, integration 10/0 — all PASSED.
- **No runner was unavailable**; no `blocked — environment unavailable` runner entry was required. Live-service-dependent checks are recorded as blocked in §6.4 and classified in §7.

## 7. Pre-existing failures / Regressions

This section classifies the baseline outcomes from §6 (task 7.2). It separates **pre-existing baseline failures** (observed on the unmodified tree) from **regressions** (failures newly introduced by a change under audit), and consolidates every check that could not be executed into a single **Blocked_Checks** list. Per the non-destructive scope (R7.6, R12.4), no application, migration, test, or infrastructure code was modified and no live service (PostgreSQL, Docker, Traefik) was started: every failure is recorded as-is, and any check whose passing would require a code change or a live service is recorded as a `Blocked_Check` with its exact reason rather than being "fixed".

### 7.1 Pre-existing baseline failures

These failures were observed on the **unmodified** tree during the §6.3 baseline run. Each is reproducible without any edit to application code and existed before this audit began. Three are by-design bug-condition exploration tests (authored by the Traefik Docker-API-version bugfix spec to *fail* on the unfixed tree, proving the bug); the fourth is a Hypothesis-falsified property on the SHAI developer-chat route. None was introduced by this audit.

| # | Failing Test | Runner | Observed Failure (verbatim) | Classification | Would passing require a code change? |
|---|--------------|--------|-----------------------------|----------------|--------------------------------------|
| P1 | `tests/test_traefik_docker_api_version.py::test_property1_expected_behavior_on_unfixed_configs[docker-mode-no-pin]` | pytest 9.0.3 | `AssertionError: [docker mode] negotiated API 1.24 is below the daemon minimum 1.40` | Pre-existing — by-design bug-condition exploration test (docstring states it MUST FAIL on the unfixed tree; the assertion *is* the counterexample proving the Docker-API-version negotiation bug) | Yes — recorded as-is; a fix belongs to the Traefik Docker-API-version bugfix spec, not this audit |
| P2 | `tests/test_traefik_docker_api_version.py::test_property1_expected_behavior_on_unfixed_configs[locally-mode-plain-export]` | pytest 9.0.3 | `AssertionError: [locally mode] negotiated API 1.24 is below the daemon minimum 1.40` | Pre-existing — same by-design bug-condition exploration (locally-mode plain-export parametrization) | Yes — recorded as-is (same bugfix spec) |
| P3 | `tests/test_traefik_docker_api_version.py::test_property1_expected_behavior_on_unfixed_configs[locally-mode-no-pin]` | pytest 9.0.3 | `AssertionError: [locally mode] negotiated API 1.24 is below the daemon minimum 1.40` | Pre-existing — same by-design bug-condition exploration (locally-mode no-pin parametrization) | Yes — recorded as-is (same bugfix spec) |
| P4 | `tests/test_shai_chat_subcommand_fix.py::test_developer_shai_uses_supported_headless_form` | pytest 9.0.3 (Hypothesis) | `AssertionError: route returned early error: (<Response 29 bytes [200 OK]>, 400)`; falsifying example `message='\x85'` | Pre-existing — Hypothesis-falsified property: the SHAI developer-chat route returns a 400 early-validation error for certain control/unicode messages instead of building the headless command | Yes — making it pass requires an application-code change to `src/routes/genai_routes.py`; recorded as-is per R7.6/R12.4 |

**Count:** 4 pre-existing baseline failures (3 by-design Traefik Docker-API-version bug-condition exploration cases + 1 Hypothesis-falsified SHAI chat route). All four surface within `pytest -q tests/` (`4 failed, 254 passed, 3 skipped`). The passing runners (node `tests/js/` 150/150; bash unit 17/0, property 30/0, integration 10/0) contributed zero failures.

### 7.2 Regressions

**Empty by definition in this first audit pass.**

A regression is a test that passes on a known-good baseline but fails after a change under audit. This task audits the repository on its **unmodified** tree — no change was applied, so there is no "before/after" delta against which a regression could be measured. Every failure in §7.1 is reproducible on the untouched tree and is therefore pre-existing, not a regression. There are **0 regressions** in this audit pass. (Future passes that compare a modified tree against this recorded baseline should populate this subsection with any test that passed above but fails after the change.)

| # | Regressed Test | Runner | Baseline (this pass) | Current | Notes |
|---|----------------|--------|----------------------|---------|-------|
| — | _(none)_ | — | — | — | No regressions: first audit pass over unmodified code; no baseline-to-current delta exists. |

### 7.3 Consolidated Blocked_Checks

Each check below requires a live service that the non-destructive scope forbids starting, or whose collection/import depends on DB wiring that is not provisioned. All are labeled `blocked — environment unavailable` with the exact reason. These are carried from §6.4 and formalized here as `Blocked_Check`s (R7.4). They were **not** executed and are **not** counted as failures.

| Blocked_Check | Runner | Label | Exact Reason |
|---------------|--------|-------|--------------|
| `integration`-marked pytest tests — `tests/test_traefik_docker_api_version_integration.py`, `tests/test_traefik_control_plane.py`, and `tests/test_e2e_governed_scenario.py` | pytest | `blocked — environment unavailable` | Marked `integration` per `tests/conftest.py`; require a live Traefik/Docker daemon and explicit opt-in env vars. Auto-skipped by default (the 3 skipped in the §6.3 count); not run — Docker/Traefik not provisioned per non-destructive scope. |
| DB-coupled `scripts/test_*.py` — e.g. `scripts/test_backups_history.py` | pytest | `blocked — environment unavailable` | Import/collection requires `src.database_postgres` DB wiring (`ImportError: cannot import name 'DatabaseManager' from 'src.database_postgres'`) and a live PostgreSQL instance on the configured host (localhost:5432); not provisioned per non-destructive scope. Outside the audited `tests/` inventory. |

> Scope note: Only the `integration`-marked tests that were actually collected under `tests/` during the §6.3 run are auto-skipped there; `test_e2e_governed_scenario.py` is listed as a `Blocked_Check` because its cross-subsystem end-to-end flow needs the same live-service wiring. The DB-coupled `scripts/test_*.py` files live outside the audited `tests/` inventory and block at import time; the §6.2 invocation was therefore scoped to `tests/` so the remainder of the suite could run.

### 7.4 Classification summary

| Outcome | Count | Detail |
|---------|-------|--------|
| Pre-existing baseline failures | 4 | 3 by-design Traefik Docker-API-version bug-condition exploration cases (P1–P3) + 1 Hypothesis-falsified SHAI chat route (P4) |
| Regressions | 0 | Empty by definition in a first audit pass over unmodified code |
| Blocked_Checks | 2 groups | `integration`-marked pytest tests (live Traefik/Docker) + DB-coupled `scripts/test_*.py` (live PostgreSQL) — all `blocked — environment unavailable` |
| Passing (for reference) | 254 pytest + 150 node + 57 bash | See §6.3 / §6.5 |

No failing test was modified to make it pass; every failure is recorded as-is and, where passing would require an application-code change (P4) or a live service (Blocked_Checks), that requirement is recorded in place of a fix (R7.5, R7.6, R12.4).
