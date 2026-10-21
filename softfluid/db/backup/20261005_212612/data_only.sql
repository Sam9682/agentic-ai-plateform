--
-- PostgreSQL database dump
--

\restrict N5hFEMPUpdD3n9ljViFPKTXezltEpcpfg2cqdKJZavPl9uMiBrqyHEmSqJrhQpT

-- Dumped from database version 18.6 (Ubuntu 18.6-0ubuntu0.26.04.1)
-- Dumped by pg_dump version 18.6 (Ubuntu 18.6-0ubuntu0.26.04.1)

-- Started on 2026-10-05 21:26:13 UTC

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
-- TOC entry 3719 (class 0 OID 18080)
-- Dependencies: 223
-- Data for Name: applications; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.applications (id, name, url, description, git_url, git_remote_url, git_local_url, git_repo_size, docker_build_duration, docker_start_duration, docker_stop_duration, docker_ps_duration, docker_compose_ports, created_at) FROM stdin;
1	opcp-serverless-brik	\N	OPCP Serverless Docker Execution	https://github.com/Sam9682/opcp-serverless-brik.git	\N	\N	10	30	30	10	1	\N	2026-10-02 18:17:51.196248+00
2	ai-staticwebsite	\N	Simple static Web Site	https://github.com/Sam9682/ai-staticwebsite.git	\N	\N	4	29	29	10	1	\N	2026-10-02 18:17:51.197785+00
3	ai-shai-web-interface	\N	Interface Web pour Shai	https://github.com/Sam9682/ai-shai-web-interface.git	\N	\N	10	30	30	10	1	\N	2026-10-02 18:17:51.197785+00
4	opcp-openstack-first-steps	\N	OPCP Openstack First Steps	https://github.com/Sam9682/opcp-openstack-first-steps.git	\N	\N	10	30	30	10	1	\N	2026-10-02 18:17:51.197785+00
5	opcp-openstack-automation	\N	OPCP Openstack Automation	https://github.com/Sam9682/opcp-openstack-automation.git	\N	\N	10	30	30	10	1	\N	2026-10-02 18:17:51.197785+00
6	opcp-psmc-dashboard	\N	OPCP PSMC Dashboard	https://github.com/Sam9682/opcp-psmc-dashboard.git	\N	\N	10	30	30	10	1	\N	2026-10-02 18:17:51.197785+00
8	opcp-introduction	\N	OPCP Introduction - non tech	https://github.com/Sam9682/opcp-introduction.git	\N	\N	10	30	30	10	1	\N	2026-10-02 18:17:51.197785+00
11	opcp-proxmox-experience	\N	OPCP Proxmox experience	https://github.com/Sam9682/opcp-proxmox-experience.git	\N	\N	10	30	30	10	1	\N	2026-10-02 18:17:51.197785+00
12	opcp-internal-rag	\N	OPCP Internal PSMC RAG	https://github.com/Sam9682/opcp-internal-rag.git	\N	\N	10	30	30	10	1	\N	2026-10-02 18:17:51.197785+00
10	opcp-ai-start-labs	https://partipolia.fr:6208	OPCP AI Start Labs	https://github.com/Sam9682/opcp-ai-start-labs.git	\N	\N	10	30	30	10	1	\N	2026-10-02 18:17:51.197785+00
7	opcp-openstack-simulator	https://partipolia.fr:6172	OPCP Openstack Simulator	https://github.com/Sam9682/opcp-openstack-simulator.git	\N	\N	10	30	30	10	1	\N	2026-10-02 18:17:51.197785+00
\.


--
-- TOC entry 3729 (class 0 OID 18191)
-- Dependencies: 233
-- Data for Name: application_costs; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.application_costs (id, application_id, cost_per_day, created_at, updated_at) FROM stdin;
1	1	1.00	2026-10-02 18:17:51.196248+00	2026-10-02 18:17:51.196248+00
2	11	1.00	2026-10-02 18:17:51.197785+00	2026-10-02 18:17:51.197785+00
3	12	1.00	2026-10-02 18:17:51.197785+00	2026-10-02 18:17:51.197785+00
4	10	1.00	2026-10-02 18:17:51.197785+00	2026-10-02 18:17:51.197785+00
5	2	1.00	2026-10-02 18:17:51.197785+00	2026-10-02 18:17:51.197785+00
6	5	1.00	2026-10-02 18:17:51.197785+00	2026-10-02 18:17:51.197785+00
7	8	1.00	2026-10-02 18:17:51.197785+00	2026-10-02 18:17:51.197785+00
8	6	1.00	2026-10-02 18:17:51.197785+00	2026-10-02 18:17:51.197785+00
9	4	1.00	2026-10-02 18:17:51.197785+00	2026-10-02 18:17:51.197785+00
10	3	1.00	2026-10-02 18:17:51.197785+00	2026-10-02 18:17:51.197785+00
11	7	1.00	2026-10-02 18:17:51.197785+00	2026-10-02 18:17:51.197785+00
\.


