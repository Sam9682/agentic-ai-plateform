-- Migration: Multi-tenant foundation for the Agent Runtime Orchestrator (ARO)
-- and Zero-trust Agent Firewall (ZAF).
-- Date: 2026-10-30
--
-- The platform was originally single-org (data scoped per user_id, with a
-- magic 'admin' username). ARO/ZAF require real multi-tenancy: every ARO/ZAF
-- entity belongs to a tenant, and isolation is enforced at the DB, API and
-- execution layers. This migration introduces the tenant model and a default
-- tenant that every existing user is mapped into, so pre-existing data keeps
-- working while new features gain tenant scoping.
--
-- Idempotent: safe to run repeatedly (IF NOT EXISTS + ON CONFLICT).

-- A tenant (organization). The default tenant (slug 'default') is created so
-- existing users have somewhere to belong.
CREATE TABLE IF NOT EXISTS tenants (
    id BIGSERIAL PRIMARY KEY,
    slug VARCHAR(64) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'suspended', 'archived')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Membership of a user in a tenant, with a role. A user may belong to several
-- tenants; the role governs what they can do within that tenant.
--   viewer   - read-only access to the tenant's ARO/ZAF surface
--   operator - manage agents/tasks, request approvals
--   admin    - manage policies, approve/reject, manage members
CREATE TABLE IF NOT EXISTS tenant_members (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role VARCHAR(32) NOT NULL DEFAULT 'operator'
        CHECK (role IN ('viewer', 'operator', 'admin')),
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_tenant_member UNIQUE (tenant_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_tenant_members_user ON tenant_members(user_id);
CREATE INDEX IF NOT EXISTS idx_tenant_members_tenant ON tenant_members(tenant_id);

-- Seed the default tenant.
INSERT INTO tenants (slug, name)
VALUES ('default', 'Default Tenant')
ON CONFLICT (slug) DO NOTHING;

-- Map every existing user into the default tenant as their default membership.
-- The 'admin' user becomes a tenant admin; everyone else is an operator.
INSERT INTO tenant_members (tenant_id, user_id, role, is_default)
SELECT t.id,
       u.id,
       CASE WHEN u.username = 'admin' THEN 'admin' ELSE 'operator' END,
       TRUE
FROM users u
CROSS JOIN tenants t
WHERE t.slug = 'default'
ON CONFLICT (tenant_id, user_id) DO NOTHING;
