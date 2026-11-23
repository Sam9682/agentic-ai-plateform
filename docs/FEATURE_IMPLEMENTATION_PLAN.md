# Feature Implementation Plan — ABF / AET / AGS

- **Input:** `docs/IMPLEMENTATION_GAP_ANALYSIS.md` (2026-11-21)
- **Approach:** incremental and additive. Each phase ends with its own tests, a full-suite regression run against the recorded baseline (660 passed / 17 known failures / 2 known errors), and a progress report.
- **Conventions:** raw SQL through `db_manager`, idempotent migrations appended to the ARO/ZAF tuple in `src/database_postgres.py`, `@tenant_scoped` / `@role_required` on every route, pure core logic with injected collaborators so it can be unit-tested without PostgreSQL, and English code with FR/EN UI strings in `TRANSLATIONS`.

## Guiding decisions

| Decision | Rationale |
|---|---|
| **Extend `agent_events`** for behavioural and execution events, rather than creating `agent_behavior_events` or `agent_execution_events`. | One audit backbone already exists, is append-only and idempotent, and is consumed by OBS routes and the UI. Two parallel stores would break correlation. |
| **Extend `agent_anomalies`** for ABF alerts, rather than creating `agent_behavior_alerts`. | It already carries rule ID, severity, evidence, recommended action and enforcement status, and OBS routes already read it. |
| **Extend `approval_requests`** for agent/session binding and single use, rather than creating `agent_approvals`. | The `params_hash` binding and admin routes already exist. |
| **ABF decides only through `governance_service.decide`.** | Spec §3.1 and §4.6. ABF rules produce *context* (risk level, rule hits) and enforcement actions. The PDP remains the single authority. |
| **RATE_LIMIT / REVOKE_PERMISSION / ALERT are ABF enforcement actions, not new PDP decisions.** | Keeps the PDP vocabulary and its DB CHECK constraints stable. These actions are executed after an ALLOW, DENY or QUARANTINE decision. |
| **New tables only where nothing equivalent exists:** `agent_ingest_tokens`, `agent_behavior_rules`, `agent_baselines`, `agent_execution_traces`, `model_pricing`, `agent_governance_scores`, `agent_governance_evidence`. | Gap analysis §5. |
| **Provenance on every event** (`ingest_source`: `control_plane` or `runtime_reported`). | Prevents forged telemetry from improving a score (spec §10). AGS counts positive evidence only from the control plane. |
| **Unknown is never 0.** | A missing price gives a `NULL` cost. Missing evidence is reported as UNKNOWN, and coverage is shown separately. |
| **French default UI** behind a config flag (`DEFAULT_LANGUAGE`, default `fr` for new installs), with the existing session override kept. | Switching every existing page silently could surprise current users. To be confirmed with the product owner. |

## Prerequisites from the gap analysis (findings F1–F8)

| ID | Fix | Phase |
|---|---|---|
| F5 | Add `'denied'` to `agent_tasks.status` CHECK (additive constraint swap, same pattern as `add_aro_phase2.sql`) | 2 |
| F4 | Approvals: enforce `expires_at`, bind to agent identity and session, consume on use, use `SELECT … FOR UPDATE` against races | 2 |
| F6 | Quarantine: block task submission, add a PDP context check (agent status → QUARANTINE), auto-revoke agent-bound credentials and ingest tokens | 2 |
| F1 | Wire `zaf.wiring.build_enforcers()` into `aro_agent_routes._service()` (and into the worker entrypoint once it exists) | 2 |
| F3 | Route `src/mcp_interface.py` tools through `McpGateway` with an agent ingest-token identity. Tools without an authenticated agent context are refused for mutating operations | 2 |
| F2 | Add a worker entrypoint (`python -m src.aro.worker_main`) and a systemd unit, wired with enforcers, `DetectionPass` and `ResponseService` | 3 (execution has to run before it can be traced) |
| F7 | UI live view queries by agent identity | 5 |
| F8 | Register `add_aro_phase2.sql` in the automatic migration chain | 2 (done) |

---

## Phase 1 — Event foundation

