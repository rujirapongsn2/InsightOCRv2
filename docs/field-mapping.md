# Field mapping

Jobs and fixed-position sample preview share field coercion and evidence through
`services/field_mapping.py`. OCR engine selection remains independent.

## Routing

- Fixed-position fields read the source file and keep the page/bounding box.
- In Auto mode, explicit `validation_rules.source_labels` can read a unique
  `Label: value` line. Labels are literals, not user-supplied regular expressions.
- Remaining fields go to Softnix `/structured-output`.
- Auto fallback uses the active OpenAI-compatible provider selected under
  Settings > Field Mapping, or the default AI provider if no override is saved.
  It retries missing, invalid or weakly supported semantic fields. Successful
  positioned values are retained. Conflicting candidates are recorded for review.
- Auto fallback may be disabled. Explicit engine selection overrides the default
  policy for a retry; fixed-position values still use their locators first.

There are no automatic numeric corrections. Optional absent fields are reported
as missing, not provider failures. Array evidence requires row alignment review.
Finding a unique value in source text is labelled `source_matched`, never verified
semantic correctness. Fixed-position reads remain `needs_review` until template
alignment can be verified or a user reviews the result.

## Explicit arithmetic rules

Schema field `validation_rules` supports:

```json
{"source_labels": ["Invoice No", "Document No"]}
```

```json
{"equals_product_of": ["quantity", "unit_price"], "arithmetic_tolerance": "0.01"}
```

```json
{"equals_sum_of": "items.amount", "arithmetic_tolerance": "0.01"}
```

These optional rules can be supplied through the schema API. No arithmetic rules
are inferred automatically from field names. Missing operands and discrepancies
require review. Existing min/max/pattern/date/array type checks also apply.

## Retry and provenance

`POST /documents/{id}/retry-mapping` accepts `engine` and optional `fields`.
It checks document access and atomically queues a document task. OCR text and
reviewed data are preserved. Results are extraction proposals; the UI explicitly
applies a proposal to the editor before Save Changes. Unresolved previous values
are retained and marked as such. Changed document text or schema during a run
invalidates the result. Reports contain schema/text/file hashes, field evidence,
provider attempts, elapsed time and unresolved/review fields.

Settings provider tests use synthetic reference and amount fields, run through
Celery, and expose owner-scoped Redis results for 30 minutes. Primary and fallback
are tested separately. A passed probe is basic functional readiness, not a
guarantee of accuracy on large or complex documents.

## Time limits

- Softnix Structured Output request timeout: `MAPPING_SOFTNIX_REQUEST_TIMEOUT_SECONDS=240`.
- OpenAI-compatible LLM fallback request timeout: `MAPPING_LLM_REQUEST_TIMEOUT_SECONDS=120`.
- Remaining stage budget: `MAPPING_TOTAL_TIMEOUT_SECONDS=300`.
- Retry task soft/hard limits: 360/390 seconds.
- Mapping probe task soft/hard limits: 300/330 seconds.

HTTP client timeouts bound connection/read waits, not strict wall-clock duration
of a streaming response. The budget is checked between stages and passed into
provider requests. The Celery task limits provide the outer retry limit. The
existing OCR task retains its global worker limits.

## Deliberate limits

Automatic template registration/alignment, vision-model region verification,
learned confidence calibration and cross-page table completeness are not yet
implemented. No engine currently reports an automatic `verified` status.
Scanned fixed-position fields use local Tesseract coordinates; malformed PDF
text-layer coordinates fall back to that source. Representative labelled Thai
documents are needed before introducing automatic acceptance thresholds.
