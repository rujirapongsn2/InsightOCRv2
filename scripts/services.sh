#!/usr/bin/env bash
set -euo pipefail

COMPOSE="docker compose"

usage() {
  cat <<'EOF'
Softnix InsightDOC service helper

Usage:
  services.sh up           # start all services (frontend, backend, db, redis, minio)
  services.sh down         # stop and remove containers
  services.sh update       # pull latest code and refresh the running stack
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
  if [ "$svc" = "backend" ] || [ "$svc" = "frontend" ]; then
    echo "Refreshing nginx upstreams..."
    $COMPOSE restart nginx
  fi
  wait_for_service_group "$svc"
}

wait_for_service_group() {
  local svc="$1"
  case "$svc" in
    backend)
      wait_for_healthy softnix_ocr_backend
      wait_for_healthy softnix_ocr_nginx
      ;;
    frontend)
      wait_for_healthy softnix_ocr_frontend
      wait_for_healthy softnix_ocr_nginx
      ;;
    celery_worker)
      wait_for_healthy softnix_ocr_backend
      ;;
    all)
      wait_for_healthy softnix_ocr_backend
      wait_for_healthy softnix_ocr_frontend
      wait_for_healthy softnix_ocr_nginx
      ;;
  esac
}

wait_for_healthy() {
  local container_name="$1"
  local timeout_seconds="${2:-180}"
  local elapsed=0
  local status=""

  while [ "$elapsed" -lt "$timeout_seconds" ]; do
    status="$(docker inspect --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_name" 2>/dev/null || true)"
    case "$status" in
      healthy|running)
        return 0
        ;;
      unhealthy|exited|dead)
        echo "${container_name} is ${status}" >&2
        return 1
        ;;
    esac

    sleep 3
    elapsed=$((elapsed + 3))
  done

  echo "Timed out waiting for ${container_name} to become healthy" >&2
  return 1
}

write_build_info() {
  local commit_sha="$1"
  local short_commit_sha="${commit_sha:0:7}"
  local branch_name="${2:-unknown}"
  local updated_at
  updated_at="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

  cat > backend/.build-info.json <<EOF
{"commit_sha":"${commit_sha}","short_commit_sha":"${short_commit_sha}","branch":"${branch_name}","updated_at":"${updated_at}"}
EOF
}

update_stack() {
  require_compose
  if ! command -v git >/dev/null 2>&1; then
    echo "git is not installed or not on PATH" >&2
    exit 1
  fi

  local before_sha after_sha branch_name
  before_sha="$(git rev-parse HEAD)"
  branch_name="$(git branch --show-current)"
  branch_name="${branch_name:-unknown}"

  echo "Fetching latest code from origin..."
  git fetch origin --prune

  echo "Pulling latest changes..."
  git pull --rebase --autostash

  after_sha="$(git rev-parse HEAD)"
  write_build_info "$after_sha" "$branch_name"

  echo "Rebuilding application services..."
  $COMPOSE up -d --build backend celery_worker frontend gateway

  echo "Refreshing nginx..."
  $COMPOSE restart nginx

  echo "Waiting for services to become healthy..."
  wait_for_healthy softnix_ocr_backend
  wait_for_healthy softnix_ocr_frontend
  wait_for_healthy softnix_ocr_nginx

  if [ "$before_sha" = "$after_sha" ]; then
    echo "Already up to date."
  else
    echo "Updated to commit ${after_sha:0:7}"
  fi

  echo "Stack is ready."
}

case "${1:-}" in
  up)
    require_compose
    $COMPOSE up -d --build
    $COMPOSE restart nginx
    wait_for_service_group all
    ;;
  down)
    require_compose
    $COMPOSE down
    ;;
  update)
    update_stack
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
      all)
        $COMPOSE up -d --build
        echo "Refreshing nginx upstreams..."
        $COMPOSE restart nginx
        wait_for_service_group all
        ;;
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
