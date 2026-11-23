# Implementation Gap Analysis — ABF / AET / AGS

- **Scope:** Agent Behavioral Firewall (ABF), Agent Execution Trace (AET), Agent Governance Score (AGS)
- **Audit date:** 2026-11-21
- **Baseline commit:** `9cd1203` (branch `main`)
- **Method:** I read the source, migrations, routes and tests directly. I did not take the earlier audit documents (`docs/audit/09-gap-matrix.md`, `docs/audit/11-phase6-promotion-report.md`) on trust: every claim below was re-checked against the code. Where this report disagrees with them, it says so and gives the evidence.

## 0. Classification legend

| Value | Meaning |
|---|---|
| **EXISTING** | Implemented, reachable from the live process, and covered by a passing test. |
| **PARTIAL** | Some of the behaviour exists, but required parts are missing. |
| **MISSING** | Not implemented. |
| **UNVERIFIED** | Code exists but is not reachable from the running application, or a live-path test cannot demonstrate it. |

## 1. Test baseline (before any change)

Command: `python -m pytest -q` in the project `.venv` (WSL Ubuntu 24.04, Python 3.12.3), with no live PostgreSQL or Docker available.

```
660 passed, 17 failed, 10 skipped, 2 errors   (445 s)
```

All 17 failures and both errors are outside the ABF/AET/AGS scope:

- 15 Traefik Docker-API-version tests (`test_traefik_api_version_pin.py`, `test_traefik_api_version_pbt.py`, `test_traefik_docker_api_version*.py`, `test_traefik_api_version_preservation.py`, `test_traefik_compose_shape.py`). These are by-design bug-condition tests, already documented in `docs/audit/07-test-coverage-report.md`.
- `tests/test_development_secret_fallback.py` (1) and `scripts/test_orchestrator.py` (1). Both depend on environment or configuration not present in the sandbox.
- `test_entry_point_consolidation.py` (2 errors). The WSGI app build needs environment or DB not present in the sandbox.

**Any new failure outside this list is a regression**, with one exception. `tests/test_phase4_ssh_secret_hygiene.py` is a flaky Hypothesis property test: its secret generator can produce a substring of the fixed log text (for example `succee` inside "SSH command succeeded"). Hypothesis then stores that example in `.hypothesis/` and replays it on every later run. It fails the same way on the unmodified baseline, so it is not a regression.

## 2. Architecture as actually found

