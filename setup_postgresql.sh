#!/bin/bash
# PostgreSQL Setup Script for AI-SwAutoMorph
# This script sets up PostgreSQL and migrates from SQLite

set -e

echo "🐘 Setting up PostgreSQL for AI-SwAutoMorph..."

# Check if PostgreSQL is installed
if ! command -v psql &> /dev/null; then
    echo "❌ PostgreSQL is not installed. Please install it first:"
    echo "   sudo apt update && sudo apt install -y postgresql postgresql-contrib python3-psycopg2"
    exit 1
fi

# Start PostgreSQL service
echo "🔄 Starting PostgreSQL service..."
sudo systemctl start postgresql
sudo systemctl enable postgresql

# Create database user and database
echo "👤 Creating PostgreSQL user and database..."
sudo -u postgres psql -c "CREATE USER swautomorph WITH PASSWORD 'swautomorph_secure_password_2026' CREATEDB;" 2>/dev/null || echo "   User already exists"
sudo -u postgres psql -c "ALTER USER swautomorph CREATEDB;" 2>/dev/null  # Ensure CREATEDB permission for existing users
sudo -u postgres psql -c "CREATE DATABASE ai_swautomorph OWNER swautomorph;" 2>/dev/null || echo "   Database already exists"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE ai_swautomorph TO swautomorph;"

# Set environment variables
echo "🔧 Setting up environment variables..."
export USE_POSTGRES=true
export POSTGRES_HOST=localhost
export POSTGRES_DB=ai_swautomorph
export POSTGRES_USER=swautomorph
export POSTGRES_PASSWORD=swautomorph_secure_password_2026

# Initialize database
echo "💾 Initializing PostgreSQL database..."
python3 ./scripts/controller_cli.py init-db

# Verify setup
echo "✅ Verifying PostgreSQL setup..."
python3 ./scripts/controller_cli.py status --show-env

echo ""
echo "🎉 PostgreSQL setup complete!"
echo ""
echo "To use PostgreSQL with the application, set these environment variables:"
echo "export USE_POSTGRES=true"
echo "export POSTGRES_PASSWORD=swautomorph_secure_password_2026"
echo ""
echo "You can now start the application with PostgreSQL support."