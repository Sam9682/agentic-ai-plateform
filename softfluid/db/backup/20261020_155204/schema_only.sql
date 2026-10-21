--
-- PostgreSQL database dump
--

\restrict cUDEw26rh1T8n8c2zHkQrpaQV6lV2ienPxcn1fBS8BArcXvDSgY1A1bA92CtCZW

-- Dumped from database version 18.6 (Ubuntu 18.6-0ubuntu0.26.04.1)
-- Dumped by pg_dump version 18.6 (Ubuntu 18.6-0ubuntu0.26.04.1)

-- Started on 2026-10-20 15:52:05 UTC

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- TOC entry 2 (class 3079 OID 21872)
-- Name: uuid-ossp; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA public;


--
-- TOC entry 3865 (class 0 OID 0)
-- Dependencies: 2
-- Name: EXTENSION "uuid-ossp"; Type: COMMENT; Schema: -; Owner: 
--

COMMENT ON EXTENSION "uuid-ossp" IS 'generate universally unique identifiers (UUIDs)';


--
-- TOC entry 280 (class 1255 OID 22195)
-- Name: update_updated_at_column(); Type: FUNCTION; Schema: public; Owner: swautomorph
--

CREATE FUNCTION public.update_updated_at_column() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$;


ALTER FUNCTION public.update_updated_at_column() OWNER TO swautomorph;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- TOC entry 233 (class 1259 OID 22014)
-- Name: application_costs; Type: TABLE; Schema: public; Owner: swautomorph
--