| Area | Location | Notes |
|---|---|---|
| Flask app factory | `src/ControlPlanFlaskApp_postgres.py` (`create_app`), `wsgi.py` | Blueprints are registered at lines 112-132. The ARO/ZAF/OBS blueprints are `aro_runtime_bp`, `aro_agent_bp`, `aro_task_bp`, `zaf_governance_bp` and `obs_bp`. |
| DB access | `src/database_postgres.py` (`db_manager.execute_query`) | Raw SQL through psycopg2 with `%s` parameters and no ORM. Each call runs in its own transaction, with commit per call. |
| Migrations | `migration/*.sql`, applied by `database_postgres.py:620-650` | Idempotent SQL files listed in an ordered tuple and re-run at every start (`IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS`). **A new migration must be added to that tuple.** |
| Authn / tenancy | `src/authz.py` (`tenant_scoped`, `role_required`) | Roles are `viewer < operator < admin` (`tenant_members`). The tenant is resolved from the session plus `X-Tenant-Id`. Applied to every ARO/ZAF/OBS route. |
| Event backbone | `migration/add_agent_events.sql`, `src/aro/event_service.py`, `src/aro/events_repository.py` | One append-only `agent_events` table shared by ARO, ZAF and OBS. The application has no UPDATE or DELETE path. Redaction runs before persistence. `UNIQUE(tenant_id, event_id)` plus `ON CONFLICT DO NOTHING` makes event IDs idempotent. |
| ZAF PDP | `src/zaf/policy_engine.py` (pure), `src/zaf/governance_service.py` (`decide`), `src/zaf/policy_repository.py` | Deny takes precedence, the default is deny, and there is a fail-closed variant. Every decision is recorded in `governance_decisions` and emitted as a `governance.decision` event. |
| ZAF PEPs | `src/zaf/enforcement.py`, `src/zaf/wiring.py`, `src/zaf/mcp_gateway.py`, `src/zaf/infra_proxy.py` | Three seam callables (`pre_transition`, `egress`, `exec`), an MCP gateway and an OpenStack proxy. |
| Approvals | `migration/add_approvals.sql`, `src/zaf/approval_service.py` | Bound to `sha256(action, params)`. Has a TTL column. |
| Credentials | `src/zaf/credential_vault.py` | Fernet at rest, scoped tokens stored hashed with expiry, revocation cascades to tokens. |
| Containment | `src/zaf/governance_service.quarantine`, `src/aro/lifecycle_service.quarantine/release`, `src/zaf/response_service.py` | QUARANTINED state with an admin release route (`POST /api/v1/agents/{id}/release`). |
| OBS detection | `src/obs/anomaly_engine.py`, `signal_bundle.py`, `detection_pass.py`, `risk_scoring.py` | Deterministic detectors (loops, retries, suspicious processes, resources, out-of-scope, authz bursts) and explainable risk scoring from 0 to 100. |
| OBS cost | `src/obs/obs_cost.py`, `agent_cost_records` | Pure `compute_cost` with MEASURED/ESTIMATED/MIXED provenance. The rate card is in `conf/obs.ini` and has **no effective dates**. |
| Runtime telemetry | `src/runtime_monitor/*`, `src/obs/infra_metrics.py` | Docker-only (`docker ps/inspect/top` over SSH), plus a /proc or eBPF sampler. |
| Adapters | `src/aro/adapters/*` | Kiro ACP, SHAI CLI and HTTP-SSE, and MCP. They have an explicit `Capability` enum and a `get_capabilities()` method. |
| Isolation policy | `src/aro/execution_manager.py`, `src/execution_policy.py` | `--cap-drop ALL` and `no-new-privileges`. Privileged mode and docker.sock mounts are refused. Kata is used when requested. |
| MCP server (live) | `src/mcp_interface.py` (FastMCP, stdio) | The MCP server that agents actually use. |
| Frontend | `templates/dashboard.html` (Jinja + vanilla JS), `static/js/dashboard_functions.js` | The "Agent Management" section has sub-panels (dashboard, runtimes, instances, tasks, policies, MCP, approvals, observability, incidents). i18n uses `TRANSLATIONS` in `src/config_postgres.py` (EN and FR), **and the default language is `en`**. |

## 3. Critical findings that contradict earlier audit claims

These matter more than any single feature gap, because ABF/AET/AGS would otherwise be built on enforcement that is not actually in force.

