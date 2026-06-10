# QUICKWIN TEST

Date: 2026-03-30

## Manual Verification

1. Static checks
   - Ran `python -m py_compile` on updated backend modules including `external.py`, `permissions.py`, `api.py`, `documents.py`, `jobs.py`, and schemas.
   - Ran `git diff --check`.
   - Ran `bash -n scripts/services.sh`.

2. Rebuild and runtime
   - Ran `./scripts/services.sh rebuild all`.
   - Confirmed `backend`, `frontend`, and `nginx` return to healthy/running state.
   - Confirmed `https://127.0.0.1/health` returns `200 {"status":"ok"}`.

3. External API
   - Confirmed `GET /api/v1/external/jobs` returns `200` with job list using a personal access token.
   - Confirmed `GET /api/v1/external/schemas` returns `200` with schema list using a personal access token.
   - Confirmed `GET /api/v1/external/integrations` returns `200` with active integrations using a personal access token.
   - Confirmed `/api/v1/openapi.json` includes the `/api/v1/external/...` routes and schemas.

4. Profile page
   - Confirmed `https://127.0.0.1/profile` contains the new `API Workflow Docs` section and endpoint examples.
   - Confirmed `https://127.0.0.1/profile` contains the new `AI Agent Skill Package` section with a single `Download Softnix-InsightDOC.zip` action.
   - Confirmed the package preview shows `SKILL.md`, `.env`, `README.md`, and `scripts/insightocr.sh`.
   - Confirmed the `/profile` page renders without the previous React hydration error after moving browser-only URL detection behind client mount.

5. Skill package download
   - Confirmed `GET /api/v1/users/me/agent-skill-pack` returns `200` with `Content-Type: application/zip`.
   - Confirmed the downloaded file name is `Softnix-InsightDOC.zip`.
   - Confirmed the zip contains:
     - `Softnix-InsightDOC/SKILL.md`
     - `Softnix-InsightDOC/.env`
     - `Softnix-InsightDOC/README.md`
     - `Softnix-InsightDOC/scripts/insightocr.sh`
   - Confirmed `SKILL.md` contains the standard frontmatter and InsightDOC workflow instructions.
   - Confirmed `.env` contains editable placeholders for token, API URLs, defaults, and `CURL_INSECURE`.
   - Confirmed the helper script resolves `job_name`, `schema_name`, and `integration_name` to UUIDs automatically, with exact-match-first and partial-match fallback behavior.

6. End-to-end agent workflow
   - Used a personal access token against the `Comply TOR` job flow.
   - Confirmed `GET /api/v1/external/jobs` returned the `Comply TOR` job and `GET /api/v1/external/integrations` returned the `Comply TOR` integration.
   - Confirmed `GET /api/v1/external/jobs/{job_id}/documents` returned the expected two reviewed documents.
   - Confirmed both documents through `POST /api/v1/external/documents/{document_id}/decision` with `decision=confirm`.
   - Sent the confirmed job through `POST /api/v1/external/jobs/{job_id}/send-integration` with `integration_name=Comply TOR`.
   - Verified the send call returned `200` and a new success result was recorded in `GET /api/v1/integrations/results`.

## Notes

- `scripts/services.sh rebuild all` now restarts `nginx` and waits for health checks, preventing stale upstream IPs from causing `502 Bad Gateway` after container recreation.
- Local HTTPS still uses a self-signed certificate, so local `curl` verification used `-k`.
- Long-running integration calls initially hit the default `nginx` `proxy_read_timeout` of 60 seconds and surfaced as `504 Gateway Timeout` even though the backend job completed successfully. Added longer `nginx` timeouts for integration send routes and re-verified the full `Comply TOR` flow successfully.

---

Date: 2026-06-10

## Manual Verification - AI-Assisted Schema Suggestion

1. Static checks
   - Ran `python3 -m py_compile backend/app/initial_ai_settings.py backend/app/services/ai_suggestion_service.py backend/app/api/v1/endpoints/schemas.py`.

2. Rebuild and runtime
   - Ran `docker compose up -d --build --no-deps backend celery_worker`.
   - Confirmed backend startup log includes `Synced default AI setting: Softnix GenAI`.

