# S3 Backup Flow with IP-Based Organization

## Backup Flow

```
┌─────────────────────────────────────────────────────────────┐
│  Server: 192.168.1.100                                      │
│  ./deployControlPlan.sh stop                                │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
         ┌───────────────────────┐
         │  backup_database()    │
         └───────────┬───────────┘
                     │
                     ▼
         ┌───────────────────────┐
         │  get_server_ip()      │
         │  Returns: 192.168.1.100│
         └───────────┬───────────┘
                     │
                     ▼
         ┌───────────────────────────────────────┐
         │  Create local backup:                 │
         │  ./softfluid/db/backup/20260214_103102│
         └───────────┬───────────────────────────┘
                     │
                     ▼
         ┌───────────────────────────────────────────────────┐
         │  aws s3 sync to:                                  │
         │  s3://softfluid/db/backup/192.168.1.100/20260214_103102/│
         └───────────────────────────────────────────────────┘
```

## Restore Flow - Same Server

```
┌─────────────────────────────────────────────────────────────┐
│  Server: 192.168.1.100                                      │
│  ./deployControlPlan.sh recover_db                          │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
         ┌───────────────────────┐
         │  Select backup source │
         │  ▶ Remote S3 backups  │
         └───────────┬───────────┘
                     │
                     ▼
         ┌───────────────────────────────┐
         │  get_server_ip()              │
         │  Current: 192.168.1.100       │
         └───────────┬───────────────────┘
                     │
                     ▼
         ┌───────────────────────────────────────┐
         │  List servers in S3:                  │
         │  ▶ 192.168.1.100 (current server)     │
         │    192.168.1.200                      │
         │    10.0.0.50                          │
         └───────────┬───────────────────────────┘
                     │
                     ▼
         ┌───────────────────────────────────────┐
         │  List backups for 192.168.1.100:     │
         │  ▶ 20260214_103102                    │
         │    20260214_104523                    │
         │    20260214_105847                    │
         └───────────┬───────────────────────────┘
                     │
                     ▼
         ┌───────────────────────────────────────────────────┐
         │  Download from:                                   │
         │  s3://softfluid/db/backup/192.168.1.100/20260214_103102/│
         │  To: ./softfluid/db/backup/s3-temp-192.168.1.100-20260214_103102│
         └───────────┬───────────────────────────────────────┘
                     │
                     ▼
         ┌───────────────────────┐
         │  Restore database     │
         └───────────┬───────────┘
                     │
                     ▼
         ┌───────────────────────┐
         │  Cleanup temp files   │
         └───────────────────────┘
```

## Restore Flow - Cross-Server (Production to Dev)

```
┌─────────────────────────────────────────────────────────────┐
│  Server: 192.168.1.200 (Development)                        │
│  ./deployControlPlan.sh recover_db                          │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
         ┌───────────────────────┐
         │  Select backup source │
         │  ▶ Remote S3 backups  │
         └───────────┬───────────┘
                     │
                     ▼
         ┌───────────────────────────────┐
         │  get_server_ip()              │
         │  Current: 192.168.1.200       │
         └───────────┬───────────────────┘
                     │
                     ▼
         ┌───────────────────────────────────────┐
         │  List servers in S3:                  │
         │  ▶ 192.168.1.100 ← SELECT THIS        │
         │    192.168.1.200 (current server)     │
         │    10.0.0.50                          │
         └───────────┬───────────────────────────┘
                     │
                     ▼
         ┌───────────────────────────────────────┐
         │  List backups for 192.168.1.100:     │
         │  (Production server backups)          │
         │  ▶ 20260214_103102 ← Latest           │
         │    20260214_104523                    │
         │    20260214_105847                    │
         └───────────┬───────────────────────────┘
                     │
                     ▼
         ┌───────────────────────────────────────────────────┐
         │  Download from PRODUCTION:                        │
         │  s3://softfluid/db/backup/192.168.1.100/20260214_103102/│
         │  To: ./softfluid/db/backup/s3-temp-192.168.1.100-20260214_103102│
         └───────────┬───────────────────────────────────────┘
                     │
                     ▼
         ┌───────────────────────────────────────┐
         │  Restore production data to dev DB    │
         └───────────┬───────────────────────────┘
                     │
                     ▼
         ┌───────────────────────┐
         │  Cleanup temp files   │
         └───────────────────────┘
```

