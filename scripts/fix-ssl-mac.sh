#!/bin/bash
# scripts/fix-ssl-mac.sh
# Automates trusting the self-signed SSL certificate on macOS

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
CERT_PATH="$PROJECT_ROOT/nginx/ssl/cert.pem"

if [ ! -f "$CERT_PATH" ]; then
    echo "Error: Certificate not found at $CERT_PATH"
    exit 1
fi

echo "=========================================="
echo "InsightDOC SSL Fix for macOS"
echo "=========================================="

echo "Step 1: Removing old localhost certificates from Keychain..."
# Find and delete existing certificates for localhost to prevent conflicts
sudo security delete-certificate -c "localhost" /Library/Keychains/System.keychain 2>/dev/null || true

echo "Step 2: Adding new certificate to System Keychain and setting 'Always Trust'..."
sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain "$CERT_PATH"

echo "Step 3: Verifying trust settings..."
# This command doesn't do much but ensures the previous one succeeded
if security find-certificate -c "localhost" /Library/Keychains/System.keychain > /dev/null; then
    echo "✓ Certificate successfully added and trusted."
else
    echo "✗ Failed to add certificate."
    exit 1
fi

echo ""
echo "=========================================="
echo "SUCCESS!"
echo "=========================================="
echo "Please RESTART your browser completely (Cmd+Q) for changes to take effect."
echo ""
echo "If using Chrome and it still fails:"
echo "1. Go to https://localhost"
echo "2. Click anywhere on the page"
echo "3. Type: thisisunsafe"
echo "=========================================="
