# Agent Behavioral Firewall (ABF)

- **Status:** Phase 2, implemented 2026-11-21
- **Code:** `src/abf/`
- **API:** `src/routes/abf_routes.py`
- **Schema:** `migration/add_abf.sql` and `migration/add_audit_chain.sql`

ABF watches what agents do, detects dangerous or abnormal behaviour with deterministic rules, and enforces containment. It does not replace ZAF: **every enforcement decision is taken by the ZAF policy decision point (`governance_service.decide`).** ABF supplies risk context (rule hits and a risk level) and runs the containment actions.

## 1. What is protected, and what is not

| Path | Enforcement | Notes |
|---|---|---|
| Agent lifecycle API (`/api/v1/agents/{id}/start`, `ready`, …) | **Before execution**, via the ZAF pre-transition seam | Wired live in Phase 2 (finding F1). A policy deny returns 403. |
| Platform MCP server (`src/mcp_interface.py`) | **Before execution**, for every tool | Requires an agent token. Tenant scoping, ABF rules, PDP, approvals and audit (finding F3). |
| Runtimes that call `POST /api/v1/firewall/check` | **Before execution** | Effective only if the runtime asks before acting (a cooperative runtime or SDK). |
| Telemetry reported by runtimes (`POST /api/v1/telemetry/events`) | **After the fact**: alerts and containment | Cannot undo an action already performed. |
| Task execution (`AgentTaskWorker` exec seam) | Enforcer ready (`wiring.build_live_exec`) | **Not live yet:** no worker process is started (finding F2). Wiring is part of Phase 3. |
| Actions an uncooperative runtime performs without asking or reporting | **Not visible** | Requires runtime-level isolation (containment adapters, network egress controls). |

## 2. Decision flow (`guard`)

1. The agent's identity and tenant come from its token or from the control-plane agent row, never from the request body.
2. Deterministic single-action rules evaluate the action as inert text (command, SQL, tool arguments, resource).
3. Rule hits set the PDP context:
   - `risk_level` is the highest hit.
   - A rule that requests DENY raises the risk to `critical`, and one that requests approval raises it to `high`.
   - `abf_rules` lists the hits.
4. `governance_service.decide` evaluates, in order:
   - the tenant's policies;
   - the platform baseline policy;
   - the agent's permissions;
   - the agent's control-plane status (QUARANTINED → QUARANTINE; TERMINATED or unknown → DENY).
5. **ABF can only tighten.** The final decision is the stricter of the PDP decision and the rule floor.
6. REQUIRE_APPROVAL is satisfied only by an approval that is all of the following:
   - approved by an admin;
   - unexpired and not yet used;
   - bound to the exact parameters, the same agent and the same session (when one was given).

   It is consumed atomically (single use). Otherwise a bound approval request is created and the call returns 202.
7. Per-hit enforcement actions are applied, and an `abf.guard` audit event is emitted.
8. **Fail closed:** if the PDP or its store is unavailable, the decision is DENY.

### Platform baseline policy (`src/zaf/baseline_policy.py`, version `platform-baseline-2026.11.1`)

The PDP is default-deny. Before Phase 2 the lifecycle seam was an inert no-op, so turning on real enforcement without a baseline would have refused every lifecycle operation for tenants that have no policy yet. The baseline keeps today's behaviour and makes risk, quarantine and tenant rules effective:

| Rule | Decision |
|---|---|
| any action with ABF `risk_level` critical | DENY |
| any action with ABF `risk_level` high | REQUIRE_APPROVAL |
| `agent.transition.*` (lifecycle; already role-gated by the API) | ALLOW |
| `abf.*` (firewall checks) | ALLOW |
| `mcp.platform.read.*` | ALLOW |

How the baseline combines with tenant rules:

- A tenant DENY rule always wins.
- A tenant REQUIRE_APPROVAL rule beats a baseline ALLOW.
- `ZAF_PLATFORM_BASELINE=off` disables the baseline (strict default deny).
- The baseline version is returned with every decision.

