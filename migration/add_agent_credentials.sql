-- Migration: Encrypted-at-rest credential vault for ARO/ZAF (Task 3).
-- Date: 2026-10-30
--
-- Infrastructure credentials (OpenStack/OVHcloud/AWS app-credentials, etc.)
-- must never be exposed to agent prompts or unrestricted environment variables
-- (SRS §4.6, §9). They are stored here encrypted with app-level AEAD; the
-- column holds ciphertext only. The plaintext never touches the database.
-- Per-task execution mints short-lived scoped tokens referencing a credential,
-- so an agent receives a narrow, expiring capability rather than the secret.
--
-- Idempotent: IF NOT EXISTS throughout.

CREATE TABLE IF NOT EXISTS agent_credentials (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    -- Optional binding to a specific agent; NULL means tenant-wide.
    agent_id VARCHAR(255),
    name VARCHAR(255) NOT NULL,
    -- Credential kind, e.g. 'openstack', 'ovh', 'aws', 'generic'.
    kind VARCHAR(64) NOT NULL DEFAULT 'generic',
    -- Scope string limiting what a minted token may do, e.g.
    -- 'openstack:compute:read'. Enforced by the infra proxy/PDP.
    scope VARCHAR(512) NOT NULL DEFAULT '',
    -- AEAD ciphertext (base64). NEVER plaintext.
    ciphertext TEXT NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'revoked')),
    rotated_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_agent_credential_name UNIQUE (tenant_id, name)
);

CREATE INDEX IF NOT EXISTS idx_agent_credentials_tenant
    ON agent_credentials(tenant_id);
CREATE INDEX IF NOT EXISTS idx_agent_credentials_agent
    ON agent_credentials(tenant_id, agent_id);

-- Short-lived scoped tokens minted from a credential for a single execution.
-- The token value is stored hashed (never in the clear); verification compares
-- hashes. Expired/used tokens are rejected.
CREATE TABLE IF NOT EXISTS agent_scoped_tokens (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    credential_id BIGINT NOT NULL REFERENCES agent_credentials(id) ON DELETE CASCADE,
    agent_id VARCHAR(255),
    token_hash VARCHAR(128) UNIQUE NOT NULL,
    scope VARCHAR(512) NOT NULL DEFAULT '',
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    revoked BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_agent_scoped_tokens_cred
    ON agent_scoped_tokens(credential_id);
CREATE INDEX IF NOT EXISTS idx_agent_scoped_tokens_expiry
    ON agent_scoped_tokens(expires_at);
