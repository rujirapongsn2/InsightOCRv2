# Repository Guidelines

## Project Structure & Module Organization
- Root: `docker-compose.yml` orchestrates FastAPI backend, Next.js frontend, Postgres, Redis, and MinIO.
- Backend (`backend/`): FastAPI app lives under `backend/app/` (`main.py`, `api/`, `models/`, `schemas/`, `services/`, `db/`). Media uploads are kept in `backend/uploads/`.
- Frontend (`frontend/`): Next.js 16 + TypeScript with app router (`frontend/app/`), shared UI in `frontend/components/`, utilities in `frontend/lib/`, static assets in `frontend/public/`.

## Build, Test, and Development Commands
- Full stack (recommended): `docker compose up --build` to start API on `:8000` and web on `:3000` with Postgres/Redis/MinIO.
- Backend local: `cd backend && pip install -r requirements.txt && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`.
- Frontend local: `cd frontend && npm install && npm run dev` (build with `npm run build`, serve with `npm start`).
- Lint frontend: `cd frontend && npm run lint`.

## Coding Style & Naming Conventions
- Python: follow PEP 8; 4-space indents; snake_case for functions/vars/modules, PascalCase for Pydantic models and SQLAlchemy classes. Type hints expected across new code.
- TypeScript/React: camelCase for functions/vars, PascalCase for components; keep components in `components/` and colocate styles. Prefer functional components and hooks.
- Styling: Tailwind v4 is available; reuse shared utility classes instead of ad-hoc inline styles.
- Imports: absolute paths for stable layers (`app.api`, `app.services`), relative imports for nearby modules.

## Testing Guidelines
- Current repo has no automated tests—add them alongside new features.
- Backend: prefer `pytest`; name files `test_*.py`; mock external services (Redis, MinIO, OpenAI).
- Frontend: use React Testing Library + Jest/Playwright; name files `*.test.tsx`; cover component behavior and API integration surfaces.
- Aim for coverage around parsing, OCR flows, and error handling; include sample payloads/fixtures.
- After completing major features or Quickwin items, document the manual verification steps you used in `QUICKWIN-TEST.md`.

## Commit & Pull Request Guidelines
- If/when Git is initialized, use concise, imperative messages; Conventional Commits (`feat:`, `fix:`, `chore:`) are preferred for changelog clarity.
- PRs should describe scope, link issues/tasks, and list verification steps. Include screenshots or recordings for UI changes and note any env/config updates.
- Keep PRs narrowly scoped (backend vs frontend) and mention any schema changes or new env vars (`DATABASE_URL`, `REDIS_URL`, `MINIO_*`, `NEXT_PUBLIC_API_URL`).

## Security & Configuration Tips
- Do not commit secrets or .env files; mirror needed variables from `docker-compose.yml`.
- Be mindful of uploaded files in `backend/uploads/`; add ignores for local artifacts if necessary.
- When working locally without Docker, ensure Postgres/Redis/MinIO endpoints match the expected URLs or override via env vars.
