"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useParams, useSearchParams } from "next/navigation"
import Link from "next/link"
import {
    ReactFlow,
    ReactFlowProvider,
    Background,
    Controls,
    MiniMap,
    addEdge,
    useNodesState,
    useEdgesState,
    useReactFlow,
    Handle,
    Position,
    MarkerType,
    type Node,
    type Edge,
    type Connection,
    type NodeProps,
} from "@xyflow/react"
import "@xyflow/react/dist/style.css"
import {
    ArrowLeft, Save, Play, Loader2, CalendarClock, Trash2, X,
    Zap, FileText, Sparkles, GitBranch, Shuffle, Code2, Globe, FileOutput, Briefcase,
    CheckCircle2, XCircle, CircleDashed, CircleDot, SkipForward, Activity, ChevronDown, ChevronRight,
    Download, Plus, FlaskConical, Cloud, CloudUpload, CloudDownload,
} from "lucide-react"
import {
    Workflow, WorkflowRun, NodeTypeDef, JobSummary,
    getWorkflow, updateWorkflow, runWorkflow, getRun, getWorkflowRuns, getNodeTypes, getJobs, testNode,
    downloadRunOutput,
} from "@/lib/workflows-api"
import { Integration, getActiveIntegrations } from "@/lib/integrations-api"

// ── Node visuals ─────────────────────────────────────────────────────
const CATEGORY_STYLE: Record<string, { icon: any; color: string; bg: string }> = {
    trigger:   { icon: Zap,        color: "#D97706", bg: "#FEF3C7" },
    data:      { icon: FileText,   color: "#2786C2", bg: "#EBF4FB" },
    ai:        { icon: Sparkles,   color: "#7C3AED", bg: "#F3E8FF" },
    logic:     { icon: GitBranch,  color: "#0D9488", bg: "#CCFBF1" },
    developer: { icon: Code2,      color: "#334155", bg: "#E2E8F0" },
    action:    { icon: Globe,      color: "#DC2626", bg: "#FEE2E2" },
    storage:   { icon: Cloud,      color: "#0EA5E9", bg: "#E0F2FE" },
}

const TYPE_ICON: Record<string, any> = {
    trigger_manual: Zap,
    trigger_schedule: CalendarClock,
    job_source: Briefcase,
    document_source: FileText,
    llm: Sparkles,
    condition: GitBranch,
    transform: Shuffle,
    python_code: Code2,
    http_request: Globe,
    write_output: FileOutput,
    gdrive_upload: CloudUpload,
    gdrive_import: CloudDownload,
    onedrive_upload: CloudUpload,
    onedrive_import: CloudDownload,
}

const STATUS_BORDER: Record<string, string> = {
    running: "#2786C2",
    succeeded: "#10B981",
    failed: "#EF4444",
    skipped: "#CBD5E1",
}

type WfNodeData = {
    nodeType: string
    label: string
    config: Record<string, any>
    category: string
    runStatus?: string
}

function WfNode({ data, selected }: NodeProps) {
    const d = data as WfNodeData
    const style = CATEGORY_STYLE[d.category] || CATEGORY_STYLE.action
    const Icon = TYPE_ICON[d.nodeType] || style.icon
    const isTrigger = d.category === "trigger"
    const isCondition = d.nodeType === "condition"
    const borderColor = d.runStatus ? STATUS_BORDER[d.runStatus] : selected ? "#2786C2" : "#E2E8F0"

    return (
        <div
            className={`rounded-xl bg-white shadow-sm px-3 py-2.5 min-w-[180px] max-w-[220px] ${d.runStatus === "running" ? "animate-pulse" : ""}`}
            style={{ border: `2px solid ${borderColor}` }}
        >
            {!isTrigger && <Handle type="target" position={Position.Left} className="!w-2.5 !h-2.5 !bg-[#94A3B8]" />}
            <div className="flex items-center gap-2">
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg" style={{ background: style.bg }}>
                    <Icon className="h-4 w-4" style={{ color: style.color }} />
                </span>
                <div className="min-w-0">
                    <div className="text-xs font-semibold text-[#0D1B2A] truncate">{d.label}</div>
                    <div className="text-[10px] text-[#94A3B8]">{d.nodeType}</div>
                </div>
            </div>
            {isCondition ? (
                <>
                    <Handle id="true" type="source" position={Position.Right} style={{ top: "35%" }} className="!w-2.5 !h-2.5 !bg-emerald-500" />
                    <Handle id="false" type="source" position={Position.Right} style={{ top: "75%" }} className="!w-2.5 !h-2.5 !bg-red-400" />
                    <div className="absolute right-1.5 text-[9px] text-emerald-600 font-semibold" style={{ top: "calc(35% - 7px)" }}>T</div>
                    <div className="absolute right-1.5 text-[9px] text-red-500 font-semibold" style={{ top: "calc(75% - 7px)" }}>F</div>
                </>
            ) : (
                <Handle type="source" position={Position.Right} className="!w-2.5 !h-2.5 !bg-[#2786C2]" />
            )}
        </div>
    )
}

const nodeTypes = { wf: WfNode }

const TRIGGER_TYPE_LABEL: Record<string, string> = {
    manual: "manual",
    schedule: "schedule",
    node_test: "ทดสอบโหนด",
}

// ── Helpers: backend definition ⇄ React Flow ─────────────────────────
const categoryOf = (defs: NodeTypeDef[], type: string) =>
    defs.find((d) => d.type === type)?.category || "action"

const toFlowNodes = (wf: Workflow, defs: NodeTypeDef[]): Node[] =>
    (wf.definition?.nodes || []).map((n) => ({
        id: n.id,
        type: "wf",
        position: n.position || { x: 0, y: 0 },
        data: {
            nodeType: n.type,
            label: n.data?.label || n.type,
            config: n.data?.config || {},
            category: categoryOf(defs, n.type),
        },
    }))

