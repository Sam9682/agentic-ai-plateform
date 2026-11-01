# 06 — Runtime Execution Gap Analysis

- **Title:** Runtime Execution Gap Analysis
- **Audit date:** 2026-10-31
- **Requirement coverage:** R6.1, R6.2, R6.3, R6.4, R11.1, R11.2
- **Method:** Read + summarize "Current behavior" and "Limitations" per component, focused on execution concerns — job dispatch, remote/SSH and Docker execution invocation, retry/timeout/cancellation handling, session lifecycle, and adapter protocol coverage (ACP, SHAI CLI, SHAI HTTP/SSE, Kiro ACP). Each limitation is tagged with the source file in which it occurs and collected in the closing table. Inspection is read/search only; no application code was modified and no live service (PostgreSQL, Docker, Traefik, SSH target) was started.

## Inspected Sources

Every file/dir below was read for this artifact and is recorded as inspected for the purposes of R11.1.

### Infrastructure Orchestrator
- `src/orchestrator.py`
- `src/ssh_utils.py`
- `src/sandbox_manager.py`
- `src/agent_control_service.py`

### `src/aro/` (ARO execution + sessions)
- `src/aro/execution_manager.py`
- `src/aro/agent_worker.py`
- `src/aro/task_repository.py`
- `src/aro/lifecycle.py`
- `src/aro/lifecycle_service.py`
- `src/aro/agent_repository.py`
- `src/aro/event_service.py`
- `src/aro/events_repository.py`
- `src/aro/runtime_scanner.py`
- `src/aro/runtime_registry_service.py`
- `src/aro/runtime_registry_repository.py`

### `src/aro/adapters/` (runtime adapter protocol coverage)
- `src/aro/adapters/base.py`
- `src/aro/adapters/acp_protocol.py`
- `src/aro/adapters/kiro_acp.py`
- `src/aro/adapters/shai_cli.py`
- `src/aro/adapters/shai_http_sse.py`
- `src/aro/adapters/sse_parser.py`

### `src/serverless/`
- `src/serverless/worker.py`
- `src/serverless/container_runtime.py`
- `src/serverless/config.py`
- `src/serverless/log_cleanup.py`

### `serverless-docker-execution/`
- `serverless-docker-execution/requirements.md`
- `serverless-docker-execution/design.md`
- `serverless-docker-execution/tasks.md`

> **Scope note on `serverless-docker-execution/`.** This directory is a **spec** directory (`requirements.md`, `design.md`, `tasks.md`, `.config.kiro`) describing the Serverless Docker Execution feature; it contains **no runtime code**. The implementation of that feature lives in `src/serverless/` (worker, container runtime, config, log cleanup) and the `serverless_jobs*` tables (see `migration/add_serverless_jobs.sql`). The web API layer is specified as an external module (`agentic-ai-plateform-serverless-brik`) that is not present in this repository. The `serverless-docker-execution/` requirements/design are therefore treated as the contract against which `src/serverless/` is reviewed, and the missing API module is recorded as a limitation.

---

## Component: `src/orchestrator.py` — app/service reconciliation engine

### Current behavior
`LightOrchestrator` manages multi-instance applications (not agents). `create_service` / `scale_service` upsert a row in `services` and trigger `_reconcile_service`, which compares desired vs. actual `instances` rows under a single process-local `threading.Lock` and creates/stops instances to converge. Instance creation selects a least-loaded server via `_select_server` (SQL `ORDER BY COUNT(instances) ASC`, respecting `server_capacity_appli_max`), allocates a port with `_find_available_port`, and starts a container with `_start_container` using a locally-invoked `subprocess.run(['docker','run',...])`. Containers are attached to the shared Traefik network (`swautomorph-shared`) and labeled for Traefik routing; `get_runtime_type()` optionally injects `--runtime kata`. Git-URL "images" are skipped (managed by `deployApp.sh`). `health_check_instances` does an HTTP GET against each running instance; `start_reconciliation_loop` runs a daemon thread that health-checks, reconciles every service, and regenerates nginx config on a fixed 30s interval.

