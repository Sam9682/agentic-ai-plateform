# Multi-Domain Configuration Guide

## Overview

The AI-SwAutoMorph platform supports multiple domains with dynamic nginx configuration generation. This allows you to host the main application on one domain (e.g., softfluid.fr) while proxying additional domains (e.g., hypervisia.fr) to different backends.

## Configuration File: `conf/deploy.ini`

### Main Domain Configuration

The `DOMAIN` variable defines the primary domain for the platform:

```ini
DOMAIN=softfluid.fr
PLTF_NAME=SoftFluid AI
```

This domain will:
- Host the main Flask application on `http://localhost:${FLASK_PORT:-5000}`
- Include all standard location blocks (/, /gitea/, etc.)
- Support ModSecurity WAF protection (if enabled)
- Use SSL certificates from `/home/ubuntu/<PLTF_FOLDER>/ssl/softfluid.fr/`

### Secondary Domains Configuration

The `SECONDARY_DOMAINS` variable allows you to configure additional domains with custom proxy configurations:

```ini
# Secondary domains (comma-separated list)
# Format: "domain:server_names:proxy_pass,domain2:server_names:proxy_pass"
# Example: "hypervisia.fr:hypervisia.fr www.hypervisia.fr:https://softfluid.fr:6137"
SECONDARY_DOMAINS=hypervisia.fr:hypervisia.fr www.hypervisia.fr:https://softfluid.fr:6137
```

#### Format Specification

Each secondary domain entry consists of three colon-separated parts:

1. **domain**: The domain name used for SSL certificate path (e.g., `hypervisia.fr`)
2. **server_names**: Space-separated list of server names for nginx (e.g., `hypervisia.fr www.hypervisia.fr`)
3. **proxy_pass**: The backend URL to proxy requests to (e.g., `https://softfluid.fr:6137`)

Multiple secondary domains can be configured by separating them with commas:

```ini
SECONDARY_DOMAINS=domain1:server_names1:proxy_pass1,domain2:server_names2:proxy_pass2
```

### Complete Example

```ini
DOMAIN=softfluid.fr
PLTF_NAME=SoftFluid AI

# Secondary domains
SECONDARY_DOMAINS=hypervisia.fr:hypervisia.fr www.hypervisia.fr:https://softfluid.fr:6137,example.com:example.com www.example.com:http://backend.local:8080
```

## SSL Certificate Structure

Each domain (main and secondary) must have its SSL certificates in the following structure:

```
/home/ubuntu/<PLTF_FOLDER>/ssl/
├── softfluid.fr/
│   ├── fullchain_domain.crt
│   └── privateKey_domain.key
├── hypervisia.fr/
│   ├── fullchain_domain.crt
│   └── privateKey_domain.key
└── example.com/
    ├── fullchain_domain.crt
    └── privateKey_domain.key
```

### Certificate Requirements

- `fullchain_domain.crt`: Full certificate chain including intermediate certificates
- `privateKey_domain.key`: Private key for the domain

## Generated Nginx Configuration

The `create_nginx_config()` function in `deployControlPlan.sh` dynamically generates nginx server blocks based on the configuration.

### Configuration Generation Order

1. **Secondary Domains** (processed first)
   - One server block per secondary domain
   - HTTPS only (port 443)
   - Custom proxy_pass from configuration
   - Domain-specific SSL certificates

2. **HTTP Redirect** (main domain)
   - Redirects HTTP (port 80) to HTTPS
   - Applies to main domain and www subdomain

3. **Main Domain HTTPS** (processed last)
   - Full application functionality
   - Proxies to Flask application
   - Includes all location blocks (/gitea/, etc.)
   - ModSecurity WAF support (if enabled)
   - Domain-specific SSL certificates

### Example Generated Configuration

For the configuration:
```ini
DOMAIN=softfluid.fr
SECONDARY_DOMAINS=hypervisia.fr:hypervisia.fr www.hypervisia.fr:https://softfluid.fr:6137
```

The generated nginx configuration will be:

