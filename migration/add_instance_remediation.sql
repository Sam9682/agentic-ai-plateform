-- Migration: Instance remediation state for runtime execution hardening.
-- Date: 2026-10-12
--
-- Additive, idempotent columns on `instances` that back the reconciliation
-- remediation state machine (health probe grace windows, crash-loop capping,
-- restart/replace escalation) and the needs-attention surface. Every statement
-- is safe to run repeatedly: columns use ADD COLUMN IF NOT EXISTS and the index
-- uses CREATE INDEX IF NOT EXISTS. Nothing is dropped or retyped.

-- Consecutive failed-start counter used by the crash-loop cap. Reset to 0 on a
-- successful/healthy start; incremented on each failed start attempt.
ALTER TABLE instances ADD COLUMN IF NOT EXISTS restart_attempts INTEGER NOT NULL DEFAULT 0;

-- Set when remediation can no longer recover the instance automatically
-- (restart and replace exhausted); surfaces the instance for operator review.
ALTER TABLE instances ADD COLUMN IF NOT EXISTS needs_attention BOOLEAN NOT NULL DEFAULT FALSE;

-- Marks an instance that has already been replaced once, so the remediation
-- state machine escalates to needs-attention rather than replacing again.
ALTER TABLE instances ADD COLUMN IF NOT EXISTS replaced BOOLEAN NOT NULL DEFAULT FALSE;

-- When the instance's current container was (re)started; anchors the grace
-- window and start-up health evaluation.
ALTER TABLE instances ADD COLUMN IF NOT EXISTS started_at TIMESTAMP WITH TIME ZONE;

-- Health failures before this timestamp are treated as within the start-up
-- grace window and do not trigger remediation.
ALTER TABLE instances ADD COLUMN IF NOT EXISTS grace_until TIMESTAMP WITH TIME ZONE;

-- Supports fast lookup of instances flagged for operator attention.
CREATE INDEX IF NOT EXISTS idx_instances_needs_attention ON instances(needs_attention);
