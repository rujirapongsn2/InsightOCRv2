# QUICKWIN TEST


Date: 2026-07-02

## Manual Verification - Nginx Real IP, Streaming Timeouts, and Probe Blocking

1. Nginx rate/connection limit remediation
   - Added trusted real-client IP handling for Docker/internal proxy traffic using `real_ip_header X-Forwarded-For`, `real_ip_recursive on`, and conservative `set_real_ip_from` ranges.
   - Split API, login, upload/process, and SSE stream rate-limit zones.
   - Increased general API connection capacity from 10 to 50 per real client IP and moved long-lived streams to a separate connection zone.

2. Long-running and streaming routes
   - Added dedicated Nginx locations for document progress streams, Agent/Chat message streams, and integration streaming with 900s read/send timeouts and buffering disabled.
   - Kept long-running schema suggestion and integration dispatch routes on extended API timeouts.

3. Bot/probe fallback blocking
   - Added Nginx map-based fallback blocking for obvious exploit probes such as `/adfa`, suspicious shell payloads in URI/query, scanner user agents, and abnormal POSTs to `/`, `/_next`, and `/api`.
   - Confirmed `GET /adfa` and `POST /` are closed by Nginx with 444 behavior (`curl` reports `000`/empty reply), without proxying to frontend.

4. TLS warning noise
   - Replaced scattered global `urllib3.disable_warnings(...)` calls with a shared TLS helper that keeps warnings visible once and logs a single config decision when `verify_ssl=false` is used.

5. Verification commands
   - Ran `PYTHONPYCACHEPREFIX=/tmp/insightocr-pycache python3 -m py_compile backend/app/services/tls.py backend/app/services/ocr.py backend/app/services/structure.py backend/app/services/schema_suggestion_service.py backend/app/tasks/document_tasks.py backend/app/api/v1/endpoints/settings.py`.
   - Generated ignored local self-signed dev cert files with `bash nginx/ssl/generate-certs.sh` so the mounted HTTPS config can be validated locally.
   - Ran `docker compose exec nginx nginx -t`; config syntax passed.
   - Ran `docker compose exec nginx nginx -s reload`; reload succeeded.
   - Confirmed `GET http://127.0.0.1/health` returns `200`.
   - Confirmed `GET /api/v1/users/me` without auth still returns `401`, not a 5xx.
   - Confirmed `POST /api/v1/login/access-token` without form data returns FastAPI validation status `422`, not a 5xx.
   - Confirmed access log records `203.0.113.10` as `$remote_addr` when `X-Forwarded-For: 203.0.113.10` is sent through the trusted local proxy path.
   - Sent 30 concurrent unauthenticated API requests with distinct `X-Forwarded-For` values; all returned `401`, with no 503/connection-limit response.
   - Ran `git diff --check`.

---

Date: 2026-06-30

## Manual Verification - Workflow LLM Agent Provider Dropdown

1. Provider resolution
   - Confirmed Workflow LLM/Agent node previously resolved `integration_id` / `OPENAI_API_KEY` / LLM Integration fallback, not AI Settings Agent Provider.
   - Updated Workflow LLM provider priority to use: selected AI Agent Provider, legacy LLM Integration ID, Setting AI Agent Provider, system Agent Provider, default AI Setting, then LLM Integration fallback.
   - Confirmed resolver uses the system Agent Provider when no DB AI Setting is marked as Agent Provider.

2. Form alignment
   - Replaced the free-text provider/model override fields with a single `AI Agent Provider` dropdown.
   - Dropdown options load active providers from Setting AI and show Agent/Default/provider type badges.
   - Leaving the dropdown blank uses the central Agent Provider configured for the system.
   - Changed new sample LLM nodes to store `ai_provider_id` and rely on the provider's configured model.
   - Synced existing sample workflow definitions on startup so the demo forms match the updated behavior.

3. Runtime verification
   - Confirmed direct LLM node execution returns a response through the system Agent Provider.
   - Ran sample Workflow 2 through Celery; all nodes succeeded and LLM logs show `Using system Agent Provider (model=gpt-5.4-mini)`.
   - Confirmed backend node catalog exposes LLM fields: `ai_provider_id`, `system_prompt`, `prompt`, and `json_output`.
   - Confirmed sample Workflow 2 LLM config contains `ai_provider_id` and no `integration_id` / `model` override.
   - Ran `PYTHONPYCACHEPREFIX=/tmp/insightocr-pycache python3 -m py_compile backend/app/services/workflow_engine.py backend/app/initial_workflows.py backend/app/main.py`.
   - Ran `docker compose build frontend`; Next.js production build and TypeScript checks passed.
   - Ran `docker compose up -d --build --no-deps backend celery_worker celery_beat frontend`.
   - Confirmed backend, celery worker, celery beat, and frontend containers are running; backend and frontend are healthy.
   - Ran `git diff --check`.

---


Date: 2026-06-30

## Manual Verification - Workflow Python Sandbox Permission

1. Docker socket access
   - Added the Docker socket group to backend and celery worker via `DOCKER_GID` fallback in `docker-compose.yml`.
   - Confirmed backend and celery worker include group `988` and can read/write `/var/run/docker.sock`.

2. Sandbox runtime
   - Switched the workflow Python sandbox to `python:3.12-slim` with `SANDBOX_AUTO_BUILD=false` to avoid first-run custom image build delays.
   - Confirmed direct `execute_python()` returns `{'ok': True, 'total': 6}` without sandbox errors.

3. Workflow verification
   - Ran sample Workflow 1 through `execute_workflow_run`; all nodes succeeded.
   - Enqueued sample Workflow 1 through Celery `run_workflow_task`; all nodes succeeded, including Python Code and Write Output.

---

Date: 2026-06-30

## Manual Verification - Workflow Sample Seeds

1. Sample data
   - Added startup seeding for the demo Job `ใบเสร็จรับเงิน review`.
   - Added three reviewed receipt documents so Jobs and Document Source nodes have data to apply.

2. Sample workflows
   - Added Workflow 1: Manual Trigger -> Jobs -> Condition -> Transform -> Python Code -> Write Output.
   - Added Workflow 2: Webhook Trigger -> Jobs -> Condition -> LLM -> Transform -> Write Output.
   - Added Workflow 3: Schedule Trigger -> Document Source -> Condition -> LLM -> Transform -> Write Output.

3. Static checks
   - Ran `PYTHONPYCACHEPREFIX=/tmp/insightocr-pycache python3 -m py_compile backend/app/initial_workflows.py backend/app/main.py`.
   - Ran `git diff --check`.
   - Validated the generated definitions include the required node types for all 3 sample workflows.

4. Runtime verification
   - Ran `docker compose up -d --build --no-deps backend celery_worker celery_beat`.
   - Confirmed backend, celery worker, and celery beat are running; backend health is `healthy`.
   - Confirmed the database contains Job `ใบเสร็จรับเงิน review` with 3 demo documents.
   - Confirmed the database contains all 3 sample workflows, each with 6 nodes and 5 edges.

---


Date: 2026-06-25

## Manual Verification - Agent Job Access Permission

1. Backend permission fix
   - Updated Agent job access to reuse the shared `ensure_job_access` helper from `app.api.permissions`.
   - Confirmed admins/superusers now follow the same Job access rules in Agent DOC as `/api/v1/jobs/{job_id}`.
   - Confirmed missing jobs still return `404 Job not found`.

2. Static checks
   - Ran `env PYTHONPYCACHEPREFIX=/private/tmp/insightocr-pycache python3 -m py_compile backend/app/api/v1/endpoints/agent.py`.
   - Ran `git diff --check`.

---

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

---

Date: 2026-06-10

## Manual Verification - System Agent Conversation Creation

1. Frontend behavior
   - Updated `AgentPanel` so `New Conversation` is available for every Job without selecting or requiring an LLM integration.
   - Confirmed the create request sends only `job_id`; no `integration_id` is attached by default.
   - Removed active-LLM integration selection and no-active-LLM messaging from the Agent DOC panel.

