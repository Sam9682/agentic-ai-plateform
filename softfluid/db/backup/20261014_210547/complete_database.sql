--
-- PostgreSQL database dump
--

\restrict H3XQwYOvwGsOWCzHa78RJD7eThgfJ89KfQ5fBJ06iW4RMkenHmUf1AY69OO4V7g

-- Dumped from database version 18.6 (Ubuntu 18.6-0ubuntu0.26.04.1)
-- Dumped by pg_dump version 18.6 (Ubuntu 18.6-0ubuntu0.26.04.1)

-- Started on 2026-10-14 21:05:47 UTC

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

DROP DATABASE IF EXISTS ai_swautomorph;
--
-- TOC entry 3915 (class 1262 OID 20866)
-- Name: ai_swautomorph; Type: DATABASE; Schema: -; Owner: swautomorph
--

CREATE DATABASE ai_swautomorph WITH TEMPLATE = template0 ENCODING = 'UTF8' LOCALE_PROVIDER = libc LOCALE = 'C.UTF-8';


ALTER DATABASE ai_swautomorph OWNER TO swautomorph;

\unrestrict H3XQwYOvwGsOWCzHa78RJD7eThgfJ89KfQ5fBJ06iW4RMkenHmUf1AY69OO4V7g
\connect ai_swautomorph
\restrict H3XQwYOvwGsOWCzHa78RJD7eThgfJ89KfQ5fBJ06iW4RMkenHmUf1AY69OO4V7g

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
-- TOC entry 2 (class 3079 OID 20867)
-- Name: uuid-ossp; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA public;


--
-- TOC entry 3916 (class 0 OID 0)
-- Dependencies: 2
-- Name: EXTENSION "uuid-ossp"; Type: COMMENT; Schema: -; Owner: 
--

COMMENT ON EXTENSION "uuid-ossp" IS 'generate universally unique identifiers (UUIDs)';


--
-- TOC entry 280 (class 1255 OID 21190)
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
-- TOC entry 233 (class 1259 OID 21009)
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
-- TOC entry 232 (class 1259 OID 21008)
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
-- TOC entry 3917 (class 0 OID 0)
-- Dependencies: 232
-- Name: application_costs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.application_costs_id_seq OWNED BY public.application_costs.id;


--
-- TOC entry 223 (class 1259 OID 20898)
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
-- TOC entry 222 (class 1259 OID 20897)
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
-- TOC entry 3918 (class 0 OID 0)
-- Dependencies: 222
-- Name: applications_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.applications_id_seq OWNED BY public.applications.id;


--
-- TOC entry 225 (class 1259 OID 20913)
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
-- TOC entry 224 (class 1259 OID 20912)
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
-- TOC entry 3919 (class 0 OID 0)
-- Dependencies: 224
-- Name: auth_tokens_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.auth_tokens_id_seq OWNED BY public.auth_tokens.id;


--
-- TOC entry 235 (class 1259 OID 21026)
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
-- TOC entry 234 (class 1259 OID 21025)
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
-- TOC entry 3920 (class 0 OID 0)
-- Dependencies: 234
-- Name: billing_activities_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.billing_activities_id_seq OWNED BY public.billing_activities.id;


--
-- TOC entry 243 (class 1259 OID 21107)
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
-- TOC entry 242 (class 1259 OID 21106)
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
-- TOC entry 3921 (class 0 OID 0)
-- Dependencies: 242
-- Name: configuration_param_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.configuration_param_id_seq OWNED BY public.configuration.param_id;


--
-- TOC entry 261 (class 1259 OID 21373)
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
-- TOC entry 260 (class 1259 OID 21372)
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
-- TOC entry 3922 (class 0 OID 0)
-- Dependencies: 260
-- Name: deploy_templates_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.deploy_templates_id_seq OWNED BY public.deploy_templates.id;


--
-- TOC entry 231 (class 1259 OID 20977)
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
-- TOC entry 3923 (class 0 OID 0)
-- Dependencies: 231
-- Name: COLUMN deployments.modification_history; Type: COMMENT; Schema: public; Owner: swautomorph
--

COMMENT ON COLUMN public.deployments.modification_history IS 'JSON array containing modification history with branch names and Gitea URLs';


--
-- TOC entry 3924 (class 0 OID 0)
-- Dependencies: 231
-- Name: COLUMN deployments.backups_history; Type: COMMENT; Schema: public; Owner: swautomorph
--

COMMENT ON COLUMN public.deployments.backups_history IS 'JSON array containing backup history with links to PostgreSQL database backups in S3';


--
-- TOC entry 230 (class 1259 OID 20976)
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
-- TOC entry 3925 (class 0 OID 0)
-- Dependencies: 230
-- Name: deployments_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.deployments_id_seq OWNED BY public.deployments.id;


--
-- TOC entry 247 (class 1259 OID 21141)
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
-- TOC entry 246 (class 1259 OID 21140)
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
-- TOC entry 3926 (class 0 OID 0)
-- Dependencies: 246
-- Name: instances_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.instances_id_seq OWNED BY public.instances.id;


--
-- TOC entry 241 (class 1259 OID 21084)
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
-- TOC entry 240 (class 1259 OID 21083)
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
-- TOC entry 3927 (class 0 OID 0)
-- Dependencies: 240
-- Name: invoicing_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.invoicing_id_seq OWNED BY public.invoicing.id;


--
-- TOC entry 259 (class 1259 OID 21331)
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
-- TOC entry 258 (class 1259 OID 21330)
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
-- TOC entry 3928 (class 0 OID 0)
-- Dependencies: 258
-- Name: mig_instances_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.mig_instances_id_seq OWNED BY public.mig_instances.id;


--
-- TOC entry 257 (class 1259 OID 21309)
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
-- TOC entry 256 (class 1259 OID 21308)
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
-- TOC entry 3929 (class 0 OID 0)
-- Dependencies: 256
-- Name: mig_profiles_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.mig_profiles_id_seq OWNED BY public.mig_profiles.id;


--
-- TOC entry 249 (class 1259 OID 21196)
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
-- TOC entry 248 (class 1259 OID 21195)
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
-- TOC entry 3930 (class 0 OID 0)
-- Dependencies: 248
-- Name: password_reset_tokens_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.password_reset_tokens_id_seq OWNED BY public.password_reset_tokens.id;


--
-- TOC entry 239 (class 1259 OID 21065)
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
-- TOC entry 238 (class 1259 OID 21064)
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
-- TOC entry 3931 (class 0 OID 0)
-- Dependencies: 238
-- Name: payment_modes_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.payment_modes_id_seq OWNED BY public.payment_modes.id;


--
-- TOC entry 267 (class 1259 OID 21545)
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
-- TOC entry 266 (class 1259 OID 21544)
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
-- TOC entry 3932 (class 0 OID 0)
-- Dependencies: 266
-- Name: runtime_anomalies_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.runtime_anomalies_id_seq OWNED BY public.runtime_anomalies.id;


--
-- TOC entry 263 (class 1259 OID 21486)
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
-- TOC entry 262 (class 1259 OID 21485)
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
-- TOC entry 3933 (class 0 OID 0)
-- Dependencies: 262
-- Name: runtime_containers_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.runtime_containers_id_seq OWNED BY public.runtime_containers.id;