| # | Finding | Evidence | Impact |
|---|---|---|---|
| F1 | **The ZAF seam enforcers are never wired into the live process.** `zaf.wiring.build_enforcers()` is referenced only in docstrings. | `grep -rn "build_enforcers(" src` finds only `wiring.py` itself. `src/routes/aro_agent_routes.py:47` builds a bare `LifecycleService()`, so the `pre_transition` seam is a no-op. | In production, lifecycle transitions, launches and task execution are **not** policy-checked. `docs/audit/11` marks this "VERIFIED (integrated)" based on unit tests that inject the enforcers themselves. |
| F2 | **No ARO task worker runs in the deployed system.** `AgentTaskWorker` is only constructed in tests. No systemd unit, script or compose service starts it (`systemd/` contains only `serverless-worker.service`). | `grep -rn "AgentTaskWorker(" src scripts systemd` returns nothing. | Tasks submitted with `POST /api/v1/agents/tasks` are queued and never executed. As a result, the OBS `DetectionPass` (run from the worker loop) also never runs live. |
| F3 | **The live MCP server bypasses ZAF entirely.** `src/mcp_interface.py` exposes `list_users`, `add_application`, `deploy_template(user_id=...)` and others with no authentication, no tenant, no PDP and no audit. `McpGateway` is never instantiated. | `grep -n "zaf\|governance\|tenant" src/mcp_interface.py` finds nothing relevant. | This is an ungoverned execution path, which conflicts with Rule 9 of the spec. |
| F4 | **Approvals are replayable, never expire in practice, and are not bound to agent or session.** `approval_service.is_authorized()` checks only `(tenant_id, params_hash, status='approved')`. It ignores `expires_at`, never consumes the approval, and does not check the agent identity or session. | `src/zaf/approval_service.py:163-175` | A single approval authorizes the same action for any agent in the tenant, any number of times, forever. This violates spec §4.6 rules 3 and 5. |
| F5 | **The `exec` seam writes a status the DB rejects.** On deny, the worker calls `repo.complete(..., "denied", ...)`, but the `agent_tasks.status` CHECK does not allow `'denied'`. | `src/aro/agent_worker.py` (exec seam) compared with `migration/add_aro_phase2.sql:588-590` | A policy deny would raise a DB error instead of recording a clean terminal state. |
| F6 | **Quarantine is not enforced on new work.** `POST /api/v1/agents/tasks` does not check agent status, and the PDP does not consult agent status. A `QUARANTINE` decision only results from an explicit policy rule. | `src/routes/aro_task_routes.py:submit_task`, `src/zaf/governance_service.decide` | A quarantined agent can still have tasks queued, and they would run if F2 were fixed. Quarantine also does not revoke the agent's credentials unless the caller passes their IDs. |
| F7 | **The UI live-activity view queries events by numeric agent id, but events store the identity string** (`agent://tenant/name`). | `static/js/dashboard_functions.js` (`connectAgent`) compared with `lifecycle_service._emit` | The per-agent live view is always empty. |
| F8 | **`migration/add_aro_phase2.sql` is never applied automatically** (found during Phase 2). It is listed as a manual step in `docs/GO_LIVE_CHECKLIST.md`, yet `task_repository` already selects its `lease_expires_at` / `heartbeat_at` columns. | `src/database_postgres.py` migration tuple compared with `src/aro/task_repository.py:87` | On a database where the manual step was skipped, every task query fails. |

**Status after Phase 2 (2026-11-21):**

| Finding | Status |
|---|---|
| F1 | Fixed for the lifecycle API. The live enforcer is wired in `aro_agent_routes._service()`. A platform baseline policy keeps today's lifecycle behaviour, and containment transitions are never gated. The exec enforcer is ready (`wiring.build_live_exec`) and goes live with the worker in Phase 3. |
| F2 | Open (Phase 3). |
| F3 | Fixed. Every MCP tool is governed: agent token, tenant scoping, ABF, PDP, approvals, audit. |
| F4 | Fixed. Approvals are single use, bound to agent and session, and expire. |
| F5 | Fixed. `'denied'` was added to the status CHECK, and the SSE stream now closes on `task.denied` / `task.timed_out`. |
| F6 | Fixed. Task submission is refused for quarantined agents, the PDP returns QUARANTINE from the agent's status, and acting tokens and scoped tokens are revoked. **Runtime stop on quarantine still needs an execution manager**, which the API path does not have yet. |
| F7 | Open (Phase 5). |
| F8 | Fixed. The migration is registered in the automatic chain. |

These are recorded as prerequisites in `docs/FEATURE_IMPLEMENTATION_PLAN.md`. F4, F5 and F6 fall naturally inside ABF Phase 2. F1, F2 and F3 are integration work that ABF enforcement depends on.

## 4. Capability-by-capability classification

### 4.1 Event foundation (shared by ABF / AET)