2. Backend agent provider
   - Updated Agent conversations without `integration_id` to use the default active AI Settings provider.
   - Added a completion-provider agent loop that can request backend tools through JSON actions.
   - Added deterministic Job context preload with `list_documents` and `get_document_detail` so Agent DOC always works from live Job data even when the provider does not support native function calling.

3. Rebuild and runtime
   - Ran backend source syntax checks with `compile(...)` because the container filesystem is read-only for `__pycache__`.
   - Ran `docker compose up -d --build backend frontend nginx`, then rebuilt backend after the context preload/fallback update.
   - Confirmed backend, frontend, and nginx are running/healthy.

4. Public API verification
   - Confirmed `POST https://insightdoc.softnix.ai/api/v1/agent/conversations` with only `job_id` returns `201` and `integration_id=null`.
   - Confirmed `POST /api/v1/agent/conversations/{id}/messages` streams tool calls for `list_documents` and `get_document_detail` before the final response.
   - Confirmed a Thai summary request returns a final summary from real Job document data for `Q26050014-9 (1).pdf`.
   - Confirmed `DELETE /api/v1/agent/conversations/{id}` returns `204` for cleanup.

---

Date: 2026-06-10

## Manual Verification - Full Agentic Document Management Provider

1. System Agent provider
   - Added `AGENT_PROVIDER_URL`, `AGENT_PROVIDER_KEY`, and `AGENT_MODEL` to backend settings.
   - Confirmed the backend reads the system Agent provider from `backend/.env` without printing secrets.
   - Confirmed default Job conversations use the system Agent provider and no longer require LLM integrations.

2. Agent loop and tools
   - Updated the Agent prompt for Agentic Document Management: observe, reason, act, verify, and report.
   - Confirmed Agent DOC has registered document, integration, memory, skill, filesystem, code sandbox, and web tools.
   - Added support for providers that return tool calls as JSON text (`{"tool_calls": [...]}`) instead of native OpenAI `tool_calls`.
   - Confirmed a document QA request executes `list_documents`, then `get_document_detail`, then answers from the real document data.

3. Web search
   - Added `web_search` tool using DuckDuckGo via the `ddgs` package, with `duckduckgo-search` as fallback import.
   - Confirmed direct tool execution returns web results for a test query without errors.

4. Runtime
   - Rebuilt backend/frontend/nginx after adding Agent provider support.
   - Rebuilt backend after switching web search to `ddgs`.
   - Confirmed backend, frontend, and nginx are healthy after deployment.

---

Date: 2026-06-10

## Manual Verification - Agent DOCX Tool Failure Fix

1. Root cause
   - Inspected the failing Agent conversation and found `execute_python` failed with `ModuleNotFoundError: No module named 'docx'`.
   - Confirmed the following `write_file` call also failed because the content sent as `content_base64` was not valid base64.
   - Confirmed the assistant incorrectly claimed the file was created even though both tools returned errors.

2. Fixes
   - Added a dedicated `create_docx` filesystem tool that generates `.docx` files from plain text/markdown-like content without requiring sandbox Python dependencies.
   - Updated Agent DOC prompt guidance to use `create_docx` for Word/quotation/report exports and only claim success after a file tool returns `ok=true`.
   - Added agent-loop guardrails so tool failures are injected into the next reasoning step and file-success claims are blocked when the latest file tool failed.
   - Updated Agent tool cards to show readable error messages and to treat `create_docx` success as a downloadable file.
   - Fixed Agent file download endpoint to stream bytes before temporary storage files are cleaned up.

3. Verification
   - Ran backend syntax checks with `PYTHONPYCACHEPREFIX=/tmp/pycache` because the runtime container is read-only.
   - Rebuilt and restarted backend/frontend/nginx with Docker Compose; frontend production build and TypeScript checks passed during image build.
   - Confirmed backend, frontend, and nginx are healthy.
   - Created a new Agent conversation through `https://insightdoc.softnix.ai` and requested a Word quotation export for Job `ce3764f5-9fa3-434f-b015-f0b88421be57`.
   - Confirmed Agent DOC executed `list_documents`, `get_document_detail`, then `create_docx` with `ok=true` and path `outputs/quotation_agent_test.docx`.
   - Confirmed the final assistant response returned the file name only after successful creation.
   - Confirmed `GET /api/v1/agent/files/download` returns HTTP 200 with DOCX content type and a valid DOCX/ZIP payload.
   - Updated the Agent UI so successful `create_docx`/`write_file` tool cards show a visible Download button while collapsed.
   - Updated assistant messages so generated file names such as `quotation_agent_test.docx` render a Download chip using the current conversation ID.
   - Rebuilt/restarted frontend and confirmed `https://insightdoc.softnix.ai/jobs/ce3764f5-9fa3-434f-b015-f0b88421be57` returns HTTP 200.
   - Reconfirmed the generated DOCX download endpoint returns HTTP 200, DOCX content type, and a valid DOCX/ZIP payload.
   - Fixed authenticated browser downloads by replacing direct `<a href>` API links with client-side `fetch` using the Bearer token from `localStorage`, then saving the response as a Blob.
   - Confirmed unauthenticated direct API navigation returns 401 as expected, while the same endpoint with `Authorization: Bearer ...` returns HTTP 200 and a valid DOCX payload.

---

Date: 2026-06-10

## Manual Verification - Agent Conversation Tool Guard

1. Conversation audit
   - Inspected conversation `d80b3f4c-2b66-457e-b1ae-e3822ab4ae45` through the Agent API.
   - Confirmed early file generation used `list_documents`, `get_document_detail`, and `create_docx` correctly.
   - Confirmed some later requests answered too quickly because no tools were called in that turn, including a web-search request and a Word-file update request.
   - Downloaded the current `quotation_agent_test.docx` and confirmed it still contained the original quotation content, so later product/address enrichment had not actually been written to the file.

2. Fixes
   - Updated Agent conversation history loading to keep the newest messages in chronological order instead of the oldest messages.
   - Added required-tool guardrails: requests that explicitly require external research must call `web_search` in the same turn before answering.
   - Added required-tool guardrails: requests that create or update Word/file artifacts must call `create_docx` or `write_file` in the same turn and only claim success after `ok=true`.
   - Added final-response protection so the Agent cannot reuse an older file-success result from history for a new file-update request.

3. Verification
   - Ran backend syntax checks with `PYTHONPYCACHEPREFIX=/tmp/pycache`.
   - Rebuilt and restarted backend/frontend/nginx with Docker Compose.
   - Confirmed backend, frontend, and nginx are healthy.
   - Created a separate test conversation and sent a combined request requiring web search plus DOCX output.
   - Confirmed the Agent executed `list_documents`, `web_search`, `get_document_detail`, then `create_docx` in the same turn.
   - Confirmed `create_docx` returned `ok=true` with path `outputs/guard_test.docx` and a changed file size.

---

Date: 2026-06-10

## Manual Verification - Agent Binary Read File Fix

1. Root cause
   - Inspected the latest Agent conversation after the UI stayed in `Thinking`.
   - Confirmed the Agent had successfully found the correct Softnix contact address from `https://www.softnix.co.th/contact/`.
   - Found the stream crashed when `read_file` tried to read `outputs/guard_test.docx` as text.
   - PostgreSQL rejected the tool result because the binary DOCX content contained `\u0000`, which cannot be stored in JSONB.

2. Fixes
   - Updated `read_file` so binary extensions such as `.docx`, `.xlsx`, `.pdf`, `.pptx`, images, and `.zip` return metadata only instead of binary content.
   - Added JSONB sanitization before saving Agent messages/tool results to strip null characters from any string payload returned by tools.

3. Verification
   - Ran backend syntax checks with `PYTHONPYCACHEPREFIX=/tmp/pycache`.
   - Rebuilt and restarted backend/frontend/nginx with Docker Compose.
   - Confirmed backend, frontend, and nginx are healthy.
   - Re-ran an Agent request that uses `web_search`, `read_file` on a DOCX, and `create_docx`.
   - Confirmed `read_file` returned `binary=true` metadata for `outputs/guard_test.docx` and no binary content.
   - Confirmed the Agent completed the stream, created `outputs/guard_address_fixed.docx`, and returned a final answer with the corrected Softnix address.
   - Confirmed backend logs no longer show PostgreSQL JSONB null-character errors after the retest.

