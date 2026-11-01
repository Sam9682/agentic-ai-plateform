-- Migration: PHASE 5 — Agent Supervisor delegation schema (Task 8.1).
-- Date: 2026-11-20
--
-- Additive, idempotent, re-runnable extension on top of the Phase 1–4 platform
-- and the Phase 5 Half-A cost/anomaly migration (add_agent_cost_records.sql).
-- Every change is purely additive (nullable/defaulted columns appended to
-- agent_tasks plus new tables created IF NOT EXISTS) so existing rows and
-- writers stay valid and the verified Phase 1–4 suites remain green. Nothing is
-- dropped or retyped — in particular the agent_tasks status CHECK constraint is
-- left untouched (Req 13.6).
--
--   * agent_tasks gains supervisor decomposition columns (parent_task_id,
--     depends_on, role_name) so a decomposed Parent_Task can link its
--     Child_Tasks, carry dependency references, and record the selected Role
--     (Req 8.1, 8.3, 9.1). All nullable/defaulted so the Phase 2 task queue and
--     its writers stay backward compatible.
--   * supervisor_delegations: the delegation ledger binding a parent task to
--     each delegated child task, the selected role, and the effective
--     (intersected) governance scope written into the child policy_context
--     (Req 9.1, 10.1). Tenant-scoped and keyed back to agent_tasks.
--   * supervisor_roles (optional, table-backed): an additive persistence of the
--     configurable Role model (Req 7.1, 7.3). Roles are primarily loaded from
--     conf/supervisor_roles.yaml; this table exists only so a deployment MAY
--     persist role definitions without a code change. Empty by default.
--
-- Idempotent: IF NOT EXISTS / ADD COLUMN IF NOT EXISTS. Running this script more
-- than once is a no-op (Req 13.6).

-- --------------------------------------------------------------------------
-- agent_tasks: supervisor decomposition columns (Req 8.1, 8.3, 9.1). Additive
-- and nullable/defaulted so the existing Phase 2 task queue stays valid. The
-- status CHECK constraint is intentionally NOT touched here.
-- --------------------------------------------------------------------------
ALTER TABLE agent_tasks
    ADD COLUMN IF NOT EXISTS parent_task_id BIGINT,
    ADD COLUMN IF NOT EXISTS depends_on JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS role_name VARCHAR(64);

-- Supervisor coordination reads child tasks by their parent (Req 9.2, 9.3).
CREATE INDEX IF NOT EXISTS idx_agent_tasks_parent
    ON agent_tasks(tenant_id, parent_task_id)
    WHERE parent_task_id IS NOT NULL;

-- --------------------------------------------------------------------------
-- supervisor_delegations: delegation ledger (Req 9.1, 10.1). Each row binds a
-- parent task to a delegated child task, the role selected for the child, and
-- the effective (intersected) scope inherited by the child. effective_scope is
-- the parent ∩ child_requested result propagated into the child policy_context.
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS supervisor_delegations (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    delegation_ref VARCHAR(64),
    parent_task_id BIGINT,
    child_task_id BIGINT REFERENCES agent_tasks(id) ON DELETE CASCADE,
    role_name VARCHAR(64),
    effective_scope JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

-- Budget aggregation and coordination read delegations by parent per tenant
-- (Req 11.2) and by the delegation reference used on cost records (Req 11.1).
CREATE INDEX IF NOT EXISTS idx_supervisor_delegations_parent
    ON supervisor_delegations(tenant_id, parent_task_id);
CREATE INDEX IF NOT EXISTS idx_supervisor_delegations_ref
    ON supervisor_delegations(tenant_id, delegation_ref);
CREATE INDEX IF NOT EXISTS idx_supervisor_delegations_child
    ON supervisor_delegations(tenant_id, child_task_id);

-- --------------------------------------------------------------------------
-- supervisor_roles (optional table-backed Role persistence, Req 7.1, 7.3).
-- Roles are configuration, not code: the canonical source is
-- conf/supervisor_roles.yaml loaded by supervisor.load_roles. This table is an
-- additive convenience so a deployment MAY persist role definitions. Adding a
-- role to configuration (file or this table) makes it selectable with no code
-- change (Req 7.4). capabilities/default_scope mirror the YAML entries.
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS supervisor_roles (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT REFERENCES tenants(id) ON DELETE CASCADE,
    name VARCHAR(64) NOT NULL,
    capabilities JSONB NOT NULL DEFAULT '[]'::jsonb,
    default_scope JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_supervisor_roles_name
    ON supervisor_roles(tenant_id, name);
