-- Migration: Runtime Security - agentic workload discovery, classification,
-- execution timelines, and alert-only anomaly detection.
-- Date: 2026-10-12
--
-- These tables back the native Runtime Security feature. Containers are
-- discovered on managed servers (including workloads the platform did not
-- launch) via SSH polling. The schema is intentionally transport-agnostic so a
-- push-based host sensor can write to the same tables later without rework.

-- One row per discovered container (per server). A container that reappears
-- after a restart keeps the same row keyed by (server_id, container_id).
CREATE TABLE IF NOT EXISTS runtime_containers (
    id BIGSERIAL PRIMARY KEY,
    server_id BIGINT NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
    container_id TEXT NOT NULL,
    name TEXT,
    image TEXT,
    runtime TEXT,
    state TEXT NOT NULL DEFAULT 'unknown',
    is_platform_managed BOOLEAN NOT NULL DEFAULT FALSE,
    classification TEXT NOT NULL DEFAULT 'unclassified'
        CHECK (classification IN ('probable_agent', 'unclassified')),
    confidence_score DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    classification_evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
    labels JSONB NOT NULL DEFAULT '{}'::jsonb,
    first_seen TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_seen TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_runtime_container UNIQUE (server_id, container_id)
);

CREATE INDEX IF NOT EXISTS idx_runtime_containers_server ON runtime_containers(server_id);
CREATE INDEX IF NOT EXISTS idx_runtime_containers_state ON runtime_containers(state);
CREATE INDEX IF NOT EXISTS idx_runtime_containers_classification ON runtime_containers(classification);

-- Time-series observations per container that build the execution timeline.
CREATE TABLE IF NOT EXISTS runtime_observations (
    id BIGSERIAL PRIMARY KEY,
    container_pk BIGINT NOT NULL REFERENCES runtime_containers(id) ON DELETE CASCADE,
    cpu_percent DOUBLE PRECISION,
    memory_bytes BIGINT,
    pids INTEGER,
    process_summary JSONB NOT NULL DEFAULT '[]'::jsonb,
    network_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    state TEXT,
    observed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_runtime_observations_container
    ON runtime_observations(container_pk, observed_at);

-- Alert-only anomalies. No enforcement is performed; status tracks review.
CREATE TABLE IF NOT EXISTS runtime_anomalies (
    id BIGSERIAL PRIMARY KEY,
    container_pk BIGINT NOT NULL REFERENCES runtime_containers(id) ON DELETE CASCADE,
    rule_id TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'low'
        CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
    status TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'acknowledged', 'resolved')),
    detected_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_runtime_anomalies_container
    ON runtime_anomalies(container_pk, detected_at);
CREATE INDEX IF NOT EXISTS idx_runtime_anomalies_status ON runtime_anomalies(status);

-- Audit of each scan run for observability.
CREATE TABLE IF NOT EXISTS runtime_scan_runs (
    id BIGSERIAL PRIMARY KEY,
    server_id BIGINT REFERENCES servers(id) ON DELETE SET NULL,
    started_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP WITH TIME ZONE,
    containers_seen INTEGER NOT NULL DEFAULT 0,
    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_runtime_scan_runs_server
    ON runtime_scan_runs(server_id, started_at);
