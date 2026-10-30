-- Migration: Agent identity + configuration for ARO (Task 7).
-- Date: 2026-10-30
--
-- An agent is a managed instance of a registered runtime, with a unique
-- zero-trust identity of the form agent://{tenant-slug}/{name}, independent of
-- the underlying model provider. It carries its runtime, execution environment,
-- owner, permissions, assigned policy references, credential references and
-- lifecycle status.
--
-- Idempotent: IF NOT EXISTS + ON CONFLICT.

CREATE TABLE IF NOT EXISTS agents (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    -- Unique zero-trust identity string, e.g. 'agent://default/infra-agent-01'.
    identity VARCHAR(512) NOT NULL,
    name VARCHAR(255) NOT NULL,
    runtime_id BIGINT NOT NULL REFERENCES agent_runtimes(id) ON DELETE RESTRICT,
    environment_id BIGINT REFERENCES execution_environments(id) ON DELETE SET NULL,
    owner_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'REGISTERED'
        CHECK (status IN (
            'REGISTERED', 'INSTALLING', 'INSTALLED', 'CONFIGURING', 'READY',
            'STARTING', 'RUNNING', 'STOPPING', 'STOPPED',
            'FAILED', 'UNHEALTHY', 'QUARANTINED', 'TERMINATED'
        )),
    configuration JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- Permissions granted to the agent (action globs), e.g.
    -- ['openstack.server.list', 'openstack.server.get'].
    permissions JSONB NOT NULL DEFAULT '[]'::jsonb,
    policy_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    credential_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_agent_identity UNIQUE (tenant_id, identity),
    CONSTRAINT uq_agent_name UNIQUE (tenant_id, name)
);

CREATE INDEX IF NOT EXISTS idx_agents_tenant ON agents(tenant_id);
CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(tenant_id, status);
