# INIT_PLATFORM — User Guide

This document explains how to use `init_pltf.sh` to bootstrap a fresh server for the AI-SwAutoMorph platform.

## Overview

`init_pltf.sh` is a one-shot provisioning script that installs all system dependencies, configures networking, sets up Docker, and prepares the repository for deployment. It is designed to run on a fresh **Ubuntu** server (typically an OVHcloud instance).

Before any installation step, the script collects the **platform identity** so each customer deployment can be renamed in one place. When a terminal is attached it prompts for the values below (press Enter to accept the shown default); it then clones the repository and writes `PLTF_NAME` / `PLTF_FOLDER` into `conf/deploy.ini`.


### How the defaults are resolved

Each of the four identity values is resolved independently through a fixed precedence chain:

1. A pre-set environment variable (if non-empty) always wins.
2. Otherwise the matching key in `conf/deploy.ini` is used (if present and non-empty).
3. Otherwise a built-in hardcoded fallback is used, so the script never breaks on a fresh or incomplete config.

The hardcoded fallbacks are `agentic-ai-plateform` (PLTF_FOLDER), `agentic-ai-plateform` (PLTF_NAME), `https://github.com/Sam9682/agentic-ai-plateform.git` (REPO_URL) and `git@github.com:Sam9682/ai-swautomorph--shared.git` (SUBMODULE_URL). The shipped `conf/deploy.ini` already defines these keys (its `PLTF_NAME` is the longer deployment-specific value, which takes precedence over the fallback), and every parameter in that file carries an explanatory comment.

## Prerequisites

| Requirement |                              Details                       |
|-------------|------------------------------------------------------------|
| OS          | Ubuntu 22.04+ (tested on OVHcloud VPS/dedicated)           |
| User        | A non-root user with `sudo` privileges                     |
| Network     | Internet access (public interface)                         |
| SSH key     | Configured for `git@github.com:Sam9682/agentic-ai-plateform.git` |
| GPU (optional) | NVIDIA H100, A100, or A30 for MIG shared GPU features   |

## What the script installs

|         Component       |               Purpose               |
|-------------------------|-------------------------------------|
| Python 3 + pip + venv   | Application runtime                 |
| net-tools, unzip        | System utilities                    |
| Amazon Kiro CLI         | AI-assisted CLI chat                |
| OVH shai CLI            | OVHcloud management                 |
| AWS CLI v2              | S3-compatible object storage access |
| Terraform 1.14.5        | Infrastructure as code              |
| Docker + docker-compose | Container orchestration             |
| NVIDIA Drivers + MIG    | GPU compute and Multi-Instance GPU partitioning |

## Usage

```bash
chmod +x init_pltf.sh
./init_pltf.sh
```

The script first prompts for the platform identity, then runs the install steps. Each step prints a colored status:
- 🟢 `[OK]` — step completed successfully
- 🔴 `[ERROR]` — step failed
- 🟡 `[WARNING]` — non-critical issue or manual action needed

### Platform identity prompts

| Prompt | Default | Written to |
|--------|---------|------------|
| Platform folder slug (`PLTF_FOLDER`) | `agentic-ai-plateform` | install dir, container prefixes, `conf/deploy.ini` |
| Platform display name (`PLTF_NAME`) | `agentic-ai-plateform_AI_SharedGPU_Docker_Serverless` | web UI, generated docs, `conf/deploy.ini` |
| Repository clone URL (`REPO_URL`) | `https://github.com/Sam9682/agentic-ai-plateform.git` | the clone source |
| Shared submodule URL (`SUBMODULE_URL`) | `git@github.com:Sam9682/ai-swautomorph--shared.git` | the `shared` submodule source |

The folder slug is validated (lowercase letters, digits and hyphens only); an invalid value is re-prompted, or aborts the run if it was pre-set via the environment.

### Non-interactive / CI runs

Pre-set any of the four values as environment variables to skip the matching prompt. With no TTY and no overrides, the defaults above are used:

```bash
PLTF_FOLDER=acme-cloud \
PLTF_NAME="Acme Cloud Platform" \
REPO_URL=https://github.com/your-org/your-repo.git \
SUBMODULE_URL=git@github.com:your-org/shared.git \
./init_pltf.sh
```

## Step-by-step breakdown

### 1. System dependencies

Installs Python 3, pip, venv, net-tools, and unzip via `apt`.

### 2. CLI tools

Installs three CLI tools:
- **Kiro CLI** — from `https://cli.kiro.dev/install`
- **OVH shai** — from the official OVH GitHub repository
- **AWS CLI v2** — from the official AWS distribution

