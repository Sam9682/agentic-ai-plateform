#!/bin/bash

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Helper function
print_step() {
    echo -e "${BLUE}>${NC} ${GREEN}$1${NC}"
}

print_success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

# Platform identity defaults (DEFAULT_PLTF_FOLDER, DEFAULT_PLTF_NAME,
# DEFAULT_REPO_URL, DEFAULT_SUBMODULE_URL) are no longer hardcoded here. They
# are computed by resolve_platform_defaults (defined below) via the precedence
# chain env > conf/deploy.ini > hardcoded fallback, and that resolver is
# invoked once above the source guard so the DEFAULT_* values exist in both
# sourced and executed contexts.

# Validate a platform folder slug: lowercase letters, digits and hyphens,
# must start with a letter or digit, non-empty.
is_valid_slug() {
    local value="$1"
    [[ "$value" =~ ^[a-z0-9][a-z0-9-]*$ ]]
}

# Collect the platform identity (folder slug, display name, repo URL and
# shared submodule URL) BEFORE the repository is cloned. Values already set
# in the environment are honored as-is; otherwise, when a TTY is attached,
# the user is prompted with the defaults. On a non-interactive run with no
# environment override, the defaults are used.
prompt_platform_identity() {
    # Platform folder slug (with validation + re-prompt loop).
    if [ -z "${PLTF_FOLDER:-}" ]; then
        if [ -t 0 ]; then
            while true; do
                read -r -p "Platform folder slug [${DEFAULT_PLTF_FOLDER}]: " _input
                PLTF_FOLDER="${_input:-$DEFAULT_PLTF_FOLDER}"
                if is_valid_slug "${PLTF_FOLDER}"; then
                    break
                fi
                print_error "Invalid slug '${PLTF_FOLDER}'. Use lowercase letters, digits and hyphens only (e.g. my-platform)."
                PLTF_FOLDER=""
            done
        else
            PLTF_FOLDER="${DEFAULT_PLTF_FOLDER}"
        fi
    fi
    if ! is_valid_slug "${PLTF_FOLDER}"; then
        print_error "PLTF_FOLDER '${PLTF_FOLDER}' is not a valid slug (lowercase letters, digits and hyphens only). Aborting."
        exit 1
    fi

    # Display name.
    if [ -z "${PLTF_NAME:-}" ]; then
        if [ -t 0 ]; then
            read -r -p "Platform display name [${DEFAULT_PLTF_NAME}]: " _input
            PLTF_NAME="${_input:-$DEFAULT_PLTF_NAME}"
        else
            PLTF_NAME="${DEFAULT_PLTF_NAME}"
        fi
    fi

    # Main repository clone URL.
    if [ -z "${REPO_URL:-}" ]; then
        if [ -t 0 ]; then
            read -r -p "Repository clone URL [${DEFAULT_REPO_URL}]: " _input
            REPO_URL="${_input:-$DEFAULT_REPO_URL}"
        else
            REPO_URL="${DEFAULT_REPO_URL}"
        fi
    fi

    # Shared submodule URL.
    if [ -z "${SUBMODULE_URL:-}" ]; then
        if [ -t 0 ]; then
            read -r -p "Shared submodule URL [${DEFAULT_SUBMODULE_URL}]: " _input
            SUBMODULE_URL="${_input:-$DEFAULT_SUBMODULE_URL}"
        else
            SUBMODULE_URL="${DEFAULT_SUBMODULE_URL}"
        fi
    fi

    # Installation directory: the parent folder the platform is cloned into.
    # The repository ends up at "${INSTALL_DIR%/}/${PLTF_FOLDER}". Defaults to
    # "../" (one level above the current working directory).
    if [ -z "${INSTALL_DIR:-}" ]; then
        if [ -t 0 ]; then
            read -r -p "Install location (parent folder) [${DEFAULT_INSTALL_DIR}]: " _input
            INSTALL_DIR="${_input:-$DEFAULT_INSTALL_DIR}"
        else
            INSTALL_DIR="${DEFAULT_INSTALL_DIR}"
        fi
    fi

    export PLTF_FOLDER PLTF_NAME REPO_URL SUBMODULE_URL INSTALL_DIR
}

# Rewrite a key=value pair in an INI file in place, preserving other keys.
# Appends the key if the file or key does not yet exist.
set_ini_value() {
    local file="$1" key="$2" value="$3"
    if [ -f "$file" ] && grep -qE "^${key}=" "$file"; then
        local escaped
        escaped="${value//|/\\|}"
        sed -i "s|^${key}=.*|${key}=${escaped}|" "$file"
    else
        mkdir -p "$(dirname "$file")"
        touch "$file"
        echo "${key}=${value}" >> "$file"
    fi
}

