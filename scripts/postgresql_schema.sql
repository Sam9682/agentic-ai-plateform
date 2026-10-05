-- PostgreSQL Schema for AI-SwAutoMorph
-- Migration from SQLite to PostgreSQL

-- Enable UUID extension for better primary keys
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Users table
CREATE TABLE users (
    id BIGSERIAL PRIMARY KEY,
    username VARCHAR(255) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    first_name VARCHAR(255),
    last_name VARCHAR(255),
    suspended BOOLEAN DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Applications table
CREATE TABLE applications (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL,
    url TEXT,
    description TEXT,
    git_url TEXT,
    git_remote_url TEXT,
    git_local_url TEXT,
    git_repo_size INTEGER DEFAULT 50,
    docker_build_duration INTEGER,
    docker_start_duration INTEGER,
    docker_stop_duration INTEGER,
    docker_ps_duration INTEGER,
    docker_compose_ports TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Authentication tokens table for SSO
CREATE TABLE auth_tokens (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    token_hash VARCHAR(255) UNIQUE NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);

-- User application assignments table
CREATE TABLE user_applications (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    application_id BIGINT NOT NULL,
    url TEXT NOT NULL,
    http_port INTEGER,
    https_port INTEGER,
    http_port2 INTEGER,
    https_port2 INTEGER,
    http_port3 INTEGER,
    https_port3 INTEGER,
    http_port4 INTEGER,
    https_port4 INTEGER,
    http_port5 INTEGER,
    https_port5 INTEGER,
    http_port6 INTEGER,
    https_port6 INTEGER,
    others_port INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    FOREIGN KEY (application_id) REFERENCES applications (id) ON DELETE CASCADE,
    UNIQUE(user_id, application_id)
);

-- Servers table
CREATE TABLE servers (
    id BIGSERIAL PRIMARY KEY,
    server_ip INET UNIQUE NOT NULL,
    server_name VARCHAR(255) NOT NULL,
    server_capacity_user_max INTEGER NOT NULL,
    server_capacity_appli_max INTEGER NOT NULL,
    server_status VARCHAR(50) DEFAULT 'STAND_BY',
    server_type VARCHAR(50) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Deployments table
CREATE TABLE deployments (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    application_id BIGINT,
    application_name VARCHAR(255) NOT NULL,
    status VARCHAR(50) DEFAULT 'pending',
    deployment_path TEXT,
    git_url TEXT,
    swautomorph_url TEXT,
    gitea_branch_url TEXT,
    modification_history JSONB DEFAULT '[]'::jsonb,
    backups_history JSONB DEFAULT '[]'::jsonb,
    server_id BIGINT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    FOREIGN KEY (application_id) REFERENCES applications (id) ON DELETE SET NULL,
    FOREIGN KEY (server_id) REFERENCES servers (id) ON DELETE SET NULL
);

-- Add comments to document JSONB columns
COMMENT ON COLUMN deployments.modification_history IS 'JSON array containing modification history with branch names and Gitea URLs';
COMMENT ON COLUMN deployments.backups_history IS 'JSON array containing backup history with links to PostgreSQL database backups in S3';

-- Application costs table
CREATE TABLE application_costs (
    id BIGSERIAL PRIMARY KEY,
    application_id BIGINT NOT NULL,
    cost_per_day DECIMAL(10,2) DEFAULT 1.0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (application_id) REFERENCES applications (id) ON DELETE CASCADE
);

-- Billing activities table
CREATE TABLE billing_activities (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    application_id BIGINT NOT NULL,
    action VARCHAR(50) NOT NULL,
    started_at TIMESTAMP WITH TIME ZONE,
    stopped_at TIMESTAMP WITH TIME ZONE,
    duration_seconds INTEGER,
    cost_amount DECIMAL(10,2),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    FOREIGN KEY (application_id) REFERENCES applications (id) ON DELETE CASCADE
);

-- Users logs table for login/logout tracking
CREATE TABLE users_logs (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    username VARCHAR(255) NOT NULL,
    action VARCHAR(50) NOT NULL,
    datetime TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);

-- Payment modes table
CREATE TABLE payment_modes (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    payment_type VARCHAR(50) NOT NULL,
    bank_account VARCHAR(255),
    paypal_email VARCHAR(255),
    card_last_four VARCHAR(4),
    card_type VARCHAR(50),
    is_default BOOLEAN DEFAULT false,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);

-- Invoicing table
CREATE TABLE invoicing (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    invoice_month VARCHAR(7) NOT NULL, -- YYYY-MM format
    total_amount DECIMAL(10,2) NOT NULL,
    status VARCHAR(50) DEFAULT 'unpaid',
    payment_date TIMESTAMP WITH TIME ZONE,
    payment_mode_id BIGINT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    FOREIGN KEY (payment_mode_id) REFERENCES payment_modes (id) ON DELETE SET NULL
);

-- Configuration table for nested parameters
CREATE TABLE configuration (
    param_id BIGSERIAL PRIMARY KEY,
    parent VARCHAR(255),
    key VARCHAR(255),
    value TEXT
);

-- Services table - logical services with desired state (App Orchestrator)
CREATE TABLE services (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    image VARCHAR(255) NOT NULL,
    user_id BIGINT NOT NULL,
    desired_replicas INTEGER DEFAULT 1,
    ports TEXT,  -- JSON: {"80": "8080", "443": "8443"}
    environment TEXT,  -- JSON: {"ENV_VAR": "value"}
    volumes TEXT,  -- JSON: ["/host:/container"]
    health_check_path VARCHAR(255) DEFAULT '/health',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(name, user_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Instances table - actual running containers (App Orchestrator)
CREATE TABLE instances (
    id BIGSERIAL PRIMARY KEY,
    service_id BIGINT NOT NULL,
    instance_id VARCHAR(255) NOT NULL,  -- service_name-replica-N
    server_id BIGINT NOT NULL,
    service_name VARCHAR(255),
    container_id VARCHAR(255),
    status VARCHAR(50) DEFAULT 'pending',  -- pending, running, failed, stopped
    port INTEGER,
    health_status VARCHAR(50) DEFAULT 'unknown',  -- healthy, unhealthy, unknown
    last_health_check TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (server_id) REFERENCES servers (id),
    FOREIGN KEY (service_id) REFERENCES services (id) ON DELETE CASCADE,
    UNIQUE(service_id, instance_id)
);

-- Indexes for performance
CREATE INDEX idx_users_username ON users(username);
CREATE INDEX idx_services_name ON services(name);
CREATE INDEX idx_instances_service_id ON instances(service_id);
CREATE INDEX idx_instances_server_id ON instances(server_id);
CREATE INDEX idx_instances_status ON instances(status);
CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_auth_tokens_user_id ON auth_tokens(user_id);
CREATE INDEX idx_auth_tokens_expires_at ON auth_tokens(expires_at);
CREATE INDEX idx_applications_url ON applications(url);
CREATE INDEX idx_user_applications_user_id ON user_applications(user_id);
CREATE INDEX idx_user_applications_application_id ON user_applications(application_id);
CREATE INDEX idx_deployments_user_id ON deployments(user_id);
CREATE INDEX idx_deployments_application_id ON deployments(application_id);
CREATE INDEX idx_deployments_server_id ON deployments(server_id);
CREATE INDEX idx_deployments_status ON deployments(status);
CREATE INDEX idx_deployments_backups_history ON deployments USING GIN (backups_history);
CREATE INDEX idx_billing_activities_user_id ON billing_activities(user_id);
CREATE INDEX idx_billing_activities_application_id ON billing_activities(application_id);
CREATE INDEX idx_billing_activities_created_at ON billing_activities(created_at);
CREATE INDEX idx_users_logs_user_id ON users_logs(user_id);
CREATE INDEX idx_users_logs_datetime ON users_logs(datetime);

-- Trigger to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_deployments_updated_at BEFORE UPDATE ON deployments
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_application_costs_updated_at BEFORE UPDATE ON application_costs
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_services_updated_at BEFORE UPDATE ON services
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_instances_updated_at BEFORE UPDATE ON instances
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
