#!/bin/bash

# Reset the platform PostgreSQL database
# This script drops and recreates the database with initial schema

echo "Resetting the platform PostgreSQL database..."

# Set database connection parameters
DB_NAME="ai_swautomorph"
DB_USER="swautomorph"
DB_PASSWORD="swautomorph_password"
DB_HOST="localhost"
DB_PORT="5432"

# Export password for psql
export PGPASSWORD=$DB_PASSWORD

# Drop existing database
echo "Dropping existing database..."
dropdb -h $DB_HOST -p $DB_PORT -U $DB_USER $DB_NAME 2>/dev/null || true

# Create new database
echo "Creating new database..."
createdb -h $DB_HOST -p $DB_PORT -U $DB_USER $DB_NAME

# Apply schema
echo "Applying database schema..."
psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME -f scripts/postgresql_schema.sql

# Initialize database with default data
echo "Initializing database with default data..."
python3 -c "
import sys
sys.path.insert(0, '.')
from src.database_postgres import init_db
init_db()
print('Database initialized successfully')
"

echo "Database reset complete!"