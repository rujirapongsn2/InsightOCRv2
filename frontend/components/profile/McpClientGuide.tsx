"use client"

import { useState } from "react"
import { BookOpen, Check, CheckCircle2, Copy, Terminal } from "lucide-react"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

type McpClientGuideProps = {
  apiBaseUrl: string
  tokenExample: string
}

type CodeSnippetProps = {
  title: string
  code: string
  copied: boolean
  onCopy: () => void
}

function CodeSnippet({ title, code, copied, onCopy }: CodeSnippetProps) {
  return (
    <div className="overflow-hidden rounded-md border border-slate-800 bg-slate-950">
      <div className="flex items-center justify-between gap-3 border-b border-slate-800 px-3 py-2">
        <span className="text-xs font-medium text-slate-300">{title}</span>
        <button
          type="button"
          onClick={onCopy}
          className="inline-flex min-h-8 items-center gap-1.5 rounded-md px-2 text-xs text-slate-300 transition-colors hover:bg-slate-800 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
          aria-label={copied ? `Copied ${title}` : `Copy ${title}`}
          title={copied ? "Copied" : "Copy code"}
        >
          {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className="max-h-80 overflow-auto p-3 text-xs leading-5 text-slate-100">{code}</pre>
    </div>
  )
}

export function McpClientGuide({ apiBaseUrl, tokenExample }: McpClientGuideProps) {
  const endpoint = `${apiBaseUrl}/mcp`
  const token = tokenExample || "sid_pat_REPLACE_ME"
  const [copiedSnippet, setCopiedSnippet] = useState<string | null>(null)

  const clientConfig = `{
  "mcpServers": {
    "insightdoc": {
      "url": "${endpoint}",
      "headers": {
        "Authorization": "Bearer ${token}"
      }
    }
  }
}`

  const listToolsCommand = `curl -sS -X POST \\
  ${endpoint} \\
  -H "Authorization: Bearer ${token}" \\
  -H "Content-Type: application/json" \\
  --data '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'`

  const listJobsCommand = `curl -sS -X POST \\
  ${endpoint} \\
  -H "Authorization: Bearer ${token}" \\
  -H "Content-Type: application/json" \\
  --data '{
    "jsonrpc":"2.0",
    "id":2,
    "method":"tools/call",
    "params":{
      "name":"insightdoc_list_jobs",
      "arguments":{"limit":20,"offset":0}
    }
  }'`

  const copySnippet = async (id: string, code: string) => {
    try {
      await navigator.clipboard.writeText(code)
      setCopiedSnippet(id)
      window.setTimeout(() => setCopiedSnippet(null), 1800)
    } catch {
      setCopiedSnippet(null)
    }
  }

  return (
    <Card>
      <CardHeader className="space-y-2">
        <div className="flex items-center gap-2">
          <BookOpen className="h-5 w-5 text-slate-600" />
          <CardTitle>MCP Access</CardTitle>
        </div>
        <p className="text-sm text-slate-600">
          เชื่อม AI Client เข้ากับ InsightDOC เพื่ออ่านข้อมูลหรือสั่งงานเอกสารตามสิทธิ์ของ Token
        </p>
        <div className="overflow-hidden rounded-md border border-sky-200 bg-sky-50">
          <div className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
            <div>
              <p className="text-xs font-semibold text-sky-900">MCP Endpoint URL</p>
              <code className="break-all text-xs text-sky-800">{endpoint}</code>
            </div>
            <button
              type="button"
              onClick={() => copySnippet("endpoint", endpoint)}
              className="inline-flex min-h-8 shrink-0 items-center gap-1.5 rounded-md border border-sky-200 bg-white px-2 text-xs text-sky-800 transition-colors hover:bg-sky-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
              aria-label={copiedSnippet === "endpoint" ? "Copied MCP endpoint URL" : "Copy MCP endpoint URL"}
              title={copiedSnippet === "endpoint" ? "Copied" : "Copy endpoint URL"}
            >
              {copiedSnippet === "endpoint" ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
              {copiedSnippet === "endpoint" ? "Copied" : "Copy URL"}
            </button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <details className="group rounded-md border border-slate-200">
          <summary className="cursor-pointer list-none px-4 py-3 text-sm font-medium text-slate-800">
            <span className="group-open:hidden">1. สร้าง Token และเลือกสิทธิ์</span>
            <span className="hidden group-open:inline">1. ซ่อนขั้นตอนสร้าง Token</span>
          </summary>
          <div className="space-y-3 border-t border-slate-200 p-4 text-sm text-slate-700">
            <div className="flex items-start gap-2">
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
              <span>ไปที่ <strong>Settings &gt; API Access Tokens</strong> แล้วสร้าง Token แยกสำหรับแต่ละ AI Client</span>
            </div>
            <div className="flex items-start gap-2">
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
              <span>อ่านข้อมูลอย่างเดียวใช้ Token ทั่วไป; ถ้าต้องสร้าง Job, Upload, Process หรือบันทึก Review ให้เปิด <strong>MCP-only token</strong> และเลือก scope ที่เกี่ยวข้อง</span>
            </div>
            <div className="flex items-start gap-2">
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
              <span>คัดลอก Token ทันทีหลังสร้าง และอย่าใส่ Token ใน source code, Git หรือข้อความสนทนา</span>
            </div>
          </div>
        </details>

        <details className="group rounded-md border border-slate-200">
          <summary className="cursor-pointer list-none px-4 py-3 text-sm font-medium text-slate-800">
            <span className="group-open:hidden">2. ตั้งค่า MCP Client</span>
            <span className="hidden group-open:inline">2. ซ่อนตัวอย่างการตั้งค่า Client</span>
          </summary>
          <div className="space-y-3 border-t border-slate-200 p-4">
            <p className="text-sm text-slate-700">คัดลอก code snippet นี้ไปยังไฟล์ตั้งค่าของ MCP Client แล้วแทนที่ Token ด้วยค่าจริง</p>
            <CodeSnippet title="MCP Client config (JSON)" code={clientConfig} copied={copiedSnippet === "config"} onCopy={() => copySnippet("config", clientConfig)} />
            <p className="break-all text-xs text-slate-600">Endpoint: <code>{endpoint}</code></p>
          </div>
        </details>

        <details className="group rounded-md border border-slate-200">
          <summary className="cursor-pointer list-none px-4 py-3 text-sm font-medium text-slate-800">
            <span className="group-open:hidden">3. ทดสอบการเชื่อมต่อด้วย code snippet</span>
            <span className="hidden group-open:inline">3. ซ่อนคำสั่งทดสอบ</span>
          </summary>
          <div className="space-y-3 border-t border-slate-200 p-4">
            <div className="flex items-center gap-2 text-sm font-medium text-slate-800">
              <Terminal className="h-4 w-4" />
              ตรวจรายการ Tools
            </div>
            <CodeSnippet title="curl: tools/list" code={listToolsCommand} copied={copiedSnippet === "tools"} onCopy={() => copySnippet("tools", listToolsCommand)} />
            <p className="text-xs text-slate-600">ถ้าได้ผลลัพธ์ใน <code>result.tools</code> แปลว่า Client เชื่อมต่อสำเร็จ</p>
            <CodeSnippet title="curl: insightdoc_list_jobs" code={listJobsCommand} copied={copiedSnippet === "jobs"} onCopy={() => copySnippet("jobs", listJobsCommand)} />
          </div>
        </details>

        <details className="group rounded-md border border-slate-200">
          <summary className="cursor-pointer list-none px-4 py-3 text-sm font-medium text-slate-800">
            <span className="group-open:hidden">4. ตัวอย่างคำสั่งที่ใช้กับ Agent</span>
            <span className="hidden group-open:inline">4. ซ่อนตัวอย่างคำสั่ง Agent</span>
          </summary>
          <div className="space-y-2 border-t border-slate-200 p-4 text-sm text-slate-700">
            <p>“แสดง Jobs ล่าสุดของฉัน”</p>
            <p>“ค้นหาเอกสารที่มีเลขที่ INV-2026-0001”</p>
            <p>“อ่านข้อความ OCR ของเอกสารนี้”</p>
            <p>“สร้าง Job ใหม่และ Upload เอกสารนี้”</p>
            <p>Action ที่มีผลต่อข้อมูลต้องใช้ MCP-only token, scope ที่ตรงกับงาน และการยืนยันจากผู้ใช้ก่อนเรียกใช้</p>
          </div>
        </details>

        <details className="group rounded-md border border-slate-200">
          <summary className="cursor-pointer list-none px-4 py-3 text-sm font-medium text-slate-800">
            <span className="group-open:hidden">5. แก้ปัญหาและยกเลิกการเชื่อมต่อ</span>
            <span className="hidden group-open:inline">5. ซ่อนการแก้ปัญหา</span>
          </summary>
          <div className="space-y-2 border-t border-slate-200 p-4 text-sm text-slate-700">
            <p><code>401</code>: Token ไม่ถูกต้อง, หมดอายุ หรือถูก Revoke</p>
            <p><code>403</code>: Token ไม่มี MCP-only หรือไม่มี scope ที่จำเป็น</p>
            <p><code>confirmed=true</code>: Action ต้องส่งค่านี้หลังผู้ใช้ยืนยันการทำงาน</p>
            <p>เมื่อเลิกใช้งาน ให้กด <strong>Revoke</strong> ที่ Token นั้นในแท็บ API Access Tokens</p>
          </div>
        </details>
      </CardContent>
    </Card>
  )
}