--
-- TOC entry 3717 (class 0 OID 18061)
-- Dependencies: 221
-- Data for Name: users; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.users (id, username, email, password_hash, first_name, last_name, suspended, created_at, totp_secret, totp_enabled, totp_backup_codes, twofa_email_enabled, account_type) FROM stdin;
2	demo	demo@partipolia.fr	scrypt:32768:8:1$9DBK3fjdYIeVDlbL$4b748a71f042c989b86969fb60e057827e6472b99f42aa1ca9aef97ffdf8258df43f046a5993e09d5b739f0cf70cd5d689d1cf85dab29f22b99a2d47731d15de	System	Demo	f	2026-10-02 18:17:51.200767+00	\N	f	\N	f	\N
1	admin	admin@partipolia.fr	scrypt:32768:8:1$6VXBvmzNAkjMxOSU$5f566bbbd6744145f7184d9884f38e957fe0b4a5d96f9629c7679e65f4327da554b5fdfaf7f7a12a064c383934594469df1f29952f044a475e2033f47428bc0c	System	Administrator	f	2026-10-02 18:17:51.200767+00	\N	f	\N	f	\N
\.


--
-- TOC entry 3721 (class 0 OID 18095)
-- Dependencies: 225
-- Data for Name: auth_tokens; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.auth_tokens (id, user_id, token_hash, expires_at, created_at) FROM stdin;
\.


--
-- TOC entry 3731 (class 0 OID 18208)
-- Dependencies: 235
-- Data for Name: billing_activities; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.billing_activities (id, user_id, application_id, action, started_at, stopped_at, duration_seconds, cost_amount, created_at) FROM stdin;
2	1	4	stop	\N	2026-10-02 20:43:51.121761+00	\N	\N	2026-10-02 20:43:51.121761+00
1	1	7	start	2026-10-02 18:49:49.751011+00	2026-10-02 20:43:56.509233+00	6846	0.08	2026-10-02 18:49:49.751011+00
3	1	7	stop	\N	2026-10-02 20:43:56.509804+00	\N	\N	2026-10-02 20:43:56.509804+00
4	1	11	stop	\N	2026-10-02 20:44:12.018576+00	\N	\N	2026-10-02 20:44:12.018576+00
5	1	5	stop	\N	2026-10-02 20:44:25.92013+00	\N	\N	2026-10-02 20:44:25.92013+00
6	1	8	stop	\N	2026-10-02 20:44:41.431231+00	\N	\N	2026-10-02 20:44:41.431231+00
7	1	10	stop	\N	2026-10-02 20:45:02.126144+00	\N	\N	2026-10-02 20:45:02.126144+00
8	1	2	stop	\N	2026-10-02 20:55:16.264042+00	\N	\N	2026-10-02 20:55:16.264042+00
\.


--
-- TOC entry 3739 (class 0 OID 18289)
-- Dependencies: 243
-- Data for Name: configuration; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.configuration (param_id, parent, key, value) FROM stdin;
1	\N	agentic_engine	kiro-cli
2	\N	agentic_command	
3	\N	runtime_type	kata
\.