**Never gated:** containment, stop and health transitions (→ QUARANTINED, TERMINATED, STOPPING, STOPPED, FAILED, UNHEALTHY), health recovery, and release. Blocking them would weaken containment. Release is authorized by the admin-only route instead.

## 3. Detection (`inspect`)

`inspect` runs after each telemetry batch is persisted. Detection errors never reject telemetry, and detection results are never returned to the agent.

- **Single-action rules** run on every new event. Alerts are deduplicated per (rule, event), so replaying telemetry does not re-alert.
- **Window rules** run over the agent's last 5 minutes. They are deduplicated per rule window.
- **Baseline deviation:** the current window is compared with stored baselines.

### Built-in rules (`abf-rules-1.0.0`)

| Rule | Risk | Default action |
|---|---|---|
| `abf.sql.drop_database` (DROP DATABASE / SCHEMA) | critical | QUARANTINE |
| `abf.sql.drop_table`, `abf.sql.truncate`, `abf.sql.unscoped_delete`, `abf.sql.unscoped_update` | high | ALERT |
| `abf.fs.recursive_delete_system_path`, `abf.fs.mkfs`, `abf.fs.dd_to_device` | critical | QUARANTINE |
| `abf.fs.world_writable_root` | high | ALERT |
| `abf.container.privileged` (`--privileged`, host `/` or `/etc` mounts, host pid/net, `cap-add all`/`sys_admin`) | high | REQUIRE_APPROVAL |
| `abf.container.docker_socket` | high | REQUIRE_APPROVAL |
| `abf.security.config_disable` (`iptables -F`, `ufw disable`, `setenforce 0`, stopping auditd, …) | high | ALERT |
| `abf.secret.access` (`/proc/*/environ`, `printenv`, `.aws/credentials`, `id_rsa`, `/etc/shadow`, …) | high | ALERT |
| `abf.tenant.cross_reference` (`agent://<other-tenant>/`) | high | DENY |
| `abf.mcp.unapproved_tool` (when an approved list is supplied) | medium | ALERT |
| `abf.burst.process` (≥ 60 per min), `abf.burst.mcp` (≥ 60 per min), `abf.burst.llm` (≥ 30 per min) | medium | RATE_LIMIT |
| `abf.repeat.identical_action` (≥ 10 identical in 60 s) | medium | RATE_LIMIT |
| `abf.failures.repeated` (≥ 10 failures in 120 s) | medium | ALERT |
| `abf.resource.spike` (≥ 3 samples at ≥ 95 % CPU or memory in 5 min) | medium | ALERT |
| `abf.exfiltration.sequence` (secret read, then a new destination or ≥ 1 MB out within 5 min) | critical | QUARANTINE |
| `abf.baseline.<metric>` (z ≥ 3 and ≥ 5 events above the mean) | low or medium | ALERT |

Every alert stores, in `agent_anomalies`:

- `observed_facts`: what was literally seen.
- `inference`: what the platform concludes.
- `confidence_label`: for example, exfiltration is `medium`, because it is an inference.
- `rule_version` and `enforcement_status`.

`enforcement_status` takes one of these values:

- `alerted`
- `applied`
- `not_enforceable_post_hoc` (DENY or approval requested after the fact)
- `not_configured`
- `failed`

### Enforcement actions

| Action | Effect |
|---|---|
| ALERT | Alert only. |
| DENY / REQUIRE_APPROVAL | Before execution only. Recorded as not enforceable when detected after the fact. |
| RATE_LIMIT | The agent's firewall checks are refused (429) for 60 s. **Per API process** (in-memory). |
| REVOKE_PERMISSION | Revokes the agent's MCP and firewall tokens. |
| QUARANTINE | See §5. |

### Tenant customisation (`agent_behavior_rules`)

Rules are data only. No pattern, regex or code is accepted.

- `override`: disables a built-in rule, or changes its risk level or enforcement action, for the tenant or for one agent. An agent row wins over a tenant row.
- `threshold`: counts events in a window, using a matcher on `category`, `action_glob`, `outcome` and `resource_prefix`.
- Every change bumps the rule version and is audited.

