-- Migration: tamper-evident hash chain over agent_events (ABF Phase 2).
-- Date: 2026-11-21
--
-- Kept in its own file so a failure here (it is the only migration of the
-- chain that defines a PL/pgSQL function) cannot roll back add_abf.sql.
--
-- Model (see src/abf/audit_chain.py):
--   * Events are inserted exactly as before (no hashing on the hot path).
--   * A sealing pass, serialized per tenant by an advisory lock, assigns
--     chain_seq = 1, 2, 3 ... and record_hash = sha256(prev_hash || canonical
--     event) in insertion (id) order.
--   * The trigger below rejects any UPDATE that changes event content, and any
--     UPDATE at all of an already-sealed row. Sealing (NULL -> value on the
--     three chain columns) is the only permitted update.
--
-- What this does NOT guarantee (documented, not hidden): a database superuser
-- can disable the trigger and rewrite the whole chain consistently, and
-- DELETE is not blocked (tenant deletion cascades). Deletion of a sealed row
-- is detected by the verifier as a chain_seq gap; truncation of the tail is
-- detected only when the exported head hash is compared with an external copy.
--
-- Idempotent: ADD COLUMN IF NOT EXISTS / CREATE OR REPLACE / DROP TRIGGER IF EXISTS.

ALTER TABLE agent_events
    ADD COLUMN IF NOT EXISTS chain_seq BIGINT,
    ADD COLUMN IF NOT EXISTS prev_hash VARCHAR(64),
    ADD COLUMN IF NOT EXISTS record_hash VARCHAR(64);

CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_events_chain_seq
    ON agent_events(tenant_id, chain_seq)
    WHERE chain_seq IS NOT NULL;
-- Sealing scans the unsealed tail in id order.
CREATE INDEX IF NOT EXISTS idx_agent_events_unsealed
    ON agent_events(tenant_id, id)
    WHERE record_hash IS NULL;

CREATE OR REPLACE FUNCTION agent_events_guard_update() RETURNS trigger AS $$
BEGIN
    IF OLD.record_hash IS NOT NULL THEN
        RAISE EXCEPTION 'agent_events row % is sealed and immutable', OLD.id;
    END IF;
    IF (to_jsonb(NEW) - ARRAY['chain_seq', 'prev_hash', 'record_hash'])
       IS DISTINCT FROM
       (to_jsonb(OLD) - ARRAY['chain_seq', 'prev_hash', 'record_hash']) THEN
        RAISE EXCEPTION 'agent_events is append-only: content of row % cannot change', OLD.id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_agent_events_guard_update ON agent_events;
CREATE TRIGGER trg_agent_events_guard_update
    BEFORE UPDATE ON agent_events
    FOR EACH ROW EXECUTE FUNCTION agent_events_guard_update();
