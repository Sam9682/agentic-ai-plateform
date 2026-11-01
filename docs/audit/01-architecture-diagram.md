# 01 — Architecture Diagram

- **Title:** Architecture Diagram
- **Audit date:** 2026-10-31
- **Requirement coverage:** R1.1, R1.2, R1.3, R11.1
- **Method:** The five subsystem groupings were established from the `src/` directory layout (inspected live) and populated with the modules the design assigns to each. Principal runtime relationships are drawn from the cross-subsystem edge set observed by static import analysis in `docs/audit/02-dependency-map.md` (task 1) — this artifact renders those module-to-module edges at subsystem granularity rather than re-deriving them. A short prose legend follows the diagram.
- **Input:** `docs/audit/02-dependency-map.md` (task 1) — "Cross-Subsystem Edges (handoff to stage 01)" section and the full edge set.

## Inspected Sources

The `src/` layout was inspected and its modules grouped into the five subsystems below. Every module named here is recorded as inspected for the purposes of R11.1 (the exhaustive per-module inspection record lives in `02-dependency-map.md`, which covers all 94 `*.py` files under `src/`).

### Subsystem groupings (as inspected)

| Subsystem | Modules grouped under it |
|-----------|--------------------------|
| **ARO** — `src/aro/` | `agent_repository.py`, `agent_worker.py`, `lifecycle.py`, `lifecycle_service.py`, `execution_manager.py`, `task_repository.py`, `runtime_registry_repository.py`, `runtime_registry_service.py`, `runtime_scanner.py`, `event_service.py`, `events_repository.py`, `adapters/` (`base.py`, `acp_protocol.py`, `kiro_acp.py`, `shai_cli.py`, `shai_http_sse.py`, `sse_parser.py`) |
| **ZAF** — `src/zaf/` | `mcp_gateway.py`, `policy_engine.py`, `policy_repository.py`, `approval_service.py`, `response_service.py`, `infra_proxy.py`, `governance_service.py`, `credential_vault.py`, `providers/` (`openstack.py`) |
| **OBS** — `src/obs/` + `src/runtime_monitor/` | `obs_repository.py`, `anomaly_engine.py`, `risk_scoring.py`; `runtime_monitor/runtime_collector.py`, `runtime_monitor/agent_classifier.py`, `runtime_monitor/runtime_monitor_repository.py` |
| **Infrastructure Orchestrator** | `orchestrator.py`, `agent_control_service.py`, `sandbox_manager.py`, `platform_discovery.py`, `serverless/` (`worker.py`, `container_runtime.py`, `log_cleanup.py`, `config.py`), `serverless-docker-execution/` |
| **Agent Supervisor** | `aro/agent_worker.py` plus the orchestration modules (`orchestrator.py`, `agent_control_service.py`) that carry role / task-decomposition / delegation / governance-inheritance behavior |

Two shared layers are drawn alongside the subsystems because every subsystem depends on them (they are not a sixth subsystem, they are the common foundation):

- **HTTP route layer** — `src/routes/*_routes.py` (the entry edge into each subsystem: `aro_*_routes.py` → ARO, `zaf_governance_routes.py` → ZAF, `obs_routes.py` → OBS, `orchestrator_routes.py`/`sandbox_routes.py` → Infrastructure Orchestrator, `agent_control_routes.py` → Agent Supervisor).
- **Data / config layer** — `database_postgres.py` (fan-in 33) and `config_postgres.py` (fan-in 20), the two dominant hubs every subsystem's repositories resolve down to.

## Architecture Diagram (Mermaid)

The flowchart has one subgraph per subsystem (ARO, ZAF, OBS, Infrastructure Orchestrator, Agent Supervisor), plus the shared HTTP route layer and data/config layer. Edges follow the principal runtime relationships recorded in task 1: **routes → services → repositories → database**; **ZAF interception layered around ARO execution** (via the shared ARO event store); and **OBS consuming agent/runtime events**.

