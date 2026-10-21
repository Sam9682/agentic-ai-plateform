--
-- PostgreSQL database dump
--

\restrict NeH0g0FdtuVFarh9se4JrMvRDOdlNtnJ9j4OXM6WNNwnRfSXAAtQf7gfe1XblsZ

-- Dumped from database version 18.6 (Ubuntu 18.6-0ubuntu0.26.04.1)
-- Dumped by pg_dump version 18.6 (Ubuntu 18.6-0ubuntu0.26.04.1)

-- Started on 2026-10-05 20:12:52 UTC

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
-- TOC entry 2 (class 3079 OID 18049)
-- Name: uuid-ossp; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA public;


--
-- TOC entry 3800 (class 0 OID 0)
-- Dependencies: 2
-- Name: EXTENSION "uuid-ossp"; Type: COMMENT; Schema: -; Owner: 
--

COMMENT ON EXTENSION "uuid-ossp" IS 'generate universally unique identifiers (UUIDs)';


--
-- TOC entry 272 (class 1255 OID 18372)
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
-- TOC entry 233 (class 1259 OID 18191)
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
-- TOC entry 232 (class 1259 OID 18190)
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
-- TOC entry 3801 (class 0 OID 0)
-- Dependencies: 232
-- Name: application_costs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.application_costs_id_seq OWNED BY public.application_costs.id;


--
-- TOC entry 223 (class 1259 OID 18080)
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
-- TOC entry 222 (class 1259 OID 18079)
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
-- TOC entry 3802 (class 0 OID 0)
-- Dependencies: 222
-- Name: applications_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.applications_id_seq OWNED BY public.applications.id;


--
-- TOC entry 225 (class 1259 OID 18095)
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
-- TOC entry 224 (class 1259 OID 18094)
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
-- TOC entry 3803 (class 0 OID 0)
-- Dependencies: 224
-- Name: auth_tokens_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.auth_tokens_id_seq OWNED BY public.auth_tokens.id;


--
-- TOC entry 235 (class 1259 OID 18208)
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
-- TOC entry 234 (class 1259 OID 18207)
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
-- TOC entry 3804 (class 0 OID 0)
-- Dependencies: 234
-- Name: billing_activities_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.billing_activities_id_seq OWNED BY public.billing_activities.id;


--
-- TOC entry 243 (class 1259 OID 18289)
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
-- TOC entry 242 (class 1259 OID 18288)
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
-- TOC entry 3805 (class 0 OID 0)
-- Dependencies: 242
-- Name: configuration_param_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.configuration_param_id_seq OWNED BY public.configuration.param_id;


--
-- TOC entry 261 (class 1259 OID 18555)
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
-- TOC entry 260 (class 1259 OID 18554)
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
-- TOC entry 3806 (class 0 OID 0)
-- Dependencies: 260
-- Name: deploy_templates_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.deploy_templates_id_seq OWNED BY public.deploy_templates.id;


--
-- TOC entry 231 (class 1259 OID 18159)
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
-- TOC entry 3807 (class 0 OID 0)
-- Dependencies: 231
-- Name: COLUMN deployments.modification_history; Type: COMMENT; Schema: public; Owner: swautomorph
--

COMMENT ON COLUMN public.deployments.modification_history IS 'JSON array containing modification history with branch names and Gitea URLs';


--
-- TOC entry 3808 (class 0 OID 0)
-- Dependencies: 231
-- Name: COLUMN deployments.backups_history; Type: COMMENT; Schema: public; Owner: swautomorph
--

COMMENT ON COLUMN public.deployments.backups_history IS 'JSON array containing backup history with links to PostgreSQL database backups in S3';


--
-- TOC entry 230 (class 1259 OID 18158)
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
-- TOC entry 3809 (class 0 OID 0)
-- Dependencies: 230
-- Name: deployments_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.deployments_id_seq OWNED BY public.deployments.id;


--
-- TOC entry 247 (class 1259 OID 18323)
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
-- TOC entry 246 (class 1259 OID 18322)
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
-- TOC entry 3810 (class 0 OID 0)
-- Dependencies: 246
-- Name: instances_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.instances_id_seq OWNED BY public.instances.id;


--
-- TOC entry 241 (class 1259 OID 18266)
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
-- TOC entry 240 (class 1259 OID 18265)
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
-- TOC entry 3811 (class 0 OID 0)
-- Dependencies: 240
-- Name: invoicing_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.invoicing_id_seq OWNED BY public.invoicing.id;