# Read the value of KEY from an INI file.
#   get_ini_value <file> <key>
# Echoes the value (text after the first '=') for the first line matching
# ^KEY= . Prints nothing (empty) when the file is absent or the key is not
# present. Lines whose key is commented (e.g. "# KEY=...") do not match
# because the '#' is part of the matched prefix, so ^KEY= fails.
get_ini_value() {
    local file="$1" key="$2"
    [ -f "$file" ] || return 0
    # First matching line only; strip everything up to and including first '='.
    grep -E "^${key}=" "$file" | head -n 1 | cut -d'=' -f2-
}

# Path to the INI file the resolver reads platform-identity defaults from.
# Overridable via the CONFIG_FILE environment variable (used by the test
# harness to point at a temporary INI); defaults to conf/deploy.ini.
CONFIG_FILE="${CONFIG_FILE:-conf/deploy.ini}"

# Resolve one platform-identity default via the fixed precedence chain:
#   pre-set environment variable  >  conf/deploy.ini value  >  hardcoded fallback
#   _resolve_default <env-var-name> <config-key> <fallback>
# A pre-set, non-empty environment variable (dereferenced with ${!env_name})
# wins. Otherwise the Config_File value is used when non-empty. Otherwise the
# hardcoded fallback is returned. An env var that is unset or empty is treated
# as absent, matching the ${VAR:-} conventions elsewhere in the script.
_resolve_default() {
    local env_name="$1" key="$2" fallback="$3"
    local env_val="${!env_name:-}"
    if [ -n "$env_val" ]; then
        printf '%s' "$env_val"; return 0
    fi
    local cfg_val
    cfg_val="$(get_ini_value "$CONFIG_FILE" "$key")"
    if [ -n "$cfg_val" ]; then
        printf '%s' "$cfg_val"; return 0
    fi
    printf '%s' "$fallback"
}

# Compute the four platform-identity DEFAULT_* variables, each resolved
# independently through _resolve_default. The env-var and config-key names
# match (PLTF_FOLDER, PLTF_NAME, REPO_URL, SUBMODULE_URL) and the fallbacks
# are the original hardcoded agentic-ai-plateform strings.
resolve_platform_defaults() {
    DEFAULT_PLTF_FOLDER="$(_resolve_default  PLTF_FOLDER   PLTF_FOLDER   "agentic-ai-plateform")"
    DEFAULT_PLTF_NAME="$(_resolve_default    PLTF_NAME     PLTF_NAME     "agentic-ai-plateform")"
    DEFAULT_REPO_URL="$(_resolve_default     REPO_URL      REPO_URL      "https://github.com/Sam9682/agentic-ai-plateform.git")"
    DEFAULT_SUBMODULE_URL="$(_resolve_default SUBMODULE_URL SUBMODULE_URL "git@github.com:Sam9682/ai-swautomorph--shared.git")"
    DEFAULT_INSTALL_DIR="$(_resolve_default  INSTALL_DIR   INSTALL_DIR   "../")"
}

# Invoke the resolver once at load time, above the source guard, so the four
# DEFAULT_* variables exist in both sourced (test harness) and executed
# (installer) contexts — replacing the former top-level literal assignments.
# Reading the INI file is idempotent and side-effect-free, so it is safe to run
# on source; the non-idempotent installer work stays below the guard.
resolve_platform_defaults

