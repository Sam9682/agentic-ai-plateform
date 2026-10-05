# Dynamic Nginx Locations Implementation Summary

## Overview

SwAutoMorph now automatically creates nginx location blocks for user applications, enabling access via:
```
https://www.swautomorph.com/{USER_ID}/{APPLICATION_NAME}
```

This reverse proxies to the application's actual URL (e.g., `https://www.swautomorph.com:6217`).

## Files Created

### Core Module
- **`src/nginx_manager.py`** - Nginx configuration management module
  - `insert_location_block()` - Add/update location for user app
  - `remove_location_block()` - Remove location for user app
  - `sync_all_locations()` - Sync all locations from database
  - `generate_location_block()` - Generate nginx config block
  - `reload_nginx()` - Test and reload nginx safely

### Scripts
- **`scripts/sync_nginx_locations.py`** - CLI tool to sync all locations from database
- **`scripts/test_nginx_locations.py`** - Test script for nginx location management

### Configuration
- **`conf/nginx-dynamic-locations.conf`** - Initial nginx configuration template

### Documentation
- **`docs/NGINX_DYNAMIC_LOCATIONS.md`** - Complete feature documentation

## Files Modified

### API Routes (`src/routes/api_routes.py`)
1. **Import nginx_manager functions**
   ```python
   from ..nginx_manager import insert_location_block, remove_location_block, sync_all_locations
   ```

2. **Application assignment endpoint** - Auto-update nginx when assigning app to user
   ```python
   insert_location_block(user_id, app_name, url)
   ```

3. **Application unassignment endpoint** - Auto-remove nginx location
   ```python
   remove_location_block(user_id, app_name)
   ```

4. **Clone deployment action** - Update nginx after successful clone
   ```python
   insert_location_block(user_id, app_name, user_app[0])
   ```

5. **New API endpoint** - `/api/nginx/sync` for manual sync (admin only)

### README.md
- Added feature to features list
- Added API usage examples
- Added to directory structure
- Added to key components

## How It Works

### Automatic Updates

Nginx locations are automatically managed when:

1. **Assigning application to user**
   - POST `/api/users/{user_id}/applications`
   - Creates location: `/{user_id}/{app_name}` → `{app_url}`

2. **Unassigning application**
   - DELETE `/api/users/{user_id}/applications`
   - Removes location block from nginx config

3. **Cloning/deploying application**
   - POST `/api/deployments` with `action=clone`
   - Updates location after successful clone

### Manual Sync

Admin can manually sync all locations:

**Via API:**
```bash
curl -X POST https://www.swautomorph.com/api/nginx/sync \
  -H "Cookie: session=your-session-cookie"
```

**Via CLI:**
```bash
python3 ./scripts/sync_nginx_locations.py
```

## Example Usage

### User 2 with ai-staticwebsite on port 6217

**Database entry:**
```sql
user_id: 2
application_name: ai-staticwebsite
url: https://www.swautomorph.com:6217
```

**Generated nginx location:**
```nginx
location /2/ai-staticwebsite {
    proxy_pass https://www.swautomorph.com:6217;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    
    # WebSocket support
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    
    # Timeouts
    proxy_connect_timeout 30s;
    proxy_send_timeout 60s;
    proxy_read_timeout 60s;
    
    # Rewrite path to remove user prefix
    rewrite ^/2/ai-staticwebsite(/.*)?$ $1 break;
}
```

**Access:**
```bash
curl https://www.swautomorph.com/2/ai-staticwebsite
```

## Safety Features

1. **Configuration testing** - Nginx config tested before reload
2. **Automatic rollback** - Failed configs don't break nginx
3. **Error logging** - All operations logged for debugging
4. **Admin-only sync** - Manual sync requires admin privileges
5. **Path validation** - Prevents injection attacks

## Testing

Run tests:
```bash
python3 ./scripts/test_nginx_locations.py
```

## Deployment

No additional deployment steps required. The feature is automatically active when:
1. Application is assigned to user
2. Application is deployed/cloned
3. Manual sync is triggered

## Configuration

Nginx configuration file location:
- **Available:** `/etc/nginx/sites-available/<PLTF_FOLDER>-dynamic`
- **Enabled:** `/etc/nginx/sites-enabled/<PLTF_FOLDER>-dynamic`

## Troubleshooting

### Check nginx config
```bash
sudo nginx -t
```

### View current config
```bash
cat /etc/nginx/sites-available/<PLTF_FOLDER>-dynamic
```

### Reload nginx
```bash
sudo systemctl reload nginx
```

### Sync all locations
```bash
python3 ./scripts/sync_nginx_locations.py
```

### Check logs
```bash
tail -f /var/log/nginx/error.log
tail -f logs/api_routes.log
```

## Future Enhancements

- Custom domain mapping per application
- SSL certificate management per app
- Rate limiting per user/application
- Access control and authentication
- Load balancing for multi-instance apps
- Health checks per location
- Metrics and monitoring per location
