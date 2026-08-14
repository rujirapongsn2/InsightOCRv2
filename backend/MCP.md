# InsightDOC MCP Server

## คู่มือเริ่มต้นสำหรับผู้ใช้

MCP ช่วยให้ AI Client เช่น Desktop Agent, IDE Agent หรือระบบ Automation
อ่านข้อมูลจาก InsightDOC และสั่งงานเอกสารตามสิทธิ์ที่กำหนดได้ โดยไม่ต้องเขียน
REST integration เอง

### เลือกรูปแบบการใช้งาน

| ต้องการให้ Agent ทำอะไร | Token ที่ควรสร้าง |
| --- | --- |
| อ่าน Jobs, เอกสาร, OCR text, Schema และสถานะ | Personal API Token แบบทั่วไป |
| สร้าง Job | MCP-only + `mcp:jobs:write` |
| Upload เอกสาร | MCP-only + `mcp:documents:upload` |
| สั่ง Process เอกสาร | MCP-only + `mcp:documents:process` |
| บันทึกข้อมูล Review | MCP-only + `mcp:documents:review` |

เริ่มจากสิทธิ์อ่านข้อมูลก่อน แล้วค่อยเพิ่มสิทธิ์เฉพาะที่จำเป็น MCP-only token
ใช้กับ REST API ปกติไม่ได้ และสามารถ Revoke แยกตาม Agent ได้

### ตั้งค่าใน 4 ขั้นตอน

1. เข้า **Profile > API Access Tokens**
2. ตั้งชื่อ Token ให้รู้ว่าใช้กับ Client ใด เช่น `Claude Invoice Reader`
3. เลือก MCP-only และ scopes เฉพาะที่ต้องใช้ ถ้าต้องการให้ Agent ทำงาน
4. คัดลอก Token ทันที แล้วนำไปใส่ใน MCP Client

ถ้า MCP Client อยู่คนละเครื่อง ต้องใช้ URL แบบเต็มของระบบ ไม่ใช่ path แบบย่อ
`/api/v1/mcp` เพราะ path แบบย่อใช้ได้เฉพาะ Client ที่อยู่บน origin เดียวกันเท่านั้น

สำหรับระบบที่เปิดใช้งานผ่าน `insightdoc-mini.softnix.ai` ให้ใช้ Endpoint นี้:

```text
https://insightdoc-mini.softnix.ai/api/v1/mcp
```

ตัวอย่าง config สำหรับ Client ที่รองรับ Remote MCP:

```json
{
  "mcpServers": {
    "insightdoc": {
      "url": "https://insightdoc-mini.softnix.ai/api/v1/mcp",
      "headers": {
        "Authorization": "Bearer sid_pat_REPLACE_ME"
      }
    }
  }
}
```

เปลี่ยน `sid_pat_REPLACE_ME` เป็น Token จริง และเก็บไฟล์ config ให้ปลอดภัย
อย่าส่ง Token ในแชต, source control หรือ prompt ของ Agent

### ทดสอบก่อนใช้กับ Agent

ทดสอบว่า Token ใช้งานได้:

```bash
curl -sS -X POST \
  https://insightdoc-mini.softnix.ai/api/v1/mcp \
  -H "Authorization: Bearer sid_pat_REPLACE_ME" \
  -H "Content-Type: application/json" \
  --data '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

ถ้าสำเร็จ จะได้รายการ Tools ใน `result.tools` จากนั้นลองอ่าน Jobs:

```bash
curl -sS -X POST \
  https://insightdoc-mini.softnix.ai/api/v1/mcp \
  -H "Authorization: Bearer sid_pat_REPLACE_ME" \
  -H "Content-Type: application/json" \
  --data '{
    "jsonrpc":"2.0",
    "id":2,
    "method":"tools/call",
    "params":{
      "name":"insightdoc_list_jobs",
      "arguments":{"limit":20,"offset":0}
    }
  }'
