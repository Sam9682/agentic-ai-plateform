# 10 — Phase-Ordered Implementation Plan

- **Title:** Phase-Ordered Implementation Plan
- **Audit date:** 2026-10-31
- **Requirement coverage:** R10.1, R10.2, R10.3, R10.4
- **Derived from:** `docs/audit/09-gap-matrix.md` (the 30-row Gap Matrix), `docs/audit/05-security-gap-analysis.md` (security limitations), and `docs/audit/06-runtime-gap-analysis.md` (runtime limitations), with consolidation targets from `docs/audit/08-duplication-report.md`.
- **Method:** The phases are shaped by the *actual* findings of the audit, not a generic roadmap. Each phase states its scope and concrete deliverables, then cites — by Subsystem / Sub-Feature — the exact Gap Matrix rows it moves forward, and the exact security (05) / runtime (06) limitations it resolves. Every citation is traceable back to a row or a tagged limitation in an upstream artifact, satisfying R10.4 (direct traceability).

## How to read this plan

- **Phase ordering rationale.** Phase 1 comes first because the consolidation/foundation work (single entry point, one bootstrap script, one reverse proxy) de-risks every later phase by removing ambiguity about *which* code runs. ARO completion (Phase 2) precedes ZAF hardening (Phase 3) because the ZAF enforcement path must be interposed on a *working, complete* ARO execution flow. Runtime execution (Phase 4) hardens the shared dispatch/timeout/retry substrate that both ARO and the orchestrator depend on. OBS pipeline wiring and the net-new Agent Supervisor (Phase 5) build on the completed execution + governance surface. Integration & end-to-end (Phase 6) is last because it can only exercise the full flow once every component is wired.
- **Classification shorthand** (from the Gap Matrix): `VERIFIED` = IMPLEMENTED_AND_VERIFIED, `INCOMPLETE` = IMPLEMENTED_BUT_INCOMPLETE, `PARTIAL` = PARTIALLY_INTEGRATED, `NOT_IMPL` = NOT_IMPLEMENTED.
- **Severity/impact tags** are carried verbatim from the 05/06 limitation tables (H/M/L).

## Phase map at a glance

| Phase | Theme | Gap Matrix rows primarily addressed | Dominant driver |
|-------|-------|-------------------------------------|-----------------|
| 1 | Foundation & consolidation | (no Gap Matrix sub-feature regresses; clears duplication debt) | `08` duplications + `05` default-secret findings |
| 2 | ARO completion | ARO: lifecycle, adapters, execution manager, sessions, runtime registry, task store (6 INCOMPLETE) | `06` ARO/adapter limitations |
| 3 | ZAF security hardening & wiring | ZAF: action interceptor, PEP/PDP split, credential broker, audit (4 PARTIAL) + identity, quarantine (2 INCOMPLETE) | `05` H/M security findings |
| 4 | Runtime execution hardening | Infrastructure Orchestrator: remote exec, scheduler, reconciliation, connectors (4 INCOMPLETE) | `06` orchestrator/SSH/serverless limitations |
| 5 | OBS pipeline & Agent Supervisor | OBS: classification, anomaly rules, loop detection (3 PARTIAL) + cost (NOT_IMPL); Agent Supervisor: roles, decomposition, delegation, governance inheritance (4 NOT_IMPL) | Gap Matrix PARTIAL/NOT_IMPL |
| 6 | Integration & end-to-end | Converts PARTIAL → integrated and INCOMPLETE → VERIFIED across all subsystems | `09` Baseline `Blocked_Check`s |

---

## Phase 1 — Foundation & Consolidation

### Scope
Collapse the duplicated entry-point, bootstrap, and reverse-proxy debt identified in `08`, and remove the hard-coded/default secrets that undermine every later security phase, so that subsequent phases operate on a single, unambiguous runtime path. This phase deliberately touches no Gap Matrix *sub-feature* behavior — it is a prerequisite that removes "which code actually runs?" ambiguity before ARO/ZAF/OBS work begins.