CREATE TABLE public.application_costs (
    id bigint NOT NULL,
    application_id bigint NOT NULL,
    cost_per_day numeric(10,2) DEFAULT 1.0,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.application_costs OWNER TO swautomorph;

--
-- TOC entry 232 (class 1259 OID 22013)
-- Name: application_costs_id_seq; Type: SEQUENCE; Schema: public; Owner: swautomorph
--

CREATE SEQUENCE public.application_costs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.application_costs_id_seq OWNER TO swautomorph;

--
-- TOC entry 3866 (class 0 OID 0)
-- Dependencies: 232
-- Name: application_costs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.application_costs_id_seq OWNED BY public.application_costs.id;


--
-- TOC entry 223 (class 1259 OID 21903)
-- Name: applications; Type: TABLE; Schema: public; Owner: swautomorph
--

CREATE TABLE public.applications (
    id bigint NOT NULL,
    name character varying(255) NOT NULL,
    url text,
    description text,
    git_url text,
    git_remote_url text,
    git_local_url text,
    git_repo_size integer DEFAULT 50,
    docker_build_duration integer,
    docker_start_duration integer,
    docker_stop_duration integer,
    docker_ps_duration integer,
    docker_compose_ports text,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.applications OWNER TO swautomorph;

--
-- TOC entry 222 (class 1259 OID 21902)
-- Name: applications_id_seq; Type: SEQUENCE; Schema: public; Owner: swautomorph
--

CREATE SEQUENCE public.applications_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.applications_id_seq OWNER TO swautomorph;

--
-- TOC entry 3867 (class 0 OID 0)
-- Dependencies: 222
-- Name: applications_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.applications_id_seq OWNED BY public.applications.id;


--
-- TOC entry 225 (class 1259 OID 21918)
-- Name: auth_tokens; Type: TABLE; Schema: public; Owner: swautomorph
--

CREATE TABLE public.auth_tokens (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    token_hash character varying(255) NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.auth_tokens OWNER TO swautomorph;

--
-- TOC entry 224 (class 1259 OID 21917)
-- Name: auth_tokens_id_seq; Type: SEQUENCE; Schema: public; Owner: swautomorph
--

CREATE SEQUENCE public.auth_tokens_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.auth_tokens_id_seq OWNER TO swautomorph;

--
-- TOC entry 3868 (class 0 OID 0)
-- Dependencies: 224
-- Name: auth_tokens_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.auth_tokens_id_seq OWNED BY public.auth_tokens.id;


--
-- TOC entry 235 (class 1259 OID 22031)
-- Name: billing_activities; Type: TABLE; Schema: public; Owner: swautomorph
--

CREATE TABLE public.billing_activities (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    application_id bigint NOT NULL,
    action character varying(50) NOT NULL,
    started_at timestamp with time zone,
    stopped_at timestamp with time zone,
    duration_seconds integer,
    cost_amount numeric(10,2),
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.billing_activities OWNER TO swautomorph;

--
-- TOC entry 234 (class 1259 OID 22030)
-- Name: billing_activities_id_seq; Type: SEQUENCE; Schema: public; Owner: swautomorph
--

CREATE SEQUENCE public.billing_activities_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.billing_activities_id_seq OWNER TO swautomorph;

--
-- TOC entry 3869 (class 0 OID 0)
-- Dependencies: 234
-- Name: billing_activities_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.billing_activities_id_seq OWNED BY public.billing_activities.id;


--
-- TOC entry 243 (class 1259 OID 22112)
-- Name: configuration; Type: TABLE; Schema: public; Owner: swautomorph
--

CREATE TABLE public.configuration (
    param_id bigint NOT NULL,
    parent character varying(255),
    key character varying(255),
    value text
);


ALTER TABLE public.configuration OWNER TO swautomorph;

--
-- TOC entry 242 (class 1259 OID 22111)
-- Name: configuration_param_id_seq; Type: SEQUENCE; Schema: public; Owner: swautomorph
--

CREATE SEQUENCE public.configuration_param_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.configuration_param_id_seq OWNER TO swautomorph;

--
-- TOC entry 3870 (class 0 OID 0)
-- Dependencies: 242
-- Name: configuration_param_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.configuration_param_id_seq OWNED BY public.configuration.param_id;


--
-- TOC entry 261 (class 1259 OID 22378)
-- Name: deploy_templates; Type: TABLE; Schema: public; Owner: swautomorph
--

CREATE TABLE public.deploy_templates (
    id bigint NOT NULL,
    template_id character varying(63) NOT NULL,
    app_type character varying(64) NOT NULL,
    display_name character varying(255) NOT NULL,
    source_image text NOT NULL,
    ports jsonb NOT NULL,
    environment jsonb DEFAULT '[]'::jsonb NOT NULL,
    memory_mb integer NOT NULL,
    cpu_cores numeric(4,1) NOT NULL,
    timeout_seconds integer DEFAULT 300 NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT deploy_templates_cpu_cores_check CHECK (((cpu_cores >= 0.1) AND (cpu_cores <= (64)::numeric))),
    CONSTRAINT deploy_templates_memory_mb_check CHECK (((memory_mb >= 64) AND (memory_mb <= 65536))),
    CONSTRAINT deploy_templates_timeout_seconds_check CHECK (((timeout_seconds >= 1) AND (timeout_seconds <= 3600)))
);


ALTER TABLE public.deploy_templates OWNER TO swautomorph;

--
-- TOC entry 260 (class 1259 OID 22377)
-- Name: deploy_templates_id_seq; Type: SEQUENCE; Schema: public; Owner: swautomorph
--

CREATE SEQUENCE public.deploy_templates_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.deploy_templates_id_seq OWNER TO swautomorph;

--
-- TOC entry 3871 (class 0 OID 0)
-- Dependencies: 260
-- Name: deploy_templates_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.deploy_templates_id_seq OWNED BY public.deploy_templates.id;


--
-- TOC entry 231 (class 1259 OID 21982)
-- Name: deployments; Type: TABLE; Schema: public; Owner: swautomorph
--

CREATE TABLE public.deployments (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    application_id bigint,
    application_name character varying(255) NOT NULL,
    status character varying(50) DEFAULT 'pending'::character varying,
    deployment_path text,
    git_url text,
    swautomorph_url text,
    gitea_branch_url text,
    modification_history jsonb DEFAULT '[]'::jsonb,
    backups_history jsonb DEFAULT '[]'::jsonb,
    server_id bigint,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    is_sandbox boolean DEFAULT false NOT NULL
);


ALTER TABLE public.deployments OWNER TO swautomorph;

--
-- TOC entry 3872 (class 0 OID 0)
-- Dependencies: 231
-- Name: COLUMN deployments.modification_history; Type: COMMENT; Schema: public; Owner: swautomorph
--

COMMENT ON COLUMN public.deployments.modification_history IS 'JSON array containing modification history with branch names and Gitea URLs';


--
-- TOC entry 3873 (class 0 OID 0)
-- Dependencies: 231
-- Name: COLUMN deployments.backups_history; Type: COMMENT; Schema: public; Owner: swautomorph
--

COMMENT ON COLUMN public.deployments.backups_history IS 'JSON array containing backup history with links to PostgreSQL database backups in S3';


--
-- TOC entry 230 (class 1259 OID 21981)
-- Name: deployments_id_seq; Type: SEQUENCE; Schema: public; Owner: swautomorph
--

CREATE SEQUENCE public.deployments_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.deployments_id_seq OWNER TO swautomorph;

--
-- TOC entry 3874 (class 0 OID 0)
-- Dependencies: 230
-- Name: deployments_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.deployments_id_seq OWNED BY public.deployments.id;


--
-- TOC entry 247 (class 1259 OID 22146)
-- Name: instances; Type: TABLE; Schema: public; Owner: swautomorph
--

CREATE TABLE public.instances (
    id bigint NOT NULL,
    service_id bigint NOT NULL,
    instance_id character varying(255) NOT NULL,
    server_id bigint NOT NULL,
    service_name character varying(255),
    container_id character varying(255),
    status character varying(50) DEFAULT 'pending'::character varying,
    port integer,
    health_status character varying(50) DEFAULT 'unknown'::character varying,
    last_health_check timestamp with time zone,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.instances OWNER TO swautomorph;

--
-- TOC entry 246 (class 1259 OID 22145)
-- Name: instances_id_seq; Type: SEQUENCE; Schema: public; Owner: swautomorph
--

CREATE SEQUENCE public.instances_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.instances_id_seq OWNER TO swautomorph;

--
-- TOC entry 3875 (class 0 OID 0)
-- Dependencies: 246
-- Name: instances_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.instances_id_seq OWNED BY public.instances.id;


--
-- TOC entry 241 (class 1259 OID 22089)
-- Name: invoicing; Type: TABLE; Schema: public; Owner: swautomorph
--

CREATE TABLE public.invoicing (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    invoice_month character varying(7) NOT NULL,
    total_amount numeric(10,2) NOT NULL,
    status character varying(50) DEFAULT 'unpaid'::character varying,
    payment_date timestamp with time zone,
    payment_mode_id bigint,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.invoicing OWNER TO swautomorph;

--
-- TOC entry 240 (class 1259 OID 22088)
-- Name: invoicing_id_seq; Type: SEQUENCE; Schema: public; Owner: swautomorph
--

CREATE SEQUENCE public.invoicing_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.invoicing_id_seq OWNER TO swautomorph;

--
-- TOC entry 3876 (class 0 OID 0)
-- Dependencies: 240
-- Name: invoicing_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.invoicing_id_seq OWNED BY public.invoicing.id;


--
-- TOC entry 259 (class 1259 OID 22336)
-- Name: mig_instances; Type: TABLE; Schema: public; Owner: swautomorph
--

CREATE TABLE public.mig_instances (
    id integer NOT NULL,
    server_id integer NOT NULL,
    instance_uuid character varying(36) NOT NULL,
    profile_name character varying(50) NOT NULL,
    gpu_memory_mb integer NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT mig_instances_gpu_memory_mb_check CHECK (((gpu_memory_mb >= 1) AND (gpu_memory_mb <= 81920)))
);


ALTER TABLE public.mig_instances OWNER TO swautomorph;

--
-- TOC entry 258 (class 1259 OID 22335)
-- Name: mig_instances_id_seq; Type: SEQUENCE; Schema: public; Owner: swautomorph
--

CREATE SEQUENCE public.mig_instances_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.mig_instances_id_seq OWNER TO swautomorph;

--
-- TOC entry 3877 (class 0 OID 0)
-- Dependencies: 258
-- Name: mig_instances_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.mig_instances_id_seq OWNED BY public.mig_instances.id;


--
-- TOC entry 257 (class 1259 OID 22314)
-- Name: mig_profiles; Type: TABLE; Schema: public; Owner: swautomorph
--

CREATE TABLE public.mig_profiles (
    id integer NOT NULL,
    server_id integer NOT NULL,
    profile_name character varying(64) NOT NULL,
    profile_id character varying(128) NOT NULL,
    gpu_memory_gb integer NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT mig_profiles_gpu_memory_gb_check CHECK (((gpu_memory_gb >= 1) AND (gpu_memory_gb <= 80)))
);


ALTER TABLE public.mig_profiles OWNER TO swautomorph;

--
-- TOC entry 256 (class 1259 OID 22313)
-- Name: mig_profiles_id_seq; Type: SEQUENCE; Schema: public; Owner: swautomorph
--

CREATE SEQUENCE public.mig_profiles_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.mig_profiles_id_seq OWNER TO swautomorph;

--
-- TOC entry 3878 (class 0 OID 0)
-- Dependencies: 256
-- Name: mig_profiles_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.mig_profiles_id_seq OWNED BY public.mig_profiles.id;


--
-- TOC entry 249 (class 1259 OID 22201)
-- Name: password_reset_tokens; Type: TABLE; Schema: public; Owner: swautomorph
--

CREATE TABLE public.password_reset_tokens (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    token_hash character varying(255) NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    used boolean DEFAULT false,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.password_reset_tokens OWNER TO swautomorph;

--
-- TOC entry 248 (class 1259 OID 22200)
-- Name: password_reset_tokens_id_seq; Type: SEQUENCE; Schema: public; Owner: swautomorph
--

CREATE SEQUENCE public.password_reset_tokens_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.password_reset_tokens_id_seq OWNER TO swautomorph;

--
-- TOC entry 3879 (class 0 OID 0)
-- Dependencies: 248
-- Name: password_reset_tokens_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.password_reset_tokens_id_seq OWNED BY public.password_reset_tokens.id;


--
-- TOC entry 239 (class 1259 OID 22070)
-- Name: payment_modes; Type: TABLE; Schema: public; Owner: swautomorph
--

CREATE TABLE public.payment_modes (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    payment_type character varying(50) NOT NULL,
    bank_account character varying(255),
    paypal_email character varying(255),
    card_last_four character varying(4),
    card_type character varying(50),
    is_default boolean DEFAULT false,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.payment_modes OWNER TO swautomorph;

--
-- TOC entry 238 (class 1259 OID 22069)
-- Name: payment_modes_id_seq; Type: SEQUENCE; Schema: public; Owner: swautomorph
--

CREATE SEQUENCE public.payment_modes_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.payment_modes_id_seq OWNER TO swautomorph;

--
-- TOC entry 3880 (class 0 OID 0)
-- Dependencies: 238
-- Name: payment_modes_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.payment_modes_id_seq OWNED BY public.payment_modes.id;


--
-- TOC entry 267 (class 1259 OID 22469)
-- Name: runtime_anomalies; Type: TABLE; Schema: public; Owner: swautomorph
--

CREATE TABLE public.runtime_anomalies (
    id bigint NOT NULL,
    container_pk bigint NOT NULL,
    rule_id text NOT NULL,
    severity text DEFAULT 'low'::text NOT NULL,
    evidence jsonb DEFAULT '[]'::jsonb NOT NULL,
    status text DEFAULT 'open'::text NOT NULL,
    detected_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT runtime_anomalies_severity_check CHECK ((severity = ANY (ARRAY['low'::text, 'medium'::text, 'high'::text, 'critical'::text]))),
    CONSTRAINT runtime_anomalies_status_check CHECK ((status = ANY (ARRAY['open'::text, 'acknowledged'::text, 'resolved'::text])))
);


ALTER TABLE public.runtime_anomalies OWNER TO swautomorph;

--
-- TOC entry 266 (class 1259 OID 22468)
-- Name: runtime_anomalies_id_seq; Type: SEQUENCE; Schema: public; Owner: swautomorph
--

CREATE SEQUENCE public.runtime_anomalies_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.runtime_anomalies_id_seq OWNER TO swautomorph;

--
-- TOC entry 3881 (class 0 OID 0)
-- Dependencies: 266
-- Name: runtime_anomalies_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.runtime_anomalies_id_seq OWNED BY public.runtime_anomalies.id;


--
-- TOC entry 263 (class 1259 OID 22410)
-- Name: runtime_containers; Type: TABLE; Schema: public; Owner: swautomorph
--

CREATE TABLE public.runtime_containers (
    id bigint NOT NULL,
    server_id bigint NOT NULL,
    container_id text NOT NULL,
    name text,
    image text,
    runtime text,
    state text DEFAULT 'unknown'::text NOT NULL,
    is_platform_managed boolean DEFAULT false NOT NULL,
    classification text DEFAULT 'unclassified'::text NOT NULL,
    confidence_score double precision DEFAULT 0.0 NOT NULL,
    classification_evidence jsonb DEFAULT '[]'::jsonb NOT NULL,
    labels jsonb DEFAULT '{}'::jsonb NOT NULL,
    first_seen timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    last_seen timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT runtime_containers_classification_check CHECK ((classification = ANY (ARRAY['probable_agent'::text, 'unclassified'::text])))
);


ALTER TABLE public.runtime_containers OWNER TO swautomorph;

--
-- TOC entry 262 (class 1259 OID 22409)
-- Name: runtime_containers_id_seq; Type: SEQUENCE; Schema: public; Owner: swautomorph
--

CREATE SEQUENCE public.runtime_containers_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.runtime_containers_id_seq OWNER TO swautomorph;

--
-- TOC entry 3882 (class 0 OID 0)
-- Dependencies: 262
-- Name: runtime_containers_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.runtime_containers_id_seq OWNED BY public.runtime_containers.id;


--
-- TOC entry 265 (class 1259 OID 22447)
-- Name: runtime_observations; Type: TABLE; Schema: public; Owner: swautomorph
--

CREATE TABLE public.runtime_observations (
    id bigint NOT NULL,
    container_pk bigint NOT NULL,
    cpu_percent double precision,
    memory_bytes bigint,
    pids integer,
    process_summary jsonb DEFAULT '[]'::jsonb NOT NULL,
    network_summary jsonb DEFAULT '{}'::jsonb NOT NULL,
    state text,
    observed_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.runtime_observations OWNER TO swautomorph;

--
-- TOC entry 264 (class 1259 OID 22446)
-- Name: runtime_observations_id_seq; Type: SEQUENCE; Schema: public; Owner: swautomorph
--

CREATE SEQUENCE public.runtime_observations_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.runtime_observations_id_seq OWNER TO swautomorph;

--
-- TOC entry 3883 (class 0 OID 0)
-- Dependencies: 264
-- Name: runtime_observations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.runtime_observations_id_seq OWNED BY public.runtime_observations.id;


--
-- TOC entry 269 (class 1259 OID 22497)
-- Name: runtime_scan_runs; Type: TABLE; Schema: public; Owner: swautomorph
--

CREATE TABLE public.runtime_scan_runs (
    id bigint NOT NULL,
    server_id bigint,
    started_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    finished_at timestamp with time zone,
    containers_seen integer DEFAULT 0 NOT NULL,
    error text
);


ALTER TABLE public.runtime_scan_runs OWNER TO swautomorph;

--
-- TOC entry 268 (class 1259 OID 22496)
-- Name: runtime_scan_runs_id_seq; Type: SEQUENCE; Schema: public; Owner: swautomorph
--

CREATE SEQUENCE public.runtime_scan_runs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.runtime_scan_runs_id_seq OWNER TO swautomorph;

--
-- TOC entry 3884 (class 0 OID 0)
-- Dependencies: 268
-- Name: runtime_scan_runs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.runtime_scan_runs_id_seq OWNED BY public.runtime_scan_runs.id;


--
-- TOC entry 254 (class 1259 OID 22278)
-- Name: serverless_job_logs; Type: TABLE; Schema: public; Owner: swautomorph
--

CREATE TABLE public.serverless_job_logs (
    id bigint NOT NULL,
    job_id uuid NOT NULL,
    stream text NOT NULL,
    content text NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT serverless_job_logs_stream_check CHECK ((stream = ANY (ARRAY['stdout'::text, 'stderr'::text])))
);


ALTER TABLE public.serverless_job_logs OWNER TO swautomorph;

--
-- TOC entry 253 (class 1259 OID 22277)
-- Name: serverless_job_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: swautomorph
--

CREATE SEQUENCE public.serverless_job_logs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.serverless_job_logs_id_seq OWNER TO swautomorph;

--
-- TOC entry 3885 (class 0 OID 0)
-- Dependencies: 253
-- Name: serverless_job_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.serverless_job_logs_id_seq OWNED BY public.serverless_job_logs.id;


--
-- TOC entry 255 (class 1259 OID 22298)
-- Name: serverless_job_results; Type: TABLE; Schema: public; Owner: swautomorph
--

CREATE TABLE public.serverless_job_results (
    job_id uuid NOT NULL,
    result jsonb,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.serverless_job_results OWNER TO swautomorph;

--
-- TOC entry 252 (class 1259 OID 22244)
-- Name: serverless_jobs; Type: TABLE; Schema: public; Owner: swautomorph
--

CREATE TABLE public.serverless_jobs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id integer NOT NULL,
    image text NOT NULL,
    command jsonb NOT NULL,
    environment jsonb DEFAULT '{}'::jsonb,
    timeout_seconds integer DEFAULT 300 NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    started_at timestamp without time zone,
    completed_at timestamp without time zone,
    exit_code integer,
    worker_id text,
    target_link text,
    CONSTRAINT serverless_jobs_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'running'::text, 'completed'::text, 'failed'::text, 'timeout'::text, 'cancelled'::text]))),
    CONSTRAINT serverless_jobs_timeout_seconds_check CHECK (((timeout_seconds >= 1) AND (timeout_seconds <= 3600)))
);


ALTER TABLE public.serverless_jobs OWNER TO swautomorph;

--
-- TOC entry 3886 (class 0 OID 0)
-- Dependencies: 252
-- Name: COLUMN serverless_jobs.target_link; Type: COMMENT; Schema: public; Owner: swautomorph
--

COMMENT ON COLUMN public.serverless_jobs.target_link IS 'The agentic-ai-plateform-serverless-brik endpoint URL selected for job execution';


--
-- TOC entry 229 (class 1259 OID 21963)
-- Name: servers; Type: TABLE; Schema: public; Owner: swautomorph
--

CREATE TABLE public.servers (
    id bigint NOT NULL,
    server_ip inet NOT NULL,
    server_name character varying(255) NOT NULL,
    server_capacity_user_max integer NOT NULL,
    server_capacity_appli_max integer NOT NULL,
    server_status character varying(50) DEFAULT 'STAND_BY'::character varying,
    server_type character varying(50) NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    shared_gpu_enabled boolean DEFAULT false
);


ALTER TABLE public.servers OWNER TO swautomorph;

--
-- TOC entry 228 (class 1259 OID 21962)
-- Name: servers_id_seq; Type: SEQUENCE; Schema: public; Owner: swautomorph
--

CREATE SEQUENCE public.servers_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.servers_id_seq OWNER TO swautomorph;

--
-- TOC entry 3887 (class 0 OID 0)
-- Dependencies: 228
-- Name: servers_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.servers_id_seq OWNED BY public.servers.id;


--
-- TOC entry 245 (class 1259 OID 22122)
-- Name: services; Type: TABLE; Schema: public; Owner: swautomorph
--

CREATE TABLE public.services (
    id bigint NOT NULL,
    name character varying(255) NOT NULL,
    image character varying(255) NOT NULL,
    user_id bigint NOT NULL,
    desired_replicas integer DEFAULT 1,
    ports text,
    environment text,
    volumes text,
    health_check_path character varying(255) DEFAULT '/health'::character varying,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.services OWNER TO swautomorph;

--
-- TOC entry 244 (class 1259 OID 22121)
-- Name: services_id_seq; Type: SEQUENCE; Schema: public; Owner: swautomorph
--

CREATE SEQUENCE public.services_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.services_id_seq OWNER TO swautomorph;

--
-- TOC entry 3888 (class 0 OID 0)
-- Dependencies: 244
-- Name: services_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.services_id_seq OWNED BY public.services.id;


--
-- TOC entry 251 (class 1259 OID 22225)
-- Name: twofa_email_codes; Type: TABLE; Schema: public; Owner: swautomorph
--

CREATE TABLE public.twofa_email_codes (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    code character varying(6) NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    used boolean DEFAULT false,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.twofa_email_codes OWNER TO swautomorph;

--
-- TOC entry 250 (class 1259 OID 22224)
-- Name: twofa_email_codes_id_seq; Type: SEQUENCE; Schema: public; Owner: swautomorph
--

CREATE SEQUENCE public.twofa_email_codes_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.twofa_email_codes_id_seq OWNER TO swautomorph;

--
-- TOC entry 3889 (class 0 OID 0)
-- Dependencies: 250
-- Name: twofa_email_codes_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.twofa_email_codes_id_seq OWNED BY public.twofa_email_codes.id;


--
-- TOC entry 227 (class 1259 OID 21937)
-- Name: user_applications; Type: TABLE; Schema: public; Owner: swautomorph
--

CREATE TABLE public.user_applications (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    application_id bigint NOT NULL,
    url text NOT NULL,
    http_port integer,
    https_port integer,
    http_port2 integer,
    https_port2 integer,
    http_port3 integer,
    https_port3 integer,
    http_port4 integer,
    https_port4 integer,
    http_port5 integer,
    https_port5 integer,
    http_port6 integer,
    https_port6 integer,
    others_port integer,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.user_applications OWNER TO swautomorph;

--
-- TOC entry 3890 (class 0 OID 0)
-- Dependencies: 227
-- Name: COLUMN user_applications.http_port3; Type: COMMENT; Schema: public; Owner: swautomorph
--

COMMENT ON COLUMN public.user_applications.http_port3 IS 'Third HTTP port allocated to the application';


--
-- TOC entry 3891 (class 0 OID 0)
-- Dependencies: 227
-- Name: COLUMN user_applications.https_port3; Type: COMMENT; Schema: public; Owner: swautomorph
--

COMMENT ON COLUMN public.user_applications.https_port3 IS 'Third HTTPS port allocated to the application';


--
-- TOC entry 3892 (class 0 OID 0)
-- Dependencies: 227
-- Name: COLUMN user_applications.http_port4; Type: COMMENT; Schema: public; Owner: swautomorph
--

COMMENT ON COLUMN public.user_applications.http_port4 IS 'Fourth HTTP port allocated to the application';


--
-- TOC entry 3893 (class 0 OID 0)
-- Dependencies: 227
-- Name: COLUMN user_applications.https_port4; Type: COMMENT; Schema: public; Owner: swautomorph
--

COMMENT ON COLUMN public.user_applications.https_port4 IS 'Fourth HTTPS port allocated to the application';


--
-- TOC entry 3894 (class 0 OID 0)
-- Dependencies: 227
-- Name: COLUMN user_applications.http_port5; Type: COMMENT; Schema: public; Owner: swautomorph
--

COMMENT ON COLUMN public.user_applications.http_port5 IS 'Fifth HTTP port allocated to the application';


--
-- TOC entry 3895 (class 0 OID 0)
-- Dependencies: 227
-- Name: COLUMN user_applications.https_port5; Type: COMMENT; Schema: public; Owner: swautomorph
--

COMMENT ON COLUMN public.user_applications.https_port5 IS 'Fifth HTTPS port allocated to the application';


--
-- TOC entry 3896 (class 0 OID 0)
-- Dependencies: 227
-- Name: COLUMN user_applications.http_port6; Type: COMMENT; Schema: public; Owner: swautomorph
--

COMMENT ON COLUMN public.user_applications.http_port6 IS 'Sixth HTTP port allocated to the application';


--
-- TOC entry 3897 (class 0 OID 0)
-- Dependencies: 227
-- Name: COLUMN user_applications.https_port6; Type: COMMENT; Schema: public; Owner: swautomorph
--

COMMENT ON COLUMN public.user_applications.https_port6 IS 'Sixth HTTPS port allocated to the application';


--
-- TOC entry 226 (class 1259 OID 21936)
-- Name: user_applications_id_seq; Type: SEQUENCE; Schema: public; Owner: swautomorph
--

CREATE SEQUENCE public.user_applications_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.user_applications_id_seq OWNER TO swautomorph;

--
-- TOC entry 3898 (class 0 OID 0)
-- Dependencies: 226
-- Name: user_applications_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.user_applications_id_seq OWNED BY public.user_applications.id;


--
-- TOC entry 221 (class 1259 OID 21884)
-- Name: users; Type: TABLE; Schema: public; Owner: swautomorph
--

CREATE TABLE public.users (
    id bigint NOT NULL,
    username character varying(255) NOT NULL,
    email character varying(255) NOT NULL,
    password_hash character varying(255) NOT NULL,
    first_name character varying(255),
    last_name character varying(255),
    suspended boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    totp_secret character varying(64),
    totp_enabled boolean DEFAULT false,
    totp_backup_codes text,
    twofa_email_enabled boolean DEFAULT false,
    account_type character varying(32)
);


ALTER TABLE public.users OWNER TO swautomorph;

--
-- TOC entry 220 (class 1259 OID 21883)
-- Name: users_id_seq; Type: SEQUENCE; Schema: public; Owner: swautomorph
--

CREATE SEQUENCE public.users_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.users_id_seq OWNER TO swautomorph;

--
-- TOC entry 3899 (class 0 OID 0)
-- Dependencies: 220
-- Name: users_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;


--
-- TOC entry 237 (class 1259 OID 22053)
-- Name: users_logs; Type: TABLE; Schema: public; Owner: swautomorph
--

CREATE TABLE public.users_logs (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    username character varying(255) NOT NULL,
    action character varying(50) NOT NULL,
    datetime timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.users_logs OWNER TO swautomorph;

--
-- TOC entry 236 (class 1259 OID 22052)
-- Name: users_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: swautomorph
--

CREATE SEQUENCE public.users_logs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.users_logs_id_seq OWNER TO swautomorph;

--
-- TOC entry 3900 (class 0 OID 0)
-- Dependencies: 236
-- Name: users_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.users_logs_id_seq OWNED BY public.users_logs.id;


--
-- TOC entry 3484 (class 2604 OID 22017)
-- Name: application_costs id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.application_costs ALTER COLUMN id SET DEFAULT nextval('public.application_costs_id_seq'::regclass);


--
-- TOC entry 3466 (class 2604 OID 21906)
-- Name: applications id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.applications ALTER COLUMN id SET DEFAULT nextval('public.applications_id_seq'::regclass);


--
-- TOC entry 3469 (class 2604 OID 21921)
-- Name: auth_tokens id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.auth_tokens ALTER COLUMN id SET DEFAULT nextval('public.auth_tokens_id_seq'::regclass);


--
-- TOC entry 3488 (class 2604 OID 22034)
-- Name: billing_activities id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.billing_activities ALTER COLUMN id SET DEFAULT nextval('public.billing_activities_id_seq'::regclass);


--
-- TOC entry 3498 (class 2604 OID 22115)
-- Name: configuration param_id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.configuration ALTER COLUMN param_id SET DEFAULT nextval('public.configuration_param_id_seq'::regclass);


--
-- TOC entry 3527 (class 2604 OID 22381)
-- Name: deploy_templates id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.deploy_templates ALTER COLUMN id SET DEFAULT nextval('public.deploy_templates_id_seq'::regclass);


--
-- TOC entry 3477 (class 2604 OID 21985)
-- Name: deployments id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.deployments ALTER COLUMN id SET DEFAULT nextval('public.deployments_id_seq'::regclass);


--
-- TOC entry 3504 (class 2604 OID 22149)
-- Name: instances id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.instances ALTER COLUMN id SET DEFAULT nextval('public.instances_id_seq'::regclass);


--
-- TOC entry 3495 (class 2604 OID 22092)
-- Name: invoicing id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.invoicing ALTER COLUMN id SET DEFAULT nextval('public.invoicing_id_seq'::regclass);


--
-- TOC entry 3525 (class 2604 OID 22339)
-- Name: mig_instances id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.mig_instances ALTER COLUMN id SET DEFAULT nextval('public.mig_instances_id_seq'::regclass);


--
-- TOC entry 3523 (class 2604 OID 22317)
-- Name: mig_profiles id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.mig_profiles ALTER COLUMN id SET DEFAULT nextval('public.mig_profiles_id_seq'::regclass);


--
-- TOC entry 3509 (class 2604 OID 22204)
-- Name: password_reset_tokens id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.password_reset_tokens ALTER COLUMN id SET DEFAULT nextval('public.password_reset_tokens_id_seq'::regclass);


--
-- TOC entry 3492 (class 2604 OID 22073)
-- Name: payment_modes id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.payment_modes ALTER COLUMN id SET DEFAULT nextval('public.payment_modes_id_seq'::regclass);


--
-- TOC entry 3545 (class 2604 OID 22472)
-- Name: runtime_anomalies id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.runtime_anomalies ALTER COLUMN id SET DEFAULT nextval('public.runtime_anomalies_id_seq'::regclass);


--
-- TOC entry 3532 (class 2604 OID 22413)
-- Name: runtime_containers id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.runtime_containers ALTER COLUMN id SET DEFAULT nextval('public.runtime_containers_id_seq'::regclass);


--
-- TOC entry 3541 (class 2604 OID 22450)
-- Name: runtime_observations id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.runtime_observations ALTER COLUMN id SET DEFAULT nextval('public.runtime_observations_id_seq'::regclass);


--
-- TOC entry 3550 (class 2604 OID 22500)
-- Name: runtime_scan_runs id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.runtime_scan_runs ALTER COLUMN id SET DEFAULT nextval('public.runtime_scan_runs_id_seq'::regclass);


--
-- TOC entry 3520 (class 2604 OID 22281)
-- Name: serverless_job_logs id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.serverless_job_logs ALTER COLUMN id SET DEFAULT nextval('public.serverless_job_logs_id_seq'::regclass);


--
-- TOC entry 3473 (class 2604 OID 21966)
-- Name: servers id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.servers ALTER COLUMN id SET DEFAULT nextval('public.servers_id_seq'::regclass);


--
-- TOC entry 3499 (class 2604 OID 22125)
-- Name: services id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.services ALTER COLUMN id SET DEFAULT nextval('public.services_id_seq'::regclass);


--
-- TOC entry 3512 (class 2604 OID 22228)
-- Name: twofa_email_codes id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.twofa_email_codes ALTER COLUMN id SET DEFAULT nextval('public.twofa_email_codes_id_seq'::regclass);


--
-- TOC entry 3471 (class 2604 OID 21940)
-- Name: user_applications id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.user_applications ALTER COLUMN id SET DEFAULT nextval('public.user_applications_id_seq'::regclass);


--
-- TOC entry 3461 (class 2604 OID 21887)
-- Name: users id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);


--
-- TOC entry 3490 (class 2604 OID 22056)
-- Name: users_logs id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.users_logs ALTER COLUMN id SET DEFAULT nextval('public.users_logs_id_seq'::regclass);


--
-- TOC entry 3601 (class 2606 OID 22024)
-- Name: application_costs application_costs_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.application_costs
    ADD CONSTRAINT application_costs_pkey PRIMARY KEY (id);


--
-- TOC entry 3573 (class 2606 OID 21916)
-- Name: applications applications_name_key; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.applications
    ADD CONSTRAINT applications_name_key UNIQUE (name);


--
-- TOC entry 3575 (class 2606 OID 21914)
-- Name: applications applications_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.applications
    ADD CONSTRAINT applications_pkey PRIMARY KEY (id);


--
-- TOC entry 3578 (class 2606 OID 21928)
-- Name: auth_tokens auth_tokens_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.auth_tokens
    ADD CONSTRAINT auth_tokens_pkey PRIMARY KEY (id);


--
-- TOC entry 3580 (class 2606 OID 21930)
-- Name: auth_tokens auth_tokens_token_hash_key; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.auth_tokens
    ADD CONSTRAINT auth_tokens_token_hash_key UNIQUE (token_hash);


--
-- TOC entry 3603 (class 2606 OID 22041)
-- Name: billing_activities billing_activities_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.billing_activities
    ADD CONSTRAINT billing_activities_pkey PRIMARY KEY (id);


--
-- TOC entry 3616 (class 2606 OID 22120)
-- Name: configuration configuration_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.configuration
    ADD CONSTRAINT configuration_pkey PRIMARY KEY (param_id);


--
-- TOC entry 3660 (class 2606 OID 22403)
-- Name: deploy_templates deploy_templates_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.deploy_templates
    ADD CONSTRAINT deploy_templates_pkey PRIMARY KEY (id);


--
-- TOC entry 3662 (class 2606 OID 22405)
-- Name: deploy_templates deploy_templates_template_id_key; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.deploy_templates
    ADD CONSTRAINT deploy_templates_template_id_key UNIQUE (template_id);


--
-- TOC entry 3594 (class 2606 OID 21997)
-- Name: deployments deployments_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.deployments
    ADD CONSTRAINT deployments_pkey PRIMARY KEY (id);


--
-- TOC entry 3626 (class 2606 OID 22161)
-- Name: instances instances_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.instances
    ADD CONSTRAINT instances_pkey PRIMARY KEY (id);


--
-- TOC entry 3628 (class 2606 OID 22163)
-- Name: instances instances_service_id_instance_id_key; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.instances
    ADD CONSTRAINT instances_service_id_instance_id_key UNIQUE (service_id, instance_id);


--
-- TOC entry 3614 (class 2606 OID 22100)
-- Name: invoicing invoicing_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.invoicing
    ADD CONSTRAINT invoicing_pkey PRIMARY KEY (id);


--
-- TOC entry 3656 (class 2606 OID 22348)
-- Name: mig_instances mig_instances_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.mig_instances
    ADD CONSTRAINT mig_instances_pkey PRIMARY KEY (id);


--
-- TOC entry 3658 (class 2606 OID 22350)
-- Name: mig_instances mig_instances_server_id_instance_uuid_key; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.mig_instances
    ADD CONSTRAINT mig_instances_server_id_instance_uuid_key UNIQUE (server_id, instance_uuid);


--
-- TOC entry 3651 (class 2606 OID 22326)
-- Name: mig_profiles mig_profiles_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.mig_profiles
    ADD CONSTRAINT mig_profiles_pkey PRIMARY KEY (id);


--
-- TOC entry 3653 (class 2606 OID 22328)
-- Name: mig_profiles mig_profiles_server_id_profile_name_key; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.mig_profiles
    ADD CONSTRAINT mig_profiles_server_id_profile_name_key UNIQUE (server_id, profile_name);


--
-- TOC entry 3632 (class 2606 OID 22212)
-- Name: password_reset_tokens password_reset_tokens_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.password_reset_tokens
    ADD CONSTRAINT password_reset_tokens_pkey PRIMARY KEY (id);


--
-- TOC entry 3634 (class 2606 OID 22214)
-- Name: password_reset_tokens password_reset_tokens_token_hash_key; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.password_reset_tokens
    ADD CONSTRAINT password_reset_tokens_token_hash_key UNIQUE (token_hash);


--
-- TOC entry 3612 (class 2606 OID 22082)
-- Name: payment_modes payment_modes_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.payment_modes
    ADD CONSTRAINT payment_modes_pkey PRIMARY KEY (id);


--
-- TOC entry 3677 (class 2606 OID 22488)
-- Name: runtime_anomalies runtime_anomalies_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.runtime_anomalies
    ADD CONSTRAINT runtime_anomalies_pkey PRIMARY KEY (id);


--
-- TOC entry 3668 (class 2606 OID 22435)
-- Name: runtime_containers runtime_containers_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.runtime_containers
    ADD CONSTRAINT runtime_containers_pkey PRIMARY KEY (id);


--
-- TOC entry 3673 (class 2606 OID 22461)
-- Name: runtime_observations runtime_observations_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.runtime_observations
    ADD CONSTRAINT runtime_observations_pkey PRIMARY KEY (id);


--
-- TOC entry 3680 (class 2606 OID 22508)
-- Name: runtime_scan_runs runtime_scan_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.runtime_scan_runs
    ADD CONSTRAINT runtime_scan_runs_pkey PRIMARY KEY (id);


--
-- TOC entry 3646 (class 2606 OID 22291)
-- Name: serverless_job_logs serverless_job_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.serverless_job_logs
    ADD CONSTRAINT serverless_job_logs_pkey PRIMARY KEY (id);


--
-- TOC entry 3648 (class 2606 OID 22306)
-- Name: serverless_job_results serverless_job_results_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.serverless_job_results
    ADD CONSTRAINT serverless_job_results_pkey PRIMARY KEY (job_id);


--
-- TOC entry 3643 (class 2606 OID 22263)
-- Name: serverless_jobs serverless_jobs_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.serverless_jobs
    ADD CONSTRAINT serverless_jobs_pkey PRIMARY KEY (id);


--
-- TOC entry 3590 (class 2606 OID 21978)
-- Name: servers servers_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.servers
    ADD CONSTRAINT servers_pkey PRIMARY KEY (id);


--
-- TOC entry 3592 (class 2606 OID 21980)
-- Name: servers servers_server_ip_key; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.servers
    ADD CONSTRAINT servers_server_ip_key UNIQUE (server_ip);


--
-- TOC entry 3619 (class 2606 OID 22139)
-- Name: services services_name_user_id_key; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.services
    ADD CONSTRAINT services_name_user_id_key UNIQUE (name, user_id);


--
-- TOC entry 3621 (class 2606 OID 22137)
-- Name: services services_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.services
    ADD CONSTRAINT services_pkey PRIMARY KEY (id);


--
-- TOC entry 3638 (class 2606 OID 22236)
-- Name: twofa_email_codes twofa_email_codes_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.twofa_email_codes
    ADD CONSTRAINT twofa_email_codes_pkey PRIMARY KEY (id);


--
-- TOC entry 3670 (class 2606 OID 22437)
-- Name: runtime_containers uq_runtime_container; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.runtime_containers
    ADD CONSTRAINT uq_runtime_container UNIQUE (server_id, container_id);


--
-- TOC entry 3586 (class 2606 OID 21949)
-- Name: user_applications user_applications_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.user_applications
    ADD CONSTRAINT user_applications_pkey PRIMARY KEY (id);


--
-- TOC entry 3588 (class 2606 OID 21951)
-- Name: user_applications user_applications_user_id_application_id_key; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.user_applications
    ADD CONSTRAINT user_applications_user_id_application_id_key UNIQUE (user_id, application_id);


--
-- TOC entry 3567 (class 2606 OID 21901)
-- Name: users users_email_key; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_email_key UNIQUE (email);


--
-- TOC entry 3610 (class 2606 OID 22063)
-- Name: users_logs users_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.users_logs
    ADD CONSTRAINT users_logs_pkey PRIMARY KEY (id);


--
-- TOC entry 3569 (class 2606 OID 21897)
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- TOC entry 3571 (class 2606 OID 21899)
-- Name: users users_username_key; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_username_key UNIQUE (username);


--
-- TOC entry 3576 (class 1259 OID 22182)
-- Name: idx_applications_url; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_applications_url ON public.applications USING btree (url);


--
-- TOC entry 3581 (class 1259 OID 22181)
-- Name: idx_auth_tokens_expires_at; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_auth_tokens_expires_at ON public.auth_tokens USING btree (expires_at);


--
-- TOC entry 3582 (class 1259 OID 22180)
-- Name: idx_auth_tokens_user_id; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_auth_tokens_user_id ON public.auth_tokens USING btree (user_id);


--
-- TOC entry 3604 (class 1259 OID 22191)
-- Name: idx_billing_activities_application_id; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_billing_activities_application_id ON public.billing_activities USING btree (application_id);


--
-- TOC entry 3605 (class 1259 OID 22192)
-- Name: idx_billing_activities_created_at; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_billing_activities_created_at ON public.billing_activities USING btree (created_at);


--
-- TOC entry 3606 (class 1259 OID 22190)
-- Name: idx_billing_activities_user_id; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_billing_activities_user_id ON public.billing_activities USING btree (user_id);


--
-- TOC entry 3663 (class 1259 OID 22406)
-- Name: idx_deploy_templates_type; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_deploy_templates_type ON public.deploy_templates USING btree (app_type);


--
-- TOC entry 3595 (class 1259 OID 22186)
-- Name: idx_deployments_application_id; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_deployments_application_id ON public.deployments USING btree (application_id);


--
-- TOC entry 3596 (class 1259 OID 22189)
-- Name: idx_deployments_backups_history; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_deployments_backups_history ON public.deployments USING gin (backups_history);


--
-- TOC entry 3597 (class 1259 OID 22187)
-- Name: idx_deployments_server_id; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_deployments_server_id ON public.deployments USING btree (server_id);


--
-- TOC entry 3598 (class 1259 OID 22188)
-- Name: idx_deployments_status; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_deployments_status ON public.deployments USING btree (status);


--
-- TOC entry 3599 (class 1259 OID 22185)
-- Name: idx_deployments_user_id; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_deployments_user_id ON public.deployments USING btree (user_id);


--
-- TOC entry 3622 (class 1259 OID 22177)
-- Name: idx_instances_server_id; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_instances_server_id ON public.instances USING btree (server_id);


--
-- TOC entry 3623 (class 1259 OID 22176)
-- Name: idx_instances_service_id; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_instances_service_id ON public.instances USING btree (service_id);


--
-- TOC entry 3624 (class 1259 OID 22178)
-- Name: idx_instances_status; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_instances_status ON public.instances USING btree (status);


--
-- TOC entry 3654 (class 1259 OID 22356)
-- Name: idx_mig_instances_server_id; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_mig_instances_server_id ON public.mig_instances USING btree (server_id);


--
-- TOC entry 3649 (class 1259 OID 22334)
-- Name: idx_mig_profiles_server_id; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_mig_profiles_server_id ON public.mig_profiles USING btree (server_id);


--
-- TOC entry 3629 (class 1259 OID 22221)
-- Name: idx_password_reset_tokens_expires_at; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_password_reset_tokens_expires_at ON public.password_reset_tokens USING btree (expires_at);


--
-- TOC entry 3630 (class 1259 OID 22220)
-- Name: idx_password_reset_tokens_user_id; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_password_reset_tokens_user_id ON public.password_reset_tokens USING btree (user_id);


--
-- TOC entry 3674 (class 1259 OID 22494)
-- Name: idx_runtime_anomalies_container; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_runtime_anomalies_container ON public.runtime_anomalies USING btree (container_pk, detected_at);


--
-- TOC entry 3675 (class 1259 OID 22495)
-- Name: idx_runtime_anomalies_status; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_runtime_anomalies_status ON public.runtime_anomalies USING btree (status);


--
-- TOC entry 3664 (class 1259 OID 22445)
-- Name: idx_runtime_containers_classification; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_runtime_containers_classification ON public.runtime_containers USING btree (classification);


--
-- TOC entry 3665 (class 1259 OID 22443)
-- Name: idx_runtime_containers_server; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_runtime_containers_server ON public.runtime_containers USING btree (server_id);


--
-- TOC entry 3666 (class 1259 OID 22444)
-- Name: idx_runtime_containers_state; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_runtime_containers_state ON public.runtime_containers USING btree (state);


--
-- TOC entry 3671 (class 1259 OID 22467)
-- Name: idx_runtime_observations_container; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_runtime_observations_container ON public.runtime_observations USING btree (container_pk, observed_at);


--
-- TOC entry 3678 (class 1259 OID 22514)
-- Name: idx_runtime_scan_runs_server; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_runtime_scan_runs_server ON public.runtime_scan_runs USING btree (server_id, started_at);


--
-- TOC entry 3644 (class 1259 OID 22297)
-- Name: idx_serverless_job_logs_job_id; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_serverless_job_logs_job_id ON public.serverless_job_logs USING btree (job_id, created_at);


--
-- TOC entry 3639 (class 1259 OID 22276)
-- Name: idx_serverless_jobs_pending; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_serverless_jobs_pending ON public.serverless_jobs USING btree (status, created_at) WHERE (status = 'pending'::text);


--
-- TOC entry 3640 (class 1259 OID 22274)
-- Name: idx_serverless_jobs_status; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_serverless_jobs_status ON public.serverless_jobs USING btree (status);


--
-- TOC entry 3641 (class 1259 OID 22275)
-- Name: idx_serverless_jobs_user_id; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_serverless_jobs_user_id ON public.serverless_jobs USING btree (user_id);


--
-- TOC entry 3617 (class 1259 OID 22175)
-- Name: idx_services_name; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_services_name ON public.services USING btree (name);


--
-- TOC entry 3635 (class 1259 OID 22243)
-- Name: idx_twofa_email_codes_expires_at; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_twofa_email_codes_expires_at ON public.twofa_email_codes USING btree (expires_at);


--
-- TOC entry 3636 (class 1259 OID 22242)
-- Name: idx_twofa_email_codes_user_id; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_twofa_email_codes_user_id ON public.twofa_email_codes USING btree (user_id);


--
-- TOC entry 3583 (class 1259 OID 22184)
-- Name: idx_user_applications_application_id; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_user_applications_application_id ON public.user_applications USING btree (application_id);


--
-- TOC entry 3584 (class 1259 OID 22183)
-- Name: idx_user_applications_user_id; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_user_applications_user_id ON public.user_applications USING btree (user_id);


--
-- TOC entry 3564 (class 1259 OID 22179)
-- Name: idx_users_email; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_users_email ON public.users USING btree (email);


--
-- TOC entry 3607 (class 1259 OID 22194)
-- Name: idx_users_logs_datetime; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_users_logs_datetime ON public.users_logs USING btree (datetime);


--
-- TOC entry 3608 (class 1259 OID 22193)
-- Name: idx_users_logs_user_id; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_users_logs_user_id ON public.users_logs USING btree (user_id);


--
-- TOC entry 3565 (class 1259 OID 22174)
-- Name: idx_users_username; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_users_username ON public.users USING btree (username);


--
-- TOC entry 3710 (class 2620 OID 22197)
-- Name: application_costs update_application_costs_updated_at; Type: TRIGGER; Schema: public; Owner: swautomorph
--

CREATE TRIGGER update_application_costs_updated_at BEFORE UPDATE ON public.application_costs FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- TOC entry 3709 (class 2620 OID 22196)
-- Name: deployments update_deployments_updated_at; Type: TRIGGER; Schema: public; Owner: swautomorph
--

CREATE TRIGGER update_deployments_updated_at BEFORE UPDATE ON public.deployments FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- TOC entry 3712 (class 2620 OID 22199)
-- Name: instances update_instances_updated_at; Type: TRIGGER; Schema: public; Owner: swautomorph
--

CREATE TRIGGER update_instances_updated_at BEFORE UPDATE ON public.instances FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- TOC entry 3711 (class 2620 OID 22198)
-- Name: services update_services_updated_at; Type: TRIGGER; Schema: public; Owner: swautomorph
--

CREATE TRIGGER update_services_updated_at BEFORE UPDATE ON public.services FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- TOC entry 3687 (class 2606 OID 22926)
-- Name: application_costs application_costs_application_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.application_costs
    ADD CONSTRAINT application_costs_application_id_fkey FOREIGN KEY (application_id) REFERENCES public.applications(id) ON DELETE CASCADE DEFERRABLE;


--
-- TOC entry 3681 (class 2606 OID 21931)
-- Name: auth_tokens auth_tokens_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.auth_tokens
    ADD CONSTRAINT auth_tokens_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- TOC entry 3688 (class 2606 OID 22931)
-- Name: billing_activities billing_activities_application_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.billing_activities
    ADD CONSTRAINT billing_activities_application_id_fkey FOREIGN KEY (application_id) REFERENCES public.applications(id) ON DELETE CASCADE DEFERRABLE;


--
-- TOC entry 3689 (class 2606 OID 22042)
-- Name: billing_activities billing_activities_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.billing_activities
    ADD CONSTRAINT billing_activities_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- TOC entry 3684 (class 2606 OID 22921)
-- Name: deployments deployments_application_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.deployments
    ADD CONSTRAINT deployments_application_id_fkey FOREIGN KEY (application_id) REFERENCES public.applications(id) ON DELETE SET NULL DEFERRABLE;


--
-- TOC entry 3685 (class 2606 OID 22008)
-- Name: deployments deployments_server_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.deployments
    ADD CONSTRAINT deployments_server_id_fkey FOREIGN KEY (server_id) REFERENCES public.servers(id) ON DELETE SET NULL;


--
-- TOC entry 3686 (class 2606 OID 21998)
-- Name: deployments deployments_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.deployments
    ADD CONSTRAINT deployments_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- TOC entry 3699 (class 2606 OID 22269)
-- Name: serverless_jobs fk_user; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.serverless_jobs
    ADD CONSTRAINT fk_user FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- TOC entry 3695 (class 2606 OID 22164)
-- Name: instances instances_server_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.instances
    ADD CONSTRAINT instances_server_id_fkey FOREIGN KEY (server_id) REFERENCES public.servers(id);


--
-- TOC entry 3696 (class 2606 OID 22169)
-- Name: instances instances_service_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.instances
    ADD CONSTRAINT instances_service_id_fkey FOREIGN KEY (service_id) REFERENCES public.services(id) ON DELETE CASCADE;


--
-- TOC entry 3692 (class 2606 OID 22106)
-- Name: invoicing invoicing_payment_mode_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.invoicing
    ADD CONSTRAINT invoicing_payment_mode_id_fkey FOREIGN KEY (payment_mode_id) REFERENCES public.payment_modes(id) ON DELETE SET NULL;


--
-- TOC entry 3693 (class 2606 OID 22101)
-- Name: invoicing invoicing_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.invoicing
    ADD CONSTRAINT invoicing_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- TOC entry 3704 (class 2606 OID 22351)
-- Name: mig_instances mig_instances_server_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.mig_instances
    ADD CONSTRAINT mig_instances_server_id_fkey FOREIGN KEY (server_id) REFERENCES public.servers(id) ON DELETE CASCADE;


--
-- TOC entry 3703 (class 2606 OID 22329)
-- Name: mig_profiles mig_profiles_server_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.mig_profiles
    ADD CONSTRAINT mig_profiles_server_id_fkey FOREIGN KEY (server_id) REFERENCES public.servers(id) ON DELETE CASCADE;


--
-- TOC entry 3697 (class 2606 OID 22215)
-- Name: password_reset_tokens password_reset_tokens_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.password_reset_tokens
    ADD CONSTRAINT password_reset_tokens_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- TOC entry 3691 (class 2606 OID 22083)
-- Name: payment_modes payment_modes_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.payment_modes
    ADD CONSTRAINT payment_modes_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- TOC entry 3707 (class 2606 OID 22489)
-- Name: runtime_anomalies runtime_anomalies_container_pk_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.runtime_anomalies
    ADD CONSTRAINT runtime_anomalies_container_pk_fkey FOREIGN KEY (container_pk) REFERENCES public.runtime_containers(id) ON DELETE CASCADE;


--
-- TOC entry 3705 (class 2606 OID 22438)
-- Name: runtime_containers runtime_containers_server_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.runtime_containers
    ADD CONSTRAINT runtime_containers_server_id_fkey FOREIGN KEY (server_id) REFERENCES public.servers(id) ON DELETE CASCADE;


--
-- TOC entry 3706 (class 2606 OID 22462)
-- Name: runtime_observations runtime_observations_container_pk_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.runtime_observations
    ADD CONSTRAINT runtime_observations_container_pk_fkey FOREIGN KEY (container_pk) REFERENCES public.runtime_containers(id) ON DELETE CASCADE;


--
-- TOC entry 3708 (class 2606 OID 22509)
-- Name: runtime_scan_runs runtime_scan_runs_server_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.runtime_scan_runs
    ADD CONSTRAINT runtime_scan_runs_server_id_fkey FOREIGN KEY (server_id) REFERENCES public.servers(id) ON DELETE SET NULL;


--
-- TOC entry 3701 (class 2606 OID 22292)
-- Name: serverless_job_logs serverless_job_logs_job_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.serverless_job_logs
    ADD CONSTRAINT serverless_job_logs_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.serverless_jobs(id) ON DELETE CASCADE;


--
-- TOC entry 3702 (class 2606 OID 22307)
-- Name: serverless_job_results serverless_job_results_job_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.serverless_job_results
    ADD CONSTRAINT serverless_job_results_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.serverless_jobs(id) ON DELETE CASCADE;


--
-- TOC entry 3700 (class 2606 OID 22264)
-- Name: serverless_jobs serverless_jobs_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.serverless_jobs
    ADD CONSTRAINT serverless_jobs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- TOC entry 3694 (class 2606 OID 22140)
-- Name: services services_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.services
    ADD CONSTRAINT services_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- TOC entry 3698 (class 2606 OID 22237)
-- Name: twofa_email_codes twofa_email_codes_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.twofa_email_codes
    ADD CONSTRAINT twofa_email_codes_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- TOC entry 3682 (class 2606 OID 22916)
-- Name: user_applications user_applications_application_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.user_applications
    ADD CONSTRAINT user_applications_application_id_fkey FOREIGN KEY (application_id) REFERENCES public.applications(id) ON DELETE CASCADE DEFERRABLE;


--
-- TOC entry 3683 (class 2606 OID 21952)
-- Name: user_applications user_applications_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.user_applications
    ADD CONSTRAINT user_applications_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- TOC entry 3690 (class 2606 OID 22064)
-- Name: users_logs users_logs_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.users_logs
    ADD CONSTRAINT users_logs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


-- Completed on 2026-10-20 15:52:05 UTC

--
-- PostgreSQL database dump complete
--

\unrestrict cUDEw26rh1T8n8c2zHkQrpaQV6lV2ienPxcn1fBS8BArcXvDSgY1A1bA92CtCZW

