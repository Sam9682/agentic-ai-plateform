# Schema Migration Verification

## Overview

This document verifies that all migration scripts are properly reflected in the main PostgreSQL schema file (`scripts/postgresql_schema.sql`) for first-time installations.

## Migration Files Analysis

### ✅ 1. add_backups_history_to_deployments.sql

**Purpose**: Add backups_history JSONB column to deployments table

**Status**: ✅ INCLUDED in main schema

**Schema Location**: Line ~75 in `scripts/postgresql_schema.sql`

```sql
CREATE TABLE deployments (
    ...
    modification_history JSONB DEFAULT '[]'::jsonb,
    backups_history JSONB DEFAULT '[]'::jsonb,  -- ✅ INCLUDED
    ...
);

-- Comments
COMMENT ON COLUMN deployments.backups_history IS 'JSON array containing backup history with links to PostgreSQL database backups in S3';

-- Index
CREATE INDEX idx_deployments_backups_history ON deployments USING GIN (backups_history);
```

**Migration Still Needed**: Only for existing databases (not fresh installs)

---

### ✅ 2. add_user_id_to_services.sql

**Purpose**: Add user_id column to services table with proper constraints

**Status**: ✅ INCLUDED in main schema

**Schema Location**: Line ~172 in `scripts/postgresql_schema.sql`

```sql
CREATE TABLE services (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    image VARCHAR(255) NOT NULL,
    user_id BIGINT NOT NULL,  -- ✅ INCLUDED
    ...
    UNIQUE(name, user_id),  -- ✅ INCLUDED
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE  -- ✅ INCLUDED
);
```

**Migration Still Needed**: Only for existing databases (not fresh installs)

---

### ⚠️ 3. fix_deployment_user_id.sql

**Purpose**: Fix deployment records with incorrect user_id (data correction)

**Status**: ⚠️ DATA MIGRATION ONLY (not schema change)

**Action Required**: This is a data correction script, not a schema change. It should be run manually on existing databases if needed.

**When to Use**: 
- When deployments have incorrect user_id values
- After admin clones applications for other users
- To fix mismatched deployment_path and user_id

**Not Needed For**: Fresh installations (no data to fix)

---

### ✅ 4. fix_instances_fkey.sql

**Purpose**: Fix foreign key constraints for instances table

**Status**: ✅ INCLUDED in main schema

**Schema Location**: Line ~188 in `scripts/postgresql_schema.sql`

```sql
CREATE TABLE instances (
    id BIGSERIAL PRIMARY KEY,
    service_id BIGINT NOT NULL,
    ...
    FOREIGN KEY (server_id) REFERENCES servers (id),  -- ✅ INCLUDED
    FOREIGN KEY (service_id) REFERENCES services (id) ON DELETE CASCADE,  -- ✅ INCLUDED
    UNIQUE(service_id, instance_id)  -- ✅ INCLUDED
);
```

**Note**: The migration script references `service_name` and `user_id` columns that don't exist in the current schema. The schema uses `service_id` instead, which is the correct approach.

**Migration Still Needed**: Only if upgrading from an older schema version

---

### ⚠️ 5. fix_server_capacity.sql

**Purpose**: Set default values for NULL server capacity fields (data correction)

**Status**: ⚠️ DATA MIGRATION ONLY (not schema change)

**Schema Already Has**: NOT NULL constraints are not enforced in schema, but defaults are set

```sql
CREATE TABLE servers (
    ...
    server_capacity_user_max INTEGER NOT NULL,  -- ✅ NOT NULL enforced
    server_capacity_appli_max INTEGER NOT NULL,  -- ✅ NOT NULL enforced
    ...
);
```

**Action Required**: This is a data correction script for existing databases with NULL values.

**Not Needed For**: Fresh installations (NOT NULL constraint prevents NULL values)

---

### ✅ 6. fix_services_constraint.sql

**Purpose**: Fix unique constraint on services table

**Status**: ✅ INCLUDED in main schema

**Schema Location**: Line ~172 in `scripts/postgresql_schema.sql`