**Goal:** normalized, correlated, redacted, provenance-tagged events, plus an authenticated ingestion path for runtimes that cannot be observed through Docker. This covers Kiro, SHAI, custom runtimes and remote-LLM agents.

**Schema** (`migration/add_event_foundation.sql`, additive and idempotent):
- `agent_events` gains `trace_id`, `session_id`, `task_id`, `parent_event_id`, `category`, `normalized_action`, `resource`, `outcome`, `duration_ms`, `ingest_source` (default `control_plane`) and `ingest_principal`, with CHECK constraints on `category`, `outcome` and `ingest_source`.
- New indexes: `(tenant_id, trace_id)`, `(tenant_id, session_id, occurred_at)`, `(tenant_id, severity, occurred_at)` and `(tenant_id, agent_id, category, occurred_at)`.
- New `agent_ingest_tokens` table (per agent, hashed, expiring, revocable). A dedicated table is justified because `agent_scoped_tokens.credential_id` is `NOT NULL` and represents a delegated infrastructure secret, while a telemetry token has no backing secret.

**Code:**
- `src/aro/event_service.py`: optional correlation and normalization fields in `build_event`. The legacy canonical shape is unchanged when these fields are not supplied. Adds inline redaction for command-line secrets, `KEY=VALUE` secret assignments, `Authorization:` headers and URL userinfo, plus a `category_for_event_type()` mapping for control-plane events.
- `src/aro/events_repository.py`: persists the new columns (deriving the category for legacy emitters), returns an `inserted` flag (duplicate detection), and adds `query_events()` with keyset pagination and trace, session, task and category filters.
- `src/obs/behavior_events.py` (pure): the category taxonomy, runtime-submittable categories (SECURITY and RUNTIME are reserved for the control plane), field validation and size limits, a clock-skew window, event-ID namespacing, action normalization, and server-side risk classification through `risk_scoring`. The agent-supplied severity, risk or decision is never trusted.
- `src/obs/ingest_tokens.py`: issue (plaintext returned once), verify, revoke, list, revoke-all-for-agent.
- `src/obs/telemetry_ingest.py`: an injectable ingestion service. Identity and tenant come from the token. It checks per-token rate limits (reusing `mcp_gateway.RateLimiter`), a batch cap, per-item accept, duplicate or reject results, and verifies task ownership.
- `src/routes/telemetry_routes.py`:
  - `POST /api/v1/telemetry/events` (bearer ingest token, no session)
  - `POST|GET /api/v1/agents/{id}/telemetry-tokens` (admin issues, operator lists)
  - `POST /api/v1/agents/{id}/telemetry-tokens/{token_id}/revoke` (admin)
  - `GET /api/v1/agents/{id}/behavior` (paginated, filterable, tenant-scoped)
- ARO integration: worker task events carry `task_id` and `trace_id`.

**Tests:** redaction, validation, provenance, identity binding, cross-agent task-ID rejection, duplicates, rate limit and batch cap, token expiry and revocation, tenant isolation and IDOR on the routes, repository SQL shape and pagination bounds, and migration idempotency (validated against a real PostgreSQL where one is available).

**Done when:** all Phase 1 tests pass and there are no regressions against the baseline.

### Phase 1 status — implemented 2026-11-21