# Restore ownership of the clone and the user-space home artifacts to the
# invoking user when the installer was launched via `sudo`. Defined above the
# source guard so it loads in both sourced (test harness) and executed
# contexts; it performs no work when merely sourced.
#
# Bug condition (and preservation guard): this is a no-op unless the script
# runs as root (EUID 0) on behalf of a real, non-root invoking user
# (SUDO_USER set and not "root"). That single guard preserves behavior for
# direct non-root runs and for genuine root logins / SUDO_USER=root.
#
# The invoking user's home is resolved from the passwd database (not $HOME,
# which may be /root under sudo). The test harness may override this via a
# non-empty SIM_HOME so the home-artifact restore targets a sandbox home while
# production uses the passwd entry.
restore_invoking_user_ownership() {
    # Not the bug condition -> no-op (preservation).
    if [ "${EUID}" -ne 0 ] || [ -z "${SUDO_USER:-}" ] || [ "${SUDO_USER}" = "root" ]; then
        return 0
    fi

    local user="${SUDO_USER}"

    # Never attempt an invalid chown: the invoking user must exist.
    if ! id -u "${user}" >/dev/null 2>&1; then
        print_warning "Cannot resolve invoking user '${user}'; skipping ownership restore"
        return 0
    fi

    # Resolve the primary group name (not assumed to equal the username).
    local group
    group="$(id -gn "${user}")"

    # Resolve the invoking user's home: prefer a non-empty SIM_HOME override
    # (test harness), otherwise the passwd-database home ($HOME is unreliable
    # under sudo).
    local user_home
    if [ -n "${SIM_HOME:-}" ]; then
        user_home="${SIM_HOME}"
    else
        user_home="$(getent passwd "${user}" | cut -d: -f6)"
    fi

    # Restore the clone (covers shared, .venv, logs, conf/deploy.ini). A
    # failure warns but does not abort an otherwise successful install.
    if [ -n "${REPO_DIR:-}" ] && [ -e "${REPO_DIR}" ]; then
        if ! chown -R "${user}:${group}" "${REPO_DIR}"; then
            print_warning "Failed to restore ownership of ${REPO_DIR} to ${user}:${group}"
        fi
    fi

    # Restore the home artifacts this script creates, skipping any that do not
    # exist. Each chown is guarded independently.
    local path
    for path in "${user_home}/.aws" "${user_home}/deployments"; do
        if [ -e "${path}" ]; then
            if ! chown -R "${user}:${group}" "${path}"; then
                print_warning "Failed to restore ownership of ${path} to ${user}:${group}"
            fi
        fi
    done
}

# When this script is sourced (e.g. by the test harness) rather than executed,
# only the function definitions above are loaded; the installer body below is
# skipped. ${BASH_SOURCE[0]} != $0 indicates a sourced context.
if [ "${BASH_SOURCE[0]}" != "${0}" ]; then
    return 0 2>/dev/null || true
fi

# Collect platform identity before any installation / clone step.
prompt_platform_identity

echo -e "${BLUE}+==========================================+${NC}"
echo -e "${BLUE}${NC}      ${PLTF_NAME} Platform Setup    ${BLUE}${NC}"
echo -e "${BLUE}+==========================================+${NC}"
echo ""

# Install Python and pip
print_step "Installing system dependencies..."
sudo apt update > /dev/null 2>&1
sudo apt --fix-broken install -y > /dev/null 2>&1
sudo apt install -y python3 python3-pip python3-venv net-tools unzip > /dev/null 2>&1
print_success "System dependencies installed"

# Install Amazon Kiro CLI Chat
print_step "Installing Amazon Kiro CLI..."
curl -fsSL https://cli.kiro.dev/install | bash > /dev/null 2>&1
print_success "Amazon Kiro CLI installed"

# Install OVH shai
print_step "Installing OVH CLI..."
curl -fsSL https://raw.githubusercontent.com/ovh/shai/main/install.sh | sh > /dev/null 2>&1
echo 'export PATH="~/.local/bin:$PATH"' >> ~/.bashrc
print_success "OVH CLI installed"

# Install AWS CLI
print_step "Installing AWS CLI..."
curl -s "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip -q awscliv2.zip
sudo ./aws/install > /dev/null 2>&1
rm -rf aws awscliv2.zip
print_success "AWS CLI installed"

# Install Terraform
print_step "Installing Terraform..."
curl -s "https://releases.hashicorp.com/terraform/1.14.5/terraform_1.14.5_linux_amd64.zip" -o "terraform.zip"
unzip -q terraform.zip
sudo mv terraform /usr/local/bin/
rm -f terraform.zip
print_success "Terraform installed"

