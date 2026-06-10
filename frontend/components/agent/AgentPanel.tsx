"use client"

import { useState, useEffect, useRef, useCallback } from "react"
import { X, Plus, Trash2, Bot, ChevronDown, AlertTriangle, Loader2, Brain, Library } from "lucide-react"
import { getApiBaseUrl } from "@/lib/api"
import AgentMessage from "./AgentMessage"
import ToolCallCard from "./ToolCallCard"
import ConfirmationDialog from "./ConfirmationDialog"
import ThinkingIndicator from "./ThinkingIndicator"
import SkillLibrary from "./SkillLibrary"
import ChatInput from "@/components/chat/ChatInput"

interface Integration {
    id: string
    name: string
    type: string
}

interface Conversation {
    id: string
    job_id: string
    integration_id: string | null
    title: string | null
    max_iterations: number
    created_at: string
    message_count: number
}

interface Message {
    id: string
    role: "user" | "assistant" | "tool"
    content: string | null
    tool_calls?: any[]
    tool_call_id?: string
    tool_name?: string
    tool_result?: any
    iteration?: number
    model_used?: string | null
    created_at: string
}

interface AgentEvent {
    type: string
    iteration?: number
    id?: string
    name?: string
    arguments?: any
    result?: any
    text?: string
    pending_action_id?: string
    description?: string
    message?: string
    iterations?: number
}

interface PendingAction {
    pending_action_id: string
    tool_name: string
    description: string
    arguments: any
}

interface AgentMemory {
    id: string
    scope: string
    memory_type: string
    key: string
    content: string
    importance: number
    access_count: number
    created_at: string | null
    updated_at: string | null
}

interface AgentPanelProps {
    jobId: string
    onClose?: () => void
    mode?: "overlay" | "inline"
}

