#!/bin/bash

# SSL Certificate Generation Script for AI-SwAutoMorph

set -e

SSL_DIR="./ssl"
DOMAIN=${DOMAIN:-"softfluid.fr"}

echo "🔐 Generating SSL certificates for $DOMAIN..."

# Create SSL directory if it doesn't exist
mkdir -p "$SSL_DIR"

# Check if certificates already exist
if [ -f "$SSL_DIR/fullchain_domain.crt" ] && [ -f "$SSL_DIR/privateKey_domain.key" ]; then
    echo "⚠️  SSL certificates already exist. Use --force to regenerate."
    if [ "$1" != "--force" ]; then
        exit 0
    fi
    echo "🔄 Regenerating certificates..."
fi

# Generate private key
echo "🔑 Generating private key..."
openssl genrsa -out "$SSL_DIR/privateKey_domain.pem" 2048

# Generate certificate signing request
echo "📝 Generating certificate signing request..."
openssl req -new -key "$SSL_DIR/privateKey_domain.pem" -out "$SSL_DIR/csr.pem" -subj "/C=US/ST=State/L=City/O=softfluid/CN=$DOMAIN"

# Generate self-signed certificate (valid for 365 days)
echo "📜 Generating self-signed certificate..."
openssl x509 -req -in "$SSL_DIR/csr.pem" -signkey "$SSL_DIR/privateKey_domain.crt" -out "$SSL_DIR/certificate_domain.key" -days 365

# Set proper permissions
chmod 600 "$SSL_DIR/privateKey_domain.key"
chmod 644 "$SSL_DIR/fullchain_domain.crt"

# Clean up CSR file
rm "$SSL_DIR/csr.pem"

echo "✅ SSL certificates generated successfully!"
echo "📁 Certificate files:"
echo "   Certificate: $SSL_DIR/certificate_domain.cert"
echo "   Private Key: $SSL_DIR/privateKey_domain.key"
echo ""
echo "⚠️  Note: This is a self-signed certificate for development/testing."
echo "   For production, replace with certificates from a trusted CA."
echo ""
echo "🔧 To use with Let's Encrypt (production):"
echo "   1. Install certbot: sudo apt install certbot"
echo "   2. Generate certificate: sudo certbot certonly --standalone -d $DOMAIN"
echo "   3. Copy certificates to ssl/ directory"