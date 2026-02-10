#!/bin/bash
# Rollback Nginx Reverse Proxy Setup
# This script helps rollback to direct service access (without Nginx)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="$PROJECT_ROOT/.nginx-backup-$(date +%Y%m%d-%H%M%S)"

echo "=========================================="
echo "Nginx Rollback for InsightDOCv2"
echo "=========================================="
echo ""

# Confirm rollback
read -p "This will stop services and backup Nginx configuration. Continue? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Rollback cancelled."
    exit 0
fi
echo ""

# Step 1: Stop services
echo "[1/4] Stopping Docker services..."
cd "$PROJECT_ROOT"
docker compose down
echo "✓ Services stopped"
echo ""

# Step 2: Backup Nginx configuration
echo "[2/4] Backing up Nginx configuration..."
mkdir -p "$BACKUP_DIR"
cp -r "$PROJECT_ROOT/nginx" "$BACKUP_DIR/" 2>/dev/null || true
cp "$PROJECT_ROOT/docker-compose.yml" "$BACKUP_DIR/" 2>/dev/null || true
cp "$PROJECT_ROOT/backend/.env" "$BACKUP_DIR/backend.env" 2>/dev/null || true
cp "$PROJECT_ROOT/frontend/.env.local" "$BACKUP_DIR/frontend.env.local" 2>/dev/null || true
echo "✓ Configuration backed up to: $BACKUP_DIR"
echo ""

# Step 3: Provide rollback instructions
echo "[3/4] Rollback Instructions:"
echo "=========================================="
echo ""
echo "To restore direct backend/frontend access (bypassing Nginx):"
echo ""
echo "1. Edit docker-compose.yml and restore port mappings:"
echo "   backend:"
echo "     ports:"
echo "       - \"8000:8000\""
echo ""
echo "   frontend:"
echo "     ports:"
echo "       - \"3000:3000\""
echo ""
echo "   db:"
echo "     ports:"
echo "       - \"5432:5432\""
echo ""
echo "   redis:"
echo "     ports:"
echo "       - \"6379:6379\""
echo ""
echo "2. Update backend/.env:"
echo "   MINIO_ENDPOINT=localhost:9000"
echo "   BACKEND_CORS_ORIGINS=http://localhost:3000,http://localhost:8000"
echo ""
echo "3. Update frontend/.env.local:"
echo "   NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1"
echo ""
echo "4. Remove or comment out nginx service from docker-compose.yml"
echo ""
echo "5. Restart services:"
echo "   docker compose up -d"
echo ""
echo "=========================================="
echo ""

# Step 4: Offer to create a simple rollback compose file
echo "[4/4] Would you like to create a simple docker-compose file for rollback?"
read -p "Create rollback compose file? (y/N) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    cat > "$BACKUP_DIR/docker-compose-rollback.yml" << 'EOF'
# Simple docker-compose for direct access (no Nginx)
# Usage: docker-compose -f docker-compose-rollback.yml up -d

services:
  backend:
    build: ./backend
    container_name: softnix_ocr_backend
    ports:
      - "8000:8000"
    volumes:
      - ./backend:/app
    env_file:
      - ./backend/.env
    depends_on:
      - db
      - redis
    restart: unless-stopped

  celery_worker:
    build: ./backend
    container_name: softnix_ocr_celery
    command: celery -A app.celery_app worker --loglevel=info --concurrency=2
    volumes:
      - ./backend:/app
    env_file:
      - ./backend/.env
    depends_on:
      - db
      - redis
      - backend
    restart: unless-stopped

  frontend:
    build: ./frontend
    container_name: softnix_ocr_frontend
    ports:
      - "3000:3000"
    volumes:
      - ./frontend:/app
      - /app/node_modules
    env_file:
      - ./frontend/.env.local
    depends_on:
      - backend
    restart: unless-stopped

  db:
    image: postgres:15-alpine
    container_name: softnix_ocr_db
    ports:
      - "5432:5432"
    environment:
      - POSTGRES_USER=postgres
      - POSTGRES_PASSWORD=postgres
      - POSTGRES_DB=softnix_ocr
    volumes:
      - postgres_data:/var/lib/postgresql/data
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    container_name: softnix_ocr_redis
    ports:
      - "6379:6379"
    restart: unless-stopped

  minio:
    image: minio/minio
    container_name: softnix_ocr_minio
    ports:
      - "9000:9000"
      - "9001:9001"
    environment:
      - MINIO_ROOT_USER=minioadmin
      - MINIO_ROOT_PASSWORD=minioadmin
    command: server /data --console-address ":9001"
    volumes:
      - minio_data:/data
    restart: unless-stopped

volumes:
  postgres_data:
  minio_data:
EOF
    echo "✓ Rollback compose file created: $BACKUP_DIR/docker-compose-rollback.yml"
    echo ""
    echo "To use it:"
    echo "  cd $PROJECT_ROOT"
    echo "  cp $BACKUP_DIR/docker-compose-rollback.yml ./docker-compose.yml"
    echo "  docker compose up -d"
fi
echo ""

echo "=========================================="
echo "Rollback Complete!"
echo "=========================================="
echo ""
echo "Backup location: $BACKUP_DIR"
echo ""
echo "Current state: Services stopped, configuration backed up"
echo ""
echo "Next steps:"
echo "  1. Follow the rollback instructions above, OR"
echo "  2. Restart services with Nginx: docker compose up -d"
echo ""
