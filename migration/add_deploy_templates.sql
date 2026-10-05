-- Migration: Add deploy templates catalog and sandbox labeling
-- Feature: onboarding-experience (Req 7.1, 7.2, 2.4, 3.1, 3.2)

-- Deploy templates catalog (Req 7.1, 7.2)
CREATE TABLE IF NOT EXISTS deploy_templates (
    id BIGSERIAL PRIMARY KEY,
    template_id VARCHAR(63) UNIQUE NOT NULL,       -- stable identifier used by CLI/MCP/REST
    app_type VARCHAR(64) NOT NULL,                 -- static_site | fastapi | n8n | ollama | jupyter | vector_db
    display_name VARCHAR(255) NOT NULL,
    source_image TEXT NOT NULL,                    -- docker image ref OR git URL (Req 7.2)
    ports JSONB NOT NULL,                          -- [{"container": 8080, "protocol": "http"}] >=1 (Req 7.2)
    environment JSONB NOT NULL DEFAULT '[]',       -- [{"name": "KEY", "value": "V"}] (Req 7.2)
    memory_mb INTEGER NOT NULL CHECK (memory_mb BETWEEN 64 AND 65536),        -- (Req 7.2)
    cpu_cores NUMERIC(4,1) NOT NULL CHECK (cpu_cores BETWEEN 0.1 AND 64),     -- (Req 7.2)
    timeout_seconds INTEGER NOT NULL DEFAULT 300 CHECK (timeout_seconds BETWEEN 1 AND 3600),
    enabled BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_deploy_templates_type ON deploy_templates(app_type);

-- Sandbox labeling (Req 2.4, 3.1, 3.2)
-- Distinguish the demo account (Req 3.1). Additive, nullable for existing rows.
ALTER TABLE users ADD COLUMN IF NOT EXISTS account_type VARCHAR(32);
-- Value 'sandbox demo' marks the Demo_User.

-- Mark deployments that belong to the sandbox (Req 2.4, 3.2).
ALTER TABLE deployments ADD COLUMN IF NOT EXISTS is_sandbox BOOLEAN NOT NULL DEFAULT false;

-- Idempotent seed of the six built-in templates (Req 7.1).
-- Each template uses valid bounded fields (Req 7.2). ON CONFLICT keeps the seed idempotent.
INSERT INTO deploy_templates
    (template_id, app_type, display_name, source_image, ports, environment, memory_mb, cpu_cores, timeout_seconds)
VALUES
    (
        'static-site',
        'static_site',
        'Static Website',
        'nginx:1.27-alpine',
        '[{"container": 80, "protocol": "http"}]'::jsonb,
        '[]'::jsonb,
        128,
        0.5,
        300
    ),
    (
        'fastapi-starter',
        'fastapi',
        'FastAPI Application',
        'tiangolo/uvicorn-gunicorn-fastapi:python3.11',
        '[{"container": 80, "protocol": "http"}]'::jsonb,
        '[{"name": "MODULE_NAME", "value": "app.main"}]'::jsonb,
        512,
        1.0,
        300
    ),
    (
        'n8n',
        'n8n',
        'n8n Workflow Automation',
        'n8nio/n8n:latest',
        '[{"container": 5678, "protocol": "http"}]'::jsonb,
        '[{"name": "N8N_PORT", "value": "5678"}]'::jsonb,
        1024,
        1.0,
        600
    ),
    (
        'ollama',
        'ollama',
        'Ollama LLM Runtime',
        'ollama/ollama:latest',
        '[{"container": 11434, "protocol": "http"}]'::jsonb,
        '[{"name": "OLLAMA_HOST", "value": "0.0.0.0"}]'::jsonb,
        4096,
        2.0,
        1200
    ),
    (
        'jupyter',
        'jupyter',
        'Jupyter Notebook',
        'jupyter/base-notebook:latest',
        '[{"container": 8888, "protocol": "http"}]'::jsonb,
        '[{"name": "JUPYTER_ENABLE_LAB", "value": "yes"}]'::jsonb,
        2048,
        1.0,
        600
    ),
    (
        'vector-db',
        'vector_db',
        'Qdrant Vector Database',
        'qdrant/qdrant:latest',
        '[{"container": 6333, "protocol": "http"}]'::jsonb,
        '[]'::jsonb,
        1024,
        1.0,
        300
    )
ON CONFLICT (template_id) DO NOTHING;