---

Date: 2026-06-10

## Manual Verification - LLM Integration Test Connection Fallback

1. Root cause
   - Inspected `/integrations/test-llm` and found it always called the OpenAI Responses API.
   - This returned 404 for OpenAI-compatible providers that expose only `/v1/chat/completions`, or when users pasted a full endpoint path instead of a base URL.
   - The LLM model selector was a fixed dropdown, which prevented provider-specific model IDs.

2. Fixes
   - Added LLM base URL normalization for full `/responses` and `/chat/completions` endpoint URLs.
   - Added Chat Completions fallback when Responses API returns 404.
   - Reused the same helper for test, send, and streaming integration paths.
   - Updated the Integration UI copy and changed Model to a free-text provider model ID input.

3. Verification
   - Ran backend syntax checks for `backend/app/api/v1/endpoints/integrations.py`.
   - Rebuilt and restarted backend/frontend/nginx with Docker Compose.
   - Found backend startup was blocked before binding port because startup work was waiting on database DDL locks after repeated imports/restarts.
   - Changed Docker sandbox image warm-up to run in a background daemon thread so sandbox pre-pull can no longer block API startup.
   - Added Docker client timeouts for sandbox image checks/execution setup.
   - Confirmed backend, frontend, and nginx are healthy after restart.
   - Confirmed `/health` returns HTTP 200 and `/integrations` returns HTTP 200 through nginx.
   - Confirmed authenticated `/api/v1/integrations/test-llm` returns HTTP 200 with `Success via chat: OK` using backend provider env.

---

Date: 2026-06-10

## Manual Verification - Integration Create Redirect Fix

1. Root cause
   - Safari showed `Load failed` after Create even though LLM Test Connection succeeded.
   - Backend logs showed `POST /api/v1/integrations` returned `307 Temporary Redirect` to `/api/v1/integrations/`.
   - POST redirects with CORS caused the browser fetch to fail before the create request completed.

2. Fixes
   - Updated the frontend integration API client to call `/integrations/` directly for list and create operations.

3. Verification
   - Rebuilt and restarted frontend/backend with Docker Compose.
   - Confirmed backend, frontend, and nginx are healthy.
   - Confirmed `/integrations` returns HTTP 200 through nginx.
   - Authenticated as admin and posted to `/api/v1/integrations/` with redirect following disabled.
   - Confirmed create returned HTTP 201 with no redirect location, then deleted the smoke-test integration with HTTP 204.

---

Date: 2026-06-11

## Manual Verification - Inline Job Rename

1. Scope
   - Added inline job-name editing on the job detail header.
   - Added backend `PUT /api/v1/jobs/{job_id}` for authorized job updates.

2. Verification
   - Ran backend syntax check for `backend/app/api/v1/endpoints/jobs.py`.
   - Rebuilt and restarted backend/frontend with Docker Compose; frontend production build and TypeScript checks passed.
   - Confirmed backend, frontend, and nginx are healthy.
   - Authenticated as admin and renamed job `31b5d083-dbde-4c23-85cd-56ec0d3311fd` from `Job2` to `Job2 Inline Test` via API.
   - Renamed the same job back to `Job2` and confirmed both `PUT` calls returned HTTP 200.
   - Confirmed the job detail page returns HTTP 200 through nginx.
---

Date: 2026-06-11

## Manual Verification - Cross Document HTML Report Skill

1. System skill files
   - Added cross-document-html-report as an agentskills.io SKILL.md.
   - Added a root .agents/skills/... copy for repository discovery and a backend/.agents/skills/... copy so the backend Docker build context includes the same system skill.

2. Backend startup registration
   - Added system skill discovery sync through ensure_system_agent_skills().
   - Confirmed the sync helper upserts discovered file-backed skills with scope=system and user_id=None.

3. Verification
   - Ran local parse_skill_md and validate_skill checks against the new SKILL.md; confirmed validation passed.
   - Ran PYTHONPYCACHEPREFIX=/tmp/pycache python3 -m py_compile backend/app/initial_agent_skills.py backend/test/agent/test_system_agent_skills.py.
   - Rebuilt the backend image with docker compose build backend.
   - Ran docker compose run --rm --no-deps backend python -m pytest test/agent/test_system_agent_skills.py -v.
   - Confirmed 2 tests passed for Skill file validation and system-skill upsert behavior.

---

Date: 2026-06-11

## Manual Verification - Thai Skill Activation Fix

1. Root cause
   - The Agent skill relevance filter matched the whole user message as one substring against skill metadata.
   - A Thai request such as ช่วยวิเคราะห์ข้อมูลระหว่างเอกสาร เพื่อรายงานความไม่ถูกต้องต่างๆ did not match the English-only cross-document skill metadata, so execute_skill was not prompted.

2. Fixes
   - Added Thai and English cross-document trigger matching in AgentContext skill relevance.
   - Updated cross-document-html-report SKILL.md descriptions with Thai activation wording.
   - Added a regression test for the exact Thai request pattern.

3. Verification
   - Ran PYTHONPYCACHEPREFIX=/tmp/pycache python3 -m py_compile backend/app/agent/context.py backend/test/agent/test_system_agent_skills.py.
   - Rebuilt backend with docker compose build backend.
   - Ran docker compose run --rm --no-deps backend python -m pytest test/agent/test_system_agent_skills.py -v and confirmed 3 tests passed.
   - Restarted backend with docker compose up -d --no-deps backend and confirmed it is healthy.
   - Queried AgentContext.list_relevant_skills with the Thai request and confirmed it returns cross-document-html-report as a system skill.

---

Date: 2026-06-11

## Manual Verification - Agent Skill Slash Picker and HTML Report Download Fix

1. Root cause
   - Agent report responses and tool cards could expose storage-scoped paths such as jobs/{job_id}/outputs/file.html, while the download endpoint expects paths relative to the job such as outputs/file.html.
   - Assistant message file detection did not include .html outputs.
   - The cross-document skill allowed execute_python HTML generation patterns that could fail when Python f-strings interpreted CSS braces as variables such as margin.
   - Chat input did not have a quick way to discover and invoke available skills.

2. Fixes
   - Added shared Agent file path normalization before building download URLs.
   - Updated assistant message and tool-card downloads to normalize jobs/.../outputs/... to outputs/..., and added .html as a downloadable output type.
   - Added a slash skill picker: typing / in Agent DOC lists available skills, selecting one inserts a skill invocation prompt, and /skill-name messages are converted to ใช้ skill skill-name before sending.
   - Added a persistent chat tip explaining that / can be used to call a skill.
   - Updated cross-document-html-report skill instructions to avoid Python f-string CSS brace errors when generating HTML.

3. Verification
   - Ran docker compose build frontend and confirmed Next.js production build and TypeScript checks passed.
   - Ran PYTHONPYCACHEPREFIX=/tmp/pycache python3 -m py_compile backend/app/agent/context.py backend/test/agent/test_system_agent_skills.py.
   - Rebuilt backend with docker compose build backend.
   - Restarted backend and frontend with docker compose up -d --no-deps backend frontend.
   - Confirmed backend and frontend are healthy.
   - Confirmed the job detail page returns HTTP 200 through local nginx on port 3000.
   - Confirmed the synced cross-document skill body contains the CSS brace guard instruction.

---

Date: 2026-06-11

## Manual Verification - Guarded Agent Report Code Tool

1. Root cause
   - Raw execute_python lets the Agent generate arbitrary report code, so missing variables such as docs or invalid HTML/CSS generation can fail after the skill has already started.
   - Pairing raw execute_python with write_file makes it possible for the UI to show a mixed state: one code tool failed, while another file-writing step later succeeded or partially succeeded.

2. Fixes
   - Added run_report_code as a guarded Agent code tool for HTML reports.
   - The tool performs Python syntax checking, runs code in the existing sandbox with network disabled, validates that result is an object with ok=true and a complete HTML document, writes only under outputs/, and returns normalized path/download metadata.
   - Updated Agent DOC prompt guidance and cross-document-html-report Skill instructions to prefer run_report_code over raw execute_python plus write_file for HTML reports.
   - Updated the Agent tool card category so run_report_code appears as a code tool in the UI.