| Capability | Status | Evidence / files | Reuse recommendation |
|---|---|---|---|
| Normalized event store | PARTIAL | `agent_events` has `event_id`, tenant, `agent_id`, `execution_id`, type, source, `action` JSONB, decision, risk score, severity, `correlation_id` and `occurred_at`. It lacks trace ID, session ID, task ID, parent event, category, normalized action string, resource, outcome, duration and provenance. | **Extend `agent_events` additively.** Do not create separate `agent_behavior_events` or `agent_execution_events` tables. |
| Unique event ID / duplicate protection | EXISTING | `UNIQUE(tenant_id, event_id)` and `ON CONFLICT DO NOTHING` in `events_repository.append_event`, tested in `test_aro_events.py`. | Reuse. |
| UTC timestamps | EXISTING | `TIMESTAMPTZ`, and `build_event` defaults to `datetime.now(timezone.utc)`. | Reuse. |
| Secret redaction before persistence | PARTIAL | `event_service.redact` masks keys that look like secrets and values shaped like Bearer tokens, long hex/base64 strings or PEM blocks. It misses inline secrets in commands (`--password=x`, `export AWS_SECRET_ACCESS_KEY=x`, `mysql -pX`) and URL userinfo (`gitea_auth.redact_credential_url` exists but is not used here). | Extend `event_service` redaction and reuse `redact_credential_url`. |
| Correlation ID | PARTIAL | `correlation_id` exists. The worker sets `task-{task_ref}`, while other emitters default it to the event's own ID. | Keep it, and add trace, session, task and parent IDs. |
| Category taxonomy (PROCESS, SHELL, …) | MISSING | Free-form `event_type` strings only (`task.received`, `governance.decision`, …). | Add a `category` column plus a mapping from existing event types. |
| Authenticated ingestion from runtimes | MISSING | No endpoint accepts runtime-reported telemetry. `credential_vault` scoped tokens require a backing credential (`credential_id NOT NULL`). | Add a dedicated per-agent ingest token table, a new `POST /api/v1/telemetry/events` route, and identity bound from the token, never from the payload. |
| Forged-telemetry protection / provenance | MISSING | No distinction between events observed by the control plane and events reported by an agent. | Add an `ingest_source` column. Reserved event types (governance, approval, zaf, security) can only be emitted by the control plane. Runtime severity is computed server-side. |
| Replay / clock-skew protection | MISSING | n/a | Reject events outside a configurable skew window, and use idempotent `event_id`. |
| Pagination | PARTIAL | `list_events` caps results at 2000 rows but has no cursor. | Add keyset pagination on `(occurred_at, id)`. |
| Ingestion rate limiting / backpressure | MISSING | `mcp_gateway.RateLimiter` exists (in-process sliding window). | Reuse `RateLimiter`, and return 429 with `Retry-After` and batch-size limits. |

### 4.2 Agent Behavioral Firewall (ABF)

