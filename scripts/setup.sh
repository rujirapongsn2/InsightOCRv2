#!/usr/bin/env bash
# =============================================================================
# InsightOCRv2 — One-command setup
# =============================================================================
# Quick start:
#   ./scripts/setup.sh
#
# What it does:
#   A. Checks prerequisites (Docker, RAM, disk, socket)
#   B. Generates secrets + writes .env files (idempotent)
#   C. Prompts for OCR endpoint if not set (required for document processing)
#   D. Builds + starts all services
#   E. Waits for health checks
#   F. Prints summary with URLs + admin credentials
#
# Flags:
#   --skip-ocr-prompt     Don't pause for OCR config; warn and continue
#   --no-build            Skip docker compose build (use existing images)
#   --reset-secrets       Regenerate all secrets (DESTRUCTIVE — overwrites .env)
#   --health-timeout SEC  Per-service health check timeout (default: 300)
#   -h, --help            Show this help
#
# Safe to re-run — skips work already done.
# =============================================================================

set -euo pipefail

# ── Defaults & flag parsing ─────────────────────────────────────────────────
SKIP_OCR_PROMPT=false
NO_BUILD=false
RESET_SECRETS=false
HEALTH_TIMEOUT=300

while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-ocr-prompt)    SKIP_OCR_PROMPT=true; shift ;;
        --no-build)           NO_BUILD=true; shift ;;
        --reset-secrets)      RESET_SECRETS=true; shift ;;
        --health-timeout)     HEALTH_TIMEOUT="$2"; shift 2 ;;
        -h|--help)            sed -n '1,30p' "$0"; exit 0 ;;
        *) echo "Unknown flag: $1" >&2; exit 2 ;;
    esac
done

# Color helpers (disabled if not a TTY)
if [[ -t 1 ]]; then
    GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RED=$'\033[31m'; BLUE=$'\033[34m'; BOLD=$'\033[1m'; RESET=$'\033[0m'
else
    GREEN=""; YELLOW=""; RED=""; BLUE=""; BOLD=""; RESET=""
fi

log()  { echo "${BLUE}›${RESET} $*"; }
ok()   { echo "${GREEN}✓${RESET} $*"; }
warn() { echo "${YELLOW}!${RESET} $*" >&2; }
err()  { echo "${RED}✗${RESET} $*" >&2; }
die()  { err "$*"; exit 1; }

# Locate project root (directory containing docker-compose.yml)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

echo ""
echo "${BOLD}InsightOCRv2 setup${RESET}"
echo "Project root: $PROJECT_ROOT"
echo ""

# ── Phase A: Prerequisites ──────────────────────────────────────────────────
log "Phase A: prerequisites"

# OS detection
OS="unknown"
case "$(uname -s)" in
    Darwin*) OS="macos" ;;
    Linux*)
        if grep -qi microsoft /proc/version 2>/dev/null; then OS="wsl"; else OS="linux"; fi
        ;;
    MINGW*|MSYS*|CYGWIN*) OS="windows" ;;
esac
ok "OS: $OS ($(uname -s) $(uname -r))"

# Docker binary
if ! command -v docker >/dev/null 2>&1; then
    err "Docker is not installed."
    case "$OS" in
        macos)   echo "  Install: https://docs.docker.com/desktop/install/mac-install/" ;;
        linux)   echo "  Install: sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin" ;;
        wsl)     echo "  Install Docker Desktop for Windows with WSL2 integration enabled" ;;
    esac
    die "Re-run this script after installing Docker."
fi
DOCKER_VERSION="$(docker --version | grep -oE 'version [0-9]+\.' | grep -oE '[0-9]+' || echo 0)"
if [[ "$DOCKER_VERSION" -lt 24 ]]; then
    die "Docker version $DOCKER_VERSION < 24. Please upgrade: https://docs.docker.com/engine/install/"
fi
ok "Docker $(docker --version | sed 's/Docker version //; s/, build.*//')"

# Docker daemon running
if ! docker info >/dev/null 2>&1; then
    warn "Docker daemon not responding."
    case "$OS" in
        macos)
            log "Attempting to start Docker Desktop..."
            open -a Docker 2>/dev/null || true
            for _ in {1..30}; do
                docker info >/dev/null 2>&1 && break
                sleep 2
                printf "."
            done
            echo ""
            docker info >/dev/null 2>&1 || die "Docker Desktop didn't come up. Start it manually and re-run."
            ;;
        linux|wsl)
            err "Start Docker:"
            echo "  sudo systemctl start docker"
            echo "  # or: sudo service docker start"
            die "Re-run after Docker is running."
            ;;
    esac
fi
ok "Docker daemon is running"