3. Verification
   - Ran PYTHONPYCACHEPREFIX=/tmp/pycache python3 -m py_compile backend/app/agent/tools/code_tools.py backend/app/agent/context.py backend/test/agent/test_code_tools.py backend/test/agent/test_system_agent_skills.py.
   - Rebuilt backend with docker compose build backend.
   - Ran docker compose run --rm --no-deps backend python -m pytest test/agent/test_code_tools.py test/agent/test_system_agent_skills.py -v and confirmed 18 tests passed.
   - Ran docker compose build frontend and confirmed Next.js production build and TypeScript checks passed.
   - Restarted backend and frontend with docker compose up -d --no-deps backend frontend.
   - Confirmed backend and frontend are healthy.
   - Confirmed run_report_code is registered in the Agent tool registry and cross-document-html-report is synced with run_report_code in allowed tools.

---

Date: 2026-06-11

## Manual Verification - Contract Comparison HTML Report Skill

1. Scope
   - Added system skill contract-comparison-html-report for Agent DOC contract analysis, contract version comparison, renewal review, legal-risk review, and decision-support HTML reporting.
   - Added both repository and backend build-context copies under .agents/skills and backend/.agents/skills.

2. Fixes
   - Added SKILL.md with allowed tools: list_documents, get_document_detail, compare_documents, run_report_code, read_file, list_files, web_search.
   - Included Thai and English trigger wording for contract analysis requests.
   - Added AgentContext matching hints for Thai/English contract requests.
   - Added backend tests for skill parsing/validation, Thai contract matching, and multi-skill system upsert.

3. Verification
   - Ran PYTHONPYCACHEPREFIX=/tmp/pycache python3 -m py_compile backend/app/agent/context.py backend/test/agent/test_system_agent_skills.py.
   - Rebuilt backend with docker compose build backend.
   - Ran docker compose run --rm --no-deps backend python -m pytest test/agent/test_system_agent_skills.py -v and confirmed 6 tests passed.
   - Restarted backend with docker compose up -d --no-deps backend.
   - Queried the backend registry and confirmed contract-comparison-html-report exists as scope=system, source=file, with run_report_code and web_search in allowed_tools.

---

Date: 2026-06-11

## Manual Verification - Agent Report Skill UI Output Ordering

1. Root cause
   - Some providers can return raw JSON/tool-call payload text as assistant content when generating report workflows, so the UI displayed code, OCR snippets, and tool arguments as if they were the final answer.
   - Persisted assistant tool-call messages were rendered as normal assistant bubbles before tool cards, which made the working process appear below the answer.
   - Assistant message download extraction treated source document filenames in raw payload/OCR text as downloadable outputs.

2. Fixes
   - Converted raw report tool-call payload assistant bubbles into a short report-created message when an outputs/*.html path is present; otherwise raw tool payloads are hidden.
   - Rendered persisted assistant tool_calls as ToolCallCard entries at their chronological position, with tool result messages hidden, so working process appears before the final answer.
   - Added run_report_code download support in ToolCallCard.
   - Limited assistant-message download chips to outputs paths and generated non-PDF artifacts, avoiding source PDF filenames from OCR/tool payloads.
   - Added backend final-answer guardrails so successful run_report_code report workflows return a short report-created message with the outputs/ path instead of raw JSON or long tool/code content.

3. Verification
   - Ran PYTHONPYCACHEPREFIX=/tmp/pycache python3 -m py_compile backend/app/agent/loop.py backend/app/agent/context.py.
   - Rebuilt backend with docker compose build backend.
   - Rebuilt frontend with docker compose build frontend and confirmed Next.js production build and TypeScript checks passed.
   - Restarted backend and frontend with docker compose up -d --no-deps backend frontend.
   - Confirmed backend and frontend are healthy.
   - Confirmed the affected job page returns HTTP 200 through local nginx on port 3000.

---

Date: 2026-06-11

## Manual Verification - Agent Report False Success Guard

1. Root cause
   - A later contract-report request returned a raw JSON tool-call payload as assistant content instead of executing run_report_code.
   - Because the raw payload contained an outputs/*.html path, the UI previously summarized it as a successful report and displayed a Download button even though no tool result had written the file.

2. Fixes
   - Backend now converts raw tool-call payload final answers without a successful run_report_code result into a clear failure/retry message instead of a file-created response.
   - Frontend no longer creates a download chip from raw tool-call payload content. It shows a short not-created message when such payloads appear in history.

3. Verification
   - Queried the affected job conversation and confirmed the missing file case had no run_report_code tool result for outputs/contract_comparison_report_th.html.
   - Ran PYTHONPYCACHEPREFIX=/tmp/pycache python3 -m py_compile backend/app/agent/loop.py.
   - Rebuilt backend with docker compose build backend.
   - Rebuilt frontend with docker compose build frontend and confirmed Next.js production build and TypeScript checks passed.
   - Restarted backend and frontend with docker compose up -d --no-deps backend frontend.
   - Confirmed backend and frontend are healthy.
   - Confirmed the affected job page returns HTTP 200 through local nginx on port 3000.


---

Date: 2026-06-11

## Manual Verification - Workflow Feature (Drag & Drop Automation Builder)

1. Scope
   - New "Workflow" menu: business users build deterministic document-automation workflows (Zapier-style) with drag & drop nodes.
   - Node types: Manual/Schedule Trigger, Document Source, LLM/Agent, Condition (true/false branch), Transform/Mapping, Python Code (Docker sandbox), HTTP Request, Write Output (json/text/csv with download).
   - Backend: workflows/workflow_runs/workflow_node_runs tables, CRUD + run + run-detail + node-catalog + output-download endpoints under /api/v1/workflows, celery task per run (concurrent runs supported by worker pool), celery beat dispatcher (every 30s, croniter) for cron schedules.
   - Frontend: /workflows list page (create/run/activate/delete), /workflows/[id] builder using @xyflow/react with palette, config panel, schedule (cron) popover, and live Run Activity panel polling node statuses every 1.5s.

2. Verification performed
   - python3 -m py_compile on all new backend modules (models/schemas/engine/tasks/endpoint/celery_app) passed.
   - Unit-checked engine pure functions (template resolution {{node.path}}, topological order + cycle detection, condition operators, transform mapping, CSV serialization) with stubbed dependencies - all assertions passed.
   - cd frontend && npx tsc --noEmit passed; npm run build succeeded and shows /workflows and /workflows/[id] routes.

3. Remaining manual steps after rebuild (docker compose up --build)
   - New python dep: croniter (backend/requirements.txt). New frontend dep: @xyflow/react.
   - New service: celery_beat (docker-compose.yml); celery_worker now mounts docker.sock for Python Code sandbox nodes.
   - Smoke test: create workflow -> drag Document Source + LLM + Write Output -> connect -> Save -> Run -> watch Activity panel -> download output file; then set cron (e.g. */5 * * * *) + enable schedule + Save and confirm a scheduled run appears.

---

Date: 2026-06-11

## Manual Verification - Workflow "Jobs" Node

1. Scope
   - New "Jobs" node (type job_source, category data) brings processed data from a Job into the workflow.
   - Config: job picker (job_select dropdown populated from /jobs/), data_source (reviewed | extracted | ocr_text; reviewed falls back to extracted), document status filter, only_completed toggle, max-documents limit.
   - Output: {job_id, job_name, job_status, count, records: [...], documents: [{id, filename, status, data}]} - `records` is a flat array convenient for downstream LLM/Transform nodes.
   - New frontend field type job_select rendered as a dropdown; builder loads the job list once via getJobs(). Existing Document Source node also upgraded to use the job picker.