--
-- TOC entry 3757 (class 0 OID 18555)
-- Dependencies: 261
-- Data for Name: deploy_templates; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.deploy_templates (id, template_id, app_type, display_name, source_image, ports, environment, memory_mb, cpu_cores, timeout_seconds, enabled, created_at) FROM stdin;
1	static-site	static_site	Static Website	nginx:1.27-alpine	[{"protocol": "http", "container": 80}]	[]	128	0.5	300	t	2026-10-02 18:17:51.192498+00
2	fastapi-starter	fastapi	FastAPI Application	tiangolo/uvicorn-gunicorn-fastapi:python3.11	[{"protocol": "http", "container": 80}]	[{"name": "MODULE_NAME", "value": "app.main"}]	512	1.0	300	t	2026-10-02 18:17:51.192498+00
3	n8n	n8n	n8n Workflow Automation	n8nio/n8n:latest	[{"protocol": "http", "container": 5678}]	[{"name": "N8N_PORT", "value": "5678"}]	1024	1.0	600	t	2026-10-02 18:17:51.192498+00
4	ollama	ollama	Ollama LLM Runtime	ollama/ollama:latest	[{"protocol": "http", "container": 11434}]	[{"name": "OLLAMA_HOST", "value": "0.0.0.0"}]	4096	2.0	1200	t	2026-10-02 18:17:51.192498+00
5	jupyter	jupyter	Jupyter Notebook	jupyter/base-notebook:latest	[{"protocol": "http", "container": 8888}]	[{"name": "JUPYTER_ENABLE_LAB", "value": "yes"}]	2048	1.0	600	t	2026-10-02 18:17:51.192498+00
6	vector-db	vector_db	Qdrant Vector Database	qdrant/qdrant:latest	[{"protocol": "http", "container": 6333}]	[]	1024	1.0	300	t	2026-10-02 18:17:51.192498+00
\.


--
-- TOC entry 3725 (class 0 OID 18140)
-- Dependencies: 229
-- Data for Name: servers; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.servers (id, server_ip, server_name, server_capacity_user_max, server_capacity_appli_max, server_status, server_type, created_at, shared_gpu_enabled) FROM stdin;
1	192.168.0.30	main-server	10	50	ACTIVE	STAND_ALONE	2026-10-02 18:17:51.200767+00	f
\.


--
-- TOC entry 3727 (class 0 OID 18159)
-- Dependencies: 231
-- Data for Name: deployments; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.deployments (id, user_id, application_id, application_name, status, deployment_path, git_url, swautomorph_url, gitea_branch_url, modification_history, backups_history, server_id, created_at, updated_at, is_sandbox) FROM stdin;
7	1	5	opcp-openstack-automation	COMPLETED	/home/partipolia/deployments/admin/opcp-openstack-automation	https://github.com/Sam9682/opcp-openstack-automation.git	https://partipolia.fr/admin/opcp-openstack-automation	https://github.com/Sam9682/opcp-openstack-automation.git	[]	[]	1	2026-10-02 18:18:43.41906+00	2026-10-05 20:15:08.949604+00	f
6	1	8	opcp-introduction	COMPLETED	/home/partipolia/deployments/admin/opcp-introduction	https://github.com/Sam9682/opcp-introduction.git	https://partipolia.fr/admin/opcp-introduction	https://github.com/Sam9682/opcp-introduction.git	[]	[]	1	2026-10-02 18:18:40.801093+00	2026-10-05 20:15:09.064357+00	f
4	1	10	opcp-ai-start-labs	COMPLETED	/home/partipolia/deployments/admin/opcp-ai-start-labs	https://github.com/Sam9682/opcp-ai-start-labs.git	https://partipolia.fr/admin/opcp-ai-start-labs	https://github.com/Sam9682/opcp-ai-start-labs.git	[]	[]	1	2026-10-02 18:18:27.546049+00	2026-10-05 20:15:09.069805+00	f
8	1	4	opcp-openstack-first-steps	COMPLETED	/home/partipolia/deployments/admin/opcp-openstack-first-steps	https://github.com/Sam9682/opcp-openstack-first-steps.git	https://partipolia.fr/admin/opcp-openstack-first-steps	https://github.com/Sam9682/opcp-openstack-first-steps.git	[]	[]	1	2026-10-02 18:18:46.583589+00	2026-10-05 20:15:09.33786+00	f
10	1	11	opcp-proxmox-experience	COMPLETED	/home/partipolia/deployments/admin/opcp-proxmox-experience	https://github.com/Sam9682/opcp-proxmox-experience.git	https://partipolia.fr/admin/opcp-proxmox-experience	https://github.com/Sam9682/opcp-proxmox-experience.git	[]	[]	1	2026-10-02 18:18:50.418676+00	2026-10-05 20:15:09.353445+00	f
5	1	12	opcp-internal-rag	COMPLETED	/home/partipolia/deployments/admin/opcp-internal-rag	https://github.com/Sam9682/opcp-internal-rag.git	https://partipolia.fr/admin/opcp-internal-rag	https://github.com/Sam9682/opcp-internal-rag.git	[]	[]	1	2026-10-02 18:18:33.982868+00	2026-10-05 20:15:09.354729+00	f
1	1	1	opcp-serverless-brik	COMPLETED	/home/partipolia/deployments/admin/opcp-serverless-brik	https://github.com/Sam9682/opcp-serverless-brik.git	https://partipolia.fr/admin/opcp-serverless-brik	https://github.com/Sam9682/opcp-serverless-brik.git	[]	[]	1	2026-10-02 18:17:57.687203+00	2026-10-05 20:15:06.738398+00	f
3	1	2	ai-staticwebsite	COMPLETED	/home/partipolia/deployments/admin/ai-staticwebsite	https://github.com/Sam9682/ai-staticwebsite.git	https://partipolia.fr/admin/ai-staticwebsite	https://github.com/Sam9682/ai-staticwebsite.git	[]	[]	1	2026-10-02 18:18:22.091738+00	2026-10-05 20:15:08.94502+00	f
2	1	3	ai-shai-web-interface	COMPLETED	/home/partipolia/deployments/admin/ai-shai-web-interface	https://github.com/Sam9682/ai-shai-web-interface.git	https://partipolia.fr/admin/ai-shai-web-interface	https://github.com/Sam9682/ai-shai-web-interface.git	[]	[]	1	2026-10-02 18:18:20.317621+00	2026-10-05 20:15:08.994612+00	f
9	1	7	opcp-openstack-simulator	COMPLETED	/home/partipolia/deployments/admin/opcp-openstack-simulator	https://github.com/Sam9682/opcp-openstack-simulator.git	https://partipolia.fr/admin/opcp-openstack-simulator	https://github.com/Sam9682/opcp-openstack-simulator.git	[]	[]	1	2026-10-02 18:18:47.921884+00	2026-10-05 20:15:09.375361+00	f
\.


