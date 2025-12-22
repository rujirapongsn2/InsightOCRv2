#!/bin/bash
# Generate self-signed SSL certificate for development

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CERT_PATH="$SCRIPT_DIR/cert.pem"
KEY_PATH="$SCRIPT_DIR/key.pem"

echo "Generating self-signed SSL certificate for InsightOCRv2..."

# Generate private key and certificate
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout "$KEY_PATH" \
  -out "$CERT_PATH" \
  -subj "/C=TH/ST=Bangkok/L=Bangkok/O=Softnix/OU=Development/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,DNS:*.localhost,IP:127.0.0.1"

# Set appropriate permissions
chmod 644 "$CERT_PATH"
chmod 600 "$KEY_PATH"

echo "SSL certificate generated successfully:"
echo "  Certificate: $CERT_PATH"
echo "  Private Key: $KEY_PATH"
echo ""
echo "To trust this certificate (macOS):"
echo "  sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain $CERT_PATH"
echo ""
echo "To trust this certificate (Linux):"
echo "  sudo cp $CERT_PATH /usr/local/share/ca-certificates/insightocr.crt"
echo "  sudo update-ca-certificates"