const toFlowEdges = (wf: Workflow): Edge[] =>
    (wf.definition?.edges || []).map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        sourceHandle: e.sourceHandle || undefined,
        targetHandle: e.targetHandle || undefined,
        label: e.sourceHandle === "true" ? "True" : e.sourceHandle === "false" ? "False" : undefined,
        markerEnd: { type: MarkerType.ArrowClosed },
        style: { strokeWidth: 1.5 },
    }))

const toDefinition = (nodes: Node[], edges: Edge[]) => ({
    nodes: nodes.map((n) => ({
        id: n.id,
        type: (n.data as WfNodeData).nodeType,
        position: { x: n.position.x, y: n.position.y },
        data: { label: (n.data as WfNodeData).label, config: (n.data as WfNodeData).config },
    })),
    edges: edges.map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        sourceHandle: e.sourceHandle || null,
        targetHandle: e.targetHandle || null,
    })),
})

// ── Run activity helpers ─────────────────────────────────────────────
const RUN_STATUS_ICON: Record<string, any> = {
    pending: CircleDashed,
    running: CircleDot,
    succeeded: CheckCircle2,
    failed: XCircle,
    skipped: SkipForward,
}
const RUN_STATUS_COLOR: Record<string, string> = {
    pending: "text-gray-400",
    running: "text-[#2786C2]",
    succeeded: "text-emerald-500",
    failed: "text-red-500",
    skipped: "text-gray-400",
}

function NodeRunRow({ nr, runId }: { nr: WorkflowRun["node_runs"][0]; runId: string }) {
    const [open, setOpen] = useState(false)
    const [downloading, setDownloading] = useState(false)
    const [downloadError, setDownloadError] = useState<string | null>(null)
    const Icon = RUN_STATUS_ICON[nr.status] || CircleDashed
    const outputFile = nr.node_type === "write_output" && nr.output?.filename ? nr.output.filename : null

    const handleDownload = async () => {
        if (!outputFile) return
        const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
        if (!token) { setDownloadError("กรุณาเข้าสู่ระบบใหม่"); return }
        try {
            setDownloading(true)
            setDownloadError(null)
            await downloadRunOutput(token, runId, outputFile)
        } catch (e: any) {
            setDownloadError(e.message || "ดาวน์โหลดไม่สำเร็จ")
        } finally {
            setDownloading(false)
        }
    }

    return (
        <div className="border border-[#E2E8F0] rounded-lg">
            <button className="w-full flex items-center gap-2 px-3 py-2 text-left" onClick={() => setOpen(!open)}>
                {open ? <ChevronDown className="h-3.5 w-3.5 text-[#94A3B8]" /> : <ChevronRight className="h-3.5 w-3.5 text-[#94A3B8]" />}
                <Icon className={`h-4 w-4 ${RUN_STATUS_COLOR[nr.status]} ${nr.status === "running" ? "animate-pulse" : ""}`} />
                <span className="text-xs font-medium text-[#0D1B2A] flex-1 truncate">{nr.node_label || nr.node_id}</span>
                <span className="text-[10px] text-[#94A3B8]">{nr.status}</span>
            </button>
            {open && (
                <div className="px-3 pb-3 space-y-2">
                    {nr.logs && (
                        <pre className="text-[10px] bg-[#0D1B2A] text-emerald-200 rounded-lg p-2 overflow-auto max-h-32 whitespace-pre-wrap">{nr.logs}</pre>
                    )}
                    {nr.error && <pre className="text-[10px] bg-red-50 text-red-600 rounded-lg p-2 overflow-auto max-h-32 whitespace-pre-wrap">{nr.error}</pre>}
                    {nr.output != null && (
                        <pre className="text-[10px] bg-[#F8F9FA] text-[#334155] rounded-lg p-2 overflow-auto max-h-40 whitespace-pre-wrap">
                            {JSON.stringify(nr.output, null, 2)}
                        </pre>
                    )}
                    {outputFile && (
                        <div>
                            <button
                                onClick={handleDownload}
                                disabled={downloading}
                                className="inline-flex items-center gap-1 text-xs text-[#2786C2] hover:underline disabled:opacity-50"
                            >
                                {downloading ? <Loader2 className="h-3 w-3 animate-spin" /> : <Download className="h-3 w-3" />}
                                ดาวน์โหลด {outputFile}
                            </button>
                            {downloadError && <p className="text-[10px] text-red-600 mt-1">{downloadError}</p>}
                        </div>
                    )}
                </div>
            )}
        </div>
    )
}

// ── Variable picker (แทรกข้อมูลจากโหนดก่อนหน้า) ──────────────────────
type UpstreamField = { name: string; label: string }
type UpstreamNode = { id: string; label: string; type: string; fields: UpstreamField[] }

/** หา id ของโหนดต้นทางทั้งหมด (ancestors) ของ targetId ด้วย reverse-BFS บน edges */
function getAncestors(targetId: string, edges: Edge[]): string[] {
    const parents: Record<string, string[]> = {}
    edges.forEach((e) => { (parents[e.target] ||= []).push(e.source) })
    const seen = new Set<string>()
    const queue = [...(parents[targetId] || [])]
    while (queue.length) {
        const id = queue.shift()!
        if (seen.has(id)) continue
        seen.add(id)
        queue.push(...(parents[id] || []))
    }
    return [...seen]
}

/** เติมรายชื่อฟิลด์จาก output จริงของการรันล่าสุด (top-level + เจาะ 1 ระดับ) */
function deriveFields(staticFields: UpstreamField[], sample: any): UpstreamField[] {
    const out: UpstreamField[] = [...staticFields]
    const has = (n: string) => out.some((f) => f.name === n)
    const add = (name: string, label: string) => { if (!has(name)) out.push({ name, label }) }
    if (sample && typeof sample === "object" && !Array.isArray(sample)) {
        for (const [k, v] of Object.entries(sample)) {
            add(k, k)
            if (Array.isArray(v) && v[0] && typeof v[0] === "object") {
                for (const sk of Object.keys(v[0])) add(`${k}.0.${sk}`, `${k}[0].${sk}`)
            } else if (v && typeof v === "object") {
                for (const sk of Object.keys(v)) add(`${k}.${sk}`, `${k}.${sk}`)
            }
        }
    }
    return out
}

