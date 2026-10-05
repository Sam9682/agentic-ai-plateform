-- Migration: Add serverless jobs tables for Docker execution service
-- Date: 2026-06-15

-- Job queue table
CREATE TABLE IF NOT EXISTS serverless_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id INTEGER NOT NULL REFERENCES users(id),
    image TEXT NOT NULL,
    command JSONB NOT NULL,
    environment JSONB DEFAULT '{}',
    timeout_seconds INTEGER NOT NULL DEFAULT 300 CHECK (timeout_seconds BETWEEN 1 AND 3600),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'completed', 'failed', 'timeout', 'cancelled')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    exit_code INTEGER,
    worker_id TEXT,
    CONSTRAINT fk_user FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Indexes for queue operations
CREATE INDEX idx_serverless_jobs_status ON serverless_jobs(status);
CREATE INDEX idx_serverless_jobs_user_id ON serverless_jobs(user_id);
CREATE INDEX idx_serverless_jobs_pending ON serverless_jobs(status, created_at) WHERE status = 'pending';

-- Job output logs (stdout/stderr streaming)
CREATE TABLE IF NOT EXISTS serverless_job_logs (
    id BIGSERIAL PRIMARY KEY,
    job_id UUID NOT NULL REFERENCES serverless_jobs(id) ON DELETE CASCADE,
    stream TEXT NOT NULL CHECK (stream IN ('stdout', 'stderr')),
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_serverless_job_logs_job_id ON serverless_job_logs(job_id, created_at);

-- Job structured results
CREATE TABLE IF NOT EXISTS serverless_job_results (
    job_id UUID PRIMARY KEY REFERENCES serverless_jobs(id) ON DELETE CASCADE,
    result JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
