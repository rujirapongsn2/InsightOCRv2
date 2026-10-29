"""A/B measurement: replay reviewed documents through the current auto chain.

No DB writes: map_fields + annotate_span_evidence run on in-memory copies.
Ground truth = reviewed_data (what the human approved).

Usage (inside the backend image):
  cd /Volumes/Seagate/myapp/InsightOCRv2
  docker compose run --rm --no-deps -e PYTHONPATH=/app --entrypoint sh \
      backend -c "python scripts/measure_auto_chain.py"

Metrics per document:
- needs_review old->new : human review queue before vs after the chain change
- auto-saved            : was needs_review, now source_matched, value == ground truth
- risk (wrong-but-matched): now source_matched but value != ground truth
- upgraded              : grounded-upgrade replacements (upgraded_from_conflict)
- new-conflicts         : "Providers returned conflicting values" outcomes
"""
import json
from collections import Counter

from app.db.session import SessionLocal
from app.models.document import Document
from app.models.schema import DocumentSchema as SchemaModel
from app.services.field_mapping import map_fields, annotate_span_evidence

db = SessionLocal()
docs = db.query(Document).filter(Document.status == "reviewed", Document.reviewed_data.isnot(None)).all()
print(f"reviewed docs with reviewed_data: {len(docs)}")

totals = Counter()
for doc in docs:
    if not doc.schema_id:
        continue
    schema = db.query(SchemaModel).filter(SchemaModel.id == doc.schema_id).first()
    if not schema:
        continue
    old_report = (doc.extraction_metadata or {}).get("mapping") or {}
    old_fields = old_report.get("fields") or {}
    try:
        values, report = map_fields(doc.ocr_text or "", schema, db)
        annotate_span_evidence(report, doc.ocr_text, doc.ocr_pages)
    except Exception as exc:
        print(f"  {doc.filename}: mapping failed: {type(exc).__name__}: {exc}")
        continue
    new_fields = report.get("fields") or {}
    reviewed = doc.reviewed_data if isinstance(doc.reviewed_data, dict) else {}
    saves = risks = upgraded = conflicts_new = 0
    for name, ev in new_fields.items():
        old_status = (old_fields.get(name) or {}).get("status", "unknown")
        new_status = ev.get("status", "unknown")
        truth = reviewed.get(name)
        if new_status == "source_matched" and old_status == "needs_review":
            if name in values and values[name] == truth:
                saves += 1
            else:
                risks += 1
        if ev.get("upgraded_from_conflict"):
            upgraded += 1
        if new_status == "needs_review" and ev.get("reason") == "Providers returned conflicting values":
            conflicts_new += 1
    old_review_count = sum(1 for ev in old_fields.values() if (ev or {}).get("status") == "needs_review")
    new_review_count = sum(1 for ev in new_fields.values() if (ev or {}).get("status") == "needs_review")
    providers = [a.get("provider") for a in report.get("attempts", []) if a.get("status") == "completed"]
    print(f"  {doc.filename}: fields={len(new_fields)} needs_review {old_review_count}->{new_review_count} "
          f"| auto-saved={saves} risk(wrong-but-matched)={risks} upgraded={upgraded} new-conflicts={conflicts_new} "
          f"| chain={providers}")
    totals["saves"] += saves
    totals["risks"] += risks
    totals["old_review"] += old_review_count
    totals["new_review"] += new_review_count

print("TOTAL", dict(totals))
db.close()
