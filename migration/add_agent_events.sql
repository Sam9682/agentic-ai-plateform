-- Migration: Unified event + audit backbone for ARO/ZAF.
-- Date: 2026-10-30
--
-- A single immutable event stream shared by all three domains (runtime
-- management, governance, observability). Events are append-only: there is no
-- UPDATE/DELETE path in the repository, so security audit records cannot be
-- tampered with through the application. Secret-like values are redacted by the
-- event service before rows are written here.
--
-- High-volume telemetry: the table is designed for partitioning by month on
-- occurred_at. We ship it unpartitioned for simplicity (idempotent, works on
-- any PG 12+), with the partition key column present so a later migration can
-- convert it to a partitioned parent without reshaping callers.
--
-- Idempotent: IF NOT EXISTS throughout.

CREATE TABLE IF NOT EXISTS agent_events (
    id BIGSERIAL PRIMARY KEY,
    -- Business event identifier (SRS "event_id"); unique per tenant.
    event_id VARCHAR(128) NOT NULL,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    agent_id VARCHAR(255),
    execution_id VARCHAR(255),
    event_type VARCHAR(128) NOT NULL,
    source VARCHAR(128) NOT NULL,
    action JSONB NOT NULL DEFAULT '{}'::jsonb,
    decision VARCHAR(32)
        CHECK (decision IS NULL OR decision IN
               ('ALLOW', 'DENY', 'REQUIRE_APPROVAL', 'QUARANTINE')),
    risk_score INTEGER NOT NULL DEFAULT 0
        CHECK (risk_score >= 0 AND risk_score <= 100),
    severity VARCHAR(16) NOT NULL DEFAULT 'INFO'
        CHECK (severity IN ('INFO', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
    correlation_id VARCHAR(128),
    occurred_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    recorded_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_agent_event UNIQUE (tenant_id, event_id)
);

CREATE INDEX IF NOT EXISTS idx_agent_events_tenant_time
    ON agent_events(tenant_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_events_agent
    ON agent_events(tenant_id, agent_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_events_correlation
    ON agent_events(correlation_id);
CREATE INDEX IF NOT EXISTS idx_agent_events_type
    ON agent_events(tenant_id, event_type);
CREATE INDEX IF NOT EXISTS idx_agent_events_severity
    ON agent_events(tenant_id, severity);