| Capability | Status | Evidence / files | Reuse recommendation |
|---|---|---|---|
| Policy decision (ALLOW/DENY/REQUIRE_APPROVAL/QUARANTINE) | EXISTING | `policy_engine.evaluate` and `governance_service.decide`, tested in `test_zaf_policy_engine.py`. | **ABF must call `governance_service.decide`** and must not build its own authorization logic. |
| RATE_LIMIT, REVOKE_PERMISSION, ALERT actions | MISSING | The PDP vocabulary has 4 values (DB CHECK on `governance_decisions` and `agent_events.decision`). | Model these as ABF *enforcement actions* derived from a PDP decision plus a rule. Avoid widening the PDP enum unless required. |
| Deny precedence / default deny / fail closed | EXISTING | `policy_engine` with `evaluate_fail_closed`. | Reuse. ABF must call it with `service_available=False` when its store is unreachable. |
| Deterministic behavioural rules | PARTIAL | `anomaly_engine` has repeated commands, excessive retries, suspicious processes, resource anomalies, out-of-scope actions and authz bursts. There are no rules for destructive SQL, privileged Docker, sensitive mounts, MCP call bursts, LLM token bursts or exfiltration indicators. Rules are hard-coded and not tenant-configurable. | Add an ABF rule catalogue (`agent_behavior_rules`, per tenant/agent, versioned) that delegates to the existing detectors where they match. |
| Facts vs inferred risk | MISSING | Anomalies store `evidence` strings only. | Add explicit `observed_facts[]` and `inference` fields to alerts. |
| Behavioural baselines | MISSING | `signal_bundle.WindowConfig` gives static thresholds only. | New `agent_baselines` table with rolling statistics. It must exclude denied actions and quarantined periods. |
| Alerts with rule ID, evidence, level, recommended action | PARTIAL | `agent_anomalies` has `rule_id`, severity, `risk_score`, `evidence` and `recommended_action`, but no confidence, no session or trace link, and no fact/inference split. | Extend `agent_anomalies` additively rather than creating `agent_behavior_alerts`. |
| Approvals bound to exact action/params | PARTIAL | `params_hash` binding exists. See **F4**: no expiry check, reusable, not bound to agent or session. | Fix `approval_service` by checking `expires_at`, binding agent identity and session, and consuming the approval on use. |
| Quarantine | PARTIAL | State and release route exist (`test_aro_lifecycle_release.py`). See **F6**: no block on task submission, PDP is unaware of it, credential and ingest-token revocation must be passed explicitly. Release is admin-only, which is good. | Add a quarantine check in the task submit route, the exec seam and the MCP gateway, plus automatic revocation of agent-bound credentials and tokens. |
| Runtime-specific containment adapters | PARTIAL | `governance_service._stop_or_isolate` handles Docker stop only, as a best effort. | Add a containment adapter contract with capability reporting. |
| Audit of every decision | EXISTING | `governance_decisions` plus `governance.decision` events, and `zaf.deny` events from seams. | Reuse. |
| Tamper-evident audit (hash chain) | MISSING | The repository is append-only, but nothing detects a direct DB modification. | Add a per-tenant hash chain on `agent_events` and a verifier. |
| MCP interception | UNVERIFIED | `McpGateway` is unit-tested (`test_zaf_mcp_gateway.py`) but unused. See **F3**. | Route `src/mcp_interface.py` tools through `McpGateway`. |
| Enforcement on lifecycle / launch / exec | UNVERIFIED | See **F1** and **F2**. | Wire `zaf.wiring.build_enforcers()` into `aro_agent_routes._service()` and the worker entrypoint. |

### 4.3 Agent Execution Trace (AET)

| Capability | Status | Evidence / files | Reuse recommendation |
|---|---|---|---|
| Trace metadata (trace, session, agent, tenant, task, runtime, start/end, status) | PARTIAL | `agent_tasks` has task, agent, tenant, `started_at`, `finished_at` and status. `agent_executions` has session ID, runtime handle and server. There is no trace entity linking them, and no rollup of decisions or costs. | New `agent_execution_traces` table as a thin index over existing rows. Events link through `trace_id`. |
| Hierarchical events (parent/child) | MISSING | No `parent_event_id`. | Event foundation, Phase 1. |
| Correlation service | PARTIAL | Only `correlation_id = task-{ref}` for worker events. | Phase 1 adds the keys, and Phase 3 adds the correlation logic. |
| OpenTelemetry-compatible IDs | MISSING | n/a | Accept W3C `traceparent` IDs on ingestion when present, and generate otherwise. |
| Instrumentation SDK / adapter interface | MISSING | No SDK. Adapters stream output but emit no structured tool or LLM telemetry. | New `src/obs/telemetry_sdk.py` with a bounded queue, using the Phase 1 ingestion endpoint. |
| LLM usage capture | MISSING | No adapter parses token usage. Kiro ACP and SHAI expose usage depending on version, and this is **unverified**. | Provider-neutral LLM event type. Use provider-reported usage only, never estimates presented as measured. |
| MCP execution telemetry | PARTIAL | `McpGateway._emit` records tool, decision and reason, but not duration, redacted arguments or session. It is also not live (F3). | Extend it when wiring the gateway. |
| Timeline API | PARTIAL | `GET /api/v1/observability/agents/{identity}/timeline` (flat, capped, no filters beyond agent). | New `/api/v1/traces*` routes. |
| Timeline UI | PARTIAL | A polling "live activity" panel exists, and is broken (F7). | Add an agent detail "Execution Traces" tab. |
| Forensic replay (no re-execution) | MISSING | n/a | Read-only reconstruction distinguishing requested, approved, executed and observed. |
| Resource and cost attribution | PARTIAL | `obs_cost.compute_cost` is pure and keeps provenance. `agent_cost_records` is keyed by agent and parent task only. There is no model or provider dimension, no pricing table with effective dates, and no "unknown" cost state (a missing rate becomes 0.0, **which would misrepresent the cost**). | Add `model_pricing` with effective dates. An unknown price must be stored as `NULL` or `unknown`, not 0. |
| Trace export | MISSING | n/a | JSON export, redacted according to the caller's role. |