--
-- TOC entry 265 (class 1259 OID 21523)
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
-- TOC entry 264 (class 1259 OID 21522)
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
-- TOC entry 3934 (class 0 OID 0)
-- Dependencies: 264
-- Name: runtime_observations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.runtime_observations_id_seq OWNED BY public.runtime_observations.id;


--
-- TOC entry 269 (class 1259 OID 21573)
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
-- TOC entry 268 (class 1259 OID 21572)
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
-- TOC entry 3935 (class 0 OID 0)
-- Dependencies: 268
-- Name: runtime_scan_runs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.runtime_scan_runs_id_seq OWNED BY public.runtime_scan_runs.id;


--
-- TOC entry 254 (class 1259 OID 21273)
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
-- TOC entry 253 (class 1259 OID 21272)
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
-- TOC entry 3936 (class 0 OID 0)
-- Dependencies: 253
-- Name: serverless_job_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.serverless_job_logs_id_seq OWNED BY public.serverless_job_logs.id;


--
-- TOC entry 255 (class 1259 OID 21293)
-- Name: serverless_job_results; Type: TABLE; Schema: public; Owner: swautomorph
--

CREATE TABLE public.serverless_job_results (
    job_id uuid NOT NULL,
    result jsonb,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.serverless_job_results OWNER TO swautomorph;

--
-- TOC entry 252 (class 1259 OID 21239)
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
-- TOC entry 3937 (class 0 OID 0)
-- Dependencies: 252
-- Name: COLUMN serverless_jobs.target_link; Type: COMMENT; Schema: public; Owner: swautomorph
--

COMMENT ON COLUMN public.serverless_jobs.target_link IS 'The agentic-ai-plateform-serverless-brik endpoint URL selected for job execution';


--
-- TOC entry 229 (class 1259 OID 20958)
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
-- TOC entry 228 (class 1259 OID 20957)
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
-- TOC entry 3938 (class 0 OID 0)
-- Dependencies: 228
-- Name: servers_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.servers_id_seq OWNED BY public.servers.id;


--
-- TOC entry 245 (class 1259 OID 21117)
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
-- TOC entry 244 (class 1259 OID 21116)
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
-- TOC entry 3939 (class 0 OID 0)
-- Dependencies: 244
-- Name: services_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.services_id_seq OWNED BY public.services.id;


--
-- TOC entry 251 (class 1259 OID 21220)
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
-- TOC entry 250 (class 1259 OID 21219)
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
-- TOC entry 3940 (class 0 OID 0)
-- Dependencies: 250
-- Name: twofa_email_codes_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.twofa_email_codes_id_seq OWNED BY public.twofa_email_codes.id;


--
-- TOC entry 227 (class 1259 OID 20932)
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
-- TOC entry 3941 (class 0 OID 0)
-- Dependencies: 227
-- Name: COLUMN user_applications.http_port3; Type: COMMENT; Schema: public; Owner: swautomorph
--

COMMENT ON COLUMN public.user_applications.http_port3 IS 'Third HTTP port allocated to the application';


--
-- TOC entry 3942 (class 0 OID 0)
-- Dependencies: 227
-- Name: COLUMN user_applications.https_port3; Type: COMMENT; Schema: public; Owner: swautomorph
--

COMMENT ON COLUMN public.user_applications.https_port3 IS 'Third HTTPS port allocated to the application';


--
-- TOC entry 3943 (class 0 OID 0)
-- Dependencies: 227
-- Name: COLUMN user_applications.http_port4; Type: COMMENT; Schema: public; Owner: swautomorph
--

COMMENT ON COLUMN public.user_applications.http_port4 IS 'Fourth HTTP port allocated to the application';


--
-- TOC entry 3944 (class 0 OID 0)
-- Dependencies: 227
-- Name: COLUMN user_applications.https_port4; Type: COMMENT; Schema: public; Owner: swautomorph
--

COMMENT ON COLUMN public.user_applications.https_port4 IS 'Fourth HTTPS port allocated to the application';


--
-- TOC entry 3945 (class 0 OID 0)
-- Dependencies: 227
-- Name: COLUMN user_applications.http_port5; Type: COMMENT; Schema: public; Owner: swautomorph
--

COMMENT ON COLUMN public.user_applications.http_port5 IS 'Fifth HTTP port allocated to the application';


--
-- TOC entry 3946 (class 0 OID 0)
-- Dependencies: 227
-- Name: COLUMN user_applications.https_port5; Type: COMMENT; Schema: public; Owner: swautomorph
--

COMMENT ON COLUMN public.user_applications.https_port5 IS 'Fifth HTTPS port allocated to the application';


--
-- TOC entry 3947 (class 0 OID 0)
-- Dependencies: 227
-- Name: COLUMN user_applications.http_port6; Type: COMMENT; Schema: public; Owner: swautomorph
--

COMMENT ON COLUMN public.user_applications.http_port6 IS 'Sixth HTTP port allocated to the application';


--
-- TOC entry 3948 (class 0 OID 0)
-- Dependencies: 227
-- Name: COLUMN user_applications.https_port6; Type: COMMENT; Schema: public; Owner: swautomorph
--

COMMENT ON COLUMN public.user_applications.https_port6 IS 'Sixth HTTPS port allocated to the application';


--
-- TOC entry 226 (class 1259 OID 20931)
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
-- TOC entry 3949 (class 0 OID 0)
-- Dependencies: 226
-- Name: user_applications_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.user_applications_id_seq OWNED BY public.user_applications.id;


--
-- TOC entry 221 (class 1259 OID 20879)
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
-- TOC entry 220 (class 1259 OID 20878)
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
-- TOC entry 3950 (class 0 OID 0)
-- Dependencies: 220
-- Name: users_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;


--
-- TOC entry 237 (class 1259 OID 21048)
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
-- TOC entry 236 (class 1259 OID 21047)
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
-- TOC entry 3951 (class 0 OID 0)
-- Dependencies: 236
-- Name: users_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.users_logs_id_seq OWNED BY public.users_logs.id;


--
-- TOC entry 3484 (class 2604 OID 21012)
-- Name: application_costs id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.application_costs ALTER COLUMN id SET DEFAULT nextval('public.application_costs_id_seq'::regclass);


--
-- TOC entry 3466 (class 2604 OID 20901)
-- Name: applications id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.applications ALTER COLUMN id SET DEFAULT nextval('public.applications_id_seq'::regclass);


--
-- TOC entry 3469 (class 2604 OID 20916)
-- Name: auth_tokens id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.auth_tokens ALTER COLUMN id SET DEFAULT nextval('public.auth_tokens_id_seq'::regclass);


--
-- TOC entry 3488 (class 2604 OID 21029)
-- Name: billing_activities id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.billing_activities ALTER COLUMN id SET DEFAULT nextval('public.billing_activities_id_seq'::regclass);


--
-- TOC entry 3498 (class 2604 OID 21110)
-- Name: configuration param_id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.configuration ALTER COLUMN param_id SET DEFAULT nextval('public.configuration_param_id_seq'::regclass);


--
-- TOC entry 3527 (class 2604 OID 21376)
-- Name: deploy_templates id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.deploy_templates ALTER COLUMN id SET DEFAULT nextval('public.deploy_templates_id_seq'::regclass);


--
-- TOC entry 3477 (class 2604 OID 20980)
-- Name: deployments id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.deployments ALTER COLUMN id SET DEFAULT nextval('public.deployments_id_seq'::regclass);


--
-- TOC entry 3504 (class 2604 OID 21144)
-- Name: instances id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.instances ALTER COLUMN id SET DEFAULT nextval('public.instances_id_seq'::regclass);


--
-- TOC entry 3495 (class 2604 OID 21087)
-- Name: invoicing id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.invoicing ALTER COLUMN id SET DEFAULT nextval('public.invoicing_id_seq'::regclass);


--
-- TOC entry 3525 (class 2604 OID 21334)
-- Name: mig_instances id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.mig_instances ALTER COLUMN id SET DEFAULT nextval('public.mig_instances_id_seq'::regclass);


--
-- TOC entry 3523 (class 2604 OID 21312)
-- Name: mig_profiles id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.mig_profiles ALTER COLUMN id SET DEFAULT nextval('public.mig_profiles_id_seq'::regclass);


--
-- TOC entry 3509 (class 2604 OID 21199)
-- Name: password_reset_tokens id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.password_reset_tokens ALTER COLUMN id SET DEFAULT nextval('public.password_reset_tokens_id_seq'::regclass);


--
-- TOC entry 3492 (class 2604 OID 21068)
-- Name: payment_modes id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.payment_modes ALTER COLUMN id SET DEFAULT nextval('public.payment_modes_id_seq'::regclass);


--
-- TOC entry 3545 (class 2604 OID 21548)
-- Name: runtime_anomalies id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.runtime_anomalies ALTER COLUMN id SET DEFAULT nextval('public.runtime_anomalies_id_seq'::regclass);


--
-- TOC entry 3532 (class 2604 OID 21489)
-- Name: runtime_containers id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.runtime_containers ALTER COLUMN id SET DEFAULT nextval('public.runtime_containers_id_seq'::regclass);


--
-- TOC entry 3541 (class 2604 OID 21526)
-- Name: runtime_observations id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.runtime_observations ALTER COLUMN id SET DEFAULT nextval('public.runtime_observations_id_seq'::regclass);


--
-- TOC entry 3550 (class 2604 OID 21576)
-- Name: runtime_scan_runs id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.runtime_scan_runs ALTER COLUMN id SET DEFAULT nextval('public.runtime_scan_runs_id_seq'::regclass);


--
-- TOC entry 3520 (class 2604 OID 21276)
-- Name: serverless_job_logs id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.serverless_job_logs ALTER COLUMN id SET DEFAULT nextval('public.serverless_job_logs_id_seq'::regclass);


--
-- TOC entry 3473 (class 2604 OID 20961)
-- Name: servers id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.servers ALTER COLUMN id SET DEFAULT nextval('public.servers_id_seq'::regclass);


--
-- TOC entry 3499 (class 2604 OID 21120)
-- Name: services id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.services ALTER COLUMN id SET DEFAULT nextval('public.services_id_seq'::regclass);


--
-- TOC entry 3512 (class 2604 OID 21223)
-- Name: twofa_email_codes id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.twofa_email_codes ALTER COLUMN id SET DEFAULT nextval('public.twofa_email_codes_id_seq'::regclass);


--
-- TOC entry 3471 (class 2604 OID 20935)
-- Name: user_applications id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.user_applications ALTER COLUMN id SET DEFAULT nextval('public.user_applications_id_seq'::regclass);


--
-- TOC entry 3461 (class 2604 OID 20882)
-- Name: users id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);