### Deliverables
1. **Single application entry point.** Collapse to `wsgi:application` backed by `src/ControlPlanFlaskApp_postgres.create_app`; retire the root shim `ControlPlanFlaskApp.py` and reconcile `src/main.py` into (or behind) the one factory. Update the legacy `Dockerfile` to stop referencing the shim.
2. **Single bootstrap script.** Reconcile `init_pltf.sh` and `init_pltf_fixed.sh` (139 differing lines) into one canonical bootstrap, folding in the `_fixed` Docker/Kata install and submodule-URL blocks.
3. **Single reverse proxy.** Retire `src/frontend_nginx_manager.py` (no inbound import) now that routing is Traefik-based via `src/frontend_manager.py`; remove the nginx config path from the orchestrator reconcile loop.
4. **De-duplicate the shadowed route.** Remove the duplicate `GET /api/deployments/<int:deployment_id>/logs` / `api_deployment_logs` handler so it is defined once (currently in both `routes/api_routes.py` and `routes/genai_routes.py`, with last-registered winning).
5. **Eliminate default/hard-coded secrets.** Replace the hard-coded `POSTGRES_PASSWORD` / Flask `SECRET_KEY` development fallbacks and the predictable seeded `admin`/`demo` password so production cannot start with known credentials.

### Traceability — consolidation targets (`08`)
- App entry point group — `ControlPlanFlaskApp.py` / `src/ControlPlanFlaskApp_postgres.py` / `wsgi.py` / `src/main.py` (Duplications table; `ControlPlanFlaskApp.py` also in the Obsolete table).
- Bootstrap script group — `init_pltf.sh` / `init_pltf_fixed.sh` (Duplications + Obsolete tables).
- Reverse-proxy manager group — `src/frontend_manager.py` (Traefik) vs `src/frontend_nginx_manager.py` (nginx; Obsolete table, no inbound import).
- Deployment-logs route group — `src/routes/api_routes.py` / `src/routes/genai_routes.py` (Duplications table).
- Legacy `Dockerfile` (Obsolete table — keeps the root shim alive).

### Traceability — security findings resolved (`05`)
- *Hard-coded default `POSTGRES_PASSWORD` and Flask `SECRET_KEY` fallbacks; secrets outside the vault unencrypted* — `src/config_postgres.py` (Severity **M**).
- *Default `admin`/`demo` users seeded with a known default password* — `src/database_postgres.py` (Severity **M**).

### Phase exit criteria
One entry point, one bootstrap script, one reverse-proxy manager, one `api_deployment_logs` route; no default secret can start a production process. The baseline test suite (254 pytest / 150 node / 57 bash from `09`) still passes after consolidation.

---

## Phase 2 — ARO Completion

### Scope
Close the internal-completeness gaps in the ARO subsystem. The Gap Matrix classifies ARO as **1 VERIFIED, 6 INCOMPLETE** — the registry is verified, but lifecycle, adapters, execution manager, sessions, runtime registry, and the task store each have core behavior with known gaps or an unverified `Blocked_Check`. This phase makes the agent execution flow correct and complete end-to-end (dispatch → launch → stream → terminal state) before any enforcement layer (Phase 3) is interposed on it.

### Deliverables
1. **Lifecycle completion.** Add a release transition out of `QUARANTINED`; wire periodic `health_check()` probing to drive agents into `UNHEALTHY`; move `agent_executions` rows past `STARTING` to RUNNING/STOPPED/ended; make multi-step drivers (`install_and_ready`/`start`) atomic or compensating.
2. **Adapter protocol coverage.** Implement the missing **generic MCP adapter** so a `protocol: mcp` registration is usable; add read timeouts to ACP stream/handshake; make Kiro ACP `cancel()` force-close on timeout; fix the SHAI CLI `result()`/`stream()` race and child-process termination; make HTTP/SSE terminal-event handling robust; add install-integrity (checksum) verification to the SHAI CLI adapter.
3. **Execution manager correctness.** Make `select_server` honor load **and** `tenant_id` (currently `ORDER BY s.id LIMIT 1`, `tenant_id` unused); enforce image digest/tag pinning; verify the `zaf-proxy-net` network exists before relying on egress lockdown; add cancel/retry for in-flight launches.
4. **Session durability.** Add session resumption/reconnect after a control-plane restart so an in-memory `_session_id`/`_transport` loss does not orphan the remote runtime; close out the execution-row lifecycle.
5. **Task store reliability.** Add a lease/heartbeat reaper to recover `claimed`/`running` tasks from dead workers; tenant-scope `complete()`/`mark_running()` writes; enforce `timeout_seconds` and `max_attempts` in the worker (see Phase 4 for the shared policy).

