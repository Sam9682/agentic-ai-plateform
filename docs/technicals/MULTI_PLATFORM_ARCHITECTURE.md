# Multi-Platform SwAutoMorph Architecture

## Overview

SwAutoMorph now supports multi-platform deployment with PRIMARY/SECONDARY server architecture. This enables distributed deployment across multiple servers with automatic discovery and role management.

## Architecture Components

### 1. Server Roles

- **PRIMARY**: Main server that coordinates operations
- **SECONDARY**: Backup servers that maintain their own database with periodic synchronization

### 2. Discovery Protocol

When adding a new server through the admin interface:

1. System attempts to connect to `/api/platform/status` endpoint on the remote IP
2. If SwAutoMorph is detected:
   - Remote server's role is identified
   - Current server role is determined based on discovery
   - If remote is PRIMARY, current becomes SECONDARY
3. Server information is stored in the database

### 3. Database Architecture

Each server maintains its own PostgreSQL database:
- Independent operation capability
- Periodic synchronization between PRIMARY and SECONDARY
- Manual intervention required for failover

## API Endpoints

### Platform Status Endpoint

```bash
GET /api/platform/status
```

Returns:
```json
{
  "platform": "SwAutoMorph",
  "version": "1.0",
  "role": "PRIMARY",
  "server_ip": "192.168.1.100",
  "server_name": "main-server",
  "servers": [
    {"ip": "192.168.1.100", "name": "main-server", "type": "PRIMARY"},
    {"ip": "192.168.1.101", "name": "worker-01", "type": "SECONDARY"}
  ]
}
```

### Server Management

```bash
# Add server with automatic discovery
POST /api/servers
{
  "SERVER_IP": "192.168.1.101",
  "SERVER_NAME": "worker-01",
  "SERVER_CAPACITY_USER_MAX": 20,
  "SERVER_CAPACITY_APPLI_MAX": 100,
  "SERVER_STATUS": "STAND_BY"
}

# Response includes discovery status
{
  "message": "Server created successfully",
  "discovered": true,
  "server_type": "SECONDARY"
}
```

## CLI Management

### Platform Status

```bash
python3 ./scripts/controller_cli.py platform-status
```

Output:
```
Platform Role: PRIMARY
Server Name: main-server
Server IP: 192.168.1.100

All Servers:
  - main-server (192.168.1.100): PRIMARY [ACTIVE]
  - worker-01 (192.168.1.101): SECONDARY [STAND_BY]
```

### Server Discovery

```bash
python3 ./scripts/controller_cli.py discover-server 192.168.1.101
```

Output:
```
Checking 192.168.1.101 for SwAutoMorph...
✓ SwAutoMorph found!
  Role: SECONDARY
  Version: 1.0
  Server: worker-01

Role determination:
  Current server will be: PRIMARY
  Remote server is: SECONDARY

✓ Local server role updated to PRIMARY
```

## Deployment Scenarios

### Scenario 1: First Installation

1. Install SwAutoMorph on first server
2. Server automatically becomes PRIMARY
3. Database initialized with server record

### Scenario 2: Adding Secondary Server

1. Install SwAutoMorph on second server
2. From PRIMARY admin interface, add new server IP
3. System discovers remote SwAutoMorph
4. PRIMARY remains PRIMARY, new server becomes SECONDARY

### Scenario 3: Manual Role Assignment

If discovery fails or manual control needed:
1. Add server with explicit SERVER_TYPE
2. System uses provided type instead of discovery

## Database Synchronization

### Periodic Sync (Future Enhancement)

```python
from src.db_sync import DatabaseSync

sync = DatabaseSync(db_manager)
primary = sync.get_primary_server()

if primary:
    sync.sync_from_primary(primary['ip'])
```

### Manual Sync

```bash
# From SECONDARY server
python3 ./scripts/sync_from_primary.py
```

## Failover Behavior

### PRIMARY Server Failure

1. SECONDARY servers continue operating with local database
2. Manual intervention required to promote SECONDARY to PRIMARY
3. Update server_type in database:

```sql
UPDATE servers SET server_type = 'PRIMARY' WHERE server_ip = 'current_ip';
```

### SECONDARY Server Failure

1. PRIMARY continues normal operation
2. Remove failed server from database or mark as inactive

## Security Considerations

1. **SSL/TLS**: Discovery uses HTTPS with fallback to HTTP
2. **Authentication**: Platform status endpoint is public (read-only)
3. **Network**: Servers should be on trusted network or VPN
4. **Firewall**: Open port 443 (or configured port) between servers

## Configuration

### Environment Variables

```bash
# PostgreSQL connection (each server)
export POSTGRES_HOST="localhost"
export POSTGRES_PORT="5432"
export POSTGRES_DB="ai_swautomorph"
export POSTGRES_USER="swautomorph"
export POSTGRES_PASSWORD="swautomorph_password"
```

### Discovery Timeout

Default: 5 seconds

Modify in `src/platform_discovery.py`:
```python
DISCOVERY_TIMEOUT = 5
```

## Monitoring

### Check Platform Health

```bash
# Via API
curl https://www.swautomorph.com/api/platform/status

# Via CLI
python3 ./scripts/platform_cli.py status
```

### Database Health

```bash
python3 ./scripts/controller_cli.py db-health
```

## Troubleshooting

### Discovery Not Working

1. Check network connectivity:
```bash
ping <remote_ip>
curl https://<remote_ip>/api/platform/status
```

2. Verify SSL certificates
3. Check firewall rules

### Role Conflicts

If both servers think they're PRIMARY:
1. Decide which should be PRIMARY
2. On SECONDARY, run:
```sql
UPDATE servers SET server_type = 'SECONDARY' WHERE server_ip = '<current_ip>';
```

### Database Sync Issues

1. Check PRIMARY server accessibility
2. Verify database credentials
3. Check network latency

## Future Enhancements

1. **Automatic Failover**: Implement leader election
2. **Real-time Sync**: Use PostgreSQL logical replication
3. **Load Balancing**: Distribute deployments across servers
4. **Health Monitoring**: Automated health checks and alerts
5. **Consensus Protocol**: Implement Raft or Paxos for distributed consensus