--
-- TOC entry 3490 (class 2604 OID 21051)
-- Name: users_logs id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.users_logs ALTER COLUMN id SET DEFAULT nextval('public.users_logs_id_seq'::regclass);


--
-- TOC entry 3873 (class 0 OID 21009)
-- Dependencies: 233
-- Data for Name: application_costs; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.application_costs (id, application_id, cost_per_day, created_at, updated_at) FROM stdin;
1	1	1.00	2026-10-10 08:58:18.205029+00	2026-10-10 08:58:18.205029+00
2	2	1.00	2026-10-10 08:58:18.206607+00	2026-10-10 08:58:18.206607+00
3	3	1.00	2026-10-10 08:58:18.206607+00	2026-10-10 08:58:18.206607+00
4	28	1.00	2026-10-14 20:43:29.040771+00	2026-10-14 20:43:29.040771+00
\.


--
-- TOC entry 3863 (class 0 OID 20898)
-- Dependencies: 223
-- Data for Name: applications; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.applications (id, name, url, description, git_url, git_remote_url, git_local_url, git_repo_size, docker_build_duration, docker_start_duration, docker_stop_duration, docker_ps_duration, docker_compose_ports, created_at) FROM stdin;
1	opcp-serverless-brik	\N	agentic-ai-plateform Serverless Docker Execution	https://github.com/Sam9682/opcp-serverless-brik.git	\N	\N	10	30	30	10	1	\N	2026-10-10 08:58:18.205029+00
2	ai-staticwebsite	\N	Simple static Web Site	https://github.com/Sam9682/ai-staticwebsite.git	\N	\N	4	29	29	10	1	\N	2026-10-10 08:58:18.206607+00
3	ai-shai-web-interface	\N	Interface Web pour Shai	https://github.com/Sam9682/ai-shai-web-interface.git	\N	\N	10	30	30	10	1	\N	2026-10-10 08:58:18.206607+00
28	ai-hypervisia		Hypervisia AI Think Tank	https://github.com/Sam9682/ai-hypervisia.git	\N	\N	50	60	30	10	1	\N	2026-10-13 08:01:49.695491+00
\.


--
-- TOC entry 3865 (class 0 OID 20913)
-- Dependencies: 225
-- Data for Name: auth_tokens; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.auth_tokens (id, user_id, token_hash, expires_at, created_at) FROM stdin;
2	1	7d18b6d332ab82fdd31b368757e5ad456ae19cc69f1c9d5949cd050d921887f2	2026-10-21 20:15:35.32256+00	2026-10-14 20:15:35.322741+00
\.


--
-- TOC entry 3875 (class 0 OID 21026)
-- Dependencies: 235
-- Data for Name: billing_activities; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.billing_activities (id, user_id, application_id, action, started_at, stopped_at, duration_seconds, cost_amount, created_at) FROM stdin;
\.


--
-- TOC entry 3883 (class 0 OID 21107)
-- Dependencies: 243
-- Data for Name: configuration; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.configuration (param_id, parent, key, value) FROM stdin;
1	\N	agentic_engine	kiro-cli
2	\N	agentic_command	
3	\N	runtime_type	runc
\.