--
-- TOC entry 259 (class 1259 OID 18513)
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
-- TOC entry 258 (class 1259 OID 18512)
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
-- TOC entry 3812 (class 0 OID 0)
-- Dependencies: 258
-- Name: mig_instances_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.mig_instances_id_seq OWNED BY public.mig_instances.id;


--
-- TOC entry 257 (class 1259 OID 18491)
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
-- TOC entry 256 (class 1259 OID 18490)
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
-- TOC entry 3813 (class 0 OID 0)
-- Dependencies: 256
-- Name: mig_profiles_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.mig_profiles_id_seq OWNED BY public.mig_profiles.id;


--
-- TOC entry 249 (class 1259 OID 18378)
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
-- TOC entry 248 (class 1259 OID 18377)
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
-- TOC entry 3814 (class 0 OID 0)
-- Dependencies: 248
-- Name: password_reset_tokens_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.password_reset_tokens_id_seq OWNED BY public.password_reset_tokens.id;


--
-- TOC entry 239 (class 1259 OID 18247)
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
-- TOC entry 238 (class 1259 OID 18246)
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
-- TOC entry 3815 (class 0 OID 0)
-- Dependencies: 238
-- Name: payment_modes_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.payment_modes_id_seq OWNED BY public.payment_modes.id;


--
-- TOC entry 254 (class 1259 OID 18455)
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
-- TOC entry 253 (class 1259 OID 18454)
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
-- TOC entry 3816 (class 0 OID 0)
-- Dependencies: 253
-- Name: serverless_job_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.serverless_job_logs_id_seq OWNED BY public.serverless_job_logs.id;


--
-- TOC entry 255 (class 1259 OID 18475)
-- Name: serverless_job_results; Type: TABLE; Schema: public; Owner: swautomorph
--