```mermaid
flowchart TD
    %% ===== Shared HTTP route layer =====
    subgraph ROUTES["HTTP Route Layer — src/routes/*_routes.py"]
        R_ARO["aro_task / aro_agent / aro_runtime routes"]
        R_ZAF["zaf_governance_routes"]
        R_OBS["obs_routes"]
        R_ORCH["orchestrator / sandbox / templates routes"]
        R_AGENTCTL["agent_control_routes"]
    end

    %% ===== ARO =====
    subgraph ARO["ARO — Agent Runtime Orchestration (src/aro/)"]
        ARO_SVC["lifecycle_service / runtime_registry_service / event_service"]
        ARO_REPO["agent_repository / task_repository / runtime_registry_repository / events_repository"]
        ARO_EXEC["execution_manager + adapters (ACP, Kiro ACP, SHAI CLI, SHAI HTTP/SSE)"]
        ARO_SCAN["runtime_scanner"]
    end

    %% ===== ZAF =====
    subgraph ZAF["ZAF — Zero-trust Agent Framework (src/zaf/)"]
        ZAF_GATE["mcp_gateway (PEP) / infra_proxy"]
        ZAF_POL["policy_engine (PDP) / policy_repository"]
        ZAF_GOV["governance_service / approval_service / response_service"]
        ZAF_CRED["credential_vault"]
    end

    %% ===== OBS =====
    subgraph OBS["OBS — Observability (src/obs/ + src/runtime_monitor/)"]
        OBS_REPO["obs_repository"]
        OBS_ANOM["anomaly_engine / risk_scoring"]
        OBS_MON["runtime_collector / agent_classifier / runtime_monitor_repository"]
    end

    %% ===== Infrastructure Orchestrator =====
    subgraph INFRA["Infrastructure Orchestrator"]
        INFRA_ORCH["orchestrator"]
        INFRA_SANDBOX["sandbox_manager / platform_discovery"]
        INFRA_SL["serverless/worker + container_runtime + log_cleanup + serverless-docker-execution/"]
    end

    %% ===== Agent Supervisor =====
    subgraph SUP["Agent Supervisor"]
        SUP_WORKER["aro/agent_worker"]
        SUP_CTL["agent_control_service"]
    end

    %% ===== Shared data/config layer =====
    subgraph DATA["Data / Config Layer"]
        DB["database_postgres"]
        CFG["config_postgres"]
        SSH["ssh_utils (remote execution helper)"]
    end

    %% ---- routes -> services -> repositories (the principal request path) ----
    R_ARO --> ARO_SVC
    R_ARO --> ARO_REPO
    ARO_SVC --> ARO_REPO
    ARO_REPO --> DB

    R_ZAF --> ZAF_GOV
    ZAF_GOV --> ZAF_POL
    ZAF_POL --> DB
    ZAF_GATE --> ZAF_POL

    R_OBS --> OBS_REPO
    OBS_REPO --> DB

    R_ORCH --> INFRA_ORCH
    INFRA_ORCH --> DB
    INFRA_SANDBOX --> DB
    INFRA_SL --> DB

    R_AGENTCTL --> SUP_CTL

    %% ---- ZAF interception layered around ARO execution (shared ARO event store) ----
    ZAF_GOV -->|emits/reads events| ARO_SVC
    ZAF_GATE -->|intercepts, logs to ARO events| ARO_REPO
    ZAF_GOV -. governs .-> ARO_EXEC

    %% ---- OBS consumes agent/runtime events ----
    ARO_REPO -->|agent/runtime events| OBS_REPO
    ZAF_GOV -->|governance responses| OBS_REPO
    OBS_REPO --> OBS_ANOM

    %% ---- Agent Supervisor over ARO + orchestration ----
    SUP_WORKER --> ARO_SVC
    SUP_WORKER --> ARO_REPO
    SUP_CTL --> OBS_MON
    SUP_WORKER -.delegates.-> INFRA_ORCH

    %% ---- remote execution + config foundation ----
    ARO_EXEC --> SSH
    OBS_MON --> SSH
    SSH --> CFG
    DB --> CFG

    %% ---- credential broker feeds runtimes ----
    ZAF_CRED --> DB
    ZAF_CRED -. secrets to runtimes .-> ARO_EXEC
```

## Legend

- **Subgraphs** are the five audited subsystems plus the two shared layers (HTTP routes, data/config) they all rest on. Each subsystem subgraph collapses several modules into a few role-labeled nodes; the full module membership is in the "Subsystem groupings" table above and the exhaustive edge list is in `02-dependency-map.md`.
- **Solid arrows** (`-->`) are direct import/call relationships observed in task 1 (e.g. `aro_*_routes.py → aro/*`, `obs_routes.py → obs_repository.py`, every repository → `database_postgres.py`).
- **Dashed arrows** (`-. label .->`) mark runtime relationships that are real but not expressed as a static Python import in the current tree — notably ZAF *governing* ARO execution, the Supervisor *delegating* to the orchestrator, and the credential vault *passing secrets to runtimes*. Task 1 flagged the four ZAF enforcement components (`mcp_gateway`, `infra_proxy`, `response_service`, `credential_vault`) as having no inbound `src/` import, so these governance/enforcement edges are the intended runtime path rather than a wired import; they are candidates for `PARTIALLY_INTEGRATED` in the Gap Matrix (task 10).
- **Principal flows named by the diagram:**
  1. **Request path:** `routes → services → repositories → database` — the dominant pattern across ARO, ZAF, OBS, and Infrastructure Orchestrator, all terminating at `database_postgres.py`.
  2. **ZAF interception around ARO execution:** every ZAF service reads/writes the shared ARO event store (`aro/event_service.py` + `aro/events_repository.py`), so governance and interception are layered on top of ARO's execution events; ZAF additionally governs the ARO execution manager/adapters path.
  3. **OBS consuming events:** agent/runtime events written by ARO and governance responses from ZAF (`zaf/response_service.py → obs/obs_repository.py`) feed the observability store, which the anomaly engine consumes.
- **Shared foundation:** `database_postgres.py` (fan-in 33) and `config_postgres.py` (fan-in 20) are the two hubs every subsystem depends on; `ssh_utils.py` is the shared remote-execution helper used by the ARO execution path and the OBS runtime collector.

All five subsystems — **ARO, ZAF, OBS, Infrastructure Orchestrator, and Agent Supervisor** — are represented in the Mermaid block above, along with the relationships between them (ZAF↔ARO via the event store, ARO/ZAF→OBS via events, Supervisor→ARO and →orchestrator, and every subsystem→data/config layer), satisfying R1.3.
