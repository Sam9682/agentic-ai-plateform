-- Migration: Agent Behavioral Firewall (ABF) — Phase 2.
-- Date: 2026-11-21
--
-- Additive and idempotent. Extends the existing stores instead of creating
-- parallel ones (see docs/FEATURE_IMPLEMENTATION_PLAN.md):
--
--   * agent_behavior_rules: tenant- or agent-scoped custom rules, versioned.
--     The built-in deterministic catalogue lives in code (src/abf/rules.py);
--     rows here can disable a built-in rule for a tenant/agent or add
--     threshold rules. Rule rows never carry executable code.
--   * agent_baselines: rolling per-(agent, metric) statistics, resettable.
--   * agent_anomalies gains the ABF alert columns: observed facts and the
--     inference are stored separately (spec: facts vs interpretation).
--   * approval_requests gains agent/session binding and single-use
--     consumption (finding F4).
--
-- The agent_tasks 'denied' terminal (finding F5) is added by
-- add_aro_phase2.sql, which now runs automatically before this file.
--
-- Idempotent: IF NOT EXISTS / DROP CONSTRAINT IF EXISTS.

-- --------------------------------------------------------------------------
-- agent_behavior_rules
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agent_behavior_rules (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    -- NULL agent_id = applies to every agent of the tenant.
    agent_id BIGINT REFERENCES agents(id) ON DELETE CASCADE,
    rule_key VARCHAR(128) NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    -- 'override' toggles/re-levels a built-in rule; 'threshold' is a custom
    -- count-in-window rule over normalized events.
    kind VARCHAR(16) NOT NULL DEFAULT 'override',
    category VARCHAR(16),
    matcher JSONB NOT NULL DEFAULT '{}'::jsonb,
    threshold INTEGER,
    window_seconds INTEGER,
    risk_level VARCHAR(16),
    enforcement_action VARCHAR(32),
    description TEXT,
    created_by_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE agent_behavior_rules DROP CONSTRAINT IF EXISTS agent_behavior_rules_kind_check;
ALTER TABLE agent_behavior_rules ADD CONSTRAINT agent_behavior_rules_kind_check
    CHECK (kind IN ('override', 'threshold'));
ALTER TABLE agent_behavior_rules DROP CONSTRAINT IF EXISTS agent_behavior_rules_risk_check;
ALTER TABLE agent_behavior_rules ADD CONSTRAINT agent_behavior_rules_risk_check
    CHECK (risk_level IS NULL OR risk_level IN ('info', 'low', 'medium', 'high', 'critical'));
ALTER TABLE agent_behavior_rules DROP CONSTRAINT IF EXISTS agent_behavior_rules_action_check;
ALTER TABLE agent_behavior_rules ADD CONSTRAINT agent_behavior_rules_action_check
    CHECK (enforcement_action IS NULL OR enforcement_action IN (
        'ALERT', 'REQUIRE_APPROVAL', 'DENY', 'RATE_LIMIT',
        'REVOKE_PERMISSION', 'QUARANTINE'));
ALTER TABLE agent_behavior_rules DROP CONSTRAINT IF EXISTS agent_behavior_rules_threshold_check;
ALTER TABLE agent_behavior_rules ADD CONSTRAINT agent_behavior_rules_threshold_check
    CHECK ((threshold IS NULL OR threshold > 0)
           AND (window_seconds IS NULL OR (window_seconds > 0 AND window_seconds <= 86400)));

CREATE INDEX IF NOT EXISTS idx_agent_behavior_rules_tenant
    ON agent_behavior_rules(tenant_id, rule_key);
CREATE INDEX IF NOT EXISTS idx_agent_behavior_rules_agent
    ON agent_behavior_rules(tenant_id, agent_id);

-- --------------------------------------------------------------------------
-- agent_baselines
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agent_baselines (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    agent_id BIGINT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    metric VARCHAR(64) NOT NULL,
    window_seconds INTEGER NOT NULL DEFAULT 300,
    mean DOUBLE PRECISION,
    stddev DOUBLE PRECISION,
    sample_count INTEGER NOT NULL DEFAULT 0,
    excluded_windows INTEGER NOT NULL DEFAULT 0,
    runtime_reported_ratio DOUBLE PRECISION,
    confidence VARCHAR(16) NOT NULL DEFAULT 'insufficient',
    computed_at TIMESTAMP WITH TIME ZONE,
    reset_at TIMESTAMP WITH TIME ZONE,
    reset_by_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    CONSTRAINT uq_agent_baseline UNIQUE (tenant_id, agent_id, metric)
);

-- --------------------------------------------------------------------------
-- agent_anomalies: ABF alert columns (all nullable / defaulted).
-- --------------------------------------------------------------------------
ALTER TABLE agent_anomalies
    ADD COLUMN IF NOT EXISTS agent_db_id BIGINT,
    ADD COLUMN IF NOT EXISTS trace_id VARCHAR(128),
    ADD COLUMN IF NOT EXISTS category VARCHAR(16),
    ADD COLUMN IF NOT EXISTS observed_facts JSONB,
    ADD COLUMN IF NOT EXISTS inference TEXT,
    ADD COLUMN IF NOT EXISTS confidence_label VARCHAR(16),
    ADD COLUMN IF NOT EXISTS rule_version VARCHAR(32),
    ADD COLUMN IF NOT EXISTS enforcement_action VARCHAR(32),
    ADD COLUMN IF NOT EXISTS source_event_id VARCHAR(128),
    ADD COLUMN IF NOT EXISTS dedupe_key VARCHAR(255);

CREATE INDEX IF NOT EXISTS idx_agent_anomalies_agent_db
    ON agent_anomalies(tenant_id, agent_db_id, detected_at DESC);
-- One alert per (tenant, dedupe key): replayed/duplicated telemetry never
-- multiplies alerts.
CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_anomalies_dedupe
    ON agent_anomalies(tenant_id, dedupe_key)
    WHERE dedupe_key IS NOT NULL;

-- --------------------------------------------------------------------------
-- approval_requests: binding + single use (finding F4).
-- --------------------------------------------------------------------------
ALTER TABLE approval_requests
    ADD COLUMN IF NOT EXISTS session_id VARCHAR(255),
    ADD COLUMN IF NOT EXISTS consumed_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS consumed_by VARCHAR(255);

CREATE INDEX IF NOT EXISTS idx_approval_requests_binding
    ON approval_requests(tenant_id, params_hash, status)
    WHERE consumed_at IS NULL;