CREATE TABLE public.serverless_job_results (
    job_id uuid NOT NULL,
    result jsonb,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.serverless_job_results OWNER TO swautomorph;

--
-- TOC entry 252 (class 1259 OID 18421)
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
-- TOC entry 3817 (class 0 OID 0)
-- Dependencies: 252
-- Name: COLUMN serverless_jobs.target_link; Type: COMMENT; Schema: public; Owner: swautomorph
--

COMMENT ON COLUMN public.serverless_jobs.target_link IS 'The agentic-ai-plateform-serverless-brik endpoint URL selected for job execution';


--
-- TOC entry 229 (class 1259 OID 18140)
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
-- TOC entry 228 (class 1259 OID 18139)
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
-- TOC entry 3818 (class 0 OID 0)
-- Dependencies: 228
-- Name: servers_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.servers_id_seq OWNED BY public.servers.id;


--
-- TOC entry 245 (class 1259 OID 18299)
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
-- TOC entry 244 (class 1259 OID 18298)
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
-- TOC entry 3819 (class 0 OID 0)
-- Dependencies: 244
-- Name: services_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.services_id_seq OWNED BY public.services.id;


--
-- TOC entry 251 (class 1259 OID 18402)
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
-- TOC entry 250 (class 1259 OID 18401)
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
-- TOC entry 3820 (class 0 OID 0)
-- Dependencies: 250
-- Name: twofa_email_codes_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.twofa_email_codes_id_seq OWNED BY public.twofa_email_codes.id;


--
-- TOC entry 227 (class 1259 OID 18114)
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
-- TOC entry 3821 (class 0 OID 0)
-- Dependencies: 227
-- Name: COLUMN user_applications.http_port3; Type: COMMENT; Schema: public; Owner: swautomorph
--

COMMENT ON COLUMN public.user_applications.http_port3 IS 'Third HTTP port allocated to the application';


--
-- TOC entry 3822 (class 0 OID 0)
-- Dependencies: 227
-- Name: COLUMN user_applications.https_port3; Type: COMMENT; Schema: public; Owner: swautomorph
--

COMMENT ON COLUMN public.user_applications.https_port3 IS 'Third HTTPS port allocated to the application';


--
-- TOC entry 3823 (class 0 OID 0)
-- Dependencies: 227
-- Name: COLUMN user_applications.http_port4; Type: COMMENT; Schema: public; Owner: swautomorph
--

COMMENT ON COLUMN public.user_applications.http_port4 IS 'Fourth HTTP port allocated to the application';


--
-- TOC entry 3824 (class 0 OID 0)
-- Dependencies: 227
-- Name: COLUMN user_applications.https_port4; Type: COMMENT; Schema: public; Owner: swautomorph
--

COMMENT ON COLUMN public.user_applications.https_port4 IS 'Fourth HTTPS port allocated to the application';


--
-- TOC entry 3825 (class 0 OID 0)
-- Dependencies: 227
-- Name: COLUMN user_applications.http_port5; Type: COMMENT; Schema: public; Owner: swautomorph
--

COMMENT ON COLUMN public.user_applications.http_port5 IS 'Fifth HTTP port allocated to the application';


--
-- TOC entry 3826 (class 0 OID 0)
-- Dependencies: 227
-- Name: COLUMN user_applications.https_port5; Type: COMMENT; Schema: public; Owner: swautomorph
--

COMMENT ON COLUMN public.user_applications.https_port5 IS 'Fifth HTTPS port allocated to the application';


--
-- TOC entry 3827 (class 0 OID 0)
-- Dependencies: 227
-- Name: COLUMN user_applications.http_port6; Type: COMMENT; Schema: public; Owner: swautomorph
--

COMMENT ON COLUMN public.user_applications.http_port6 IS 'Sixth HTTP port allocated to the application';


--
-- TOC entry 3828 (class 0 OID 0)
-- Dependencies: 227
-- Name: COLUMN user_applications.https_port6; Type: COMMENT; Schema: public; Owner: swautomorph
--

COMMENT ON COLUMN public.user_applications.https_port6 IS 'Sixth HTTPS port allocated to the application';


--
-- TOC entry 226 (class 1259 OID 18113)
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
-- TOC entry 3829 (class 0 OID 0)
-- Dependencies: 226
-- Name: user_applications_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.user_applications_id_seq OWNED BY public.user_applications.id;


--
-- TOC entry 221 (class 1259 OID 18061)
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
-- TOC entry 220 (class 1259 OID 18060)
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
-- TOC entry 3830 (class 0 OID 0)
-- Dependencies: 220
-- Name: users_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;


--
-- TOC entry 237 (class 1259 OID 18230)
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
-- TOC entry 236 (class 1259 OID 18229)
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
-- TOC entry 3831 (class 0 OID 0)
-- Dependencies: 236
-- Name: users_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: swautomorph
--

ALTER SEQUENCE public.users_logs_id_seq OWNED BY public.users_logs.id;


--
-- TOC entry 3464 (class 2604 OID 18194)
-- Name: application_costs id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.application_costs ALTER COLUMN id SET DEFAULT nextval('public.application_costs_id_seq'::regclass);


--
-- TOC entry 3446 (class 2604 OID 18083)
-- Name: applications id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.applications ALTER COLUMN id SET DEFAULT nextval('public.applications_id_seq'::regclass);


--
-- TOC entry 3449 (class 2604 OID 18098)
-- Name: auth_tokens id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.auth_tokens ALTER COLUMN id SET DEFAULT nextval('public.auth_tokens_id_seq'::regclass);


--
-- TOC entry 3468 (class 2604 OID 18211)
-- Name: billing_activities id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.billing_activities ALTER COLUMN id SET DEFAULT nextval('public.billing_activities_id_seq'::regclass);


--
-- TOC entry 3478 (class 2604 OID 18292)
-- Name: configuration param_id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.configuration ALTER COLUMN param_id SET DEFAULT nextval('public.configuration_param_id_seq'::regclass);


--
-- TOC entry 3507 (class 2604 OID 18558)
-- Name: deploy_templates id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.deploy_templates ALTER COLUMN id SET DEFAULT nextval('public.deploy_templates_id_seq'::regclass);


--
-- TOC entry 3457 (class 2604 OID 18162)
-- Name: deployments id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.deployments ALTER COLUMN id SET DEFAULT nextval('public.deployments_id_seq'::regclass);


--
-- TOC entry 3484 (class 2604 OID 18326)
-- Name: instances id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.instances ALTER COLUMN id SET DEFAULT nextval('public.instances_id_seq'::regclass);


--
-- TOC entry 3475 (class 2604 OID 18269)
-- Name: invoicing id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.invoicing ALTER COLUMN id SET DEFAULT nextval('public.invoicing_id_seq'::regclass);


--
-- TOC entry 3505 (class 2604 OID 18516)
-- Name: mig_instances id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.mig_instances ALTER COLUMN id SET DEFAULT nextval('public.mig_instances_id_seq'::regclass);


--
-- TOC entry 3503 (class 2604 OID 18494)
-- Name: mig_profiles id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.mig_profiles ALTER COLUMN id SET DEFAULT nextval('public.mig_profiles_id_seq'::regclass);


--
-- TOC entry 3489 (class 2604 OID 18381)
-- Name: password_reset_tokens id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.password_reset_tokens ALTER COLUMN id SET DEFAULT nextval('public.password_reset_tokens_id_seq'::regclass);


--
-- TOC entry 3472 (class 2604 OID 18250)
-- Name: payment_modes id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.payment_modes ALTER COLUMN id SET DEFAULT nextval('public.payment_modes_id_seq'::regclass);


--
-- TOC entry 3500 (class 2604 OID 18458)
-- Name: serverless_job_logs id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.serverless_job_logs ALTER COLUMN id SET DEFAULT nextval('public.serverless_job_logs_id_seq'::regclass);


--
-- TOC entry 3453 (class 2604 OID 18143)
-- Name: servers id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.servers ALTER COLUMN id SET DEFAULT nextval('public.servers_id_seq'::regclass);


--
-- TOC entry 3479 (class 2604 OID 18302)
-- Name: services id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.services ALTER COLUMN id SET DEFAULT nextval('public.services_id_seq'::regclass);


--
-- TOC entry 3492 (class 2604 OID 18405)
-- Name: twofa_email_codes id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.twofa_email_codes ALTER COLUMN id SET DEFAULT nextval('public.twofa_email_codes_id_seq'::regclass);


--
-- TOC entry 3451 (class 2604 OID 18117)
-- Name: user_applications id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.user_applications ALTER COLUMN id SET DEFAULT nextval('public.user_applications_id_seq'::regclass);


--
-- TOC entry 3441 (class 2604 OID 18064)
-- Name: users id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);