### Traceability — Gap Matrix rows (`09`)
- ARO / **Lifecycle manager** (INCOMPLETE) — `src/aro/lifecycle.py`, `lifecycle_service.py`.
- ARO / **Runtime adapter interface** (INCOMPLETE) — `src/aro/adapters/*` (the `mcp` protocol has no adapter).
- ARO / **Execution manager** (INCOMPLETE) — `src/aro/execution_manager.py`.
- ARO / **Sessions** (INCOMPLETE) — `src/aro/execution_manager.py`, `event_service.py`, `events_repository.py`.
- ARO / **Runtime registry** (INCOMPLETE) — `src/aro/runtime_registry_service.py`, `runtime_registry_repository.py`, `runtime_scanner.py`.
- ARO / **Task store** (INCOMPLETE) — `src/aro/task_repository.py`.
- (Also advances ZAF / **Quarantine** INCOMPLETE — the `QUARANTINED` release path lives in `lifecycle.py`; completed here, consumed by Phase 3.)

### Traceability — runtime findings resolved (`06`)
- *No generic MCP/CLI adapter implemented* — `src/aro/adapters/base.py`, `runtime_registry_service.py` (**H**).
- *ACP stream/handshake have no read timeout* — `src/aro/adapters/kiro_acp.py` (**H**).
- *ACP cancel best-effort, non-interrupting* — `src/aro/adapters/kiro_acp.py` (**M**).
- *SHAI CLI `result()` races `stream()`* / *cancel may not stop in-container children* / *install lacks integrity verification* — `src/aro/adapters/shai_cli.py` (**M**).
- *HTTP/SSE completion depends on undocumented event names* — `src/aro/adapters/shai_http_sse.py` (**M**).
- *`select_server` ignores load and tenant* — `src/aro/execution_manager.py` (**H**).
- *Image pinning assumed, not enforced* / *proxy network existence unverified* / *no cancel/retry on in-flight launch* — `src/aro/execution_manager.py` (**M**).
- *`timeout_seconds` stored but never enforced* / *retry documented but not implemented* — `src/aro/agent_worker.py` (**H**).
- *No lease/heartbeat to recover dead-worker tasks* — `src/aro/task_repository.py` (**H**); *`complete()`/`mark_running()` not tenant-scoped* (**L**).
- *No session resumption after control-plane restart* — `src/aro/adapters/kiro_acp.py`, `lifecycle_service.py` (**M**).
- *QUARANTINED has no release transition* / *UNHEALTHY never auto-driven* / *execution row never moved past STARTING* / *multi-step drivers non-atomic* — `src/aro/lifecycle.py`, `lifecycle_service.py` (**M**).

### Phase exit criteria
Each ARO INCOMPLETE row has its internal gaps closed and a non-blocked covering test, making it eligible for `VERIFIED` once run in Phase 6. A `protocol: mcp` runtime can be launched; a dead worker's tasks are reclaimed; a quarantined agent can be released.

---

## Phase 3 — ZAF Security Hardening & Wiring

### Scope
Resolve the ZAF enforcement-path integration gap and the high-severity security findings. The Gap Matrix shows ZAF as **2 VERIFIED, 2 INCOMPLETE, 4 PARTIAL**: the PDP (policy engine) and approval service are verified, but the PEP (action interceptor), the PEP/PDP split, the credential broker, and the audit/response hook all **exist and are unit-tested yet have no inbound `src/` consumer** — they are not interposed on live ARO execution/MCP traffic. This phase wires the enforcement layer onto the now-complete ARO flow from Phase 2 and closes the H/M security limitations from `05`.

### Deliverables
1. **Interpose the PEP.** Wire `src/zaf/mcp_gateway.py` and `src/zaf/infra_proxy.py` in front of ARO execution and MCP traffic so the PEP actually enforces PDP decisions on live calls (today no route/runtime imports them).
2. **Secure the MCP surface.** Add authentication/authorization to the MCP stdio tools so `user_id` is no longer a trusted argument; consult the ZAF policy engine / approval service before privileged operations (deploy, start/stop, backup/restore, `modify_code`); add per-tool rate limiting/quota.
3. **Remove hard-coded Gitea credentials.** Eliminate the static `gitadmin` credential embedded in constructed repo URLs in `src/mcp_interface.py` and `src/routes/genai_routes.py`; stop persisting the secret-bearing URL into `deployments.modification_history` / `gitea_branch_url`; stop streaming it into the SSE `data:` chunk.
4. **Wire the credential broker.** Route runtimes through `credential_vault.mint_scoped_token`/`get` so the scoped-token-to-runtime handoff is actually exercised (today the vault has no inbound `src/` consumer); harden key derivation with a salted KDF (PBKDF2/scrypt/argon2) and add key-versioning for rotation; return decrypted plaintext behind a wrapper type rather than a bare dict.
5. **Wire the audit/response hook.** Interpose `src/zaf/response_service.py` on the live execution path (post-execution handling / OBS linkage), and emit an audit event on denied tenant switches in `authz.py`.
6. **Converge the authorization model.** Migrate the legacy inline `username == 'admin'` / `user_id in session` routes onto the `authz.py` tenant-scoped decorators so there is one authorization model with tenant scoping (currently two divergent models).
7. **Harden SSO token handling.** Add an HMAC/keyed MAC over stored token hashes; move the SSO token out of the redirect URL query string; add rate limiting / failure auditing on token validation.
8. **Complete quarantine enforcement.** Build on the Phase 2 `QUARANTINED` release path with an isolation-enforcement path (not just a state change).

