-- Migration: ABF/AET event foundation (Phase 1).
-- Date: 2026-11-21
--
-- Additive, idempotent, re-runnable extension of the unified event backbone
-- (add_agent_events.sql). Nothing is dropped or retyped; every new column is
-- nullable or has a constant default, so existing rows and writers stay valid.
--
--   * agent_events gains normalized behavioral / execution-trace fields:
--       trace_id, session_id, task_id, parent_event_id  -> correlation keys
--       category                                         -> PROCESS/SHELL/... taxonomy
--       normalized_action, resource, outcome, duration_ms
--       ingest_source, ingest_principal                  -> provenance
--     ingest_source distinguishes events the control plane observed itself
--     ('control_plane') from events an agent runtime reported through the
--     authenticated ingestion endpoint ('runtime_reported'). Agent-reported data
--     is untrusted: it is never allowed to improve a governance score on its own.
--   * agent_ingest_tokens: per-agent, hashed, expiring, revocable tokens that
--     authenticate runtime telemetry ingestion. Separate from
--     agent_scoped_tokens, whose credential_id is NOT NULL and represents a
--     delegated infrastructure secret; a telemetry token has no backing secret.
--
-- Idempotent: ADD COLUMN IF NOT EXISTS / CREATE ... IF NOT EXISTS /
-- DROP CONSTRAINT IF EXISTS + ADD CONSTRAINT.

-- --------------------------------------------------------------------------
-- agent_events: normalized fields
-- --------------------------------------------------------------------------
ALTER TABLE agent_events
    ADD COLUMN IF NOT EXISTS trace_id VARCHAR(128),
    ADD COLUMN IF NOT EXISTS session_id VARCHAR(255),
    ADD COLUMN IF NOT EXISTS task_id VARCHAR(255),
    ADD COLUMN IF NOT EXISTS parent_event_id VARCHAR(128),
    ADD COLUMN IF NOT EXISTS category VARCHAR(16),
    ADD COLUMN IF NOT EXISTS normalized_action VARCHAR(255),
    ADD COLUMN IF NOT EXISTS resource TEXT,
    ADD COLUMN IF NOT EXISTS outcome VARCHAR(16),
    ADD COLUMN IF NOT EXISTS duration_ms INTEGER,
    ADD COLUMN IF NOT EXISTS ingest_source VARCHAR(32) NOT NULL DEFAULT 'control_plane',
    ADD COLUMN IF NOT EXISTS ingest_principal VARCHAR(255);

ALTER TABLE agent_events DROP CONSTRAINT IF EXISTS agent_events_category_check;
ALTER TABLE agent_events ADD CONSTRAINT agent_events_category_check
    CHECK (category IS NULL OR category IN (
        'PROCESS', 'SHELL', 'FILESYSTEM', 'NETWORK', 'MCP', 'LLM', 'API',
        'DATABASE', 'RUNTIME', 'SECURITY', 'RESOURCE'));

ALTER TABLE agent_events DROP CONSTRAINT IF EXISTS agent_events_outcome_check;
ALTER TABLE agent_events ADD CONSTRAINT agent_events_outcome_check
    CHECK (outcome IS NULL OR outcome IN ('SUCCESS', 'FAILURE', 'DENIED', 'UNKNOWN'));

ALTER TABLE agent_events DROP CONSTRAINT IF EXISTS agent_events_ingest_source_check;
ALTER TABLE agent_events ADD CONSTRAINT agent_events_ingest_source_check
    CHECK (ingest_source IN ('control_plane', 'runtime_reported'));

ALTER TABLE agent_events DROP CONSTRAINT IF EXISTS agent_events_duration_check;
ALTER TABLE agent_events ADD CONSTRAINT agent_events_duration_check
    CHECK (duration_ms IS NULL OR duration_ms >= 0);

CREATE INDEX IF NOT EXISTS idx_agent_events_trace
    ON agent_events(tenant_id, trace_id)
    WHERE trace_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_agent_events_session
    ON agent_events(tenant_id, session_id, occurred_at)
    WHERE session_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_agent_events_severity_time
    ON agent_events(tenant_id, severity, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_events_agent_category
    ON agent_events(tenant_id, agent_id, category, occurred_at DESC);

-- --------------------------------------------------------------------------
-- agent_ingest_tokens: authenticated runtime telemetry ingestion
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agent_ingest_tokens (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    agent_id BIGINT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    -- sha256 of the clear token; the clear token is shown to the caller once.
    token_hash VARCHAR(128) UNIQUE NOT NULL,
    -- Non-secret display prefix so operators can tell tokens apart.
    token_prefix VARCHAR(32) NOT NULL,
    scope VARCHAR(64) NOT NULL DEFAULT 'telemetry:ingest',
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    revoked BOOLEAN NOT NULL DEFAULT FALSE,
    revoked_at TIMESTAMP WITH TIME ZONE,
    created_by_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    last_used_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_agent_ingest_tokens_agent
    ON agent_ingest_tokens(tenant_id, agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_ingest_tokens_expiry
    ON agent_ingest_tokens(expires_at);