```nginx
# Secondary domain: hypervisia.fr
server {
    listen 443 ssl;
    server_name hypervisia.fr www.hypervisia.fr;
    
    ssl_certificate /home/ubuntu/<PLTF_FOLDER>/ssl/hypervisia.fr/fullchain_domain.crt;
    ssl_certificate_key /home/ubuntu/<PLTF_FOLDER>/ssl/hypervisia.fr/privateKey_domain.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    location / {
        proxy_pass https://softfluid.fr:6137;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

# HTTP redirect for main domain
server {
    listen 80;
    server_name softfluid.fr www.softfluid.fr;
    return 301 https://$host$request_uri;
}

# Main domain HTTPS
server {
    listen 443 ssl;
    server_name softfluid.fr www.softfluid.fr;
    
    ssl_certificate /home/ubuntu/<PLTF_FOLDER>/ssl/softfluid.fr/fullchain_domain.crt;
    ssl_certificate_key /home/ubuntu/<PLTF_FOLDER>/ssl/softfluid.fr/privateKey_domain.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    
    # ModSecurity (if enabled)
    modsecurity on;
    modsecurity_rules_file /etc/nginx/modsec/main.conf;
    
    location / {
        proxy_pass http://localhost:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    
    location /gitea/ {
        proxy_pass http://localhost:3000/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_buffering off;
        
        # WebSocket support for Gitea
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        
        # Increase timeouts for large operations
        proxy_connect_timeout 60s;
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;
    }
}
```

## Deployment Process

### 1. Update Configuration

Edit `conf/deploy.ini` to add or modify domains:

```bash
nano conf/deploy.ini
```

### 2. Prepare SSL Certificates

Ensure SSL certificates exist for all configured domains:

```bash
# Create directory structure
mkdir -p /home/ubuntu/<PLTF_FOLDER>/ssl/yourdomain.com

# Copy certificates
cp fullchain.crt /home/ubuntu/<PLTF_FOLDER>/ssl/yourdomain.com/fullchain_domain.crt
cp privkey.key /home/ubuntu/<PLTF_FOLDER>/ssl/yourdomain.com/privateKey_domain.key

# Set proper permissions
chmod 644 /home/ubuntu/<PLTF_FOLDER>/ssl/yourdomain.com/fullchain_domain.crt
chmod 600 /home/ubuntu/agentic-ai-plateform-docker-ah/ssl/yourdomain.com/privateKey_domain.key
```

### 3. Deploy Configuration

Run the deployment script to regenerate nginx configuration:

```bash
./deployControlPlan.sh deploy
```

The script will:
1. Load configuration from `conf/deploy.ini`
2. Generate nginx configuration with all domains
3. Test nginx configuration syntax
4. Reload nginx to apply changes

### 4. Verify Configuration

Check that nginx is running correctly:

```bash
# Test nginx configuration
sudo nginx -t

# Check nginx status
sudo systemctl status nginx

# View generated configuration
cat /etc/nginx/sites-available/<PLTF_FOLDER>
```

## Use Cases

### Use Case 1: Brand Consolidation

Host multiple brand domains on the same infrastructure:

```ini
DOMAIN=mainbrand.com
SECONDARY_DOMAINS=oldbrand.com:oldbrand.com www.oldbrand.com:https://mainbrand.com:443
```

### Use Case 2: Regional Domains

Route regional domains to localized backends:

```ini
DOMAIN=global.example.com
SECONDARY_DOMAINS=eu.example.com:eu.example.com:http://eu-backend:8080,us.example.com:us.example.com:http://us-backend:8080
```

### Use Case 3: Service Separation

Separate different services by domain:

```ini
DOMAIN=app.example.com
SECONDARY_DOMAINS=api.example.com:api.example.com:http://localhost:8000,admin.example.com:admin.example.com:http://localhost:9000
```

## Troubleshooting

### Issue: SSL Certificate Errors

**Symptoms**: Browser shows SSL certificate warnings

**Solutions**:
1. Verify certificate files exist:
   ```bash
   ls -la /home/ubuntu/<PLTF_FOLDER>/ssl/yourdomain.com/
   ```

2. Check certificate validity:
   ```bash
   openssl x509 -in /home/ubuntu/<PLTF_FOLDER>/ssl/yourdomain.com/fullchain_domain.crt -text -noout
   ```

3. Ensure certificate matches domain:
   ```bash
   openssl x509 -in /home/ubuntu/<PLTF_FOLDER>/ssl/yourdomain.com/fullchain_domain.crt -noout -subject
   ```

### Issue: Nginx Configuration Syntax Error

**Symptoms**: `nginx -t` fails with syntax errors

**Solutions**:
1. Check `deploy.ini` format:
   - Ensure no extra spaces in domain configuration
   - Verify colon separators are correct
   - Check for proper comma separation between domains

2. Manually inspect generated configuration:
   ```bash
   cat /tmp/<PLTF_FOLDER>-site
   ```

3. Test with minimal configuration first, then add domains incrementally

### Issue: Domain Not Accessible

**Symptoms**: Domain returns connection refused or timeout

**Solutions**:
1. Verify DNS points to correct server:
   ```bash
   dig yourdomain.com
   nslookup yourdomain.com
   ```

2. Check firewall allows HTTPS traffic:
   ```bash
   sudo ufw status
   sudo ufw allow 443/tcp
   ```

