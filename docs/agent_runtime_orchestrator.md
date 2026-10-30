# Agent Runtime Orchestrator (ARO) + Zero-trust Agent Firewall (ZAF)

A governed control plane for heterogeneous AI agent runtimes, added as a module
of `agentic-ai-plateform`. It manages the full agent lifecycle (Kiro over ACP,
SHAI over CLI and HTTP/SSE), enforces zero-trust governance over the actions
agents take against infrastructure, and provides runtime observability.

This document covers the API surface, the enforcement model, configuration, and
the Definition of Done. It is written to be read alongside the code in
`src/aro/`, `src/zaf/`, `src/obs/` and the migrations in `migration/add_*.sql`.

## Architecture at a glance

- **Control plane** (Flask, in `src/`): registries, lifecycle, policy decision
  point, approvals, audit, UI.
- **Execution plane**: agent containers launched on managed `servers` over SSH
  with least-privilege hardening and egress locked to the ZAF infra proxy.
- **Enforcement points** (combined): the governed MCP gateway, the
  infrastructure API proxy, adapter-level PDP checks, and container egress
  lockdown. The infra proxy authorizes infra operations *independently of what
  the agent reports*.
- **Multi-tenancy**: every ARO/ZAF entity carries `tenant_id`; access is
  resolved by `src/authz.py` decorators (`login_required`, `tenant_scoped`,
  `role_required`).
- **Fail closed**: if the policy decision point is unavailable, protected
  actions are denied. Explicit deny beats allow. Approvals are bound to the
  exact action + parameters (a hash); a modified request needs re-authorization.

```
Agent container (Kiro/SHAI) ──tool calls──▶ MCP gateway ──▶ PDP
                            ──infra egress─▶ Infra proxy ──▶ PDP ──▶ (approval)
PDP / gateway / proxy / lifecycle / worker ──▶ unified event + audit stream
```

## Configuration

| Env var | Purpose | Notes |
|---|---|---|
| `ZAF_SECRET_KEY` | AEAD key for the credential vault | **Required** to store/read credentials; the vault fails closed if unset. |
| `ZAF_LIVE_OPENSTACK` | Enable real OpenStack/OVHcloud mutations | Must be `1` for the real provider to perform a mutating call. Never set in CI. |

Migrations are applied automatically at boot by `init_db()` (idempotent
`migration/add_*.sql`). New blueprints are registered in
`src/ControlPlanFlaskApp_postgres.py`.

## REST API

All endpoints enforce authentication + tenant scoping; mutating governance
endpoints require the tenant `admin` role; agent/task operations require
`operator`.

### Runtimes — `/api/v1/agents/runtimes`
- `GET /runtimes` — list registered runtimes
- `POST /runtimes` — register/update (admin); validated (pinned version,
  integrity-verified install, no arbitrary scripts)
- `GET /runtimes/{id}` — details
- `GET /runtimes/{id}/health` — declared health check

### Agents — `/api/v1/agents`
- `GET /` · `POST /` · `GET /{id}` · `DELETE /{id}`
- `POST /{id}/ready` — install + configure to READY
- `POST /{id}/start` · `POST /{id}/stop` · `POST /{id}/restart`
- `GET /{id}/status`

Illegal lifecycle transitions return `409`.

### Tasks — `/api/v1/agents/tasks`
- `POST /tasks` — submit (idempotent on `idempotency_key`)
- `GET /tasks/{id}` · `POST /tasks/{id}/cancel`
- `GET /tasks/{id}/events` — SSE stream (no polling)

### Governance — `/api/v1/governance`
- `POST /policies` (admin; JSON `rules[]` or an SRS-style `{"yaml": "..."}`)
- `GET /policies`
- `POST /evaluate` — returns ALLOW / DENY / REQUIRE_APPROVAL / QUARANTINE
- `GET /decisions` — audit of decisions
- `GET /approvals` · `POST /approvals/{id}/approve` · `POST /approvals/{id}/reject` (admin)

### Observability — `/api/v1/observability`
- `GET /events` · `GET /metrics` · `GET /anomalies` · `GET /incidents`
- `GET /agents/{identity}/timeline` · `GET /agents/{identity}/risk`

## Policy language

A policy is a list of rules. A rule matches on an `action` glob and an optional
`condition`; the decision is one of ALLOW/DENY/REQUIRE_APPROVAL/QUARANTINE.

