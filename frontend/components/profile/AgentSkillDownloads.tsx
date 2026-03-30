"use client"

import { useEffect, useMemo, useState } from "react"
import { Archive, Bot, Download, FileCode2, Settings2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Textarea } from "@/components/ui/textarea"

type AgentSkillDownloadsProps = {
  apiBaseUrl: string
  getAuthHeader: () => Record<string, string>
}

type PreviewFile = {
  id: string
  label: string
  path: string
  description: string
  content: string
}

const PACKAGE_NAME = "Softnix-InsightDOC"
const PACKAGE_FILENAME = `${PACKAGE_NAME}.zip`

function triggerBlobDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement("a")
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

export function AgentSkillDownloads({ apiBaseUrl, getAuthHeader }: AgentSkillDownloadsProps) {
  const [resolvedApiBaseUrl, setResolvedApiBaseUrl] = useState(apiBaseUrl)
  const [selectedFileId, setSelectedFileId] = useState("skill")
  const [downloadMessage, setDownloadMessage] = useState<string | null>(null)
  const [downloadError, setDownloadError] = useState<string | null>(null)
  const [downloading, setDownloading] = useState(false)

  useEffect(() => {
    if (apiBaseUrl.startsWith("http://") || apiBaseUrl.startsWith("https://")) {
      setResolvedApiBaseUrl(apiBaseUrl)
      return
    }

    if (typeof window === "undefined") {
      setResolvedApiBaseUrl(apiBaseUrl)
      return
    }

    setResolvedApiBaseUrl(`${window.location.origin}${apiBaseUrl}`)
  }, [apiBaseUrl])

  const externalBaseUrl = `${resolvedApiBaseUrl}/external`

  const previewFiles = useMemo<PreviewFile[]>(() => {
    const skillMd = `---
name: Softnix-InsightDOC
description: Use when an AI agent needs to operate InsightDOC through the external workflow API for job management, document upload, OCR processing, review, confirmation, rejection, and integration dispatch.
---

# Softnix-InsightDOC

## Runtime Setup

- API base URL: ${resolvedApiBaseUrl}
- External API base URL: ${externalBaseUrl}
- Authentication: Authorization: Bearer $INSIGHTOCR_API_TOKEN
- Environment variables are stored in .env
- Optional helper commands are available in scripts/insightocr.sh

## Standard Workflow

1. GET /external/jobs
2. POST /external/jobs
3. POST /external/jobs/{job_id}/documents
4. GET /external/schemas
5. POST /external/documents/{document_id}/process
6. GET /external/documents/{document_id}/status
7. PUT /external/documents/{document_id}/review
8. POST /external/documents/{document_id}/decision
9. GET /external/integrations
10. POST /external/jobs/{job_id}/send-integration
`

    const envFile = `INSIGHTOCR_API_TOKEN=REPLACE_WITH_PERSONAL_ACCESS_TOKEN
INSIGHTOCR_API_BASE_URL=${resolvedApiBaseUrl}
INSIGHTOCR_EXTERNAL_BASE_URL=${externalBaseUrl}
INSIGHTOCR_DEFAULT_JOB_NAME=
INSIGHTOCR_DEFAULT_SCHEMA_ID=
INSIGHTOCR_DEFAULT_INTEGRATION_NAME=
CURL_INSECURE=${["localhost", "127.0.0.1"].some((host) => externalBaseUrl.includes(host)) ? "true" : "false"}
`

    const readme = `# ${PACKAGE_NAME}

This package contains one portable AI-agent skill for InsightDOC.

Files:
- SKILL.md
- .env
- README.md
- scripts/insightocr.sh

Setup:
1. Edit .env
2. Set INSIGHTOCR_API_TOKEN from the Profile page
3. Run helper commands from the package root
`

    const script = `#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "\${BASH_SOURCE[0]}")/.." && pwd)"
source "\${ROOT_DIR}/.env"

case "\${1:-}" in
  jobs) curl -sS -H "Authorization: Bearer \${INSIGHTOCR_API_TOKEN}" "\${INSIGHTOCR_EXTERNAL_BASE_URL}/jobs" ;;
  schemas) curl -sS -H "Authorization: Bearer \${INSIGHTOCR_API_TOKEN}" "\${INSIGHTOCR_EXTERNAL_BASE_URL}/schemas" ;;
  integrations) curl -sS -H "Authorization: Bearer \${INSIGHTOCR_API_TOKEN}" "\${INSIGHTOCR_EXTERNAL_BASE_URL}/integrations" ;;
  *) echo "See README.md for full usage" >&2; exit 1 ;;
esac
`

    return [
      {
        id: "skill",
        label: "SKILL.md",
        path: `${PACKAGE_NAME}/SKILL.md`,
        description: "The main agent skill file in standard SKILL.md format.",
        content: skillMd,
      },
      {
        id: "env",
        label: ".env",
        path: `${PACKAGE_NAME}/.env`,
        description: "Editable runtime values including token, API URLs, and optional defaults.",
        content: envFile,
      },
      {
        id: "readme",
        label: "README.md",
        path: `${PACKAGE_NAME}/README.md`,
        description: "Setup and usage notes for quick installation into an agent runtime.",
        content: readme,
      },
      {
        id: "script",
        label: "scripts/insightocr.sh",
        path: `${PACKAGE_NAME}/scripts/insightocr.sh`,
        description: "Helper CLI for common API operations once .env is configured.",
        content: script,
      },
    ]
  }, [externalBaseUrl, resolvedApiBaseUrl])

  const selectedFile = previewFiles.find((file) => file.id === selectedFileId) ?? previewFiles[0]

  const handleDownloadPackage = async () => {
    setDownloading(true)
    setDownloadError(null)
    setDownloadMessage(null)

    try {
      const res = await fetch(`${apiBaseUrl}/users/me/agent-skill-pack`, {
        headers: getAuthHeader(),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.detail || "Failed to download skill package")
      }

      const blob = await res.blob()
      const disposition = res.headers.get("content-disposition")
      const filenameMatch = disposition?.match(/filename="?([^"]+)"?/)
      const filename = filenameMatch?.[1] || PACKAGE_FILENAME
      triggerBlobDownload(blob, filename)
      setDownloadMessage(`Downloaded ${filename}`)
    } catch (error: any) {
      console.error("Skill pack download error", error)
      setDownloadError(error?.message || "Failed to download skill package")
    } finally {
      setDownloading(false)
    }
  }

  return (
    <Card>
      <CardHeader className="space-y-3">
        <div className="flex items-center gap-2">
          <Bot className="h-5 w-5 text-slate-600" />
          <CardTitle>AI Agent Skill Package</CardTitle>
        </div>
        <div className="space-y-2 text-sm text-slate-600">
          <p>
            Download one standard package named <span className="font-mono">{PACKAGE_FILENAME}</span> that contains a
            single skill called <span className="font-mono">{PACKAGE_NAME}</span>.
          </p>
          <p>
            The zip includes <span className="font-mono">SKILL.md</span>, an editable <span className="font-mono">.env</span>,
            a <span className="font-mono">README.md</span>, and helper scripts so it can be installed or adapted quickly
            for different AI agent runtimes.
          </p>
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-4">
          <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
            <div className="space-y-3">
              <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
                <Archive className="h-4 w-4" />
                {PACKAGE_FILENAME}
              </div>
              <div className="space-y-2 text-sm text-slate-600">
                <p>Recommended install flow:</p>
                <ol className="list-decimal space-y-1 pl-5">
                  <li>Download and extract the zip</li>
                  <li>Edit the bundled <span className="font-mono">.env</span></li>
                  <li>Set your personal access token</li>
                  <li>Use <span className="font-mono">SKILL.md</span> and optional scripts in your target agent</li>
                </ol>
              </div>
            </div>
            <Button type="button" onClick={handleDownloadPackage} disabled={downloading}>
              <Download className="mr-2 h-4 w-4" />
              {downloading ? "Preparing..." : `Download ${PACKAGE_FILENAME}`}
            </Button>
          </div>
        </div>

        {downloadError && (
          <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {downloadError}
          </div>
        )}
        {downloadMessage && (
          <div className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
            {downloadMessage}
          </div>
        )}

        <div className="grid gap-4 md:grid-cols-[320px_1fr]">
          <div className="space-y-3">
            <div className="rounded-xl border border-slate-200 bg-white p-4">
              <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
                <Settings2 className="h-4 w-4" />
                Package Structure
              </div>
              <div className="mt-3 space-y-2">
                {previewFiles.map((file) => {
                  const isSelected = file.id === selectedFile.id
                  return (
                    <button
                      key={file.id}
                      type="button"
                      onClick={() => setSelectedFileId(file.id)}
                      className={`w-full rounded-lg border px-3 py-3 text-left transition-colors ${
                        isSelected
                          ? "border-slate-900 bg-slate-50"
                          : "border-slate-200 bg-white hover:bg-slate-50"
                      }`}
                    >
                      <div className="flex items-center gap-2 text-sm font-medium text-slate-900">
                        <FileCode2 className="h-4 w-4 text-slate-500" />
                        {file.label}
                      </div>
                      <p className="mt-1 font-mono text-xs text-slate-500">{file.path}</p>
                      <p className="mt-2 text-xs text-slate-600">{file.description}</p>
                    </button>
                  )
                })}
              </div>
            </div>
          </div>

          <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-4">
            <div className="space-y-1">
              <h3 className="text-sm font-semibold text-slate-900">{selectedFile.label}</h3>
              <p className="text-sm text-slate-600">{selectedFile.description}</p>
            </div>
            <Textarea
              readOnly
              value={selectedFile.content}
              className="mt-4 min-h-[420px] bg-slate-950 font-mono text-xs leading-6 text-slate-100"
            />
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