## S3 Bucket Structure

```
s3://softfluid/
│
├── db/
│   └── backup/
│       ├── 192.168.1.100/          ← Production Server
│       │   ├── 20260214_103102/
│       │   │   ├── complete_database.sql
│       │   │   ├── data_only.sql
│       │   │   ├── schema_only.sql
│       │   │   └── backup.log
│       │   ├── 20260214_104523/
│       │   │   └── ...
│       │   └── 20260214_105847/
│       │       └── ...
│       │
│       ├── 192.168.1.200/          ← Development Server
│       │   ├── 20260214_110234/
│       │   │   └── ...
│       │   └── 20260214_111456/
│       │       └── ...
│       │
│       └── 10.0.0.50/              ← Staging Server
│           └── 20260214_112345/
│               └── ...
│
└── logs/                           ← Application logs
    └── ...
```

## Key Features

### 1. Server Identification
- Each server is identified by its IP address
- IP is automatically detected during backup
- Supports both public and private IPs

### 2. Backup Isolation
- Each server's backups are stored separately
- No risk of backup conflicts between servers
- Easy to identify backup source

### 3. Cross-Server Restore
- Can restore from any server to any server
- Useful for:
  - Refreshing dev/staging with production data
  - Disaster recovery to new server
  - Testing backups from different environments

### 4. Flexible Recovery
- Choose backup source: Local or S3
- Choose server: Current or any other
- Choose backup: Any timestamp available

## Use Cases

### Use Case 1: Regular Backup
**Scenario:** Daily backup on production server
```bash
# On 192.168.1.100 (Production)
./deployControlPlan.sh stop
# Backup created at: s3://softfluid/db/backup/192.168.1.100/YYYYMMDD_HHMMSS/
```

### Use Case 2: Refresh Development
**Scenario:** Update dev database with production data
```bash
# On 192.168.1.200 (Development)
./deployControlPlan.sh recover_db
# Select: S3 → 192.168.1.100 → Latest backup
```

### Use Case 3: Disaster Recovery
**Scenario:** Production server failed, restore to new server
```bash
# On 10.0.0.50 (New Production Server)
./deployControlPlan.sh recover_db
# Select: S3 → 192.168.1.100 (old prod) → Latest backup
```

### Use Case 4: Testing Backups
**Scenario:** Verify backup integrity on staging
```bash
# On 10.0.0.75 (Staging)
./deployControlPlan.sh recover_db
# Select: S3 → 192.168.1.100 → Specific backup to test
```

## Migration Path

### For Existing Non-IP Backups

If you have existing backups without IP organization:

```bash
# List old backups
aws s3 ls s3://softfluid/db/backup/ --profile OVH-SWAUTOMORPH

# Example output:
#   PRE 20260214_103102/
#   PRE 20260214_104523/

# Move to IP-based structure
SERVER_IP="192.168.1.100"  # Your server IP

aws s3 mv \
  s3://softfluid/db/backup/20260214_103102/ \
  s3://softfluid/db/backup/$SERVER_IP/20260214_103102/ \
  --recursive --profile OVH-SWAUTOMORPH

aws s3 mv \
  s3://softfluid/db/backup/20260214_104523/ \
  s3://softfluid/db/backup/$SERVER_IP/20260214_104523/ \
  --recursive --profile OVH-SWAUTOMORPH
```

## Troubleshooting

### Issue: IP Detection Fails
**Symptom:** Backup uses 127.0.0.1
**Solution:** 
```bash
# Manually check IP
curl -s ifconfig.me
hostname -I | awk '{print $1}'

# Set in environment before backup
export SERVER_IP="your.actual.ip"
```

### Issue: Cannot List S3 Servers
**Symptom:** "No server backups found in S3 bucket"
**Solution:**
```bash
# Verify AWS CLI and profile
aws s3 ls s3://softfluid/db/backup/ --profile OVH-SWAUTOMORPH

# Check credentials
aws configure list --profile OVH-SWAUTOMORPH
```

### Issue: Download Fails
**Symptom:** "Failed to download backup from S3"
**Solution:**
```bash
# Test S3 access
aws s3 ls s3://softfluid/db/backup/192.168.1.100/ --profile OVH-SWAUTOMORPH

# Check permissions
aws s3api get-bucket-acl --bucket softfluid --profile OVH-SWAUTOMORPH
```
