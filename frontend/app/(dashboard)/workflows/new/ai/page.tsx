"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import { ReactFlow, Background, Controls, ReactFlowProvider } from "@xyflow/react"
import "@xyflow/react/dist/style.css"
import { ArrowLeft, Sparkles, Wrench, CheckCircle2, KeyRound, Loader2, X } from "lucide-react"

import { getApiBaseUrl } from "@/lib/api"
import { createWorkflowConversation, resolveCredential } from "@/lib/workflows-api"
import { createIntegration } from "@/lib/integrations-api"
import { createAIProvider } from "@/lib/ai-settings-api"
import ChatInput from "@/components/chat/ChatInput"
import ConfirmationDialog from "@/components/agent/ConfirmationDialog"

// ── Types ────────────────────────────────────────────────────────────
interface AgentEvent {
    type: string
    id?: string
    name?: string
    arguments?: any
    result?: any
    text?: string
    pending_action_id?: string
    tool_call_id?: string
    tool_name?: string
    description?: string
    message?: string
}

type TranscriptItem =
    | { kind: "msg"; id: string; role: "user" | "assistant"; content: string }
    | { kind: "tool"; id: string; name: string; args: any; result?: any }

interface PendingAction { pending_action_id: string; tool_name: string; description: string; arguments: any }
interface CredentialRequest { pending_action_id: string; credential_kind: string; fields: string[]; purpose: string }

const SECRET_FIELDS = new Set(["api_key", "private_key", "client_secret", "authHeader", "apiKey"])

// ── Live preview (read-only React Flow) ──────────────────────────────
function WorkflowPreview({ definition }: { definition: any }) {
    const { nodes, edges } = useMemo(() => {
        const defNodes: any[] = definition?.nodes || []
        const defEdges: any[] = definition?.edges || []
        const nodes = defNodes.map((n, i) => ({
            id: n.id,
            position: n.position && typeof n.position.x === "number" ? n.position : { x: 120, y: 80 + i * 90 },
            data: { label: `${(n.data?.label || n.type || "node")}` },
            style: {
                border: "1px solid #2786C2", borderRadius: 10, padding: "8px 12px",
                background: "#fff", fontSize: 12, color: "#0D1B2A", minWidth: 150,
            },
        }))
        const edges = defEdges.map((e, i) => ({
            id: e.id || `e${i}`, source: e.source, target: e.target,
            label: e.sourceHandle || undefined, animated: true,
        }))
        return { nodes, edges }
    }, [definition])

    if (!definition?.nodes?.length) {
        return (
            <div className="h-full flex flex-col items-center justify-center text-[#9AA8BC] text-sm gap-2">
                <Sparkles className="h-8 w-8 text-[#CBD5E1]" />
                <p>พรีวิว workflow จะปรากฏที่นี่เมื่อ AI เริ่มออกแบบ</p>
            </div>
        )
    }
    return (
        <ReactFlow nodes={nodes} edges={edges} fitView
            nodesDraggable={false} nodesConnectable={false} elementsSelectable={false}
            proOptions={{ hideAttribution: true }}>
            <Background />
            <Controls showInteractive={false} />
        </ReactFlow>
    )
}

