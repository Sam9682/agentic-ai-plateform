# Database Recovery S3 Feature with IP-Based Organization

## Overview
Modified the `recover_database()` and `backup_database()` functions in `deployControlPlan.sh` to organize backups by server IP address in S3, allowing customers to select backups from different servers.

## Changes Made

### 1. IP Address Detection Function
Added `get_server_ip()` function that:
- Attempts to get the public IP from external services (ifconfig.me, icanhazip.com)
- Falls back to the primary network interface IP
- Uses localhost as a last resort

### 2. Backup Function Updates
Modified `backup_database()` to:
- Get the server's IP address using `get_server_ip()`
- Sync backups to S3 with IP-based path: `s3://softfluid/db/backup/$SERVER_IP/$DATETIME/`
- Display the server IP during backup process
- Provide clear feedback on the S3 sync destination

**Old S3 Path Structure:**
```
s3://softfluid/db/backup/20260214_103102/
```

**New S3 Path Structure:**
```
s3://softfluid/db/backup/192.168.1.100/20260214_103102/
```

### 3. Backup Source Selection
Added an interactive menu at the start of the recovery process that allows users to choose between:
- **Local backups**: `./softfluid/db/backup` (existing behavior)
- **Remote S3 backups**: `s3://softfluid/db/backup/$SERVER_IP/` (new feature)

The menu uses `simple-term-menu` for a better user experience, with a fallback to numbered selection.

### 4. Server Selection for S3 Restore
When S3 is selected, users can now:
- View all available server IPs that have backups in S3
- See which server is the current server (marked with "(current server)")
- Select which server's backups to restore from
- View the number of backups available for the selected server

### 5. S3 Backup Listing
When S3 is selected:
- Lists all server IPs with backups in S3
- Allows selection of the source server
- Lists available backup directories from the selected server
- Displays the number of backups found
- Provides helpful error messages if AWS CLI is missing or no backups are found

### 6. S3 Backup Download
When a backup from S3 is selected:
- Creates a temporary directory: `./softfluid/db/backup/s3-temp-$SERVER_IP-$DATETIME`
- Downloads the selected backup using `aws s3 sync` from the correct IP-based path
- Provides clear feedback on download progress
- Handles download failures gracefully with cleanup

### 7. Cleanup
After the recovery process completes:
- Automatically removes the temporary S3 backup directory
- Keeps the pre-recovery backup for safety
- Provides clear status messages

## Usage

### Creating Backups
Backups are automatically organized by server IP:
```bash
./deployControlPlan.sh stop  # Creates backup before stopping
```

The backup will be synced to: `s3://softfluid/db/backup/$SERVER_IP/$TIMESTAMP/`

### Restoring from Backup
Run the recovery command:
```bash
./deployControlPlan.sh recover_db
```

The script will now prompt you to:
1. Select backup source (Local or S3)
2. If S3: Select which server to restore from (shows all available server IPs)
3. Select which backup to restore (from the chosen server)
4. Proceed with the restoration

## Requirements

For S3 backup recovery:
- AWS CLI must be installed: `sudo apt-get install awscli`
- AWS profile `OVH-SWAUTOMORPH` must be configured
- Network access to S3 bucket `s3://softfluid`
- Internet access for IP detection (optional, falls back to local IP)

## Benefits

- **Multi-Server Management**: Organize backups by server IP for easy identification
- **Cross-Server Recovery**: Restore backups from any server to any other server
- **Disaster Recovery**: Restore from remote backups if local storage fails
- **Server Migration**: Easily migrate databases between servers
- **Backup Verification**: Test S3 backups without manual download
- **Flexibility**: Choose the most appropriate backup source and server for each situation
- **Clear Organization**: S3 bucket is organized by server IP, making it easy to manage backups from multiple servers

## Example Scenarios

### Scenario 1: Restore from Same Server
1. Server 192.168.1.100 creates backups to `s3://softfluid/db/backup/192.168.1.100/`
2. Later, restore on the same server by selecting "192.168.1.100 (current server)"

### Scenario 2: Restore from Different Server
1. Production server 192.168.1.100 has backups in S3
2. Development server 192.168.1.200 needs production data
3. Run recovery on dev server, select S3, choose server 192.168.1.100
4. Select the desired backup and restore

### Scenario 3: Disaster Recovery
1. Server 192.168.1.100 fails completely
2. New server 192.168.1.150 is provisioned
3. Run recovery, select S3, choose server 192.168.1.100
4. Restore the latest backup to the new server
