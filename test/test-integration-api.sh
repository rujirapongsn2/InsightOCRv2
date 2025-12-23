#!/bin/bash
# Integration API Test Script

set -e

echo "=========================================="
echo "Integration API Test"
echo "=========================================="
echo ""

# Get auth token from user
if [ -z "$TOKEN" ]; then
    echo "Please set TOKEN environment variable first:"
    echo "  export TOKEN='your-jwt-token'"
    echo ""
    echo "Or run: TOKEN='your-token' bash $0"
    exit 1
fi

API_BASE="https://localhost/api/v1"

echo "Testing Integration CRUD Operations..."
echo ""

# Test 1: Get all integrations
echo "[1/5] GET /integrations - List all integrations"
RESPONSE=$(curl -k -s -w "\n%{http_code}" -X GET "$API_BASE/integrations" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json")

HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | sed '$d')

if [ "$HTTP_CODE" = "200" ]; then
    echo "✓ Success (200 OK)"
    echo "Response: $BODY" | jq '.' 2>/dev/null || echo "$BODY"
else
    echo "✗ Failed ($HTTP_CODE)"
    echo "$BODY"
fi
echo ""

# Test 2: Get active integrations
echo "[2/5] GET /integrations/active - List active integrations"
RESPONSE=$(curl -k -s -w "\n%{http_code}" -X GET "$API_BASE/integrations/active" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json")

HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | sed '$d')

if [ "$HTTP_CODE" = "200" ]; then
    echo "✓ Success (200 OK)"
    echo "Response: $BODY" | jq '. | length' 2>/dev/null && echo "Active integrations count"
else
    echo "✗ Failed ($HTTP_CODE)"
    echo "$BODY"
fi
echo ""

# Test 3: Create new integration
echo "[3/5] POST /integrations - Create new integration"
RESPONSE=$(curl -k -s -w "\n%{http_code}" -X POST "$API_BASE/integrations" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Test API Integration",
    "type": "api",
    "description": "Test integration created via API",
    "status": "active",
    "config": {
      "method": "POST",
      "endpoint": "https://example.com/api/webhook",
      "authHeader": "Bearer test-token"
    }
  }')

HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | sed '$d')

if [ "$HTTP_CODE" = "201" ]; then
    echo "✓ Success (201 Created)"
    INTEGRATION_ID=$(echo "$BODY" | jq -r '.id' 2>/dev/null)
    echo "Created integration ID: $INTEGRATION_ID"
    echo "$BODY" | jq '.' 2>/dev/null || echo "$BODY"
else
    echo "✗ Failed ($HTTP_CODE)"
    echo "$BODY"
    INTEGRATION_ID=""
fi
echo ""

# Test 4: Update integration (if created)
if [ -n "$INTEGRATION_ID" ]; then
    echo "[4/5] PUT /integrations/{id} - Update integration"
    RESPONSE=$(curl -k -s -w "\n%{http_code}" -X PUT "$API_BASE/integrations/$INTEGRATION_ID" \
      -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" \
      -d '{
        "name": "Test API Integration (Updated)",
        "description": "Updated description",
        "status": "paused"
      }')

    HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
    BODY=$(echo "$RESPONSE" | sed '$d')

    if [ "$HTTP_CODE" = "200" ]; then
        echo "✓ Success (200 OK)"
        echo "$BODY" | jq '.' 2>/dev/null || echo "$BODY"
    else
        echo "✗ Failed ($HTTP_CODE)"
        echo "$BODY"
    fi
    echo ""
else
    echo "[4/5] SKIPPED - No integration to update"
    echo ""
fi

# Test 5: Delete integration (if created)
if [ -n "$INTEGRATION_ID" ]; then
    echo "[5/5] DELETE /integrations/{id} - Delete integration"
    RESPONSE=$(curl -k -s -w "\n%{http_code}" -X DELETE "$API_BASE/integrations/$INTEGRATION_ID" \
      -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json")

    HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
    BODY=$(echo "$RESPONSE" | sed '$d')

    if [ "$HTTP_CODE" = "204" ]; then
        echo "✓ Success (204 No Content)"
    else
        echo "✗ Failed ($HTTP_CODE)"
        echo "$BODY"
    fi
    echo ""
else
    echo "[5/5] SKIPPED - No integration to delete"
    echo ""
fi

echo "=========================================="
echo "Test Complete"
echo "=========================================="
