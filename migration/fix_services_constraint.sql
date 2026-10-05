-- Fix the constraint issue
-- Drop the foreign key that depends on services_name_key
ALTER TABLE instances DROP CONSTRAINT IF EXISTS instances_service_name_fkey;

-- Drop the old unique constraint
ALTER TABLE services DROP CONSTRAINT IF EXISTS services_name_key;

-- Add new unique constraint on (name, user_id)
ALTER TABLE services ADD CONSTRAINT services_name_user_id_key UNIQUE (name, user_id);

-- Recreate the foreign key to reference the new constraint
ALTER TABLE instances ADD CONSTRAINT instances_service_name_fkey 
    FOREIGN KEY (service_name) REFERENCES services(name);
