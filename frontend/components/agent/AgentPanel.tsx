"use client"

import { useState, useEffect, useRef, useCallback } from "react"
import { X, Plus, Trash2, Bot, ChevronDown, AlertTriangle, Loader2, Brain, Library, Sparkles, ListChecks, Check, Circle, ShieldCheck, ShieldAlert, FileText, GitCompare, CheckCircle2 } from "lucide-react"
import { getApiBaseUrl } from "@/lib/api"
import AgentMessage from "./AgentMessage"
import ToolCallCard from "./ToolCallCard"
import ConfirmationDialog from "./ConfirmationDialog"
import ThinkingIndicator from "./ThinkingIndicator"
import SkillLibrary from "./SkillLibrary"
import ChatInput from "@/components/chat/ChatInput"

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
    role: "user" | "assistant" | "tool" | "plan"
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
    steps?: string[]
    complete?: boolean
    missing?: string[]
    success?: boolean
    failed_steps?: string[]
    stopped?: string
    tool_call_id?: string
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

interface AgentSkill {
    id: string
    name: string
    scope: string
    description: string
    trigger_hint?: string | null
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
    const [planSteps, setPlanSteps] = useState<string[]>([])
    const [reflection, setReflection] = useState<{ complete: boolean; missing: string[] } | null>(null)
    const [doneStatus, setDoneStatus] = useState<{ success: boolean; failedSteps: string[] } | null>(null)
    const [streamText, setStreamText] = useState("")
    const [pendingAction, setPendingAction] = useState<PendingAction | null>(null)
    const [autoConfirm, setAutoConfirm] = useState(false)
    const [autoConfirmedIds, setAutoConfirmedIds] = useState<Set<string>>(new Set())
    const autoConfirmRef = useRef(false)
    useEffect(() => { autoConfirmRef.current = autoConfirm }, [autoConfirm])
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const [showConvList, setShowConvList] = useState(false)
    const [showMemories, setShowMemories] = useState(false)
    const [showSkillLibrary, setShowSkillLibrary] = useState(false)
    const [memoryScope, setMemoryScope] = useState<"user" | "job">("user")
    const [memories, setMemories] = useState<AgentMemory[]>([])
    const [loadingMemories, setLoadingMemories] = useState(false)
    const [skills, setSkills] = useState<AgentSkill[]>([])
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

    const reloadActiveMessages = useCallback(async () => {
        if (!activeConversation) return
        try {
            const res = await fetch(`${apiBase}/agent/conversations/${activeConversation}`, { headers: headers() })
            if (res.ok) {
                const data = await res.json()
                setMessages(data.messages || [])
            }
        } catch { }
    }, [activeConversation, apiBase, headers])

    useEffect(() => {
        if (!activeConversation) { setMessages([]); return }
        reloadActiveMessages()
    }, [activeConversation, reloadActiveMessages])

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


    const loadSkills = useCallback(async () => {
        try {
            const res = await fetch(`${apiBase}/agent/skills`, { headers: headers() })
            if (res.ok) {
                const data = await res.json()
                setSkills(data.skills || [])
            }
        } catch { }
    }, [apiBase, headers])

    useEffect(() => { loadSkills() }, [loadSkills])

    const createConversation = async () => {
        setError(null)
        try {
            const res = await fetch(`${apiBase}/agent/conversations`, {
                method: "POST", headers: headers(),
                body: JSON.stringify({ job_id: jobId }),
            })
            if (res.ok) {
                const conv: Conversation = await res.json()
                setConversations(prev => [conv, ...prev])
                setActiveConversation(conv.id)
                setMessages([])
                setEvents([])
                setShowConvList(false)
                setError(null)
            } else {
                const data = await res.json().catch(() => null)
                setError(data?.detail || `Failed to create conversation (${res.status})`)
            }
        } catch { setError("Failed to create conversation") }
    }


    const slashCommand = inputValue.trimStart().startsWith("/")
    const slashQuery = slashCommand ? inputValue.trimStart().slice(1).trim().toLowerCase() : ""
    const filteredSkills = slashCommand
        ? skills.filter(skill => {
            if (!slashQuery) return true
            return skill.name.toLowerCase().includes(slashQuery)
                || (skill.description || "").toLowerCase().includes(slashQuery)
        }).slice(0, 8)
        : []

    const resolveOutgoingMessage = (raw: string) => {
        const trimmed = raw.trim()
        const match = trimmed.match(/^\/([a-z0-9-]+)(?:\s+([\s\S]*))?$/i)
        if (!match) return trimmed
        const skillName = match[1].toLowerCase()
        const rest = (match[2] || "").trim()
        return `ใช้ skill ${skillName}${rest ? ` ${rest}` : ""}`
    }