2. Verification performed
   - python3 -m py_compile app/services/workflow_engine.py passed.
   - cd frontend && npx tsc --noEmit passed; npm run build succeeded.
   - Rebuilt backend/frontend/celery_worker images and restarted services; backend + frontend healthy.
   - GET /api/v1/workflows/node-types returns job_source with the job_select field.
   - E2E: created a workflow trigger -> job_source(real job "Q1", data_source=reviewed) -> write_output({{j1.records}}), ran it, polled to succeeded. Jobs node loaded 5 documents and emitted records; write_output wrote job_records.json (4472 chars). Confirmed via run node-run logs/output.
   - https://localhost/workflows returns 200.

---

Date: 2026-06-11

## Manual Verification - Workflow Builder UX (Variable Picker + Single-node Test + Field Hints)

1. Scope (ทำให้ business user ใช้ง่ายขึ้น)
   - Variable Picker: ปุ่ม "+ แทรกข้อมูลจากโหนดก่อนหน้า" ในช่อง text/textarea และคอลัมน์ value ของ mappings — แสดงเฉพาะโหนดต้นทาง (ancestors) ของโหนดที่เลือก พร้อมฟิลด์ (จาก output_fields ใน catalog + เติมจาก output จริงของการรันล่าสุด) คลิกแล้วแทรก {{nodeId.field}} ที่ caret
   - Single-node Test: ปุ่ม "ทดสอบโหนดนี้" ในแผง Config — รันโหนดเดียวโดยใช้ข้อมูลจากการรันเต็มครั้งล่าสุดเป็น context แสดงผลผ่านแผง Activity เดิม (run trigger_type=node_test)
   - Field hints/placeholder: เพิ่ม hint + placeholder ภาษาไทยในทุก node type

2. Backend changes
   - workflow_engine.py: เพิ่ม output_fields/placeholder/hint ใน NODE_TYPES; เพิ่ม execute_single_node() + _build_context_from_last_run()
   - workflow_tasks.py: เพิ่ม test_node_task
   - endpoints/workflows.py: เพิ่ม POST /workflows/{id}/nodes/{node_id}/test

3. Verification performed
   - python3 -m py_compile ผ่านทุกไฟล์ backend ที่แก้
   - cd frontend && npx tsc --noEmit ผ่าน; npm run build สำเร็จ
   - Rebuild backend/frontend/celery_worker + restart; backend+frontend healthy
   - GET node-types: ยืนยัน job_source.output_fields = [count, records, documents, job_name, job_status], job_id มี hint, llm.prompt มี placeholder
   - Single-node test (สำเร็จ): POST /workflows/{id}/nodes/tf_1/test บน example workflow ที่เคยรันเต็มแล้ว → ได้ run node_test ที่มี node_runs เดียว (tf_1) succeeded, output ประกอบค่าจาก jobs_1 + llm_1 ที่ cache ไว้ถูกต้อง
   - Single-node test (เคส error): workflow ใหม่ที่ยังไม่เคยรัน → failed พร้อมข้อความ "กรุณารัน workflow แบบเต็มอย่างน้อย 1 ครั้งก่อน เพื่อให้มีข้อมูลจากโหนดก่อนหน้า"
   - https://localhost/workflows และ /workflows/{id} ตอบ 200 ผ่าน nginx

---

Date: 2026-06-11

## Manual Verification - Google Drive / OneDrive Workflow Nodes

1. Scope
   - 4 nodes ใหม่ (หมวด storage): gdrive_upload, gdrive_import, onedrive_upload, onedrive_import
   - upload = อัปโหลดผลลัพธ์ workflow ขึ้นโฟลเดอร์คลาวด์; import = ดึงทั้งโฟลเดอร์เข้า Job แล้ว OCR/process ตามฟังก์ชัน Jobs
   - Auth = service account (Google JWT-bearer) / app credentials (OneDrive client-credentials) เก็บใน Integration (type gdrive/onedrive) อ้างด้วย integration_id
   - ไม่เพิ่ม pip dependency — ใช้ requests + python-jose ที่มีอยู่; egress ผ่าน gateway proxy

2. Backend changes
   - services/cloud_drive.py (GoogleDriveClient/OneDriveClient: token + list/download/upload)
   - services/ingestion.py (ingest_file_into_job reuse storage + process_document_task)
   - services/workflow_engine.py: 4 NODE_TYPES + executors + EXECUTORS
   - schemas/integration.py + models/integration.py: type รองรับ gdrive/onedrive (Postgres ENUM ต้อง ALTER TYPE ADD VALUE — เพิ่ม migration ใน main.py แบบ AUTOCOMMIT; ค่า label = ชื่อ enum ตัวพิมพ์ใหญ่ GDRIVE/ONEDRIVE ตามที่ SQLAlchemy SQLEnum persist)
   - api/v1/endpoints/integrations.py: endpoint POST /integrations/{id}/test-drive
   - Frontend: integration_select field type + หมวด/ไอคอน storage (workflows builder); ฟอร์มสร้าง credential gdrive(วาง service-account JSON)/onedrive(tenant/client/secret/drive) + ปุ่มทดสอบในหน้า Integration

3. Verification performed
   - python3 -m py_compile ผ่านทุกไฟล์ backend; cd frontend && npx tsc --noEmit ผ่าน; npm run build สำเร็จ
   - Rebuild backend/frontend/celery_worker + restart; healthy
   - Gateway egress: requests จาก worker ไป oauth2.googleapis.com / www.googleapis.com / login.microsoftonline.com / graph.microsoft.com เชื่อมต่อได้ (404/200)
   - node-types: มี 4 โหนดใหม่ หมวด storage พร้อม output_fields + integration_select(provider ตรง)
   - สร้าง Integration type gdrive และ onedrive ได้ (หลังแก้ Postgres ENUM); ปรากฏใน /integrations/active (สำหรับ dropdown ในโหนด)
   - test-drive ด้วย credential ปลอม: ทั้ง Google (JWT signing → token endpoint → invalid_grant) และ Microsoft (token endpoint → AADSTS900023) คืน HTTP 400 พร้อมข้อความ error จริง — พิสูจน์ว่า client + proxy + error handling ทำงาน (ไม่ crash 500)
   - https://localhost/workflows และ /integrations ตอบ 200

4. ขั้น end-to-end ที่เหลือ (ต้องมี credential จริงจากผู้ใช้)
   - Google: สร้าง service account + แชร์โฟลเดอร์ Drive ให้อีเมล client_email; OneDrive: Azure app + Files.ReadWrite.All + admin consent + drive_id
   - จากนั้น: gdrive_import(folder→Job) ต้องมี Document ใหม่และ process_document_task ทำงาน; (Transform/Write→) gdrive_upload ต้องเห็นไฟล์บน Drive

---

Date: 2026-06-13

## Manual Verification - Workflow Webhook Trigger

1. Scope
   - New `trigger_webhook` node starts workflows from external webhooks and exposes payload data as `{{trigger.body}}`, `{{trigger.query}}`, and `{{trigger.headers}}`.
   - New `webhook_response` node selects the pollable workflow result; if no visible response node runs, result falls back to the last successful non-response node.
   - Workflow webhook secret URLs are generated/rotated from the builder and stored server-side as a hash only.

2. Verification performed
   - `PYTHONPYCACHEPREFIX=/private/tmp/insightocr-pycache python3 -m py_compile ...` passed for modified backend files.
   - `PYTHONPYCACHEPREFIX=/private/tmp/insightocr-pycache python3 -m pytest backend/test/test_workflow_engine_webhook.py -q` passed (3 tests).
   - `cd frontend && npm run build` passed.

3. Manual smoke to run with services
   - Create workflow: Webhook Trigger -> Transform or LLM -> Webhook Response.
   - Generate Webhook URL in the Webhook Trigger config panel.
   - `curl -X POST <webhook_url> -H 'Content-Type: application/json' -d '{"events":[{"message":{"text":"hello LINE"}}]}'`
   - Poll the returned `poll_url` until `status=succeeded`; confirm `result.body` contains the configured response.

---

Date: 2026-06-15

## Manual Verification - Agent Python Sandbox Image and Office File Support