// ── Credential card ──────────────────────────────────────────────────
function CredentialCard({ req, onSaved, onCancel }: {
    req: CredentialRequest
    onSaved: (info: { idKey: "integration_id" | "ai_provider_id"; id: string; name: string }) => void
    onCancel: () => void
}) {
    const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
    const [values, setValues] = useState<Record<string, string>>({})
    const [saving, setSaving] = useState(false)
    const [err, setErr] = useState<string | null>(null)

    const set = (k: string, v: string) => setValues((prev) => ({ ...prev, [k]: v }))

    const save = async () => {
        if (!token) return
        setSaving(true); setErr(null)
        try {
            const name = values["display_name"] || values["name"] || `${req.credential_kind}-credential`
            if (req.credential_kind === "llm") {
                const p = await createAIProvider(token, {
                    name: (name || "ai-provider").toLowerCase().replace(/\s+/g, "_"),
                    display_name: name,
                    api_url: values["api_url"] || "",
                    api_key: values["api_key"] || "",
                    model: values["model"] || undefined,
                })
                await resolveCredential(token, req.pending_action_id, { ai_provider_id: p.id, name })
                onSaved({ idKey: "ai_provider_id", id: p.id, name })
            } else {
                const config: Record<string, any> = {}
                for (const f of req.fields) {
                    if (f === "name") continue
                    if (values[f]) config[f] = values[f]
                }
                const integ = await createIntegration(token, {
                    name,
                    type: req.credential_kind as any,
                    config,
                })
                await resolveCredential(token, req.pending_action_id, { integration_id: integ.id, name })
                onSaved({ idKey: "integration_id", id: integ.id, name })
            }
        } catch (e: any) {
            setErr(e.message || "บันทึกไม่สำเร็จ")
            setSaving(false)
        }
    }

    return (
        <div className="mx-3 mb-3 rounded-xl border-2 border-[#2786C2] bg-[#EBF4FB] p-4">
            <div className="flex items-start gap-2 mb-3">
                <KeyRound className="h-5 w-5 text-[#2786C2] flex-shrink-0 mt-0.5" />
                <div>
                    <p className="text-sm font-semibold text-[#0D1B2A]">กรอกข้อมูล credential ({req.credential_kind})</p>
                    <p className="text-xs text-[#5B6B7E] mt-0.5">{req.purpose}</p>
                    <p className="text-[11px] text-[#5B6B7E] mt-1">คีย์จะถูกบันทึกลงระบบโดยตรง ไม่ผ่านช่องแชท</p>
                </div>
            </div>
            <div className="space-y-2 mb-3">
                {req.fields.map((f) => (
                    <div key={f}>
                        <label className="block text-xs text-[#0D1B2A] mb-0.5">{f}</label>
                        <input
                            type={SECRET_FIELDS.has(f) ? "password" : "text"}
                            value={values[f] || ""}
                            onChange={(e) => set(f, e.target.value)}
                            className="w-full border border-[#CBD5E1] rounded-lg px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-[#2786C2]/30"
                        />
                    </div>
                ))}
            </div>
            {err && <p className="text-xs text-red-600 mb-2">{err}</p>}
            <div className="flex gap-2">
                <button onClick={save} disabled={saving}
                    className="flex-1 px-3 py-1.5 rounded-lg bg-[#2786C2] text-white text-sm hover:bg-[#1F6FA3] disabled:opacity-50 flex items-center justify-center gap-1">
                    {saving && <Loader2 className="h-3.5 w-3.5 animate-spin" />} บันทึกและใช้งาน
                </button>
                <button onClick={onCancel} disabled={saving}
                    className="px-3 py-1.5 rounded-lg border border-[#CBD5E1] text-[#778DA9] text-sm hover:bg-white">
                    ยกเลิก
                </button>
            </div>
        </div>
    )
}