export default function AgentPanel({ jobId, onClose, mode = "overlay" }: AgentPanelProps) {
    const isInline = mode === "inline"
    const [conversations, setConversations] = useState<Conversation[]>([])
    const [activeConversation, setActiveConversation] = useState<string | null>(null)
    const [messages, setMessages] = useState<Message[]>([])
    const [events, setEvents] = useState<AgentEvent[]>([])
    const [inputValue, setInputValue] = useState("")
    const [streaming, setStreaming] = useState(false)
    const [thinkingIteration, setThinkingIteration] = useState<number | null>(null)
    const [streamText, setStreamText] = useState("")
    const [pendingAction, setPendingAction] = useState<PendingAction | null>(null)
    const [llmIntegrations, setLlmIntegrations] = useState<Integration[]>([])
    const [selectedIntegrationId, setSelectedIntegrationId] = useState("")
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const [showConvList, setShowConvList] = useState(false)
    const [showMemories, setShowMemories] = useState(false)
    const [showSkillLibrary, setShowSkillLibrary] = useState(false)
    const [memoryScope, setMemoryScope] = useState<"user" | "job">("user")
    const [memories, setMemories] = useState<AgentMemory[]>([])
    const [loadingMemories, setLoadingMemories] = useState(false)
    const messagesEndRef = useRef<HTMLDivElement>(null)
    const apiBase = getApiBaseUrl()

    const getToken = () => typeof window !== "undefined" ? localStorage.getItem("token") : null
    const headers = useCallback(() => {
        const token = getToken()
        return { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) }
    }, [])

    useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: "smooth" }) }, [messages, streamText, events])

    useEffect(() => {
        const load = async () => {
            try {
                const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
                if (!token) return
                const { getActiveIntegrations } = await import("@/lib/integrations-api")
                const all: Integration[] = await getActiveIntegrations(token)
                const llms = all.filter((i: Integration) => i.type === "llm")
                setLlmIntegrations(llms)
                if (llms.length > 0) setSelectedIntegrationId(llms[0].id)
            } catch { }
        }
        load()
    }, [])

    useEffect(() => {
        const load = async () => {
            setLoading(true)
            try {
                const res = await fetch(`${apiBase}/agent/conversations?job_id=${jobId}`, { headers: headers() })
                if (res.ok) {
                    const data: Conversation[] = await res.json()
                    setConversations(data)
                    if (data.length > 0) setActiveConversation(data[0].id)
                }
            } catch { } finally { setLoading(false) }
        }
        load()
    }, [apiBase, jobId, headers])

    useEffect(() => {
        if (!activeConversation) { setMessages([]); return }
        const load = async () => {
            try {
                const res = await fetch(`${apiBase}/agent/conversations/${activeConversation}`, { headers: headers() })
                if (res.ok) {
                    const data = await res.json()
                    setMessages(data.messages || [])
                }
            } catch { }
        }
        load()
    }, [activeConversation, apiBase, headers])

    const loadMemories = useCallback(async (scope: "user" | "job" = memoryScope) => {
        setLoadingMemories(true)
        try {
            const res = await fetch(`${apiBase}/agent/memories?job_id=${jobId}&scope=${scope}`, { headers: headers() })
            if (res.ok) {
                const data = await res.json()
                setMemories(data.memories || [])
            }
        } catch { } finally { setLoadingMemories(false) }
    }, [apiBase, headers, jobId, memoryScope])

    const createConversation = async () => {
        if (!selectedIntegrationId) return
        try {
            const res = await fetch(`${apiBase}/agent/conversations`, {
                method: "POST", headers: headers(),
                body: JSON.stringify({ job_id: jobId, integration_id: selectedIntegrationId }),
            })
            if (res.ok) {
                const conv: Conversation = await res.json()
                setConversations(prev => [conv, ...prev])
                setActiveConversation(conv.id)
                setMessages([])
                setEvents([])
                setShowConvList(false)
                setError(null)
            }
        } catch { setError("Failed to create conversation") }
    }

    const sendMessage = async () => {
        if (!inputValue.trim() || !activeConversation || streaming) return
        const userMsg = inputValue.trim()
        setInputValue("")
        setStreaming(true)
        setStreamText("")
        setEvents([])
        setError(null)
        setThinkingIteration(null)

        const userMsgObj: Message = { id: crypto.randomUUID(), role: "user", content: userMsg, created_at: new Date().toISOString() }
        setMessages(prev => [...prev, userMsgObj])

        try {
            const res = await fetch(`${apiBase}/agent/conversations/${activeConversation}/messages`, {
                method: "POST", headers: headers(), body: JSON.stringify({ content: userMsg }),
            })
            if (!res.ok) { setError(`Server error: ${res.status}`); setStreaming(false); return }

            const reader = res.body!.getReader()
            const decoder = new TextDecoder()
            let buffer = ""
            let finalText = ""
            const newEvents: AgentEvent[] = []

            while (true) {
                const { done, value } = await reader.read()
                if (done) break
                buffer += decoder.decode(value, { stream: true })
                const lines = buffer.split("\n")
                buffer = lines.pop() || ""
                for (const line of lines) {
                    if (!line.startsWith("data: ")) continue
                    try {
                        const evt: AgentEvent = JSON.parse(line.slice(6))
                        switch (evt.type) {
                            case "thinking":
                                setThinkingIteration(evt.iteration || null)
                                break
                            case "tool_call":
                            case "tool_result":
                            case "tool_rejected":
                                newEvents.push(evt)
                                setEvents([...newEvents])
                                break
                            case "confirmation_required":
                                setPendingAction(evt as unknown as PendingAction)
                                break
                            case "delta":
                                finalText += evt.text || ""
                                setStreamText(finalText)
                                break
                            case "done":
                                setStreaming(false)
                                setThinkingIteration(null)
                                if (finalText) {
                                    setMessages(prev => [...prev, { id: crypto.randomUUID(), role: "assistant", content: finalText, created_at: new Date().toISOString() }])
                                    setStreamText("")
                                }
                                break
                            case "error":
                                setError(evt.message || "Agent error")
                                setStreaming(false)
                                break
                        }
                    } catch { }
                }
            }
        } catch (e: any) {
            setError(e.message || "Network error")
            setStreaming(false)
        }
    }

    const confirmAction = async (approved: boolean) => {
        if (!pendingAction) return
        await fetch(`${apiBase}/agent/confirm/${pendingAction.pending_action_id}`, {
            method: "POST", headers: headers(), body: JSON.stringify({ approved }),
        })
        setPendingAction(null)
    }

    const deleteConversation = async (convId: string) => {
        await fetch(`${apiBase}/agent/conversations/${convId}`, { method: "DELETE", headers: headers() })
        setConversations(prev => prev.filter(c => c.id !== convId))
        if (activeConversation === convId) { setActiveConversation(null); setMessages([]); setEvents([]) }
    }

    const toggleMemories = async () => {
        const next = !showMemories
        setShowMemories(next)
        if (next) await loadMemories(memoryScope)
    }

    const toolResultsMap: Record<string, any> = {}
    for (const evt of events) {
        if (evt.type === "tool_result" && evt.id) toolResultsMap[evt.id] = evt.result
    }

    return (
        <div className={
            isInline
                ? "w-full bg-white border rounded-lg shadow-sm flex flex-col"
                : "fixed inset-y-0 right-0 w-[440px] bg-white shadow-2xl border-l flex flex-col z-40"
        } style={isInline ? { minHeight: "70vh" } : undefined}>
            {/* Header */}
            <div className={`flex items-center justify-between px-4 py-3 border-b ${isInline ? "bg-gradient-to-r from-softnix-deep to-softnix-blue rounded-t-lg" : "bg-gradient-to-r from-softnix-deep to-softnix-blue"}`}>
                <div className="flex items-center gap-2">
                    <Bot className="h-5 w-5 text-white" />
                    <span className="font-semibold text-white text-sm">Agent DOC</span>
                    {streaming && <ThinkingIndicator iteration={thinkingIteration} compact />}
                </div>
                <div className="flex items-center gap-1">
                    <button onClick={toggleMemories} className="text-white/70 hover:text-white p-1 rounded" title="Memories">
                        <Brain className="h-4 w-4" />
                    </button>
                    <button onClick={() => setShowSkillLibrary(v => !v)} className="text-white/70 hover:text-white p-1 rounded" title="Skill Library">
                        <Library className="h-4 w-4" />
                    </button>
                    <button onClick={() => setShowConvList(v => !v)} className="text-white/70 hover:text-white p-1 rounded" title="Conversations">
                        <ChevronDown className={`h-4 w-4 transition-transform ${showConvList ? "rotate-180" : ""}`} />
                    </button>
                    {!isInline && (
                        <button onClick={onClose} className="text-white/70 hover:text-white p-1 rounded"><X className="h-4 w-4" /></button>
                    )}
                </div>
            </div>

            {/* Conversation list dropdown */}
            {showConvList && (
                <div className="border-b bg-off-white p-3 space-y-2 max-h-56 overflow-y-auto">
                    <button onClick={createConversation} disabled={!selectedIntegrationId} className="w-full flex items-center gap-2 text-sm text-softnix-blue hover:text-softnix-deep font-medium disabled:opacity-40">
                        <Plus className="h-4 w-4" /> New conversation
                    </button>
                    {llmIntegrations.length > 0 && (
                        <select value={selectedIntegrationId} onChange={e => setSelectedIntegrationId(e.target.value)} className="w-full text-xs border rounded px-2 py-1">
                            {llmIntegrations.map(i => <option key={i.id} value={i.id}>{i.name}</option>)}
                        </select>
                    )}
                    {conversations.map(conv => (
                        <div key={conv.id} className={`flex items-center gap-2 p-2 rounded cursor-pointer text-sm ${activeConversation === conv.id ? "bg-[#EBF4FB] border border-[#AED6F1]" : "hover:bg-off-white"}`} onClick={() => { setActiveConversation(conv.id); setShowConvList(false) }}>
                            <span className="flex-1 truncate">{conv.title || "New conversation"}</span>
                            <button onClick={e => { e.stopPropagation(); deleteConversation(conv.id) }} className="text-mute-gray hover:text-red-500"><Trash2 className="h-3.5 w-3.5" /></button>
                        </div>
                    ))}
                    {conversations.length === 0 && !loading && <p className="text-xs text-mute-gray text-center py-2">No conversations yet</p>}
                </div>
            )}

            {showMemories && (
                <div className="border-b bg-amber-50 p-3 space-y-3 max-h-72 overflow-y-auto">
                    <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2 text-sm font-medium text-amber-900">
                            <Brain className="h-4 w-4" /> Memories
                        </div>
                        <select
                            value={memoryScope}
                            onChange={async e => {
                                const scope = e.target.value as "user" | "job"
                                setMemoryScope(scope)
                                await loadMemories(scope)
                            }}
                            className="text-xs border border-amber-200 rounded px-2 py-1 bg-white"
                        >
                            <option value="user">User</option>
                            <option value="job">Job</option>
                        </select>
                    </div>
                    <p className="text-[11px] text-amber-700">Read-only inspector. Memories are preferences or hints, not source of truth.</p>
                    {loadingMemories && <div className="flex justify-center py-3"><Loader2 className="h-4 w-4 animate-spin text-amber-600" /></div>}
                    {!loadingMemories && memories.length === 0 && <p className="text-xs text-amber-700 text-center py-2">No saved memories</p>}
                    {!loadingMemories && memories.map(memory => (
                        <div key={memory.id} className="rounded-lg border border-amber-200 bg-white p-2">
                            <div className="flex items-center justify-between gap-2">
                                <span className="text-xs font-semibold text-ink-navy truncate">{memory.key}</span>
                                <span className="text-[10px] rounded-full bg-amber-100 text-amber-700 px-2 py-0.5">{memory.memory_type}</span>
                            </div>
                            <p className="text-xs text-charcoal mt-1 whitespace-pre-wrap">{memory.content}</p>
                            <div className="mt-2 flex items-center justify-between text-[10px] text-mute-gray">
                                <span>{memory.scope}</span>
                                <span>importance {memory.importance}</span>
                            </div>
                        </div>
                    ))}
                </div>
            )}

            {/* Messages */}
            <div className="flex-1 overflow-y-auto py-4 space-y-3">
                {loading && <div className="flex justify-center py-8"><Loader2 className="h-5 w-5 animate-spin text-mute-gray" /></div>}
                {!activeConversation && !loading && (
                    <div className="text-center py-12 px-6 text-slate-gray">
                        <Bot className="h-10 w-10 mx-auto mb-3 text-mute-gray" />
                        <p className="text-sm font-medium">Agent DOC</p>
                        <p className="text-xs mt-1">Create a conversation to start</p>
                        <button onClick={createConversation} disabled={!selectedIntegrationId} className="mt-4 px-4 py-2 bg-softnix-blue text-white text-sm rounded-lg disabled:opacity-40 hover:bg-softnix-deep">
                            <Plus className="h-4 w-4 inline mr-1" />New Conversation
                        </button>
                    </div>
                )}
                {messages.map(msg => (
                    <AgentMessage key={msg.id} role={msg.role} content={msg.content} toolCalls={msg.tool_calls} toolResult={msg.tool_result} toolName={msg.tool_name} iteration={msg.iteration} />
                ))}
                {events.filter(e => e.type === "tool_call").map(evt => (
                    <ToolCallCard key={evt.id} call={evt} result={toolResultsMap[evt.id!]} conversationId={activeConversation || undefined} />
                ))}
                {streaming && !streamText && events.filter(e => e.type === "tool_call").length === 0 && (
                    <ThinkingIndicator iteration={thinkingIteration} />
                )}
                {streaming && streamText && (
                    <AgentMessage role="assistant" content={streamText} isStreaming />
                )}
                {error && (
                    <div className="mx-3 flex items-start gap-2 p-3 rounded-lg bg-red-50 border border-red-200">
                        <AlertTriangle className="h-4 w-4 text-red-500 mt-0.5 flex-shrink-0" />
                        <p className="text-xs text-red-700">{error}</p>
                    </div>
                )}
                <div ref={messagesEndRef} />
            </div>

            {/* Skill Library */}
            {showSkillLibrary && (
                <SkillLibrary jobId={jobId} onClose={() => setShowSkillLibrary(false)} />
            )}

            {/* Confirmation Dialog */}
            {pendingAction && <ConfirmationDialog action={pendingAction} onConfirm={() => confirmAction(true)} onReject={() => confirmAction(false)} />}

            {/* Input */}
            {activeConversation && (
                <ChatInput value={inputValue} onChange={setInputValue} onSend={sendMessage} disabled={!activeConversation} streaming={streaming} />
            )}
        </div>
    )
}
