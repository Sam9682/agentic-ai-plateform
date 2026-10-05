-- Migration: Add MIG (Multi-Instance GPU) shared GPU support tables
-- Date: 2025-07-15

-- Add shared_gpu_enabled flag to servers table
ALTER TABLE servers ADD COLUMN IF NOT EXISTS shared_gpu_enabled BOOLEAN DEFAULT FALSE;

-- MIG profiles table (available GPU partition configurations per server)
CREATE TABLE IF NOT EXISTS mig_profiles (
    id SERIAL PRIMARY KEY,
    server_id INTEGER NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
    profile_name VARCHAR(64) NOT NULL,
    profile_id VARCHAR(128) NOT NULL,
    gpu_memory_gb INTEGER NOT NULL CHECK (gpu_memory_gb BETWEEN 1 AND 80),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (server_id, profile_name)
);

CREATE INDEX IF NOT EXISTS idx_mig_profiles_server_id ON mig_profiles(server_id);

-- MIG instances table (active GPU partitions per server)
CREATE TABLE IF NOT EXISTS mig_instances (
    id SERIAL PRIMARY KEY,
    server_id INTEGER NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
    instance_uuid VARCHAR(36) NOT NULL,
    profile_name VARCHAR(50) NOT NULL,
    gpu_memory_mb INTEGER NOT NULL CHECK (gpu_memory_mb BETWEEN 1 AND 81920),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (server_id, instance_uuid)
);

CREATE INDEX IF NOT EXISTS idx_mig_instances_server_id ON mig_instances(server_id);