--
-- TOC entry 3901 (class 0 OID 21373)
-- Dependencies: 261
-- Data for Name: deploy_templates; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.deploy_templates (id, template_id, app_type, display_name, source_image, ports, environment, memory_mb, cpu_cores, timeout_seconds, enabled, created_at) FROM stdin;
1	static-site	static_site	Static Website	nginx:1.27-alpine	[{"protocol": "http", "container": 80}]	[]	128	0.5	300	t	2026-10-10 08:58:18.201071+00
2	fastapi-starter	fastapi	FastAPI Application	tiangolo/uvicorn-gunicorn-fastapi:python3.11	[{"protocol": "http", "container": 80}]	[{"name": "MODULE_NAME", "value": "app.main"}]	512	1.0	300	t	2026-10-10 08:58:18.201071+00
3	n8n	n8n	n8n Workflow Automation	n8nio/n8n:latest	[{"protocol": "http", "container": 5678}]	[{"name": "N8N_PORT", "value": "5678"}]	1024	1.0	600	t	2026-10-10 08:58:18.201071+00
4	ollama	ollama	Ollama LLM Runtime	ollama/ollama:latest	[{"protocol": "http", "container": 11434}]	[{"name": "OLLAMA_HOST", "value": "0.0.0.0"}]	4096	2.0	1200	t	2026-10-10 08:58:18.201071+00
5	jupyter	jupyter	Jupyter Notebook	jupyter/base-notebook:latest	[{"protocol": "http", "container": 8888}]	[{"name": "JUPYTER_ENABLE_LAB", "value": "yes"}]	2048	1.0	600	t	2026-10-10 08:58:18.201071+00
6	vector-db	vector_db	Qdrant Vector Database	qdrant/qdrant:latest	[{"protocol": "http", "container": 6333}]	[]	1024	1.0	300	t	2026-10-10 08:58:18.201071+00
\.


--
-- TOC entry 3871 (class 0 OID 20977)
-- Dependencies: 231
-- Data for Name: deployments; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.deployments (id, user_id, application_id, application_name, status, deployment_path, git_url, swautomorph_url, gitea_branch_url, modification_history, backups_history, server_id, created_at, updated_at, is_sandbox) FROM stdin;
1	1	1	opcp-serverless-brik	RUNNING	\N	\N	https://agentic-ai-plateform.com/admin/opcp-serverless-brik	\N	[]	[]	1	2026-10-10 09:03:25.18589+00	2026-10-10 09:03:25.18589+00	f
2	1	28	ai-hypervisia	COMPLETED	/home/partipolia/deployments/admin/ai-hypervisia	https://github.com/Sam9682/ai-hypervisia.git	https://agentic-ai-plateform.com/admin/ai-hypervisia	https://github.com/Sam9682/ai-hypervisia.git	[]	[]	1	2026-10-13 08:05:22.20465+00	2026-10-14 21:05:45.828128+00	f
\.


--
-- TOC entry 3887 (class 0 OID 21141)
-- Dependencies: 247
-- Data for Name: instances; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.instances (id, service_id, instance_id, server_id, service_name, container_id, status, port, health_status, last_health_check, created_at, updated_at) FROM stdin;
\.


--
-- TOC entry 3881 (class 0 OID 21084)
-- Dependencies: 241
-- Data for Name: invoicing; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.invoicing (id, user_id, invoice_month, total_amount, status, payment_date, payment_mode_id, created_at) FROM stdin;
\.


--
-- TOC entry 3899 (class 0 OID 21331)
-- Dependencies: 259
-- Data for Name: mig_instances; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.mig_instances (id, server_id, instance_uuid, profile_name, gpu_memory_mb, created_at) FROM stdin;
\.


--
-- TOC entry 3897 (class 0 OID 21309)
-- Dependencies: 257
-- Data for Name: mig_profiles; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.mig_profiles (id, server_id, profile_name, profile_id, gpu_memory_gb, created_at) FROM stdin;
\.


--
-- TOC entry 3889 (class 0 OID 21196)
-- Dependencies: 249
-- Data for Name: password_reset_tokens; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.password_reset_tokens (id, user_id, token_hash, expires_at, used, created_at) FROM stdin;
\.


--
-- TOC entry 3879 (class 0 OID 21065)
-- Dependencies: 239
-- Data for Name: payment_modes; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.payment_modes (id, user_id, payment_type, bank_account, paypal_email, card_last_four, card_type, is_default, created_at) FROM stdin;
1	2	bank_transfer	\N	\N	\N	\N	t	2026-10-10 08:58:18.207615+00
\.


--
-- TOC entry 3907 (class 0 OID 21545)
-- Dependencies: 267
-- Data for Name: runtime_anomalies; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.runtime_anomalies (id, container_pk, rule_id, severity, evidence, status, detected_at) FROM stdin;
\.


--
-- TOC entry 3903 (class 0 OID 21486)
-- Dependencies: 263
-- Data for Name: runtime_containers; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.runtime_containers (id, server_id, container_id, name, image, runtime, state, is_platform_managed, classification, confidence_score, classification_evidence, labels, first_seen, last_seen) FROM stdin;
\.


--
-- TOC entry 3905 (class 0 OID 21523)
-- Dependencies: 265
-- Data for Name: runtime_observations; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.runtime_observations (id, container_pk, cpu_percent, memory_bytes, pids, process_summary, network_summary, state, observed_at) FROM stdin;
\.


--
-- TOC entry 3909 (class 0 OID 21573)
-- Dependencies: 269
-- Data for Name: runtime_scan_runs; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.runtime_scan_runs (id, server_id, started_at, finished_at, containers_seen, error) FROM stdin;
\.


--
-- TOC entry 3894 (class 0 OID 21273)
-- Dependencies: 254
-- Data for Name: serverless_job_logs; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.serverless_job_logs (id, job_id, stream, content, created_at) FROM stdin;
\.


--
-- TOC entry 3895 (class 0 OID 21293)
-- Dependencies: 255
-- Data for Name: serverless_job_results; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.serverless_job_results (job_id, result, created_at) FROM stdin;
\.


--
-- TOC entry 3892 (class 0 OID 21239)
-- Dependencies: 252
-- Data for Name: serverless_jobs; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.serverless_jobs (id, user_id, image, command, environment, timeout_seconds, status, created_at, started_at, completed_at, exit_code, worker_id, target_link) FROM stdin;
\.


--
-- TOC entry 3869 (class 0 OID 20958)
-- Dependencies: 229
-- Data for Name: servers; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.servers (id, server_ip, server_name, server_capacity_user_max, server_capacity_appli_max, server_status, server_type, created_at, shared_gpu_enabled) FROM stdin;
1	192.168.0.30	main-server	10	50	ACTIVE	STAND_ALONE	2026-10-10 08:58:18.207615+00	f
\.


--
-- TOC entry 3885 (class 0 OID 21117)
-- Dependencies: 245
-- Data for Name: services; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.services (id, name, image, user_id, desired_replicas, ports, environment, volumes, health_check_path, created_at, updated_at) FROM stdin;
\.


--
-- TOC entry 3891 (class 0 OID 21220)
-- Dependencies: 251
-- Data for Name: twofa_email_codes; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.twofa_email_codes (id, user_id, code, expires_at, used, created_at) FROM stdin;
\.


--
-- TOC entry 3867 (class 0 OID 20932)
-- Dependencies: 227
-- Data for Name: user_applications; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.user_applications (id, user_id, application_id, url, http_port, https_port, http_port2, https_port2, http_port3, https_port3, http_port4, https_port4, http_port5, https_port5, http_port6, https_port6, others_port, created_at) FROM stdin;
1	2	1	https://www.agentic-ai-plateform.com:6212	6213	6212	6215	6214	6217	6216	6219	6218	6221	6220	6223	6222	\N	2026-10-10 08:58:18.207615+00
2	2	2	https://www.agentic-ai-plateform.com:6224	6225	6224	6227	6226	6229	6228	6231	6230	6233	6232	6235	6234	\N	2026-10-10 08:58:18.207615+00
3	2	3	https://www.agentic-ai-plateform.com:6236	6237	6236	6239	6238	6241	6240	6243	6242	6245	6244	6247	6246	\N	2026-10-10 08:58:18.207615+00
4	1	1	https://www.agentic-ai-plateform.com:6112	6113	6112	6115	6114	6117	6116	6119	6118	6121	6120	6123	6122	\N	2026-10-10 09:03:25.18589+00
7	1	28	https://agentic-ai-plateform.com:6436	6437	6436	6439	6438	6441	6440	6443	6442	6445	6444	6447	6446	\N	2026-10-13 08:03:53.875529+00
\.


