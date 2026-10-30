-- Migration: Governed MCP registry for ZAF (Task 13).
-- Date: 2026-10-30
--
-- The ZAF MCP gateway mediates agent tool invocations. Registered MCP servers
-- and their tools are tenant-scoped; each tool maps to a canonical action
-- string the PDP evaluates. Direct agent->MCP connections that bypass the
-- gateway are a reduced-governance mode and are flagged as such.
--
-- Idempotent: IF NOT EXISTS + ON CONFLICT.

CREATE TABLE IF NOT EXISTS mcp_servers (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    transport VARCHAR(32) NOT NULL DEFAULT 'stdio'
        CHECK (transport IN ('stdio', 'http', 'sse')),
    endpoint TEXT,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_mcp_server UNIQUE (tenant_id, name)
);

CREATE TABLE IF NOT EXISTS mcp_tools (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    server_id BIGINT NOT NULL REFERENCES mcp_servers(id) ON DELETE CASCADE,
    tool_name VARCHAR(255) NOT NULL,
    -- Canonical action the PDP evaluates for this tool, e.g. 'mcp.deploy_template'.
    canonical_action VARCHAR(255) NOT NULL,
    -- Optional JSON-schema-ish parameter spec for validation.
    param_schema JSONB NOT NULL DEFAULT '{}'::jsonb,
    rate_limit_per_minute INTEGER NOT NULL DEFAULT 60,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_mcp_tool UNIQUE (tenant_id, server_id, tool_name)
);

CREATE INDEX IF NOT EXISTS idx_mcp_tools_tenant ON mcp_tools(tenant_id, server_id);