### Traceability — Gap Matrix rows (`09`)
- ZAF / **Action interceptor** (PARTIAL) — `src/zaf/mcp_gateway.py`, `infra_proxy.py` (no inbound import).
- ZAF / **PEP / PDP split** (PARTIAL) — PEP `mcp_gateway.py` not interposed on live traffic.
- ZAF / **Credential broker** (PARTIAL) — `src/zaf/credential_vault.py` (no inbound `src/` consumer).
- ZAF / **Audit** (PARTIAL) — `src/zaf/response_service.py` (enforcement hook not wired), `governance_service.py`.
- ZAF / **Identity manager** (INCOMPLETE) — `src/zaf/providers/openstack.py`, `governance_service.py`; platform identity in `auth.py`/`authz.py`.
- ZAF / **Quarantine** (INCOMPLETE) — `src/zaf/governance_service.py`, `src/aro/lifecycle.py`.

### Traceability — security findings resolved (`05`)
- *MCP stdio tools perform no authn/authz; `user_id` is a trusted argument* — `src/mcp_interface.py` (**H**).
- *Hard-coded Gitea credential embedded in a constructed repo URL* — `src/mcp_interface.py` (**H**) and `src/routes/genai_routes.py` (**H**).
- *Secret-bearing Gitea URL persisted unredacted into `deployments.modification_history`/`gitea_branch_url`* — `src/mcp_interface.py` (**H**).
- *`authz.py` decorators not applied to legacy routes; legacy auth uses a magic `username == 'admin'` check* — `src/authz.py` (**H**).
- *Fernet key derived via unsalted single-round SHA-256; no KDF, no key versioning/rotation* — `src/zaf/credential_vault.py` (**M**).
- *Credential broker has no inbound `src/` consumer — scoped-token handoff not wired* — `src/zaf/credential_vault.py` (**M**).
- *Decrypted credential plaintext returned by value with no wrapper/zeroization* — `src/zaf/credential_vault.py` (**M**).
- *SSO token stored as unsalted fast SHA-256 (no HMAC)* — `src/auth.py` (**M**); *no rate limiting / brute-force protection* (**L**).
- *SSO token placed in redirect URL query string* — `src/routes/sso_routes.py` (**M**).
- *No denied-tenant-switch audit event; coarse `viewer/operator/admin` model* — `src/authz.py` (**L**).
- *MCP operator tools have no per-tool rate limit/quota; convention-built paths not validated* — `src/mcp_interface.py` (**L**).

### Phase exit criteria
Every ZAF PARTIAL row has a live inbound caller (PEP interposed, broker minting scoped tokens, response hook firing); all six High-severity `05` findings are closed; one authorization model governs all routes.

---

## Phase 4 — Runtime Execution Hardening

### Scope
Harden the shared execution substrate the Infrastructure Orchestrator depends on. The Gap Matrix classifies all four orchestrator sub-features (remote execution, scheduler, reconciliation, connectors) as **INCOMPLETE** — each is implemented but unverified (live-service `Blocked_Check`) with known timeout/retry/placement gaps. `06` also records *two parallel execution engines with inconsistent timeout/retry/cancellation* (serverless vs ARO agent worker) and a single host-key-disabled SSH chokepoint. This phase introduces a shared execution policy (timeout, retry/backoff, cancellation) and fixes the remote-exec and reconciliation defects.

