#!/usr/bin/env bash
set -euo pipefail

COMPOSE="docker compose"

usage() {
  cat <<'EOF'
Softnix InsightOCR service helper

Usage:
  services.sh up           # start all services (frontend, backend, db, redis, minio)
  services.sh down         # stop and remove containers
  services.sh restart api  # restart backend only
  services.sh restart web  # restart frontend only
  services.sh restart all  # restart all containers
  services.sh rebuild api  # rebuild and restart backend only
  services.sh rebuild web  # rebuild and restart frontend only
  services.sh rebuild all  # rebuild and restart all services
  services.sh logs api     # tail backend logs
  services.sh logs web     # tail frontend logs
  services.sh ps           # show container status

Shortcuts:
  api  = backend
  web  = frontend
  worker = celery_worker

EOF
}

require_compose() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "docker is not installed or not on PATH" >&2
    exit 1
  fi
}

restart_service() {
  local svc="$1"
  echo "Restarting ${svc}..."
  $COMPOSE restart "$svc"
}

logs_service() {
  local svc="$1"
  echo "Tailing logs for ${svc} (Ctrl+C to stop)..."
  $COMPOSE logs -f "$svc"
}

rebuild_service() {
  local svc="$1"
  echo "Rebuilding and restarting ${svc}..."
  $COMPOSE up -d --build --no-deps "$svc"
}

case "${1:-}" in
  up)
    require_compose
    $COMPOSE up -d --build
    ;;
  down)
    require_compose
    $COMPOSE down
    ;;
  restart)
    require_compose
    svc="${2:-all}"
    case "$svc" in
      api|backend) restart_service backend ;;
      web|frontend) restart_service frontend ;;
      worker|celery) restart_service celery_worker ;;
      all) $COMPOSE restart ;;
      *) echo "Unknown service '$svc'"; usage; exit 1 ;;
    esac
    ;;
  rebuild)
    require_compose
    svc="${2:-all}"
    case "$svc" in
      api|backend) rebuild_service backend ;;
      web|frontend) rebuild_service frontend ;;
      worker|celery) rebuild_service celery_worker ;;
      all) $COMPOSE up -d --build ;;
      *) echo "Unknown service '$svc'"; usage; exit 1 ;;
    esac
    ;;
  logs)
    require_compose
    svc="${2:-}"
    case "$svc" in
      api|backend) logs_service backend ;;
      web|frontend) logs_service frontend ;;
      worker|celery) logs_service celery_worker ;;
      *)
        echo "Specify api|backend or web|frontend for logs" >&2
        exit 1
        ;;
    esac
    ;;
  ps)
    require_compose
    $COMPOSE ps
    ;;
  -h|--help|help|"")
    usage
    ;;
  *)
    echo "Unknown command '$1'" >&2
    usage
    exit 1
    ;;
esac