1. Scope
   - Added a dedicated `insightocr-sandbox:py312` image for Agent/Workflow Python sandbox runs.
   - Preinstalled document/data packages: fpdf2, reportlab, requests, openpyxl, xlsxwriter, pandas, python-docx, pypdf, pillow, xlrd, plus Thai-capable fonts.
   - Sandbox runner now forwards proxy/PIP env, auto-detects the backend Docker network, uses `/tmp` as the writable working directory, and can auto-build the sandbox image from `backend/Dockerfile.sandbox`.
   - Agent guidance now treats Excel/CSV/PDF generation as first-class supported sandbox tasks without runtime pip installs for common packages.

2. Verification performed
   - `PYTHONPYCACHEPREFIX=/private/tmp/insightocr-pycache python3 -m py_compile backend/app/services/code_sandbox.py backend/app/agent/tools/code_tools.py backend/app/agent/context.py` passed.
   - `docker build -f backend/Dockerfile.sandbox -t insightocr-sandbox:py312 backend` passed.
   - `docker run --rm -v ... insightocrv2-backend pytest test/agent/test_code_sandbox_config.py test/agent/test_code_tools.py -q` passed: 18 tests.
   - Live sandbox smoke via `execute_python(..., allow_network=False)` created `.xlsx`, `.csv`, and Thai PDF successfully with the prebuilt `insightocr-sandbox:py312` image.

3. Manual smoke to run after rebuild
   - `docker compose build backend`
   - Start/restart backend and verify startup builds or finds `insightocr-sandbox:py312`.
   - Ask Agent DOC to create:
     - a Thai PDF from chat content,
     - an `.xlsx` workbook with at least one styled sheet,
     - a UTF-8 `.csv` file.
   - Confirm each tool result returns `ok=true` or a `_save_file()` result, and that the generated file downloads correctly.

---

Date: 2026-06-15

## Manual Verification - Agent File Result Anti-Hallucination Guard

1. Scope
   - `write_file` now rejects invalid binary payloads before saving Office/PDF/image files.
   - Agent loop now performs post-write verification for `write_file`, `create_docx`, and `run_report_code` before treating a file result as successful.
   - A file-creation final answer is allowed only after the saved object exists in job storage, has a non-zero verified size, and binary formats pass structural validation.
   - `read_file(return_base64=true)` remains the supported path for editing existing binary outputs; old `/tmp/...` files from prior sandbox runs must not be reused.

2. Verification performed
   - `PYTHONPYCACHEPREFIX=/private/tmp/insightocr-pycache python3 -m py_compile backend/app/agent/loop.py backend/app/agent/tools/filesystem_tools.py backend/test/agent/test_agent_file_verification.py backend/test/agent/test_filesystem_tools.py` passed.
   - `docker run --rm -v ... insightocrv2-backend pytest test/agent/test_agent_file_verification.py test/agent/test_filesystem_tools.py -q` passed: 32 tests.
   - `docker run --rm -v ... insightocrv2-backend pytest test/e2e/test_agent_loop_e2e.py -q` passed: 7 tests.

3. Manual smoke to run after rebuild
   - Ask Agent DOC to create a new `.xlsx` file and confirm the `write_file` tool result includes `verified=true`.
   - Try a follow-up edit to the generated workbook; confirm the agent reads the saved file with `read_file(return_base64=true)` rather than using an old `/tmp` path.
   - Download the workbook and open it in Excel/Numbers.

4. Follow-up fix for execute_python-only file generation
   - Root cause: some agent-generated code saved `/tmp/<file>` and returned `result={"path": "/tmp/<file>"}` without calling `_save_file()` or `write_file`, so no file reached job storage.
   - Sandbox now auto-captures existing `/tmp` file paths returned via `result.path`, `result.file_path`, or `result.output_path`.
   - `execute_python` handler now auto-persists captured files under `outputs/`, verifies them, and returns `ok=true`, `verified=true`, `path`, and `saved_files`.
   - Verification: live smoke created Thai PDF with only `result={'path':'/tmp/auto_capture.pdf'}` and returned `outputs/auto_capture.pdf`, `verified=true`.
   - Tests: `pytest test/agent/test_code_tools.py test/agent/test_agent_file_verification.py test/agent/test_filesystem_tools.py -q` passed: 48 tests; `pytest test/e2e/test_agent_loop_e2e.py -q` passed: 7 tests.

5. Follow-up fix for "ช่วยแปลงเป็น excel" from an existing DOCX output
   - Root cause: the agent tried to read DOCX base64 and generate ad-hoc Python, causing `KeyError: 'docx_base64'` and repeated Python `NameError: name 'true' is not defined`; after a later successful file write, stale tool-failure context could still make the final answer report failure.
   - Added deterministic `convert_to_xlsx` filesystem tool for saved DOCX/PDF/CSV/text/report to Excel conversion, plus a direct conversion route for short prompts like `ช่วยแปลงเป็น excel` that uses the latest convertible output in the same conversation.
   - Agent file success tracking now keeps the latest verified file result and overrides stale failure text only when a later file-producing tool returned `ok=true` and `verified=true`.
   - UI now treats `convert_to_xlsx` as a filesystem write tool and shows the download button.
   - Verification after rebuild/restart:
     - `docker exec softnix_ocr_backend python -m pytest /app/test/agent/test_filesystem_tools.py /app/test/agent/test_agent_file_verification.py /app/test/agent/test_code_tools.py -q` passed: 52 tests.
     - `docker exec softnix_ocr_backend python -m pytest /app/test/e2e/test_agent_loop_e2e.py -q` passed: 7 tests.
     - `docker compose build frontend` passed, including Next.js production build + TypeScript.
     - API prompt test against the original conversation with `content="ช่วยแปลงเป็น excel"` returned one tool call: `convert_to_xlsx`, `ok=true`, `verified=true`, `path=outputs/contract_risk_comparison_summary.xlsx`, `size=4458`, `rows=34`.
     - Stored workbook verification passed and ZIP/OpenXML entries were present: `[Content_Types].xml`, `_rels/.rels`, `xl/_rels/workbook.xml.rels`, `xl/workbook.xml`, `xl/worksheets/sheet1.xml`; `zip.testzip()` returned `None`.

6. Follow-up fix for table/report prompts with stale file history
   - Root cause: text `write_file` returned a scoped storage path (`jobs/<job_id>/outputs/...`) while post-write verification expected a job-relative path (`outputs/...`), causing false `not found after write` even though `list_files/read_file` could see the file.
   - Added filesystem path normalization so tools accept either `outputs/...` or `jobs/<current_job_id>/outputs/...`, reject cross-job scoped paths, and return job-relative paths consistently.
   - Added guardrails for stale file claims in conversation history:
     - prior assistant file/download claims are omitted from LLM history unless current-turn tools verify a file;
     - source document names such as `Contract_V1.pdf` are no longer misclassified as generated-output claims;
     - unverified output/download claims are rewritten or sanitized before final response.
   - Verification after rebuild/restart:
     - `docker exec softnix_ocr_backend python -m pytest /app/test/agent/test_filesystem_tools.py /app/test/agent/test_agent_file_verification.py /app/test/agent/test_code_tools.py /app/test/e2e/test_agent_loop_e2e.py -q` passed: 65 tests.
     - API prompt test against the original failing conversation with `content="เปรียบเทียบสัญญามิติความเสี่ยงในรูปแบบตาราง"` completed with `done`, no `write_file` verification error, no stale `outputs/...` success claim, and returned the risk comparison table inline in chat.

