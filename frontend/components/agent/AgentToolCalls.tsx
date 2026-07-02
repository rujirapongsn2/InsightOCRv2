"use client"

import { type ReactNode, useCallback, useMemo, useState } from "react"
import { Download, ShieldCheck } from "lucide-react"
import {
    ChatToolCalls,
    type ChatToolCallItem,
    type ChatToolCallStatus,
} from "@astryxdesign/core/Chat"
import { downloadAgentFile, normalizeAgentFilePath } from "@/lib/agent-download"

type JsonRecord = Record<string, unknown>

export interface AgentToolCallLike {
    id?: string
    name?: string
    arguments?: unknown
    result?: unknown
    type?: string
}

interface AgentToolCallsProps {
    calls: AgentToolCallLike[]
    results?: Record<string, unknown>
    conversationId?: string
    autoConfirmedIds?: Set<string>
}

const FILE_WRITE_TOOLS = new Set(["write_file", "create_docx", "create_pdf", "convert_to_xlsx", "run_report_code"])

function isRecord(value: unknown): value is JsonRecord {
    return typeof value === "object" && value !== null && !Array.isArray(value)
}

function stringify(value: unknown): string {
    try {
        return JSON.stringify(value, null, 2)
    } catch {
        return String(value)
    }
}

function getErrorMessage(result: unknown): string | null {
    if (!isRecord(result) || !result.error) return null
    const error = result.error
    if (typeof error === "string") return error
    if (isRecord(error)) return String(error.message || error.type || stringify(error))
    return String(error)
}

function getResultPath(result: unknown): string | null {
    if (!isRecord(result) || typeof result.path !== "string") return null
    return normalizeAgentFilePath(result.path)
}

function isWriteSuccess(name: string, result: unknown): boolean {
    return FILE_WRITE_TOOLS.has(name) && isRecord(result) && result.ok === true && typeof result.path === "string"
}

function getCategory(name: string): string {
    if (["list_documents", "get_document_detail", "search_documents", "compare_documents", "update_document_field", "approve_document", "reject_document", "bulk_approve"].includes(name)) return "document"
    if (["list_integrations", "call_api_integration", "send_to_workflow"].includes(name)) return "integration"
    if (["execute_python", "run_report_code"].includes(name)) return "code"
    if (["read_file", "write_file", "list_files", "delete_file", "create_docx", "create_pdf", "convert_to_xlsx"].includes(name)) return "filesystem"
    if (["save_memory", "recall_memory", "list_memories", "forget_memory"].includes(name)) return "memory"
    if (["create_skill", "import_skill", "export_skill", "list_skills", "execute_skill", "delete_skill", "discover_skills"].includes(name)) return "skill"
    return "tool"
}

function getTarget(name: string, args: unknown, result: unknown): string | undefined {
    const argRecord = isRecord(args) ? args : {}
    const resultRecord = isRecord(result) ? result : {}
    const candidates = [
        resultRecord.path,
        argRecord.path,
        argRecord.file_path,
        argRecord.output_path,
        argRecord.filename,
        argRecord.query,
        argRecord.command,
        argRecord.endpoint,
        argRecord.integration_name,
        argRecord.document_id,
        argRecord.name,
    ]
    const found = candidates.find((candidate): candidate is string => typeof candidate === "string" && candidate.trim().length > 0)
    if (found) return found
    if (name === "execute_python" || name === "run_report_code") return "Python code"
    return undefined
}

function getStatus(result: unknown): ChatToolCallStatus {
    if (result === undefined) return "running"
    return getErrorMessage(result) ? "error" : "complete"
}