### Deliverables
1. **Shared execution policy.** Factor one timeout / retry-with-backoff / cancellation abstraction used by both the serverless worker and the ARO agent worker (today they are two divergent implementations of the same claim/poll pattern), and by the orchestrator subprocess calls.
2. **Remote execution hardening.** Re-enable SSH host-key verification (replace `StrictHostKeyChecking=no` + `/dev/null` known-hosts); raise/parameterize the 30s default timeout for container ops; add connection reuse/pooling and transient-failure retry; move off single-shell-string transport toward an arg-array where feasible.
3. **Scheduler/reconcile hardening.** Add `timeout=` to the `docker`/`nginx` subprocess calls so a hung call cannot wedge the reconcile thread; add retry/backoff and a crash-loop cap on instance start; replace the process-local `threading.Lock` with a cross-process/DB advisory lock; add a join timeout to loop shutdown. Honor real multi-server placement (today Docker is invoked locally regardless of selected `server_id`).
4. **Reconciliation remediation.** Make the health check retry with a grace period and actually remediate `unhealthy` instances (restart/replace) rather than only updating a column; remove the residual nginx path (completed in Phase 1).
5. **Connector hardening.** Fix the serverless `container_runtime` stdout/stderr capture (logs currently mis-attributed/empty); add image digest pinning and pull retry; enforce `max_concurrent_jobs`; add per-operation DB connection pooling; add live start/stop/restart actuation to `agent_control_service` (currently read-only) and parallelize its multi-server scan.

### Traceability — Gap Matrix rows (`09`)
- Infrastructure Orchestrator / **Remote execution** (INCOMPLETE) — `src/ssh_utils.py`, `src/sandbox_manager.py`.
- Infrastructure Orchestrator / **Scheduler** (INCOMPLETE) — `src/orchestrator.py`, `src/serverless/worker.py`.
- Infrastructure Orchestrator / **Reconciliation** (INCOMPLETE) — `src/orchestrator.py`, `src/platform_discovery.py`.
- Infrastructure Orchestrator / **Connectors** (INCOMPLETE) — `src/agent_control_service.py`, `src/serverless/container_runtime.py`.

### Traceability — runtime findings resolved (`06`)
- *Docker invoked locally despite server selection* / *no `timeout=` on docker/nginx subprocesses* — `src/orchestrator.py` (**H**).
- *No retry/backoff or crash-loop cap on instance start* / *process-local lock only* / *shallow single-attempt health check, no remediation* — `src/orchestrator.py` (**M**); *mixed Traefik+nginx routing* / *reconcile loop stop has no join timeout* (**L**).
- *SSH host-key verification disabled* — `src/ssh_utils.py` (**H**); *default 30s SSH timeout too short* / *command passed as single shell string* / *no SSH retry/connection reuse* (**M**).
- *stdout/stderr capture unreliable* — `src/serverless/container_runtime.py` (**H**).
- *No image digest pinning or pull retry (serverless)* / *`max_concurrent_jobs`/warm pool config-only* / *per-operation DB connections, no pooling* / *serverless timeout approximate, cancel poll-based* / *no retry for transient serverless jobs* — `src/serverless/config.py`, `worker.py`, `container_runtime.py` (**M**).
- *No live start/stop/restart control actions* / *multi-server scan is serial* — `src/agent_control_service.py` (**M**).
- *Two parallel execution engines/queues* / *inconsistent timeout/retry/cancel across engines* — `src/orchestrator.py`, `src/aro/agent_worker.py`, `src/serverless/worker.py` (**M**).
- *Sandbox rollback best-effort, can orphan resources* / *teardown needs injected orchestrator* — `src/sandbox_manager.py` (**M**).

### Phase exit criteria
A single execution policy enforces timeout/retry/cancellation across both engines; SSH verifies host keys; the reconcile loop cannot be wedged by a hung subprocess and actually remediates unhealthy instances; serverless logs are captured correctly and concurrency limits are enforced.

---

## Phase 5 — OBS Pipeline & Agent Supervisor

### Scope
Wire the OBS detection pipeline into the live flow and build the entirely net-new Agent Supervisor. The Gap Matrix shows OBS as **2 VERIFIED, 1 INCOMPLETE, 3 PARTIAL, 1 NOT_IMPL** — runtime/agent behavior are verified, but classification, anomaly rules, and loop detection all **exist and pass unit tests yet have no inbound `src/` caller feeding them live observations**, and OBS cost is unimplemented. The Agent Supervisor is **4 NOT_IMPL** (roles, task decomposition, delegation, governance inheritance) — none of it exists today. This phase depends on the completed execution flow (Phase 2/4) and the wired governance layer (Phase 3).

