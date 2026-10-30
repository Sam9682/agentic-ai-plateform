-- Migration: Agent execution lifecycle records for ARO (Task 7).
-- Date: 2026-10-30
--
-- One row per start-to-stop execution lifecycle of an agent, recording the
-- state transitions and the server/container it ran on. Distinct from
-- agent_tasks (Task 10), which are the units of work submitted to a running
-- agent. An execution references the server and container so observability and
-- containment (quarantine) can act on it.
--
-- Idempotent: IF NOT EXISTS.

CREATE TABLE IF NOT EXISTS agent_executions (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    agent_id BIGINT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    execution_ref VARCHAR(255) NOT NULL,
    server_id BIGINT REFERENCES servers(id) ON DELETE SET NULL,
    container_id TEXT,
    status VARCHAR(32) NOT NULL DEFAULT 'STARTING'
        CHECK (status IN (
            'STARTING', 'RUNNING', 'STOPPING', 'STOPPED',
            'FAILED', 'UNHEALTHY', 'QUARANTINED', 'TERMINATED'
        )),
    detail JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT uq_agent_execution_ref UNIQUE (tenant_id, execution_ref)
);

CREATE INDEX IF NOT EXISTS idx_agent_executions_agent
    ON agent_executions(agent_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_executions_tenant
    ON agent_executions(tenant_id, status);
