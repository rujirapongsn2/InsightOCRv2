#!/bin/bash
# Nginx Management Helper Script
# Provides convenient commands for managing Nginx in Docker

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Helper function to print colored messages
print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if nginx container is running
check_nginx() {
    if docker ps --filter "name=softnix_ocr_nginx" --filter "status=running" | grep -q softnix_ocr_nginx; then
        return 0
    else
        return 1
    fi
}

# Show usage
show_usage() {
    echo "Nginx Management Helper for InsightOCRv2"
    echo ""
    echo "Usage: $0 <command>"
    echo ""
    echo "Commands:"
    echo "  test      - Test Nginx configuration"
    echo "  reload    - Reload Nginx configuration (graceful)"
    echo "  restart   - Restart Nginx container"
    echo "  logs      - View Nginx logs (access + error)"
    echo "  access    - View access logs only"
    echo "  error     - View error logs only"
    echo "  status    - Check Nginx container status"
    echo "  exec      - Execute command in Nginx container"
    echo "  help      - Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 logs           # View all logs"
    echo "  $0 logs -f        # Follow logs"
    echo "  $0 reload         # Reload configuration"
    echo "  $0 exec bash      # Open shell in container"
    echo ""
}

# Command handlers
cmd_test() {
    print_info "Testing Nginx configuration..."
    cd "$PROJECT_ROOT"

    if check_nginx; then
        docker exec softnix_ocr_nginx nginx -t
    else
        print_error "Nginx container is not running"
        exit 1
    fi
}

cmd_reload() {
    print_info "Reloading Nginx configuration..."
    cd "$PROJECT_ROOT"

    if check_nginx; then
        docker exec softnix_ocr_nginx nginx -s reload
        print_info "Configuration reloaded successfully"
    else
        print_error "Nginx container is not running"
        exit 1
    fi
}

cmd_restart() {
    print_info "Restarting Nginx container..."
    cd "$PROJECT_ROOT"

    docker compose restart nginx
    print_info "Nginx restarted successfully"
}

cmd_logs() {
    cd "$PROJECT_ROOT"

    if check_nginx; then
        print_info "Viewing Nginx logs (Ctrl+C to exit)..."
        docker logs ${1:--f} softnix_ocr_nginx
    else
        print_error "Nginx container is not running"
        exit 1
    fi
}

cmd_access_logs() {
    cd "$PROJECT_ROOT"

    if [ -f "$PROJECT_ROOT/nginx/logs/access.log" ]; then
        print_info "Viewing access logs (Ctrl+C to exit)..."
        tail ${1:--f} "$PROJECT_ROOT/nginx/logs/access.log"
    else
        print_warn "Access log file not found"
        exit 1
    fi
}

cmd_error_logs() {
    cd "$PROJECT_ROOT"

    if [ -f "$PROJECT_ROOT/nginx/logs/error.log" ]; then
        print_info "Viewing error logs (Ctrl+C to exit)..."
        tail ${1:--f} "$PROJECT_ROOT/nginx/logs/error.log"
    else
        print_warn "Error log file not found"
        exit 1
    fi
}

cmd_status() {
    cd "$PROJECT_ROOT"

    print_info "Checking Nginx status..."
    echo ""

    if check_nginx; then
        print_info "✓ Nginx container is running"
        echo ""
        echo "Container details:"
        docker ps --filter "name=softnix_ocr_nginx" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
        echo ""

        print_info "Health check:"
        docker inspect softnix_ocr_nginx --format='{{.State.Health.Status}}' 2>/dev/null || echo "No health check configured"
        echo ""

        print_info "Testing endpoints..."
        echo -n "  - Health endpoint: "
        if curl -s -k https://localhost/health > /dev/null 2>&1; then
            echo "✓ OK"
        else
            echo "✗ Failed"
        fi

        echo -n "  - Frontend:        "
        if curl -s -k https://localhost > /dev/null 2>&1; then
            echo "✓ OK"
        else
            echo "✗ Failed"
        fi
    else
        print_error "✗ Nginx container is not running"
        exit 1
    fi
}

cmd_exec() {
    cd "$PROJECT_ROOT"

    if check_nginx; then
        shift  # Remove first argument (command name)
        docker exec -it softnix_ocr_nginx "$@"
    else
        print_error "Nginx container is not running"
        exit 1
    fi
}

# Main command router
COMMAND="${1:-help}"

case "$COMMAND" in
    test)
        cmd_test
        ;;
    reload)
        cmd_reload
        ;;
    restart)
        cmd_restart
        ;;
    logs)
        shift
        cmd_logs "$@"
        ;;
    access)
        shift
        cmd_access_logs "$@"
        ;;
    error)
        shift
        cmd_error_logs "$@"
        ;;
    status)
        cmd_status
        ;;
    exec)
        cmd_exec "$@"
        ;;
    help|--help|-h)
        show_usage
        ;;
    *)
        print_error "Unknown command: $COMMAND"
        echo ""
        show_usage
        exit 1
        ;;
esac