7. Follow-up fix for PDF creation disconnects
   - Root cause: short PDF prompts such as `ช่วยสร้างเป้น pdf` let the agent call raw `execute_python`; the sandbox run could finish with `error=null` but `files=[]` and `result=null`, so no verified artifact existed and the UI eventually showed a connection-lost banner instead of a deterministic completion.
   - Added deterministic `create_pdf` tool for converting saved text-like outputs or current text content to PDF under `outputs/`.
   - Added a direct PDF route for short follow-up prompts so the agent uses the latest saved text/Markdown/CSV/HTML output instead of ad-hoc Python.
   - Hardened PDF generation for Thai text, Markdown tables, long unbroken text, and unsupported emoji by pre-wrapping text by rendered width and normalizing symbols before writing.
   - Sanitized persisted sandbox file results so SSE tool results return file metadata only, not large base64 payloads.
   - UI now treats `create_pdf` as a downloadable filesystem write tool.
   - Verification after rebuild/restart:
     - `docker exec softnix_ocr_backend python -m pytest /app/test/agent/test_code_tools.py /app/test/agent/test_filesystem_tools.py /app/test/agent/test_agent_file_verification.py /app/test/e2e/test_agent_loop_e2e.py -q` passed: 66 tests.
     - API prompt test against the original failing conversation with `content="ช่วยสร้างเป้น pdf"` returned one tool call: `create_pdf`, `ok=true`, `verified=true`, `path=outputs/risk_comparison_table.pdf`, `size=16639`, `mime_type=application/pdf`, followed by `done`.
     - Stored PDF verification passed with `verify_saved_file(...)=ok`; `pypdf.PdfReader` opened the generated file and reported 3 pages.
     - `docker compose build frontend` passed, including Next.js production build + TypeScript, then frontend was restarted.

---

Date: 2026-06-30

## Manual Verification - Astryx Design System Initial Adoption

1. Scope
   - Installed Astryx packages in `frontend`: `@astryxdesign/core`, `@astryxdesign/theme-neutral`, and `@astryxdesign/cli`.
   - Added Astryx CSS reset, core styles, neutral theme CSS, and Tailwind v4 token bridge while keeping existing Softnix tokens.
   - Added a root Astryx theme provider and SSR theme attributes.
   - Converted shared `Button`, `Card`, `Input`, and `Textarea` wrappers into Astryx adapters while preserving the existing local import paths and event signatures.
   - Generated `frontend/ASTRYX.md` for local Astryx agent guidance.

2. Verification performed
   - `npm run build` passed for the frontend, including Next.js production build and TypeScript.
   - `npx eslint app/layout.tsx components/astryx-provider.tsx components/ui/button.tsx components/ui/card.tsx components/ui/input.tsx components/ui/textarea.tsx` passed.
   - `npm run dev` started successfully on `http://localhost:3002` because port 3000 was already in use.
   - `curl -I http://localhost:3002` returned `HTTP/1.1 200 OK`.

3. Notes
   - Full `npm run lint` still fails due to existing repo-wide lint debt such as `any` usage, hook dependency warnings, and unrelated source warnings.
   - Next/Turbopack reports CSS optimizer warnings for Astryx-generated `@property` rules, but the production build completes successfully.

4. Follow-up fix for Cloudflare Tunnel login API
   - Root cause: `https://insightdoc-mini.softnix.ai/` was serving a host `next dev` origin on port 3002. In that mode, `next.config.ts` rewrote `/api/v1/*` to `http://backend:8000`, which only resolves inside Docker, so login requests through the tunnel returned `500 Internal Server Error`.
   - Updated frontend rewrites to use `NEXT_API_REWRITE_ORIGIN` when set, `http://127.0.0.1:3000` in development, and `http://backend:8000` in production Docker.
   - Restarted the host dev server on port 3002 so Cloudflare Tunnel traffic uses the corrected rewrite config.
   - Verification:
     - `npm run build` passed after the rewrite change.
     - `npx eslint next.config.ts` passed.
     - `curl -I https://insightdoc-mini.softnix.ai/login` returned `HTTP/2 200`.
     - Diagnostic public login request with a fake user now returns `HTTP/2 400` and `{"detail":"Incorrect email or password"}` instead of `HTTP/2 500`.

5. Follow-up migration for shared UI primitives
   - Added a local `Badge` adapter backed by Astryx `Badge` while preserving the existing `components/ui/*` import pattern.
   - Converted `Modal` to Astryx `Dialog` and `DialogHeader`, keeping the existing `isOpen`, `onClose`, `title`, and `children` API.
   - Converted `FileUpload` to Astryx `FileInput` dropzone mode while preserving `onFileSelect`, `accept`, `maxSize`, `description`, and `className`.
   - Converted `HelpTooltip` to Astryx `Tooltip` with the existing icon-button trigger.
   - Updated `InfoCard` to compose the local Astryx-backed `Card`, `Badge`, and `Button` adapters.
   - Tuned `Stepper` to use the Softnix/Astryx token palette with stable dimensions and fewer ad-hoc class branches.
   - Verification:
     - `npm run build` passed for the frontend, including Next.js production build and TypeScript.
     - `npx eslint components/ui/badge.tsx components/ui/modal.tsx components/ui/file-upload.tsx components/ui/info-card.tsx components/ui/help-tooltip.tsx components/ui/stepper.tsx` passed.
   - Notes:
     - Next/Turbopack still reports the existing Astryx CSS optimizer warnings for generated `@property` rules, but the production build completes successfully.

6. Follow-up fix for Astryx visual regressions and slash-redirect API loops
   - Root cause: the Astryx-backed local `Button` adapter rendered Astryx button structure into call sites that already passed custom icon/content classes, causing several existing buttons to size incorrectly.
   - Restored the local `Button` wrapper to a native button with Softnix token classes, preserving existing `variant`, `size`, `className`, icon, and children behavior.
   - Root cause: Tailwind v4 plus Astryx reset made bare `border` utilities render too dark in existing panels/cards.
   - Added a base border color fallback using the Softnix hairline token.
   - Root cause: FastAPI redirects `/api/v1/ai-settings` and `/api/v1/users` to trailing-slash paths, while the host Next dev rewrite proxied them back without the slash, producing a 307 loop that Safari surfaced as a 503.
   - Added explicit Next rewrite entries for both slash and non-slash `ai-settings` and `users` collection paths.
   - Restarted the host Next dev server on port 3002 so Cloudflare Tunnel uses the updated config.
   - Verification:
     - `npm run build` passed for the frontend, including Next.js production build and TypeScript.
     - `npx eslint components/ui/button.tsx next.config.ts` passed.
     - `curl -i https://insightdoc-mini.softnix.ai/api/v1/ai-settings -H 'Authorization: Bearer invalid-token'` now returns `HTTP/2 403` with `{"detail":"Could not validate credentials"}`, confirming it reaches backend instead of redirect-looping/503.
     - `curl -i https://insightdoc-mini.softnix.ai/api/v1/users -H 'Authorization: Bearer invalid-token'` now returns `HTTP/2 403` with `{"detail":"Could not validate credentials"}`.
     - `curl -I https://insightdoc-mini.softnix.ai/jobs/69b4ccdf-3330-4aa1-a3d5-13d7e0799e3f` returned `HTTP/2 200`.

7. Follow-up fix for Integration page assets and API redirect loop
   - Root cause: the Integration catalog referenced remote GitHub raw SVG URLs for OpenAI, n8n, Google Drive, and OneDrive logos; those filenames were unavailable and Safari logged 404s.
   - Added local SVG assets under `frontend/public/integrations/` and updated the Integration catalog to reference those local paths.
   - Root cause: FastAPI redirects `/api/v1/integrations` to `/api/v1/integrations/`, and the host Next dev rewrite could loop that collection endpoint like the earlier `ai-settings` issue.
   - Added explicit Next rewrite entries for both slash and non-slash `/api/v1/integrations` collection paths.
   - Restarted the host Next dev server on port 3002 so Cloudflare Tunnel uses the updated assets and config.
   - Verification:
     - `npm run build` passed for the frontend, including Next.js production build and TypeScript.
     - `npx eslint next.config.ts` passed.
     - `curl -I https://insightdoc-mini.softnix.ai/integrations/openai.svg` returned `HTTP/2 200`.
     - `curl -I https://insightdoc-mini.softnix.ai/integrations/n8n.svg` returned `HTTP/2 200`.
     - `curl -i https://insightdoc-mini.softnix.ai/api/v1/integrations -H 'Authorization: Bearer invalid-token'` now returns `HTTP/2 403` with `{"detail":"Could not validate credentials"}`, confirming it reaches backend instead of redirect-looping/503.
     - `curl -I https://insightdoc-mini.softnix.ai/integrations` returned `HTTP/2 200`.
   - Notes:
     - Targeted lint on `app/(dashboard)/integrations/page.tsx` still reports pre-existing warnings/errors (`any`, hook dependency, no-img-element, and unescaped quotes). These were not introduced by this fix; the production build passes.