### Limitations
- **Docker is invoked locally only.** `_start_container` and `_stop_instance` call `subprocess.run(['docker', ...])` on the control-plane host; the code comment itself notes "locally for now, could be extended for remote servers". A selected `server_id` other than the local host is recorded in the DB but the container is still started locally, so multi-server placement is not actually honored by the orchestrator path. *(src/orchestrator.py)*
- **No timeout on docker/nginx subprocesses.** `subprocess.run` for `docker run`, `docker stop`, `docker rm`, and `nginx -s reload` is called without a `timeout=`, so a hung Docker/nginx invocation can block the reconciliation thread indefinitely. *(src/orchestrator.py)*
- **No retry/backoff on instance start failure.** On a failed start the instance is marked `failed` and left; the reconcile loop will try to create a *new* replica but there is no backoff, attempt cap, or crash-loop detection, so a persistently failing image is retried every 30s forever. *(src/orchestrator.py)*
- **Process-local lock only.** `_reconcile_service` serializes with an in-process `threading.Lock`; two control-plane processes (or a restart mid-reconcile) have no cross-process/DB advisory lock, so concurrent reconciliation can race on `instances` (the code already catches a duplicate-key `IntegrityError` as evidence of this race). *(src/orchestrator.py)*
- **Health check is fixed and shallow.** `requests.get(..., timeout=5)` with a single attempt marks any non-200/exception as `unhealthy`; there is no retry, no grace period for slow-starting apps, and `unhealthy` does not trigger restart/replacement — it only updates a column. *(src/orchestrator.py)*
- **Mixed/legacy routing concerns.** Both Traefik labels and an nginx upstream generator (`generate_nginx_config` / `reload_nginx`) are present, indicating a partially-migrated routing model carried in the hot reconcile loop. *(src/orchestrator.py)*
- **Reconcile loop stop is best-effort.** `stop_reconciliation_loop` flips a flag and `join()`s with no timeout; a wedged iteration (e.g. a hung subprocess) prevents clean shutdown. *(src/orchestrator.py)*

---

## Component: `src/ssh_utils.py` — shared remote execution primitive

### Current behavior
`ssh_execute(server_ip, command, timeout=30)` is the single remote-exec helper used by the ARO execution manager, adapters, and runtime scanner. It short-circuits to `local_execute` when the target resolves to the local host (`is_local_server`, using a UDP-socket self-IP trick and `getaddrinfo`). Remote calls shell out to `ssh` with `StrictHostKeyChecking=no`, `UserKnownHostsFile=/dev/null`, and `BatchMode=yes`. Both paths return a uniform `(success, stdout, stderr)` tuple and convert timeouts/exceptions into `success=False`. The login user comes from `LINUX_USER_INSTALLATION` via `config_postgres.ssh_target`, defaulting to `ubuntu`.

### Limitations
- **Host-key verification disabled.** `StrictHostKeyChecking=no` + `UserKnownHostsFile=/dev/null` accept any host key, leaving remote execution open to man-in-the-middle; acceptable only on a fully trusted private network and should be flagged for hardening. *(src/ssh_utils.py)*
- **Default 30s timeout is short for container ops.** The default `timeout=30` is inherited by callers that pull images / start containers over SSH; a slow image pull can exceed it and be reported as a failure even though the remote op may still be running. *(src/ssh_utils.py)*
- **Command is passed as a single shell string.** `ssh_execute` and `local_execute` run with `shell=True` semantics (the command is handed to the remote/local shell), so safety depends entirely on each caller quoting correctly (ARO uses `shlex.quote`; the orchestrator builds argv lists but does not route through this helper). There is no built-in arg-array transport. *(src/ssh_utils.py)*
- **No retry/connection reuse.** Every call opens a fresh SSH connection with no retry on transient network failure and no connection multiplexing/pooling, so high-frequency remote operations (scanner, per-task launches) pay full connection cost each time. *(src/ssh_utils.py)*

