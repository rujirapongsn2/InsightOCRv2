# Process Document Activity Log Enhancement

## Summary

Enhanced Activity Log for PROCESS_DOCUMENT action to include comprehensive details about document processing and integration status.

---

## Changes Made

### 1. Enhanced PROCESS_DOCUMENT Activity Log
**File**: `backend/app/tasks/document_tasks.py:326-349`

#### Previous Details:
```json
{
  "filename": "document.pdf",
  "status": "extraction_completed",
  "schema_id": "uuid-here"
}
```

#### New Details:
```json
{
  "job_name": "Invoice Processing Batch",
  "filename": "invoice_001.pdf",
  "extraction_status": "completed",
  "review_status": "pending",
  "integration_status": null,
  "schema_id": "uuid-here",
  "document_status": "extraction_completed"
}
```

#### Fields Explanation:

| Field | Type | Description | Values |
|-------|------|-------------|--------|
| `job_name` | string | Name of the job this document belongs to | Job name or "Job-{id}" if no name |
| `filename` | string | Original uploaded file name | e.g., "invoice_001.pdf" |
| `extraction_status` | string | Status of data extraction | "completed", "failed", "processing" |
| `review_status` | string | Whether document has been reviewed | "reviewed", "pending" |
| `integration_status` | null/string | Status of integration send (future use) | null (not sent yet) |
| `schema_id` | string/null | UUID of schema used for extraction | UUID or null |
| `document_status` | string | Raw document status | Full status value from database |

#### Status Logic:

**Extraction Status:**
- `"completed"` - when document.status is "extraction_completed" or "reviewed"
- `"failed"` - when document.status is "failed"
- `"processing"` - otherwise

**Review Status:**
- `"reviewed"` - when document.reviewed_data exists OR status is "reviewed"
- `"pending"` - otherwise

**Integration Status:**
- `null` - during processing (will be updated when document is sent to integration)
- Set by SEND_TO_INTEGRATION action

---

### 2. Added SEND_TO_INTEGRATION Activity Log
**File**: `backend/app/api/v1/endpoints/integrations.py:92-193`

#### New Activity Log Details:

**Successful Send:**
```json
{
  "integration_name": "LLM Integration",
  "integration_type": "llm",
  "model": "gpt-4",
  "document_count": 5,
  "successful_count": 5,
  "failed_count": 0,
  "documents": [
    {
      "id": "doc-uuid-1",
      "filename": "invoice_001.pdf",
      "status": "success"
    },
    {
      "id": "doc-uuid-2",
      "filename": "invoice_002.pdf",
      "status": "success"
    }
  ]
}
```

**Failed Send:**
```json
{
  "integration_name": "LLM Integration",
  "integration_type": "llm",
  "status": "failed",
  "error": "API key invalid"
}
```

---

## Benefits

### 1. **Complete Audit Trail**
- Track job name for context
- Monitor extraction success/failure rates
- Track review status
- Future: Track integration delivery

### 2. **Better Reporting**
- Identify which jobs have processing issues
- Monitor extraction success rates by job
- Track documents pending review
- Monitor integration delivery success

### 3. **Debugging Support**
- Full context for troubleshooting
- Clear status progression
- Integration delivery tracking

### 4. **Compliance**
- Complete processing history
- Document lifecycle tracking
- Integration delivery audit

---

## Example Activity Logs

### Example 1: Successful Processing
```json
{
  "id": "activity-uuid",
  "user_id": "user-uuid",
  "user_email": "admin@example.com",
  "action": "process_document",
  "resource_type": "document",
  "resource_id": "doc-uuid",
  "details": {
    "job_name": "Monthly Invoices - Dec 2025",
    "filename": "invoice_001.pdf",
    "extraction_status": "completed",
    "review_status": "pending",
    "integration_status": null,
    "schema_id": "schema-uuid",
    "document_status": "extraction_completed"
  },
  "ip_address": "192.168.1.100",
  "created_at": "2025-12-21T10:30:00Z"
}
```

### Example 2: Failed Processing
```json
{
  "id": "activity-uuid",
  "user_id": "user-uuid",
  "user_email": "admin@example.com",
  "action": "process_document",
  "resource_type": "document",
  "resource_id": "doc-uuid",
  "details": {
    "job_name": "Monthly Invoices - Dec 2025",
    "filename": "corrupted_file.pdf",
    "extraction_status": "failed",
    "review_status": "pending",
    "integration_status": null,
    "schema_id": "schema-uuid",
    "document_status": "failed"
  },
  "ip_address": "192.168.1.100",
  "created_at": "2025-12-21T10:31:00Z"
}
```

### Example 3: Reviewed Document
```json
{
  "id": "activity-uuid",
  "user_id": "user-uuid",
  "user_email": "admin@example.com",
  "action": "process_document",
  "resource_type": "document",
  "resource_id": "doc-uuid",
  "details": {
    "job_name": "Monthly Invoices - Dec 2025",
    "filename": "invoice_002.pdf",
    "extraction_status": "completed",
    "review_status": "reviewed",
    "integration_status": null,
    "schema_id": "schema-uuid",
    "document_status": "reviewed"
  },
  "ip_address": "192.168.1.100",
  "created_at": "2025-12-21T10:35:00Z"
}
```

### Example 4: Integration Send
```json
{
  "id": "activity-uuid",
  "user_id": "user-uuid",
  "user_email": "admin@example.com",
  "action": "send_to_integration",
  "resource_type": "integration",
  "resource_id": null,
  "details": {
    "integration_name": "LLM Integration",
    "integration_type": "llm",
    "model": "gpt-4",
    "document_count": 3,
    "successful_count": 3,
    "failed_count": 0,
    "documents": [
      {"id": "doc-1", "filename": "invoice_001.pdf", "status": "success"},
      {"id": "doc-2", "filename": "invoice_002.pdf", "status": "success"},
      {"id": "doc-3", "filename": "invoice_003.pdf", "status": "success"}
    ]
  },
  "ip_address": "192.168.1.100",
  "created_at": "2025-12-21T10:40:00Z"
}
```

---

## Files Modified

1. `backend/app/tasks/document_tasks.py` - Enhanced PROCESS_DOCUMENT logging
2. `backend/app/api/v1/endpoints/integrations.py` - Added SEND_TO_INTEGRATION logging

---

## Testing

### Test PROCESS_DOCUMENT Logging:
1. Upload a document to a job
2. Process the document
3. Check activity logs via API: `GET /api/v1/activity-logs`
4. Verify all required fields are present

### Test SEND_TO_INTEGRATION Logging:
1. Process some documents
2. Send them to LLM integration
3. Check activity logs
4. Verify integration details are logged

---

## Future Enhancements

1. **Update integration_status in PROCESS_DOCUMENT logs**
   - When document is sent to integration, update the activity log
   - Track which integration received the document

2. **Add more integration types**
   - Webhook integrations
   - API integrations
   - File export integrations

3. **Track integration response**
   - Success/failure status
   - Response time
   - Error details

---

## Migration Notes

- No database migration required
- Backward compatible (old logs still valid)
- New fields added to existing action types
- Restart backend to apply changes
