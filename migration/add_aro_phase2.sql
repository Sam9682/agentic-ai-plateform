-- Migration: PHASE 2 — ARO completion additive schema (Task 1.1).
-- Date: 2026-11-06
--
-- Additive, idempotent, re-runnable extension of the Phase 1 ARO baseline.
-- Every change is purely additive (nullable columns, partial indexes, an
-- appended CHECK value) so existing rows and writers stay valid and the
-- Phase_1_Baseline suites remain green.
--
--   * agent_executions gains session-durability columns (session_id,
--     runtime_handle, runtime_adapter) and a partial index over RUNNING rows
--     for the reconnect routine.
--   * agent_tasks gains lease/heartbeat columns (lease_expires_at,
--     heartbeat_at) and a partial index over leased rows for the reaper.
--   * agent_tasks_status_check is swapped to add the 'timed_out' terminal
--     while retaining the legacy 'timeout' value for backward compatibility.
--
-- Idempotent: IF NOT EXISTS / DROP CONSTRAINT IF EXISTS. Running this script
-- more than once is a no-op.

-- --------------------------------------------------------------------------
-- agent_executions: session durability (Req 4.1) + RUNNING reconnect lookup.
-- --------------------------------------------------------------------------
ALTER TABLE agent_executions
    ADD COLUMN IF NOT EXISTS session_id TEXT,
    ADD COLUMN IF NOT EXISTS runtime_handle TEXT,
    ADD COLUMN IF NOT EXISTS runtime_adapter VARCHAR(64);

CREATE INDEX IF NOT EXISTS idx_agent_executions_running
    ON agent_executions(tenant_id, status)
    WHERE status = 'RUNNING';

-- --------------------------------------------------------------------------
-- agent_tasks: lease/heartbeat (Req 6.5, 6.6) + reaper lookup over leased rows.
-- --------------------------------------------------------------------------
ALTER TABLE agent_tasks
    ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMP WITH TIME ZONE;

CREATE INDEX IF NOT EXISTS idx_agent_tasks_lease
    ON agent_tasks(status, lease_expires_at)
    WHERE status IN ('claimed', 'running');

-- --------------------------------------------------------------------------
-- agent_tasks: add the 'timed_out' terminal (Req 6.1, 6.2) while keeping the
-- legacy 'timeout' value so any existing rows/writers stay valid (Req 7.1,
-- 7.2). The constraint is dropped and re-added idempotently.
-- --------------------------------------------------------------------------
ALTER TABLE agent_tasks
    DROP CONSTRAINT IF EXISTS agent_tasks_status_check;

ALTER TABLE agent_tasks
    ADD CONSTRAINT agent_tasks_status_check
    CHECK (status IN ('pending', 'claimed', 'running', 'succeeded',
                      'failed', 'cancelled', 'timeout', 'timed_out'));