--
-- TOC entry 3741 (class 0 OID 18299)
-- Dependencies: 245
-- Data for Name: services; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.services (id, name, image, user_id, desired_replicas, ports, environment, volumes, health_check_path, created_at, updated_at) FROM stdin;
\.


--
-- TOC entry 3743 (class 0 OID 18323)
-- Dependencies: 247
-- Data for Name: instances; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.instances (id, service_id, instance_id, server_id, service_name, container_id, status, port, health_status, last_health_check, created_at, updated_at) FROM stdin;
\.


--
-- TOC entry 3735 (class 0 OID 18247)
-- Dependencies: 239
-- Data for Name: payment_modes; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.payment_modes (id, user_id, payment_type, bank_account, paypal_email, card_last_four, card_type, is_default, created_at) FROM stdin;
1	2	bank_transfer	\N	\N	\N	\N	t	2026-10-02 18:17:51.200767+00
\.


--
-- TOC entry 3737 (class 0 OID 18266)
-- Dependencies: 241
-- Data for Name: invoicing; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.invoicing (id, user_id, invoice_month, total_amount, status, payment_date, payment_mode_id, created_at) FROM stdin;
\.


--
-- TOC entry 3755 (class 0 OID 18513)
-- Dependencies: 259
-- Data for Name: mig_instances; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.mig_instances (id, server_id, instance_uuid, profile_name, gpu_memory_mb, created_at) FROM stdin;
\.


--
-- TOC entry 3753 (class 0 OID 18491)
-- Dependencies: 257
-- Data for Name: mig_profiles; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.mig_profiles (id, server_id, profile_name, profile_id, gpu_memory_gb, created_at) FROM stdin;
\.


--
-- TOC entry 3745 (class 0 OID 18378)
-- Dependencies: 249
-- Data for Name: password_reset_tokens; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.password_reset_tokens (id, user_id, token_hash, expires_at, used, created_at) FROM stdin;
\.


--
-- TOC entry 3748 (class 0 OID 18421)
-- Dependencies: 252
-- Data for Name: serverless_jobs; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.serverless_jobs (id, user_id, image, command, environment, timeout_seconds, status, created_at, started_at, completed_at, exit_code, worker_id, target_link) FROM stdin;
\.


--
-- TOC entry 3750 (class 0 OID 18455)
-- Dependencies: 254
-- Data for Name: serverless_job_logs; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.serverless_job_logs (id, job_id, stream, content, created_at) FROM stdin;
\.


--
-- TOC entry 3751 (class 0 OID 18475)
-- Dependencies: 255
-- Data for Name: serverless_job_results; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.serverless_job_results (job_id, result, created_at) FROM stdin;
\.