```yaml
policy:
  name: infrastructure-protection
  scope: tenant
  rules:
    - action: openstack.server.list
      decision: ALLOW
    - action: openstack.server.delete
      decision: REQUIRE_APPROVAL
    - action: database.drop
      decision: DENY
    - action: shell.command
      condition: { risk_level: high }
      decision: REQUIRE_APPROVAL
```

Resolution: any matching DENY wins (deny precedence); otherwise the
highest-precedence matched decision (QUARANTINE > REQUIRE_APPROVAL > ALLOW); if
no rule matches, the action is allowed only when a granted agent permission glob
covers it, else denied (default deny).

## Runtime adapters

Adapters implement `src/aro/adapters/base.py:AgentRuntimeAdapter` and declare
their real capabilities. ACP, CLI and HTTP/SSE are distinct protocols with
distinct adapters — an MCP connection alone does not expose every action.

| Adapter | Protocol | Cancellation | Logs | Health |
|---|---|---|---|---|
| `KiroAcpAdapter` | ACP (JSON-RPC over stdio) | yes (`session/cancel`) | container logs | container state |
| `ShaiCliAdapter` | headless CLI (subprocess) | yes (signal) | container logs | container state |
| `ShaiHttpSseAdapter` | HTTP + SSE | only if the deployment advertises it | not over HTTP | `/health` |

Unsupported operations raise `CapabilityError` so the platform records the
limitation rather than faking behavior.

## End-to-end scenario

`tests/test_e2e_governed_scenario.py` runs the SRS scenario for **both** Kiro
and SHAI against the deterministic mock OpenStack provider:

1. register runtime → drive an infra agent to RUNNING via the real adapter;
2. grant OpenStack read-only permission;
3. submit an inspect task; the agent streams output through the worker;
4. `server.list` is ALLOWED and executes;
5. `server.delete` is REQUIRE_APPROVAL → blocked (HTTP 202), nothing deleted;
6. a human approves the exact action+params → the delete executes;
7. a different server id is **not** authorized by that approval
   (re-authorization required);
8. every decision is in the audit stream.

### Running the automated E2E (safe, mock provider)

```bash
ZAF_SECRET_KEY=ci-key ./.venv/bin/python -m pytest tests/test_e2e_governed_scenario.py -v
```

### Running against live OpenStack/OVHcloud (manual, destructive-gated)

The real provider refuses any mutating call unless `ZAF_LIVE_OPENSTACK=1`. Live
mutations create/destroy real cloud resources, so this is manual-only and must
never run in CI. Store the OpenStack credential in the vault (ciphertext), mint a
scoped token per call, and keep `server.delete` behind REQUIRE_APPROVAL so a
human gates every destructive mutation.

## Definition of Done (maps to SRS §16)

- [x] Kiro and SHAI can be registered and executed (`runtime registry`, adapters, lifecycle).
- [x] Agents run in isolated, hardened environments (`execution_manager`, egress lockdown, no docker.sock/host mounts).
- [x] Agents have independent zero-trust identities (`agent://{tenant}/{name}`).
- [x] Lifecycle operations work through the platform API (`/api/v1/agents/...`).
- [x] Tasks tracked submission → completion with SSE streaming + cancellation.
- [x] Sensitive actions subject to centralized authorization (PDP, fail-closed, deny precedence).
- [x] MCP calls governed through the gateway (authn, param validation, rate limit, approvals).
- [x] Security decisions audited (immutable `agent_events` + `governance_decisions`).
- [x] Process/resource telemetry collected (runtime scanner wiring the runtime_monitor repo).
- [x] Repeated execution patterns detected (anomaly engine) with explainable risk scoring.
- [x] Critical incidents trigger containment (quarantine, credential revocation, incident record, break-glass).
- [x] Tenant isolation enforced and tested.
- [x] API + UI documented (this file + the Agent Management dashboard section).
- [x] Automated unit, integration and E2E tests pass.

## Test suites

- Python: `tests/test_aro_*.py`, `tests/test_zaf_*.py`, `tests/test_obs_*.py`,
  `tests/test_e2e_governed_scenario.py` (pytest + hypothesis, stubbed DB/SSH,
  mock OpenStack).
- JS: `tests/js/agentManagement.test.js` (jsdom) for the dashboard panels.
