--
-- PostgreSQL database dump
--

\restrict 6FSHQaigQX4RjbNFjWFMCyNdzRNU9fPo5KSmJR05T9DFiF1IBdzoCk5IQ9PIF2Q

-- Dumped from database version 18.6 (Ubuntu 18.6-0ubuntu0.26.04.1)
-- Dumped by pg_dump version 18.6 (Ubuntu 18.6-0ubuntu0.26.04.1)

-- Started on 2026-10-14 21:04:04 UTC

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
-- TOC entry 3760 (class 0 OID 20898)
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
-- TOC entry 3770 (class 0 OID 21009)
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
-- TOC entry 3758 (class 0 OID 20879)
-- Dependencies: 221
-- Data for Name: users; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.users (id, username, email, password_hash, first_name, last_name, suspended, created_at, totp_secret, totp_enabled, totp_backup_codes, twofa_email_enabled, account_type) FROM stdin;
1	admin	admin@agentic-ai-plateform.com	scrypt:32768:8:1$9zoQjSeQUjjnTABn$ad48ef0c4c9d1a677e1acca9170c1e15ff4eacaf8386bc57cca5319c0fd8f1ff3b4b49f321a93d71b21036fe2269e2b510161db767c2462366ee7c3e394ed19d	System	Administrator	f	2026-10-10 08:58:18.207615+00	\N	f	\N	f	\N
2	demo	demo@agentic-ai-plateform.com	scrypt:32768:8:1$B2cAABx8l6QgtBW4$87e2dd1a54e4eeed435c7428bbe42514073560c89b9edf3d220ae28b9122d2166ed072b20055a9060dededfcf7efeb091d15f168ac43731173d7c5e9989a8333	System	Demo	f	2026-10-10 08:58:18.207615+00	\N	f	\N	f	\N
\.


--
-- TOC entry 3762 (class 0 OID 20913)
-- Dependencies: 225
-- Data for Name: auth_tokens; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.auth_tokens (id, user_id, token_hash, expires_at, created_at) FROM stdin;
2	1	7d18b6d332ab82fdd31b368757e5ad456ae19cc69f1c9d5949cd050d921887f2	2026-10-21 20:15:35.32256+00	2026-10-14 20:15:35.322741+00
\.


--
-- TOC entry 3772 (class 0 OID 21026)
-- Dependencies: 235
-- Data for Name: billing_activities; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.billing_activities (id, user_id, application_id, action, started_at, stopped_at, duration_seconds, cost_amount, created_at) FROM stdin;
\.


--
-- TOC entry 3780 (class 0 OID 21107)
-- Dependencies: 243
-- Data for Name: configuration; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.configuration (param_id, parent, key, value) FROM stdin;
1	\N	agentic_engine	kiro-cli
2	\N	agentic_command	
3	\N	runtime_type	runc
\.


--
-- TOC entry 3798 (class 0 OID 21373)
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
-- TOC entry 3766 (class 0 OID 20958)
-- Dependencies: 229
-- Data for Name: servers; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.servers (id, server_ip, server_name, server_capacity_user_max, server_capacity_appli_max, server_status, server_type, created_at, shared_gpu_enabled) FROM stdin;
1	192.168.0.30	main-server	10	50	ACTIVE	STAND_ALONE	2026-10-10 08:58:18.207615+00	f
\.


--
-- TOC entry 3768 (class 0 OID 20977)
-- Dependencies: 231
-- Data for Name: deployments; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.deployments (id, user_id, application_id, application_name, status, deployment_path, git_url, swautomorph_url, gitea_branch_url, modification_history, backups_history, server_id, created_at, updated_at, is_sandbox) FROM stdin;
1	1	1	opcp-serverless-brik	RUNNING	\N	\N	https://agentic-ai-plateform.com/admin/opcp-serverless-brik	\N	[]	[]	1	2026-10-10 09:03:25.18589+00	2026-10-10 09:03:25.18589+00	f
2	1	28	ai-hypervisia	COMPLETED	/home/partipolia/deployments/admin/ai-hypervisia	https://github.com/Sam9682/ai-hypervisia.git	https://agentic-ai-plateform.com/admin/ai-hypervisia	https://github.com/Sam9682/ai-hypervisia.git	[]	[]	1	2026-10-13 08:05:22.20465+00	2026-10-14 21:04:04.360167+00	f
\.


