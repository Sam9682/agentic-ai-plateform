-- Migration: Add user_id to services table
-- Date: 2026

-- Add user_id column if it doesn't exist
ALTER TABLE services ADD COLUMN IF NOT EXISTS user_id BIGINT;

-- Set default user_id to admin user (id=1) for existing records
UPDATE services SET user_id = 1 WHERE user_id IS NULL;

-- Make user_id NOT NULL
ALTER TABLE services ALTER COLUMN user_id SET NOT NULL;

-- Drop old unique constraint on name
ALTER TABLE services DROP CONSTRAINT IF EXISTS services_name_key;

-- Add new unique constraint on (name, user_id)
ALTER TABLE services ADD CONSTRAINT services_name_user_id_key UNIQUE (name, user_id);

-- Add foreign key constraint
ALTER TABLE services ADD CONSTRAINT services_user_id_fkey 
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
