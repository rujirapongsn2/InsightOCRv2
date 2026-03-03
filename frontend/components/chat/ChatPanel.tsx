"use client"

import { useState, useEffect, useRef, useCallback } from "react"
import { X, Plus, Trash2, MessageSquare, ChevronDown, AlertTriangle } from "lucide-react"
import { getApiBaseUrl } from "@/lib/api"
import ChatMessage from "./ChatMessage"
import ChatInput from "./ChatInput"

interface Integration {
    id: string
    name: string
    type: string
    status: string
    config: Record<string, any>
}

interface Conversation {
    id: string
    job_id: string
    integration_id: string | null
    title: string | null
    created_at: string
    message_count: number
}

interface Message {
    id: string
    role: "user" | "assistant"
    content: string
    model_used?: string | null
    created_at: string
}

interface ChatPanelProps {
    jobId: string
    onClose: () => void
}

export default function ChatPanel({ jobId, onClose }: ChatPanelProps) {
    const [conversations, setConversations] = useState<Conversation[]>([])
    const [activeConversation, setActiveConversation] = useState<string | null>(null)
    const [messages, setMessages] = useState<Message[]>([])
    const [inputValue, setInputValue] = useState("")
    const [streaming, setStreaming] = useState(false)
    const [streamText, setStreamText] = useState("")
    const [llmIntegrations, setLlmIntegrations] = useState<Integration[]>([])
    const [selectedIntegrationId, setSelectedIntegrationId] = useState("")
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const [showConversationList, setShowConversationList] = useState(false)
    const messagesEndRef = useRef<HTMLDivElement>(null)
    const apiBase = getApiBaseUrl()

    const getToken = () => typeof window !== "undefined" ? localStorage.getItem("token") : null

    const headers = useCallback(() => {
        const token = getToken()
        return {
            "Content-Type": "application/json",
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
        }
    }, [])

    // Auto-scroll
    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
    }, [messages, streamText])

    // Load LLM integrations on mount
    useEffect(() => {
        const load = async () => {
            try {
                const res = await fetch(`${apiBase}/integrations/active`, { headers: headers() })
                if (res.ok) {
                    const all: Integration[] = await res.json()
                    const llms = all.filter((i) => i.type === "llm")
                    setLlmIntegrations(llms)
                    if (llms.length > 0) {
                        setSelectedIntegrationId(llms[0].id)
                    }
                }
            } catch {
                // ignore
            }
        }
        load()
    }, [apiBase])

    // Load conversations for this job
    useEffect(() => {
        const load = async () => {
            setLoading(true)
            try {
                const res = await fetch(`${apiBase}/chat/conversations?job_id=${jobId}`, { headers: headers() })
                if (res.ok) {
                    const data: Conversation[] = await res.json()
                    setConversations(data)
                    if (data.length > 0) {
                        setActiveConversation(data[0].id)
                    }
                }
            } catch {
                // ignore
            } finally {
                setLoading(false)
            }
        }
        load()
    }, [apiBase, jobId])

    // Load messages when active conversation changes
    useEffect(() => {
        if (!activeConversation) {
            setMessages([])
            return
        }
        const load = async () => {
            try {
                const res = await fetch(`${apiBase}/chat/conversations/${activeConversation}`, { headers: headers() })
                if (res.ok) {
                    const data = await res.json()
                    setMessages(data.messages || [])
                }
            } catch {
                // ignore
            }
        }
        load()
    }, [activeConversation, apiBase])

    const createConversation = async () => {
        if (!selectedIntegrationId) return
        try {
            const res = await fetch(`${apiBase}/chat/conversations`, {
                method: "POST",
                headers: headers(),
                body: JSON.stringify({ job_id: jobId, integration_id: selectedIntegrationId }),
            })
            if (res.ok) {
                const conv: Conversation = await res.json()
                setConversations((prev) => [conv, ...prev])
                setActiveConversation(conv.id)
                setMessages([])
                setShowConversationList(false)
                setError(null)
            }
        } catch (e: any) {
            setError("Failed to create conversation")
        }
    }

    const deleteConversation = async (convId: string) => {
        try {
            await fetch(`${apiBase}/chat/conversations/${convId}`, {
                method: "DELETE",
                headers: headers(),
            })
            setConversations((prev) => prev.filter((c) => c.id !== convId))
            if (activeConversation === convId) {
                setActiveConversation(null)
                setMessages([])
            }
        } catch {
            // ignore
        }
    }

    const sendMessage = async () => {
        if (!inputValue.trim() || streaming) return

        // Auto-create conversation if none
        if (!activeConversation) {
            if (!selectedIntegrationId) {
                setError("Please select an LLM integration first")
                return
            }
            try {
                const res = await fetch(`${apiBase}/chat/conversations`, {
                    method: "POST",
                    headers: headers(),
                    body: JSON.stringify({ job_id: jobId, integration_id: selectedIntegrationId }),
                })
                if (!res.ok) throw new Error("Failed to create conversation")
                const conv: Conversation = await res.json()
                setConversations((prev) => [conv, ...prev])
                setActiveConversation(conv.id)
                // Send message to new conversation
                await doSendMessage(conv.id, inputValue.trim())
                return
            } catch {
                setError("Failed to create conversation")
                return
            }
        }

        await doSendMessage(activeConversation, inputValue.trim())
    }

    const doSendMessage = async (convId: string, content: string) => {
        // Optimistic add user message
        const tempId = `temp-${Date.now()}`
        const userMsg: Message = {
            id: tempId,
            role: "user",
            content,
            created_at: new Date().toISOString(),
        }
        setMessages((prev) => [...prev, userMsg])
        setInputValue("")
        setStreaming(true)
        setStreamText("")
        setError(null)

        try {
            const res = await fetch(`${apiBase}/chat/conversations/${convId}/messages`, {
                method: "POST",
                headers: headers(),
                body: JSON.stringify({ content }),
            })

            if (!res.ok) {
                const errData = await res.json().catch(() => ({ detail: "Request failed" }))
                throw new Error(errData.detail || "Request failed")
            }

            const reader = res.body?.getReader()
            if (!reader) throw new Error("No stream reader")

            const decoder = new TextDecoder()
            let accumulated = ""
            let fullOutput = ""
            let assistantMsgId = ""

            while (true) {
                const { done, value } = await reader.read()
                if (done) break

                accumulated += decoder.decode(value, { stream: true })
                const lines = accumulated.split("\n")
                accumulated = lines.pop() || ""

                for (const line of lines) {
                    if (!line.startsWith("data: ")) continue
                    const jsonStr = line.slice(6).trim()
                    if (!jsonStr) continue

                    try {
                        const evt = JSON.parse(jsonStr)
                        if (evt.type === "delta") {
                            fullOutput += evt.text
                            setStreamText(fullOutput)
                        } else if (evt.type === "done") {
                            fullOutput = evt.full_output || fullOutput
                            assistantMsgId = evt.message_id || ""
                        } else if (evt.type === "error") {
                            throw new Error(evt.message)
                        }
                    } catch (parseErr: any) {
                        if (parseErr.message && !parseErr.message.includes("JSON")) {
                            throw parseErr
                        }
                    }
                }
            }

            // Add assistant message to state
            const assistantMsg: Message = {
                id: assistantMsgId || `assistant-${Date.now()}`,
                role: "assistant",
                content: fullOutput,
                created_at: new Date().toISOString(),
            }
            setMessages((prev) => [...prev, assistantMsg])

            // Update conversation title in list if first message
            setConversations((prev) =>
                prev.map((c) =>
                    c.id === convId && !c.title
                        ? { ...c, title: content.slice(0, 50) + (content.length > 50 ? "..." : ""), message_count: c.message_count + 2 }
                        : c.id === convId
                        ? { ...c, message_count: c.message_count + 2 }
                        : c
                )
            )
        } catch (e: any) {
            setError(e.message || "Failed to send message")
        } finally {
            setStreaming(false)
            setStreamText("")
        }
    }

    const noLlm = llmIntegrations.length === 0
    const hasProcessedDocs = true // Documents are checked server-side

    return (
        <div className="fixed right-0 top-0 h-screen w-full md:w-[420px] bg-white border-l shadow-2xl z-50 flex flex-col">
            {/* Header */}
            <div className="flex items-center justify-between px-4 py-3 border-b bg-gradient-to-r from-blue-50 to-white">
                <div className="flex items-center gap-2">
                    <MessageSquare className="h-5 w-5 text-blue-600" />
                    <h2 className="font-semibold text-slate-800">ChatDOC</h2>
                </div>
                <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-slate-100 transition-colors">
                    <X className="h-5 w-5 text-slate-500" />
                </button>
            </div>

            {/* Integration selector */}
            {noLlm ? (
                <div className="px-4 py-3 bg-amber-50 border-b flex items-start gap-2">
                    <AlertTriangle className="h-4 w-4 text-amber-600 mt-0.5 flex-shrink-0" />
                    <div className="text-sm">
                        <p className="text-amber-800 font-medium">No LLM Integration</p>
                        <p className="text-amber-600 text-xs mt-0.5">
                            Please configure an LLM integration first in{" "}
                            <a href="/integrations" className="underline">Integrations</a>.
                        </p>
                    </div>
                </div>
            ) : (
                <div className="px-4 py-2 border-b bg-slate-50 flex items-center gap-2">
                    <label className="text-xs text-slate-500 flex-shrink-0">LLM:</label>
                    <select
                        value={selectedIntegrationId}
                        onChange={(e) => setSelectedIntegrationId(e.target.value)}
                        className="flex-1 text-xs border rounded-md px-2 py-1.5 bg-white text-slate-700 focus:outline-none focus:ring-1 focus:ring-blue-500"
                    >
                        {llmIntegrations.map((i) => (
                            <option key={i.id} value={i.id}>
                                {i.name}
                            </option>
                        ))}
                    </select>
                </div>
            )}

            {/* Conversation list toggle */}
            {conversations.length > 0 && (
                <div className="border-b">
                    <button
                        onClick={() => setShowConversationList(!showConversationList)}
                        className="w-full px-4 py-2 flex items-center justify-between text-xs text-slate-600 hover:bg-slate-50 transition-colors"
                    >
                        <span>{conversations.length} conversation{conversations.length !== 1 ? "s" : ""}</span>
                        <ChevronDown className={`h-3.5 w-3.5 transition-transform ${showConversationList ? "rotate-180" : ""}`} />
                    </button>
                    {showConversationList && (
                        <div className="max-h-40 overflow-y-auto px-2 pb-2 space-y-1">
                            {conversations.map((conv) => (
                                <div
                                    key={conv.id}
                                    className={`flex items-center justify-between rounded-lg px-3 py-2 text-xs cursor-pointer transition-colors group ${
                                        conv.id === activeConversation
                                            ? "bg-blue-50 text-blue-700 border border-blue-200"
                                            : "hover:bg-slate-50 text-slate-600"
                                    }`}
                                    onClick={() => {
                                        setActiveConversation(conv.id)
                                        setShowConversationList(false)
                                    }}
                                >
                                    <span className="truncate flex-1">{conv.title || "New Chat"}</span>
                                    <button
                                        onClick={(e) => {
                                            e.stopPropagation()
                                            deleteConversation(conv.id)
                                        }}
                                        className="p-1 rounded hover:bg-red-100 opacity-0 group-hover:opacity-100 transition-opacity"
                                    >
                                        <Trash2 className="h-3 w-3 text-red-500" />
                                    </button>
                                </div>
                            ))}
                            <button
                                onClick={createConversation}
                                disabled={noLlm}
                                className="w-full flex items-center justify-center gap-1 rounded-lg px-3 py-2 text-xs text-blue-600 hover:bg-blue-50 border border-dashed border-blue-200 disabled:opacity-40"
                            >
                                <Plus className="h-3 w-3" /> New Chat
                            </button>
                        </div>
                    )}
                </div>
            )}

            {/* Messages */}
            <div className="flex-1 overflow-y-auto py-4 space-y-4">
                {loading ? (
                    <div className="flex items-center justify-center h-full text-sm text-slate-400">Loading...</div>
                ) : messages.length === 0 && !streaming ? (
                    <div className="flex flex-col items-center justify-center h-full px-8 text-center">
                        <MessageSquare className="h-12 w-12 text-slate-200 mb-4" />
                        <p className="text-sm text-slate-500 font-medium">Chat with your documents</p>
                        <p className="text-xs text-slate-400 mt-1">
                            Ask questions, compare data, or get summaries from your OCR-processed documents.
                        </p>
                    </div>
                ) : (
                    <>
                        {messages.map((msg) => (
                            <ChatMessage
                                key={msg.id}
                                role={msg.role}
                                content={msg.content}
                                modelUsed={msg.model_used}
                            />
                        ))}
                        {streaming && streamText && (
                            <ChatMessage role="assistant" content={streamText} isStreaming />
                        )}
                    </>
                )}
                <div ref={messagesEndRef} />
            </div>

            {/* Error */}
            {error && (
                <div className="px-4 py-2 bg-red-50 border-t text-xs text-red-600 flex items-center gap-2">
                    <AlertTriangle className="h-3.5 w-3.5 flex-shrink-0" />
                    <span className="flex-1">{error}</span>
                    <button onClick={() => setError(null)} className="text-red-400 hover:text-red-600">
                        <X className="h-3.5 w-3.5" />
                    </button>
                </div>
            )}

            {/* Input */}
            <ChatInput
                value={inputValue}
                onChange={setInputValue}
                onSend={sendMessage}
                disabled={noLlm}
                streaming={streaming}
            />
        </div>
    )
}
