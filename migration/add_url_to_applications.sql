-- Add url column to applications table
-- This column stores the application's URL

ALTER TABLE applications 
ADD COLUMN IF NOT EXISTS url TEXT;

-- Add comment to document the column
COMMENT ON COLUMN applications.url IS 'Application URL for accessing the deployed application';

-- Create index for better query performance
CREATE INDEX IF NOT EXISTS idx_applications_url ON applications(url);