// ── Main page ────────────────────────────────────────────────────────
function AiBuilderInner() {
    const router = useRouter()
    const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
    const apiBase = getApiBaseUrl()

    const [conversationId, setConversationId] = useState<string | null>(null)
    const [transcript, setTranscript] = useState<TranscriptItem[]>([])
    const [input, setInput] = useState("")
    const [streaming, setStreaming] = useState(false)
    const [streamText, setStreamText] = useState("")
    const [thinking, setThinking] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [pendingAction, setPendingAction] = useState<PendingAction | null>(null)
    const [credentialReq, setCredentialReq] = useState<CredentialRequest | null>(null)
    const [previewDef, setPreviewDef] = useState<any>(null)
    const [savedWorkflowId, setSavedWorkflowId] = useState<string | null>(null)
    const scrollRef = useRef<HTMLDivElement>(null)

    const headers = useCallback(() => ({
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
    }), [token])

    useEffect(() => {
        scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" })
    }, [transcript, streamText, thinking])

    const ensureConversation = useCallback(async (): Promise<string | null> => {
        if (conversationId) return conversationId
        if (!token) return null
        const conv = await createWorkflowConversation(token)
        setConversationId(conv.id)
        return conv.id
    }, [conversationId, token])

    const sendMessage = useCallback(async (text: string) => {
        if (!text.trim() || streaming) return
        const convId = await ensureConversation()
        if (!convId) { setError("ไม่พบ token"); return }

        setTranscript((prev) => [...prev, { kind: "msg", id: crypto.randomUUID(), role: "user", content: text }])
        setInput("")
        setStreaming(true); setStreamText(""); setError(null); setThinking(true)

        try {
            const res = await fetch(`${apiBase}/agent/conversations/${convId}/messages`, {
                method: "POST", headers: headers(), body: JSON.stringify({ content: text }),
            })
            if (!res.ok) {
                const data = await res.json().catch(() => null)
                setError(data?.detail || `Server error: ${res.status}`); setStreaming(false); setThinking(false)
                return
            }
            const reader = res.body!.getReader()
            const decoder = new TextDecoder()
            let buffer = ""
            let finalText = ""
            while (true) {
                const { done, value } = await reader.read()
                if (done) break
                buffer += decoder.decode(value, { stream: true })
                const lines = buffer.split("\n")
                buffer = lines.pop() || ""
                for (const line of lines) {
                    if (!line.startsWith("data: ")) continue
                    let evt: AgentEvent
                    try { evt = JSON.parse(line.slice(6)) } catch { continue }
                    switch (evt.type) {
                        case "thinking":
                            setThinking(true)
                            break
                        case "tool_call":
                            setTranscript((prev) => [...prev, { kind: "tool", id: evt.id || crypto.randomUUID(), name: evt.name || "", args: evt.arguments }])
                            break
                        case "tool_result": {
                            const result = evt.result
                            setTranscript((prev) => prev.map((it) =>
                                it.kind === "tool" && it.id === evt.id ? { ...it, result } : it))
                            if (evt.name === "propose_workflow" && result?.definition) {
                                setPreviewDef(result.definition)
                            }
                            if (evt.name === "save_workflow" && result?.ok && result?.workflow_id) {
                                setSavedWorkflowId(result.workflow_id)
                            }
                            if (result?.status === "awaiting_credential" && result?.pending_action_id) {
                                setCredentialReq({
                                    pending_action_id: result.pending_action_id,
                                    credential_kind: result.credential_kind || "llm",
                                    fields: result.fields || ["name", "api_key"],
                                    purpose: result.purpose || "",
                                })
                            }
                            break
                        }
                        case "confirmation_required":
                            setPendingAction(evt as unknown as PendingAction)
                            break
                        case "delta":
                            finalText += evt.text || ""
                            setStreamText(finalText)
                            break
                        case "done":
                            setStreaming(false); setThinking(false)
                            if (finalText) {
                                setTranscript((prev) => [...prev, { kind: "msg", id: crypto.randomUUID(), role: "assistant", content: finalText }])
                                setStreamText("")
                            }
                            break
                        case "error":
                            setError(evt.message || "Agent error"); setStreaming(false); setThinking(false)
                            break
                    }
                }
            }
            setStreaming(false); setThinking(false)
        } catch (e: any) {
            setError(e?.message || "การเชื่อมต่อขาดหาย")
            setStreaming(false); setThinking(false)
        }
    }, [streaming, ensureConversation, apiBase, headers])

    const confirmAction = async (approved: boolean) => {
        if (!pendingAction || !token) return
        await fetch(`${apiBase}/agent/confirm/${pendingAction.pending_action_id}`, {
            method: "POST", headers: headers(), body: JSON.stringify({ approved }),
        })
        setPendingAction(null)
    }

    const onCredentialSaved = (info: { idKey: string; id: string; name: string }) => {
        setCredentialReq(null)
        // Feed only the created id back to the agent — never the key.
        sendMessage(`ผู้ใช้สร้าง credential '${info.name}' แล้ว (${info.idKey}=${info.id}) ใช้ค่านี้กับโหนดที่ต้องใช้ได้เลย`)
    }

    return (
        <div className="flex flex-col h-[calc(100vh-4rem)]">
            <div className="flex items-center gap-3 px-4 py-3 border-b border-[#E2E8F0]">
                <button onClick={() => router.push("/workflows")} className="p-2 rounded-lg hover:bg-gray-50 text-[#778DA9]">
                    <ArrowLeft className="h-4 w-4" />
                </button>
                <Sparkles className="h-5 w-5 text-[#2786C2]" />
                <div>
                    <h1 className="text-base font-semibold text-[#0D1B2A]">สร้าง Workflow ด้วย AI</h1>
                    <p className="text-xs text-[#778DA9]">บอกเป้าหมาย แล้ว AI จะออกแบบและตรวจสอบให้ก่อนบันทึก</p>
                </div>
                {savedWorkflowId && (
                    <button onClick={() => router.push(`/workflows/${savedWorkflowId}`)}
                        className="ml-auto flex items-center gap-2 px-4 py-2 rounded-lg bg-emerald-600 text-white text-sm hover:bg-emerald-700">
                        <CheckCircle2 className="h-4 w-4" /> เปิดใน Builder
                    </button>
                )}
            </div>

            <div className="flex flex-1 min-h-0">
                {/* Chat */}
                <div className="flex flex-col w-[46%] min-w-[380px] border-r border-[#E2E8F0]">
                    <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-3">
                        {transcript.length === 0 && (
                            <div className="text-sm text-[#778DA9] bg-[#F8FAFC] rounded-xl p-4">
                                ลองพิมพ์เช่น: “ทุกเช้า 8 โมง ดึงเอกสารจาก Job ‘ใบเสร็จ’ ที่ตรวจแล้ว มาสรุปยอดรวมด้วย AI แล้วส่งผลเข้า Google Drive”
                            </div>
                        )}
                        {transcript.map((it) => it.kind === "msg" ? (
                            <div key={it.id} className={`flex ${it.role === "user" ? "justify-end" : "justify-start"}`}>
                                <div className={`max-w-[85%] rounded-2xl px-3.5 py-2 text-sm whitespace-pre-wrap ${it.role === "user" ? "bg-[#2786C2] text-white" : "bg-[#F1F5F9] text-[#0D1B2A]"}`}>
                                    {it.content}
                                </div>
                            </div>
                        ) : (
                            <div key={it.id} className="flex items-start gap-2 text-xs text-[#5B6B7E]">
                                <Wrench className="h-3.5 w-3.5 mt-0.5 text-[#2786C2] flex-shrink-0" />
                                <div className="min-w-0">
                                    <span className="font-medium text-[#0D1B2A]">{it.name}</span>
                                    {it.result?.error && <span className="text-red-600"> — {String(it.result.error)}</span>}
                                    {it.result?.ok === false && it.result?.issues && (
                                        <span className="text-amber-600"> — {it.result.issues.filter((x: any) => x.level === "error").length} ปัญหา</span>
                                    )}
                                </div>
                            </div>
                        ))}
                        {streamText && (
                            <div className="flex justify-start">
                                <div className="max-w-[85%] rounded-2xl px-3.5 py-2 text-sm whitespace-pre-wrap bg-[#F1F5F9] text-[#0D1B2A]">{streamText}</div>
                            </div>
                        )}
                        {thinking && !streamText && (
                            <div className="flex items-center gap-2 text-xs text-[#778DA9]"><Loader2 className="h-3.5 w-3.5 animate-spin" /> กำลังคิด…</div>
                        )}
                        {error && (
                            <div className="text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2 flex justify-between">
                                {error}<button onClick={() => setError(null)}><X className="h-4 w-4" /></button>
                            </div>
                        )}
                    </div>

                    {credentialReq && (
                        <CredentialCard req={credentialReq} onSaved={onCredentialSaved} onCancel={() => setCredentialReq(null)} />
                    )}
                    {pendingAction && (
                        <ConfirmationDialog action={pendingAction}
                            onConfirm={() => confirmAction(true)} onReject={() => confirmAction(false)} />
                    )}

                    <ChatInput value={input} onChange={setInput} onSend={() => sendMessage(input)}
                        streaming={streaming} tips={<span className="text-[11px] text-[#9AA8BC]">Enter เพื่อส่ง • Shift+Enter ขึ้นบรรทัดใหม่</span>} />
                </div>

                {/* Live preview */}
                <div className="flex-1 bg-[#F8FAFC]">
                    <WorkflowPreview definition={previewDef} />
                </div>
            </div>
        </div>
    )
}

export default function AiBuilderPage() {
    return (
        <ReactFlowProvider>
            <AiBuilderInner />
        </ReactFlowProvider>
    )
}
