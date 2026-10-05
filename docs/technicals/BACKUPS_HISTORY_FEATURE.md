# Backups History Feature

## Overview

The `backups_history` field in the deployments table tracks all database backup operations for each deployed application. This feature provides a complete audit trail of backups with links to S3 storage locations.

## Database Schema

### Column Details

- **Table**: `deployments`
- **Column**: `backups_history`
- **Type**: `JSONB`
- **Default**: `[]` (empty array)
- **Index**: GIN index for efficient JSONB queries

### Backup Entry Structure

Each backup entry in the `backups_history` array contains:

```json
{
  "backup_file": "myapp_1_20260228_143022.sql.gz",
  "s3_location": "s3://bucket-name/myapp/192.168.1.100/backups/myapp_1_20260228_143022.sql.gz",
  "backup_size": "15.2M",
  "backup_date": "2026-02-28 14:30:22",
  "server_ip": "192.168.1.100",
  "created_by": 1
}
```

## Migration

Run the migration script to add the column to existing deployments table:

```bash
psql -U swautomorph -d ai_swautomorph -f migration/add_backups_history_to_deployments.sql
```

Or use the PostgreSQL connection from your application:

```bash
python3 -c "from src.database_postgres import DatabaseManager; \
db = DatabaseManager(); \
db.execute_query(open('migration/add_backups_history_to_deployments.sql').read())"
```

## API Endpoints

### Add Backup Entry

**Endpoint**: `POST /api/deployments/<deployment_id>/backup`

**Authentication**: Required (user must own deployment or be admin)

**Request Body**:
```json
{
  "backup_file": "myapp_1_20260228_143022.sql.gz",
  "s3_location": "s3://bucket/myapp/192.168.1.100/backups/myapp_1_20260228_143022.sql.gz",
  "backup_size": "15.2M",
  "backup_date": "2026-02-28 14:30:22",
  "server_ip": "192.168.1.100"
}
```

**Response**:
```json
{
  "message": "Backup entry added successfully",
  "backup_entry": { ... }
}
```

### Get Backups History

**Endpoint**: `GET /api/deployments/<deployment_id>/backups`

**Authentication**: Required (user must own deployment or be admin)

**Response**:
```json
{
  "backups_history": [
    {
      "backup_file": "myapp_1_20260228_143022.sql.gz",
      "s3_location": "s3://bucket/myapp/192.168.1.100/backups/myapp_1_20260228_143022.sql.gz",
      "backup_size": "15.2M",
      "backup_date": "2026-02-28 14:30:22",
      "server_ip": "192.168.1.100",
      "created_by": 1
    }
  ]
}
```

## CLI Usage

### Add Backup Entry via Script

```bash
python3 scripts/add_backup_to_deployment.py \
  --deployment-id 5 \
  --backup-file "myapp_1_20260228_143022.sql.gz" \
  --s3-location "s3://bucket/myapp/192.168.1.100/backups/myapp_1_20260228_143022.sql.gz" \
  --backup-size "15.2M" \
  --server-ip "192.168.1.100" \
  --user-id 1
```

### Integration with BACKUP_DATABASE Operation

Add this to the end of your backup script (after successful S3 upload):

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

## Dashboard Display

The Deployments Management section in the dashboard displays backups history as a listbox:

- Each backup entry shows: `backup_date (backup_size)`
- Click on an entry to copy the S3 location to clipboard
- Hover over an entry to see the full S3 path in a tooltip

## Example Workflow

1. **Application Backup Operation**:
   ```bash
   # Execute backup (from BACKUP_DATABASE_context.md)
   docker exec $DB_CONTAINER pg_dump -U $DB_USER $DB_NAME | gzip > $BACKUP_FILE
   s3cmd put $BACKUP_FILE $S3_PATH
   ```

2. **Record Backup in History**:
   ```bash
   python3 scripts/add_backup_to_deployment.py \
     --deployment-id 5 \
     --backup-file "myapp_1_20260228_143022.sql.gz" \
     --s3-location "s3://bucket/myapp/192.168.1.100/backups/myapp_1_20260228_143022.sql.gz" \
     --backup-size "15.2M" \
     --server-ip "192.168.1.100" \
     --user-id 1
   ```

3. **View in Dashboard**:
   - Navigate to Deployments Management
   - See backups history in the "Backups History" column
   - Click to copy S3 location for restore operations

## Benefits

1. **Audit Trail**: Complete history of all backup operations
2. **Easy Recovery**: Quick access to backup locations for restore operations
3. **Compliance**: Track backup frequency and retention
4. **Multi-Server Support**: Track backups across different server IPs
5. **User Attribution**: Know who created each backup

## Query Examples

### Get all backups for a deployment

```sql
SELECT backups_history 
FROM deployments 
WHERE id = 5;
```

### Get deployments with recent backups

```sql
SELECT id, application_name, 
       jsonb_array_length(backups_history) as backup_count
FROM deployments 
WHERE backups_history IS NOT NULL 
  AND jsonb_array_length(backups_history) > 0;
```

### Find backups by date range

```sql
SELECT id, application_name, backup_entry
FROM deployments,
     jsonb_array_elements(backups_history) as backup_entry
WHERE (backup_entry->>'backup_date')::timestamp 
      BETWEEN '2026-02-01' AND '2026-02-28';
```

## Security Considerations

- Only authenticated users can add/view backup entries
- Users can only access backups for their own deployments
- Admin users have access to all deployment backups
- S3 credentials should be stored securely (not in backups_history)
- Backup files should use appropriate S3 ACLs (--acl-private)

## Future Enhancements

- Automatic backup retention policy enforcement
- Backup verification and integrity checks
- Scheduled backup reminders
- Backup size trending and analytics
- Integration with restore operations