--
-- TOC entry 3747 (class 0 OID 18402)
-- Dependencies: 251
-- Data for Name: twofa_email_codes; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.twofa_email_codes (id, user_id, code, expires_at, used, created_at) FROM stdin;
\.


--
-- TOC entry 3723 (class 0 OID 18114)
-- Dependencies: 227
-- Data for Name: user_applications; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.user_applications (id, user_id, application_id, url, http_port, https_port, http_port2, https_port2, http_port3, https_port3, http_port4, https_port4, http_port5, https_port5, http_port6, https_port6, others_port, created_at) FROM stdin;
1	2	1	https://www.partipolia.fr:6213	6212	6213	6214	6215	6216	6217	6218	6219	6220	6221	6222	6223	\N	2026-10-02 18:17:51.200767+00
2	2	2	https://www.partipolia.fr:6225	6224	6225	6226	6227	6228	6229	6230	6231	6232	6233	6234	6235	\N	2026-10-02 18:17:51.200767+00
3	2	3	https://www.partipolia.fr:6237	6236	6237	6238	6239	6240	6241	6242	6243	6244	6245	6246	6247	\N	2026-10-02 18:17:51.200767+00
4	2	4	https://www.partipolia.fr:6249	6248	6249	6250	6251	6252	6253	6254	6255	6256	6257	6258	6259	\N	2026-10-02 18:17:51.200767+00
5	2	5	https://www.partipolia.fr:6261	6260	6261	6262	6263	6264	6265	6266	6267	6268	6269	6270	6271	\N	2026-10-02 18:17:51.200767+00
6	2	6	https://www.partipolia.fr:6273	6272	6273	6274	6275	6276	6277	6278	6279	6280	6281	6282	6283	\N	2026-10-02 18:17:51.200767+00
8	2	8	https://www.partipolia.fr:6297	6296	6297	6298	6299	6300	6301	6302	6303	6304	6305	6306	6307	\N	2026-10-02 18:17:51.200767+00
10	2	11	https://www.partipolia.fr:6333	6332	6333	6334	6335	6336	6337	6338	6339	6340	6341	6342	6343	\N	2026-10-02 18:17:51.200767+00
11	2	12	https://www.partipolia.fr:6345	6344	6345	6346	6347	6348	6349	6350	6351	6352	6353	6354	6355	\N	2026-10-02 18:17:51.200767+00
12	1	1	https://www.partipolia.fr:6113	6112	6113	6114	6115	6116	6117	6118	6119	6120	6121	6122	6123	\N	2026-10-02 18:17:57.687203+00
13	1	3	https://partipolia.fr:6137	6136	6137	6138	6139	6140	6141	6142	6143	6144	6145	6146	6147	\N	2026-10-02 18:18:17.313958+00
14	1	2	https://partipolia.fr:6125	6124	6125	6126	6127	6128	6129	6130	6131	6132	6133	6134	6135	\N	2026-10-02 18:18:19.536622+00
16	1	12	https://partipolia.fr:6245	6244	6245	6246	6247	6248	6249	6250	6251	6252	6253	6254	6255	\N	2026-10-02 18:18:31.976832+00
17	1	8	https://partipolia.fr:6197	6196	6197	6198	6199	6200	6201	6202	6203	6204	6205	6206	6207	\N	2026-10-02 18:18:36.802737+00
18	1	5	https://partipolia.fr:6161	6160	6161	6162	6163	6164	6165	6166	6167	6168	6169	6170	6171	\N	2026-10-02 18:18:39.860526+00
19	1	4	https://partipolia.fr:6149	6148	6149	6150	6151	6152	6153	6154	6155	6156	6157	6158	6159	\N	2026-10-02 18:18:43.052428+00
21	1	11	https://partipolia.fr:6233	6232	6233	6234	6235	6236	6237	6238	6239	6240	6241	6242	6243	\N	2026-10-02 18:18:49.037361+00
9	2	10	https://partipolia.fr:6208	6320	6321	6322	6323	6324	6325	6326	6327	6328	6329	6330	6331	\N	2026-10-02 18:17:51.200767+00
15	1	10	https://partipolia.fr:6208	6220	6221	6222	6223	6224	6225	6226	6227	6228	6229	6230	6231	\N	2026-10-02 18:18:24.740158+00
7	2	7	https://partipolia.fr:6172	6284	6285	6286	6287	6288	6289	6290	6291	6292	6293	6294	6295	\N	2026-10-02 18:17:51.200767+00
20	1	7	https://partipolia.fr:6172	6184	6185	6186	6187	6188	6189	6190	6191	6192	6193	6194	6195	\N	2026-10-02 18:18:45.776747+00
\.