3. AI settings sync
   - Confirmed runtime `AI_PROVIDER_URL` and default `ai_settings` URL both point to `https://genai.softnix.ai/external/api/completion-messages`.
   - Confirmed the runtime env key and DB default provider key hashes match, without printing the secret.

4. AI provider check
   - Ran `AISuggestionService.test_ai_connection()` inside the backend container.
   - After rotating `AI_PROVIDER_KEY`, confirmed the runtime env key and DB default provider key hashes match.
   - Confirmed `POST /api/v1/ai-settings/suggest-fields` through `localhost:3000` returns `200` with suggested fields `invoice_number`, `date`, and `total`.
   - Confirmed JSON Schema responses from the AI provider are normalized to snake_case names and mapped to app field types such as `date` and `currency`.

---

Date: 2026-06-10

## Manual Verification - Document Processing Queue

1. Redis/Celery auth
   - Found Celery and backend were using `redis://redis:6379/0` while Redis requires authentication.
   - Updated Docker Compose so backend and celery worker receive a password-authenticated `REDIS_URL` from `REDIS_PASSWORD`.
   - Recreated backend and celery worker.
   - Confirmed backend sees a Redis URL with `redis_has_password=True` without printing the password.
   - Confirmed celery worker logs show `Connected to redis://:**@redis:6379/0` and `ready`.

2. Process endpoint
   - Retested `POST /api/v1/documents/{document_id}/process` through `localhost:3000`.
   - Confirmed it returns `200` with a Celery `task_id`, so the previous `Failed to start processing` queue error is fixed.

3. OCR provider auth
   - After updating Settings `api_token`, confirmed `GET https://111.223.37.41:9001/me` returns `200` with active OCR/AI processing scopes.
   - Retested `POST /api/v1/documents/{document_id}/process` through `localhost:3000`; it returned `200` with a Celery `task_id`.
   - Confirmed the background task progressed through OCR and structured extraction.
   - Confirmed `GET /api/v1/documents/{document_id}/task-status` returns `status=extraction_completed`, `page_count=1`, no processing error, and extracted data.

---

## Agentic Document Processing Phase 1 Tests

Date: 2026-05-05

1. Mock ERP/CRM service
   - Added `backend/test/mock_external_api.py` with mock ERP product, CRM customer, quotation, and workflow webhook endpoints.
   - Added `test/test_mock_external_api.py`.
   - Ran `python test/test_mock_external_api.py`.
   - Confirmed 5 tests passed.

2. Agent tool unit tests
   - Added `test/test_agent_tools.py`.
   - Covered Phase 1 document tools: `list_documents`, `get_document_detail`, `search_documents`, `compare_documents`, `update_document_field`, `approve_document`, `reject_document`, and `bulk_approve`.
   - Covered Phase 1 integration tools: `list_integrations`, `call_api_integration`, and `send_to_workflow`.
   - Ran `python test/test_agent_tools.py`.
   - Confirmed 13 tests passed.

3. Explicitly skipped
   - E2E quotation workflow test was skipped by request.

## Agentic Document Processing Phase 2 Memory Tests

Date: 2026-05-05

1. Memory tools
   - Added `backend/app/agent/tools/memory_tools.py`.
   - Implemented `save_memory`, `recall_memory`, `list_memories`, and `forget_memory`.
   - Confirmed memory tools are registered under the `memory` category.
   - Confirmed `forget_memory` remains confirmation-gated through existing confirmation rules.

2. Memory context and UI
   - Updated agent loop registration so memory tools are available to the LLM.
   - Updated system prompt rules to treat memories as hints only and never as source of truth.
   - Added read-only Memory inspector to `AgentPanel`.
   - Added `GET /api/v1/agent/memories` for user/job scoped read-only memory listing.

3. Verification
   - Ran `python test/test_memory_tools.py`.
   - Confirmed 6 memory tests passed, including current user/job scoping and tenant isolation.
   - Ran `python test/test_agent_tools.py`.
   - Confirmed 13 agent tool tests still passed.
   - Ran `python test/test_mock_external_api.py`.
   - Confirmed 5 mock API tests still passed.
   - Ran `docker compose build backend frontend`.
   - Confirmed frontend production build and TypeScript checks passed.
   - Restarted `backend` and `frontend`.
   - Confirmed both services are healthy.