--
-- TOC entry 3861 (class 0 OID 20879)
-- Dependencies: 221
-- Data for Name: users; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.users (id, username, email, password_hash, first_name, last_name, suspended, created_at, totp_secret, totp_enabled, totp_backup_codes, twofa_email_enabled, account_type) FROM stdin;
1	admin	admin@agentic-ai-plateform.com	scrypt:32768:8:1$9zoQjSeQUjjnTABn$ad48ef0c4c9d1a677e1acca9170c1e15ff4eacaf8386bc57cca5319c0fd8f1ff3b4b49f321a93d71b21036fe2269e2b510161db767c2462366ee7c3e394ed19d	System	Administrator	f	2026-10-10 08:58:18.207615+00	\N	f	\N	f	\N
2	demo	demo@agentic-ai-plateform.com	scrypt:32768:8:1$B2cAABx8l6QgtBW4$87e2dd1a54e4eeed435c7428bbe42514073560c89b9edf3d220ae28b9122d2166ed072b20055a9060dededfcf7efeb091d15f168ac43731173d7c5e9989a8333	System	Demo	f	2026-10-10 08:58:18.207615+00	\N	f	\N	f	\N
\.


--
-- TOC entry 3877 (class 0 OID 21048)
-- Dependencies: 237
-- Data for Name: users_logs; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.users_logs (id, user_id, username, action, datetime) FROM stdin;
1	1	admin	logout	2026-10-10 09:04:11.605708+00
2	1	admin	login	2026-10-10 09:04:18.233585+00
3	1	admin	login	2026-10-14 20:15:35.324395+00
\.


--
-- TOC entry 3952 (class 0 OID 0)
-- Dependencies: 232
-- Name: application_costs_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.application_costs_id_seq', 4, true);


--
-- TOC entry 3953 (class 0 OID 0)
-- Dependencies: 222
-- Name: applications_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.applications_id_seq', 43, true);


--
-- TOC entry 3954 (class 0 OID 0)
-- Dependencies: 224
-- Name: auth_tokens_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.auth_tokens_id_seq', 2, true);


--
-- TOC entry 3955 (class 0 OID 0)
-- Dependencies: 234
-- Name: billing_activities_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.billing_activities_id_seq', 1, false);


--
-- TOC entry 3956 (class 0 OID 0)
-- Dependencies: 242
-- Name: configuration_param_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.configuration_param_id_seq', 3, true);


--
-- TOC entry 3957 (class 0 OID 0)
-- Dependencies: 260
-- Name: deploy_templates_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.deploy_templates_id_seq', 114, true);


--
-- TOC entry 3958 (class 0 OID 0)
-- Dependencies: 230
-- Name: deployments_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.deployments_id_seq', 2, true);


--
-- TOC entry 3959 (class 0 OID 0)
-- Dependencies: 246
-- Name: instances_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.instances_id_seq', 1, false);


--
-- TOC entry 3960 (class 0 OID 0)
-- Dependencies: 240
-- Name: invoicing_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.invoicing_id_seq', 1, false);


--
-- TOC entry 3961 (class 0 OID 0)
-- Dependencies: 258
-- Name: mig_instances_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.mig_instances_id_seq', 1, false);


--
-- TOC entry 3962 (class 0 OID 0)
-- Dependencies: 256
-- Name: mig_profiles_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.mig_profiles_id_seq', 1, false);


--
-- TOC entry 3963 (class 0 OID 0)
-- Dependencies: 248
-- Name: password_reset_tokens_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.password_reset_tokens_id_seq', 1, false);


--
-- TOC entry 3964 (class 0 OID 0)
-- Dependencies: 238
-- Name: payment_modes_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.payment_modes_id_seq', 1, true);


--
-- TOC entry 3965 (class 0 OID 0)
-- Dependencies: 266
-- Name: runtime_anomalies_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.runtime_anomalies_id_seq', 1, false);


--
-- TOC entry 3966 (class 0 OID 0)
-- Dependencies: 262
-- Name: runtime_containers_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.runtime_containers_id_seq', 1, false);


--
-- TOC entry 3967 (class 0 OID 0)
-- Dependencies: 264
-- Name: runtime_observations_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.runtime_observations_id_seq', 1, false);


--
-- TOC entry 3968 (class 0 OID 0)
-- Dependencies: 268
-- Name: runtime_scan_runs_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.runtime_scan_runs_id_seq', 1, false);


--
-- TOC entry 3969 (class 0 OID 0)
-- Dependencies: 253
-- Name: serverless_job_logs_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.serverless_job_logs_id_seq', 1, false);


--
-- TOC entry 3970 (class 0 OID 0)
-- Dependencies: 228
-- Name: servers_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.servers_id_seq', 1, true);


--
-- TOC entry 3971 (class 0 OID 0)
-- Dependencies: 244
-- Name: services_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.services_id_seq', 1, false);


--
-- TOC entry 3972 (class 0 OID 0)
-- Dependencies: 250
-- Name: twofa_email_codes_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.twofa_email_codes_id_seq', 1, false);


--
-- TOC entry 3973 (class 0 OID 0)
-- Dependencies: 226
-- Name: user_applications_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.user_applications_id_seq', 7, true);


--
-- TOC entry 3974 (class 0 OID 0)
-- Dependencies: 220
-- Name: users_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.users_id_seq', 2, true);


--
-- TOC entry 3975 (class 0 OID 0)
-- Dependencies: 236
-- Name: users_logs_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.users_logs_id_seq', 3, true);


--
-- TOC entry 3601 (class 2606 OID 21019)
-- Name: application_costs application_costs_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.application_costs
    ADD CONSTRAINT application_costs_pkey PRIMARY KEY (id);


--
-- TOC entry 3573 (class 2606 OID 20911)
-- Name: applications applications_name_key; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.applications
    ADD CONSTRAINT applications_name_key UNIQUE (name);


--
-- TOC entry 3575 (class 2606 OID 20909)
-- Name: applications applications_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.applications
    ADD CONSTRAINT applications_pkey PRIMARY KEY (id);


--
-- TOC entry 3578 (class 2606 OID 20923)
-- Name: auth_tokens auth_tokens_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.auth_tokens
    ADD CONSTRAINT auth_tokens_pkey PRIMARY KEY (id);


--
-- TOC entry 3580 (class 2606 OID 20925)
-- Name: auth_tokens auth_tokens_token_hash_key; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.auth_tokens
    ADD CONSTRAINT auth_tokens_token_hash_key UNIQUE (token_hash);


--
-- TOC entry 3603 (class 2606 OID 21036)
-- Name: billing_activities billing_activities_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.billing_activities
    ADD CONSTRAINT billing_activities_pkey PRIMARY KEY (id);


--
-- TOC entry 3616 (class 2606 OID 21115)
-- Name: configuration configuration_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.configuration
    ADD CONSTRAINT configuration_pkey PRIMARY KEY (param_id);