function DetailBlock({
    call,
    result,
    conversationId,
    onDownload,
    downloadingPath,
    downloadError,
}: {
    call: AgentToolCallLike
    result: unknown
    conversationId?: string
    onDownload: (path: string) => void
    downloadingPath: string | null
    downloadError: string | null
}) {
    const name = call.name || "tool"
    const args = call.arguments || {}
    const errorMessage = getErrorMessage(result)
    const path = getResultPath(result)
    const canDownload = Boolean(conversationId && path && isWriteSuccess(name, result))
    const isCodeTool = ["execute_python", "run_report_code"].includes(name) && isRecord(args) && typeof args.code === "string"

    return (
        <div className="space-y-2 text-xs">
            {isCodeTool ? (
                <details open>
                    <summary className="cursor-pointer text-[#778DA9] hover:text-[#415A77]">Code</summary>
                    <pre className="mt-1 max-h-64 overflow-auto rounded-md bg-[#0D1B2A] p-3 font-mono text-[11px] leading-relaxed text-[#A9CB2E]">{String((args as JsonRecord).code)}</pre>
                </details>
            ) : (
                <details open>
                    <summary className="cursor-pointer text-[#778DA9] hover:text-[#415A77]">Arguments</summary>
                    <pre className="mt-1 max-h-48 overflow-auto rounded-md bg-white p-2 text-[11px]">{stringify(args)}</pre>
                </details>
            )}
            {errorMessage && (
                <div className="rounded-md border border-red-200 bg-red-50 px-2 py-1.5 text-[11px] text-red-700">
                    {errorMessage}
                </div>
            )}
            {downloadError && (
                <div className="rounded-md border border-red-200 bg-red-50 px-2 py-1.5 text-[11px] text-red-700">
                    {downloadError}
                </div>
            )}
            {canDownload && path && (
                <button
                    type="button"
                    onClick={() => onDownload(path)}
                    disabled={downloadingPath === path}
                    className="inline-flex items-center gap-1.5 rounded-md border border-[#2786C2]/20 bg-white px-2.5 py-1 text-[11px] font-medium text-[#2786C2] hover:bg-[#EEF8FD] disabled:opacity-60"
                >
                    <Download className="h-3.5 w-3.5" />
                    {downloadingPath === path ? "Downloading..." : `Download ${path}`}
                </button>
            )}
            {result !== undefined && (
                <details>
                    <summary className="cursor-pointer text-[#778DA9] hover:text-[#415A77]">Result</summary>
                    <pre className="mt-1 max-h-48 overflow-auto rounded-md bg-white p-2 text-[11px]">{stringify(result)}</pre>
                </details>
            )}
        </div>
    )
}

export default function AgentToolCalls({ calls, results = {}, conversationId, autoConfirmedIds }: AgentToolCallsProps) {
    const [downloadError, setDownloadError] = useState<string | null>(null)
    const [downloadingPath, setDownloadingPath] = useState<string | null>(null)

    const handleDownload = useCallback(async (path: string) => {
        if (!conversationId || downloadingPath) return
        setDownloadError(null)
        setDownloadingPath(path)
        try {
            await downloadAgentFile(conversationId, path)
        } catch (error) {
            setDownloadError(error instanceof Error ? error.message : "Download failed")
        } finally {
            setDownloadingPath(null)
        }
    }, [conversationId, downloadingPath])

    const items: ChatToolCallItem[] = useMemo(() => calls.map((call, index) => {
        const id = call.id || `${call.name || "tool"}-${index}`
        const name = call.name || "tool"
        const result = call.result !== undefined ? call.result : results[id]
        const status = getStatus(result)
        const autoConfirmed = autoConfirmedIds?.has(id)
        const stats: ReactNode = autoConfirmed ? (
            <span className="inline-flex items-center gap-1 rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-medium text-emerald-700">
                <ShieldCheck className="h-3 w-3" />
                auto
            </span>
        ) : undefined

        return {
            key: id,
            name,
            status,
            target: getTarget(name, call.arguments, result),
            node: getCategory(name),
            stats,
            errorMessage: status === "error" ? getErrorMessage(result) || undefined : undefined,
            data: { arguments: call.arguments, result },
            resultDetail: (
                <DetailBlock
                    call={call}
                    result={result}
                    conversationId={conversationId}
                    onDownload={handleDownload}
                    downloadingPath={downloadingPath}
                    downloadError={downloadError}
                />
            ),
        }
    }), [autoConfirmedIds, calls, conversationId, downloadError, downloadingPath, handleDownload, results])

    return (
        <div className="mx-3">
            <ChatToolCalls calls={items} label={`${items.length} tool call${items.length === 1 ? "" : "s"}`} />
        </div>
    )
}
