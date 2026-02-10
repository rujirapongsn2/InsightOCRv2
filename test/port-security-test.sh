#!/bin/bash
# Port Security Test Script

echo "=========================================="
echo "Port Security Test - InsightDOCv2"
echo "=========================================="
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "Testing External Port Accessibility..."
echo ""

# Test ports that SHOULD be accessible
echo "Expected Accessible Ports:"
echo -n "  Port 80 (HTTP):    "
nc -zv localhost 80 2>&1 | grep -q succeeded && echo -e "${GREEN}✓ OPEN${NC}" || echo -e "${RED}✗ CLOSED${NC}"

echo -n "  Port 443 (HTTPS):  "
nc -zv localhost 443 2>&1 | grep -q succeeded && echo -e "${GREEN}✓ OPEN${NC}" || echo -e "${RED}✗ CLOSED${NC}"

echo -n "  Port 9000 (MinIO): "
nc -zv localhost 9000 2>&1 | grep -q succeeded && echo -e "${YELLOW}⚠ OPEN (Should close in production)${NC}" || echo -e "${GREEN}✓ CLOSED${NC}"

echo -n "  Port 9001 (MinIO Console): "
nc -zv localhost 9001 2>&1 | grep -q succeeded && echo -e "${YELLOW}⚠ OPEN (Should close in production)${NC}" || echo -e "${GREEN}✓ CLOSED${NC}"

echo ""
echo "Expected CLOSED Ports (Internal Only):"

# Test ports that should NOT be accessible
echo -n "  Port 8000 (Backend):  "
nc -zv localhost 8000 2>&1 | grep -q refused && echo -e "${GREEN}✓ BLOCKED${NC}" || echo -e "${RED}✗ EXPOSED (Security Risk!)${NC}"

echo -n "  Port 3000 (Frontend): "
nc -zv localhost 3000 2>&1 | grep -q refused && echo -e "${GREEN}✓ BLOCKED${NC}" || echo -e "${RED}✗ EXPOSED (Security Risk!)${NC}"

echo -n "  Port 5432 (PostgreSQL): "
nc -zv localhost 5432 2>&1 | grep -q refused && echo -e "${GREEN}✓ BLOCKED${NC}" || echo -e "${RED}✗ EXPOSED (CRITICAL SECURITY RISK!)${NC}"

echo -n "  Port 6379 (Redis):    "
nc -zv localhost 6379 2>&1 | grep -q refused && echo -e "${GREEN}✓ BLOCKED${NC}" || echo -e "${RED}✗ EXPOSED (CRITICAL SECURITY RISK!)${NC}"

echo ""
echo "=========================================="
echo "Test Complete"
echo "=========================================="