--
-- TOC entry 3470 (class 2604 OID 18233)
-- Name: users_logs id; Type: DEFAULT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.users_logs ALTER COLUMN id SET DEFAULT nextval('public.users_logs_id_seq'::regclass);


--
-- TOC entry 3557 (class 2606 OID 18201)
-- Name: application_costs application_costs_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.application_costs
    ADD CONSTRAINT application_costs_pkey PRIMARY KEY (id);


--
-- TOC entry 3529 (class 2606 OID 18093)
-- Name: applications applications_name_key; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.applications
    ADD CONSTRAINT applications_name_key UNIQUE (name);


--
-- TOC entry 3531 (class 2606 OID 18091)
-- Name: applications applications_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.applications
    ADD CONSTRAINT applications_pkey PRIMARY KEY (id);


--
-- TOC entry 3534 (class 2606 OID 18105)
-- Name: auth_tokens auth_tokens_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.auth_tokens
    ADD CONSTRAINT auth_tokens_pkey PRIMARY KEY (id);


--
-- TOC entry 3536 (class 2606 OID 18107)
-- Name: auth_tokens auth_tokens_token_hash_key; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.auth_tokens
    ADD CONSTRAINT auth_tokens_token_hash_key UNIQUE (token_hash);


--
-- TOC entry 3559 (class 2606 OID 18218)
-- Name: billing_activities billing_activities_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.billing_activities
    ADD CONSTRAINT billing_activities_pkey PRIMARY KEY (id);


--
-- TOC entry 3572 (class 2606 OID 18297)
-- Name: configuration configuration_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.configuration
    ADD CONSTRAINT configuration_pkey PRIMARY KEY (param_id);


--
-- TOC entry 3616 (class 2606 OID 18580)
-- Name: deploy_templates deploy_templates_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.deploy_templates
    ADD CONSTRAINT deploy_templates_pkey PRIMARY KEY (id);


--
-- TOC entry 3618 (class 2606 OID 18582)
-- Name: deploy_templates deploy_templates_template_id_key; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.deploy_templates
    ADD CONSTRAINT deploy_templates_template_id_key UNIQUE (template_id);


--
-- TOC entry 3550 (class 2606 OID 18174)
-- Name: deployments deployments_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.deployments
    ADD CONSTRAINT deployments_pkey PRIMARY KEY (id);


--
-- TOC entry 3582 (class 2606 OID 18338)
-- Name: instances instances_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.instances
    ADD CONSTRAINT instances_pkey PRIMARY KEY (id);


