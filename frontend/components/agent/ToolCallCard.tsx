"use client"

import { useState } from "react"
import { ChevronDown, CheckCircle, XCircle, Loader2, Download, ShieldCheck } from "lucide-react"
import { downloadAgentFile, normalizeAgentFilePath } from "@/lib/agent-download"

const CATEGORY_ICONS: Record<string, string> = {
    document: "📄", integration: "🔗", code: "⚡", filesystem: "💾", memory: "🧠", skill: "🎯",
}

function getCategory(name: string): string {
    if (["list_documents", "get_document_detail", "search_documents", "compare_documents", "update_document_field", "approve_document", "reject_document", "bulk_approve"].includes(name)) return "document"
    if (["list_integrations", "call_api_integration", "send_to_workflow"].includes(name)) return "integration"
    if (["execute_python", "run_report_code"].includes(name)) return "code"
    if (["read_file", "write_file", "list_files", "delete_file", "create_docx", "create_pdf", "convert_to_xlsx"].includes(name)) return "filesystem"
    if (["save_memory", "recall_memory", "list_memories", "forget_memory"].includes(name)) return "memory"
    if (["create_skill", "import_skill", "export_skill", "list_skills", "execute_skill", "delete_skill", "discover_skills"].includes(name)) return "skill"
    return "other"
}

interface ToolCallCardProps {
    call: { id?: string; name?: string; arguments?: any }
    result?: any
    conversationId?: string
    autoConfirmed?: boolean
}

function getErrorMessage(result: any): string | null {
    if (!result?.error) return null
    if (typeof result.error === "string") return result.error
    if (typeof result.error === "object") return result.error.message || result.error.type || JSON.stringify(result.error)
    return String(result.error)
}

export default function ToolCallCard({ call, result, conversationId, autoConfirmed }: ToolCallCardProps) {
    const [expanded, setExpanded] = useState(false)
    const icon = CATEGORY_ICONS[getCategory(call.name || "")] || "🔧"
    const hasResult = result !== undefined
    const errorMessage = getErrorMessage(result)
    const isWriteSuccess = ["write_file", "create_docx", "create_pdf", "convert_to_xlsx", "run_report_code"].includes(call.name || "") && result?.ok === true && result?.path
    const normalizedPath = isWriteSuccess ? normalizeAgentFilePath(result.path) : ""
    const [downloadError, setDownloadError] = useState<string | null>(null)
    const [downloading, setDownloading] = useState(false)

    const handleDownload = async () => {
        if (!conversationId || !result?.path || downloading) return
        setDownloadError(null)
        setDownloading(true)
        try {
            await downloadAgentFile(conversationId, normalizedPath)
        } catch (error) {
            setDownloadError(error instanceof Error ? error.message : "Download failed")
        } finally {
            setDownloading(false)
        }
    }

    return (
        <div className="mx-3 rounded-lg border border-hairline bg-off-white text-xs">
            <button onClick={() => setExpanded(v => !v)} className="w-full flex items-center gap-2 px-3 py-2 text-left">
                <span>{icon}</span>
                <code className="font-mono text-charcoal flex-1">{call.name}</code>
                {autoConfirmed && (
                    <span className="inline-flex items-center gap-1 rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-medium text-emerald-700" title="Auto-confirmed โดย Confirm All toggle">
                        <ShieldCheck className="h-3 w-3" />
                        auto
                    </span>
                )}
                {!hasResult && <Loader2 className="h-3 w-3 animate-spin text-mute-gray" />}
                {hasResult && (errorMessage ? <XCircle className="h-3.5 w-3.5 text-red-500" /> : <CheckCircle className="h-3.5 w-3.5 text-emerald-500" />)}
                <ChevronDown className={`h-3.5 w-3.5 text-mute-gray transition-transform ${expanded ? "rotate-180" : ""}`} />
            </button>
            {errorMessage && !expanded && (
                <div className="px-3 pb-2 text-[11px] text-red-600 line-clamp-2">
                    {errorMessage}
                </div>
            )}
            {isWriteSuccess && conversationId && !expanded && (
                <div className="px-3 pb-2">
                    <button
                        type="button"
                        onClick={event => { event.stopPropagation(); handleDownload() }}
                        disabled={downloading}
                        className="inline-flex items-center gap-1.5 rounded-md border border-softnix-blue/20 bg-white px-2.5 py-1 text-[11px] font-medium text-softnix-blue hover:bg-[#EEF8FD] disabled:opacity-60"
                    >
                        <Download className="h-3.5 w-3.5" />
                        {downloading ? "Downloading..." : `Download ${normalizedPath}`}
                    </button>
                </div>
            )}
            {downloadError && !expanded && (
                <div className="px-3 pb-2 text-[11px] text-red-600 line-clamp-2">
                    {downloadError}
                </div>
            )}
            {expanded && (
                <div className="px-3 pb-3 space-y-2 border-t border-hairline pt-2">
                    {["execute_python", "run_report_code"].includes(call.name || "") && call.arguments?.code ? (
                        <details open>
                            <summary className="cursor-pointer text-slate-gray hover:text-charcoal">Code</summary>
                            <pre className="bg-slate-900 text-emerald-300 rounded p-3 overflow-auto mt-1 text-[11px] font-mono leading-relaxed max-h-64">{call.arguments.code}</pre>
                        </details>
                    ) : (
                        <details open>
                            <summary className="cursor-pointer text-slate-gray hover:text-charcoal">Arguments</summary>
                            <pre className="bg-white rounded p-2 overflow-auto mt-1 text-[11px]">{JSON.stringify(call.arguments, null, 2)}</pre>
                        </details>
                    )}
                    {errorMessage && (
                        <div className="rounded border border-red-200 bg-red-50 px-2 py-1.5 text-[11px] text-red-700">
                            {errorMessage}
                        </div>
                    )}
                    {downloadError && (
                        <div className="rounded border border-red-200 bg-red-50 px-2 py-1.5 text-[11px] text-red-700">
                            {downloadError}
                        </div>
                    )}
                    {isWriteSuccess && conversationId && (
                        <button
                            type="button"
                            onClick={handleDownload}
                            disabled={downloading}
                            className="flex items-center gap-1.5 text-softnix-blue hover:text-softnix-deep font-medium py-1 disabled:opacity-60"
                        >
                            <Download className="h-3.5 w-3.5" />
                            {downloading ? "Downloading..." : `Download ${normalizedPath}`}
                        </button>
                    )}
                    {hasResult && (
                        <details open>
                            <summary className="cursor-pointer text-slate-gray hover:text-charcoal">Result</summary>
                            <pre className="bg-white rounded p-2 overflow-auto mt-1 text-[11px]">{JSON.stringify(result, null, 2)}</pre>
                        </details>
                    )}
                </div>
            )}
        </div>
    )
}
