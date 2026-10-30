-- Migration: Durable agent task queue for ARO (Task 10).
-- Date: 2026-10-30
--
-- Units of work submitted to a running agent. A polling worker claims pending
-- tasks atomically (FOR UPDATE SKIP LOCKED), executes them through the agent
-- adapter, streams output, and records the terminal status. An idempotency key
-- prevents duplicate submission; retry/timeout policy is carried per task.
--
-- Idempotent: IF NOT EXISTS.

CREATE TABLE IF NOT EXISTS agent_tasks (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    agent_id BIGINT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    task_ref VARCHAR(255) NOT NULL,
    operation VARCHAR(128) NOT NULL DEFAULT 'prompt',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    initiator_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    priority INTEGER NOT NULL DEFAULT 100,
    status VARCHAR(32) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'claimed', 'running', 'succeeded',
                          'failed', 'cancelled', 'timeout')),
    policy_context JSONB NOT NULL DEFAULT '{}'::jsonb,
    result_ref TEXT,
    result JSONB,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 1,
    timeout_seconds INTEGER NOT NULL DEFAULT 1800,
    cancel_requested BOOLEAN NOT NULL DEFAULT FALSE,
    worker_id VARCHAR(128),
    deadline TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP WITH TIME ZONE,
    finished_at TIMESTAMP WITH TIME ZONE,
    -- Idempotency: a given (tenant, idempotency_key) yields one task.
    idempotency_key VARCHAR(255),
    CONSTRAINT uq_agent_task_ref UNIQUE (tenant_id, task_ref)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_task_idempotency
    ON agent_tasks(tenant_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_agent_tasks_claim
    ON agent_tasks(status, priority, created_at)
    WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_agent_tasks_agent
    ON agent_tasks(tenant_id, agent_id, created_at DESC);