--
-- TOC entry 3584 (class 2606 OID 18340)
-- Name: instances instances_service_id_instance_id_key; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.instances
    ADD CONSTRAINT instances_service_id_instance_id_key UNIQUE (service_id, instance_id);


--
-- TOC entry 3570 (class 2606 OID 18277)
-- Name: invoicing invoicing_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.invoicing
    ADD CONSTRAINT invoicing_pkey PRIMARY KEY (id);


--
-- TOC entry 3612 (class 2606 OID 18525)
-- Name: mig_instances mig_instances_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.mig_instances
    ADD CONSTRAINT mig_instances_pkey PRIMARY KEY (id);


--
-- TOC entry 3614 (class 2606 OID 18527)
-- Name: mig_instances mig_instances_server_id_instance_uuid_key; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.mig_instances
    ADD CONSTRAINT mig_instances_server_id_instance_uuid_key UNIQUE (server_id, instance_uuid);


--
-- TOC entry 3607 (class 2606 OID 18503)
-- Name: mig_profiles mig_profiles_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.mig_profiles
    ADD CONSTRAINT mig_profiles_pkey PRIMARY KEY (id);


--
-- TOC entry 3609 (class 2606 OID 18505)
-- Name: mig_profiles mig_profiles_server_id_profile_name_key; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.mig_profiles
    ADD CONSTRAINT mig_profiles_server_id_profile_name_key UNIQUE (server_id, profile_name);


--
-- TOC entry 3588 (class 2606 OID 18389)
-- Name: password_reset_tokens password_reset_tokens_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.password_reset_tokens
    ADD CONSTRAINT password_reset_tokens_pkey PRIMARY KEY (id);


--
-- TOC entry 3590 (class 2606 OID 18391)
-- Name: password_reset_tokens password_reset_tokens_token_hash_key; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.password_reset_tokens
    ADD CONSTRAINT password_reset_tokens_token_hash_key UNIQUE (token_hash);


--
-- TOC entry 3568 (class 2606 OID 18259)
-- Name: payment_modes payment_modes_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.payment_modes
    ADD CONSTRAINT payment_modes_pkey PRIMARY KEY (id);


--
-- TOC entry 3602 (class 2606 OID 18468)
-- Name: serverless_job_logs serverless_job_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.serverless_job_logs
    ADD CONSTRAINT serverless_job_logs_pkey PRIMARY KEY (id);


--
-- TOC entry 3604 (class 2606 OID 18483)
-- Name: serverless_job_results serverless_job_results_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.serverless_job_results
    ADD CONSTRAINT serverless_job_results_pkey PRIMARY KEY (job_id);


--
-- TOC entry 3599 (class 2606 OID 18440)
-- Name: serverless_jobs serverless_jobs_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.serverless_jobs
    ADD CONSTRAINT serverless_jobs_pkey PRIMARY KEY (id);


--
-- TOC entry 3546 (class 2606 OID 18155)
-- Name: servers servers_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.servers
    ADD CONSTRAINT servers_pkey PRIMARY KEY (id);


--
-- TOC entry 3548 (class 2606 OID 18157)
-- Name: servers servers_server_ip_key; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.servers
    ADD CONSTRAINT servers_server_ip_key UNIQUE (server_ip);


--
-- TOC entry 3575 (class 2606 OID 18316)
-- Name: services services_name_user_id_key; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.services
    ADD CONSTRAINT services_name_user_id_key UNIQUE (name, user_id);


--
-- TOC entry 3577 (class 2606 OID 18314)
-- Name: services services_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.services
    ADD CONSTRAINT services_pkey PRIMARY KEY (id);


--
-- TOC entry 3594 (class 2606 OID 18413)
-- Name: twofa_email_codes twofa_email_codes_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.twofa_email_codes
    ADD CONSTRAINT twofa_email_codes_pkey PRIMARY KEY (id);


--
-- TOC entry 3542 (class 2606 OID 18126)
-- Name: user_applications user_applications_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.user_applications
    ADD CONSTRAINT user_applications_pkey PRIMARY KEY (id);


--
-- TOC entry 3544 (class 2606 OID 18128)
-- Name: user_applications user_applications_user_id_application_id_key; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.user_applications
    ADD CONSTRAINT user_applications_user_id_application_id_key UNIQUE (user_id, application_id);


--
-- TOC entry 3523 (class 2606 OID 18078)
-- Name: users users_email_key; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_email_key UNIQUE (email);