| Item | Result |
|---|---|
| Files created | `migration/add_event_foundation.sql`, `src/obs/behavior_events.py`, `src/obs/ingest_tokens.py`, `src/obs/telemetry_ingest.py`, `src/routes/telemetry_routes.py`, `tests/test_event_foundation_{schema,ingest,repository,routes}.py` |
| Files modified | `src/aro/event_service.py` (optional normalized fields, inline redaction, category mapping), `src/aro/events_repository.py` (new columns, `inserted` flag, `query_events`), `src/aro/agent_worker.py` (task events carry `task_id`/`trace_id`), `src/aro/task_repository.py` (`get_task_agent_by_ref`), `src/database_postgres.py` (migration registered), `src/ControlPlanFlaskApp_postgres.py` (blueprint registered) |
| Reused | `agent_events` and its idempotent append, `event_service` redaction, `risk_scoring.score`, `mcp_gateway.RateLimiter`, the `authz` decorators, `agent_repository.get_agent` |
| DB changes | 11 nullable or defaulted columns, 4 CHECKs and 4 indexes on `agent_events`, and the new `agent_ingest_tokens` table. All additive and idempotent. |
| Security | Ingestion identity is bound to the token. Event types are server-assigned, SECURITY/RUNTIME categories are reserved, and agent severity is ignored. Provenance is tagged on every event, cross-agent `task_id` is rejected, client IDs are namespaced, and stale or future events are rejected. Size, depth and batch caps apply, plus a per-token rate limit. Tokens are stored hashed with expiry and revocation. Redaction is linear-time on adversarial input (a ReDoS issue was found and fixed during the phase). |
| Tests | 88 new tests, all passing. Full suite: 746 passed. Failures are the 17 baseline failures plus the 2 cases of the pre-existing flaky Hypothesis test `test_phase4_ssh_secret_hygiene.py` (it fails the same way without these changes), with no new regressions. |
| Known limitations | (1) **The migration has not been run against a live PostgreSQL** (none is available in the dev sandbox). It is validated statically only, and must be checked on staging before release. (2) The ingestion rate limiter is per process, not global. (3) `session_id` on runtime events is agent-asserted (provenance-tagged) until Phase 3 binds sessions to `agent_executions`. (4) No component issues ingest tokens to runtimes automatically yet. An admin issues them through the API, and egress injection comes in Phase 3. (5) Inline redaction covers common shapes (`--password`, `KEY=`, `Authorization:`, URL userinfo). Tool-specific forms such as `mysql -pSECRET` are not detected. |
| Remaining | Phases 2–5, including fixes F1–F7. |

## Phase 2 — Agent Behavioral Firewall

- Schema (`add_abf.sql`): `agent_behavior_rules` (tenant- or agent-scoped, versioned, enabled, category, matcher, threshold, window, risk level, enforcement action); `agent_baselines`; `agent_anomalies` gains `trace_id`, `observed_facts`, `inference`, `confidence_label`, `rule_version`; `approval_requests` gains `agent_identity` binding enforcement, `session_id`, `consumed_at`, `consumed_by_event`; the `agent_tasks` status CHECK accepts `denied` (F5); `agent_events` gains a hash chain (`chain_seq`, `prev_hash`, `record_hash`).
- `src/abf/rules.py` (pure): built-in deterministic rule catalogue. It covers destructive SQL (`DROP DATABASE/TABLE`, `TRUNCATE`, unscoped `DELETE`/`UPDATE`), destructive filesystem operations (`rm -rf /`, `mkfs`, `dd of=/dev/…`, `chmod -R 777 /`), privileged Docker (`--privileged`, `docker.sock`, host `/` or `/etc` mounts, `--pid=host`, `--net=host`), security config changes (`iptables -F`, `setenforce 0`, `ufw disable`), secret access (`/proc/*/environ`, `printenv`, `.aws/credentials`, `id_rsa`), cross-tenant resource references, unapproved MCP tools, repeated identical commands, process, MCP or LLM bursts, repeated API failures, resource spikes, and exfiltration sequences (sensitive read followed by a large or new outbound transfer). Every hit returns observed facts and an inference separately.
- `src/abf/baseline.py` (pure): rolling mean and standard deviation per (agent, metric), excluding denied, quarantined and runtime-reported-only windows, with manual reset and explanations.
- `src/abf/firewall.py`: `inspect(event)` for detection and `guard(action_request)` for pre-execution enforcement. Rule hits raise the PDP context (`risk_level`, `abf_rules`), then **`governance_service.decide`** decides. The firewall then applies ALLOW, DENY, REQUIRE_APPROVAL (a session-bound approval), RATE_LIMIT, REVOKE_PERMISSION, QUARANTINE or ALERT. It fails closed for sensitive categories when the PDP or its store is unavailable, while telemetry continues.
- Fixes F1, F3, F4, F5 and F6. Adds a containment adapter contract (`docker`, `kata`, `noop` with explicit capabilities). Adds an audit chain verifier (`GET /api/v1/governance/audit/verify`).
- API: `/api/v1/agents/{id}/alerts|rules|quarantine|release`, `/api/v1/approvals*` (an alias over the existing `/api/v1/governance/approvals*`, with no duplicated logic).
- Tests: all of spec §12.1 plus §12.5 IDOR, approval bypass and replay, unauthorized release, and malicious tool arguments.