### 3. Terraform

Downloads and installs Terraform `1.14.5` to `/usr/local/bin/`.

### 4. Network interface priorities

Automatically detects public and private network interfaces and configures netplan route metrics:
- **Public interface** → metric `50` (preferred for outbound traffic)
- **Private interface** → metric `200` (lower priority)

A backup of the original netplan configuration is created before any changes.

> This step is skipped if netplan is not found on the system.

### 5. Docker

Installs Docker Engine and docker-compose. Adds the current user to the `docker` group.

> You must log out and back in (or run `newgrp docker`) for the group change to take effect.

### 6. NVIDIA GPU Drivers and MIG

Installs NVIDIA GPU drivers and enables Multi-Instance GPU (MIG) mode for GPU sharing:

1. **NVIDIA Driver** — Installs `nvidia-driver-550` and `nvidia-utils-550` via apt
2. **MIG Mode** — Enables Multi-Instance GPU with `sudo nvidia-smi -mig 1` (requires compatible GPU like H100/A100/A30)
3. **Container Toolkit** — Installs `nvidia-container-toolkit` for Docker GPU access
4. **Verification** — Runs `docker run --gpus` test with a 30-second timeout

All GPU steps are non-blocking — if the server has no GPU or an incompatible GPU, the script logs a warning and continues with the remaining setup.

> This step requires an NVIDIA GPU with MIG support (H100, A100, or A30). On servers without GPU hardware, a warning is logged and the platform operates without GPU features.

### 7. AWS credentials

Creates `~/.aws/config` and `~/.aws/credentials` with a placeholder profile `OVH-SWAUTOMORPH` pointing to the OVHcloud S3 endpoint (`s3.gra.io.cloud.ovh.net`).

### 8. Repository clone

Clones the repository from the chosen `REPO_URL` into the chosen `PLTF_FOLDER`, adds the `shared` submodule from `SUBMODULE_URL`, and initializes submodules. After the clone, `PLTF_NAME` and `PLTF_FOLDER` are written into `conf/deploy.ini`.

### 9. Python virtual environment

Creates a `.venv` in the project directory and installs all dependencies from `requirements.txt`.

### 10. Final configuration

Creates the `logs/` directory and makes `setup_modsecurity_config.sh` executable.

## Post-installation steps

After the script completes, you **must** perform these manual steps:

### Review the platform identity

`PLTF_NAME` and `PLTF_FOLDER` were already written to `./conf/deploy.ini` from your answers to the init prompts. Review the remaining settings there (and adjust `PLTF_NAME` / `PLTF_FOLDER` if needed):

```ini
DOMAIN=yourdomain.com
PLTF_NAME=Your Platform Name
PLTF_FOLDER=your-platform

# Optional: secondary domains
SECONDARY_DOMAINS=other.com:other.com www.other.com:https://yourdomain.com:6137
```

### Add SSL certificates

Place your SSL files in the `ssl/` directory:

```
~/<PLTF_FOLDER>/ssl/fullchain_domain.crt    # Full certificate chain
~/<PLTF_FOLDER>/ssl/privateKey_domain.key   # Private key
```

### Configure S3 credentials

Edit `~/.aws/credentials` and replace the placeholder values:

```ini
[OVH-SWAUTOMORPH]
aws_access_key_id = YOUR_ACCESS_KEY
aws_secret_access_key = YOUR_SECRET_KEY
endpoint_url = https://s3.gra.io.cloud.ovh.net/
signature_version = s3v4
```

### Apply Docker group

Log out and back in, or run:

```bash
newgrp docker
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `Permission denied` on script | Run `chmod +x init_pltf.sh` |
| Docker commands fail after install | Log out/in or run `newgrp docker` |
| Git clone fails | Ensure your SSH key is added to GitHub |
| Netplan step skipped | Normal on non-netplan systems; configure routing manually |
| AWS CLI not found after install | Run `source ~/.bashrc` or open a new shell |
| NVIDIA driver fails to install | Normal on non-GPU servers; GPU features will be unavailable |
| MIG mode enable fails | GPU may not support MIG (requires H100/A100/A30) |
| Docker GPU verification fails | Check `nvidia-smi` works on the host first |

## Related documentation

- [DEPLOYMENT_GUIDE.md](./DEPLOYMENT_GUIDE.md) — How to deploy the platform after initialization
- [ARCHITECTURE_GUIDE.md](./ARCHITECTURE_GUIDE.md) — Platform architecture overview
- [REPLICATION_GUIDE.md](./technicals/REPLICATION_GUIDE.md) — Multi-server replication setup