function InsertVariableButton({ upstream, onInsert }: { upstream: UpstreamNode[]; onInsert: (token: string) => void }) {
    const [open, setOpen] = useState(false)
    const [expanded, setExpanded] = useState<string | null>(upstream[0]?.id ?? null)
    const ref = useRef<HTMLDivElement>(null)
    useEffect(() => {
        const h = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as HTMLElement)) setOpen(false) }
        document.addEventListener("mousedown", h)
        return () => document.removeEventListener("mousedown", h)
    }, [])
    return (
        <div className="relative" ref={ref}>
            <button
                type="button"
                onClick={() => setOpen((v) => !v)}
                className="flex items-center gap-1 text-[10px] text-[#2786C2] hover:text-[#1F6FA3] font-medium"
            >
                <Plus className="h-3 w-3" /> แทรกข้อมูลจากโหนดก่อนหน้า
            </button>
            {open && (
                <div className="absolute z-30 mt-1 w-64 max-h-72 overflow-y-auto bg-white border border-[#E2E8F0] rounded-xl shadow-lg p-1.5">
                    {upstream.length === 0 ? (
                        <p className="text-[10px] text-[#94A3B8] px-2 py-2">ยังไม่มีโหนดก่อนหน้า — ลากเส้นเชื่อมจากโหนดอื่นมายังโหนดนี้ก่อน</p>
                    ) : upstream.map((n) => (
                        <div key={n.id}>
                            <button
                                type="button"
                                onClick={() => setExpanded(expanded === n.id ? null : n.id)}
                                className="w-full flex items-center gap-1.5 px-2 py-1.5 rounded-lg hover:bg-[#F8F9FA] text-left"
                            >
                                {expanded === n.id ? <ChevronDown className="h-3 w-3 text-[#94A3B8]" /> : <ChevronRight className="h-3 w-3 text-[#94A3B8]" />}
                                <span className="text-[11px] font-medium text-[#0D1B2A] flex-1 truncate">{n.label}</span>
                                <span className="text-[9px] text-[#94A3B8]">{n.type}</span>
                            </button>
                            {expanded === n.id && (
                                <div className="pl-5 pb-1">
                                    <button
                                        type="button"
                                        onClick={() => { onInsert(`{{${n.id}}}`); setOpen(false) }}
                                        className="block w-full text-left px-2 py-1 rounded text-[10px] text-[#778DA9] hover:bg-[#EBF4FB] hover:text-[#2786C2] italic"
                                    >
                                        ทั้งโหนด ({"{{"}{n.id}{"}}"})
                                    </button>
                                    {n.fields.map((f) => (
                                        <button
                                            key={f.name}
                                            type="button"
                                            onClick={() => { onInsert(`{{${n.id}.${f.name}}}`); setOpen(false) }}
                                            className="block w-full text-left px-2 py-1 rounded text-[10px] text-[#0D1B2A] hover:bg-[#EBF4FB] hover:text-[#2786C2]"
                                        >
                                            {f.label} <span className="text-[#94A3B8]">· {f.name}</span>
                                        </button>
                                    ))}
                                    {n.fields.length === 0 && (
                                        <p className="px-2 py-1 text-[9px] text-[#94A3B8]">ไม่มีฟิลด์ที่ทราบล่วงหน้า — ลองรันโหนดนี้ก่อนเพื่อดูฟิลด์จริง</p>
                                    )}
                                </div>
                            )}
                        </div>
                    ))}
                </div>
            )}
        </div>
    )
}

// ── Config panel field renderer ──────────────────────────────────────
function ConfigField({
    field, value, onChange, jobs, upstream, integrations,
}: { field: NodeTypeDef["config_fields"][0]; value: any; onChange: (v: any) => void; jobs: JobSummary[]; upstream: UpstreamNode[]; integrations: Integration[] }) {
    const base = "w-full border border-[#E2E8F0] rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-[#2786C2]/30"
    const inputRef = useRef<HTMLInputElement | HTMLTextAreaElement | null>(null)
    const supportsTemplate = ["text", "textarea", "code"].includes(field.type)

    /** แทรก token ที่ตำแหน่ง caret ของช่องนี้ */
    const insertToken = (token: string) => {
        const el = inputRef.current
        const cur = typeof value === "string" ? value : ""
        if (el && typeof el.selectionStart === "number") {
            const start = el.selectionStart, end = el.selectionEnd ?? start
            onChange(cur.slice(0, start) + token + cur.slice(end))
            requestAnimationFrame(() => {
                el.focus()
                const pos = start + token.length
                el.setSelectionRange(pos, pos)
            })
        } else {
            onChange(cur + token)
        }
    }
    if (field.type === "integration_select") {
        const matches = integrations.filter((i) => !field.provider || i.type === field.provider)
        const known = matches.some((i) => i.id === value)
        return (
            <div>
                <select className={base} value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
                    <option value="">— เลือกบัญชี —</option>
                    {matches.map((i) => (
                        <option key={i.id} value={i.id}>{i.name}{i.status === "paused" ? " (paused)" : ""}</option>
                    ))}
                    {value && !known && <option value={value}>{`${value} (ไม่พบในรายการ)`}</option>}
                </select>
                {matches.length === 0 && (
                    <p className="text-[10px] text-amber-600 mt-1">
                        ยังไม่มีบัญชีชนิดนี้ — ไปสร้างที่ <a href="/integrations" className="underline">เมนู Integration</a> ก่อน
                    </p>
                )}
            </div>
        )
    }
    if (field.type === "job_select") {
        const known = jobs.some((j) => j.id === value)
        return (
            <select className={base} value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
                <option value="">— เลือก Job —</option>
                {jobs.map((j) => (
                    <option key={j.id} value={j.id}>{(j.name || "(ไม่มีชื่อ)") + ` · ${j.status}`}</option>
                ))}
                {value && !known && <option value={value}>{`${value} (ไม่พบในรายการ)`}</option>}
            </select>
        )
    }
    if (field.type === "boolean") {
        return (
            <label className="flex items-center gap-2 text-xs text-[#0D1B2A]">
                <input type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} />
                {field.label}
            </label>
        )
    }
    if (field.type === "select") {
        return (
            <select className={base} value={value ?? field.default ?? ""} onChange={(e) => onChange(e.target.value)}>
                {(field.options || []).map((o) => <option key={o} value={o}>{o || "(any)"}</option>)}
            </select>
        )
    }
    if (field.type === "textarea" || field.type === "code") {
        return (
            <div>
                {supportsTemplate && field.type !== "code" && (
                    <div className="mb-1"><InsertVariableButton upstream={upstream} onInsert={insertToken} /></div>
                )}
                <textarea
                    ref={(el) => { inputRef.current = el }}
                    className={`${base} ${field.type === "code" ? "font-mono" : ""}`}
                    rows={field.type === "code" ? 8 : 4}
                    value={value ?? ""}
                    placeholder={field.placeholder ?? (field.type === "code" ? "# set `result` variable\nresult = inputs" : undefined)}
                    onChange={(e) => onChange(e.target.value)}
                />
            </div>
        )
    }
    if (field.type === "mappings") {
        return <MappingsField value={value} onChange={onChange} base={base} upstream={upstream} />
    }
    return (
        <div>
            {supportsTemplate && (
                <div className="mb-1"><InsertVariableButton upstream={upstream} onInsert={insertToken} /></div>
            )}
            <input
                ref={(el) => { inputRef.current = el }}
                type={field.type === "number" ? "number" : "text"}
                className={base}
                placeholder={field.placeholder}
                value={value ?? field.default ?? ""}
                onChange={(e) => onChange(field.type === "number" ? Number(e.target.value) : e.target.value)}
            />
        </div>
    )
}

