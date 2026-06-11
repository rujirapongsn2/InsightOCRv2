"use client"

import { useMemo, useState } from "react"
import { Bot, User, Download } from "lucide-react"
import { Renderer, marked } from "marked"
import { downloadAgentFile, normalizeAgentFilePath } from "@/lib/agent-download"

// Configure marked for GitHub Flavored Markdown
marked.setOptions({
    gfm: true,        // tables, strikethrough, task lists, autolinks
    breaks: true,     // single newline → <br>
})

const ALLOWED_PROTOCOLS = new Set(["http:", "https:", "mailto:", "tel:"])

function escapeHtml(value: string): string {
    return value
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;")
}

function getSafeUrl(href: string): string {
    const trimmed = href.trim()
    if (!trimmed) return "#"

    if (trimmed.startsWith("//")) return "#"

    if (trimmed.startsWith("#") || trimmed.startsWith("/")) {
        return trimmed
    }

    try {
        const parsed = new URL(trimmed)
        return ALLOWED_PROTOCOLS.has(parsed.protocol) ? trimmed : "#"
    } catch {
        return "#"
    }
}

const safeRenderer = new Renderer()

safeRenderer.html = ({ text }) => escapeHtml(text)
safeRenderer.link = ({ href, title, tokens }) => {
    const safeHref = escapeHtml(getSafeUrl(href || ""))
    const safeTitle = title ? ` title="${escapeHtml(title)}"` : ""
    const text = marked.parser(tokens)
    return `<a href="${safeHref}"${safeTitle} target="_blank" rel="noopener noreferrer">${text}</a>`
}
safeRenderer.image = ({ href, title, text }) => {
    const safeSrc = escapeHtml(getSafeUrl(href || ""))
    if (safeSrc === "#") return escapeHtml(text || "")
    const safeTitle = title ? ` title="${escapeHtml(title)}"` : ""
    return `<img src="${safeSrc}" alt="${escapeHtml(text || "")}"${safeTitle} />`
}


const OUTPUT_FILE_RE = /(?:jobs\/[0-9a-f-]+\/)?outputs\/[A-Za-z0-9][A-Za-z0-9._ -]*\.(?:docx|xlsx|pptx|pdf|csv|json|html|zip)/gi
const GENERATED_FILE_RE = /\b[A-Za-z0-9][A-Za-z0-9._ -]*\.(?:docx|xlsx|pptx|csv|json|html|zip)\b/gi

function extractDownloadableFiles(text: string | null): string[] {
    if (!text) return []
    const seen = new Set<string>()
    const files: string[] = []
    for (const pattern of [OUTPUT_FILE_RE, GENERATED_FILE_RE]) {
        for (const match of text.matchAll(pattern)) {
            const path = normalizeAgentFilePath(match[0])
            if (!seen.has(path)) {
                seen.add(path)
                files.push(path)
            }
        }
    }
    return files
}

function renderMarkdown(text: string): string {
    if (!text) return ""
    try {
        const html = marked.parse(text, { renderer: safeRenderer }) as string
        return html
    } catch {
        // Fallback: basic escaping + newlines
        return escapeHtml(text).replace(/\n/g, "<br/>")
    }
}

interface AgentMessageProps {
    role: "user" | "assistant" | "tool" | string
    content: string | null
    toolCalls?: any[]
    toolResult?: any
    toolName?: string
    iteration?: number
    isStreaming?: boolean
    conversationId?: string
}

function looksLikeRawToolPayload(text: string | null): boolean {
    const trimmed = (text || "").trim()
    if (!trimmed.startsWith("{") || trimmed.length < 20) return false
    return trimmed.includes('"tool_calls"') || trimmed.includes('"type":"tool_call"') || trimmed.includes('"type": "tool_call"')
}

function extractRawReportPath(text: string | null): string | null {
    if (!text) return null
    const match = text.match(/(?:jobs\/[0-9a-f-]+\/)?outputs\/[A-Za-z0-9][A-Za-z0-9._ -]*\.html/i)
    return match ? normalizeAgentFilePath(match[0]) : null
}

