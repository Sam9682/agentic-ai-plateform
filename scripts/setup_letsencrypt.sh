#!/bin/bash

# Let's Encrypt SSL Certificate Setup for AI-SwAutoMorph

set -e

DOMAIN="www.swautomorph.com"
EMAIL="admin@swautomorph.com"
SSL_DIR="./ssl"

echo "🔐 Setting up Let's Encrypt SSL certificate for $DOMAIN..."

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "❌ This script must be run as root (use sudo)"
    exit 1
fi

# Install certbot if not installed
if ! command -v certbot &> /dev/null; then
    echo "📦 Installing certbot..."
    apt update
    apt install -y certbot
fi

# Stop nginx temporarily
echo "🛑 Stopping nginx temporarily..."
docker-compose stop nginx 2>/dev/null || true

# Generate certificate
echo "📜 Generating Let's Encrypt certificate..."
certbot certonly --standalone \
    --email "$EMAIL" \
    --agree-tos \
    --no-eff-email \
    -d "$DOMAIN"

# Copy certificates to ssl directory
echo "📁 Copying certificates..."
mkdir -p "$SSL_DIR"
cp "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" "$SSL_DIR/cert.pem"
cp "/etc/letsencrypt/live/$DOMAIN/privkey.pem" "$SSL_DIR/key.pem"

# Set proper permissions
chown $(stat -c '%U:%G' .) "$SSL_DIR/cert.pem" "$SSL_DIR/key.pem"
chmod 644 "$SSL_DIR/cert.pem"
chmod 600 "$SSL_DIR/key.pem"

# Restart services
echo "🚀 Restarting services..."
docker-compose up -d

echo "✅ Let's Encrypt SSL certificate installed successfully!"
echo "📅 Certificate expires: $(openssl x509 -enddate -noout -in "$SSL_DIR/cert.pem" | cut -d= -f2)"
echo ""
echo "🔄 Auto-renewal setup:"
echo "   Add to crontab: 0 12 * * * /usr/bin/certbot renew --quiet && docker-compose restart nginx"