---

## Component: `src/aro/execution_manager.py` — hardened agent-container launcher

### Current behavior
Provides a pure `build_run_command` that assembles a least-privilege `docker run` argv (`--cap-drop ALL`, `--security-opt no-new-privileges`, `--read-only`, non-root `--user`, `--pids-limit`, `--memory`, `--cpus`) with egress locked to either `--network none` or a dedicated `zaf-proxy-net` with injected `HTTP(S)_PROXY`. `_validate_environment` and a post-assembly `_assert_no_forbidden` reject `--privileged`, docker-socket mounts, host-root mounts, and host networking. `launch()` selects a server (`select_server`) and runs the assembled command through `ssh_utils.ssh_execute`; `stop()` runs `docker stop && docker rm` remotely.

### Limitations
- **`select_server` ignores load and tenancy.** Despite the docstring ("least-loaded… mirroring orchestrator._select_server"), the query is `ORDER BY s.id LIMIT 1` with no instance-count join, so it always returns the lowest-id active server; the `tenant_id` parameter is accepted but unused. *(src/aro/execution_manager.py)*
- **No timeout/cancellation plumbing for the launch itself.** `launch` passes a `timeout` to `ssh_execute` but there is no way to cancel an in-flight launch, and no retry on transient SSH failure — a failed launch returns `(False, …)` to the caller with no recovery policy here. *(src/aro/execution_manager.py)*
- **Image pinning is assumed, not enforced.** The docstring states the image "should be pinned by digest/tag upstream," but `build_run_command` accepts any image string and performs no digest/tag validation, so an unpinned/`latest` image can be launched. *(src/aro/execution_manager.py)*
- **Proxy enforcement depends on an unverified network.** The `proxy` policy attaches `zaf-proxy-net` and sets proxy env vars, but there is no check that the network exists or that the ZAF infra proxy is reachable; if the network is absent the container may fail to start or (worse) fall back to default egress depending on Docker config. *(src/aro/execution_manager.py)*

---

## Component: `src/aro/agent_worker.py` + `src/aro/task_repository.py` — agent task queue & dispatch

### Current behavior
`task_repository` persists an `agent_tasks` queue with idempotency (`idempotency_key`), priority, `max_attempts`, `timeout_seconds`, and a `cancel_requested` flag. `claim_next_task` claims one pending task across tenants using `FOR UPDATE SKIP LOCKED` in a transaction, incrementing `attempts`. `agent_worker.execute_claimed_task` resolves the agent and adapter, emits `task.received`, checks cancellation before and during streaming, streams adapter chunks, and records a terminal status (`succeeded`/`failed`/`cancelled`) with a lifecycle event. `AgentTaskWorker.run` is a blocking poll loop that swallows exceptions so the loop never dies.

### Limitations
- **`timeout_seconds` is stored but never enforced.** The worker streams the adapter handle with no wall-clock deadline; a hung adapter stream blocks `execute_claimed_task` indefinitely. The column exists in the schema and the submit API but nothing enforces it. *(src/aro/agent_worker.py)*
- **Retry is described but not implemented.** The module docstring says "Retry is handled by re-enqueue semantics via attempts/max_attempts," but `execute_claimed_task` marks a failed task terminal `failed` and never re-enqueues; `max_attempts` is incremented on claim but never consulted to retry. *(src/aro/agent_worker.py)*
- **Claimed-but-dead-worker tasks are not recovered.** A task moved to `claimed`/`running` by a worker that then crashes has no lease/heartbeat/timeout reaper, so it stays stuck and is never reclaimed. *(src/aro/task_repository.py)*
- **Cancellation is cooperative and poll-based only.** `request_cancel` sets a flag; the worker only observes it between chunks, so a task blocked inside a single long `stream()` read is not actually interrupted until the next chunk arrives. *(src/aro/agent_worker.py, src/aro/task_repository.py)*
- **No concurrency/throughput controls.** `AgentTaskWorker` processes one task at a time with a fixed poll interval; there is no per-tenant fairness, no max-in-flight cap, and no backpressure. *(src/aro/agent_worker.py)*
- **`complete()`/`mark_running()` are not tenant-scoped.** These updates key on `id` only (unlike the tenant-scoped reads), relying on ids being globally unique rather than enforcing tenant isolation on the write. *(src/aro/task_repository.py)*

