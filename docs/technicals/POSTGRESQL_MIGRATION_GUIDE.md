# 🐘 PostgreSQL Migration Guide / Guide de Migration PostgreSQL

## English

<div class="center">
🚀 **SQLite to PostgreSQL Migration for AI-SwAutoMorph** 📊
</div>

### 📋 Table of Contents
- [🌟 Overview](#overview)
- [🎯 Migration Benefits](#migration-benefits)
- [📋 Prerequisites](#prerequisites)
- [🔧 Migration Process](#migration-process)
- [⚙️ Configuration](#configuration)
- [🔍 Verification](#verification)
- [🛠️ Troubleshooting](#troubleshooting)
- [🔄 Rollback Procedure](#rollback-procedure)

### 🌟 Overview

AI-SwAutoMorph has migrated from SQLite to PostgreSQL to provide enterprise-grade database performance, scalability, and reliability. This guide covers the complete migration process, configuration, and verification steps.

#### 🎯 Migration Benefits

**🚀 Performance Improvements**:
- **Connection Pooling**: ThreadedConnectionPool with 2-20 configurable connections
- **ACID Transactions**: Full transaction support with proper isolation levels
- **Concurrent Access**: Better handling of multiple simultaneous connections
- **Query Optimization**: Advanced query planner and execution engine

**📊 Advanced Data Types**:
- **INET**: Native IP address validation and storage
- **BIGSERIAL**: 64-bit auto-incrementing primary keys
- **TIMESTAMP WITH TIME ZONE**: Timezone-aware date/time handling
- **DECIMAL**: Precise financial calculations without floating-point errors
- **BOOLEAN**: Native boolean data type (not integer-based)

**🔧 Enterprise Features**:
- **Database Triggers**: Automatic timestamp management
- **Advanced Indexing**: Performance-optimized indexes
- **SSL Support**: Secure database connections
- **Backup & Recovery**: pg_dump/pg_restore tools
- **Monitoring**: Built-in statistics and health monitoring

### 📋 Prerequisites

#### 🐘 PostgreSQL Installation
```bash
# Ubuntu/Debian
sudo apt update
sudo apt install postgresql postgresql-contrib python3-psycopg2

# CentOS/RHEL
sudo yum install postgresql-server postgresql-contrib python3-psycopg2

# macOS
brew install postgresql
```

#### 🔧 Database Setup
```bash
# Start PostgreSQL service
sudo systemctl start postgresql
sudo systemctl enable postgresql

# Create database and user
sudo -u postgres psql
CREATE DATABASE ai_swautomorph;
CREATE USER swautomorph WITH PASSWORD 'swautomorph_password';
GRANT ALL PRIVILEGES ON DATABASE ai_swautomorph TO swautomorph;
ALTER USER swautomorph CREATEDB;
\q
```

#### 🐍 Python Dependencies
```bash
# Install required packages
pip install psycopg2-binary

# Or from requirements.txt
pip install -r requirements.txt
```

### 🔧 Migration Process

#### 1️⃣ Pre-Migration Backup
```bash
# Create backup of existing SQLite database
cp softfluid/db/ai_swautomorph.db softfluid/db/ai_swautomorph.db.backup.$(date +%Y%m%d_%H%M%S)

# Verify backup integrity
sqlite3 softfluid/db/ai_swautomorph.db.backup.* "PRAGMA integrity_check;"
```

#### 2️⃣ Environment Configuration
```bash
# Set PostgreSQL connection parameters
export POSTGRES_HOST="localhost"
export POSTGRES_PORT="5432"
export POSTGRES_DB="ai_swautomorph"
export POSTGRES_USER="swautomorph"
export POSTGRES_PASSWORD="swautomorph_password"
export POSTGRES_MIN_CONN="2"
export POSTGRES_MAX_CONN="20"
export POSTGRES_SSLMODE="prefer"
export POSTGRES_TIMEOUT="10"
```

#### 3️⃣ Schema Creation
```bash
# Create PostgreSQL schema
psql -h localhost -U swautomorph -d ai_swautomorph -f ./scripts/postgresql_schema.sql
```

#### 4️⃣ Data Migration
```bash
# Run the automated migration script
python3 ./migration/migrate_sqlite_to_postgres.py
```

#### 5️⃣ Application Configuration
```bash
# Update application to use PostgreSQL
# The application will automatically detect PostgreSQL configuration
# and use database_postgres.py instead of database.py
```

### ⚙️ Configuration

#### 🔧 PostgreSQL Configuration File
Create or update `src/config_postgres.py`:

```python
def get_database_config():
    """Get PostgreSQL database configuration"""
    return {
        'host': os.environ.get('POSTGRES_HOST', 'localhost'),
        'port': int(os.environ.get('POSTGRES_PORT', 5432)),
        'database': os.environ.get('POSTGRES_DB', 'ai_swautomorph'),
        'user': os.environ.get('POSTGRES_USER', 'swautomorph'),
        'password': os.environ.get('POSTGRES_PASSWORD', 'swautomorph_password'),
        'min_connections': int(os.environ.get('POSTGRES_MIN_CONN', 2)),
        'max_connections': int(os.environ.get('POSTGRES_MAX_CONN', 20)),
        'sslmode': os.environ.get('POSTGRES_SSLMODE', 'prefer'),
        'connect_timeout': int(os.environ.get('POSTGRES_TIMEOUT', 10))
    }
```

#### 🐳 Docker Configuration
Update `docker-compose.yml` to include PostgreSQL:

```yaml
version: '3.8'
services:
  postgres:
    image: postgres:15
    environment:
      POSTGRES_DB: ai_swautomorph
      POSTGRES_USER: swautomorph
      POSTGRES_PASSWORD: swautomorph_password
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./scripts/postgresql_schema.sql:/docker-entrypoint-initdb.d/init.sql
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U swautomorph"]
      interval: 30s
      timeout: 10s
      retries: 3

  app:
    build: .
    depends_on:
      - postgres
    environment:
      POSTGRES_HOST: postgres
      POSTGRES_PORT: 5432
      POSTGRES_DB: ai_swautomorph
      POSTGRES_USER: swautomorph
      POSTGRES_PASSWORD: swautomorph_password

volumes:
  postgres_data:
```

### 🔍 Verification

#### ✅ Migration Verification Script
```python
#!/usr/bin/env python3
"""Verify PostgreSQL migration success"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from database_postgres import db_manager

def verify_migration():
    """Verify migration was successful"""
    print("🔍 Verifying PostgreSQL migration...")
    
    # Test connection
    try:
        with db_manager.get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT version()")
                version = cursor.fetchone()[0]
                print(f"✅ PostgreSQL connection successful: {version}")
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return False
    
    # Verify tables exist
    tables = [
        'users', 'applications', 'user_applications', 'deployments',
        'servers', 'auth_tokens', 'application_costs', 'billing_activities',
        'users_logs', 'payment_modes', 'invoicing'
    ]
    
    for table in tables:
        try:
            count = db_manager.execute_query(f"SELECT COUNT(*) FROM {table}", fetch_one=True)
            print(f"✅ Table {table}: {count[0]} records")
        except Exception as e:
            print(f"❌ Table {table} verification failed: {e}")
            return False
    
    # Test data integrity
    try:
        # Check user count matches
        user_count = db_manager.execute_query("SELECT COUNT(*) FROM users", fetch_one=True)[0]
        app_count = db_manager.execute_query("SELECT COUNT(*) FROM applications", fetch_one=True)[0]
        
        print(f"✅ Data integrity check passed: {user_count} users, {app_count} applications")
        
    except Exception as e:
        print(f"❌ Data integrity check failed: {e}")
        return False
    
    print("🎉 Migration verification completed successfully!")
    return True

if __name__ == "__main__":
    success = verify_migration()
    sys.exit(0 if success else 1)
```

#### 🏥 Health Check
```bash
# Run health check
python3 ./scripts/controller_cli.py db-health

# Check connection pool status
python3 -c "
import sys, os
sys.path.insert(0, 'src')
from database_postgres import db_manager
print('Connection pool initialized:', db_manager._pool is not None)
"
```

### 🛠️ Troubleshooting

#### 🔧 Common Issues

**Connection Refused**:
```bash
# Check PostgreSQL service status
sudo systemctl status postgresql

# Check if PostgreSQL is listening
sudo netstat -tulpn | grep 5432

# Check PostgreSQL logs
sudo tail -f /var/log/postgresql/postgresql-*.log
```

**Authentication Failed**:
```bash
# Check pg_hba.conf configuration
sudo nano /etc/postgresql/*/main/pg_hba.conf

# Add or modify line for local connections:
# local   all             all                                     md5
# host    all             all             127.0.0.1/32            md5

# Restart PostgreSQL
sudo systemctl restart postgresql
```

**Migration Script Errors**:
```bash
# Check Python dependencies
pip list | grep psycopg2

# Verify database exists and is accessible
psql -h localhost -U swautomorph -d ai_swautomorph -c "SELECT 1;"

# Run migration with verbose output
python3 ./migration/migrate_sqlite_to_postgres.py 2>&1 | tee migration.log
```

**Performance Issues**:
```bash
# Check connection pool configuration
export POSTGRES_MAX_CONN="50"  # Increase if needed

# Monitor active connections
psql -h localhost -U swautomorph -d ai_swautomorph -c "
SELECT count(*) as active_connections 
FROM pg_stat_activity 
WHERE state = 'active';"
```

### 🔄 Rollback Procedure

#### 🔙 Emergency Rollback
If migration fails or issues arise, you can rollback to SQLite:

```bash
# 1. Stop the application
./deployControlPlan.sh stop

# 2. Restore SQLite backup
cp softfluid/db/ai_swautomorph.db.backup.* softfluid/db/ai_swautomorph.db

# 3. Remove PostgreSQL environment variables
unset POSTGRES_HOST POSTGRES_PORT POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD

# 4. Restart application (will use SQLite)
./deployControlPlan.sh start
```

#### 🔄 Gradual Rollback
For production environments, implement gradual rollback:

```bash
# 1. Configure application to use SQLite temporarily
export USE_SQLITE=true

# 2. Verify SQLite database integrity
sqlite3 softfluid/db/ai_swautomorph.db "PRAGMA integrity_check;"

# 3. Test application functionality
curl -s https://www.swautomorph.com/api/auth/status

# 4. If successful, remove PostgreSQL configuration
# If issues persist, investigate and fix before re-attempting migration
```

---

## Français

<div class="center">
🚀 **Migration SQLite vers PostgreSQL pour AI-SwAutoMorph** 📊
</div>

### 📋 Table des Matières
- [🌟 Aperçu](#aperçu-fr)
- [🎯 Avantages de la Migration](#avantages-de-la-migration)
- [📋 Prérequis](#prérequis-fr)
- [🔧 Processus de Migration](#processus-de-migration)
- [⚙️ Configuration](#configuration-fr)
- [🔍 Vérification](#vérification-fr)
- [🛠️ Dépannage](#dépannage)
- [🔄 Procédure de Retour](#procédure-de-retour)

### 🌟 Aperçu {#aperçu-fr}

AI-SwAutoMorph a migré de SQLite vers PostgreSQL pour fournir des performances de base de données de niveau entreprise, une évolutivité et une fiabilité. Ce guide couvre le processus complet de migration, la configuration et les étapes de vérification.

#### 🎯 Avantages de la Migration

**🚀 Améliorations de Performance** :
- **Mise en Pool de Connexions** : ThreadedConnectionPool avec 2-20 connexions configurables
- **Transactions ACID** : Support complet des transactions avec niveaux d'isolation appropriés
- **Accès Concurrent** : Meilleure gestion des connexions simultanées multiples
- **Optimisation de Requêtes** : Planificateur et moteur d'exécution de requêtes avancés

**📊 Types de Données Avancés** :
- **INET** : Validation et stockage natifs d'adresses IP
- **BIGSERIAL** : Clés primaires auto-incrémentées 64-bit
- **TIMESTAMP WITH TIME ZONE** : Gestion date/heure avec fuseau horaire
- **DECIMAL** : Calculs financiers précis sans erreurs de virgule flottante
- **BOOLEAN** : Type de données booléen natif (non basé sur entier)

**🔧 Fonctionnalités Entreprise** :
- **Triggers de Base de Données** : Gestion automatique des timestamps
- **Indexation Avancée** : Index optimisés pour performance
- **Support SSL** : Connexions de base de données sécurisées
- **Sauvegarde et Récupération** : Outils pg_dump/pg_restore
- **Surveillance** : Statistiques intégrées et surveillance de santé

### 📋 Prérequis {#prérequis-fr}

La migration nécessite l'installation de PostgreSQL, la configuration de la base de données et des utilisateurs, et l'installation des dépendances Python requises.

### 🔧 Processus de Migration

Le processus inclut la sauvegarde pré-migration, la configuration d'environnement, la création de schéma, la migration de données, et la configuration d'application.

### ⚙️ Configuration {#configuration-fr}

La configuration inclut les paramètres de connexion PostgreSQL, la configuration Docker, et les variables d'environnement pour la mise en pool de connexions.

### 🔍 Vérification {#vérification-fr}

La vérification inclut des scripts de test de connexion, vérification d'intégrité des données, et contrôles de santé pour s'assurer que la migration s'est déroulée avec succès.

### 🛠️ Dépannage

Le dépannage couvre les problèmes courants comme les refus de connexion, les échecs d'authentification, les erreurs de script de migration, et les problèmes de performance.

### 🔄 Procédure de Retour

Les procédures de retour incluent le retour d'urgence vers SQLite et le retour graduel pour les environnements de production, avec des étapes de vérification et de test.