# Database Replication - Quick Start Guide

## 5-Minute Setup

### Step 1: Generate Sync Secret (Run on ONE server)
```bash
cd /home/ubuntu/<PLTF_FOLDER>
python3 -c "import secrets; print('SYNC_SECRET=' + secrets.token_hex(32))" | tee -a .env
```

Copy the generated `SYNC_SECRET` value.

### Step 2: Configure All Servers
On **each** SwAutoMorph server, add the **same** sync secret to `.env`:
```bash
echo "SYNC_SECRET=<paste-secret-here>" >> .env
```

### Step 3: Restart Application
```bash
./deployControlPlan.sh restart
```

### Step 4: Verify Replication
```bash
# Check replication health
curl -k https://localhost/api/sync/health

# Check status
python3 scripts/replication_cli.py status
```

## Testing Replication

### Test 1: Create User on Server A
```bash
# On Server A (192.168.1.10)
curl -X POST https://192.168.1.10/register \
  -H "Content-Type: application/json" \
  -d '{"username":"testuser","email":"test@example.com","password":"test123"}'
```

### Test 2: Verify User on Server B
```bash
# On Server B (192.168.1.11)
python3 scripts/controller_cli.py list-users | grep testuser
```

If user appears on Server B, replication is working! ✓

## Monitoring

### Check Queue Size
```bash
curl -k https://localhost/api/sync/status
```

### View Replication Logs
```bash
tail -f logs/output_print_logs.txt | grep REPLICATION
```

### Manual Sync (if needed)
```bash
# Sync users table to specific server
python3 scripts/replication_cli.py sync users 192.168.1.11
```

## Troubleshooting

### Problem: Queue growing
**Solution**: Check peer connectivity
```bash
python3 scripts/replication_cli.py test <peer_ip>
```

### Problem: Sync secret mismatch
**Solution**: Verify secrets match on all servers
```bash
grep SYNC_SECRET .env
```

### Problem: Network issues
**Solution**: Test HTTPS connectivity
```bash
curl -k https://<peer_ip>/api/sync/health
```

## What Gets Replicated?

✅ **YES** - Business data:
- Users
- Applications
- User-app assignments
- Billing activities
- SSO tokens

❌ **NO** - Server-specific:
- Server registry
- Nginx locations
- Deployment logs
- Sessions

## Architecture Summary

```
User Action → Database Insert → Replication Queue → Background Worker → HTTPS API → Peer Server → Apply Change
```

**Latency**: < 1 second for most operations
**Reliability**: 3 automatic retries on failure
**Security**: Shared secret + HTTPS encryption

## Next Steps

1. ✅ Setup complete - replication is automatic
2. Monitor queue size periodically
3. Rotate sync secret every 90 days
4. Add more peer servers as needed

For detailed documentation, see: `docs/REPLICATION_GUIDE.md`
