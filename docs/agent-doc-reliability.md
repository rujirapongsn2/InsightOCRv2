# Agent DOC reliability assessment

## Architecture

Jobs chat uses AgentContext for Job/user scope, memory and skill discovery;
AgentLoop orchestrates provider requests and tool calls; ToolRegistry enforces
skill allowlists and per-tool deadlines. Separate native-tool and completion
provider loops share document and artifact tools. File tools verify stored bytes
before returning success. Workflow Agent nodes also use this harness, so changes
must preserve their allowlists, output namespaces and unattended execution.

## Corrections

- Document reads formerly returned only the first 5,000 OCR characters without
  coverage metadata. Reads now return bounded text plus continuation cursors,
  source identity and character ranges. Large preferred structured data has a
  separate JSON excerpt cursor. Reviewed values take precedence, including empty
  reviewed values. Character offsets are not PDF page citations.
- Search now finds whitespace-wrapped phrases and returns snippets around the
  match instead of the start of a long OCR line. Reviewed values are searchable;
  results beyond ten documents have a continuation cursor.
- Field comparison explicitly declares its scope and whether OCR differs. An
  empty field diff must never be presented as proof of semantic equivalence.
- History windows discard orphan results and incomplete call batches to avoid
  invalid provider messages after interrupted runs or long conversations.
- Runtime deadlines interrupt a silent async provider/tool wait instead of
  checking only after events. Blocking synchronous work still requires separate
  worker isolation for a hard process-level deadline.
- File writes default to outputs/ after validating Job scope. Failed PDF text
  extraction cannot produce a successful spreadsheet containing an error message.

## Acceptance and limits

Automated regressions cover complete long-text reconstruction, large structured
data, wrapped and late search matches, pagination, field-only comparison,
interrupted history, silent timeout, invalid/scanned PDF conversion, artifact
read-back and Workflow Agent compatibility.

Operator checks on a test Job:

1. Ask a question whose answer occurs after character 5,000. Confirm source and
   text range, including an explicit missing-evidence answer for absent facts.
2. Summarize all documents; confirm continuation reads and disclosed omissions
   when the iteration budget prevents full coverage.
3. Compare two documents with no structured fields but different clauses. Confirm
   the agent reads text and does not call the empty field diff an agreement.
4. Generate HTML, DOCX and PDF reports, then convert a saved text-bearing report
   to XLSX. Download each artifact and inspect its contents, tables and Thai text.
5. Try a scanned PDF conversion. It must request OCR rather than publish an empty
   or error-only workbook.

These fixes do not establish universal answer correctness or visual report
quality. Live provider evaluation and human inspection of generated artifacts
remain required. Large Jobs still need hierarchical summarization/retrieval with
durable coverage state to exceed the finite context and iteration budget.
Vector retrieval, page-level citations, resumable background execution, and
unifying the separate provider loops are follow-up architecture work, not
capabilities introduced by this patch.
