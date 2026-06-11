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