    const selectSkill = (skill: AgentSkill) => {
        setInputValue(`ใช้ skill ${skill.name} `)
    }

    const sendMessage = async () => {
        if (!inputValue.trim() || !activeConversation || streaming) return
        const userMsg = resolveOutgoingMessage(inputValue)
        setInputValue("")
        setStreaming(true)
        setStreamText("")
        setEvents([])
        setError(null)
        setThinkingIteration(null)
        setPlanSteps([])
        setReflection(null)
        setDoneStatus(null)

        const userMsgObj: Message = { id: crypto.randomUUID(), role: "user", content: userMsg, created_at: new Date().toISOString() }
        setMessages(prev => [...prev, userMsgObj])

        try {
            const res = await fetch(`${apiBase}/agent/conversations/${activeConversation}/messages`, {
                method: "POST", headers: headers(), body: JSON.stringify({ content: userMsg }),
            })
            if (!res.ok) {
                const data = await res.json().catch(() => null)
                setError(data?.detail || `Server error: ${res.status}`)
                setStreaming(false)
                return
            }

            const reader = res.body!.getReader()
            const decoder = new TextDecoder()
            let buffer = ""
            let finalText = ""
            const newEvents: AgentEvent[] = []
            let receivedDone = false

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
                            case "plan":
                                setPlanSteps(evt.steps || [])
                                break
                            case "reflection":
                                setReflection({ complete: !!evt.complete, missing: evt.missing || [] })
                                break
                            case "tool_call":
                            case "tool_result":
                            case "tool_rejected":
                                newEvents.push(evt)
                                setEvents([...newEvents])
                                break
                            case "confirmation_required":
                                if (autoConfirmRef.current && evt.tool_call_id && evt.pending_action_id) {
                                    const toolCallId = evt.tool_call_id
                                    const pendingId = evt.pending_action_id
                                    setAutoConfirmedIds(prev => new Set(prev).add(toolCallId))
                                    fetch(`${apiBase}/agent/confirm/${pendingId}`, {
                                        method: "POST", headers: headers(),
                                        body: JSON.stringify({ approved: true }),
                                    }).catch(err => {
                                        console.error("Auto-confirm failed, falling back to manual dialog", err)
                                        setPendingAction(evt as unknown as PendingAction)
                                    })
                                } else {
                                    setPendingAction(evt as unknown as PendingAction)
                                }
                                break
                            case "delta":
                                finalText += evt.text || ""
                                setStreamText(finalText)
                                break
                            case "done":
                                receivedDone = true
                                setStreaming(false)
                                setThinkingIteration(null)
                                setDoneStatus({
                                    success: evt.success !== false,
                                    failedSteps: Array.isArray(evt.failed_steps) ? evt.failed_steps : [],
                                })
                                if (finalText) {
                                    setMessages(prev => [...prev, { id: crypto.randomUUID(), role: "assistant", content: finalText, created_at: new Date().toISOString() }])
                                    setStreamText("")
                                }
                                // Reconcile with authoritative history (adds the persisted
                                // plan card + tool messages in order), then drop the live
                                // event cards so they don't double-render.
                                reloadActiveMessages().then(() => setEvents([]))
                                break
                            case "error":
                                setError(evt.message || "Agent error")
                                setStreaming(false)
                                break
                        }
                    } catch { }
                }
            }
            // Stream closed without a "done" event — backend likely threw an
            // unhandled exception and dropped the connection.
            if (!receivedDone) {
                setStreaming(false)
                setThinkingIteration(null)
                setError("การเชื่อมต่อขาดหาย — กรุณาลองส่งคำถามใหม่อีกครั้ง")
                reloadActiveMessages().then(() => setEvents([]))
            }
        } catch (e: any) {
            // Safari reports aborted SSE connections as "Load failed";
            // Chrome/Firefox say "Failed to fetch". Show a friendlier message.
            const raw: string = e?.message || ""
            const isConnErr = raw === "Load failed" || raw === "Failed to fetch" || raw.includes("network") || raw.includes("connection")
            setError(isConnErr ? "การเชื่อมต่อขาดหาย — กรุณาลองส่งคำถามใหม่อีกครั้ง" : raw || "Network error")
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

    const persistedToolResultsMap: Record<string, any> = {}
    for (const msg of messages) {
        if (msg.role === "tool" && msg.tool_call_id) {
            persistedToolResultsMap[msg.tool_call_id] = msg.tool_result
        }
    }

    const parseToolArguments = (value: any) => {
        if (typeof value !== "string") return value || {}
        try {
            const parsed = JSON.parse(value || "{}")
            return parsed && typeof parsed === "object" ? parsed : {}
        } catch {
            return {}
        }
    }

    const renderPlanCard = (
        steps: string[],
        refl: { complete: boolean; missing: string[] } | null,
        isLive: boolean,
        key?: string,
    ) => (
        <div key={key} className="mx-3 rounded-lg border border-softnix-blue/30 bg-softnix-blue/5 p-3">
            <div className="flex items-center gap-1.5 mb-2">
                <ListChecks className="h-3.5 w-3.5 text-softnix-blue" />
                <span className="text-[11px] font-semibold text-softnix-deep">แผนการทำงาน</span>
                {isLive && !refl && <Loader2 className="h-3 w-3 animate-spin text-softnix-blue ml-auto" />}
                {refl?.complete && <span className="ml-auto text-[10px] text-emerald-600 font-medium">ตรวจสอบครบถ้วน ✓</span>}
            </div>
            <ul className="space-y-1">
                {steps.map((step, i) => (
                    <li key={i} className="flex items-start gap-1.5 text-[11px] text-slate-gray">
                        {refl?.complete
                            ? <Check className="h-3 w-3 mt-0.5 text-emerald-500 flex-shrink-0" />
                            : <Circle className="h-3 w-3 mt-0.5 text-mute-gray flex-shrink-0" />}
                        <span>{step}</span>
                    </li>
                ))}
            </ul>
            {refl && !refl.complete && refl.missing.length > 0 && (
                <div className="mt-2 pt-2 border-t border-amber-200">
                    <p className="text-[10px] font-medium text-amber-700 mb-0.5">งานที่ยังขาด:</p>
                    <ul className="space-y-0.5">
                        {refl.missing.map((m, i) => (
                            <li key={i} className="text-[10px] text-amber-600">• {m}</li>
                        ))}
                    </ul>
                </div>
            )}
        </div>
    )

    const renderPersistedMessage = (msg: Message) => {
        if (msg.role === "tool") return null
        if (msg.role === "plan") {
            const tr = msg.tool_result || {}
            return renderPlanCard(tr.steps || [], tr.reflection || null, false, msg.id)
        }
        if (msg.role === "assistant" && Array.isArray(msg.tool_calls) && msg.tool_calls.length > 0) {
            return msg.tool_calls.map((toolCall: any, index: number) => {
                const call = {
                    id: toolCall.id || `${msg.id}-${index}`,
                    name: toolCall.function?.name || toolCall.name,
                    arguments: parseToolArguments(toolCall.function?.arguments || toolCall.arguments),
                }
                return (
                    <ToolCallCard
                        key={`${msg.id}-${call.id}`}
                        call={call}
                        result={persistedToolResultsMap[call.id]}
                        conversationId={activeConversation || undefined}
                    />
                )
            })
        }
        return (
            <AgentMessage
                key={msg.id}
                role={msg.role}
                content={msg.content}
                toolCalls={msg.tool_calls}
                toolResult={msg.tool_result}
                toolName={msg.tool_name}
                iteration={msg.iteration}
                conversationId={activeConversation || undefined}
            />
        )
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
                    <button
                        onClick={createConversation}
                        className="text-xs px-2 py-1 rounded flex items-center gap-1 bg-white/15 hover:bg-white/25 text-white transition-colors"
                        title="เริ่ม conversation ใหม่"
                    >
                        <Plus className="h-3.5 w-3.5" />
                        <span className="hidden sm:inline">ใหม่</span>
                    </button>
                    <div className="w-px h-4 bg-white/20 mx-0.5" />
                    <button
                        onClick={() => {
                            if (autoConfirm) {
                                setAutoConfirm(false)
                                return
                            }
                            const ok = window.confirm(
                                "เปิด 'ยืนยันอัตโนมัติ' แล้ว Agent จะอนุมัติการกระทำที่รุนแรงทั้งหมด\n" +
                                "(ลบไฟล์, อนุมัติเอกสาร, แก้ไข field, ส่ง API) โดยอัตโนมัติ\n" +
                                "ใน session นี้โดยไม่ถามซ้ำอีก\n\n" +
                                "คุณแน่ใจหรือไม่?"
                            )
                            if (ok) setAutoConfirm(true)
                        }}
                        className={`text-xs px-2 py-1 rounded flex items-center gap-1 transition-colors ${
                            autoConfirm
                                ? "bg-amber-500/30 text-amber-200 ring-1 ring-amber-400/50"
                                : "text-white/70 hover:text-white"
                        }`}
                        title={autoConfirm
                            ? "⚠️ ยืนยันอัตโนมัติเปิดอยู่ — Agent จะอนุมัติการกระทำที่รุนแรงทั้งหมดโดยไม่ถาม คลิกเพื่อปิด"
                            : "เปิดยืนยันอัตโนมัติ — Agent จะอนุมัติทุก destructive action ใน session นี้โดยไม่ถามซ้ำ"
                        }
                    >
                        {autoConfirm ? <ShieldAlert className="h-3.5 w-3.5" /> : <ShieldCheck className="h-3.5 w-3.5" />}
                        {autoConfirm ? "ยืนยันอัตโนมัติ: เปิด" : "ยืนยันอัตโนมัติ"}
                    </button>
                    <button onClick={toggleMemories} className="text-white/70 hover:text-white p-1 rounded" title="Memories">
                        <Brain className="h-4 w-4" />
                    </button>
                    <button onClick={() => setShowSkillLibrary(v => !v)} className="text-white/70 hover:text-white p-1 rounded" title="Skill Library">
                        <Library className="h-4 w-4" />
                    </button>
                    <button onClick={() => setShowConvList(v => !v)} className="text-white/70 hover:text-white p-1 rounded" title="รายการสนทนา">
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
                    <button onClick={createConversation} className="w-full flex items-center gap-2 text-sm text-softnix-blue hover:text-softnix-deep font-medium">
                        <Plus className="h-4 w-4" /> New conversation
                    </button>
                    {conversations.map(conv => (
                        <div key={conv.id} className={`flex items-center gap-2 p-2 rounded cursor-pointer text-sm ${activeConversation === conv.id ? "bg-[#EBF4FB] border border-[#AED6F1]" : "hover:bg-off-white"}`} onClick={() => {
                            setActiveConversation(conv.id)
                            setShowConvList(false)
                            setAutoConfirm(false)
                            setAutoConfirmedIds(new Set())
                            setPendingAction(null)
                        }}>
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
                        <button onClick={createConversation} className="mt-4 px-4 py-2 bg-softnix-blue text-white text-sm rounded-lg hover:bg-softnix-deep">
                            <Plus className="h-4 w-4 inline mr-1" />New Conversation
                        </button>
                    </div>
                )}
                {messages.length === 0 && !streaming && (
                    <div className="flex-1 min-h-[50vh] flex flex-col items-center justify-center px-4 text-center">
                        <div className="h-12 w-12 rounded-full bg-gradient-to-br from-softnix-blue to-softnix-deep flex items-center justify-center mb-3">
                            <Bot className="h-6 w-6 text-white" />
                        </div>
                        <h3 className="text-sm font-semibold text-charcoal mb-1">สวัสดีครับ ผมพร้อมช่วยคุณ</h3>
                        <p className="text-xs text-mute-gray mb-4">เลือกคำสั่งด้านล่าง หรือพิมพ์คำถามของคุณได้เลย</p>
                        <div className="w-full max-w-md space-y-2">
                            <button
                                onClick={() => { setInputValue("ช่วยสรุปเอกสาร"); document.getElementById("agent-input")?.focus() }}
                                className="w-full flex items-center gap-3 rounded-lg border border-hairline bg-white px-3 py-2.5 text-left text-xs hover:border-softnix-blue hover:bg-blue-50/30 transition-colors"
                            >
                                <FileText className="h-4 w-4 text-softnix-blue flex-shrink-0" />
                                <div>
                                    <div className="font-medium text-charcoal">ช่วยสรุปเอกสาร</div>
                                    <div className="text-mute-gray text-[11px]">สรุปเนื้อหาและจุดสำคัญของเอกสาร</div>
                                </div>
                            </button>
                            <button
                                onClick={() => { setInputValue("ช่วยเปรียบเทียบ"); document.getElementById("agent-input")?.focus() }}
                                className="w-full flex items-center gap-3 rounded-lg border border-hairline bg-white px-3 py-2.5 text-left text-xs hover:border-softnix-blue hover:bg-blue-50/30 transition-colors"
                            >
                                <GitCompare className="h-4 w-4 text-softnix-blue flex-shrink-0" />
                                <div>
                                    <div className="font-medium text-charcoal">ช่วยเปรียบเทียบ</div>
                                    <div className="text-mute-gray text-[11px]">เปรียบเทียบข้อมูลระหว่างเอกสารใน job</div>
                                </div>
                            </button>
                            <button
                                onClick={() => { setInputValue("ช่วยตรวจสอบความถูกต้องตามเงื่อนไข"); document.getElementById("agent-input")?.focus() }}
                                className="w-full flex items-center gap-3 rounded-lg border border-hairline bg-white px-3 py-2.5 text-left text-xs hover:border-softnix-blue hover:bg-blue-50/30 transition-colors"
                            >
                                <CheckCircle2 className="h-4 w-4 text-softnix-blue flex-shrink-0" />
                                <div>
                                    <div className="font-medium text-charcoal">ช่วยตรวจสอบความถูกต้องตามเงื่อนไข</div>
                                    <div className="text-mute-gray text-[11px]">ตรวจสอบข้อมูลเอกสารว่าถูกต้องตามเงื่อนไขที่กำหนด</div>
                                </div>
                            </button>
                        </div>
                    </div>
                )}
                {messages.map(msg => renderPersistedMessage(msg))}
                {streaming && planSteps.length > 0 && renderPlanCard(planSteps, reflection, true, "live-plan")}
                {events.filter(e => e.type === "tool_call").map(evt => (
                    <ToolCallCard
                        key={evt.id}
                        call={evt}
                        result={toolResultsMap[evt.id!]}
                        conversationId={activeConversation || undefined}
                        autoConfirmed={evt.id ? autoConfirmedIds.has(evt.id) : false}
                    />
                ))}
                {streaming && !streamText && events.filter(e => e.type === "tool_call").length === 0 && (
                    <ThinkingIndicator iteration={thinkingIteration} />
                )}
                {streaming && streamText && (
                    <AgentMessage role="assistant" content={streamText} isStreaming conversationId={activeConversation || undefined} />
                )}
                {error && (
                    <div className="mx-3 flex items-start gap-2 p-3 rounded-lg bg-red-50 border border-red-200">
                        <AlertTriangle className="h-4 w-4 text-red-500 mt-0.5 flex-shrink-0" />
                        <p className="text-xs text-red-700">{error}</p>
                    </div>
                )}
                {doneStatus && !doneStatus.success && (
                    <div className="mx-3 mb-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900">
                        <div className="flex items-center gap-2 font-medium">
                            <AlertTriangle className="h-4 w-4" />
                            การทำงานยังไม่สมบูรณ์ — ตรวจพบปัญหา:
                        </div>
                        {doneStatus.failedSteps.length > 0 && (
                            <ul className="mt-1 list-disc pl-6 space-y-0.5">
                                {doneStatus.failedSteps.map((s, i) => <li key={i}>{s}</li>)}
                            </ul>
                        )}
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
            {activeConversation && slashCommand && (
                <div className="border-t border-hairline bg-white px-3 pt-3">
                    <div className="rounded-lg border border-softnix-blue/20 bg-[#F7FBFE] shadow-sm overflow-hidden">
                        <div className="flex items-center gap-2 px-3 py-2 text-xs font-medium text-softnix-deep border-b border-softnix-blue/10">
                            <Sparkles className="h-3.5 w-3.5" /> เลือก Skill
                        </div>
                        {filteredSkills.length > 0 ? filteredSkills.map(skill => (
                            <button
                                key={skill.id}
                                type="button"
                                onClick={() => selectSkill(skill)}
                                className="w-full px-3 py-2 text-left hover:bg-white border-b border-softnix-blue/10 last:border-b-0"
                            >
                                <div className="flex items-center justify-between gap-2">
                                    <code className="text-xs font-semibold text-softnix-deep truncate">/{skill.name}</code>
                                    <span className="text-[10px] uppercase tracking-wide text-slate-gray">{skill.scope}</span>
                                </div>
                                <p className="mt-0.5 line-clamp-1 text-[11px] text-slate-gray">{skill.description}</p>
                            </button>
                        )) : (
                            <div className="px-3 py-2 text-xs text-slate-gray">ไม่พบ skill ที่ตรงกับคำค้น</div>
                        )}
                    </div>
                </div>
            )}
            {activeConversation && (
                <ChatInput
                    value={inputValue}
                    onChange={setInputValue}
                    onSend={sendMessage}
                    disabled={!activeConversation}
                    streaming={streaming}
                    tips={<p className="text-[11px] text-slate-gray">Tips: พิมพ์ <code className="rounded bg-slate-100 px-1 font-mono">/</code> เพื่อเลือก Skill ที่ต้องการใช้งาน</p>}
                />
            )}
        </div>
    )
}