export default function AgentMessage({ role, content, isStreaming, conversationId }: AgentMessageProps) {
    const isRawToolPayload = looksLikeRawToolPayload(content)
    const rawReportPath = useMemo(() => isRawToolPayload ? extractRawReportPath(content) : null, [content, isRawToolPayload])
    const displayContent = isRawToolPayload && rawReportPath
        ? `สร้างรายงาน HTML เรียบร้อยครับ\n\nไฟล์: \`${rawReportPath}\`\n\nดาวน์โหลดได้จากปุ่ม Download ใต้คำตอบนี้ครับ`
        : (content || "")
    const rendered = useMemo(() => renderMarkdown(isRawToolPayload && !rawReportPath ? "" : displayContent), [displayContent, isRawToolPayload, rawReportPath])
    const downloadableFiles = useMemo(() => rawReportPath ? [rawReportPath] : (isRawToolPayload ? [] : extractDownloadableFiles(content)), [content, isRawToolPayload, rawReportPath])
    const [downloadError, setDownloadError] = useState<string | null>(null)
    const [downloadingPath, setDownloadingPath] = useState<string | null>(null)

    const handleDownload = async (filePath: string) => {
        if (!conversationId || downloadingPath) return
        setDownloadError(null)
        setDownloadingPath(filePath)
        try {
            await downloadAgentFile(conversationId, filePath)
        } catch (error) {
            setDownloadError(error instanceof Error ? error.message : "Download failed")
        } finally {
            setDownloadingPath(null)
        }
    }

    if (role === "user") {
        return (
            <div className="flex justify-end gap-2 px-3">
                <div className="max-w-[85%] rounded-2xl rounded-br-md bg-softnix-blue text-white px-4 py-2.5 text-sm whitespace-pre-wrap">{content}</div>
                <div className="flex-shrink-0 w-7 h-7 rounded-full bg-[#D6EAF8] flex items-center justify-center mt-1"><User className="h-3.5 w-3.5 text-softnix-blue" /></div>
            </div>
        )
    }

    if (role === "tool" || (isRawToolPayload && !rawReportPath)) return null

    return (
        <div className="flex gap-2 px-3">
            <div className="flex-shrink-0 w-7 h-7 rounded-full bg-[#D6EAF8] flex items-center justify-center mt-1"><Bot className="h-3.5 w-3.5 text-softnix-blue" /></div>
            <div className="max-w-[85%]">
                <div
                    className="rounded-2xl rounded-bl-md bg-off-white px-4 py-2.5 text-sm text-ink-navy agent-markdown"
                    dangerouslySetInnerHTML={{ __html: rendered }}
                />
                {conversationId && downloadableFiles.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-2">
                        {downloadableFiles.map(filePath => (
                            <button
                                key={filePath}
                                type="button"
                                onClick={() => handleDownload(filePath)}
                                disabled={Boolean(downloadingPath)}
                                className="inline-flex items-center gap-1.5 rounded-md border border-softnix-blue/20 bg-white px-2.5 py-1 text-xs font-medium text-softnix-blue hover:bg-[#EEF8FD] disabled:opacity-60"
                            >
                                <Download className="h-3.5 w-3.5" />
                                {downloadingPath === filePath ? "Downloading..." : `Download ${filePath.split("/").pop()}`}
                            </button>
                        ))}
                    </div>
                )}
                {downloadError && (
                    <div className="mt-2 rounded border border-red-200 bg-red-50 px-2 py-1.5 text-[11px] text-red-700">
                        {downloadError}
                    </div>
                )}
                {isStreaming && (
                    <div className="flex items-center gap-1 mt-1 ml-2">
                        <span className="w-1.5 h-1.5 rounded-full bg-[#5EADD6] animate-pulse" />
                        <span className="w-1.5 h-1.5 rounded-full bg-[#5EADD6] animate-pulse [animation-delay:0.2s]" />
                        <span className="w-1.5 h-1.5 rounded-full bg-[#5EADD6] animate-pulse [animation-delay:0.4s]" />
                    </div>
                )}
            </div>
        </div>
    )
}
