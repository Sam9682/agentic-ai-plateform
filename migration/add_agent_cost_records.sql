-- Migration: PHASE 5 — OBS cost pipeline + anomaly enforcement columns (Task 1.1).
-- Date: 2026-11-20
--
-- Additive, idempotent, re-runnable extension on top of the Phase 1–4 platform.
-- Every change is purely additive (a new table created IF NOT EXISTS plus
-- nullable/defaulted columns appended to agent_anomalies) so existing rows and
-- writers stay valid and the verified Phase 1–4 suites remain green. Nothing is
-- dropped or retyped.
--
--   * agent_cost_records: the OBS cost pipeline's measured-vs-estimated cost
--     ledger (Req 4.1, 4.2, 4.6, 4.7), tenant-scoped and keyed back to the
--     delegating parent task / delegation for budget aggregation (Req 11).
--   * agent_anomalies gains enforcement/routing columns (anomaly_ref,
--     runtime_id, session_id, recommended_action, enforcement_status) that the
--     Detection_Pass set_enforcement helper populates (Req 1.3, 3.4). The
--     existing INFO/LOW/MEDIUM/HIGH/CRITICAL record path stays backward
--     compatible because every new column is nullable or defaulted.
--
-- Idempotent: IF NOT EXISTS / ADD COLUMN IF NOT EXISTS. Running this script more
-- than once is a no-op (Req 13.6).

-- --------------------------------------------------------------------------
-- agent_cost_records: measured-vs-estimated cost ledger (Req 4.1, 4.2, 4.6,
-- 4.7). usage holds the measured usage dimensions; estimated_cost is derived
-- from the rate card and stored separately; data_source records how the figure
-- was obtained (MEASURED / ESTIMATED / MIXED).
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agent_cost_records (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    agent_identity VARCHAR(512),
    parent_task_id BIGINT,
    delegation_id VARCHAR(64),
    usage JSONB NOT NULL DEFAULT '{}'::jsonb,
    estimated_cost NUMERIC(18, 6) NOT NULL DEFAULT 0,
    data_source VARCHAR(16)
        CHECK (data_source IN ('MEASURED', 'ESTIMATED', 'MIXED')),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

-- Budget aggregation reads cost records filtered by parent/delegation per
-- tenant (Req 11.2, 11.3).
CREATE INDEX IF NOT EXISTS idx_agent_cost_records_tenant
    ON agent_cost_records(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_cost_records_parent
    ON agent_cost_records(tenant_id, parent_task_id);
CREATE INDEX IF NOT EXISTS idx_agent_cost_records_delegation
    ON agent_cost_records(tenant_id, delegation_id);

-- --------------------------------------------------------------------------
-- agent_anomalies: enforcement/routing columns for the Detection_Pass
-- (Req 1.3, 3.4). All additive and nullable/defaulted so record_anomaly and
-- existing rows/writers stay valid.
-- --------------------------------------------------------------------------
ALTER TABLE agent_anomalies
    ADD COLUMN IF NOT EXISTS anomaly_ref VARCHAR(64),
    ADD COLUMN IF NOT EXISTS runtime_id VARCHAR(255),
    ADD COLUMN IF NOT EXISTS session_id VARCHAR(255),
    ADD COLUMN IF NOT EXISTS recommended_action VARCHAR(32),
    ADD COLUMN IF NOT EXISTS enforcement_status VARCHAR(32) DEFAULT 'pending';
