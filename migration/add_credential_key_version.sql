-- Migration: Additive, backward-compatible columns for ZAF Phase 3 hardening.
-- Date: 2026-11-15
--
-- This migration is purely additive and backward compatible (SRS R4.3, R4.4,
-- R7.1, R11.4). It drops no column and makes nothing NOT NULL, so every
-- pre-existing row keeps its current shape and reads as a legacy value.
--
-- 1. agent_credentials.key_version — tags each stored ciphertext with the
--    key-derivation scheme used to encrypt it. New v1 writes set 'v1'; a NULL
--    value denotes a legacy v0 (unsalted) ciphertext, so existing rows decrypt
--    through the preserved legacy path without migration.
-- 2. auth_tokens.token_mac — holds the keyed MAC computed over the stored SSO
--    token hash. NULL for tokens minted before this migration; validation
--    treats a NULL MAC as a legacy token until it is re-minted.
--
-- Idempotent: ADD COLUMN IF NOT EXISTS throughout. Safe to run repeatedly.

-- Key-derivation version tag for versioned at-rest credential encryption.
-- NULL = legacy v0 (unsalted SHA-256) ciphertext.
ALTER TABLE agent_credentials
    ADD COLUMN IF NOT EXISTS key_version VARCHAR(8);

-- Keyed MAC over the stored SSO token hash.
-- NULL for pre-existing tokens minted before MAC protection was added.
ALTER TABLE auth_tokens
    ADD COLUMN IF NOT EXISTS token_mac VARCHAR(128);
