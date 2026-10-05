# Quick Reference: Deployments Management

## Installation (One-Time Setup)

```bash
# 1. Apply migration
psql -U swautomorph -d ai_swautomorph -f migration/add_backups_history_to_deployments.sql

# 2. Restart application
./deployControlPlan.sh restart

# 3. Verify
python3 scripts/test_backups_history.py
```

## Dashboard Usage

### Access Deployments Management
1. Login as admin
2. Click "Deployments Management" tab
3. Use filters to find specific deployments

### Edit Deployment
1. Click ✏️ button in Actions column
2. Enter new values in prompts (or press Cancel to skip)
3. Deployment updates automatically

### Delete Deployment
1. Click 🗑️ button in Actions column
2. Confirm deletion
3. Deployment removed permanently

### View Backups
1. Find deployment in table
2. Look at "Backups History" column
3. Click any backup to copy S3 URL to clipboard
4. Hover to see full S3 path

## CLI Commands

### Add Backup Entry
```bash
python3 scripts/add_backup_to_deployment.py \
  --deployment-id 5 \
  --backup-file "myapp_backup.sql.gz" \
  --s3-location "s3://bucket/myapp/192.168.1.100/backups/myapp_backup.sql.gz" \
  --backup-size "15.2M" \
  --server-ip "192.168.1.100" \
  --user-id 1
```

### Test Installation
```bash
python3 scripts/test_backups_history.py
```

## API Endpoints

### Get All Deployments (Admin)
```bash
curl -X GET http://localhost:5000/api/deployments/all -b cookies.txt
```

### Update Deployment (Admin)
```bash
curl -X PUT http://localhost:5000/api/deployments/5 \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  -d '{"status": "active"}'
```

### Delete Deployment (Admin)
```bash
curl -X DELETE http://localhost:5000/api/deployments/5 -b cookies.txt
```

### Add Backup Entry
```bash
curl -X POST http://localhost:5000/api/deployments/5/backup \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  -d '{
    "backup_file": "backup.sql.gz",
    "s3_location": "s3://bucket/app/ip/backups/backup.sql.gz",
    "backup_size": "10M",
    "server_ip": "192.168.1.100"
  }'
```

### Get Backups History
```bash
curl -X GET http://localhost:5000/api/deployments/5/backups -b cookies.txt
```

## Backup Integration

Add to end of backup scripts (after S3 upload):

```bash
# Get deployment ID
DEPLOYMENT_ID=$(docker exec postgres psql -U $DB_USER -d ai_swautomorph -t -c \
  "SELECT id FROM deployments WHERE user_id = $USER_ID AND application_name = '$NAME_OF_APPLICATION' ORDER BY updated_at DESC LIMIT 1" | xargs)

# Record backup
python3 /home/ubuntu/<PLTF_FOLDER>/scripts/add_backup_to_deployment.py \
  --deployment-id $DEPLOYMENT_ID \
  --backup-file "$(basename $BACKUP_FILE)" \
  --s3-location "${S3_PATH}$(basename $BACKUP_FILE)" \
  --backup-size "$(du -h $BACKUP_FILE | cut -f1)" \
  --server-ip "$SERVER_IP" \
  --user-id "$USER_ID"
```

## Troubleshooting

### Column doesn't exist
```bash
# Run migration
psql -U swautomorph -d ai_swautomorph -f migration/add_backups_history_to_deployments.sql
```

### Buttons not working
```bash
# Check browser console for errors
# Restart application
./deployControlPlan.sh restart
```

### API returns 401
```bash
# Login first to get session cookie
curl -X POST http://localhost:5000/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"your_password"}' \
  -c cookies.txt
```

### Check logs
```bash
tail -f logs/api_routes.log
```

## Backup Entry Format

```json
{
  "backup_file": "myapp_1_20260228_143022.sql.gz",
  "s3_location": "s3://bucket/myapp/192.168.1.100/backups/myapp_1_20260228_143022.sql.gz",
  "backup_size": "15.2M",
  "backup_date": "2026-02-28 14:30:22",
  "server_ip": "192.168.1.100",
  "created_by": 1
}
```

## SQL Queries

### Get deployments with backups
```sql
SELECT id, application_name, 
       jsonb_array_length(backups_history) as backup_count
FROM deployments 
WHERE backups_history IS NOT NULL 
  AND jsonb_array_length(backups_history) > 0;
```

### Get all backups for a deployment
```sql
SELECT backups_history 
FROM deployments 
WHERE id = 5;
```

### Find backups by date
```sql
SELECT id, application_name, backup_entry
FROM deployments,
     jsonb_array_elements(backups_history) as backup_entry
WHERE (backup_entry->>'backup_date')::timestamp 
      BETWEEN '2026-02-01' AND '2026-02-28';
```

## Permissions

| Operation | Required Role |
|-----------|---------------|
| View deployments | Admin |
| Edit deployment | Admin |
| Delete deployment | Admin |
| Add backup entry | Owner or Admin |
| View backups | Owner or Admin |

## Files Location

| File | Path |
|------|------|
| Migration | `migration/add_backups_history_to_deployments.sql` |
| CLI Tool | `scripts/add_backup_to_deployment.py` |
| Test Script | `scripts/test_backups_history.py` |
| API Routes | `src/routes/api_routes.py` |
| Dashboard | `templates/dashboard.html` |
| Backup Context | `shared/BACKUP_DATABASE_context.md` |

## Support Resources

- Full Documentation: `docs/BACKUPS_HISTORY_FEATURE.md`
- Implementation Details: `docs/DEPLOYMENTS_MANAGEMENT_ENHANCEMENTS.md`
- Summary: `IMPLEMENTATION_SUMMARY_DEPLOYMENTS.md`
