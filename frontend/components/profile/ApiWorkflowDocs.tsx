"use client"

import { BookOpenText, Route, TerminalSquare } from "lucide-react"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

type ApiWorkflowDocsProps = {
  apiBaseUrl: string
  tokenExample: string
}

type EndpointDoc = {
  method: string
  path: string
  description: string
}

type WorkflowStep = {
  title: string
  description: string
  command: string
}

export function ApiWorkflowDocs({ apiBaseUrl, tokenExample }: ApiWorkflowDocsProps) {
  const externalBaseUrl = `${apiBaseUrl}/external`
  const authHeader = `Authorization: Bearer ${tokenExample}`
  const needsInsecureTls =
    typeof window !== "undefined" &&
    window.location.protocol === "https:" &&
    ["127.0.0.1", "localhost"].includes(window.location.hostname)
  const curlBase = needsInsecureTls ? "curl -sS -k" : "curl -sS"

  const endpoints: EndpointDoc[] = [
    { method: "GET", path: "/external/jobs", description: "List accessible jobs for this token." },
    { method: "POST", path: "/external/jobs", description: "Create a new job owned by the token user." },
    { method: "GET", path: "/external/jobs/{job_id}", description: "Fetch one job and its current status." },
    { method: "GET", path: "/external/jobs/{job_id}/documents", description: "List documents under a job." },
    { method: "POST", path: "/external/jobs/{job_id}/documents", description: "Upload a document into a job." },
    { method: "GET", path: "/external/schemas", description: "List available schemas and their fields." },
    { method: "POST", path: "/external/documents/{document_id}/process", description: "Queue OCR and structured extraction." },
    { method: "GET", path: "/external/documents/{document_id}/status", description: "Poll processing progress and extracted data." },
    { method: "PUT", path: "/external/documents/{document_id}/review", description: "Save reviewed data without final confirmation." },
    { method: "POST", path: "/external/documents/{document_id}/decision", description: "Confirm or reject a reviewed document." },
    { method: "GET", path: "/external/integrations", description: "List active integrations that can receive confirmed data." },
    { method: "POST", path: "/external/jobs/{job_id}/send-integration", description: "Send confirmed documents to an integration by name or id." },
  ]

  const workflow: WorkflowStep[] = [
    {
      title: "1. List Jobs",
      description: "Use this when an agent needs to select an existing job before uploading or processing.",
      command: `${curlBase} -H "${authHeader}" \\\n  ${externalBaseUrl}/jobs`,
    },
    {
      title: "2. Create Job",
      description: "Create a new job when the workflow should isolate a new processing batch.",
      command: `${curlBase} -X POST \\\n  -H "${authHeader}" \\\n  -H "Content-Type: application/json" \\\n  -d '{\n    "name": "Invoice Batch 2026-03-30",\n    "description": "Created by agent",\n    "schema_id": null\n  }' \\\n  ${externalBaseUrl}/jobs`,
    },
    {
      title: "3. Upload Document",
      description: "Upload a file into an existing job. Replace JOB_ID and file path.",
      command: `${curlBase} -X POST \\\n  -H "${authHeader}" \\\n  -F "file=@/absolute/path/to/document.pdf" \\\n  ${externalBaseUrl}/jobs/JOB_ID/documents`,
    },
    {
      title: "4. List Schemas",
      description: "Inspect available schemas before selecting one for extraction.",
      command: `${curlBase} -H "${authHeader}" \\\n  ${externalBaseUrl}/schemas`,
    },
    {
      title: "5. Process Document",
      description: "Trigger OCR and structured extraction. Set schema_id to null for auto mode.",
      command: `${curlBase} -X POST \\\n  -H "${authHeader}" \\\n  -H "Content-Type: application/json" \\\n  -d '{\n    "schema_id": "SCHEMA_ID"\n  }' \\\n  ${externalBaseUrl}/documents/DOCUMENT_ID/process`,
    },
    {
      title: "6. Poll Status",
      description: "Keep polling until status settles and extracted_data is available.",
      command: `${curlBase} -H "${authHeader}" \\\n  ${externalBaseUrl}/documents/DOCUMENT_ID/status`,
    },
    {
      title: "7. Save Review Data",
      description: "Persist corrected data before the final confirm or reject action.",
      command: `${curlBase} -X PUT \\\n  -H "${authHeader}" \\\n  -H "Content-Type: application/json" \\\n  -d '{\n    "reviewed_data": {\n      "document_number": "INV-2026-0001",\n      "seller": "Example Seller Co., Ltd.",\n      "buyer": "Example Buyer Co., Ltd."\n    }\n  }' \\\n  ${externalBaseUrl}/documents/DOCUMENT_ID/review`,
    },
    {
      title: "8. Confirm or Reject",
      description: "Use confirm/yes to approve, or reject to mark the document as rejected.",
      command: `${curlBase} -X POST \\\n  -H "${authHeader}" \\\n  -H "Content-Type: application/json" \\\n  -d '{\n    "decision": "confirm"\n  }' \\\n  ${externalBaseUrl}/documents/DOCUMENT_ID/decision`,
    },
    {
      title: "9. List Integrations",
      description: "Check the active integration names before sending a job onward.",
      command: `${curlBase} -H "${authHeader}" \\\n  ${externalBaseUrl}/integrations`,
    },
    {
      title: "10. Send To Integration",
      description: "By default, this sends only confirmed documents. Use include_unconfirmed=true only when intended.",
      command: `${curlBase} -X POST \\\n  -H "${authHeader}" \\\n  -H "Content-Type: application/json" \\\n  -d '{\n    "integration_name": "ERP Sync",\n    "include_unconfirmed": false\n  }' \\\n  ${externalBaseUrl}/jobs/JOB_ID/send-integration`,
    },
  ]

  return (
    <Card>
      <CardHeader className="space-y-3">
        <div className="flex items-center gap-2">
          <BookOpenText className="h-5 w-5 text-slate-600" />
          <CardTitle>API Workflow Docs</CardTitle>
        </div>
        <div className="space-y-2 text-sm text-slate-600">
          <p>
            Personal access tokens authenticate both the dashboard API and the external agent workflow API.
            External endpoints are exposed under <span className="font-mono">{externalBaseUrl}</span>.
          </p>
          <p>
            Tokens inherit the creator&apos;s permissions. A regular user sees only their own jobs, while admin users can see all jobs.
          </p>
          {needsInsecureTls && (
            <p className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-amber-900">
              Local HTTPS currently uses a self-signed certificate, so the examples below include <span className="font-mono">-k</span>.
              Remove that flag in production with trusted TLS.
            </p>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-8">
        <section className="space-y-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-800">
            <Route className="h-4 w-4" />
            Endpoint Reference
          </div>
          <div className="grid gap-3">
            {endpoints.map((endpoint) => (
              <div key={`${endpoint.method}:${endpoint.path}`} className="rounded-lg border border-slate-200 bg-white p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded bg-slate-900 px-2 py-0.5 text-xs font-semibold text-white">{endpoint.method}</span>
                  <code className="text-sm text-slate-700">{endpoint.path}</code>
                </div>
                <p className="mt-2 text-sm text-slate-600">{endpoint.description}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="space-y-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-800">
            <TerminalSquare className="h-4 w-4" />
            End-to-End cURL Examples
          </div>
          <div className="space-y-4">
            {workflow.map((step) => (
              <div key={step.title} className="rounded-xl border border-slate-200 bg-slate-50/60 p-4">
                <h3 className="text-sm font-semibold text-slate-900">{step.title}</h3>
                <p className="mt-1 text-sm text-slate-600">{step.description}</p>
                <pre className="mt-3 overflow-x-auto rounded-lg bg-slate-950 p-4 text-xs leading-6 text-slate-100">
                  {step.command}
                </pre>
              </div>
            ))}
          </div>
        </section>
      </CardContent>
    </Card>
  )
}
