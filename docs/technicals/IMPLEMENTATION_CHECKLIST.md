# IP-Based S3 Backup Implementation Checklist

## ✅ Completed Tasks

### Code Changes
- [x] Added `get_server_ip()` function to detect server IP address
- [x] Modified `backup_database()` to use IP-based S3 paths
- [x] Modified `recover_database()` to support server selection
- [x] Updated S3 sync commands with IP-based structure
- [x] Added server selection menu for S3 restore
- [x] Updated temporary directory naming to include server IP
- [x] Added cleanup logic for IP-based temp directories
- [x] Validated script syntax (bash -n)

### Path Structure Changes
- [x] Backup path: `s3://softfluid/db/backup/$SERVER_IP/$DATETIME/`
- [x] Restore path: `s3://softfluid/db/backup/$SELECTED_SERVER/$SELECTED_BACKUP/`
- [x] Temp directory: `./softfluid/db/backup/s3-temp-$SERVER_IP-$DATETIME`

### User Experience
- [x] Added backup source selection menu (Local/S3)
- [x] Added server selection menu for S3 restores
- [x] Display current server IP during operations
- [x] Mark current server in selection menu
- [x] Show selected server during download
- [x] Provide clear feedback messages
- [x] Fallback to numbered selection if simple-term-menu unavailable

### Documentation
- [x] Updated RECOVER_DB_S3_FEATURE.md with IP-based structure
- [x] Created IP_BASED_S3_BACKUP_SUMMARY.md
- [x] Created S3_BACKUP_FLOW_DIAGRAM.md
- [x] Created IMPLEMENTATION_CHECKLIST.md
- [x] Documented migration path for existing backups
- [x] Added troubleshooting section
- [x] Included usage examples and scenarios

## 🧪 Testing Checklist

### Pre-Deployment Testing
- [ ] Test IP detection on target server
  ```bash
  curl -s --max-time 2 ifconfig.me
  hostname -I | awk '{print $1}
  ```

- [ ] Verify AWS CLI is installed and configured
  ```bash
  aws --version
  aws configure list --profile OVH-SWAUTOMORPH
  ```

- [ ] Test S3 access
  ```bash
  aws s3 ls s3://softfluid/db/backup/ --profile OVH-SWAUTOMORPH
  ```

### Backup Testing
- [ ] Create a test backup
  ```bash
  ./deployControlPlan.sh stop
  ```

- [ ] Verify backup appears in S3 with IP-based path
  ```bash
  SERVER_IP=$(curl -s ifconfig.me)
  aws s3 ls s3://softfluid/db/backup/$SERVER_IP/ --profile OVH-SWAUTOMORPH
  ```

- [ ] Check backup files are complete
  ```bash
  aws s3 ls s3://softfluid/db/backup/$SERVER_IP/YYYYMMDD_HHMMSS/ --profile OVH-SWAUTOMORPH
  # Should show: complete_database.sql, data_only.sql, schema_only.sql, backup.log
  ```

### Restore Testing - Same Server
- [ ] Test local backup restore
  ```bash
  ./deployControlPlan.sh recover_db
  # Select: Local backups
  ```

- [ ] Test S3 backup restore from current server
  ```bash
  ./deployControlPlan.sh recover_db
  # Select: Remote S3 backups → Current server → Latest backup
  ```

- [ ] Verify database was restored correctly
  ```bash
  psql -h localhost -U swautomorph -d ai_swautomorph -c "\dt"
  ```

### Restore Testing - Cross-Server (if available)
- [ ] Test S3 restore from different server
  ```bash
  # On server B
  ./deployControlPlan.sh recover_db
  # Select: Remote S3 backups → Server A IP → Backup
  ```

- [ ] Verify cross-server restore completed
- [ ] Check data integrity after cross-server restore

### Error Handling Testing
- [ ] Test with no AWS CLI installed
- [ ] Test with invalid AWS credentials
- [ ] Test with no S3 backups available
- [ ] Test with network timeout during download
- [ ] Test cancellation during server selection
- [ ] Test cancellation during backup selection

### Cleanup Testing
- [ ] Verify temporary S3 directories are removed after restore
  ```bash
  ls -la ./softfluid/db/backup/ | grep s3-temp
  # Should be empty after successful restore
  ```

