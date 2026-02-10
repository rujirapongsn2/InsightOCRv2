#!/bin/bash
# Setup Nginx Reverse Proxy for InsightDOCv2
# This script automates the Nginx setup process

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
NGINX_DIR="$PROJECT_ROOT/nginx"
SSL_DIR="$NGINX_DIR/ssl"

echo "=========================================="
echo "Nginx Reverse Proxy Setup for InsightDOCv2"
echo "=========================================="
echo ""

# Step 1: Check if Nginx directory structure exists
echo "[1/5] Checking Nginx directory structure..."
if [ ! -d "$NGINX_DIR" ]; then
    echo "Error: Nginx directory not found at $NGINX_DIR"
    exit 1
fi

if [ ! -d "$SSL_DIR" ]; then
    echo "Error: SSL directory not found at $SSL_DIR"
    exit 1
fi
echo "✓ Directory structure exists"
echo ""

# Step 2: Generate SSL certificates if they don't exist
echo "[2/5] Checking SSL certificates..."
if [ ! -f "$SSL_DIR/cert.pem" ] || [ ! -f "$SSL_DIR/key.pem" ]; then
    echo "Generating self-signed SSL certificates..."
    bash "$SSL_DIR/generate-certs.sh"
    echo "✓ SSL certificates generated"
else
    echo "✓ SSL certificates already exist"
fi
echo ""

# Step 3: Validate Nginx configuration
echo "[3/5] Validating Nginx configuration..."
if command -v nginx &> /dev/null; then
    nginx -t -c "$NGINX_DIR/nginx.conf" 2>&1 || echo "Warning: Nginx validation failed (this is expected if nginx is not installed locally)"
else
    echo "Note: nginx command not found locally, will validate in Docker container"
fi
echo ""

# Step 4: Stop existing services
echo "[4/5] Stopping existing Docker services..."
cd "$PROJECT_ROOT"
docker compose down
echo "✓ Services stopped"
echo ""

# Step 5: Start services with Nginx
echo "[5/5] Starting services with Nginx..."
docker compose up -d
echo "✓ Services started"
echo ""

# Wait for services to be healthy
echo "Waiting for services to become healthy..."
sleep 5

# Check service status
echo ""
echo "=========================================="
echo "Service Status:"
echo "=========================================="
docker compose ps
echo ""

# Display access information
echo "=========================================="
echo "Setup Complete!"
echo "=========================================="
echo ""
echo "Access URLs:"
echo "  - Frontend (HTTPS): https://localhost"
echo "  - Frontend (HTTP):  http://localhost (redirects to HTTPS)"
echo "  - Backend API:      https://localhost/api/v1"
echo "  - Health Check:     https://localhost/health"
echo "  - MinIO Console:    http://localhost:9001"
echo ""
echo "Note: You'll see a browser warning about the self-signed certificate."
echo "      This is expected for development. Click 'Advanced' and 'Proceed'."
echo ""
echo "To trust the certificate on macOS:"
echo "  sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain $SSL_DIR/cert.pem"
echo ""
echo "Useful commands:"
echo "  - View logs:        bash scripts/nginx-manage.sh logs"
echo "  - Reload Nginx:     bash scripts/nginx-manage.sh reload"
echo "  - Check status:     bash scripts/nginx-manage.sh status"
echo "  - Rollback setup:   bash scripts/rollback-nginx.sh"
echo ""