--
-- TOC entry 3660 (class 2606 OID 21398)
-- Name: deploy_templates deploy_templates_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.deploy_templates
    ADD CONSTRAINT deploy_templates_pkey PRIMARY KEY (id);


--
-- TOC entry 3662 (class 2606 OID 21400)
-- Name: deploy_templates deploy_templates_template_id_key; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.deploy_templates
    ADD CONSTRAINT deploy_templates_template_id_key UNIQUE (template_id);


--
-- TOC entry 3594 (class 2606 OID 20992)
-- Name: deployments deployments_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.deployments
    ADD CONSTRAINT deployments_pkey PRIMARY KEY (id);


--
-- TOC entry 3626 (class 2606 OID 21156)
-- Name: instances instances_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.instances
    ADD CONSTRAINT instances_pkey PRIMARY KEY (id);


--
-- TOC entry 3628 (class 2606 OID 21158)
-- Name: instances instances_service_id_instance_id_key; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.instances
    ADD CONSTRAINT instances_service_id_instance_id_key UNIQUE (service_id, instance_id);


--
-- TOC entry 3614 (class 2606 OID 21095)
-- Name: invoicing invoicing_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.invoicing
    ADD CONSTRAINT invoicing_pkey PRIMARY KEY (id);


--
-- TOC entry 3656 (class 2606 OID 21343)
-- Name: mig_instances mig_instances_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.mig_instances
    ADD CONSTRAINT mig_instances_pkey PRIMARY KEY (id);


--
-- TOC entry 3658 (class 2606 OID 21345)
-- Name: mig_instances mig_instances_server_id_instance_uuid_key; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.mig_instances
    ADD CONSTRAINT mig_instances_server_id_instance_uuid_key UNIQUE (server_id, instance_uuid);


--
-- TOC entry 3651 (class 2606 OID 21321)
-- Name: mig_profiles mig_profiles_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.mig_profiles
    ADD CONSTRAINT mig_profiles_pkey PRIMARY KEY (id);


--
-- TOC entry 3653 (class 2606 OID 21323)
-- Name: mig_profiles mig_profiles_server_id_profile_name_key; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.mig_profiles
    ADD CONSTRAINT mig_profiles_server_id_profile_name_key UNIQUE (server_id, profile_name);


--
-- TOC entry 3632 (class 2606 OID 21207)
-- Name: password_reset_tokens password_reset_tokens_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.password_reset_tokens
    ADD CONSTRAINT password_reset_tokens_pkey PRIMARY KEY (id);


--
-- TOC entry 3634 (class 2606 OID 21209)
-- Name: password_reset_tokens password_reset_tokens_token_hash_key; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.password_reset_tokens
    ADD CONSTRAINT password_reset_tokens_token_hash_key UNIQUE (token_hash);


--
-- TOC entry 3612 (class 2606 OID 21077)
-- Name: payment_modes payment_modes_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.payment_modes
    ADD CONSTRAINT payment_modes_pkey PRIMARY KEY (id);


--
-- TOC entry 3677 (class 2606 OID 21564)
-- Name: runtime_anomalies runtime_anomalies_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.runtime_anomalies
    ADD CONSTRAINT runtime_anomalies_pkey PRIMARY KEY (id);


--
-- TOC entry 3668 (class 2606 OID 21511)
-- Name: runtime_containers runtime_containers_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.runtime_containers
    ADD CONSTRAINT runtime_containers_pkey PRIMARY KEY (id);


--
-- TOC entry 3673 (class 2606 OID 21537)
-- Name: runtime_observations runtime_observations_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.runtime_observations
    ADD CONSTRAINT runtime_observations_pkey PRIMARY KEY (id);


--
-- TOC entry 3680 (class 2606 OID 21584)
-- Name: runtime_scan_runs runtime_scan_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.runtime_scan_runs
    ADD CONSTRAINT runtime_scan_runs_pkey PRIMARY KEY (id);


--
-- TOC entry 3646 (class 2606 OID 21286)
-- Name: serverless_job_logs serverless_job_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.serverless_job_logs
    ADD CONSTRAINT serverless_job_logs_pkey PRIMARY KEY (id);


--
-- TOC entry 3648 (class 2606 OID 21301)
-- Name: serverless_job_results serverless_job_results_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.serverless_job_results
    ADD CONSTRAINT serverless_job_results_pkey PRIMARY KEY (job_id);


--
-- TOC entry 3643 (class 2606 OID 21258)
-- Name: serverless_jobs serverless_jobs_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.serverless_jobs
    ADD CONSTRAINT serverless_jobs_pkey PRIMARY KEY (id);


--
-- TOC entry 3590 (class 2606 OID 20973)
-- Name: servers servers_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.servers
    ADD CONSTRAINT servers_pkey PRIMARY KEY (id);


--
-- TOC entry 3592 (class 2606 OID 20975)
-- Name: servers servers_server_ip_key; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.servers
    ADD CONSTRAINT servers_server_ip_key UNIQUE (server_ip);


--
-- TOC entry 3619 (class 2606 OID 21134)
-- Name: services services_name_user_id_key; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.services
    ADD CONSTRAINT services_name_user_id_key UNIQUE (name, user_id);


--
-- TOC entry 3621 (class 2606 OID 21132)
-- Name: services services_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.services
    ADD CONSTRAINT services_pkey PRIMARY KEY (id);


--
-- TOC entry 3638 (class 2606 OID 21231)
-- Name: twofa_email_codes twofa_email_codes_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.twofa_email_codes
    ADD CONSTRAINT twofa_email_codes_pkey PRIMARY KEY (id);


--
-- TOC entry 3670 (class 2606 OID 21513)
-- Name: runtime_containers uq_runtime_container; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.runtime_containers
    ADD CONSTRAINT uq_runtime_container UNIQUE (server_id, container_id);


--
-- TOC entry 3586 (class 2606 OID 20944)
-- Name: user_applications user_applications_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.user_applications
    ADD CONSTRAINT user_applications_pkey PRIMARY KEY (id);


--
-- TOC entry 3588 (class 2606 OID 20946)
-- Name: user_applications user_applications_user_id_application_id_key; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.user_applications
    ADD CONSTRAINT user_applications_user_id_application_id_key UNIQUE (user_id, application_id);


--
-- TOC entry 3567 (class 2606 OID 20896)
-- Name: users users_email_key; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_email_key UNIQUE (email);


--
-- TOC entry 3610 (class 2606 OID 21058)
-- Name: users_logs users_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.users_logs
    ADD CONSTRAINT users_logs_pkey PRIMARY KEY (id);


--
-- TOC entry 3569 (class 2606 OID 20892)
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- TOC entry 3571 (class 2606 OID 20894)
-- Name: users users_username_key; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_username_key UNIQUE (username);


--
-- TOC entry 3576 (class 1259 OID 21177)
-- Name: idx_applications_url; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_applications_url ON public.applications USING btree (url);


--
-- TOC entry 3581 (class 1259 OID 21176)
-- Name: idx_auth_tokens_expires_at; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_auth_tokens_expires_at ON public.auth_tokens USING btree (expires_at);


--
-- TOC entry 3582 (class 1259 OID 21175)
-- Name: idx_auth_tokens_user_id; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_auth_tokens_user_id ON public.auth_tokens USING btree (user_id);


