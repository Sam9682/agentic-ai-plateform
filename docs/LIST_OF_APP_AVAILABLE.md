# List of Available Applications

This document summarizes the default applications available on the OPCP AI-Powered Store (Container / Serverless / AI) platform.

These applications are defined in `conf/default_apps` and are automatically provisioned for the admin user when the platform starts.

---

## Applications

### 1. ai-staticwebsite
- **Description**: Simple static Web Site
- **Repository**: [github.com/Sam9682/ai-staticwebsite](https://github.com/Sam9682/ai-staticwebsite.git)
- **Repository Size**: ~4 MB
- **Timings**: Build ~29s | Start ~29s | Stop ~10s | PS ~1s

---

### 2. ai-shai-web-interface
- **Description**: Interface Web pour Shai
- **Repository**: [github.com/Sam9682/ai-shai-web-interface](https://github.com/Sam9682/ai-shai-web-interface.git)
- **Repository Size**: ~10 MB
- **Timings**: Build ~30s | Start ~30s | Stop ~10s | PS ~1s

---

### 3. opcp-openstack-first-steps
- **Description**: OPCP Openstack First Steps
- **Repository**: [github.com/Sam9682/opcp-openstack-first-steps](https://github.com/Sam9682/opcp-openstack-first-steps.git)
- **Repository Size**: ~10 MB
- **Timings**: Build ~30s | Start ~30s | Stop ~10s | PS ~1s

---

### 4. opcp-openstack-automation
- **Description**: OPCP Openstack Automation
- **Repository**: [github.com/Sam9682/opcp-openstack-automation](https://github.com/Sam9682/opcp-openstack-automation.git)
- **Repository Size**: ~10 MB
- **Timings**: Build ~30s | Start ~30s | Stop ~10s | PS ~1s

---

### 5. opcp-psmc-dashboard
- **Description**: OPCP PSMC Dashboard
- **Repository**: [github.com/Sam9682/opcp-psmc-dashboard](https://github.com/Sam9682/opcp-psmc-dashboard.git)
- **Repository Size**: ~10 MB
- **Timings**: Build ~30s | Start ~30s | Stop ~10s | PS ~1s

---

### 6. opcp-openstack-simulator
- **Description**: OPCP Openstack Simulator
- **Repository**: [github.com/Sam9682/opcp-openstack-simulator](https://github.com/Sam9682/opcp-openstack-simulator.git)
- **Repository Size**: ~10 MB
- **Timings**: Build ~30s | Start ~30s | Stop ~10s | PS ~1s

---

### 7. opcp-introduction
- **Description**: OPCP Introduction - non tech
- **Repository**: [github.com/Sam9682/opcp-introduction](https://github.com/Sam9682/opcp-introduction.git)
- **Repository Size**: ~10 MB
- **Timings**: Build ~30s | Start ~30s | Stop ~10s | PS ~1s

---

### 8. opcp-serverless-brik
- **Description**: OPCP Serverless Docker Execution
- **Repository**: [github.com/Sam9682/opcp-serverless-brik](https://github.com/Sam9682/opcp-serverless-brik.git)
- **Repository Size**: ~10 MB
- **Timings**: Build ~30s | Start ~30s | Stop ~10s | PS ~1s

---

### 9. opcp-ai-start-labs
- **Description**: OPCP AI Start Labs
- **Repository**: [github.com/Sam9682/opcp-ai-start-labs](https://github.com/Sam9682/opcp-ai-start-labs.git)
- **Repository Size**: ~10 MB
- **Timings**: Build ~30s | Start ~30s | Stop ~10s | PS ~1s

---

### 10. opcp-proxmox-experience
- **Description**: OPCP Proxmox experience
- **Repository**: [github.com/Sam9682/opcp-proxmox-experience](https://github.com/Sam9682/opcp-proxmox-experience.git)
- **Repository Size**: ~10 MB
- **Timings**: Build ~30s | Start ~30s | Stop ~10s | PS ~1s

---

### 11. opcp-internal-rag
- **Description**: OPCP Internal PSMC RAG
- **Repository**: [github.com/Sam9682/opcp-internal-rag](https://github.com/Sam9682/opcp-internal-rag.git)
- **Repository Size**: ~10 MB
- **Timings**: Build ~30s | Start ~30s | Stop ~10s | PS ~1s

---

## Configuration Format

Applications are defined in `conf/default_apps`, one per line, with pipe-separated fields. Lines starting with # are comments and empty lines are ignored.

```
name | description | git_url | git_repo_size (MB) | docker_build_duration (s) | docker_start_duration (s) | docker_stop_duration (s) | docker_ps_duration (s)
```

## How It Works

1. When the platform starts, the applications listed in `conf/default_apps` are loaded into the database.
2. The admin user is automatically assigned all default applications.
3. New users can be assigned applications by the administrator from the Users management panel.
4. Each application is cloned from its Git repository, built with Docker, and deployed with its own isolated ports. The platform reserves 12 consecutive ports per application (6 HTTP + 6 HTTPS).
