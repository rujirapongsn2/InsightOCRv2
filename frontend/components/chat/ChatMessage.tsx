"use client"

import { useMemo } from "react"
import { Bot, User } from "lucide-react"

interface ChatMessageProps {
    role: "user" | "assistant"
    content: string
    modelUsed?: string | null
    isStreaming?: boolean
}

function simpleMarkdown(text: string): string {
    let html = text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")

    // Code blocks
    html = html.replace(/```(\w*)\n([\s\S]*?)```/g, '<pre class="bg-slate-100 rounded p-2 my-2 overflow-x-auto text-xs"><code>$2</code></pre>')
    // Inline code
    html = html.replace(/`([^`]+)`/g, '<code class="bg-slate-100 px-1 py-0.5 rounded text-xs">$1</code>')
    // Bold
    html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    // Italic
    html = html.replace(/\*(.+?)\*/g, "<em>$1</em>")
    // Line breaks
    html = html.replace(/\n/g, "<br/>")

    return html
}

export default function ChatMessage({ role, content, modelUsed, isStreaming }: ChatMessageProps) {
    const rendered = useMemo(() => simpleMarkdown(content), [content])

    if (role === "user") {
        return (
            <div className="flex justify-end gap-2 px-3">
                <div className="max-w-[85%] rounded-2xl rounded-br-md bg-blue-600 text-white px-4 py-2.5 text-sm whitespace-pre-wrap">
                    {content}
                </div>
                <div className="flex-shrink-0 w-7 h-7 rounded-full bg-blue-100 flex items-center justify-center mt-1">
                    <User className="h-3.5 w-3.5 text-blue-600" />
                </div>
            </div>
        )
    }

    return (
        <div className="flex gap-2 px-3">
            <div className="flex-shrink-0 w-7 h-7 rounded-full bg-emerald-100 flex items-center justify-center mt-1">
                <Bot className="h-3.5 w-3.5 text-emerald-600" />
            </div>
            <div className="max-w-[85%]">
                <div
                    className="rounded-2xl rounded-bl-md bg-slate-100 px-4 py-2.5 text-sm text-slate-800"
                    dangerouslySetInnerHTML={{ __html: rendered }}
                />
                {isStreaming && (
                    <div className="flex items-center gap-1 mt-1 ml-2">
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse [animation-delay:0.2s]" />
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse [animation-delay:0.4s]" />
                    </div>
                )}
            </div>
        </div>
    )
}