---

## Component: `src/aro/lifecycle.py` + `src/aro/lifecycle_service.py` — agent lifecycle & session establishment

### Current behavior
`lifecycle.py` is a pure state graph (REGISTERED→INSTALLING→…→RUNNING→STOPPING→STOPPED, plus FAILED/UNHEALTHY/QUARANTINED/TERMINATED) with `can_transition`. `LifecycleService` validates every transition against the graph, persists via `agent_repository`, and emits an event; illegal transitions raise `IllegalTransition` with no side effect. `install_and_ready`, `start` (creates an `agent_executions` row via an injected `launcher`), `stop`, `restart`, and `quarantine` drive the adapter and record executions. The ACP/SSE adapters model the *runtime session* (handshake → `session/new` → `session/prompt` → streamed updates → `session/cancel`).

### Limitations
- **QUARANTINED has no release path in the graph.** `lifecycle.py` defines no outgoing transitions from `QUARANTINED` (comment: "exit quarantine only via explicit release flow"), and no such release flow exists in `lifecycle_service.py`, so a quarantined agent is effectively stuck. *(src/aro/lifecycle.py)*
- **No automatic UNHEALTHY detection wired in.** `UNHEALTHY` is a valid state and adapters expose `health_check()`, but nothing in `LifecycleService` periodically probes health or drives agents into `UNHEALTHY`; the transition is defined but never triggered by the service. *(src/aro/lifecycle_service.py)*
- **Execution/session row lifecycle is incomplete.** `start` creates an `agent_executions` row with status `STARTING` but `LifecycleService` never calls `set_execution_status` to move it to RUNNING/STOPPED/ended, so execution records do not reflect the true session end. *(src/aro/lifecycle_service.py)*
- **Multi-step drivers are non-atomic.** `install_and_ready`/`start` perform several `transition` calls + adapter calls in sequence with no overall rollback; a failure midway (e.g. after INSTALLED but during CONFIGURING) leaves the agent in an intermediate persisted state with partial side effects. *(src/aro/lifecycle_service.py)*
- **No session resumption/reconnect.** The ACP/SSE session is held in adapter instance memory (`_session_id`, `_transport`); a control-plane restart loses the session with no reconnect/resume, orphaning the remote runtime process. *(src/aro/kiro_acp.py, src/aro/lifecycle_service.py)*

---

## Component: `src/aro/adapters/` — runtime adapter protocol coverage

### Current behavior
`base.py` defines the common `AgentRuntimeAdapter` ABC with an explicit `Capability` enum, typed errors (`CapabilityError`, `ExecutionError`), a streaming/cancellable `ExecutionHandle`, and `ExecutionResult`; unsupported operations raise rather than fake behavior. Four concrete protocols are implemented:
- **Kiro ACP** (`kiro_acp.py` + pure `acp_protocol.py`): JSON-RPC 2.0 newline-delimited over stdio (`docker exec … kiro --acp`), full handshake, streamed `session/update`, `session/cancel`; advertises all capabilities except PAUSE.
- **SHAI CLI** (`shai_cli.py`): headless `shai --prompt` one-shot via `docker exec`, stdout streamed line-by-line, cancel = process terminate, health = container inspect.
- **SHAI HTTP/SSE** (`shai_http_sse.py` + pure `sse_parser.py`): POST + SSE stream; advertises CANCELLATION only when the deployment declares `supports_cancel`; no INSTALL/LOGS.
- Test adapters `FakeAdapter`/`NullAdapter` prove the capability-gating contract.