--
-- TOC entry 3566 (class 2606 OID 18240)
-- Name: users_logs users_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.users_logs
    ADD CONSTRAINT users_logs_pkey PRIMARY KEY (id);


--
-- TOC entry 3525 (class 2606 OID 18074)
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- TOC entry 3527 (class 2606 OID 18076)
-- Name: users users_username_key; Type: CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_username_key UNIQUE (username);


--
-- TOC entry 3532 (class 1259 OID 18359)
-- Name: idx_applications_url; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_applications_url ON public.applications USING btree (url);


--
-- TOC entry 3537 (class 1259 OID 18358)
-- Name: idx_auth_tokens_expires_at; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_auth_tokens_expires_at ON public.auth_tokens USING btree (expires_at);


--
-- TOC entry 3538 (class 1259 OID 18357)
-- Name: idx_auth_tokens_user_id; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_auth_tokens_user_id ON public.auth_tokens USING btree (user_id);


--
-- TOC entry 3560 (class 1259 OID 18368)
-- Name: idx_billing_activities_application_id; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_billing_activities_application_id ON public.billing_activities USING btree (application_id);


--
-- TOC entry 3561 (class 1259 OID 18369)
-- Name: idx_billing_activities_created_at; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_billing_activities_created_at ON public.billing_activities USING btree (created_at);


--
-- TOC entry 3562 (class 1259 OID 18367)
-- Name: idx_billing_activities_user_id; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_billing_activities_user_id ON public.billing_activities USING btree (user_id);


--
-- TOC entry 3619 (class 1259 OID 18583)
-- Name: idx_deploy_templates_type; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_deploy_templates_type ON public.deploy_templates USING btree (app_type);


--
-- TOC entry 3551 (class 1259 OID 18363)
-- Name: idx_deployments_application_id; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_deployments_application_id ON public.deployments USING btree (application_id);


--
-- TOC entry 3552 (class 1259 OID 18366)
-- Name: idx_deployments_backups_history; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_deployments_backups_history ON public.deployments USING gin (backups_history);


--
-- TOC entry 3553 (class 1259 OID 18364)
-- Name: idx_deployments_server_id; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_deployments_server_id ON public.deployments USING btree (server_id);


--
-- TOC entry 3554 (class 1259 OID 18365)
-- Name: idx_deployments_status; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_deployments_status ON public.deployments USING btree (status);


--
-- TOC entry 3555 (class 1259 OID 18362)
-- Name: idx_deployments_user_id; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_deployments_user_id ON public.deployments USING btree (user_id);


--
-- TOC entry 3578 (class 1259 OID 18354)
-- Name: idx_instances_server_id; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_instances_server_id ON public.instances USING btree (server_id);


--
-- TOC entry 3579 (class 1259 OID 18353)
-- Name: idx_instances_service_id; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_instances_service_id ON public.instances USING btree (service_id);


--
-- TOC entry 3580 (class 1259 OID 18355)
-- Name: idx_instances_status; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_instances_status ON public.instances USING btree (status);


--
-- TOC entry 3610 (class 1259 OID 18533)
-- Name: idx_mig_instances_server_id; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_mig_instances_server_id ON public.mig_instances USING btree (server_id);


--
-- TOC entry 3605 (class 1259 OID 18511)
-- Name: idx_mig_profiles_server_id; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_mig_profiles_server_id ON public.mig_profiles USING btree (server_id);


--
-- TOC entry 3585 (class 1259 OID 18398)
-- Name: idx_password_reset_tokens_expires_at; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_password_reset_tokens_expires_at ON public.password_reset_tokens USING btree (expires_at);


--
-- TOC entry 3586 (class 1259 OID 18397)
-- Name: idx_password_reset_tokens_user_id; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_password_reset_tokens_user_id ON public.password_reset_tokens USING btree (user_id);


--
-- TOC entry 3600 (class 1259 OID 18474)
-- Name: idx_serverless_job_logs_job_id; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_serverless_job_logs_job_id ON public.serverless_job_logs USING btree (job_id, created_at);


--
-- TOC entry 3595 (class 1259 OID 18453)
-- Name: idx_serverless_jobs_pending; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_serverless_jobs_pending ON public.serverless_jobs USING btree (status, created_at) WHERE (status = 'pending'::text);


