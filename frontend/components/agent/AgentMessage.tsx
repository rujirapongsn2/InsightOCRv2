"use client"

import { useMemo } from "react"
import { Bot, User } from "lucide-react"
import { Renderer, marked } from "marked"

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
}

export default function AgentMessage({ role, content, isStreaming }: AgentMessageProps) {
    const rendered = useMemo(() => renderMarkdown(content || ""), [content])

    if (role === "user") {
        return (
            <div className="flex justify-end gap-2 px-3">
                <div className="max-w-[85%] rounded-2xl rounded-br-md bg-softnix-blue text-white px-4 py-2.5 text-sm whitespace-pre-wrap">{content}</div>
                <div className="flex-shrink-0 w-7 h-7 rounded-full bg-[#D6EAF8] flex items-center justify-center mt-1"><User className="h-3.5 w-3.5 text-softnix-blue" /></div>
            </div>
        )
    }

    if (role === "tool") return null

    return (
        <div className="flex gap-2 px-3">
            <div className="flex-shrink-0 w-7 h-7 rounded-full bg-[#D6EAF8] flex items-center justify-center mt-1"><Bot className="h-3.5 w-3.5 text-softnix-blue" /></div>
            <div className="max-w-[85%]">
                <div
                    className="rounded-2xl rounded-bl-md bg-off-white px-4 py-2.5 text-sm text-ink-navy agent-markdown"
                    dangerouslySetInnerHTML={{ __html: rendered }}
                />
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
