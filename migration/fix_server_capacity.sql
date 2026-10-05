-- Fix servers with NULL capacity values
UPDATE servers 
SET server_capacity_appli_max = 100 
WHERE server_capacity_appli_max IS NULL;

UPDATE servers 
SET server_capacity_user_max = 20 
WHERE server_capacity_user_max IS NULL;