### 4.4 Agent Governance Score (AGS)

| Capability | Status | Evidence / files | Reuse recommendation |
|---|---|---|---|
| Score engine 0–100, 7 weighted dimensions | MISSING | `risk_scoring` scores *actions*, not agent posture. | New pure `src/obs/governance_score.py`, deterministic and versioned. |
| Evidence collection | MISSING (inputs exist) | Inputs are available: `agents.permissions` and `agent_permissions` (wildcards), `agent_credentials` and `agent_scoped_tokens` (expiry, sharing), execution policy and runtime config (privileged, Kata), `governance_decisions` (denials), `security_incidents` (open or critical), `agent_events` (telemetry coverage), task `timeout_seconds` and resource limits. | An evidence collector that reads these and emits PASS/FAIL/UNKNOWN/NOT_APPLICABLE per check. |
| PASS / FAIL / UNKNOWN / N/A, coverage | MISSING | n/a | Part of the engine. |
| Critical overrides | MISSING | n/a | A separate `critical_status` field that is never folded into the number. |
| History, versioning, evidence references | MISSING | n/a | New tables `agent_governance_scores` and `agent_governance_evidence`. |
| Anti-gaming (agent-reported data) | MISSING | n/a | The engine counts only `ingest_source='control_plane'` evidence toward positive scoring. Runtime-reported telemetry may count toward coverage only, and is labelled as such. |

### 4.5 Platform-wide requirements

| Requirement | Status | Notes |
|---|---|---|
| Tenant isolation | EXISTING (API and data layer) | All ARO/ZAF/OBS SQL filters on `tenant_id`, and decorators enforce membership. New code must follow the same pattern. |
| Role-based authorization | EXISTING | `role_required`. |
| French default UI | PARTIAL | FR translations exist, but `get_language()` defaults to `en`. Changing the global default affects every existing page. The plan proposes a config flag rather than a silent switch. |
| Global governance dashboard | PARTIAL | The `amPanel-dashboard` cards (agents, metrics, approvals, incidents) exist. There is no score, coverage or cost trend. |
| Retention policies | MISSING | No retention job for `agent_events`. |
| Partitioning | N/A for now | The schema is designed for it (comment in `add_agent_events.sql`). The spec says not to partition until volume justifies it. |
| Performance benchmarks / SLOs | MISSING | No load tests exist. |

## 5. Summary

| Feature | EXISTING | PARTIAL | MISSING | UNVERIFIED |
|---|---:|---:|---:|---:|
| Event foundation | 2 | 4 | 5 | 0 |
| ABF | 3 | 5 | 4 | 2 |
| AET | 0 | 6 | 6 | 0 |
| AGS | 0 | 0 | 6 | 0 |

**What can be reused directly:** the PDP and governance decision recording, the approval table and hash binding, the credential vault and revocation, the lifecycle QUARANTINED/release states, the anomaly detectors and risk scoring, the cost computation with provenance, the append-only event store with idempotent IDs, the tenant/role decorators, adapter capability reporting, and the execution-policy isolation checks.

**What must not be duplicated:** a second event table, a second authorization engine, a second approvals table, or a second anomaly table.

**What is genuinely new:** an authenticated ingestion path with provenance, the behavioural rule catalogue and baselines, the trace index and timeline, the pricing table, the governance score engine and history, and the audit hash chain.

**What must be fixed before ABF can claim enforcement:** F1–F6.