```sql
CREATE TABLE services (
    ...
    UNIQUE(name, user_id),  -- ✅ Correct constraint already in place
    ...
);
```

**Migration Still Needed**: Only for existing databases with old constraint

---

## Summary Table

| Migration File | Type | Status in Schema | Fresh Install | Existing DB |
|----------------|------|------------------|---------------|-------------|
| add_backups_history_to_deployments.sql | Schema | ✅ Included | Not needed | Run migration |
| add_user_id_to_services.sql | Schema | ✅ Included | Not needed | Run migration |
| fix_deployment_user_id.sql | Data | ⚠️ Data only | Not needed | Run if needed |
| fix_instances_fkey.sql | Schema | ✅ Included | Not needed | Run if needed |
| fix_server_capacity.sql | Data | ⚠️ Data only | Not needed | Run if needed |
| fix_services_constraint.sql | Schema | ✅ Included | Not needed | Run migration |

## Verification Checklist

### For Fresh Installations (First Time Setup)

✅ All schema changes are included in `scripts/postgresql_schema.sql`
✅ No migration scripts need to be run
✅ Database will be created with correct schema from the start

**Command**:
```bash
psql -U swautomorph -d ai_swautomorph -f scripts/postgresql_schema.sql
```

### For Existing Databases (Upgrades)

Run migrations in this order:

1. **Schema Migrations** (if not already applied):
```bash
# Check if backups_history exists
psql -U swautomorph -d ai_swautomorph -c "\d deployments"

# If not, run migration
psql -U swautomorph -d ai_swautomorph -f migration/add_backups_history_to_deployments.sql

# Check if services has user_id
psql -U swautomorph -d ai_swautomorph -c "\d services"

# If not, run migration
psql -U swautomorph -d ai_swautomorph -f migration/add_user_id_to_services.sql
psql -U swautomorph -d ai_swautomorph -f migration/fix_services_constraint.sql
```

2. **Data Corrections** (if needed):
```bash
# Fix deployment user_id mismatches (if any)
psql -U swautomorph -d ai_swautomorph -f migration/fix_deployment_user_id.sql

# Fix NULL server capacities (if any)
psql -U swautomorph -d ai_swautomorph -f migration/fix_server_capacity.sql
```

## Testing Verification

Run this test to verify schema is correct:

```bash
python3 scripts/test_backups_history.py
```

Or manually verify:

```sql
-- Check deployments table has backups_history
SELECT column_name, data_type 
FROM information_schema.columns 
WHERE table_name = 'deployments' 
AND column_name = 'backups_history';

-- Check services table has user_id
SELECT column_name, data_type 
FROM information_schema.columns 
WHERE table_name = 'services' 
AND column_name = 'user_id';

-- Check unique constraint on services
SELECT constraint_name, constraint_type
FROM information_schema.table_constraints
WHERE table_name = 'services'
AND constraint_type = 'UNIQUE';

-- Check indexes
SELECT indexname 
FROM pg_indexes 
WHERE tablename IN ('deployments', 'services', 'instances')
ORDER BY tablename, indexname;
```

## Conclusion

✅ **Main schema file is UP TO DATE** with all structural changes from migration scripts.

✅ **Fresh installations** will have the correct schema without needing to run migrations.

⚠️ **Existing databases** should run schema migrations if upgrading from older versions.

⚠️ **Data correction scripts** should be run manually only when needed (not part of schema).

## Maintenance Notes

When creating new migration scripts:

1. **Schema Changes**: Always update `scripts/postgresql_schema.sql` to include the change
2. **Data Corrections**: Keep as separate migration scripts (not in main schema)
3. **Documentation**: Update this verification document
4. **Testing**: Add verification to `scripts/test_backups_history.py` or create new test

## Files Reference

- Main Schema: `scripts/postgresql_schema.sql`
- Migrations: `migration/*.sql`
- Tests: `scripts/test_backups_history.py`
- This Document: `docs/SCHEMA_MIGRATION_VERIFICATION.md`
