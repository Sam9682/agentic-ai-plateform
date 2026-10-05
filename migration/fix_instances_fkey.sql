-- Add user_id to instances table to properly reference services
ALTER TABLE instances ADD COLUMN IF NOT EXISTS user_id BIGINT;

-- Update instances to match their service's user_id
UPDATE instances SET user_id = s.user_id 
FROM services s 
WHERE instances.service_name = s.name AND instances.user_id IS NULL;

-- Make user_id NOT NULL
ALTER TABLE instances ALTER COLUMN user_id SET NOT NULL;

-- Add foreign key constraint referencing the composite key
ALTER TABLE instances ADD CONSTRAINT instances_service_fkey 
    FOREIGN KEY (service_name, user_id) REFERENCES services(name, user_id);

-- Add foreign key for user_id
ALTER TABLE instances ADD CONSTRAINT instances_user_id_fkey 
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