--
-- TOC entry 3733 (class 0 OID 18230)
-- Dependencies: 237
-- Data for Name: users_logs; Type: TABLE DATA; Schema: public; Owner: swautomorph
--

COPY public.users_logs (id, user_id, username, action, datetime) FROM stdin;
1	1	admin	password_changed	2026-10-02 20:43:13.686397+00
2	1	admin	login	2026-10-03 04:48:23.46107+00
3	1	admin	login	2026-10-03 08:46:50.765412+00
4	1	admin	login	2026-10-05 20:15:05.001438+00
5	1	admin	logout	2026-10-05 20:15:09.249262+00
\.


--
-- TOC entry 3763 (class 0 OID 0)
-- Dependencies: 232
-- Name: application_costs_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.application_costs_id_seq', 11, true);


--
-- TOC entry 3764 (class 0 OID 0)
-- Dependencies: 222
-- Name: applications_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.applications_id_seq', 375, true);


--
-- TOC entry 3765 (class 0 OID 0)
-- Dependencies: 224
-- Name: auth_tokens_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.auth_tokens_id_seq', 3, true);


--
-- TOC entry 3766 (class 0 OID 0)
-- Dependencies: 234
-- Name: billing_activities_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.billing_activities_id_seq', 8, true);


--
-- TOC entry 3767 (class 0 OID 0)
-- Dependencies: 242
-- Name: configuration_param_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.configuration_param_id_seq', 3, true);


--
-- TOC entry 3768 (class 0 OID 0)
-- Dependencies: 260
-- Name: deploy_templates_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.deploy_templates_id_seq', 204, true);


--
-- TOC entry 3769 (class 0 OID 0)
-- Dependencies: 230
-- Name: deployments_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.deployments_id_seq', 10, true);


--
-- TOC entry 3770 (class 0 OID 0)
-- Dependencies: 246
-- Name: instances_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.instances_id_seq', 1, false);


--
-- TOC entry 3771 (class 0 OID 0)
-- Dependencies: 240
-- Name: invoicing_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.invoicing_id_seq', 1, false);


--
-- TOC entry 3772 (class 0 OID 0)
-- Dependencies: 258
-- Name: mig_instances_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.mig_instances_id_seq', 1, false);


--
-- TOC entry 3773 (class 0 OID 0)
-- Dependencies: 256
-- Name: mig_profiles_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.mig_profiles_id_seq', 1, false);


--
-- TOC entry 3774 (class 0 OID 0)
-- Dependencies: 248
-- Name: password_reset_tokens_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.password_reset_tokens_id_seq', 1, false);


--
-- TOC entry 3775 (class 0 OID 0)
-- Dependencies: 238
-- Name: payment_modes_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.payment_modes_id_seq', 1, true);


--
-- TOC entry 3776 (class 0 OID 0)
-- Dependencies: 253
-- Name: serverless_job_logs_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.serverless_job_logs_id_seq', 1, false);


--
-- TOC entry 3777 (class 0 OID 0)
-- Dependencies: 228
-- Name: servers_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.servers_id_seq', 1, true);


--
-- TOC entry 3778 (class 0 OID 0)
-- Dependencies: 244
-- Name: services_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.services_id_seq', 1, false);


--
-- TOC entry 3779 (class 0 OID 0)
-- Dependencies: 250
-- Name: twofa_email_codes_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.twofa_email_codes_id_seq', 1, false);


--
-- TOC entry 3780 (class 0 OID 0)
-- Dependencies: 226
-- Name: user_applications_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.user_applications_id_seq', 21, true);


--
-- TOC entry 3781 (class 0 OID 0)
-- Dependencies: 220
-- Name: users_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.users_id_seq', 2, true);


--
-- TOC entry 3782 (class 0 OID 0)
-- Dependencies: 236
-- Name: users_logs_id_seq; Type: SEQUENCE SET; Schema: public; Owner: swautomorph
--

SELECT pg_catalog.setval('public.users_logs_id_seq', 5, true);


-- Completed on 2026-10-05 21:26:13 UTC

--
-- PostgreSQL database dump complete
--

\unrestrict N5hFEMPUpdD3n9ljViFPKTXezltEpcpfg2cqdKJZavPl9uMiBrqyHEmSqJrhQpT