--
-- TOC entry 3782 (class 0 OID 21117)
-- Dependencies: 245
-- Data for Name: services; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.services (id, name, image, user_id, desired_replicas, ports, environment, volumes, health_check_path, created_at, updated_at) FROM stdin;
\.


--
-- TOC entry 3784 (class 0 OID 21141)
-- Dependencies: 247
-- Data for Name: instances; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.instances (id, service_id, instance_id, server_id, service_name, container_id, status, port, health_status, last_health_check, created_at, updated_at) FROM stdin;
\.


--
-- TOC entry 3776 (class 0 OID 21065)
-- Dependencies: 239
-- Data for Name: payment_modes; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.payment_modes (id, user_id, payment_type, bank_account, paypal_email, card_last_four, card_type, is_default, created_at) FROM stdin;
1	2	bank_transfer	\N	\N	\N	\N	t	2026-10-10 08:58:18.207615+00
\.


--
-- TOC entry 3778 (class 0 OID 21084)
-- Dependencies: 241
-- Data for Name: invoicing; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.invoicing (id, user_id, invoice_month, total_amount, status, payment_date, payment_mode_id, created_at) FROM stdin;
\.


--
-- TOC entry 3796 (class 0 OID 21331)
-- Dependencies: 259
-- Data for Name: mig_instances; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.mig_instances (id, server_id, instance_uuid, profile_name, gpu_memory_mb, created_at) FROM stdin;
\.


--
-- TOC entry 3794 (class 0 OID 21309)
-- Dependencies: 257
-- Data for Name: mig_profiles; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.mig_profiles (id, server_id, profile_name, profile_id, gpu_memory_gb, created_at) FROM stdin;
\.


--
-- TOC entry 3786 (class 0 OID 21196)
-- Dependencies: 249
-- Data for Name: password_reset_tokens; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.password_reset_tokens (id, user_id, token_hash, expires_at, used, created_at) FROM stdin;
\.


--
-- TOC entry 3800 (class 0 OID 21486)
-- Dependencies: 263
-- Data for Name: runtime_containers; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.runtime_containers (id, server_id, container_id, name, image, runtime, state, is_platform_managed, classification, confidence_score, classification_evidence, labels, first_seen, last_seen) FROM stdin;
\.


--
-- TOC entry 3804 (class 0 OID 21545)
-- Dependencies: 267
-- Data for Name: runtime_anomalies; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.runtime_anomalies (id, container_pk, rule_id, severity, evidence, status, detected_at) FROM stdin;
\.


--
-- TOC entry 3802 (class 0 OID 21523)
-- Dependencies: 265
-- Data for Name: runtime_observations; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.runtime_observations (id, container_pk, cpu_percent, memory_bytes, pids, process_summary, network_summary, state, observed_at) FROM stdin;
\.


--
-- TOC entry 3806 (class 0 OID 21573)
-- Dependencies: 269
-- Data for Name: runtime_scan_runs; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.runtime_scan_runs (id, server_id, started_at, finished_at, containers_seen, error) FROM stdin;
\.


--
-- TOC entry 3789 (class 0 OID 21239)
-- Dependencies: 252
-- Data for Name: serverless_jobs; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.serverless_jobs (id, user_id, image, command, environment, timeout_seconds, status, created_at, started_at, completed_at, exit_code, worker_id, target_link) FROM stdin;
\.


--
-- TOC entry 3791 (class 0 OID 21273)
-- Dependencies: 254
-- Data for Name: serverless_job_logs; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.serverless_job_logs (id, job_id, stream, content, created_at) FROM stdin;
\.


--
-- TOC entry 3792 (class 0 OID 21293)
-- Dependencies: 255
-- Data for Name: serverless_job_results; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.serverless_job_results (job_id, result, created_at) FROM stdin;
\.


--
-- TOC entry 3788 (class 0 OID 21220)
-- Dependencies: 251
-- Data for Name: twofa_email_codes; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.twofa_email_codes (id, user_id, code, expires_at, used, created_at) FROM stdin;
\.


--
-- TOC entry 3764 (class 0 OID 20932)
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
-- TOC entry 3774 (class 0 OID 21048)
-- Dependencies: 237
-- Data for Name: users_logs; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.users_logs (id, user_id, username, action, datetime) FROM stdin;
1	1	admin	logout	2026-10-10 09:04:11.605708+00
2	1	admin	login	2026-10-10 09:04:18.233585+00
3	1	admin	login	2026-10-14 20:15:35.324395+00
\.