--
-- TOC entry 3596 (class 1259 OID 18451)
-- Name: idx_serverless_jobs_status; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_serverless_jobs_status ON public.serverless_jobs USING btree (status);


--
-- TOC entry 3597 (class 1259 OID 18452)
-- Name: idx_serverless_jobs_user_id; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_serverless_jobs_user_id ON public.serverless_jobs USING btree (user_id);


--
-- TOC entry 3573 (class 1259 OID 18352)
-- Name: idx_services_name; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_services_name ON public.services USING btree (name);


--
-- TOC entry 3591 (class 1259 OID 18420)
-- Name: idx_twofa_email_codes_expires_at; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_twofa_email_codes_expires_at ON public.twofa_email_codes USING btree (expires_at);


--
-- TOC entry 3592 (class 1259 OID 18419)
-- Name: idx_twofa_email_codes_user_id; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_twofa_email_codes_user_id ON public.twofa_email_codes USING btree (user_id);


--
-- TOC entry 3539 (class 1259 OID 18361)
-- Name: idx_user_applications_application_id; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_user_applications_application_id ON public.user_applications USING btree (application_id);


--
-- TOC entry 3540 (class 1259 OID 18360)
-- Name: idx_user_applications_user_id; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_user_applications_user_id ON public.user_applications USING btree (user_id);


--
-- TOC entry 3520 (class 1259 OID 18356)
-- Name: idx_users_email; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_users_email ON public.users USING btree (email);


--
-- TOC entry 3563 (class 1259 OID 18371)
-- Name: idx_users_logs_datetime; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_users_logs_datetime ON public.users_logs USING btree (datetime);


--
-- TOC entry 3564 (class 1259 OID 18370)
-- Name: idx_users_logs_user_id; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_users_logs_user_id ON public.users_logs USING btree (user_id);


--
-- TOC entry 3521 (class 1259 OID 18351)
-- Name: idx_users_username; Type: INDEX; Schema: public; Owner: swautomorph
--

CREATE INDEX idx_users_username ON public.users USING btree (username);


--
-- TOC entry 3645 (class 2620 OID 18374)
-- Name: application_costs update_application_costs_updated_at; Type: TRIGGER; Schema: public; Owner: swautomorph
--

CREATE TRIGGER update_application_costs_updated_at BEFORE UPDATE ON public.application_costs FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- TOC entry 3644 (class 2620 OID 18373)
-- Name: deployments update_deployments_updated_at; Type: TRIGGER; Schema: public; Owner: swautomorph
--

CREATE TRIGGER update_deployments_updated_at BEFORE UPDATE ON public.deployments FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- TOC entry 3647 (class 2620 OID 18376)
-- Name: instances update_instances_updated_at; Type: TRIGGER; Schema: public; Owner: swautomorph
--

CREATE TRIGGER update_instances_updated_at BEFORE UPDATE ON public.instances FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- TOC entry 3646 (class 2620 OID 18375)
-- Name: services update_services_updated_at; Type: TRIGGER; Schema: public; Owner: swautomorph
--

CREATE TRIGGER update_services_updated_at BEFORE UPDATE ON public.services FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- TOC entry 3626 (class 2606 OID 19117)
-- Name: application_costs application_costs_application_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.application_costs
    ADD CONSTRAINT application_costs_application_id_fkey FOREIGN KEY (application_id) REFERENCES public.applications(id) ON DELETE CASCADE DEFERRABLE;


--
-- TOC entry 3620 (class 2606 OID 18108)
-- Name: auth_tokens auth_tokens_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.auth_tokens
    ADD CONSTRAINT auth_tokens_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- TOC entry 3627 (class 2606 OID 19122)
-- Name: billing_activities billing_activities_application_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.billing_activities
    ADD CONSTRAINT billing_activities_application_id_fkey FOREIGN KEY (application_id) REFERENCES public.applications(id) ON DELETE CASCADE DEFERRABLE;


--
-- TOC entry 3628 (class 2606 OID 18219)
-- Name: billing_activities billing_activities_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.billing_activities
    ADD CONSTRAINT billing_activities_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- TOC entry 3623 (class 2606 OID 19112)
-- Name: deployments deployments_application_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.deployments
    ADD CONSTRAINT deployments_application_id_fkey FOREIGN KEY (application_id) REFERENCES public.applications(id) ON DELETE SET NULL DEFERRABLE;