### Limitations
- **No generic MCP/CLI adapter exists.** `runtime_registry_service` lists `mcp` as a supported protocol and `base.py` references "generic CLI/MCP," but no MCP adapter is implemented — only ACP, SHAI-CLI, and SHAI-HTTP/SSE. A runtime registered with `protocol: mcp` has no adapter. *(src/aro/adapters/base.py, src/aro/runtime_registry_service.py)*
- **Kiro ACP cancel is best-effort and non-interrupting.** `cancel()` writes a `session/cancel` notification but the `stream()` loop blocks on `read_chunks()`; cancellation is only honored when the agent voluntarily responds, and there is no timeout to force-close the transport. *(src/aro/adapters/kiro_acp.py)*
- **ACP streaming has no read timeout.** `_AcpExecutionHandle.stream` and `_handshake` loop over `read_chunks()` with no deadline; an agent that stops emitting (without closing stdout) hangs the stream indefinitely, and the "stream ended early" result only fires on actual EOF. *(src/aro/adapters/kiro_acp.py)*
- **SHAI CLI `result()` races `stream()`.** `_ProcessHandle.result()` reads `self._proc.poll()`; if called before `stream()` has drained stdout and `wait()`ed, it can return a premature/None return code. The contract (`result()` "blocks until finished") is not actually enforced. *(src/aro/adapters/shai_cli.py)*
- **SHAI CLI cancel may not stop children.** `cancel()` sends `terminate()` to the `docker exec` process; the in-container `shai` process (and any children) may survive if the exec'd process does not forward the signal (no `docker stop`/kill of the container itself). *(src/aro/adapters/shai_cli.py)*
- **HTTP/SSE result shape depends on undocumented event names.** Completion is inferred from events named `done`/`end`/`complete` and failure from `error`; a SHAI server using different terminal event names would never terminate the stream cleanly, falling through to the default "no result"/partial-success branch. *(src/aro/adapters/shai_http_sse.py)*
- **No install integrity enforcement at adapter level for SHAI CLI.** `shai_cli.install` runs `npm install -g @ovhcloud/shai@<version>` with a pinned version but no checksum/digest verification of the installed artifact (unlike the Kiro adapter's optional `sha256` check). *(src/aro/adapters/shai_cli.py)*

---

## Component: `src/serverless/worker.py` + `container_runtime.py` + `config.py` — serverless job execution

### Current behavior
`ServerlessWorker` polls `serverless_jobs` with `FOR UPDATE SKIP LOCKED` (`claim_next_job`), validates the image against `registry_whitelist`, pulls the image, and runs it with a hardened `DockerRuntime`/`PodmanRuntime` (`--read-only`, `--user nobody`, `--cap-drop ALL`, `--network none`, `--pids-limit 256`, memory/cpu limits, optional `--runtime kata`). `_wait_with_cancellation_check` polls `docker wait` in 2s slices, checking the DB for a `cancelled` status between slices and raising `TimeoutError` past the job's `timeout_seconds`. Terminal status (`completed`/`failed`/`timeout`/`cancelled`) and stdout/stderr logs are persisted; a container `cleanup` always runs in `finally`. `main()` wires logging, SIGTERM/SIGINT graceful shutdown, runtime detection, and DB config from env.

### Limitations
- **The serverless web API is absent from this repo.** The `serverless-docker-execution/` spec places the `/api/jobs` submission API in an external module (`agentic-ai-plateform-serverless-brik`); no job-submission route exists here, so jobs can only be executed if rows are inserted into `serverless_jobs` by some other means. *(serverless-docker-execution/requirements.md, src/serverless/worker.py)*
- **Per-worker DB connections are opened per operation.** `claim_next_job`, `check_cancelled`, `store_result`, and each `mark_*` open and close a fresh `psycopg2.connect`; under load this is heavy and there is no pooling or reuse. *(src/serverless/worker.py)*
- **Timeout is approximate and cancellation is poll-based.** `_wait_with_cancellation_check` advances `elapsed` by the full `check_interval` on every `docker wait` timeout regardless of real elapsed time, so the effective timeout drifts; cancellation latency is bounded only by the 2s poll. *(src/serverless/worker.py)*
- **No retry for failed/transient jobs.** A job that fails (pull error, non-zero exit, infra error) is marked `failed` with no attempt counter or re-queue; there is no distinction between a deterministic failure and a transient one. *(src/serverless/worker.py)*
- **stdout/stderr separation is unreliable.** `DockerRuntime.get_logs` runs `docker logs --stdout`/`--stderr` but then returns Python's `result.stdout` for the stdout case and `result.stderr` for the stderr case; `docker logs` does not route container streams to the CLI process's stdout/stderr that way, so captured logs can be empty or mis-attributed. *(src/serverless/container_runtime.py)*
- **No image digest pinning or pull retry.** `validate_image_registry` only checks the registry host; tags like `latest` pass, and `pull_image` has no retry/backoff on a transient registry error. *(src/serverless/config.py, src/serverless/container_runtime.py)*
- **`max_concurrent_jobs`/warm pool are config-only.** `SERVERLESS_CONFIG` declares `max_concurrent_jobs: 100` and `warm_pool_*`, but the worker enforces none of them (single serial execution, no warm pool). *(src/serverless/config.py, src/serverless/worker.py)*
- **Runtime type is frozen at startup.** `resolve_runtime_type` reads `runtime_type` once; a config change (runc↔kata) requires a worker restart, which the code documents but which limits live reconfiguration. *(src/serverless/worker.py)*

---

## Component: `src/sandbox_manager.py` — sandbox/demo provisioning (execution-adjacent)

### Current behavior
`SandboxManager` provisions a demo environment by creating a `Demo_User` and deploying 3–10 catalog templates through the shared `TemplateDeployService`, which in turn drives the orchestrator. Provisioning is atomic (`_rollback_provision` on any app failure or <3 apps), and `reset`/`teardown` scope every destructive operation to sandbox-labeled rows (`account_type='sandbox demo'` / `is_sandbox=true`).

### Limitations
- **Rollback is best-effort and can leave orphans.** Each rollback step (`orchestrator.delete_service`, `nginx.remove_location_block`, DB deletes) is wrapped in its own try/except that only logs on failure; a mid-rollback error can leave a started container or nginx location behind despite the "no partial sandbox" intent. *(src/sandbox_manager.py)*
- **Sequential deploy with no concurrency or deploy timeout.** Seeding deploys templates one at a time and stops on the first failure; a single slow/hung template deploy blocks the whole provision with no per-deploy timeout. *(src/sandbox_manager.py)*
- **Teardown depends on an injected orchestrator.** Both removal and rollback guard on `if self.orchestrator is not None`; when no orchestrator is injected, containers/instances are not stopped and only DB/nginx records are cleaned, risking stranded running containers. *(src/sandbox_manager.py)*

---

## Component: `src/agent_control_service.py` — container discovery/ownership aggregation

### Current behavior
Surface-agnostic logic that serializes discovered containers to the Agent Control API contract and aggregates them across managed servers. `scan_live` calls an injected `collect(server)` (SSH collector) per server and records a per-server `error` entry for unreachable servers rather than failing the whole scan; `derive_owner` maps a container to an owner by deployment-path label, `BASE_PATH` env, then compose-project label.

### Current behavior (limitations)
- **Serial, synchronous multi-server scan.** `scan_live` iterates servers sequentially; a slow/unreachable server adds its full SSH timeout to the total scan time (no parallelism, no overall deadline). *(src/agent_control_service.py)*
- **Ownership is heuristic.** Owner derivation relies on compose labels / `BASE_PATH` conventions; containers without those signals are silently `Unowned_Container` (owner `None`), so classification/attribution gaps are expected for non-conforming containers. *(src/agent_control_service.py)*
- **No live-control actions.** This module only reads/serializes inventory; it exposes no start/stop/restart control over discovered agent containers, so "Agent Control" here is observability, not actuation. *(src/agent_control_service.py)*

---

## Cross-cutting runtime observations

- **Two parallel execution engines, two queues.** The serverless path (`serverless_jobs` + `src/serverless/worker.py`) and the ARO agent path (`agent_tasks` + `src/aro/agent_worker.py`) are independent implementations of the same claim/poll/cancel/timeout pattern, with the agent path missing the timeout and retry behaviors the serverless path has. *(src/aro/agent_worker.py, src/serverless/worker.py)*
- **Timeout/retry/cancellation are inconsistent across engines.** Serverless enforces timeout (approximately) and poll-based cancel but no retry; the agent worker enforces neither timeout nor retry; the orchestrator enforces none of the three. No shared execution policy abstracts these. *(src/orchestrator.py, src/aro/agent_worker.py, src/serverless/worker.py)*
- **All remote execution funnels through one host-key-disabled SSH helper** with a short default timeout and no retry/pooling, making it a shared reliability and security chokepoint for ARO launches and runtime scanning. *(src/ssh_utils.py)*

---

## Limitation Summary

| Limitation | Source File | Impact | Notes |
|------------|-------------|--------|-------|
| Docker invoked locally despite server selection | `src/orchestrator.py` | High | Multi-server placement not honored by orchestrator container path |
| No `timeout=` on docker/nginx subprocesses | `src/orchestrator.py` | High | A hung Docker/nginx call blocks the reconcile thread forever |
| No retry/backoff or crash-loop cap on instance start | `src/orchestrator.py` | Medium | Failing image retried every 30s indefinitely |
| Process-local lock only (no cross-process/DB lock) | `src/orchestrator.py` | Medium | Concurrent reconcile races on `instances` (duplicate-key caught) |
| Shallow single-attempt health check, no remediation | `src/orchestrator.py` | Medium | `unhealthy` updates a column but never restarts/replaces |
| Mixed Traefik + nginx routing in reconcile loop | `src/orchestrator.py` | Low | Partially-migrated routing model |
| Reconcile loop stop has no join timeout | `src/orchestrator.py` | Low | Wedged iteration blocks clean shutdown |
| SSH host-key verification disabled | `src/ssh_utils.py` | High | MITM-exposed remote exec; trusted-network assumption |
| Default 30s SSH timeout too short for container ops | `src/ssh_utils.py` | Medium | Slow image pull reported as failure |
| Command passed as single shell string | `src/ssh_utils.py` | Medium | Injection safety depends on each caller quoting |
| No SSH retry / connection reuse | `src/ssh_utils.py` | Medium | Full connection cost per call; no transient-failure retry |
| `select_server` ignores load and tenant | `src/aro/execution_manager.py` | High | Always lowest-id server; `tenant_id` param unused |
| No cancel/retry on in-flight launch | `src/aro/execution_manager.py` | Medium | Failed launch has no recovery policy |
| Image pinning assumed, not enforced | `src/aro/execution_manager.py` | Medium | `latest`/unpinned image can be launched |
| Proxy network existence/reachability unverified | `src/aro/execution_manager.py` | Medium | Egress lockdown may silently not apply |
| `timeout_seconds` stored but never enforced | `src/aro/agent_worker.py` | High | Hung adapter stream blocks worker forever |
| Retry/re-enqueue documented but not implemented | `src/aro/agent_worker.py` | High | Failed tasks are terminal; `max_attempts` unused for retry |
| No lease/heartbeat to recover dead-worker tasks | `src/aro/task_repository.py` | High | `claimed`/`running` tasks stuck after worker crash |
| Cancellation cooperative/poll-based only | `src/aro/agent_worker.py`, `src/aro/task_repository.py` | Medium | A blocked single read is not interrupted |
| No concurrency/fairness/backpressure controls | `src/aro/agent_worker.py` | Medium | One task at a time, no per-tenant fairness |
| `complete()`/`mark_running()` not tenant-scoped | `src/aro/task_repository.py` | Low | Writes key on id only, unlike reads |
| QUARANTINED has no release transition | `src/aro/lifecycle.py` | Medium | Quarantined agent effectively stuck |
| UNHEALTHY never auto-detected/driven | `src/aro/lifecycle_service.py` | Medium | Health transition defined but never triggered |
| Execution/session row never moved past STARTING | `src/aro/lifecycle_service.py` | Medium | `agent_executions` status does not reflect true end |
| Multi-step lifecycle drivers non-atomic | `src/aro/lifecycle_service.py` | Medium | Mid-sequence failure leaves partial persisted state |
| No session resumption after control-plane restart | `src/aro/adapters/kiro_acp.py`, `src/aro/lifecycle_service.py` | Medium | In-memory session lost; remote runtime orphaned |
| No generic MCP/CLI adapter implemented | `src/aro/adapters/base.py`, `src/aro/runtime_registry_service.py` | High | `protocol: mcp` registrations have no adapter |
| ACP cancel best-effort, non-interrupting | `src/aro/adapters/kiro_acp.py` | Medium | Honored only if agent responds; no force-close |
| ACP stream/handshake have no read timeout | `src/aro/adapters/kiro_acp.py` | High | Silent agent hangs the stream indefinitely |
| SHAI CLI `result()` races `stream()` | `src/aro/adapters/shai_cli.py` | Medium | Premature/None return code if called early |
| SHAI CLI cancel may not stop in-container children | `src/aro/adapters/shai_cli.py` | Medium | `terminate()` on exec proc may leave `shai` running |
| HTTP/SSE completion depends on undocumented event names | `src/aro/adapters/shai_http_sse.py` | Medium | Non-standard terminal events never close stream |
| SHAI CLI install lacks integrity verification | `src/aro/adapters/shai_cli.py` | Medium | npm install pinned by version only, no checksum |
| Serverless web API module absent from repo | `serverless-docker-execution/requirements.md`, `src/serverless/worker.py` | High | No `/api/jobs`; jobs only via direct DB insert |
| Per-operation DB connections, no pooling | `src/serverless/worker.py` | Medium | Heavy connection churn under load |
| Serverless timeout approximate; cancel poll-based | `src/serverless/worker.py` | Medium | Effective timeout drifts; 2s cancel latency |
| No retry for failed/transient serverless jobs | `src/serverless/worker.py` | Medium | No attempt counter; transient = permanent failure |
| stdout/stderr capture unreliable | `src/serverless/container_runtime.py` | High | `docker logs` streams mis-captured; logs may be empty |
| No image digest pinning or pull retry (serverless) | `src/serverless/config.py`, `src/serverless/container_runtime.py` | Medium | `latest` passes; no transient pull retry |
| `max_concurrent_jobs`/warm pool config-only | `src/serverless/config.py`, `src/serverless/worker.py` | Medium | Declared limits/features not enforced |
| Serverless runtime type frozen at startup | `src/serverless/worker.py` | Low | runc↔kata change needs worker restart |
| Sandbox rollback best-effort, can orphan resources | `src/sandbox_manager.py` | Medium | Mid-rollback error leaves container/nginx behind |
| Sequential sandbox deploy, no per-deploy timeout | `src/sandbox_manager.py` | Low | One slow template blocks whole provision |
| Sandbox teardown needs injected orchestrator | `src/sandbox_manager.py` | Medium | Without it, running containers are not stopped |
| Agent-control multi-server scan is serial | `src/agent_control_service.py` | Medium | Unreachable server adds full SSH timeout to scan |
| Container ownership is heuristic only | `src/agent_control_service.py` | Low | Non-conforming containers silently unowned |
| No live start/stop/restart control actions | `src/agent_control_service.py` | Medium | Agent Control is observability, not actuation |
| Two parallel execution engines/queues | `src/aro/agent_worker.py`, `src/serverless/worker.py` | Medium | Divergent timeout/retry behavior between them |
| Inconsistent timeout/retry/cancel across engines | `src/orchestrator.py`, `src/aro/agent_worker.py`, `src/serverless/worker.py` | Medium | No shared execution-policy abstraction |
