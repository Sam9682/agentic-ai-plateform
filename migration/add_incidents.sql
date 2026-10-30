-- Migration: Observability anomalies + security incidents for ZAF (Task 16/17).
-- Date: 2026-10-30
--
-- Agent-level anomalies (distinct from the container-level runtime_anomalies in
-- add_runtime_monitor.sql) and security incidents that containment produces.
-- Both are tenant-scoped and carry an explainable evidence payload.
--
-- Idempotent: IF NOT EXISTS.

CREATE TABLE IF NOT EXISTS agent_anomalies (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    agent_identity VARCHAR(512),
    rule_id VARCHAR(128) NOT NULL,
    severity VARCHAR(16) NOT NULL DEFAULT 'LOW'
        CHECK (severity IN ('INFO', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
    risk_score INTEGER NOT NULL DEFAULT 0,
    evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
    status VARCHAR(16) NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'acknowledged', 'resolved')),
    detected_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_agent_anomalies_tenant
    ON agent_anomalies(tenant_id, detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_anomalies_agent
    ON agent_anomalies(tenant_id, agent_identity);

CREATE TABLE IF NOT EXISTS security_incidents (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    agent_identity VARCHAR(512),
    kind VARCHAR(64) NOT NULL,
    severity VARCHAR(16) NOT NULL DEFAULT 'HIGH'
        CHECK (severity IN ('INFO', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
    summary TEXT NOT NULL,
    detail JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(16) NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'contained', 'resolved')),
    actions_taken JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_security_incidents_tenant
    ON security_incidents(tenant_id, created_at DESC);
