# Service Management Guide

Use `scripts/services.sh` to manage the stack (Docker Compose).

## Prerequisites
- Docker + Docker Compose available on PATH
- Run commands from repo root

## Commands
- Start all services (backend, frontend, db, redis, minio):
  - `./scripts/services.sh up`
- Stop and remove containers:
  - `./scripts/services.sh down`
- Restart:
  - Backend: `./scripts/services.sh restart api` (alias: `backend`)
  - Frontend: `./scripts/services.sh restart web` (alias: `frontend`)
  - All: `./scripts/services.sh restart all`
- Logs (tail):
  - Backend: `./scripts/services.sh logs api`
  - Frontend: `./scripts/services.sh logs web`
- Status:
  - `./scripts/services.sh ps`

## Notes
- Commands wrap `docker compose` using `docker-compose.yml` in repo root.
- Use Ctrl+C to exit log tailing.