3. Verify nginx is listening on port 443:
   ```bash
   sudo netstat -tlnp | grep :443
   ```

4. Check nginx error logs:
   ```bash
   sudo tail -f /var/log/nginx/error.log
   ```

### Issue: Proxy Backend Unreachable

**Symptoms**: 502 Bad Gateway or 504 Gateway Timeout

**Solutions**:
1. Verify backend service is running:
   ```bash
   curl http://localhost:5000  # or your backend URL
   ```

2. Check backend logs for errors

3. Verify proxy_pass URL in configuration:
   ```bash
   grep proxy_pass /etc/nginx/sites-available/<PLTF_FOLDER>
   ```

4. Test backend connectivity from nginx server:
   ```bash
   telnet backend-host backend-port
   ```

## Security Considerations

### SSL/TLS Configuration

- Uses TLS 1.2 and 1.3 only (older versions disabled)
- Strong cipher suites configured
- Perfect Forward Secrecy enabled

### Certificate Management

- Keep private keys secure (chmod 600)
- Regularly renew certificates before expiration
- Use Let's Encrypt for automated renewal
- Monitor certificate expiration dates

### Proxy Security

- All proxy headers properly configured
- X-Forwarded-Proto prevents protocol downgrade attacks
- Host header validation prevents host header injection
- ModSecurity WAF protection on main domain

## Advanced Configuration

### Custom Location Blocks for Secondary Domains

To add custom location blocks to secondary domains, modify the `create_nginx_config()` function in `deployControlPlan.sh`:

```bash
# After the main location / block for secondary domain
cat >> /tmp/<PLTF_FOLDER>-site << EOF
    location /api/ {
        proxy_pass ${custom_api_backend};
        # Additional proxy settings
    }
EOF
```

### Load Balancing Multiple Backends

Configure multiple backend servers for a domain:

```ini
SECONDARY_DOMAINS=api.example.com:api.example.com:http://backend-pool
```

Then add upstream configuration in nginx:

```nginx
upstream backend-pool {
    least_conn;
    server backend1.local:8080;
    server backend2.local:8080;
    server backend3.local:8080;
}
```

### WebSocket Support

For secondary domains requiring WebSocket support, modify the generated configuration to include:

```nginx
proxy_http_version 1.1;
proxy_set_header Upgrade $http_upgrade;
proxy_set_header Connection "upgrade";
```

## Migration Guide

### Migrating from Hardcoded Configuration

If you previously had hardcoded domain configurations in `deployControlPlan.sh`:

1. **Identify all domains** currently configured
2. **Extract SSL certificate paths** for each domain
3. **Determine proxy_pass targets** for each domain
4. **Update deploy.ini** with new format:
   ```ini
   DOMAIN=primary-domain.com
   SECONDARY_DOMAINS=domain1:server_names1:proxy1,domain2:server_names2:proxy2
   ```
5. **Organize SSL certificates** into domain-specific directories
6. **Test configuration** with `nginx -t`
7. **Deploy** using `./deployControlPlan.sh deploy`

### Rollback Procedure

If issues occur after deployment:

1. **Restore previous nginx configuration**:
   ```bash
   sudo cp /etc/nginx/sites-available/<PLTF_FOLDER>.backup /etc/nginx/sites-available/<PLTF_FOLDER>
   ```

2. **Test and reload**:
   ```bash
   sudo nginx -t && sudo systemctl reload nginx
   ```

3. **Revert deploy.ini changes**:
   ```bash
   git checkout conf/deploy.ini
   ```

## Best Practices

1. **Always backup** configuration before changes:
   ```bash
   cp conf/deploy.ini conf/deploy.ini.backup
   sudo cp /etc/nginx/sites-available/<PLTF_FOLDER> /etc/nginx/sites-available/<PLTF_FOLDER>.backup
   ```

2. **Test in staging** environment first

3. **Use version control** for deploy.ini changes

4. **Document** each domain's purpose and backend

5. **Monitor** nginx logs after deployment:
   ```bash
   sudo tail -f /var/log/nginx/access.log /var/log/nginx/error.log
   ```

6. **Set up alerts** for certificate expiration

7. **Regular security audits** of SSL configuration:
   ```bash
   # Test SSL configuration
   openssl s_client -connect yourdomain.com:443 -tls1_2
   ```

## Related Documentation

- [DEPLOYMENT_GUIDE.md](./DEPLOYMENT_GUIDE.md) - General deployment procedures
- [NGINX_DYNAMIC_LOCATIONS.md](./NGINX_DYNAMIC_LOCATIONS.md) - Dynamic location management
- [ARCHITECTURE_GUIDE.md](./ARCHITECTURE_GUIDE.md) - System architecture overview