### Baselines (`agent_baselines`)

- **What is measured:** per (agent, metric) over 5-minute windows, across the last 7 days, or since the last reset if that is more recent.
- **Metrics:** `events_total`, `shell_events`, `network_events`, `mcp_events`, `llm_events`, `failures`.
- **Excluded windows:** any window containing a deny, a quarantine or a DENIED outcome, so that incidents never become "normal".
- **Confidence:**
  - `insufficient` with fewer than 12 windows; no deviation is reported.
  - `low` when more than 90 % of events are self-reported, because an agent could inflate its own baseline.
- **Limit:** baseline deviation never exceeds `medium` risk and never triggers containment on its own.
- **Refresh:** `POST /agents/{id}/baseline/refresh` (operator), or reset (admin).

## 4. Approvals (finding F4 fixed)

- **Before Phase 2:** approvals ignored `expires_at`, could be reused without limit, and were not bound to an agent.
- **Single use and binding:** an approval is bound to the exact action and parameters (hash), the agent identity and the session. It is consumed atomically by one `UPDATE … WHERE id = (SELECT … FOR UPDATE SKIP LOCKED)`. Concurrent replays get nothing.
- **Expiry:** expired pending approvals are marked `expired` and cannot be approved.
- **One window:** the approval's `expires_at` (default 1 h from the request) bounds both the decision and the use.
- **API:** `/api/v1/approvals*` aliases the existing `/api/v1/governance/approvals*` views, with the same admin requirement for approve and reject.

## 5. Quarantine (finding F6 fixed)

To quarantine an agent:

- **Manually:** `POST /api/v1/agents/{id}/quarantine` (operator).
- **Automatically:** a rule whose enforcement action is QUARANTINE.

Effects:

1. **Status.** The agent moves to QUARANTINED. This transition is never blocked by policy.
2. **Runtime.** It is stopped or isolated when an execution manager is wired. **Today the API path has none, so the runtime keeps running** unless the containment adapter or an operator stops it.
3. **Scoped tokens.** The agent's short-lived scoped tokens are revoked.
4. **Agent tokens.** The agent's MCP and firewall tokens are revoked. **Telemetry tokens are kept**, so the contained runtime stays observable; its events carry `agent_status_at_ingest`.
5. **Base credentials.** The agent's base credentials are revoked only with `revoke_credentials: true`. This is irreversible: the credentials must be rotated.
6. **New tasks.** Task submission is refused (409).
7. **Every gated action.** The PDP returns QUARANTINE for the agent's lifecycle transitions, firewall checks, MCP tools and task execution, independently of steps 2–5.

Release: `POST /api/v1/agents/{id}/release` (**admin only**). Revoked tokens are not restored; issue new ones.

### Containment adapters (`src/abf/containment.py`)

| Adapter | Capabilities |
|---|---|
| `noop` | None. It reports `supported: false` and never pretends. |
| `docker` | `stop`, `pause`, `network_isolate`. Disconnects from the default `bridge` network only; user-defined networks are not discovered. |
| `kata` | `stop`, `network_isolate` |

Commands are passed as argv lists, and container references are validated.

## 6. Audit chain (tamper evidence, not immutability)

`agent_events` gains `chain_seq`, `prev_hash` and `record_hash`:

- A sealing pass, serialized per tenant by an advisory lock, links events: `sha256(prev_hash + canonical event)`.
- Sealing runs after telemetry batches, after firewall checks, and on `POST /api/v1/governance/audit/seal` (admin).
- A trigger rejects any UPDATE that changes event content, and any UPDATE of a sealed row.
- `GET /api/v1/governance/audit/verify` (admin) recomputes the chain. It reports the first gap, broken link or modified record, plus the head hash.

**Residual risks** (stated plainly):

- A database superuser can disable the trigger and rewrite the chain consistently.
- DELETE is not blocked, because tenant deletion cascades. Deleting a sealed row is detected as a gap.
- Truncating the tail is detected only by comparing the head hash with an externally stored copy.
- Export and anchor the head hash periodically if you need that guarantee.