--
-- TOC entry 3604 (class 1259 OID 21186)
-- Name: idx_billing_activities_application_id; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_billing_activities_application_id ON public.billing_activities USING btree (application_id);


--
-- TOC entry 3605 (class 1259 OID 21187)
-- Name: idx_billing_activities_created_at; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_billing_activities_created_at ON public.billing_activities USING btree (created_at);


--
-- TOC entry 3606 (class 1259 OID 21185)
-- Name: idx_billing_activities_user_id; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_billing_activities_user_id ON public.billing_activities USING btree (user_id);


--
-- TOC entry 3663 (class 1259 OID 21401)
-- Name: idx_deploy_templates_type; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_deploy_templates_type ON public.deploy_templates USING btree (app_type);


--
-- TOC entry 3595 (class 1259 OID 21181)
-- Name: idx_deployments_application_id; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_deployments_application_id ON public.deployments USING btree (application_id);


--
-- TOC entry 3596 (class 1259 OID 21184)
-- Name: idx_deployments_backups_history; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_deployments_backups_history ON public.deployments USING gin (backups_history);


--
-- TOC entry 3597 (class 1259 OID 21182)
-- Name: idx_deployments_server_id; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_deployments_server_id ON public.deployments USING btree (server_id);


--
-- TOC entry 3598 (class 1259 OID 21183)
-- Name: idx_deployments_status; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_deployments_status ON public.deployments USING btree (status);


--
-- TOC entry 3599 (class 1259 OID 21180)
-- Name: idx_deployments_user_id; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_deployments_user_id ON public.deployments USING btree (user_id);


--
-- TOC entry 3622 (class 1259 OID 21172)
-- Name: idx_instances_server_id; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_instances_server_id ON public.instances USING btree (server_id);


--
-- TOC entry 3623 (class 1259 OID 21171)
-- Name: idx_instances_service_id; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_instances_service_id ON public.instances USING btree (service_id);


--
-- TOC entry 3624 (class 1259 OID 21173)
-- Name: idx_instances_status; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_instances_status ON public.instances USING btree (status);


--
-- TOC entry 3654 (class 1259 OID 21351)
-- Name: idx_mig_instances_server_id; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_mig_instances_server_id ON public.mig_instances USING btree (server_id);


--
-- TOC entry 3649 (class 1259 OID 21329)
-- Name: idx_mig_profiles_server_id; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_mig_profiles_server_id ON public.mig_profiles USING btree (server_id);


--
-- TOC entry 3629 (class 1259 OID 21216)
-- Name: idx_password_reset_tokens_expires_at; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_password_reset_tokens_expires_at ON public.password_reset_tokens USING btree (expires_at);


--
-- TOC entry 3630 (class 1259 OID 21215)
-- Name: idx_password_reset_tokens_user_id; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_password_reset_tokens_user_id ON public.password_reset_tokens USING btree (user_id);


--
-- TOC entry 3674 (class 1259 OID 21570)
-- Name: idx_runtime_anomalies_container; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_runtime_anomalies_container ON public.runtime_anomalies USING btree (container_pk, detected_at);


--
-- TOC entry 3675 (class 1259 OID 21571)
-- Name: idx_runtime_anomalies_status; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_runtime_anomalies_status ON public.runtime_anomalies USING btree (status);


--
-- TOC entry 3664 (class 1259 OID 21521)
-- Name: idx_runtime_containers_classification; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_runtime_containers_classification ON public.runtime_containers USING btree (classification);


--
-- TOC entry 3665 (class 1259 OID 21519)
-- Name: idx_runtime_containers_server; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_runtime_containers_server ON public.runtime_containers USING btree (server_id);


--
-- TOC entry 3666 (class 1259 OID 21520)
-- Name: idx_runtime_containers_state; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_runtime_containers_state ON public.runtime_containers USING btree (state);


--
-- TOC entry 3671 (class 1259 OID 21543)
-- Name: idx_runtime_observations_container; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_runtime_observations_container ON public.runtime_observations USING btree (container_pk, observed_at);


--
-- TOC entry 3678 (class 1259 OID 21590)
-- Name: idx_runtime_scan_runs_server; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_runtime_scan_runs_server ON public.runtime_scan_runs USING btree (server_id, started_at);


--
-- TOC entry 3644 (class 1259 OID 21292)
-- Name: idx_serverless_job_logs_job_id; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_serverless_job_logs_job_id ON public.serverless_job_logs USING btree (job_id, created_at);


--
-- TOC entry 3639 (class 1259 OID 21271)
-- Name: idx_serverless_jobs_pending; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_serverless_jobs_pending ON public.serverless_jobs USING btree (status, created_at) WHERE (status = 'pending'::text);


--
-- TOC entry 3640 (class 1259 OID 21269)
-- Name: idx_serverless_jobs_status; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_serverless_jobs_status ON public.serverless_jobs USING btree (status);


--
-- TOC entry 3641 (class 1259 OID 21270)
-- Name: idx_serverless_jobs_user_id; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_serverless_jobs_user_id ON public.serverless_jobs USING btree (user_id);


--
-- TOC entry 3617 (class 1259 OID 21170)
-- Name: idx_services_name; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_services_name ON public.services USING btree (name);


--
-- TOC entry 3635 (class 1259 OID 21238)
-- Name: idx_twofa_email_codes_expires_at; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_twofa_email_codes_expires_at ON public.twofa_email_codes USING btree (expires_at);


--
-- TOC entry 3636 (class 1259 OID 21237)
-- Name: idx_twofa_email_codes_user_id; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_twofa_email_codes_user_id ON public.twofa_email_codes USING btree (user_id);


--
-- TOC entry 3583 (class 1259 OID 21179)
-- Name: idx_user_applications_application_id; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_user_applications_application_id ON public.user_applications USING btree (application_id);


--
-- TOC entry 3584 (class 1259 OID 21178)
-- Name: idx_user_applications_user_id; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_user_applications_user_id ON public.user_applications USING btree (user_id);


--
-- TOC entry 3564 (class 1259 OID 21174)
-- Name: idx_users_email; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_users_email ON public.users USING btree (email);


--
-- TOC entry 3607 (class 1259 OID 21189)
-- Name: idx_users_logs_datetime; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_users_logs_datetime ON public.users_logs USING btree (datetime);


--
-- TOC entry 3608 (class 1259 OID 21188)
-- Name: idx_users_logs_user_id; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_users_logs_user_id ON public.users_logs USING btree (user_id);


--
-- TOC entry 3565 (class 1259 OID 21169)
-- Name: idx_users_username; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_users_username ON public.users USING btree (username);


--
-- TOC entry 3710 (class 2620 OID 21192)
-- Name: application_costs update_application_costs_updated_at; Type: TRIGGER; Schema: public; Owner: swautomorph
--

CREATE TRIGGER update_application_costs_updated_at BEFORE UPDATE ON public.application_costs FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- TOC entry 3709 (class 2620 OID 21191)
-- Name: deployments update_deployments_updated_at; Type: TRIGGER; Schema: public; Owner: swautomorph
--

CREATE TRIGGER update_deployments_updated_at BEFORE UPDATE ON public.deployments FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- TOC entry 3712 (class 2620 OID 21194)
-- Name: instances update_instances_updated_at; Type: TRIGGER; Schema: public; Owner: swautomorph
--