# docker compose v2 plugin
COMPOSE_CMD=""
if docker compose version >/dev/null 2>&1; then
    COMPOSE_CMD="docker compose"
    ok "docker compose v2 available"
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_CMD="docker-compose"
    warn "Using legacy docker-compose (v1). Consider installing compose v2 plugin."
else
    die "Neither 'docker compose' plugin nor docker-compose found."
fi

# RAM check (warn only)
RAM_GB=0
case "$OS" in
    macos) RAM_GB=$(( $(sysctl -n hw.memsize 2>/dev/null || echo 0) / 1024 / 1024 / 1024 )) ;;
    linux|wsl) RAM_GB=$(awk '/MemTotal/ {printf "%d", $2/1024/1024}' /proc/meminfo 2>/dev/null || echo 0) ;;
esac
if [[ "$RAM_GB" -gt 0 && "$RAM_GB" -lt 8 ]]; then
    warn "Host RAM is ${RAM_GB} GB — recommend ≥ 8 GB. Services may OOM under load."
elif [[ "$RAM_GB" -ge 8 ]]; then
    ok "Host RAM: ${RAM_GB} GB"
fi

# Disk space (block if < 10 GB)
DISK_AVAIL_GB=$(df -Pg "$PROJECT_ROOT" 2>/dev/null | awk 'NR==2 {print $4}' || echo 0)
if [[ "$DISK_AVAIL_GB" -lt 10 ]]; then
    die "Free disk ${DISK_AVAIL_GB} GB < 10 GB minimum. Clear space and re-run."
fi
ok "Free disk: ${DISK_AVAIL_GB} GB"

# Docker socket access (Linux: needs docker group)
if [[ "$OS" == "linux" || "$OS" == "wsl" ]] && [[ ! -w /var/run/docker.sock ]]; then
    err "Cannot access /var/run/docker.sock."
    echo "  Fix: add your user to the docker group and re-login:"
    echo "    sudo usermod -aG docker \$USER"
    echo "    # log out + log back in, then re-run this script"
    die "Cannot proceed without docker socket access."
fi
[[ -w /var/run/docker.sock ]] && ok "Docker socket accessible"

# Root warning
if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
    warn "Running as root — sandbox container security is weakened. Use a non-root user if possible."
fi

echo ""

# ── Phase B: Secrets + env files ────────────────────────────────────────────
log "Phase B: environment files"

# Secret generation — prefer openssl, fall back to /dev/urandom
gen_secret() {
    local len="${1:-32}"
    if command -v openssl >/dev/null 2>&1; then
        openssl rand -hex "$len" 2>/dev/null
    else
        head -c "$len" /dev/urandom | od -An -tx1 | tr -d ' \n'
    fi
}

# Root .env
if [[ -f .env ]] && [[ "$RESET_SECRETS" == "false" ]]; then
    ok ".env exists (skipping — use --reset-secrets to regenerate)"
else
    if [[ ! -f .env.example ]]; then
        die ".env.example missing — git pull may be incomplete."
    fi
    log "Generating secrets + writing .env"
    cp .env.example .env
    SECRET_KEY=$(gen_secret 32);        sed -i.bak "s|^SECRET_KEY=.*|SECRET_KEY=${SECRET_KEY}|" .env
    DB_PASSWORD=$(gen_secret 16);       sed -i.bak "s|^DB_PASSWORD=.*|DB_PASSWORD=${DB_PASSWORD}|" .env
    REDIS_PASSWORD=$(gen_secret 16);    sed -i.bak "s|^REDIS_PASSWORD=.*|REDIS_PASSWORD=${REDIS_PASSWORD}|" .env
    MINIO_PASS=$(gen_secret 16);        sed -i.bak "s|^MINIO_ROOT_PASSWORD=.*|MINIO_ROOT_PASSWORD=${MINIO_PASS}|" .env
    rm -f .env.bak
    ok "Secrets generated + .env written"
fi

# backend/.env
if [[ -f backend/.env ]] && [[ "$RESET_SECRETS" == "false" ]]; then
    ok "backend/.env exists (skipping — use --reset-secrets to regenerate)"
else
    if [[ ! -f backend/.env.example ]]; then
        die "backend/.env.example missing — git pull may be incomplete."
    fi
    cp backend/.env.example backend/.env
    ok "backend/.env written from template"
fi

echo ""

# ── Phase C: OCR endpoint config (REQUIRED) ─────────────────────────────────
log "Phase C: OCR service configuration"

OCR_SET=false
if grep -qE "^OCR_ENDPOINT=.+" backend/.env 2>/dev/null; then
    if [[ "$(awk -F= '/^OCR_ENDPOINT=/{print $2}' backend/.env)" != "" ]]; then
        OCR_SET=true
    fi
fi

if [[ "$OCR_SET" == "true" ]]; then
    ok "OCR_ENDPOINT already configured"