- [ ] Verify pre-recovery backups are kept
  ```bash
  ls -la ./softfluid/db/backup/ | grep pre-recovery
  # Should exist after restore
  ```

## 📋 Deployment Steps

### Step 1: Backup Current System
```bash
# Create a backup of the current script
cp deployControlPlan.sh deployControlPlan.sh.backup.$(date +%Y%m%d)

# Create a database backup
./deployControlPlan.sh stop
./deployControlPlan.sh start
```

### Step 2: Deploy New Script
```bash
# The modified deployControlPlan.sh is already in place
# Verify syntax
bash -n deployControlPlan.sh
```

### Step 3: Test on Non-Production First
```bash
# On development/staging server
./deployControlPlan.sh stop
# Verify backup appears in S3 with IP-based path

./deployControlPlan.sh recover_db
# Test restore functionality
```

### Step 4: Deploy to Production
```bash
# On production server
# Script is ready to use
# Next backup will automatically use IP-based structure
```

### Step 5: Migrate Existing Backups (Optional)
```bash
# If you want to migrate old backups to IP-based structure
SERVER_IP=$(curl -s ifconfig.me)

# List old backups
aws s3 ls s3://softfluid/db/backup/ --profile OVH-SWAUTOMORPH

# Move each backup (example)
aws s3 mv \
  s3://softfluid/db/backup/20260214_103102/ \
  s3://softfluid/db/backup/$SERVER_IP/20260214_103102/ \
  --recursive --profile OVH-SWAUTOMORPH
```

## 🔍 Verification Commands

### Check Current Server IP
```bash
curl -s ifconfig.me
hostname -I | awk '{print $1}'
```

### List All Server Backups in S3
```bash
aws s3 ls s3://softfluid/db/backup/ --profile OVH-SWAUTOMORPH
```

### List Backups for Specific Server
```bash
SERVER_IP="192.168.1.100"
aws s3 ls s3://softfluid/db/backup/$SERVER_IP/ --profile OVH-SWAUTOMORPH
```

### Check Backup Contents
```bash
SERVER_IP="192.168.1.100"
BACKUP_DATE="20260214_103102"
aws s3 ls s3://softfluid/db/backup/$SERVER_IP/$BACKUP_DATE/ --profile OVH-SWAUTOMORPH
```

### Download Backup Manually (for inspection)
```bash
SERVER_IP="192.168.1.100"
BACKUP_DATE="20260214_103102"
aws s3 sync \
  s3://softfluid/db/backup/$SERVER_IP/$BACKUP_DATE/ \
  /tmp/test-backup/ \
  --profile OVH-SWAUTOMORPH
```

## 🚨 Rollback Plan

If issues occur, rollback to previous version:

```bash
# Stop current services
./deployControlPlan.sh stop

# Restore old script
cp deployControlPlan.sh.backup.YYYYMMDD deployControlPlan.sh

# Verify syntax
bash -n deployControlPlan.sh

# Restart services
./deployControlPlan.sh start
```

## 📊 Success Criteria

- [x] Script syntax is valid
- [ ] Backups are created with IP-based S3 paths
- [ ] S3 restore shows server selection menu
- [ ] Can restore from current server's backups
- [ ] Can restore from different server's backups (if multi-server)
- [ ] Temporary directories are cleaned up
- [ ] Pre-recovery backups are created
- [ ] No errors in logs during backup/restore
- [ ] Database integrity maintained after restore

## 📝 Notes

### IP Detection Priority
1. Public IP from ifconfig.me (preferred)
2. Public IP from icanhazip.com (fallback)
3. Primary network interface IP (fallback)
4. 127.0.0.1 (last resort)

### Backward Compatibility
- Local backups: Fully compatible, no changes
- S3 backups: New structure, old backups need migration
- Database restore: No changes to restore logic

### Known Limitations
- Requires internet access for public IP detection
- Falls back to local IP if external services unavailable
- Old S3 backups (without IP) not accessible via new interface

### Future Enhancements
- Add option to specify custom server identifier
- Support for backup retention policies per server
- Automated backup migration tool
- Backup comparison between servers
- Backup size and age reporting per server