CREATE TRIGGER update_instances_updated_at BEFORE UPDATE ON public.instances FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- TOC entry 3711 (class 2620 OID 21193)
-- Name: services update_services_updated_at; Type: TRIGGER; Schema: public; Owner: swautomorph
--

CREATE TRIGGER update_services_updated_at BEFORE UPDATE ON public.services FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- TOC entry 3687 (class 2606 OID 21861)
-- Name: application_costs application_costs_application_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.application_costs
    ADD CONSTRAINT application_costs_application_id_fkey FOREIGN KEY (application_id) REFERENCES public.applications(id) ON DELETE CASCADE DEFERRABLE;


--
-- TOC entry 3681 (class 2606 OID 20926)
-- Name: auth_tokens auth_tokens_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.auth_tokens
    ADD CONSTRAINT auth_tokens_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- TOC entry 3688 (class 2606 OID 21866)
-- Name: billing_activities billing_activities_application_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.billing_activities
    ADD CONSTRAINT billing_activities_application_id_fkey FOREIGN KEY (application_id) REFERENCES public.applications(id) ON DELETE CASCADE DEFERRABLE;


--
-- TOC entry 3689 (class 2606 OID 21037)
-- Name: billing_activities billing_activities_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.billing_activities
    ADD CONSTRAINT billing_activities_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- TOC entry 3684 (class 2606 OID 21856)
-- Name: deployments deployments_application_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.deployments
    ADD CONSTRAINT deployments_application_id_fkey FOREIGN KEY (application_id) REFERENCES public.applications(id) ON DELETE SET NULL DEFERRABLE;


--
-- TOC entry 3685 (class 2606 OID 21003)
-- Name: deployments deployments_server_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.deployments
    ADD CONSTRAINT deployments_server_id_fkey FOREIGN KEY (server_id) REFERENCES public.servers(id) ON DELETE SET NULL;


--
-- TOC entry 3686 (class 2606 OID 20993)
-- Name: deployments deployments_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.deployments
    ADD CONSTRAINT deployments_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- TOC entry 3699 (class 2606 OID 21264)
-- Name: serverless_jobs fk_user; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.serverless_jobs
    ADD CONSTRAINT fk_user FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- TOC entry 3695 (class 2606 OID 21159)
-- Name: instances instances_server_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.instances
    ADD CONSTRAINT instances_server_id_fkey FOREIGN KEY (server_id) REFERENCES public.servers(id);


--
-- TOC entry 3696 (class 2606 OID 21164)
-- Name: instances instances_service_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.instances
    ADD CONSTRAINT instances_service_id_fkey FOREIGN KEY (service_id) REFERENCES public.services(id) ON DELETE CASCADE;


--
-- TOC entry 3692 (class 2606 OID 21101)
-- Name: invoicing invoicing_payment_mode_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.invoicing
    ADD CONSTRAINT invoicing_payment_mode_id_fkey FOREIGN KEY (payment_mode_id) REFERENCES public.payment_modes(id) ON DELETE SET NULL;


--
-- TOC entry 3693 (class 2606 OID 21096)
-- Name: invoicing invoicing_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.invoicing
    ADD CONSTRAINT invoicing_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- TOC entry 3704 (class 2606 OID 21346)
-- Name: mig_instances mig_instances_server_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.mig_instances
    ADD CONSTRAINT mig_instances_server_id_fkey FOREIGN KEY (server_id) REFERENCES public.servers(id) ON DELETE CASCADE;


--
-- TOC entry 3703 (class 2606 OID 21324)
-- Name: mig_profiles mig_profiles_server_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.mig_profiles
    ADD CONSTRAINT mig_profiles_server_id_fkey FOREIGN KEY (server_id) REFERENCES public.servers(id) ON DELETE CASCADE;


--
-- TOC entry 3697 (class 2606 OID 21210)
-- Name: password_reset_tokens password_reset_tokens_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.password_reset_tokens
    ADD CONSTRAINT password_reset_tokens_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- TOC entry 3691 (class 2606 OID 21078)
-- Name: payment_modes payment_modes_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.payment_modes
    ADD CONSTRAINT payment_modes_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- TOC entry 3707 (class 2606 OID 21565)
-- Name: runtime_anomalies runtime_anomalies_container_pk_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.runtime_anomalies
    ADD CONSTRAINT runtime_anomalies_container_pk_fkey FOREIGN KEY (container_pk) REFERENCES public.runtime_containers(id) ON DELETE CASCADE;


--
-- TOC entry 3705 (class 2606 OID 21514)
-- Name: runtime_containers runtime_containers_server_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.runtime_containers
    ADD CONSTRAINT runtime_containers_server_id_fkey FOREIGN KEY (server_id) REFERENCES public.servers(id) ON DELETE CASCADE;


--
-- TOC entry 3706 (class 2606 OID 21538)
-- Name: runtime_observations runtime_observations_container_pk_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.runtime_observations
    ADD CONSTRAINT runtime_observations_container_pk_fkey FOREIGN KEY (container_pk) REFERENCES public.runtime_containers(id) ON DELETE CASCADE;


--
-- TOC entry 3708 (class 2606 OID 21585)
-- Name: runtime_scan_runs runtime_scan_runs_server_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.runtime_scan_runs
    ADD CONSTRAINT runtime_scan_runs_server_id_fkey FOREIGN KEY (server_id) REFERENCES public.servers(id) ON DELETE SET NULL;


--
-- TOC entry 3701 (class 2606 OID 21287)
-- Name: serverless_job_logs serverless_job_logs_job_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.serverless_job_logs
    ADD CONSTRAINT serverless_job_logs_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.serverless_jobs(id) ON DELETE CASCADE;


--
-- TOC entry 3702 (class 2606 OID 21302)
-- Name: serverless_job_results serverless_job_results_job_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.serverless_job_results
    ADD CONSTRAINT serverless_job_results_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.serverless_jobs(id) ON DELETE CASCADE;


--
-- TOC entry 3700 (class 2606 OID 21259)
-- Name: serverless_jobs serverless_jobs_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.serverless_jobs
    ADD CONSTRAINT serverless_jobs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- TOC entry 3694 (class 2606 OID 21135)
-- Name: services services_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.services
    ADD CONSTRAINT services_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- TOC entry 3698 (class 2606 OID 21232)
-- Name: twofa_email_codes twofa_email_codes_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.twofa_email_codes
    ADD CONSTRAINT twofa_email_codes_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- TOC entry 3682 (class 2606 OID 21851)
-- Name: user_applications user_applications_application_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.user_applications
    ADD CONSTRAINT user_applications_application_id_fkey FOREIGN KEY (application_id) REFERENCES public.applications(id) ON DELETE CASCADE DEFERRABLE;


--
-- TOC entry 3683 (class 2606 OID 20947)
-- Name: user_applications user_applications_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.user_applications
    ADD CONSTRAINT user_applications_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- TOC entry 3690 (class 2606 OID 21059)
-- Name: users_logs users_logs_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.users_logs
    ADD CONSTRAINT users_logs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


-- Completed on 2026-10-14 21:05:47 UTC

--
-- PostgreSQL database dump complete
--

\unrestrict H3XQwYOvwGsOWCzHa78RJD7eThgfJ89KfQ5fBJ06iW4RMkenHmUf1AY69OO4V7g

