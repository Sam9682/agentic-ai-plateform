# Quick Reference: IP-Based S3 Backup

## 🎯 What Changed?

Backups are now organized by server IP address in S3:
- **Old:** `s3://softfluid/db/backup/20260214_103102/`
- **New:** `s3://softfluid/db/backup/192.168.1.100/20260214_103102/`

## 🚀 Quick Commands

### Create Backup
```bash
./deployControlPlan.sh stop
```
Backup will be synced to: `s3://softfluid/db/backup/$YOUR_IP/$TIMESTAMP/`

### Restore from Backup
```bash
./deployControlPlan.sh recover_db
```
Follow the interactive menus:
1. Choose: Local or S3
2. If S3: Choose server IP
3. Choose backup timestamp

### Check Your Server IP
```bash
curl -s ifconfig.me
```

### List Your Backups in S3
```bash
SERVER_IP=$(curl -s ifconfig.me)
aws s3 ls s3://softfluid/db/backup/$SERVER_IP/ --profile OVH-SWAUTOMORPH
```

### List All Servers with Backups
```bash
aws s3 ls s3://softfluid/db/backup/ --profile OVH-SWAUTOMORPH
```

## 📖 Common Scenarios

### Scenario 1: Regular Backup (Same as Before)
```bash
./deployControlPlan.sh stop
# Backup created and synced to S3 automatically
```

### Scenario 2: Restore Latest Backup
```bash
./deployControlPlan.sh recover_db
# Select: Remote S3 backups
# Select: [Your IP] (current server)
# Select: [Latest timestamp]
```

### Scenario 3: Copy Production to Development
```bash
# On development server
./deployControlPlan.sh recover_db
# Select: Remote S3 backups
# Select: [Production server IP]
# Select: [Desired backup]
```

### Scenario 4: Disaster Recovery
```bash
# On new server
./deployControlPlan.sh recover_db
# Select: Remote S3 backups
# Select: [Failed server IP]
# Select: [Latest backup before failure]
```

## 🔧 Troubleshooting

### Problem: Backup uses 127.0.0.1
**Solution:** Check internet connectivity
```bash
curl -s ifconfig.me
```

### Problem: Cannot see S3 backups
**Solution:** Verify AWS CLI configuration
```bash
aws configure list --profile OVH-SWAUTOMORPH
aws s3 ls s3://softfluid/db/backup/ --profile OVH-SWAUTOMORPH
```

### Problem: Download fails
**Solution:** Check S3 permissions and network
```bash
aws s3 ls s3://softfluid/ --profile OVH-SWAUTOMORPH
```

## 📁 File Locations

- **Script:** `./deployControlPlan.sh`
- **Local backups:** `./softfluid/db/backup/YYYYMMDD_HHMMSS/`
- **S3 backups:** `s3://softfluid/db/backup/$SERVER_IP/YYYYMMDD_HHMMSS/`
- **Temp downloads:** `./softfluid/db/backup/s3-temp-$SERVER_IP-$TIMESTAMP/`
- **Pre-recovery:** `./softfluid/db/backup/pre-recovery-$TIMESTAMP/`

## ⚙️ Configuration

### Required
- AWS CLI installed: `sudo apt-get install awscli`
- AWS profile configured: `OVH-SWAUTOMORPH`
- S3 bucket access: `s3://softfluid`

### Optional
- Python package: `simple-term-menu` (for better menus)
  ```bash
  pip3 install simple-term-menu
  ```

## 💡 Tips

1. **Always test restore** on non-production first
2. **Keep local backups** as primary, S3 as secondary
3. **Monitor S3 costs** if storing many backups
4. **Document server IPs** for easy identification
5. **Test cross-server restore** before you need it

## 📞 Support

### Check Script Syntax
```bash
bash -n deployControlPlan.sh
```

### View Recent Backups
```bash
ls -lt ./softfluid/db/backup/ | head -10
```

### Check Database Status
```bash
./deployControlPlan.sh status
```

### View Logs
```bash
tail -f logs/gunicorn_error.log
```

## 🔗 Related Documentation

- Full details: `docs/RECOVER_DB_S3_FEATURE.md`
- Implementation summary: `IP_BASED_S3_BACKUP_SUMMARY.md`
- Flow diagrams: `S3_BACKUP_FLOW_DIAGRAM.md`
- Testing checklist: `IMPLEMENTATION_CHECKLIST.md`
