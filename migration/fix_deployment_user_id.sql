-- Fix deployment records that have incorrect user_id
-- This happens when admin clones applications for other users
-- The deployment record was created with admin's user_id instead of target user's user_id

-- Step 1: Identify incorrect deployments by matching deployment_path with actual user
-- deployment_path format: /home/ubuntu/deployments/{username}/{app-name}

-- For each deployment, extract username from deployment_path and update user_id
UPDATE deployments d
SET user_id = u.id
FROM users u
WHERE d.deployment_path LIKE '/home/ubuntu/deployments/' || u.username || '/%'
  AND d.user_id != u.id;

-- Verify the fix
SELECT 
    d.id,
    d.user_id,
    u.username as current_user,
    d.deployment_path,
    d.application_name,
    CASE 
        WHEN d.deployment_path LIKE '/home/ubuntu/deployments/' || u.username || '/%' THEN 'CORRECT'
        ELSE 'MISMATCH'
    END as status
FROM deployments d
JOIN users u ON d.user_id = u.id
ORDER BY d.id;
