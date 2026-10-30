-- Migration: Human approval workflow for ZAF (Task 12).
-- Date: 2026-10-30
--
-- When the PDP returns REQUIRE_APPROVAL, a pending approval is created and the
-- action is blocked until a human decides. Every approval is bound to the exact
-- action + parameters via a hash; a modified request produces a different hash
-- and therefore requires a NEW approval (SRS §4.5). Records are append-only for
-- audit (the decision is set once).
--
-- Idempotent: IF NOT EXISTS.

CREATE TABLE IF NOT EXISTS approval_requests (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    agent_identity VARCHAR(512),
    action VARCHAR(255) NOT NULL,
    resource TEXT,
    params JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- Hash binding this approval to the exact action + params.
    params_hash VARCHAR(128) NOT NULL,
    risk_explanation TEXT,
    triggering_policy JSONB,
    status VARCHAR(16) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected', 'expired')),
    approver_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    decided_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_approval_requests_tenant
    ON approval_requests(tenant_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_approval_requests_hash
    ON approval_requests(tenant_id, params_hash);