--
-- TOC entry 3812 (class 0 OID 0)
-- Dependencies: 232
-- Name: application_costs_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.application_costs_id_seq', 4, true);


--
-- TOC entry 3813 (class 0 OID 0)
-- Dependencies: 222
-- Name: applications_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.applications_id_seq', 37, true);


--
-- TOC entry 3814 (class 0 OID 0)
-- Dependencies: 224
-- Name: auth_tokens_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.auth_tokens_id_seq', 2, true);


--
-- TOC entry 3815 (class 0 OID 0)
-- Dependencies: 234
-- Name: billing_activities_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.billing_activities_id_seq', 1, false);


--
-- TOC entry 3816 (class 0 OID 0)
-- Dependencies: 242
-- Name: configuration_param_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.configuration_param_id_seq', 3, true);


--
-- TOC entry 3817 (class 0 OID 0)
-- Dependencies: 260
-- Name: deploy_templates_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.deploy_templates_id_seq', 96, true);


--
-- TOC entry 3818 (class 0 OID 0)
-- Dependencies: 230
-- Name: deployments_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.deployments_id_seq', 2, true);


--
-- TOC entry 3819 (class 0 OID 0)
-- Dependencies: 246
-- Name: instances_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.instances_id_seq', 1, false);


--
-- TOC entry 3820 (class 0 OID 0)
-- Dependencies: 240
-- Name: invoicing_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.invoicing_id_seq', 1, false);


--
-- TOC entry 3821 (class 0 OID 0)
-- Dependencies: 258
-- Name: mig_instances_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.mig_instances_id_seq', 1, false);


--
-- TOC entry 3822 (class 0 OID 0)
-- Dependencies: 256
-- Name: mig_profiles_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.mig_profiles_id_seq', 1, false);


--
-- TOC entry 3823 (class 0 OID 0)
-- Dependencies: 248
-- Name: password_reset_tokens_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.password_reset_tokens_id_seq', 1, false);


--
-- TOC entry 3824 (class 0 OID 0)
-- Dependencies: 238
-- Name: payment_modes_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.payment_modes_id_seq', 1, true);


--
-- TOC entry 3825 (class 0 OID 0)
-- Dependencies: 266
-- Name: runtime_anomalies_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.runtime_anomalies_id_seq', 1, false);


--
-- TOC entry 3826 (class 0 OID 0)
-- Dependencies: 262
-- Name: runtime_containers_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.runtime_containers_id_seq', 1, false);


--
-- TOC entry 3827 (class 0 OID 0)
-- Dependencies: 264
-- Name: runtime_observations_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.runtime_observations_id_seq', 1, false);


--
-- TOC entry 3828 (class 0 OID 0)
-- Dependencies: 268
-- Name: runtime_scan_runs_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.runtime_scan_runs_id_seq', 1, false);


--
-- TOC entry 3829 (class 0 OID 0)
-- Dependencies: 253
-- Name: serverless_job_logs_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.serverless_job_logs_id_seq', 1, false);


--
-- TOC entry 3830 (class 0 OID 0)
-- Dependencies: 228
-- Name: servers_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.servers_id_seq', 1, true);


--
-- TOC entry 3831 (class 0 OID 0)
-- Dependencies: 244
-- Name: services_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.services_id_seq', 1, false);


--
-- TOC entry 3832 (class 0 OID 0)
-- Dependencies: 250
-- Name: twofa_email_codes_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.twofa_email_codes_id_seq', 1, false);


--
-- TOC entry 3833 (class 0 OID 0)
-- Dependencies: 226
-- Name: user_applications_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.user_applications_id_seq', 7, true);


--
-- TOC entry 3834 (class 0 OID 0)
-- Dependencies: 220
-- Name: users_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.users_id_seq', 2, true);


--
-- TOC entry 3835 (class 0 OID 0)
-- Dependencies: 236
-- Name: users_logs_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.users_logs_id_seq', 3, true);


-- Completed on 2026-10-14 21:04:04 UTC

--
-- PostgreSQL database dump complete
--

\unrestrict 6FSHQaigQX4RjbNFjWFMCyNdzRNU9fPo5KSmJR05T9DFiF1IBdzoCk5IQ9PIF2Q