### Phase 2 status — implemented 2026-11-21

| Item | Result |
|---|---|
| Files created | `migration/add_abf.sql`, `migration/add_audit_chain.sql`, `src/abf/{__init__,rules,baseline,firewall,repository,audit_chain,containment,mcp_governance}.py`, `src/zaf/baseline_policy.py`, `src/routes/abf_routes.py`, `docs/AGENT_BEHAVIORAL_FIREWALL.md`, `tests/test_abf_{rules,enforcement,routes,mcp_and_audit_chain}.py` |
| Files modified | `src/zaf/policy_engine.py` (agent status), `src/zaf/governance_service.py` (baseline, status lookup, fail closed, allow-path audit), `src/zaf/policy_repository.py` (`agent_status`), `src/zaf/approval_service.py` (F4), `src/zaf/enforcement.py` and `src/zaf/wiring.py` (consume approvals, live lifecycle and exec enforcers, `quarantine_agent`), `src/zaf/mcp_gateway.py` (bound approval consumer, deny audit), `src/zaf/credential_vault.py` (`revoke_agent_scoped_tokens`), `src/obs/ingest_tokens.py` (scopes), `src/obs/telemetry_ingest.py` and `src/routes/telemetry_routes.py` (detection and sealing hooks, scoped issuance), `src/routes/aro_agent_routes.py` (F1, 403), `src/routes/aro_task_routes.py` (F6, terminal events), `src/mcp_interface.py` (F3), `migration/add_aro_phase2.sql` (`'denied'`, F5), `src/database_postgres.py` (F8 plus two migrations), `src/ControlPlanFlaskApp_postgres.py`, `tests/test_zaf_approvals.py` (stub updated for the intentionally changed approval SQL; assertions unchanged) |
| Reused | PDP and `governance_service.decide` (the only decision authority), `approval_service`, `McpGateway` and `RateLimiter`, `governance_service.quarantine`, `LifecycleService`, `credential_vault`, `agent_anomalies` (alerts), `agent_events` (audit), Phase 1 ingest tokens and `query_events` |
| DB changes | New tables `agent_behavior_rules` and `agent_baselines`. New columns: 10 on `agent_anomalies`, 3 on `approval_requests`, 3 on `agent_events` (chain). One update-guard trigger on `agent_events`. `'denied'` added to the `agent_tasks` status CHECK. All additive and idempotent. |
| Security | ABF decides only through the PDP and can only tighten it. Fail closed on PDP or store failure. An ALLOW that cannot be audited is not returned. Single-use bound approvals with a race-free consume. `agent_status` is control-plane only and cannot be supplied by callers. Containment is never blockable by policy. Quarantine revokes acting tokens and keeps telemetry. MCP tools are authenticated per call. Rule customisation is data only, with no patterns or code. Rule internals are not returned to agents, and detection results are not returned to runtimes. Rules are linear-time on adversarial input. |
| Tests | 167 new tests (69 + 46 + 35 + 17), all passing. Full suite: 913 passed. The 19 failures and 2 errors are the same set as Phase 1 (17 baseline failures plus 2 flaky Hypothesis cases, and the 2 baseline errors), so there are no regressions. |
| Behaviour changes (approved 2026-11-21) | MCP clients need an agent token with `mcp:invoke`, and mutating tools need a grant. Existing approvals are single use and must be used before `expires_at`. Lifecycle transitions now honour tenant DENY / REQUIRE_APPROVAL rules and quarantine status. |
| Known limitations | (1) **The migrations have not been run against live PostgreSQL**, including the PL/pgSQL trigger. Validate on staging (`docs/AGENT_BEHAVIORAL_FIREWALL.md` §10). (2) RATE_LIMIT cooldowns and the firewall-check limiter are per process. (3) Quarantine from the API does not stop the runtime (no execution manager on that path); the containment adapters are implemented but not yet wired to a live executor. (4) The task worker is still not running (F2), so the exec enforcer is not exercised live. (5) The audit chain is tamper-evident, not immutable (superuser rewrite, DELETE, tail truncation without an external head copy). (6) `docker` network isolation disconnects only the default bridge network. (7) `guard` sees only actions routed through it. |
| Remaining | Phase 3 (F2, AET), Phase 4 (AGS), Phase 5 (UI, F7, French default, dashboard, perf). |