### Deliverables
1. **Wire the OBS detection pipeline.** Add a route/worker that feeds live event windows into `anomaly_engine.analyze(...)` and runs `risk_scoring` on live observations (today the `/anomalies` and `/agents/<id>/risk` routes only read pre-recorded rows that nothing in-repo writes via the engine). Loop detection (`detect_repeated_commands` → `execution.loop`) rides on the same wiring.
2. **OBS cost pipeline.** Implement agent/runtime cost-and-usage accounting inside `src/obs/` (e.g. an `obs_cost` module joined to runtime-monitor usage), distinct from the separate platform billing path which is not OBS-linked.
3. **Agent Supervisor — roles.** Introduce a supervising-agent role model (new module, e.g. `src/aro/supervisor.py`, plus a roles table); `agent_worker.py` today is a flat task executor with no roles.
4. **Agent Supervisor — task decomposition.** Add a parent/child task schema alongside `task_repository` and a decomposition planner that fans a task into sub-tasks (none exists today).
5. **Agent Supervisor — delegation.** Add agent-to-agent delegation coordinating multiple `agent_worker` executions (today one task binds to one agent's adapter).
6. **Agent Supervisor — governance inheritance.** Propagate a parent agent's governance context/constraints down to delegated/child agents, consuming ZAF `governance_service` (wired in Phase 3); this is only meaningful once delegation and decomposition exist.

### Traceability — Gap Matrix rows (`09`)
- OBS / **Classification** (PARTIAL) — `src/obs/risk_scoring.py` (consumed only by the unwired `anomaly_engine`).
- OBS / **Anomaly rules** (PARTIAL) — `src/obs/anomaly_engine.py` (no inbound import; no live caller).
- OBS / **Loop detection** (PARTIAL) — `src/obs/anomaly_engine.py` (`detect_repeated_commands` → `execution.loop`).
- OBS / **Cost** (NOT_IMPL) — `—` (would live in `src/obs/`).
- OBS / **Infra metrics** (INCOMPLETE) — `src/obs/obs_repository.py`, `runtime_monitor/*` (endpoint aggregates event counters, not true infra metrics) — advanced here opportunistically with the pipeline wiring.
- Agent Supervisor / **Roles** (NOT_IMPL) — `—` (new `src/aro/supervisor.py` + roles table).
- Agent Supervisor / **Task decomposition** (NOT_IMPL) — `—` (parent/child schema alongside `task_repository`).
- Agent Supervisor / **Delegation** (NOT_IMPL) — `—` (supervisor module over multiple `agent_worker` runs).
- Agent Supervisor / **Governance inheritance** (NOT_IMPL) — `—` (consumes `src/zaf/governance_service.py`).

### Traceability — supporting findings
- The OBS integration gap (no inbound import for `anomaly_engine`/`risk_scoring`) is the `02`-sourced evidence cited in the Gap Matrix PARTIAL ratings; the `08` report confirms `anomaly_engine.py` is *not-yet-integrated*, not obsolete, so this phase wires rather than rewrites it.
- Agent Supervisor governance inheritance depends on the ZAF governance primitives being interposed on the live path (Phase 3), per the Gap Matrix note that the inheritance sub-feature "would live where delegation is added, consuming `governance_service`."

### Phase exit criteria
Live observations flow into the anomaly/risk/loop detectors and surface through the OBS routes; an OBS cost figure is produced per agent/runtime; a supervising agent can decompose a task, delegate sub-tasks to child agents, and have governance constraints inherited by those children.

---

## Phase 6 — Integration & End-to-End

### Scope
Prove the whole system works together and convert audit classifications upward. The Gap Matrix `_VERIFIED` rule requires a **passing, non-blocked** covering test; today the integration-marked tests (`test_e2e_governed_scenario.py`, live Traefik/Docker) and DB-coupled `scripts/test_*.py` are `Blocked_Check`s because the audit was strictly non-destructive and started no live service. This phase stands up the live environment and exercises the end-to-end path so that INCOMPLETE rows (now internally complete after Phases 2/4) and PARTIAL rows (now wired after Phases 3/5) can be re-run and promoted to `VERIFIED`.

### Deliverables
1. **Stand up the live test environment** (PostgreSQL, Docker, Traefik) and run the previously `Blocked_Check`ed integration and DB-coupled suites.
2. **End-to-end governed scenario.** Exercise the full flow — task submit → PEP/PDP decision → scoped-token handoff → ARO launch over hardened SSH → streamed execution with enforced timeout/retry → OBS anomaly/risk/cost observation → audit/response hook — i.e. `test_e2e_governed_scenario.py` and siblings, now that every link is wired.
3. **Promote classifications.** Re-run covering tests so each ARO INCOMPLETE row (Phase 2) and each orchestrator INCOMPLETE row (Phase 4) with a now-passing non-blocked test moves to `VERIFIED`, and each ZAF/OBS PARTIAL row (Phases 3/5) with a live inbound caller is confirmed integrated.
4. **Clear the pre-existing baseline failures.** Address the 4 pre-existing failures recorded in `09`/`07` (3 by-design Traefik Docker-API-version bug-condition cases + 1 Hypothesis-falsified SHAI chat route in `src/routes/genai_routes.py`) so the baseline is green.

### Traceability — Gap Matrix rows (`09`)
- **All INCOMPLETE rows** whose only blocker to `VERIFIED` was a `Blocked_Check`: Infrastructure Orchestrator / Remote execution, Scheduler, Reconciliation, Connectors; plus the ARO rows completed in Phase 2.
- **All PARTIAL rows** now wired: ZAF / Action interceptor, PEP/PDP split, Credential broker, Audit (Phase 3); OBS / Classification, Anomaly rules, Loop detection (Phase 5).
- The Baseline_Result basis for `_VERIFIED` and the enumerated `Blocked_Check`s (`test_e2e_governed_scenario.py`, live Traefik/Docker integration tests, DB-coupled `scripts/test_*.py`) are taken directly from the Gap Matrix "Baseline_Result basis" section (sourced from `07`).

### Traceability — findings resolved
- Closing the pre-existing baseline failures resolves the 1 Hypothesis-falsified SHAI chat route finding that overlaps the `05` Gitea-credential-in-SSE finding for `src/routes/genai_routes.py` (also addressed in Phase 3) and the 3 Traefik Docker-API-version bug-condition cases referenced in `07`.

### Phase exit criteria
The end-to-end governed scenario passes against live services; every component wired in Phases 1–5 has a passing non-blocked covering test; the baseline is green with no pre-existing failures; the audit's PARTIAL and INCOMPLETE rows are demonstrably promotable to `VERIFIED`.

---

## Traceability summary (R10.4)

Every phase above cites (a) the specific Gap Matrix rows by *Subsystem / Sub-Feature* it resolves, and (b) the specific `05`/`06` limitations by *finding + source file + severity*. Rolling the citations up against the Gap Matrix coverage check (30 rows: 5 VERIFIED, 13 INCOMPLETE, 7 PARTIAL, 5 NOT_IMPL):

| Gap Matrix cohort | Count | Resolving phase(s) |
|-------------------|-------|--------------------|
| ARO INCOMPLETE (lifecycle, adapters, exec mgr, sessions, runtime registry, task store) | 6 | Phase 2 (complete) → Phase 6 (verify) |
| ZAF INCOMPLETE (identity manager, quarantine) | 2 | Phase 3 |
| ZAF PARTIAL (action interceptor, PEP/PDP split, credential broker, audit) | 4 | Phase 3 (wire) → Phase 6 (verify) |
| OBS INCOMPLETE (infra metrics) | 1 | Phase 5 |
| OBS PARTIAL (classification, anomaly rules, loop detection) | 3 | Phase 5 (wire) → Phase 6 (verify) |
| OBS NOT_IMPL (cost) | 1 | Phase 5 |
| Infrastructure Orchestrator INCOMPLETE (remote exec, scheduler, reconciliation, connectors) | 4 | Phase 4 (harden) → Phase 6 (verify) |
| Agent Supervisor NOT_IMPL (roles, decomposition, delegation, governance inheritance) | 4 | Phase 5 |
| VERIFIED today (ARO registry; ZAF policy engine + approvals; OBS runtime + agent behavior) | 5 | Regression-guarded across all phases |
| Consolidation/security debt (not a Gap Matrix sub-feature) | — | Phase 1 (from `08` + `05`) |

The five sub-features already `VERIFIED` in the Gap Matrix require no new implementation; they are protected by the Phase 1 exit criterion (baseline must still pass) and re-confirmed in Phase 6.
