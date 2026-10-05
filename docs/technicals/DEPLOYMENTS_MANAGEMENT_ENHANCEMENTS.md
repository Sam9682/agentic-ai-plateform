# Deployments Management Enhancements

## Summary

Enhanced the Deployments Management section with EDIT/DELETE actions and added a `backups_history` field to track database backup operations.

## Changes Made

### 1. Database Schema Changes

**File**: `migration/add_backups_history_to_deployments.sql`

- Added `backups_history` JSONB column to `deployments` table
- Default value: empty array `[]`
- Created GIN index for efficient JSONB queries
- Added column documentation comment

**Migration Command**:
```bash
psql -U swautomorph -d ai_swautomorph -f migration/add_backups_history_to_deployments.sql
```

### 2. Backend API Enhancements

**File**: `src/routes/api_routes.py`

#### Updated Endpoints:

1. **GET /api/deployments/all** - Added `backups_history` to response
   - Now returns backups_history field for each deployment

2. **PUT /api/deployments/<deployment_id>** - New endpoint for updating deployments
   - Admin only
   - Update status, deployment_path, git_url, server_id, swautomorph_url
   - Automatically updates `updated_at` timestamp

3. **DELETE /api/deployments/<deployment_id>** - New endpoint for deleting deployments
   - Admin only
   - Permanently removes deployment record

4. **POST /api/deployments/<deployment_id>/backup** - New endpoint for adding backup entries
   - Authenticated users (owner or admin)
   - Adds backup entry to backups_history array
   - Records: backup_file, s3_location, backup_size, backup_date, server_ip, created_by

5. **GET /api/deployments/<deployment_id>/backups** - New endpoint for retrieving backups
   - Authenticated users (owner or admin)
   - Returns complete backups_history array

### 3. Frontend Dashboard Changes

**File**: `templates/dashboard.html`

#### Deployments Table Updates:

1. **Added "Backups History" Column**
   - Displays backups as a listbox (similar to Modification History)
   - Shows: `backup_date (backup_size)`
   - Click to copy S3 location to clipboard
   - Tooltip shows full S3 path

2. **Enhanced Actions Column**
   - ✏️ **Edit Button**: Opens prompts to edit deployment fields
   - 🗑️ **Delete Button**: Confirms and deletes deployment
   - 🔄 **Update Nginx Button**: Updates nginx configuration (existing)

#### New JavaScript Functions:

1. **editDeployment()** - Edit deployment details
   - Prompts for: status, deployment_path, git_url, server_id, swautomorph_url
   - Calls PUT /api/deployments/<id>
   - Refreshes table on success

2. **deleteDeployment()** - Delete deployment
   - Confirmation dialog
   - Calls DELETE /api/deployments/<id>
   - Refreshes table on success

### 4. Helper Scripts

**File**: `scripts/add_backup_to_deployment.py`

CLI tool to add backup entries to deployments:

```bash
python3 scripts/add_backup_to_deployment.py \
  --deployment-id 5 \
  --backup-file "myapp_1_20260228_143022.sql.gz" \
  --s3-location "s3://bucket/myapp/192.168.1.100/backups/myapp_1_20260228_143022.sql.gz" \
  --backup-size "15.2M" \
  --server-ip "192.168.1.100" \
  --user-id 1
```

### 5. Documentation

**Files Created**:
- `docs/BACKUPS_HISTORY_FEATURE.md` - Complete feature documentation
- `docs/DEPLOYMENTS_MANAGEMENT_ENHANCEMENTS.md` - This file

## Integration with BACKUP_DATABASE Operation

Add to the end of backup scripts (after successful S3 upload):

```bash
# Get deployment ID
DEPLOYMENT_ID=$(psql -U $DB_USER -d ai_swautomorph -t -c \
  "SELECT id FROM deployments WHERE user_id = $USER_ID AND application_name = '$NAME_OF_APPLICATION' ORDER BY updated_at DESC LIMIT 1")

# Add backup entry
python3 scripts/add_backup_to_deployment.py \
  --deployment-id $DEPLOYMENT_ID \
  --backup-file "$(basename $BACKUP_FILE)" \
  --s3-location "${S3_PATH}$(basename $BACKUP_FILE)" \
  --backup-size "$(du -h $BACKUP_FILE | cut -f1)" \
  --server-ip "$SERVER_IP" \
  --user-id "$USER_ID"
```

## Testing

### 1. Run Migration

```bash
psql -U swautomorph -d ai_swautomorph -f migration/add_backups_history_to_deployments.sql
```

### 2. Restart Application

```bash
./deployControlPlan.sh restart
```

### 3. Test in Dashboard

1. Login as admin
2. Navigate to "Deployments Management"
3. Verify new "Backups History" column appears
4. Test Edit button (✏️) - modify deployment details
5. Test Delete button (🗑️) - delete a test deployment
6. Verify Update Nginx button (🔄) still works

### 4. Test API Endpoints

```bash
# Add backup entry
curl -X POST http://localhost:5000/api/deployments/5/backup \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  -d '{
    "backup_file": "test_backup.sql.gz",
    "s3_location": "s3://bucket/test/backups/test_backup.sql.gz",
    "backup_size": "10M",
    "server_ip": "192.168.1.100"
  }'

# Get backups history
curl -X GET http://localhost:5000/api/deployments/5/backups \
  -b cookies.txt

# Update deployment
curl -X PUT http://localhost:5000/api/deployments/5 \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  -d '{"status": "active"}'

# Delete deployment
curl -X DELETE http://localhost:5000/api/deployments/5 \
  -b cookies.txt
```

### 5. Test CLI Script

```bash
python3 scripts/add_backup_to_deployment.py \
  --deployment-id 5 \
  --backup-file "test_backup.sql.gz" \
  --s3-location "s3://bucket/test/backups/test_backup.sql.gz" \
  --backup-size "10M" \
  --server-ip "192.168.1.100" \
  --user-id 1
```

## Security Features

- All endpoints require authentication
- Edit/Delete operations restricted to admin users
- Backup operations restricted to deployment owner or admin
- Input validation on all API endpoints
- Confirmation dialogs for destructive operations (delete)

## UI/UX Improvements

- Compact action buttons with emoji icons
- Tooltips on hover for better usability
- Click-to-copy functionality for S3 locations
- Listbox display for easy backup browsing
- Inline editing with prompts (simple and fast)
- Automatic table refresh after operations

## Database Performance

- GIN index on `backups_history` for fast JSONB queries
- Efficient JSONB append operations using PostgreSQL operators
- Minimal overhead for backup tracking

## Future Enhancements

1. Modal dialog for editing (instead of prompts)
2. Backup restore functionality from dashboard
3. Backup verification and integrity checks
4. Automated backup retention policies
5. Backup size trending and analytics
6. Email notifications for backup operations
7. Backup scheduling from dashboard

## Files Modified

1. `migration/add_backups_history_to_deployments.sql` (new)
2. `src/routes/api_routes.py` (modified)
3. `templates/dashboard.html` (modified)
4. `scripts/add_backup_to_deployment.py` (new)
5. `docs/BACKUPS_HISTORY_FEATURE.md` (new)
6. `docs/DEPLOYMENTS_MANAGEMENT_ENHANCEMENTS.md` (new)

## Rollback Plan

If issues occur, rollback using:

```sql
-- Remove backups_history column
ALTER TABLE deployments DROP COLUMN IF EXISTS backups_history;

-- Remove index
DROP INDEX IF EXISTS idx_deployments_backups_history;
```

Then revert code changes:
```bash
git checkout HEAD -- src/routes/api_routes.py templates/dashboard.html
```
