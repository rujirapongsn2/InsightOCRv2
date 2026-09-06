# Softnix OCR v3 integration audit

Reviewed: 2026-09-06. Sources read directly from the running provider:

- https://111.223.37.41:9001/openapi.json
- https://111.223.37.41:9001/v3/docs-html
- https://111.223.37.41:9001/docs

OpenAPI leaves response schemas unspecified. The HTML examples explain the
response envelope but are not a substitute for live verification. Documentation
was fetched without certificate verification; deployment TLS settings are a
separate concern and were not changed by this audit.

## Integration map

| Surface | Runtime path | Softnix dependency |
| --- | --- | --- |
| Jobs upload/process | `documents.py` -> Celery `document_tasks.py` -> `anydoc_pipeline.py` | PDF text layer first; rendered/scanned pages try local Tesseract, Softnix, then configured Mistral fallback |
| Preview Retry OCR | Same task, `requested_ocr_engine` | Explicit selection forces that engine; it must fail visibly rather than silently use another engine |
| Legacy document fallback | Direct async submission and status polling in `document_tasks.py` | Full file sent to configured OCR endpoint; separate queue and total time limits |
| Jobs schema mapping | `map_anydoc_schema_fields` -> `structure.extract_structure` | Form POST `/structured-output` using selected schema and canonical document text |
| Fixed-position fields | Coordinate/text-layer extraction, local OCR; mapping has its own fallback | Does not require upstream automatic schema discovery |
| New schema sample | `/schemas/suggest-from-file` -> AnyDoc/Tesseract/Mistral -> active AI Provider | Intentionally skips Softnix OCR; changing the Softnix OCR model does not change this generator |
| Older AI suggestion upload | `/documents/extract-ocr` -> `process_ocr` | Uses Softnix for the first page, then field suggestions; kept compatible |
| Schema import validation | `/schemas/validate-import` | Form POST `/validate-schema` at the suggestion endpoint origin |
| Schema suggestion adapter | `SchemaSuggestionService.suggest_from_file` | Implements `/suggest-schema` async API but current new-schema endpoint does not call it; class also supplies local schema-to-fields conversion |
| Settings functional test | `/settings/ocr/test` | Synthetic image -> same Softnix OCR adapter, then independent fallback adapter; checks known text |
| Settings legacy connection checks | `/settings/test`, `/settings/ocr-fallback/test` | Authentication/connectivity checks only; retained for existing API callers, not used as OCR readiness evidence |
| Workflow / Agent DOC | Read Job documents/results | Consume stored text and mapped fields; do not directly invoke Softnix OCR for each Agent prompt |

## Confirmed v3 contract

- `POST /v3/ai-process-file` accepts multipart `file`, optional page selection,
  OCR engine and model, `json_schema`, `disable_structure`, `extraction_mode`,
  `use_thinking`, and other documented options. Token requires `ai:process`.
- HTTP 200 with `status: success` and `job_id` means submission was accepted.
  It does not mean document processing finished.
- The acknowledgement supplies `check_status`, `get_result`, and `stream`.
  Poll status until completed, then fetch the result. Polling avoids requiring
  an indefinitely open SSE connection through the application proxy.
- Results contain per-page raw `ocr_text`, processed Markdown in
  `ai_processing.content`, and optionally `results.combined_markdown`.
  Prefer successful Markdown, falling back to raw text for that page only.
- `disable_structure` defaults to false. Omitting it can trigger automatic
  schema generation and structured extraction, even when the caller only
  needs Markdown. InsightDOC maps its selected schema separately.
- `/structured-output` is a separate, synchronous form endpoint. There is no
  documented `/v3/structured-output` route.
- `/v3/structure-extract` is an asynchronous Hop 2 accepting JSON-encoded
  Markdown pages and a schema. It is not a drop-in URL replacement for
  `/structured-output` because both request and completion handling differ.
- `combine` merges pages of one logical document; `one_per_page` handles
  independent documents. Do not enable the latter globally for multipage
  contracts, because one contract spans multiple pages.
- v3 offers queue information and cancellation of queued jobs. Cancellation
  is not documented as reliable termination of an already-running model call.

## Corrections implemented

1. OCR-only callers, including legacy document submission, explicitly disable
   upstream structured extraction on v3. Remove the legacy empty `image_size`
   form value, which is an optional integer in the API contract.
2. Shared OCR client follows supplied status/result references, supports a
   job-ID-only acknowledgement, and rejects empty or failed terminal output.
3. Submission time is deducted from the polling budget. Transient GET failures
   retry within that budget without resubmitting a new OCR job.
4. Provider result references must stay on the configured origin and redirects
   are rejected before forwarding credentials.
5. AnyDoc, legacy Jobs, Settings tests and older suggestion upload share the
   canonical text reader. Repeated text on different pages is preserved; raw
   and processed versions of the same page are not concatenated.
6. Reported failed pages or unsuccessful page counts cannot be accepted as a
   complete OCR result. Mapping cannot conceal incomplete source extraction.
7. Structured Output URL fallback resolves to the documented origin route.
8. Older async suggestion upload offloads blocking OCR requests to a worker
   thread. Settings fallback test applies a shared deadline to upload, signed
   URL lookup and OCR; generated test text stays legible without a system font.

## Remaining design work

- Legacy full-file submission still has its own polling/retry implementation.
  Consolidate it with the shared client while preserving Redis progress,
  queue deadlines, Celery cancellation and compatibility with older jobs.
  In particular, an ambiguous connection failure on POST can create a duplicate
  upstream job on resubmission; provider idempotency is not documented.
- Persist upstream job ID, provider/stage, submitted time and failure category
  so a timed-out job can be inspected or reconciled. A local timeout does not
  prove the upstream job stopped.
- Settings still runs sequential checks in an HTTP request. A durable test run
  with status polling would handle slow provider queues without proxy timeouts.
  A passed small-image test establishes connectivity and basic OCR capability,
  not accuracy for every Thai layout, scan quality, table or large document.
- Add representative Thai PDF/image/table fixtures and expected page coverage
  before changing engine defaults or migrating mapping to Hop 2.
- Review the upstream TLS certificate/hostname and configure trust before
  enabling strict verification; do not silently flip working deployments.
- Keep raw per-page source and canonical Markdown separate from reviewed
  values. Provider/model versions and source citations should accompany
  diagnostics and downstream analysis.

## Verification

Focused mocked-provider regression suite covers OCR submission, polling,
transient failures, credentials, partial results, canonical text, fallback,
AnyDoc routing, schema mapping and schema sample upload: 59 passed.

Live checks using the configured credentials and synthetic data passed:

| Route | Check | Duration |
| --- | --- | --- |
| `/v3/ai-process-file` | Generated image marker recovered exactly | 6.589s |
| Mistral OCR fallback | Same marker recovered through upload/signed URL/OCR | 2.913s |
| `/structured-output` | Reference and numeric total matched the supplied schema/input | 11.73s |

No customer documents were sent. Current saved endpoint paths were verified as
`/v3/ai-process-file` and `/structured-output`. Live tests used the edited source
in an isolated application container; small-fixture success does not establish
all-document accuracy or large-job latency guarantees.
