-- Extend the per-application port allocation from 4 ports (2 HTTP + 2 HTTPS)
-- to 12 ports (6 HTTP + 6 HTTPS) per application.
--
-- The existing columns http_port, https_port, http_port2, https_port2 are kept.
-- This migration adds the 8 new columns for ports 3 through 6.
-- Safe to run multiple times (IF NOT EXISTS).

ALTER TABLE user_applications
    ADD COLUMN IF NOT EXISTS http_port3 INTEGER,
    ADD COLUMN IF NOT EXISTS https_port3 INTEGER,
    ADD COLUMN IF NOT EXISTS http_port4 INTEGER,
    ADD COLUMN IF NOT EXISTS https_port4 INTEGER,
    ADD COLUMN IF NOT EXISTS http_port5 INTEGER,
    ADD COLUMN IF NOT EXISTS https_port5 INTEGER,
    ADD COLUMN IF NOT EXISTS http_port6 INTEGER,
    ADD COLUMN IF NOT EXISTS https_port6 INTEGER;

-- Document the new columns
COMMENT ON COLUMN user_applications.http_port3  IS 'Third HTTP port allocated to the application';
COMMENT ON COLUMN user_applications.https_port3 IS 'Third HTTPS port allocated to the application';
COMMENT ON COLUMN user_applications.http_port4  IS 'Fourth HTTP port allocated to the application';
COMMENT ON COLUMN user_applications.https_port4 IS 'Fourth HTTPS port allocated to the application';
COMMENT ON COLUMN user_applications.http_port5  IS 'Fifth HTTP port allocated to the application';
COMMENT ON COLUMN user_applications.https_port5 IS 'Fifth HTTPS port allocated to the application';
COMMENT ON COLUMN user_applications.http_port6  IS 'Sixth HTTP port allocated to the application';
COMMENT ON COLUMN user_applications.https_port6 IS 'Sixth HTTPS port allocated to the application';

-- Backfill the new ports for existing rows based on the sequential allocation
-- scheme (12 consecutive ports starting at http_port). The columns are laid out
-- as alternating HTTP/HTTPS pairs, so:
--   http_port  = base + 0    https_port  = base + 1
--   http_port2 = base + 2    https_port2 = base + 3
--   http_port3 = base + 4    https_port3 = base + 5
--   http_port4 = base + 6    https_port4 = base + 7
--   http_port5 = base + 8    https_port5 = base + 9
--   http_port6 = base + 10   https_port6 = base + 11
UPDATE user_applications
SET http_port3  = http_port + 4,
    https_port3 = http_port + 5,
    http_port4  = http_port + 6,
    https_port4 = http_port + 7,
    http_port5  = http_port + 8,
    https_port5 = http_port + 9,
    http_port6  = http_port + 10,
    https_port6 = http_port + 11
WHERE http_port IS NOT NULL
  AND http_port3 IS NULL;