## Phase 3 — Agent Execution Trace

- Worker entrypoint and systemd unit (F2).
- Schema: `agent_execution_traces` (trace, session, task, agent, runtime, start and end, status, rollups); `model_pricing` (provider, model, input and output price, currency, `effective_from` and `effective_to`); `agent_cost_records` gains `trace_id`, `provider`, `model`, `input_tokens`, `output_tokens`, and a nullable `estimated_cost` meaning "unknown".
- `src/aet/correlation.py` (parent/child tree, out-of-order tolerant), `src/aet/trace_service.py` (open and close traces from task lifecycle, rollups), `src/aet/replay.py` (read-only reconstruction labelling requested, approved, executed and observed actions; it never re-executes anything).
- `src/obs/telemetry_sdk.py` (`AgentTelemetryAdapter`): bounded queue, background flush, retry with backoff, explicit drop counters, never blocks the agent. Accepts a W3C `traceparent`.
- LLM telemetry: a provider-neutral `LLM` event (provider, model, request ID, usage, latency, error), recorded only from provider-reported usage. Adapter usage parsing is added only where the runtime actually exposes it, and each adapter reports this through its capabilities.
- MCP gateway telemetry: duration, redacted arguments, session, result status.
- API: `/api/v1/traces`, `/traces/{id}`, `/traces/{id}/events`, `/sessions/{id}/trace`, `/traces/{id}/export`.

## Phase 4 — Agent Governance Score

- Schema: `agent_governance_scores` (score, max, coverage, assessment, critical status, algorithm version, weights, timestamp); `agent_governance_evidence` (dimension, check ID, status PASS/FAIL/UNKNOWN/NOT_APPLICABLE, points, explanation, evidence references).
- `src/ags/engine.py` (pure, versioned `ags-1.0.0`): 7 dimensions with configurable weights in `conf/governance_score.yaml`. Coverage is computed separately, unknown counts as zero points and is shown explicitly, and critical overrides produce a separate `critical_status`.
- `src/ags/evidence.py`: collectors over permissions, credentials and tokens, effective runtime configuration (not product names), decisions, incidents, telemetry coverage and resource limits. Positive behavioural evidence is counted from control-plane provenance only.
- Recalculation triggers: on permission or runtime change, incidents, new evidence, or an admin request. Recalculation is debounced and idempotent.
- API: `/api/v1/agents/{id}/governance`, `/history`, `/recalculate`, `/api/v1/governance/overview`.

## Phase 5 — Dashboard and integration

- Agent detail view with three tabs (Sécurité comportementale, Traces d'exécution, Score de gouvernance), a global governance dashboard, drill-down to evidence, and explicit confirmation dialogs for quarantine, release and approval.
- Fix F7, add FR/EN translations and the `DEFAULT_LANGUAGE` flag.
- Documentation: `docs/AGENT_BEHAVIORAL_FIREWALL.md`, `docs/AGENT_EXECUTION_TRACE.md`, `docs/AGENT_GOVERNANCE_SCORE.md`, the threat model, deployment and rollback, demo scenarios, and updated installation and configuration guides.
- Performance harness: ingestion rate, concurrent agents, large traces, and PDP latency. SLOs to be set from the measurements.

## Rollback strategy (all phases)

Every migration is additive (new nullable or defaulted columns, new tables, widened CHECKs). Rolling back the application code leaves the schema compatible with the previous release. New routes are new blueprints, so unregistering a blueprint disables a feature without touching others. A down-migration script per phase is provided for operators who must remove the schema objects. It drops only the new objects and never touches pre-existing columns or data.
