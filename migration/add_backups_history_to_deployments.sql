-- Add backups_history column to deployments table
-- This column stores the list of backup links for the application's PostgreSQL database

ALTER TABLE deployments 
ADD COLUMN IF NOT EXISTS backups_history JSONB DEFAULT '[]'::jsonb;

-- Add comment to document the column
COMMENT ON COLUMN deployments.backups_history IS 'JSON array containing backup history with links to PostgreSQL database backups';

-- Create index for better query performance on JSONB column
CREATE INDEX IF NOT EXISTS idx_deployments_backups_history ON deployments USING GIN (backups_history);