# Configure network interface priorities
print_step "Configuring network interface priorities..."
if [ -f /etc/netplan/*.yaml ]; then
    NETPLAN_FILE=$(ls /etc/netplan/*.yaml | head -1)
    sudo cp $NETPLAN_FILE ${NETPLAN_FILE}.backup

    # Detect interfaces and their IPs
    INTERFACES=$(ip -o link show | awk -F': ' '{print $2}' | grep -E '^e' | grep -v '@')
    PUBLIC_IF=""
    PRIVATE_IF=""

    for iface in $INTERFACES; do
        IP=$(ip -4 addr show $iface | grep -oP '(?<=inet\s)\d+(\.\d+){3}' | head -1)
        if [ -n "$IP" ]; then
            # Check if IP is private (10.x, 172.16-31.x, 192.168.x)
            if [[ $IP =~ ^10\. ]] || [[ $IP =~ ^172\.(1[6-9]|2[0-9]|3[0-1])\. ]] || [[ $IP =~ ^192\.168\. ]]; then
                PRIVATE_IF=$iface
            else
                PUBLIC_IF=$iface
            fi
        fi
    done

    # Generate netplan config
    echo "network:" | sudo tee $NETPLAN_FILE > /dev/null
    echo "  version: 2" | sudo tee -a $NETPLAN_FILE > /dev/null
    echo "  ethernets:" | sudo tee -a $NETPLAN_FILE > /dev/null

    for iface in $INTERFACES; do
        echo "    $iface:" | sudo tee -a $NETPLAN_FILE > /dev/null
        echo "      dhcp4: true" | sudo tee -a $NETPLAN_FILE > /dev/null
        if [ "$iface" = "$PUBLIC_IF" ]; then
            echo "      dhcp4-overrides:" | sudo tee -a $NETPLAN_FILE > /dev/null
            echo "        route-metric: 50" | sudo tee -a $NETPLAN_FILE > /dev/null
        elif [ "$iface" = "$PRIVATE_IF" ]; then
            echo "      dhcp4-overrides:" | sudo tee -a $NETPLAN_FILE > /dev/null
            echo "        route-metric: 200" | sudo tee -a $NETPLAN_FILE > /dev/null
        fi
    done

    sudo netplan apply > /dev/null 2>&1
    print_success "Network priorities configured (public: 50, private: 200)"
else
    print_warning "Netplan not found, skipping network configuration"
fi

# Install Docker
print_step "Installing Docker..."
curl -fsSL https://get.docker.com -o get-docker.sh && sudo sh get-docker.sh > /dev/null 2>&1
sudo usermod -aG docker $USER
sudo curl -sL "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose
rm -f get-docker.sh
print_success "Docker installed"

# Install Kata Containers
print_step "Installing Kata Containers..."
wget -q https://github.com/kata-containers/kata-containers/releases/download/3.32.0/kata-static-3.32.0-amd64.tar.zst
unzstd kata-static-3.32.0-amd64.tar.zst
sudo tar xvf kata-static-3.32.0-amd64.tar > /dev/null 2>&1
sudo mv ./opt/kata /opt/
sudo mkdir -p /etc/docker
# Register the 'kata' runtime with the Docker daemon. The "runtimeType" key
# pointing at the containerd-shim-kata-v2 binary matches the official Kata
# "how-to-use-kata-with-docker" guide for the Go runtime (requires Docker v26+
# with Kata >= 3.29.0; this script installs 3.32.0). Once configured, the
# platform launches containers with `docker run --runtime kata ...` whenever the
# admin selects the 'kata' runtime type in Settings.
# Verify after install with:  docker info | grep -i kata
#                             docker run --runtime kata --rm hello-world
sudo tee /etc/docker/daemon.json > /dev/null <<EOF
{
    "runtimes": {
        "kata": {
            "runtimeType": "/opt/kata/bin/containerd-shim-kata-v2"
        }
    }
}
EOF
sudo systemctl reload docker
rm -f kata-static-3.32.0-amd64.tar.zst kata-static-3.32.0-amd64.tar
print_success "Kata Containers installed"

# Install NVIDIA GPU Drivers and MIG Support
print_step "Installing NVIDIA GPU drivers..."
sudo apt install -y nvidia-driver-550 nvidia-utils-550 > /dev/null 2>&1
if [ $? -eq 0 ]; then
    print_success "NVIDIA drivers installed"

    print_step "Enabling MIG mode..."
    sudo nvidia-smi -mig 1 > /dev/null 2>&1
    if [ $? -eq 0 ]; then
        print_success "MIG mode enabled"
    else
        print_warning "MIG mode could not be enabled (GPU may not support MIG)"
    fi

    print_step "Installing NVIDIA Container Toolkit..."
    sudo apt install -y nvidia-container-toolkit > /dev/null 2>&1
    if [ $? -eq 0 ]; then
        print_success "NVIDIA Container Toolkit installed"

        print_step "Verifying Docker GPU access..."
        timeout 30 docker run --rm --gpus '"device=0"' nvidia/cuda:12.3.0-base-ubuntu22.04 nvidia-smi > /dev/null 2>&1
        if [ $? -eq 0 ]; then
            print_success "Docker GPU access verified"
        else
            print_warning "Docker GPU access verification failed (GPU may not be available)"
        fi
    else
        print_warning "NVIDIA Container Toolkit installation failed"
    fi
else
    print_warning "NVIDIA driver installation failed (no GPU or incompatible hardware), skipping GPU setup"
fi

# Configure AWS
print_step "Configuring AWS credentials..."
mkdir -p ~/.aws
cat > ~/.aws/config <<EOF
[profile OVH-SWAUTOMORPH]
region = gra
output = json
EOF

cat > ~/.aws/credentials <<EOF
[OVH-SWAUTOMORPH]
aws_access_key_id = XXX
aws_secret_access_key = YYY
endpoint_url = https://s3.gra.io.cloud.ovh.net/
signature_version = s3v4
EOF

export AWS_DEFAULT_PROFILE=OVH-SWAUTOMORPH
export AWS_ENDPOINT_URL_S3=https://s3.gra.io.cloud.ovh.net/
print_success "AWS credentials configured"

# Clone repository
print_step "Cloning ${PLTF_NAME} repository..."
# Resolve the install destination: "${INSTALL_DIR}/${PLTF_FOLDER}". Strip any
# trailing slash from INSTALL_DIR so the join never produces a double slash.
INSTALL_PARENT="${INSTALL_DIR%/}"
mkdir -p "${INSTALL_PARENT}"
CLONE_DEST="${INSTALL_PARENT}/${PLTF_FOLDER}"
git clone "${REPO_URL}" "${CLONE_DEST}" > /dev/null 2>&1
cd "${CLONE_DEST}"
# Capture an absolute path to the clone so repository-relative steps resolve
# their targets regardless of the current working directory later in the run.
REPO_DIR="$(pwd)"
export REPO_DIR
git submodule add "${SUBMODULE_URL}" shared > /dev/null 2>&1
git submodule update --init --recursive > /dev/null 2>&1
print_success "Repository cloned into ${CLONE_DEST}"

# Persist the collected platform identity into conf/deploy.ini so every
# runtime consumer (config_postgres.py, gunicorn.conf.py, docker-compose.yml,
# scripts/*.sh) resolves the same values. Existing keys are rewritten in
# place; other keys (DOMAIN, VERSION, ...) are preserved.
print_step "Writing platform identity to conf/deploy.ini..."
set_ini_value "conf/deploy.ini" "PLTF_NAME" "${PLTF_NAME}"
set_ini_value "conf/deploy.ini" "PLTF_FOLDER" "${PLTF_FOLDER}"
print_success "Platform identity written to conf/deploy.ini"

# Setup Python environment
print_step "Setting up Python virtual environment..."
python3 -m venv "${REPO_DIR}/.venv"
source "${REPO_DIR}/.venv/bin/activate"
if ! pip install -q -r "${REPO_DIR}/requirements.txt"; then
    print_error "Failed to install Python dependencies from ${REPO_DIR}/requirements.txt"
    exit 1
fi
print_success "Python environment ready"

# Final setup
print_step "Final configuration..."
mkdir -p "${REPO_DIR}/logs"
if ! chmod +x "${REPO_DIR}/setup_modsecurity_config.sh"; then
    print_error "Failed to make ${REPO_DIR}/setup_modsecurity_config.sh executable"
    exit 1
fi
cd ~
mkdir -p deployments
cd deployments
mkdir -p admin
print_success "Configuration complete"

# Hand the clone and user-space home artifacts back to the invoking user when
# the installer ran under sudo. Placed last so every user-space artifact
# (REPO_DIR with shared/.venv/logs/conf/deploy.ini, plus ~/.aws and
# ~/deployments/admin) already exists and a single recursive pass catches them
# all. No-op for non-sudo and bare-root runs.
print_step "Restoring ownership to the invoking user..."
restore_invoking_user_ownership
print_success "Ownership restored"

echo ""
echo -e "${GREEN}[OK] Installation completed successfully!${NC}"
echo ""
print_warning "Don't forget to :"
print_warning "     - PLTF_NAME and PLTF_FOLDER are already set in ./conf/deploy.ini; review DOMAIN and other settings there"
print_warning "     - add ssl certificate in ~/${PLTF_FOLDER}/ssl/fullchain_domain.crt for nginx https"
print_warning "     - add ssl private key in ~/${PLTF_FOLDER}/ssl/privateKey_domain.key for nginx https"
print_warning "     - enter aws_access_key_id & aws_secret_access_key in ~/.aws/credentials for s3 synchronization"
print_warning "     - the default user is admin/password"