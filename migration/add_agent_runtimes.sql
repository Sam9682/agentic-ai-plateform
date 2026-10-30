-- Migration: Agent runtime registry for ARO (Task 4).
-- Date: 2026-10-30
--
-- Central catalog of the agent runtimes the platform can install and operate
-- (Kiro via ACP, SHAI via CLI/HTTP-SSE, generic CLI, generic MCP). Each row is
-- a runtime *definition*; installation uses pinned versions and integrity
-- verification (the platform never auto-runs an arbitrary agent-supplied
-- install script). Tenant-scoped so one tenant cannot see/alter another's
-- registered runtimes.
--
-- Idempotent: IF NOT EXISTS + ON CONFLICT.

CREATE TABLE IF NOT EXISTS agent_runtimes (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    -- Stable machine identifier, e.g. 'kiro', 'shai-cli', 'shai-http'.
    identifier VARCHAR(128) NOT NULL,
    name VARCHAR(255) NOT NULL,
    version VARCHAR(64) NOT NULL,
    vendor VARCHAR(255),
    -- Installation source (trusted registry/URL) and method ('pip','npm',
    -- 'binary','image'). Integrity material (sha256) is kept in install_method
    -- payload so verification is explicit.
    install_source TEXT,
    install_method JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- Protocols this runtime speaks: e.g. ['acp'], ['cli'], ['http','sse'].
    supported_protocols JSONB NOT NULL DEFAULT '[]'::jsonb,
    dependencies JSONB NOT NULL DEFAULT '[]'::jsonb,
    required_permissions JSONB NOT NULL DEFAULT '[]'::jsonb,
    execution_modes JSONB NOT NULL DEFAULT '[]'::jsonb,
    health_check JSONB NOT NULL DEFAULT '{}'::jsonb,
    config_schema JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(32) NOT NULL DEFAULT 'registered'
        CHECK (status IN ('registered', 'disabled')),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_agent_runtime UNIQUE (tenant_id, identifier)
);

CREATE INDEX IF NOT EXISTS idx_agent_runtimes_tenant ON agent_runtimes(tenant_id);