--
-- TOC entry 3624 (class 2606 OID 18185)
-- Name: deployments deployments_server_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.deployments
    ADD CONSTRAINT deployments_server_id_fkey FOREIGN KEY (server_id) REFERENCES public.servers(id) ON DELETE SET NULL;


--
-- TOC entry 3625 (class 2606 OID 18175)
-- Name: deployments deployments_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.deployments
    ADD CONSTRAINT deployments_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- TOC entry 3638 (class 2606 OID 18446)
-- Name: serverless_jobs fk_user; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.serverless_jobs
    ADD CONSTRAINT fk_user FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- TOC entry 3634 (class 2606 OID 18341)
-- Name: instances instances_server_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.instances
    ADD CONSTRAINT instances_server_id_fkey FOREIGN KEY (server_id) REFERENCES public.servers(id);


--
-- TOC entry 3635 (class 2606 OID 18346)
-- Name: instances instances_service_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.instances
    ADD CONSTRAINT instances_service_id_fkey FOREIGN KEY (service_id) REFERENCES public.services(id) ON DELETE CASCADE;


--
-- TOC entry 3631 (class 2606 OID 18283)
-- Name: invoicing invoicing_payment_mode_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.invoicing
    ADD CONSTRAINT invoicing_payment_mode_id_fkey FOREIGN KEY (payment_mode_id) REFERENCES public.payment_modes(id) ON DELETE SET NULL;


--
-- TOC entry 3632 (class 2606 OID 18278)
-- Name: invoicing invoicing_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.invoicing
    ADD CONSTRAINT invoicing_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- TOC entry 3643 (class 2606 OID 18528)
-- Name: mig_instances mig_instances_server_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.mig_instances
    ADD CONSTRAINT mig_instances_server_id_fkey FOREIGN KEY (server_id) REFERENCES public.servers(id) ON DELETE CASCADE;


--
-- TOC entry 3642 (class 2606 OID 18506)
-- Name: mig_profiles mig_profiles_server_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.mig_profiles
    ADD CONSTRAINT mig_profiles_server_id_fkey FOREIGN KEY (server_id) REFERENCES public.servers(id) ON DELETE CASCADE;


--
-- TOC entry 3636 (class 2606 OID 18392)
-- Name: password_reset_tokens password_reset_tokens_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.password_reset_tokens
    ADD CONSTRAINT password_reset_tokens_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- TOC entry 3630 (class 2606 OID 18260)
-- Name: payment_modes payment_modes_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.payment_modes
    ADD CONSTRAINT payment_modes_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- TOC entry 3640 (class 2606 OID 18469)
-- Name: serverless_job_logs serverless_job_logs_job_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.serverless_job_logs
    ADD CONSTRAINT serverless_job_logs_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.serverless_jobs(id) ON DELETE CASCADE;


--
-- TOC entry 3641 (class 2606 OID 18484)
-- Name: serverless_job_results serverless_job_results_job_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.serverless_job_results
    ADD CONSTRAINT serverless_job_results_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.serverless_jobs(id) ON DELETE CASCADE;


--
-- TOC entry 3639 (class 2606 OID 18441)
-- Name: serverless_jobs serverless_jobs_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.serverless_jobs
    ADD CONSTRAINT serverless_jobs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- TOC entry 3633 (class 2606 OID 18317)
-- Name: services services_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.services
    ADD CONSTRAINT services_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- TOC entry 3637 (class 2606 OID 18414)
-- Name: twofa_email_codes twofa_email_codes_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.twofa_email_codes
    ADD CONSTRAINT twofa_email_codes_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- TOC entry 3621 (class 2606 OID 19107)
-- Name: user_applications user_applications_application_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.user_applications
    ADD CONSTRAINT user_applications_application_id_fkey FOREIGN KEY (application_id) REFERENCES public.applications(id) ON DELETE CASCADE DEFERRABLE;


--
-- TOC entry 3622 (class 2606 OID 18129)
-- Name: user_applications user_applications_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.user_applications
    ADD CONSTRAINT user_applications_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- TOC entry 3629 (class 2606 OID 18241)
-- Name: users_logs users_logs_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: swautomorph
--

ALTER TABLE ONLY public.users_logs
    ADD CONSTRAINT users_logs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


-- Completed on 2026-10-05 20:12:52 UTC

--
-- PostgreSQL database dump complete
--

\unrestrict NeH0g0FdtuVFarh9se4JrMvRDOdlNtnJ9j4OXM6WNNwnRfSXAAtQf7gfe1XblsZ