## 7. Agent tokens and scopes

Tokens are issued with `POST /api/v1/agents/{id}/telemetry-tokens` and body `{"scopes": [...], "ttl_seconds": N}` (admin):

| Scope | Allows |
|---|---|
| `telemetry:ingest` (default) | `POST /api/v1/telemetry/events` |
| `firewall:check` | `POST /api/v1/firewall/check` |
| `mcp:invoke` | Platform MCP tools (set `AGENTIC_MCP_TOKEN` in the MCP client env) |

A quarantined agent can only be issued telemetry tokens.

## 8. MCP server governance (finding F3 fixed)

| Tool | Canonical action | Baseline |
|---|---|---|
| `list_applications`, `list_users` (tenant members only), `ps`, `logs` | `mcp.platform.read.*` | ALLOW |
| `add_application` | `mcp.platform.catalog.add_application` | needs a grant |
| `deploy_template`, `start`, `stop`, `backup`, `restore`, `modify_code` | `mcp.platform.app.*` | needs a grant |
| `agent_control_containers` (cross-tenant infrastructure view) | `mcp.platform.infra.agent_control_containers` | needs a grant |

**Grants.** Give an agent a mutating tool with an agent permission (`agent_permissions`, for example `mcp.platform.app.*`) or a tenant policy rule. A REQUIRE_APPROVAL rule makes the tool return `approval_id`. After an admin approves, the same call in the same MCP session runs once.

**Tenant scoping.** Tools taking a `user_id` refuse users outside the agent's tenant.

**Legacy reads.** `MCP_ALLOW_UNAUTHENTICATED_READS=true` restores unauthenticated read-only tools, and only those. It is an explicit opt-in, and every result is tagged.

**Behaviour change.** Existing MCP clients must be given an agent token, or every call is refused.

## 9. API summary

| Method and path | Auth |
|---|---|
| `POST /api/v1/firewall/check` | agent token `firewall:check` |
| `GET /api/v1/agents/{id}/alerts` | tenant member |
| `POST /api/v1/agents/{id}/alerts/{aid}/acknowledge` or `resolve` | operator |
| `GET /api/v1/agents/{id}/rules` | tenant member |
| `POST /api/v1/agents/{id}/rules`, `PATCH /api/v1/agents/{id}/rules/{rid}` | admin |
| `POST /api/v1/agents/{id}/quarantine` | operator |
| `POST /api/v1/agents/{id}/release` | admin |
| `GET /api/v1/agents/{id}/baseline`, `POST …/baseline/refresh` | tenant member / operator |
| `POST /api/v1/agents/{id}/baseline/reset` | admin |
| `GET /api/v1/governance/audit/verify`, `POST /api/v1/governance/audit/seal` | admin |
| `GET /api/v1/approvals`, `GET /api/v1/approvals/{id}`, `POST /api/v1/approvals/{id}/approve` or `reject` | tenant member / admin |

An agent id that belongs to another tenant returns 404 on every route.

## 10. Deployment and rollback

**Deploy.** The migrations apply automatically at start-up. `add_aro_phase2.sql` is now part of the automatic chain (finding F8). Validate on staging first by running each file twice; the second run must change nothing:

```bash
for f in add_aro_phase2 add_event_foundation add_abf add_audit_chain; do
  psql "$DB_URL" -v ON_ERROR_STOP=1 -f migration/$f.sql
  psql "$DB_URL" -v ON_ERROR_STOP=1 -f migration/$f.sql
done
```

**Before go-live:**

- Issue `mcp:invoke` tokens to the existing MCP clients.
- Grant their mutating tools.

**Rollback:**

- **Enforcement is too strict:** set `ZAF_PLATFORM_BASELINE` (it is already on by default), or add tenant ALLOW rules.
- **Code rollback:** revert the code. The schema is additive, and old code ignores the new columns and tables.
- **Audit trigger:** run `DROP TRIGGER trg_agent_events_guard_update ON agent_events;` to remove it.