elif [[ "$SKIP_OCR_PROMPT" == "true" ]]; then
    warn "OCR_ENDPOINT not set. System will start but document processing won't work."
    warn "Configure later: edit backend/.env and restart backend."
else
    echo ""
    echo "${BOLD}External OCR service is required for document processing.${RESET}"
    echo "Format: https://host:port/ai-process-file"
    echo "Press ENTER to skip (configure later) or paste your endpoint:"
    read -r USER_OCR_ENDPOINT
    if [[ -n "$USER_OCR_ENDPOINT" ]]; then
        sed -i.bak "s|^OCR_ENDPOINT=.*|OCR_ENDPOINT=${USER_OCR_ENDPOINT}|" backend/.env
        rm -f backend/.env.bak
        ok "OCR_ENDPOINT set"
        echo ""
        echo "API token (Bearer auth, press ENTER to skip):"
        read -r USER_API_TOKEN
        if [[ -n "$USER_API_TOKEN" ]]; then
            sed -i.bak "s|^API_TOKEN=.*|API_TOKEN=${USER_API_TOKEN}|" backend/.env
            rm -f backend/.env.bak
            ok "API_TOKEN set"
        fi
    else
        warn "Skipped — document processing won't work until OCR_ENDPOINT is set."
    fi
fi

echo ""

# ── Phase D: Build + start ──────────────────────────────────────────────────
log "Phase D: build + start services"

if [[ "$NO_BUILD" == "true" ]]; then
    warn "Skipping build (--no-build)"
else
    log "Building images (first run downloads + builds sandbox: ~2-3 min)..."
    $COMPOSE_CMD build --pull 2>&1 | sed 's/^/  /'
    ok "Images built"
fi

log "Starting services..."
$COMPOSE_CMD up -d 2>&1 | sed 's/^/  /'
ok "Services started"

echo ""

# ── Phase E: Health checks ──────────────────────────────────────────────────
log "Phase E: waiting for health (timeout ${HEALTH_TIMEOUT}s per service)"

check_health() {
    local name="$1" check_cmd="$2"
    local elapsed=0
    printf "  %-15s " "$name"
    while [[ "$elapsed" -lt "$HEALTH_TIMEOUT" ]]; do
        if eval "$check_cmd" >/dev/null 2>&1; then
            echo "${GREEN}✓ healthy${RESET}"
            return 0
        fi
        printf "."
        sleep 5
        elapsed=$((elapsed + 5))
    done
    echo ""
    err "$name did not become healthy within ${HEALTH_TIMEOUT}s"
    return 1
}

# Per-service health checks
HEALTH_FAILURES=0

check_health "db"       "docker exec softnix_ocr_db pg_isready -U insightocr_user -d softnix_ocr" || HEALTH_FAILURES=$((HEALTH_FAILURES+1))
check_health "redis"    "docker exec softnix_ocr_redis redis-cli -a \$(awk -F= '/^REDIS_PASSWORD=/{print \$2}' .env) ping | grep -q PONG" || HEALTH_FAILURES=$((HEALTH_FAILURES+1))
check_health "backend"  "curl -sf http://localhost:8000/health" || HEALTH_FAILURES=$((HEALTH_FAILURES+1))
check_health "frontend" "curl -sfI http://localhost:80/ | grep -q '200 OK'" || HEALTH_FAILURES=$((HEALTH_FAILURES+1))

echo ""

# ── Phase F: Summary ────────────────────────────────────────────────────────
if [[ "$HEALTH_FAILURES" -gt 0 ]]; then
    warn "$HEALTH_FAILURES service(s) failed health check — see logs:"
    echo "  $COMPOSE_CMD logs db redis backend frontend"
    echo ""
fi

# Look up or generate admin password (first-run creates admin@softnix.ai with default 'admin' — recommend change)
DEFAULT_PASS="admin"
if grep -qE "^FIRST_SUPERUSER_PASSWORD" backend/.env 2>/dev/null; then
    DEFAULT_PASS="$(awk -F= '/^FIRST_SUPERUSER_PASSWORD=/{print $2}' backend/.env)"
fi

cat <<EOF
${GREEN}${BOLD}✓ InsightOCRv2 ready${RESET}

  ${BOLD}Web UI:${RESET}       http://localhost
  ${BOLD}API docs:${RESET}     http://localhost/api/v1/docs
  ${BOLD}Admin login:${RESET}  admin@softnix.ai
  ${BOLD}Admin pass:${RESET}   ${DEFAULT_PASS}  ${YELLOW}(CHANGE in /profile after first login)${RESET}

  ${BOLD}Next steps:${RESET}
  1. Open http://localhost in your browser
  2. Change admin password in /profile
  3. Configure OCR endpoint in /settings if not done above
  4. See ${BOLD}INSTALL.md${RESET} for production hardening (TLS, backups)

EOF