```

### วิธีสั่งงานจาก Agent

หลังเชื่อมต่อแล้ว ผู้ใช้สามารถสั่งด้วยภาษาปกติ เช่น:

- “แสดง Jobs ล่าสุดของฉัน”
- “ค้นหาเอกสารที่มีคำว่า INV-2026-0001”
- “อ่านข้อความ OCR ของเอกสารนี้”
- “สร้าง Job ชื่อ Invoice Batch และ Upload ไฟล์นี้”
- “ประมวลผลเอกสารนี้ด้วย Schema Invoice”

สำหรับคำสั่งที่สร้างหรือแก้ไขข้อมูล Agent ต้องแจ้งเป้าหมายและขอการยืนยัน
จากผู้ใช้ก่อนเรียกใช้ Tool ทุกครั้ง จากนั้นส่ง `confirmed: true` ใน arguments
ของ action นั้น แม้ MCP จะตรวจสอบ scope และสิทธิ์ซ้ำที่ Server แล้วก็ตาม

### แก้ปัญหาเบื้องต้น

| อาการ | สาเหตุที่พบบ่อย | วิธีแก้ |
| --- | --- | --- |
| `401 Not authenticated` | Token หาย, ผิด, หมดอายุ หรือถูก Revoke | สร้าง Token ใหม่และตรวจ `Authorization: Bearer ...` |
| `403 Controlled MCP actions require...` | ใช้ General Token เรียก Action | สร้าง MCP-only token |
| `requires token scope` | Token ไม่มี scope ของ Tool | เพิ่ม scope ที่ตรงกับ Tool หรือใช้ Tool แบบอ่าน |
| `Resource not found or not permitted` | ไม่มีสิทธิ์เข้าถึง Job/Document หรือ ID ผิด | ตรวจ UUID และสิทธิ์ของเจ้าของ Token |
| Client หา Server ไม่พบ | Client ไม่รองรับ Remote MCP หรือ config ไม่ถูก format | ใช้ `https://insightdoc-mini.softnix.ai/api/v1/mcp` และตรวจรูปแบบ config ของ Client |

เมื่อไม่ต้องใช้งานแล้ว ให้ Revoke Token ในหน้า Profile ทันที

InsightDOC exposes a Model Context Protocol endpoint at:

```
https://insightdoc-mini.softnix.ai/api/v1/mcp
```

Use a Personal API Token from **Profile > API Access Tokens** as a bearer token.
The endpoint accepts stateless Streamable HTTP JSON-RPC requests. Approval,
rejection, deletion, outbound integration, workflow, and web-search tools are
not exposed.

## Available tools

- `insightdoc_list_jobs`
- `insightdoc_get_job`
- `insightdoc_list_job_documents`
- `insightdoc_get_document`
- `insightdoc_get_document_text`
- `insightdoc_get_document_status`
- `insightdoc_get_document_evidence`
- `insightdoc_search_documents`
- `insightdoc_list_schemas`
- `insightdoc_list_integrations`

## Controlled actions

Action tools require a dedicated **MCP-only** Personal API Token created with
the corresponding scope. MCP-only tokens cannot be reused against ordinary
REST endpoints. New and existing general API tokens remain read-only when used
with MCP.

| Tool | Required scope | Effect |
| --- | --- | --- |
| `insightdoc_create_job` | `mcp:jobs:write` | Creates a draft job owned by the token owner. Requires `confirmed: true`. |
| `insightdoc_upload_document` | `mcp:documents:upload` | Uploads a base64 document, up to 10 MB, without changing the job to processing. Requires `confirmed: true`. |
| `insightdoc_process_document` | `mcp:documents:process` | Queues one document for extraction. Requires `confirmed: true`. |
| `insightdoc_save_document_review` | `mcp:documents:review` | Saves structured review data without approving or rejecting it. Requires `confirmed: true`. |

Every controlled action is written to the activity log with `source: mcp` and
the token ID. It still uses the token owner's normal job and document access
checks.

`insightdoc_create_job` and `insightdoc_upload_document` accept an optional
`idempotency_key` (8-128 characters). Reusing it with the same MCP token and
tool returns the original resource instead of creating a duplicate.

Each request is authorized as the token owner. Non-admin users can only read
their own jobs, documents, and integrations. Schema definitions are shared
application metadata. Integration secrets and configuration are never returned.

## Client configuration

Configure an MCP client with the full endpoint above and an `Authorization` header.
Do not use `/api/v1/mcp` alone when the MCP client runs on another machine:

```
Authorization: Bearer sid_pat_your_personal_api_token
```

The server supports the `2025-03-26` and `2025-06-18` MCP protocol versions.
It is intentionally stateless and does not open an SSE stream; clients should
send JSON-RPC requests with HTTP `POST`.

## Security notes

- Use a dedicated Personal API Token for each external agent and revoke it when
  the agent no longer needs access.
- The server rejects browser requests from origins outside the configured
  InsightDOC application origins. Native MCP clients can connect without an
  `Origin` header.
- High-impact MCP tools require explicit confirmation and audit controls. They
  are not part of this endpoint.