/** mappings field — แต่ละแถวมีช่อง target + value(template) + ปุ่มแทรกข้อมูล */
function MappingsField({
    value, onChange, base, upstream,
}: { value: any; onChange: (v: any) => void; base: string; upstream: UpstreamNode[] }) {
    const rows: { target: string; value: string }[] = Array.isArray(value) ? value : []
    const valueRefs = useRef<(HTMLInputElement | null)[]>([])
    const update = (i: number, key: "target" | "value", v: string) => {
        onChange(rows.map((r, idx) => (idx === i ? { ...r, [key]: v } : r)))
    }
    const insertAt = (i: number, token: string) => {
        const el = valueRefs.current[i]
        const cur = rows[i]?.value || ""
        if (el && typeof el.selectionStart === "number") {
            const start = el.selectionStart, end = el.selectionEnd ?? start
            update(i, "value", cur.slice(0, start) + token + cur.slice(end))
            requestAnimationFrame(() => { el.focus(); const p = start + token.length; el.setSelectionRange(p, p) })
        } else {
            update(i, "value", cur + token)
        }
    }
    return (
        <div className="space-y-2">
            {rows.map((r, i) => (
                <div key={i} className="border border-[#E2E8F0] rounded-lg p-1.5 space-y-1">
                    <div className="flex gap-1.5 items-center">
                        <input className={`${base} flex-[2]`} placeholder="ชื่อฟิลด์ใหม่" value={r.target || ""} onChange={(e) => update(i, "target", e.target.value)} />
                        <span className="text-[#94A3B8] text-xs">=</span>
                        <button onClick={() => onChange(rows.filter((_, idx) => idx !== i))} className="text-red-400 hover:text-red-600" title="ลบ">
                            <X className="h-3.5 w-3.5" />
                        </button>
                    </div>
                    <InsertVariableButton upstream={upstream} onInsert={(t) => insertAt(i, t)} />
                    <input
                        ref={(el) => { valueRefs.current[i] = el }}
                        className={base}
                        placeholder="ค่า เช่น {{jobs_1.count}} หรือข้อความคงที่"
                        value={r.value || ""}
                        onChange={(e) => update(i, "value", e.target.value)}
                    />
                </div>
            ))}
            <button onClick={() => onChange([...rows, { target: "", value: "" }])} className="text-xs text-[#2786C2] hover:underline">
                + เพิ่ม mapping
            </button>
        </div>
    )
}

