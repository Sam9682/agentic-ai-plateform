-- Migration: Execution environment configuration for ARO (Task 6).
-- Date: 2026-10-30
--
-- Describes the isolated environment an agent runs in. Agents execute on
-- managed servers (reached over SSH) in hardened containers launched with least
-- privilege by default: no privileged mode, no docker.sock / host mounts, and
-- egress locked to the ZAF infrastructure proxy. These rows hold the resource
-- limits and policy knobs for each environment.
--
-- Idempotent: IF NOT EXISTS + ON CONFLICT.

CREATE TABLE IF NOT EXISTS execution_environments (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    -- 'docker' now; 'kata'/'firecracker'/'k8s' are future values.
    kind VARCHAR(32) NOT NULL DEFAULT 'docker'
        CHECK (kind IN ('docker', 'kata', 'firecracker', 'k8s')),
    cpu_limit VARCHAR(16) NOT NULL DEFAULT '1',
    memory_limit VARCHAR(16) NOT NULL DEFAULT '512m',
    disk_limit VARCHAR(16),
    pids_limit INTEGER NOT NULL DEFAULT 256,
    exec_timeout_seconds INTEGER NOT NULL DEFAULT 1800,
    -- Network policy: 'proxy' routes egress through the infra proxy (default),
    -- 'none' isolates entirely. 'open' is intentionally not allowed here.
    network_policy VARCHAR(16) NOT NULL DEFAULT 'proxy'
        CHECK (network_policy IN ('proxy', 'none')),
    read_only BOOLEAN NOT NULL DEFAULT TRUE,
    run_as_user VARCHAR(64) NOT NULL DEFAULT 'nobody',
    env JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_execution_environment UNIQUE (tenant_id, name)
);

CREATE INDEX IF NOT EXISTS idx_execution_environments_tenant
    ON execution_environments(tenant_id);
