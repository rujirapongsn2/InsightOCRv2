# Standard Document Extraction

## Scope

Document Extraction is the standard route for supported PDFs and images. It
creates canonical Markdown for review first; Schema Mapping and Structured Data
are intentionally deferred to a later phase.

Schemas remain available to classify documents and define future mapping work,
but selecting one does not send the document to Structured Output during this
phase.

## Extraction Route

For PDFs, AnyDoc reads a reliable text layer directly. Pages without a reliable
text layer, and all supported images, use this fixed route:

1. **TesseractOCR**: local Thai and English OCR.
2. **Softnix OCR**: external OCR when local OCR cannot return text.
3. **OCR fallback**: configured cloud provider when both earlier providers
   cannot return text.

The Document list shows compact chips for the page sources that actually ran.
The Preview contains only **AI Extract**, the durable Markdown/text result.

`Legacy` remains an internal compatibility fallback only when AnyDoc cannot
accept a file or parse malformed input. It is not a user-selectable route.

## Safety Limits

- Maximum PDF pages: `ANYDOC_MAX_PAGES` (default `100`)
- Maximum rendered OCR pages: `ANYDOC_MAX_OCR_PAGES` (default `50`)
- Maximum image pixels: `ANYDOC_MAX_IMAGE_PIXELS` (default `40000000`)
- Total extraction budget: `ANYDOC_DOCUMENT_TIMEOUT_SECONDS` (default `1200`)
- TesseractOCR page timeout: `TESSERACT_OCR_TIMEOUT_SECONDS` (default `30`)
- Softnix OCR page timeout: `ANYDOC_PRIMARY_OCR_TIMEOUT_SECONDS` (default
  `90`)
- OCR fallback request timeout: `ANYDOC_FALLBACK_REQUEST_TIMEOUT_SECONDS`
  (default `120`)

AnyDoc is built in Docker from pinned commit
`82e23481480d5b54a4f4e0b3d99950f09108685c`. The image includes
`poppler-utils`, TesseractOCR, and Thai/English language data.

## Next Phase

After extraction quality and provider timing meet the rollout targets, Schema
Mapping v2 will consume this canonical Markdown in a separate, reviewable step.
