# Nginx Dynamic Location Management

## Overview

SwAutoMorph now automatically creates nginx location blocks for each user's applications, allowing access via:
```
https://www.swautomorph.com/{USER_NAME}/{APPLICATION_NAME}
```

This URL pattern reverse proxies to the application's actual URL (e.g., `https://www.swautomorph.com:6217`).

## How It Works

### Automatic Configuration

When an application is assigned to a user or deployed:
1. A location block is dynamically inserted into nginx configuration
2. The location path follows the pattern `/{USER_NAME}/{APPLICATION_NAME}`
3. Requests are reverse proxied to the application's actual URL
4. Path rewriting removes the user prefix before forwarding

### Example

For user `john` with application `ai-staticwebsite` running on port `6217`:

**Access URL:**
```
https://www.swautomorph.com/john/ai-staticwebsite
```

**Proxies to:**
```
https://www.swautomorph.com:6217
```

**Generated nginx configuration:**
```nginx
location /john/ai-staticwebsite {
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
    rewrite ^/john/ai-staticwebsite(/.*)?$ $1 break;
}
```

## API Usage

### Automatic Updates

Nginx locations are automatically updated when:
- Assigning an application to a user via `/api/users/{user_id}/applications` (POST)
- Unassigning an application via `/api/users/{user_id}/applications` (DELETE)
- Cloning/deploying an application via `/api/deployments` (POST with action=clone)

### Manual Sync

Sync all locations from database (admin only):
```bash
curl -X POST https://www.swautomorph.com/api/nginx/sync \
  -H "Cookie: session=your-session-cookie"
```

Or via CLI:
```bash
python3 ./scripts/sync_nginx_locations.py
```

## Configuration Files

- **Nginx config:** `/etc/nginx/sites-available/<PLTF_FOLDER>-dynamic`
- **Enabled symlink:** `/etc/nginx/sites-enabled/<PLTF_FOLDER>-dynamic`
- **Manager module:** `src/nginx_manager.py`

## Troubleshooting

### Check nginx configuration
```bash
sudo nginx -t
```

### View current configuration
```bash
cat /etc/nginx/sites-available/<PLTF_FOLDER>-dynamic
```

### Reload nginx manually
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

## Security Considerations

- Only admin users can manually sync nginx locations
- Path validation prevents directory traversal attacks
- Configuration testing before reload prevents broken configs
- Automatic rollback on configuration errors

## Implementation Details

### Module: `src/nginx_manager.py`

**Functions:**
- `insert_location_block(user_id, app_name, target_url)` - Add/update location
- `remove_location_block(user_id, app_name)` - Remove location
- `sync_all_locations(db_manager)` - Sync all from database
- `reload_nginx()` - Test and reload nginx

### Integration Points

**API Routes (`src/routes/api_routes.py`):**
- Application assignment endpoint
- Application unassignment endpoint
- Deployment clone action
- Manual sync endpoint

### Database Schema

Uses existing `user_applications` table with username lookup:
```sql
SELECT u.username, a.name, ua.url
FROM user_applications ua
JOIN applications a ON ua.application_id = a.id
JOIN users u ON ua.user_id = u.id
WHERE ua.url IS NOT NULL AND ua.url != ''
```

**Note:** The system uses `username` (not `user_id`) in URL paths for better readability and user experience.

## Future Enhancements

- Support for custom domain mapping
- SSL certificate management per application
- Rate limiting per user/application
- Access control and authentication
- Load balancing for multi-instance applications
