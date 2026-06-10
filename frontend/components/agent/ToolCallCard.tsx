"use client"

import { useState } from "react"
import { ChevronDown, CheckCircle, XCircle, Loader2, Download } from "lucide-react"
import { getApiBaseUrl } from "@/lib/api"

const CATEGORY_ICONS: Record<string, string> = {
    document: "📄", integration: "🔗", code: "⚡", filesystem: "💾", memory: "🧠", skill: "🎯",
}

function getCategory(name: string): string {
    if (["list_documents", "get_document_detail", "search_documents", "compare_documents", "update_document_field", "approve_document", "reject_document", "bulk_approve"].includes(name)) return "document"
    if (["list_integrations", "call_api_integration", "send_to_workflow"].includes(name)) return "integration"
    if (name === "execute_python") return "code"
    if (["read_file", "write_file", "list_files", "delete_file"].includes(name)) return "filesystem"
    if (["save_memory", "recall_memory", "list_memories", "forget_memory"].includes(name)) return "memory"
    if (["create_skill", "import_skill", "export_skill", "list_skills", "execute_skill", "delete_skill", "discover_skills"].includes(name)) return "skill"
    return "other"
}

interface ToolCallCardProps {
    call: { id?: string; name?: string; arguments?: any }
    result?: any
    conversationId?: string
}

function buildDownloadUrl(conversationId: string, filePath: string): string {
    const base = getApiBaseUrl()
    return `${base}/agent/files/download?conversation_id=${encodeURIComponent(conversationId)}&path=${encodeURIComponent(filePath)}`
}

export default function ToolCallCard({ call, result, conversationId }: ToolCallCardProps) {
    const [expanded, setExpanded] = useState(false)
    const icon = CATEGORY_ICONS[getCategory(call.name || "")] || "🔧"
    const hasResult = result !== undefined
    const isWriteSuccess = call.name === "write_file" && result?.ok === true && result?.path

    return (
        <div className="mx-3 rounded-lg border border-hairline bg-off-white text-xs">
            <button onClick={() => setExpanded(v => !v)} className="w-full flex items-center gap-2 px-3 py-2 text-left">
                <span>{icon}</span>
                <code className="font-mono text-charcoal flex-1">{call.name}</code>
                {!hasResult && <Loader2 className="h-3 w-3 animate-spin text-mute-gray" />}
                {hasResult && (result?.error ? <XCircle className="h-3.5 w-3.5 text-red-500" /> : <CheckCircle className="h-3.5 w-3.5 text-emerald-500" />)}
                <ChevronDown className={`h-3.5 w-3.5 text-mute-gray transition-transform ${expanded ? "rotate-180" : ""}`} />
            </button>
            {expanded && (
                <div className="px-3 pb-3 space-y-2 border-t border-hairline pt-2">
                    {call.name === "execute_python" && call.arguments?.code ? (
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
                    {isWriteSuccess && conversationId && (
                        <a
                            href={buildDownloadUrl(conversationId, result.path)}
                            target="_blank"
                            rel="noreferrer"
                            className="flex items-center gap-1.5 text-softnix-blue hover:text-softnix-deep font-medium py-1"
                        >
                            <Download className="h-3.5 w-3.5" />
                            Download {result.path}
                        </a>
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
