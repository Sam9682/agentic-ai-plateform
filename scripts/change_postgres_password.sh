#!/bin/bash
#
# change_postgres_password.sh
#
# Prompts for a new PostgreSQL password, applies it to the running
# PostgreSQL server, and updates POSTGRES_PASSWORD in the .env file
# located one directory above this script (../.env).
#
# Usage:
#   cd scripts
#   ./change_postgres_password.sh
#
set -euo pipefail

# --- Resolve paths -----------------------------------------------------------
# .env is expected one level up from this script (../.env), per requirement.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$(cd "${SCRIPT_DIR}/.." && pwd)/.env"

if [[ ! -f "${ENV_FILE}" ]]; then
    echo "ERROR: .env file not found at: ${ENV_FILE}" >&2
    exit 1
fi

# --- Load current connection settings from .env ------------------------------
# Read values without executing the file (avoids side effects).
get_env() {
    local key="$1"
    local line
    line="$(grep -E "^${key}=" "${ENV_FILE}" | tail -n 1 || true)"
    echo "${line#*=}"
}

DB_NAME="$(get_env POSTGRES_DB)"
DB_USER="$(get_env POSTGRES_USER)"
DB_HOST="$(get_env POSTGRES_HOST)"
DB_PORT="$(get_env POSTGRES_PORT)"
OLD_PASSWORD="$(get_env POSTGRES_PASSWORD)"

DB_NAME="${DB_NAME:-ai_swautomorph}"
DB_USER="${DB_USER:-swautomorph}"
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"

echo "Changing PostgreSQL password for user '${DB_USER}' on ${DB_HOST}:${DB_PORT}"
echo

# --- Prompt for the new password (hidden, with confirmation) -----------------
read -r -s -p "Enter new PostgreSQL password: " NEW_PASSWORD
echo
read -r -s -p "Confirm new PostgreSQL password: " CONFIRM_PASSWORD
echo

if [[ -z "${NEW_PASSWORD}" ]]; then
    echo "ERROR: Password cannot be empty." >&2
    exit 1
fi

if [[ "${NEW_PASSWORD}" != "${CONFIRM_PASSWORD}" ]]; then
    echo "ERROR: Passwords do not match." >&2
    exit 1
fi

# --- Apply the password change to PostgreSQL ---------------------------------
# Build the ALTER USER statement. The password literal is single-quoted;
# escape any single quotes in the password to keep the SQL valid.
ESCAPED_PASSWORD="${NEW_PASSWORD//\'/\'\'}"
ALTER_SQL="ALTER USER \"${DB_USER}\" WITH PASSWORD '${ESCAPED_PASSWORD}';"

# Detect a running PostgreSQL docker container for this platform, if any.
PG_CONTAINER="$(docker ps --filter "name=postgres" --format '{{.Names}}' 2>/dev/null \
    | grep -E "agentic-ai-plateform|${PLTF_FOLDER:-agentic-ai-plateform}" \
    | head -n 1 || true)"

applied=false

if [[ -n "${PG_CONTAINER}" ]]; then
    echo "Applying change inside docker container '${PG_CONTAINER}'..."
    if docker exec -e PGPASSWORD="${OLD_PASSWORD}" -i "${PG_CONTAINER}" \
        psql -U "${DB_USER}" -d "${DB_NAME}" -v ON_ERROR_STOP=1 -c "${ALTER_SQL}"; then
        applied=true
    fi
fi

if [[ "${applied}" != true ]] && command -v psql >/dev/null 2>&1; then
    echo "Applying change via local psql to ${DB_HOST}:${DB_PORT}..."
    if PGPASSWORD="${OLD_PASSWORD}" psql -h "${DB_HOST}" -p "${DB_PORT}" \
        -U "${DB_USER}" -d "${DB_NAME}" -v ON_ERROR_STOP=1 -c "${ALTER_SQL}"; then
        applied=true
    fi
fi

if [[ "${applied}" != true ]]; then
    echo "ERROR: Could not apply the password change to the PostgreSQL server." >&2
    echo "       No reachable postgres container or local psql connection worked." >&2
    echo "       The .env file was NOT modified." >&2
    exit 1
fi

echo "PostgreSQL password updated on the server."

# --- Update POSTGRES_PASSWORD in .env ----------------------------------------
# Back up the .env, then rewrite the POSTGRES_PASSWORD line (or append it).
BACKUP_FILE="${ENV_FILE}.bak.$(date +%Y%m%d%H%M%S)"
cp "${ENV_FILE}" "${BACKUP_FILE}"

TMP_FILE="$(mktemp)"
if grep -qE '^POSTGRES_PASSWORD=' "${ENV_FILE}"; then
    # Replace the existing line. Use awk to avoid regex issues with special
    # characters in the password value.
    awk -v newval="${NEW_PASSWORD}" '
        /^POSTGRES_PASSWORD=/ { print "POSTGRES_PASSWORD=" newval; next }
        { print }
    ' "${ENV_FILE}" > "${TMP_FILE}"
else
    cp "${ENV_FILE}" "${TMP_FILE}"
    printf 'POSTGRES_PASSWORD=%s\n' "${NEW_PASSWORD}" >> "${TMP_FILE}"
fi

# Preserve original permissions.
chmod --reference="${ENV_FILE}" "${TMP_FILE}" 2>/dev/null || true
mv "${TMP_FILE}" "${ENV_FILE}"

echo "Updated POSTGRES_PASSWORD in ${ENV_FILE}"
echo "Backup saved to ${BACKUP_FILE}"
echo
echo "Done. If services are running, restart them to pick up the new password:"
echo "  docker compose up -d"
