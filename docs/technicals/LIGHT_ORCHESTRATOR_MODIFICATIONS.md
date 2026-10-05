# App Orchestrator Modifications Summary

## Changes Made

### 1. Database Schema Changes
**File**: `/home/ubuntu/<PLTF_FOLDER>/scripts/postgresql_schema.sql`
- Added `user_id BIGINT NOT NULL` column to `services` table
- Changed unique constraint from `name` to `(name, user_id)` - allows same service name for different users
- Added foreign key constraint linking `user_id` to `users(id)` with CASCADE delete

### 2. Frontend Changes
**File**: `/home/ubuntu/<PLTF_FOLDER>/templates/dashboard.html`

#### Form Modifications:
- **Service Name field**: Changed from text input to combo box (select element)
  - Populated with applications from `user_applications` table for current logged-in user
  - Loads via new API endpoint `/api/orchestrator/user-applications`

- **Docker Image field**: Changed from text input to combo box (select element)
  - Populated with git URLs from `deployments` table
  - Extracts URLs from both `gitea_branch_url` and `modification_history` fields
  - Loads via new API endpoint `/api/orchestrator/git-urls`

#### JavaScript Functions Added:
- `loadUserApplicationsForService()`: Fetches user's assigned applications
- `loadGitUrlsForService()`: Fetches all git URLs from deployments
- Modified `showCreateServiceForm()`: Calls both load functions when form opens

### 3. Backend API Changes
**File**: `/home/ubuntu/<PLTF_FOLDER>/src/routes/orchestrator_routes.py`

#### New Endpoints:
- `GET /api/orchestrator/user-applications`: Returns applications assigned to current user
- `GET /api/orchestrator/git-urls`: Returns unique git URLs from deployments table

#### Modified Endpoints:
- `POST /api/orchestrator/services`: 
  - Now includes `user_id` from session
  - Triggers `deployApp.sh start` via SSH on assigned server
  - Selects server based on capacity
  - Executes deployment in user's application directory

- `GET /api/orchestrator/services`: Filters by user_id
- `GET /api/orchestrator/services/<name>`: Filters by user_id
- `POST /api/orchestrator/services/<name>/scale`: Passes user_id
- `DELETE /api/orchestrator/services/<name>`: Passes user_id
- `POST /api/orchestrator/reconcile`: Handles user_id for all services

### 4. Orchestrator Core Changes
**File**: `/home/ubuntu/<PLTF_FOLDER>/src/orchestrator.py`

#### Modified Methods:
- `create_service()`: Added `user_id` parameter, updates INSERT query
- `scale_service()`: Added `user_id` parameter, updates WHERE clause
- `delete_service()`: Added `user_id` parameter
- `get_service_status()`: Added `user_id` parameter for filtering
- `_reconcile_service()`: Added `user_id` parameter
- `_create_instance()`: Adjusted to handle new service structure with user_id
- `_stop_all_instances()`: Added `user_id` parameter
- `start_reconciliation_loop()`: Fetches and uses user_id for each service

### 5. Migration Script
**File**: `/home/ubuntu/<PLTF_FOLDER>/migration/add_user_id_to_services.sql`
- Adds `user_id` column to existing services table
- Sets default to admin user (id=1) for existing records
- Updates constraints and foreign keys

## Deployment Flow

When a service is created:
1. User selects application name from their assigned applications
2. User selects git URL from available deployments
3. Service record created in database with user_id
4. System selects best available server based on capacity
5. SSH command executed: `ssh ubuntu@<server_ip> 'cd /home/ubuntu/deployments/<username>/<appname> && ./deployApp.sh start'`
6. Application starts on the assigned server
7. Orchestrator tracks instances and manages lifecycle

## Migration Steps

To apply these changes to an existing installation:

```bash
# 1. Run the migration script
psql -U swautomorph -d ai_swautomorph -f /home/ubuntu/<PLTF_FOLDER>/migration/add_user_id_to_services.sql

# 2. Restart the application
sudo systemctl restart <PLTF_FOLDER>
# OR
cd /home/ubuntu/<PLTF_FOLDER> && ./deployControlPlan.sh restart
```

## Key Features

1. **User Isolation**: Each user can create services with same names without conflicts
2. **Application Integration**: Services linked to user's assigned applications
3. **Git URL Management**: Reuses existing git URLs from deployments
4. **Automated Deployment**: Triggers deployApp.sh automatically on service creation
5. **Multi-Server Support**: Deploys to appropriate server based on capacity
6. **SSH Execution**: Remote deployment via SSH to target servers
