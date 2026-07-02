"use client"

import { useState, useEffect, useRef, useCallback, type KeyboardEvent } from "react"
import { X, Plus, Trash2, Bot, ChevronDown, AlertTriangle, Loader2, Brain, Library, Sparkles, ListChecks, Check, Circle, ShieldCheck, ShieldAlert, FileText, GitCompare, CheckCircle2, Send } from "lucide-react"
import { getApiBaseUrl } from "@/lib/api"
import AgentMessage from "./AgentMessage"
import AgentToolCalls from "./AgentToolCalls"
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
    const [showStartSkillPicker, setShowStartSkillPicker] = useState(false)
    const [memoryScope, setMemoryScope] = useState<"user" | "job">("user")
    const [memories, setMemories] = useState<AgentMemory[]>([])
    const [loadingMemories, setLoadingMemories] = useState(false)
    const [skills, setSkills] = useState<AgentSkill[]>([])
    const messagesEndRef = useRef<HTMLDivElement>(null)
    const startInputRef = useRef<HTMLTextAreaElement>(null)
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

    useEffect(() => {
        if (!streaming || !activeConversation) return
        const interval = window.setInterval(() => {
            reloadActiveMessages()
        }, 1200)
        return () => window.clearInterval(interval)
    }, [activeConversation, reloadActiveMessages, streaming])

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

    const enableAutoConfirm = () => {
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
    }

    const createConversation = async (): Promise<Conversation | null> => {
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
                return conv
            } else {
                const data = await res.json().catch(() => null)
                setError(data?.detail || `Failed to create conversation (${res.status})`)
            }
        } catch { setError("Failed to create conversation") }
        return null
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
        setShowStartSkillPicker(false)
        window.setTimeout(() => startInputRef.current?.focus(), 0)
    }

    const sendMessage = async (override?: string) => {
        const rawInput = override ?? inputValue
        if (!rawInput.trim() || streaming) return
        setShowStartSkillPicker(false)
        let conversationId = activeConversation
        if (!conversationId) {
            const conv = await createConversation()
            if (!conv) return
            conversationId = conv.id
        }
        const userMsg = resolveOutgoingMessage(rawInput)
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
            const res = await fetch(`${apiBase}/agent/conversations/${conversationId}/messages`, {
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
            const calls = msg.tool_calls.map((toolCall: any, index: number) => ({
                    id: toolCall.id || `${msg.id}-${index}`,
                    name: toolCall.function?.name || toolCall.name,
                    arguments: parseToolArguments(toolCall.function?.arguments || toolCall.arguments),
            }))
            return (
                <AgentToolCalls
                    key={msg.id}
                    calls={calls}
                    results={persistedToolResultsMap}
                    conversationId={activeConversation || undefined}
                />
            )
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

    const showStartComposer = !loading && messages.length === 0 && !streaming
    const suggestionPrompts = [
        {
            icon: FileText,
            label: "สรุปเอกสารใน job",
            description: "ประเด็นสำคัญและสถานะ",
            prompt: "ช่วยสรุปเอกสารทั้งหมดใน job นี้ พร้อมระบุเอกสารที่ review แล้วและประเด็นสำคัญที่ควรตรวจต่อ",
        },
        {
            icon: GitCompare,
            label: "เปรียบเทียบข้อมูล",
            description: "หาความไม่สอดคล้อง",
            prompt: "ช่วยเปรียบเทียบข้อมูลระหว่างเอกสารใน job นี้ และสรุปความแตกต่างหรือข้อมูลที่ไม่สอดคล้องกัน",
        },
        {
            icon: CheckCircle2,
            label: "ตรวจความถูกต้องก่อนส่ง",
            description: "เช็ก field ก่อนส่ง",
            prompt: "ช่วยตรวจสอบความถูกต้องของ field ที่ดึงจากเอกสารใน job นี้ก่อนส่งไป integration พร้อมแนะนำรายการที่ควรแก้ไข",
        },
        {
            icon: Sparkles,
            label: "เตรียม workflow/API",
            description: "เตรียมข้อมูลปลายทาง",
            prompt: "ช่วยวางแผนส่งข้อมูลจาก job นี้ไป integration โดยตรวจความพร้อมก่อน และระบุ action ที่ต้องทำทีละขั้น",
        },
    ]

    const applySuggestion = (prompt: string) => {
        setInputValue(prompt)
        setShowStartSkillPicker(false)
        window.setTimeout(() => startInputRef.current?.focus(), 0)
    }

    const handleStartKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault()
            sendMessage()
        }
    }

    const startSkillPickerVisible = showStartComposer && (showStartSkillPicker || slashCommand)
    const startSkillOptions = slashCommand ? filteredSkills : skills.slice(0, 8)

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
                        onClick={enableAutoConfirm}
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
                {showStartComposer && (
                    <div className="flex min-h-[58vh] items-center justify-center px-5 py-8">
                        <div className="w-full max-w-3xl">
                            <div className="mb-7">
                                <div className="mb-3 flex items-center justify-center gap-2 text-[0.9375rem] font-semibold text-softnix-deep">
                                    <Sparkles className="h-4 w-4" />
                                    Softnix Agent DOC
                                </div>
                                <h3 className="text-center text-[2rem] font-semibold leading-tight text-ink-navy">
                                    วันนี้ให้ Agent ช่วยจัดการอะไรดี?
                                </h3>
                                <p className="mx-auto mt-3 max-w-xl text-center text-[0.9375rem] leading-6 text-slate-gray">
                                    พิมพ์ภารกิจหรือเลือกตัวอย่างด้านล่าง
                                </p>
                            </div>

                            <div className="rounded-[24px] border border-hairline bg-white shadow-[0_18px_45px_rgba(13,27,42,0.10)]">
                                <textarea
                                    ref={startInputRef}
                                    value={inputValue}
                                    onChange={(e) => {
                                        const next = e.target.value
                                        setInputValue(next)
                                        if (next.trimStart().startsWith("/")) setShowStartSkillPicker(true)
                                    }}
                                    onKeyDown={handleStartKeyDown}
                                    placeholder="เช่น ตรวจใบเสร็จที่ review แล้ว และเตรียมข้อมูลสำหรับส่ง integration"
                                    disabled={streaming}
                                    maxLength={10000}
                                    rows={5}
                                    className="min-h-[148px] w-full resize-none rounded-t-[24px] px-6 py-5 text-[1rem] leading-7 text-ink-navy placeholder:text-slate-400 focus:outline-none disabled:opacity-50"
                                />
                                {autoConfirm && (
                                    <div className="mx-4 mb-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-left">
                                        <div className="flex items-start gap-2">
                                            <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
                                            <p className="text-[0.8125rem] leading-5 text-amber-800">
                                                Act เปิดอยู่: Agent จะอนุมัติการลบไฟล์ อนุมัติเอกสาร แก้ไข field และส่ง API ใน session นี้โดยไม่ถามซ้ำ
                                            </p>
                                        </div>
                                    </div>
                                )}
                                <div className="flex flex-wrap items-center gap-2 border-t border-hairline px-4 py-3">
                                    <button
                                        type="button"
                                        onClick={() => {
                                            setShowStartSkillPicker(prev => !prev)
                                            window.setTimeout(() => startInputRef.current?.focus(), 0)
                                        }}
                                        className="inline-flex h-9 items-center gap-2 rounded-full bg-off-white px-3 text-[0.875rem] font-semibold text-charcoal transition-colors hover:bg-[#EBF4FB] hover:text-softnix-deep"
                                        title="เลือก Skill"
                                    >
                                        <Sparkles className="h-4 w-4" />
                                        Skill
                                    </button>
                                    <button
                                        type="button"
                                        onClick={() => setShowSkillLibrary(true)}
                                        className="flex h-9 w-9 items-center justify-center rounded-full text-charcoal transition-colors hover:bg-off-white"
                                        title="Skill Library"
                                    >
                                        <Library className="h-4 w-4" />
                                    </button>
                                    <button
                                        type="button"
                                        onClick={enableAutoConfirm}
                                        className={`inline-flex h-9 items-center gap-2 rounded-full px-3 text-[0.875rem] font-semibold transition-colors ${
                                            autoConfirm
                                                ? "bg-amber-100 text-amber-800 ring-1 ring-amber-300"
                                                : "bg-off-white text-charcoal hover:bg-[#EBF4FB] hover:text-softnix-deep"
                                        }`}
                                    >
                                        {autoConfirm ? <ShieldAlert className="h-4 w-4" /> : <ShieldCheck className="h-4 w-4" />}
                                        Act
                                    </button>
                                    <button
                                        type="button"
                                        onClick={() => sendMessage()}
                                        disabled={!inputValue.trim() || streaming}
                                        className="ml-auto flex h-11 w-11 items-center justify-center rounded-full bg-softnix-blue text-white shadow-sm transition-colors hover:bg-softnix-deep disabled:cursor-not-allowed disabled:opacity-40"
                                        title="ส่งข้อความ"
                                    >
                                        {streaming ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                                    </button>
                                </div>
                                {startSkillPickerVisible && (
                                    <div className="border-t border-hairline bg-[#F7FBFE] px-4 py-3">
                                        <div className="mb-2 flex items-center justify-between gap-3">
                                            <div className="flex items-center gap-2 text-[0.8125rem] font-semibold text-softnix-deep">
                                                <Sparkles className="h-3.5 w-3.5" />
                                                เลือก Skill
                                            </div>
                                            <button
                                                type="button"
                                                onClick={() => setShowStartSkillPicker(false)}
                                                className="text-[0.75rem] font-medium text-slate-gray hover:text-ink-navy"
                                            >
                                                ปิด
                                            </button>
                                        </div>
                                        {skills.length === 0 ? (
                                            <div className="rounded-xl border border-dashed border-hairline bg-white px-4 py-4 text-center">
                                                <p className="text-[0.8125rem] font-semibold text-charcoal">ยังไม่มี Skill ให้เลือก</p>
                                                <button
                                                    type="button"
                                                    onClick={() => setShowSkillLibrary(true)}
                                                    className="mt-2 text-[0.8125rem] font-semibold text-softnix-blue hover:text-softnix-deep"
                                                >
                                                    เปิด Skill Library
                                                </button>
                                            </div>
                                        ) : startSkillOptions.length > 0 ? (
                                            <div className="max-h-56 overflow-y-auto rounded-xl border border-softnix-blue/20 bg-white shadow-sm">
                                                {startSkillOptions.map(skill => (
                                                    <button
                                                        key={skill.id}
                                                        type="button"
                                                        onClick={() => selectSkill(skill)}
                                                        className="w-full border-b border-softnix-blue/10 px-3 py-2.5 text-left transition-colors last:border-b-0 hover:bg-[#F0F8FD]"
                                                    >
                                                        <div className="flex items-center justify-between gap-2">
                                                            <code className="truncate text-[0.8125rem] font-semibold text-softnix-deep">/{skill.name}</code>
                                                            <span className="shrink-0 rounded-full bg-slate-100 px-2 py-0.5 text-[0.625rem] font-bold uppercase tracking-wide text-slate-gray">{skill.scope}</span>
                                                        </div>
                                                        {skill.description && (
                                                            <p className="mt-1 line-clamp-1 text-[0.75rem] leading-5 text-slate-gray">{skill.description}</p>
                                                        )}
                                                    </button>
                                                ))}
                                            </div>
                                        ) : (
                                            <div className="rounded-xl border border-hairline bg-white px-4 py-3 text-[0.8125rem] text-slate-gray">
                                                ไม่พบ Skill ที่ตรงกับคำค้น
                                            </div>
                                        )}
                                    </div>
                                )}
                            </div>

                            <div className="mt-7 grid grid-cols-1 gap-2 sm:grid-cols-2">
                                {suggestionPrompts.map(item => {
                                    const Icon = item.icon
                                    return (
                                        <button
                                            key={item.label}
                                            type="button"
                                            onClick={() => applySuggestion(item.prompt)}
                                            className="group flex items-start gap-3 rounded-xl px-3 py-3 text-left transition-colors hover:bg-white hover:shadow-sm"
                                        >
                                            <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[#EBF4FB] text-softnix-blue transition-colors group-hover:bg-softnix-blue group-hover:text-white">
                                                <Icon className="h-4 w-4" />
                                            </span>
                                            <span className="min-w-0">
                                                <span className="block text-[0.9375rem] font-semibold leading-5 text-ink-navy">{item.label}</span>
                                                <span className="mt-0.5 block text-[0.8125rem] leading-5 text-slate-gray">{item.description}</span>
                                            </span>
                                        </button>
                                    )
                                })}
                            </div>
                        </div>
                    </div>
                )}
                {messages.map(msg => renderPersistedMessage(msg))}
                {streaming && planSteps.length > 0 && renderPlanCard(planSteps, reflection, true, "live-plan")}
                {events.filter(e => e.type === "tool_call").length > 0 && (
                    <AgentToolCalls
                        calls={events.filter(e => e.type === "tool_call")}
                        results={toolResultsMap}
                        conversationId={activeConversation || undefined}
                        autoConfirmedIds={autoConfirmedIds}
                    />
                )}
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
            {activeConversation && !showStartComposer && slashCommand && (
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
            {activeConversation && !showStartComposer && (
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
