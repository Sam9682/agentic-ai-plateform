-- Migration: ZAF governance (policies, decisions, agent permissions) (Task 11).
-- Date: 2026-10-30
--
-- The policy decision point (PDP) evaluates every protected action against
-- versioned policies and per-agent permissions, recording an immutable decision
-- for audit. Deny takes precedence over allow; when the PDP cannot evaluate, it
-- fails closed (DENY). Policies are tenant-scoped and versioned so a change is
-- additive and auditable.
--
-- Idempotent: IF NOT EXISTS.

CREATE TABLE IF NOT EXISTS governance_policies (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    scope VARCHAR(32) NOT NULL DEFAULT 'tenant'
        CHECK (scope IN ('tenant', 'agent')),
    -- The rule set as JSON (list of rules with action/condition/decision).
    rules JSONB NOT NULL DEFAULT '[]'::jsonb,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_governance_policy_version UNIQUE (tenant_id, name, version)
);

CREATE INDEX IF NOT EXISTS idx_governance_policies_tenant
    ON governance_policies(tenant_id, enabled);

-- Per-agent permissions (action globs the agent is explicitly granted).
CREATE TABLE IF NOT EXISTS agent_permissions (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    agent_id BIGINT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    action_glob VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_agent_permission UNIQUE (tenant_id, agent_id, action_glob)
);

CREATE INDEX IF NOT EXISTS idx_agent_permissions_agent
    ON agent_permissions(tenant_id, agent_id);

-- Immutable record of every authorization decision for audit.
CREATE TABLE IF NOT EXISTS governance_decisions (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    agent_identity VARCHAR(512),
    action VARCHAR(255) NOT NULL,
    resource TEXT,
    decision VARCHAR(32) NOT NULL
        CHECK (decision IN ('ALLOW', 'DENY', 'REQUIRE_APPROVAL', 'QUARANTINE')),
    matched_rule JSONB,
    risk_score INTEGER NOT NULL DEFAULT 0,
    reason TEXT,
    params_hash VARCHAR(128),
    decided_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_governance_decisions_tenant
    ON governance_decisions(tenant_id, decided_at DESC);
CREATE INDEX IF NOT EXISTS idx_governance_decisions_agent
    ON governance_decisions(tenant_id, agent_identity);