// ── Main builder ─────────────────────────────────────────────────────
function Builder() {
    const params = useParams()
    const searchParams = useSearchParams()
    const workflowId = params.id as string
    const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
    const { screenToFlowPosition } = useReactFlow()

    const [workflow, setWorkflow] = useState<Workflow | null>(null)
    const [nodeDefs, setNodeDefs] = useState<NodeTypeDef[]>([])
    const [jobs, setJobs] = useState<JobSummary[]>([])
    const [integrations, setIntegrations] = useState<Integration[]>([])
    const [nodes, setNodes, onNodesChange] = useNodesState<Node>([])
    const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])
    const [selectedId, setSelectedId] = useState<string | null>(null)
    const [saving, setSaving] = useState(false)
    const [dirty, setDirty] = useState(false)
    const [notice, setNotice] = useState<string | null>(null)

    // schedule
    const [scheduleOpen, setScheduleOpen] = useState(false)
    const [cron, setCron] = useState("")
    const [scheduleEnabled, setScheduleEnabled] = useState(false)

    // runs / activity
    const [activeRun, setActiveRun] = useState<WorkflowRun | null>(null)
    const [runPanelOpen, setRunPanelOpen] = useState(false)
    const [runHistory, setRunHistory] = useState<WorkflowRun[]>([])
    const [showRunModal, setShowRunModal] = useState(false)
    const [runInput, setRunInput] = useState("")
    const [starting, setStarting] = useState(false)
    const [testing, setTesting] = useState(false)
    // output จริงของแต่ละโหนดจากการรันเต็มล่าสุด — ใช้เติมฟิลด์ใน variable picker
    const [nodeOutputs, setNodeOutputs] = useState<Record<string, any>>({})
    const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

    // ── Load workflow + node catalog ──
    useEffect(() => {
        if (!token) return
        Promise.all([getWorkflow(token, workflowId), getNodeTypes(token)])
            .then(([wf, nt]) => {
                setWorkflow(wf)
                setNodeDefs(nt.node_types)
                setNodes(toFlowNodes(wf, nt.node_types))
                setEdges(toFlowEdges(wf))
                setCron(wf.schedule_cron || "")
                setScheduleEnabled(wf.schedule_enabled)
                const runId = searchParams.get("run")
                if (runId) watchRun(runId)
            })
            .catch((e) => setNotice(e.message))
        getJobs(token).then(setJobs).catch(() => { /* picker falls back to manual id */ })
        getActiveIntegrations(token).then(setIntegrations).catch(() => { /* select shows empty hint */ })
        loadLatestOutputs()
        return () => { if (pollRef.current) clearInterval(pollRef.current) }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [token, workflowId])

    // ── Run polling ──
    const applyRunToCanvas = useCallback((run: WorkflowRun | null) => {
        setNodes((nds) => nds.map((n) => {
            const nr = run?.node_runs?.find((r) => r.node_id === n.id)
            return { ...n, data: { ...n.data, runStatus: nr?.status } }
        }))
    }, [setNodes])

    // เก็บ output จริงของแต่ละโหนดไว้เติม variable picker (เฉพาะ run เต็ม ไม่ใช่ node_test)
    const captureOutputs = useCallback((run: WorkflowRun) => {
        if (run.trigger_type === "node_test") return
        setNodeOutputs((prev) => {
            const next = { ...prev }
            for (const nr of run.node_runs || []) {
                if (nr.output != null) next[nr.node_id] = nr.output
            }
            return next
        })
    }, [])

    // โหลด output จากการรันเต็มล่าสุดตอนเปิดหน้า (ให้ picker มีฟิลด์จริงทันที)
    const loadLatestOutputs = useCallback(async () => {
        if (!token) return
        try {
            const { runs } = await getWorkflowRuns(token, workflowId, 10)
            const latest = runs.find((r) => r.trigger_type !== "node_test")
            if (latest) captureOutputs(await getRun(token, latest.id))
        } catch { /* ignore */ }
    }, [token, workflowId, captureOutputs])

    const watchRun = useCallback((runId: string) => {
        if (!token) return
        setRunPanelOpen(true)
        if (pollRef.current) clearInterval(pollRef.current)
        const tick = async () => {
            try {
                const run = await getRun(token, runId)
                setActiveRun(run)
                applyRunToCanvas(run)
                captureOutputs(run)
                if (["succeeded", "failed", "cancelled"].includes(run.status) && pollRef.current) {
                    clearInterval(pollRef.current)
                    pollRef.current = null
                }
            } catch { /* transient poll errors are fine */ }
        }
        tick()
        pollRef.current = setInterval(tick, 1500)
    }, [token, applyRunToCanvas])

    // ── DnD from palette ──
    const onDragStart = (e: React.DragEvent, type: string) => {
        e.dataTransfer.setData("application/wf-node", type)
        e.dataTransfer.effectAllowed = "move"
    }

    const onDrop = useCallback((e: React.DragEvent) => {
        e.preventDefault()
        const type = e.dataTransfer.getData("application/wf-node")
        const def = nodeDefs.find((d) => d.type === type)
        if (!def) return
        const position = screenToFlowPosition({ x: e.clientX, y: e.clientY })
        const config: Record<string, any> = {}
        def.config_fields.forEach((f) => { if (f.default !== undefined) config[f.name] = f.default })
        const id = `${type}_${Date.now().toString(36)}`
        setNodes((nds) => [...nds, {
            id, type: "wf", position,
            data: { nodeType: type, label: def.label, config, category: def.category },
        }])
        setSelectedId(id)
        setDirty(true)
    }, [nodeDefs, screenToFlowPosition, setNodes])

    const onConnect = useCallback((conn: Connection) => {
        setEdges((eds) => addEdge({
            ...conn,
            label: conn.sourceHandle === "true" ? "True" : conn.sourceHandle === "false" ? "False" : undefined,
            markerEnd: { type: MarkerType.ArrowClosed },
            style: { strokeWidth: 1.5 },
        }, eds))
        setDirty(true)
    }, [setEdges])

    // ── Save ──
    const handleSave = async () => {
        if (!token || !workflow) return
        try {
            setSaving(true)
            const updated = await updateWorkflow(token, workflowId, {
                name: workflow.name,
                description: workflow.description,
                definition: toDefinition(nodes, edges),
                schedule_cron: cron.trim() || null,
                schedule_enabled: scheduleEnabled && !!cron.trim(),
            })
            setWorkflow(updated)
            setDirty(false)
            setNotice(null)
        } catch (e: any) {
            setNotice(`Save failed: ${e.message}`)
        } finally {
            setSaving(false)
        }
    }

    // ── Run ──
    const handleRun = async () => {
        if (!token) return
        let input: Record<string, any> = {}
        if (runInput.trim()) {
            try { input = JSON.parse(runInput) } catch { setNotice("Trigger input ต้องเป็น JSON ที่ถูกต้อง"); return }
        }
        try {
            setStarting(true)
            if (dirty) await handleSave()
            const run = await runWorkflow(token, workflowId, input)
            setShowRunModal(false)
            watchRun(run.id)
        } catch (e: any) {
            setNotice(`Run failed: ${e.message}`)
        } finally {
            setStarting(false)
        }
    }

    const loadHistory = async () => {
        if (!token) return
        try {
            const data = await getWorkflowRuns(token, workflowId)
            setRunHistory(data.runs as unknown as WorkflowRun[])
        } catch { /* ignore */ }
    }

    // ── Selection / deletion ──
    const selectedNode = nodes.find((n) => n.id === selectedId) || null
    const selectedDef = selectedNode ? nodeDefs.find((d) => d.type === (selectedNode.data as WfNodeData).nodeType) : null

    const updateSelectedConfig = (name: string, value: any) => {
        setNodes((nds) => nds.map((n) => n.id === selectedId
            ? { ...n, data: { ...n.data, config: { ...(n.data as WfNodeData).config, [name]: value } } }
            : n))
        setDirty(true)
    }

    const updateSelectedLabel = (label: string) => {
        setNodes((nds) => nds.map((n) => n.id === selectedId ? { ...n, data: { ...n.data, label } } : n))
        setDirty(true)
    }

    const deleteSelected = () => {
        if (!selectedId) return
        setNodes((nds) => nds.filter((n) => n.id !== selectedId))
        setEdges((eds) => eds.filter((e) => e.source !== selectedId && e.target !== selectedId))
        setSelectedId(null)
        setDirty(true)
    }

    // รายชื่อโหนดต้นทาง + ฟิลด์ ที่ใช้ใน variable picker ของโหนดที่เลือก
    const upstreamVars: UpstreamNode[] = useMemo(() => {
        if (!selectedId) return []
        const ancestorIds = getAncestors(selectedId, edges)
        return ancestorIds.map((id) => {
            const node = nodes.find((n) => n.id === id)
            const nodeType = node ? (node.data as WfNodeData).nodeType : "unknown"
            const def = nodeDefs.find((d) => d.type === nodeType)
            let staticFields: UpstreamField[] = (def?.output_fields || []).map((f) => ({ name: f.name, label: f.label }))
            // transform: ฟิลด์มาจาก target ที่ผู้ใช้กำหนดเอง
            if (nodeType === "transform") {
                const maps = (node?.data as WfNodeData)?.config?.mappings || []
                staticFields = maps.filter((m: any) => m?.target).map((m: any) => ({ name: m.target, label: m.target }))
            }
            const fields = deriveFields(staticFields, nodeOutputs[id])
            return {
                id,
                label: node ? (node.data as WfNodeData).label : id,
                type: nodeType,
                fields,
            }
        })
    }, [selectedId, edges, nodes, nodeDefs, nodeOutputs])

    // ── ทดสอบโหนดเดียว ──
    const handleTestNode = async () => {
        if (!token || !selectedId) return
        try {
            setTesting(true)
            if (dirty) await handleSave()
            const run = await testNode(token, workflowId, selectedId)
            watchRun(run.id)
        } catch (e: any) {
            setNotice(`ทดสอบโหนดล้มเหลว: ${e.message}`)
        } finally {
            setTesting(false)
        }
    }

    const grouped = useMemo(() => {
        const groups: Record<string, NodeTypeDef[]> = {}
        nodeDefs.forEach((d) => { (groups[d.category] ||= []).push(d) })
        return groups
    }, [nodeDefs])

    if (!workflow) {
        return (
            <div className="flex items-center justify-center h-full text-[#778DA9]">
                <Loader2 className="h-6 w-6 animate-spin mr-2" /> Loading workflow…
            </div>
        )
    }

    return (
        <div className="flex flex-col h-full">
            {/* ── Top bar ── */}
            <div className="flex items-center gap-3 px-4 py-2.5 bg-white border-b border-[#E2E8F0]">
                <Link href="/workflows" className="p-1.5 rounded-lg hover:bg-[#F8F9FA] text-[#778DA9]">
                    <ArrowLeft className="h-4 w-4" />
                </Link>
                <input
                    className="font-semibold text-[#0D1B2A] text-sm bg-transparent focus:outline-none focus:ring-2 focus:ring-[#2786C2]/30 rounded px-2 py-1 min-w-0 flex-1 max-w-xs"
                    value={workflow.name}
                    onChange={(e) => { setWorkflow({ ...workflow, name: e.target.value }); setDirty(true) }}
                />
                {dirty && <span className="text-[10px] text-amber-600 bg-amber-50 px-2 py-0.5 rounded-full">unsaved</span>}

                <div className="flex-1" />

                {/* Schedule */}
                <div className="relative">
                    <button
                        onClick={() => setScheduleOpen(!scheduleOpen)}
                        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs border transition-colors ${
                            scheduleEnabled && cron ? "border-[#2786C2] text-[#2786C2] bg-[#EBF4FB]" : "border-[#E2E8F0] text-[#778DA9] hover:bg-[#F8F9FA]"
                        }`}
                    >
                        <CalendarClock className="h-3.5 w-3.5" />
                        {scheduleEnabled && cron ? `Schedule: ${cron}` : "Schedule"}
                    </button>
                    {scheduleOpen && (
                        <div className="absolute right-0 top-9 z-30 bg-white border border-[#E2E8F0] rounded-xl shadow-lg p-4 w-72">
                            <p className="text-xs font-semibold text-[#0D1B2A] mb-2">ตั้งเวลารันอัตโนมัติ (Cron)</p>
                            <input
                                className="w-full border border-[#E2E8F0] rounded-lg px-2.5 py-1.5 text-xs font-mono mb-1"
                                placeholder="*/15 * * * *"
                                value={cron}
                                onChange={(e) => { setCron(e.target.value); setDirty(true) }}
                            />
                            <p className="text-[10px] text-[#94A3B8] mb-2">นาที ชั่วโมง วัน เดือน วันในสัปดาห์ — เช่น &quot;0 9 * * 1-5&quot; = 9 โมงเช้าวันจันทร์–ศุกร์</p>
                            <label className="flex items-center gap-2 text-xs text-[#0D1B2A]">
                                <input type="checkbox" checked={scheduleEnabled} onChange={(e) => { setScheduleEnabled(e.target.checked); setDirty(true) }} />
                                เปิดใช้งาน schedule
                            </label>
                            <p className="text-[10px] text-[#94A3B8] mt-2">กด Save เพื่อบันทึกการตั้งเวลา</p>
                        </div>
                    )}
                </div>

                <button
                    onClick={() => { setRunPanelOpen(!runPanelOpen); if (!runPanelOpen) loadHistory() }}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs border border-[#E2E8F0] text-[#778DA9] hover:bg-[#F8F9FA]"
                >
                    <Activity className="h-3.5 w-3.5" /> Activity
                </button>

                <button
                    onClick={handleSave}
                    disabled={saving}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs border border-[#2786C2] text-[#2786C2] hover:bg-[#EBF4FB] disabled:opacity-50"
                >
                    {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />} Save
                </button>
                <button
                    onClick={() => setShowRunModal(true)}
                    className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs bg-[#2786C2] text-white hover:bg-[#1F6FA3]"
                >
                    <Play className="h-3.5 w-3.5" /> Run
                </button>
            </div>

            {notice && (
                <div className="px-4 py-2 bg-amber-50 text-amber-700 text-xs flex justify-between">
                    {notice}
                    <button onClick={() => setNotice(null)} className="font-bold ml-4">×</button>
                </div>
            )}

            <div className="flex flex-1 min-h-0">
                {/* ── Palette ── */}
                <aside className="w-56 bg-white border-r border-[#E2E8F0] overflow-y-auto p-3 space-y-4">
                    <p className="text-[10px] uppercase tracking-wide text-[#94A3B8] font-semibold">ลาก node ไปวางบน canvas</p>
                    {Object.entries(grouped).map(([cat, defs]) => {
                        const style = CATEGORY_STYLE[cat] || CATEGORY_STYLE.action
                        return (
                            <div key={cat}>
                                <p className="text-[10px] uppercase tracking-wide font-semibold mb-1.5" style={{ color: style.color }}>{cat}</p>
                                <div className="space-y-1.5">
                                    {defs.map((d) => {
                                        const Icon = TYPE_ICON[d.type] || style.icon
                                        return (
                                            <div
                                                key={d.type}
                                                draggable
                                                onDragStart={(e) => onDragStart(e, d.type)}
                                                title={d.description}
                                                className="flex items-center gap-2 px-2.5 py-2 rounded-lg border border-[#E2E8F0] bg-white cursor-grab hover:border-[#2786C2] hover:shadow-sm transition-all"
                                            >
                                                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md" style={{ background: style.bg }}>
                                                    <Icon className="h-3.5 w-3.5" style={{ color: style.color }} />
                                                </span>
                                                <span className="text-xs text-[#0D1B2A]">{d.label}</span>
                                            </div>
                                        )
                                    })}
                                </div>
                            </div>
                        )
                    })}
                </aside>

                {/* ── Canvas ── */}
                <div className="flex-1 relative" onDrop={onDrop} onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = "move" }}>
                    <ReactFlow
                        nodes={nodes}
                        edges={edges}
                        nodeTypes={nodeTypes}
                        onNodesChange={(c) => { onNodesChange(c); if (c.some((ch) => ch.type !== "select" && ch.type !== "dimensions")) setDirty(true) }}
                        onEdgesChange={(c) => { onEdgesChange(c); if (c.some((ch) => ch.type === "remove")) setDirty(true) }}
                        onConnect={onConnect}
                        onNodeClick={(_, n) => setSelectedId(n.id)}
                        onPaneClick={() => { setSelectedId(null); setScheduleOpen(false) }}
                        fitView
                        proOptions={{ hideAttribution: true }}
                        deleteKeyCode={["Backspace", "Delete"]}
                    >
                        <Background gap={18} color="#E2E8F0" />
                        <Controls position="bottom-left" />
                        <MiniMap pannable zoomable className="!bg-[#F8F9FA]" />
                    </ReactFlow>

                    {/* ── Activity panel ── */}
                    {runPanelOpen && (
                        <div className="absolute top-3 right-3 z-20 w-80 max-h-[calc(100%-24px)] bg-white border border-[#E2E8F0] rounded-xl shadow-lg flex flex-col">
                            <div className="flex items-center justify-between px-3 py-2.5 border-b border-[#E2E8F0]">
                                <span className="text-xs font-semibold text-[#0D1B2A] flex items-center gap-1.5">
                                    <Activity className="h-3.5 w-3.5 text-[#2786C2]" /> Run Activity
                                </span>
                                <button onClick={() => { setRunPanelOpen(false); setActiveRun(null); applyRunToCanvas(null) }} className="text-[#94A3B8] hover:text-[#0D1B2A]">
                                    <X className="h-4 w-4" />
                                </button>
                            </div>
                            <div className="overflow-y-auto p-3 space-y-2">
                                {activeRun ? (
                                    <>
                                        <div className="flex items-center gap-2 text-xs">
                                            <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${
                                                activeRun.status === "succeeded" ? "bg-emerald-50 text-emerald-600"
                                                : activeRun.status === "failed" ? "bg-red-50 text-red-600"
                                                : "bg-[#EBF4FB] text-[#2786C2]"
                                            }`}>
                                                {activeRun.status}
                                            </span>
                                            <span className="text-[#94A3B8] text-[10px]">{TRIGGER_TYPE_LABEL[activeRun.trigger_type] || activeRun.trigger_type}</span>
                                            {["queued", "running"].includes(activeRun.status) && <Loader2 className="h-3 w-3 animate-spin text-[#2786C2]" />}
                                            <button className="ml-auto text-[10px] text-[#2786C2] hover:underline" onClick={() => { setActiveRun(null); loadHistory() }}>
                                                ← history
                                            </button>
                                        </div>
                                        {activeRun.error && <p className="text-[10px] text-red-600 bg-red-50 rounded-lg p-2">{activeRun.error}</p>}
                                        {(activeRun.node_runs || []).map((nr) => <NodeRunRow key={nr.id} nr={nr} runId={activeRun.id} />)}
                                    </>
                                ) : (
                                    <>
                                        <p className="text-[10px] text-[#94A3B8]">ประวัติการรันล่าสุด</p>
                                        {runHistory.length === 0 && <p className="text-xs text-[#778DA9]">ยังไม่มีการรัน</p>}
                                        {runHistory.map((r) => (
                                            <button
                                                key={r.id}
                                                onClick={() => watchRun(r.id)}
                                                className="w-full flex items-center gap-2 px-3 py-2 rounded-lg border border-[#E2E8F0] hover:border-[#2786C2] text-left"
                                            >
                                                {r.status === "succeeded" ? <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
                                                    : r.status === "failed" ? <XCircle className="h-3.5 w-3.5 text-red-500" />
                                                    : <Loader2 className="h-3.5 w-3.5 text-[#2786C2] animate-spin" />}
                                                <span className="text-[11px] text-[#0D1B2A] flex-1">
                                                    {r.created_at ? new Date(r.created_at).toLocaleString() : r.id.slice(0, 8)}
                                                </span>
                                                <span className="text-[10px] text-[#94A3B8]">{TRIGGER_TYPE_LABEL[r.trigger_type] || r.trigger_type}</span>
                                            </button>
                                        ))}
                                    </>
                                )}
                            </div>
                        </div>
                    )}
                </div>

                {/* ── Config panel ── */}
                {selectedNode && selectedDef && (
                    <aside className="w-80 bg-white border-l border-[#E2E8F0] overflow-y-auto p-4">
                        <div className="flex items-center justify-between mb-1">
                            <span className="text-xs font-semibold text-[#0D1B2A]">{selectedDef.label}</span>
                            <button onClick={deleteSelected} title="ลบ node" className="p-1.5 rounded-lg text-red-500 hover:bg-red-50">
                                <Trash2 className="h-3.5 w-3.5" />
                            </button>
                        </div>
                        <p className="text-[10px] text-[#94A3B8] mb-3">{selectedDef.description}</p>

                        {/* ปุ่มทดสอบโหนดเดียว */}
                        {!(selectedNode.data as WfNodeData).nodeType.startsWith("trigger") && (
                            <button
                                onClick={handleTestNode}
                                disabled={testing}
                                className="w-full flex items-center justify-center gap-1.5 mb-4 px-3 py-1.5 rounded-lg text-xs border border-emerald-500 text-emerald-600 hover:bg-emerald-50 disabled:opacity-50"
                            >
                                {testing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <FlaskConical className="h-3.5 w-3.5" />}
                                ทดสอบโหนดนี้
                            </button>
                        )}

                        <label className="block text-[10px] uppercase tracking-wide text-[#94A3B8] font-semibold mb-1">ชื่อโหนด</label>
                        <input
                            className="w-full border border-[#E2E8F0] rounded-lg px-2.5 py-1.5 text-xs mb-4 focus:outline-none focus:ring-2 focus:ring-[#2786C2]/30"
                            value={(selectedNode.data as WfNodeData).label}
                            onChange={(e) => updateSelectedLabel(e.target.value)}
                        />

                        <div className="space-y-3">
                            {selectedDef.config_fields.map((f) => (
                                <div key={f.name}>
                                    {f.type !== "boolean" && (
                                        <label className="block text-[10px] uppercase tracking-wide text-[#94A3B8] font-semibold mb-1">
                                            {f.label}{f.required ? " *" : ""}
                                        </label>
                                    )}
                                    <ConfigField
                                        field={f}
                                        value={(selectedNode.data as WfNodeData).config?.[f.name]}
                                        onChange={(v) => updateSelectedConfig(f.name, v)}
                                        jobs={jobs}
                                        upstream={upstreamVars}
                                        integrations={integrations}
                                    />
                                    {f.hint && <p className="text-[10px] text-[#94A3B8] mt-1 leading-snug">{f.hint}</p>}
                                </div>
                            ))}
                        </div>

                        <div className="mt-5 p-3 rounded-lg bg-[#F8F9FA] text-[10px] text-[#778DA9] leading-relaxed">
                            <p className="font-semibold text-[#0D1B2A] mb-1">💡 เคล็ดลับ</p>
                            กดปุ่ม <span className="text-[#2786C2]">“+ แทรกข้อมูลจากโหนดก่อนหน้า”</span> เพื่อเลือกค่าจากโหนดอื่นโดยไม่ต้องพิมพ์เอง<br />
                            กด <span className="text-emerald-600">“ทดสอบโหนดนี้”</span> เพื่อดูผลเฉพาะโหนดนี้ (ต้องรัน workflow เต็มอย่างน้อย 1 ครั้งก่อน)
                        </div>
                    </aside>
                )}
            </div>

            {/* ── Run modal ── */}
            {showRunModal && (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={() => setShowRunModal(false)}>
                    <div className="bg-white rounded-xl p-5 w-full max-w-md mx-4" onClick={(e) => e.stopPropagation()}>
                        <h3 className="text-sm font-semibold text-[#0D1B2A] mb-3">Run Workflow</h3>
                        <label className="block text-xs text-[#778DA9] mb-1">Trigger input (JSON, optional) — เข้าถึงด้วย {"{{trigger.field}}"}</label>
                        <textarea
                            rows={4}
                            className="w-full border border-[#E2E8F0] rounded-lg px-2.5 py-1.5 text-xs font-mono mb-4 focus:outline-none focus:ring-2 focus:ring-[#2786C2]/30"
                            placeholder='{ "customer": "ACME" }'
                            value={runInput}
                            onChange={(e) => setRunInput(e.target.value)}
                        />
                        <div className="flex justify-end gap-2">
                            <button onClick={() => setShowRunModal(false)} className="px-3 py-1.5 rounded-lg text-xs text-[#778DA9] hover:bg-gray-50">ยกเลิก</button>
                            <button
                                onClick={handleRun}
                                disabled={starting}
                                className="px-4 py-1.5 rounded-lg bg-[#2786C2] text-white text-xs hover:bg-[#1F6FA3] disabled:opacity-50 flex items-center gap-1.5"
                            >
                                {starting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
                                {dirty ? "Save & Run" : "Run"}
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}

export default function WorkflowBuilderPage() {
    return (
        <ReactFlowProvider>
            <Builder />
        </ReactFlowProvider>
    )
}