8. Follow-up fix for Workflow page API redirect loop
   - Root cause: FastAPI redirects `/api/v1/workflows` to `/api/v1/workflows/`, and the host Next dev rewrite could loop the workflow collection endpoint, causing the Workflow page to show `Load failed`.
   - Added explicit Next rewrite entries for both slash and non-slash `/api/v1/workflows` collection paths.
   - Restarted the host Next dev server on port 3002 so Cloudflare Tunnel uses the updated workflow rewrite.
   - Verification:
     - `npm run build` passed for the frontend, including Next.js production build and TypeScript.
     - `npx eslint next.config.ts` passed.
     - `curl -i https://insightdoc-mini.softnix.ai/api/v1/workflows -H 'Authorization: Bearer invalid-token'` now returns `HTTP/2 403` with `{"detail":"Could not validate credentials"}`, confirming it reaches backend instead of redirect-looping/503.
     - `curl -i https://insightdoc-mini.softnix.ai/api/v1/workflows/node-types -H 'Authorization: Bearer invalid-token'` returned `HTTP/2 403`, confirming non-collection workflow endpoints still proxy correctly.
     - `curl -I https://insightdoc-mini.softnix.ai/workflows` returned `HTTP/2 200`.

9. Follow-up migration for AI Agent tool calls
   - Added `AgentToolCalls`, a local adapter around Astryx `ChatToolCalls`.
   - Replaced the custom live and persisted Agent tool-call card rendering in `AgentPanel` with grouped `ChatToolCalls` rendering.
   - Mapped InsightDOC agent data to Astryx fields:
     - `status`: `running`, `complete`, or `error`
     - `target`: output path, file path, query, command, endpoint, document id, or Python code fallback
     - `node`: tool category such as document, filesystem, code, memory, skill, or integration
     - `stats`: auto-confirm badge when applicable
     - `errorMessage`: normalized tool error text
     - `resultDetail`: arguments/code, result JSON, errors, and download action for generated files
   - Verification:
     - `npm run build` passed for the frontend, including Next.js production build and TypeScript.
     - `npx eslint components/agent/AgentToolCalls.tsx` passed.
     - Restarted the host Next dev server on port 3002 so Cloudflare Tunnel loads the updated AI Agent UI.
     - `curl -I https://insightdoc-mini.softnix.ai/jobs/69b4ccdf-3330-4aa1-a3d5-13d7e0799e3f` returned `HTTP/2 200`.
   - Notes:
     - Targeted lint on `AgentPanel.tsx` still reports pre-existing `any` usage. The production build passes.

10. Follow-up fix for AI Agent activity visibility during streaming
   - Root cause: Safari/tunnel streaming can leave the panel on the generic thinking indicator while plan/tool activity is already persisted in backend message history.
   - Added a lightweight refresh loop while an Agent response is streaming so persisted `plan`, assistant `tool_calls`, and `tool` results are pulled into the panel every 1.2 seconds.
   - This keeps Astryx `ChatToolCalls` visible during processing even if live SSE chunks are delayed or missed, and still reconciles with authoritative history after `done`.
   - Verification:
     - `npm run build` passed for the frontend, including Next.js production build and TypeScript.
     - `npx eslint components/agent/AgentToolCalls.tsx` passed.
     - Restarted the host Next dev server on port 3002 so Cloudflare Tunnel loads the updated activity refresh behavior.
     - `curl -I https://insightdoc-mini.softnix.ai/jobs/543fba80-fdf9-4a46-aba0-77bf9d584d50` returned `HTTP/2 200`.

11. Follow-up fix for Profile API token redirect loop
   - Root cause: the profile page calls `/api/v1/users/me/api-tokens`, while FastAPI redirects that collection route to `/api/v1/users/me/api-tokens/`; the host Next dev rewrite could loop the redirect and surface as `503` or `too many HTTP redirects`.
   - Added explicit Next rewrite entries for both slash and non-slash `/api/v1/users/me/api-tokens` collection paths.
   - Restarted the host Next dev server on port 3002 so Cloudflare Tunnel uses the updated rewrite.
   - Verification:
     - `npm run build` passed for the frontend, including Next.js production build and TypeScript.
     - `npx eslint next.config.ts` passed.
     - `curl -i https://insightdoc-mini.softnix.ai/api/v1/users/me/api-tokens -H 'Authorization: Bearer invalid-token'` now returns `HTTP/2 403` with `{"detail":"Could not validate credentials"}`, confirming it reaches backend instead of redirect-looping/503.
     - `curl -I https://insightdoc-mini.softnix.ai/profile` returned `HTTP/2 200`.

12. UX typography pass for Integration page
   - Increased the Integration page heading and subtitle scale for clearer page hierarchy.
   - Increased catalog card labels, subtitles, status labels, and Add button text so each integration type is readable at dashboard distance.
   - Increased Connected list titles, descriptions, type chips, and empty-state text; descriptions now use a two-line clamp instead of single-line truncation.
   - Slightly improved sidebar nav contrast and weight for better scanability without increasing sidebar width.
   - Verification:
     - `npm run build` passed for the frontend, including Next.js production build and TypeScript.
     - Targeted `npx eslint app/(dashboard)/integrations/page.tsx app/(dashboard)/layout.tsx` still reports pre-existing issues in the Integration file (`any`, hook dependency, no-img-element, and one existing layout eslint-disable warning). The production build passes.

13. AI Agent start screen mission composer
   - Replaced the small empty-state prompt cards with a centered mission composer for Agent DOC.
   - Added a larger textarea, welcome copy, send control, Skill/Act/Thinking action row, and document-aware prompt suggestions.
   - Connected the first message flow so typing in the start composer creates a conversation automatically before sending.
   - Reused the existing "ยืนยันอัตโนมัติ" confirmation logic for the new Act control.
   - Added an in-context warning when Act is enabled, clarifying that destructive actions such as deleting files, approving documents, editing fields, and sending APIs are auto-approved for the current session.
   - Verification:
     - `npm run build` passed for the frontend, including Next.js production build and TypeScript.
     - Targeted `npx eslint components/agent/AgentPanel.tsx` still reports pre-existing `any` usage in the file. The production build passes.

14. Job Send to Integration modal UX pass
   - Added optional `width` and `bodyClassName` props to the shared `Modal` component while preserving existing defaults.
   - Reworked the job detail "Select Integration" modal with a wider layout, stronger header summary, scroll-bounded integration list, clearer selected state, integration type icons, empty state, status message styling, and a structured footer.
   - The footer now shows the selected destination and action context before sending reviewed document data.
   - Verification:
     - `npm run build` passed for the frontend, including Next.js production build and TypeScript.
     - Targeted `npx eslint app/(dashboard)/jobs/[id]/page.tsx components/ui/modal.tsx` still reports pre-existing issues in the job detail file (`any`, hook dependencies, no-img-element, and unused variables). The production build passes.

15. AI Agent start composer affordance cleanup
   - Replaced the ambiguous plus button in the start composer with an explicit `Skill` action using the Sparkles icon.
   - Changed the Skill Library action to use the Library icon instead of a generic settings icon.
   - Removed the non-functional `Thinking` control from the start composer action row.
   - Shortened the welcome helper text, textarea placeholder, and prompt suggestion descriptions to reduce visual noise.
   - Verification:
     - `npm run build` passed for the frontend, including Next.js production build and TypeScript.
     - Targeted `npx eslint components/agent/AgentPanel.tsx` still reports pre-existing `any` usage in the file. The production build passes.

16. AI Agent start composer Skill picker
   - Changed the start composer `Skill` action from inserting only `/` to opening a selectable skill picker.
   - The picker shows existing skills, supports `/`-based filtering from the textarea, and fills `ใช้ skill <name>` when a skill is selected.
   - Added empty and no-match states, including a shortcut to open Skill Library when no skills are available.
   - Verification:
     - `npm run build` passed for the frontend, including Next.js production build and TypeScript.
     - Targeted `npx eslint components/agent/AgentPanel.tsx` still reports pre-existing `any` usage in the file. The production build passes.
