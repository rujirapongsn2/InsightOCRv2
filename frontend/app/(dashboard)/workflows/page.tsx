"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import {
    Plus, Play, Trash2, Pencil, CalendarClock, Loader2, Workflow as WorkflowIcon,
    CheckCircle2, XCircle, Clock, Sparkles, PencilRuler, Download, Upload,
} from "lucide-react"
import {
    Workflow, getWorkflows, createWorkflow, deleteWorkflow, runWorkflow, updateWorkflow,
    exportWorkflow, importWorkflow, downloadWorkflowJson, WorkflowExport,
} from "@/lib/workflows-api"

const statusBadge = (wf: Workflow) => {
    if (!wf.is_active) return <span className="px-2 py-0.5 rounded-full text-xs bg-gray-100 text-gray-500">Inactive</span>
    return <span className="px-2 py-0.5 rounded-full text-xs bg-emerald-50 text-emerald-600">Active</span>
}

export default function WorkflowsPage() {
    const router = useRouter()
    const token = typeof window !== "undefined" ? localStorage.getItem("token") : null

    const [workflows, setWorkflows] = useState<Workflow[]>([])
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const [showCreate, setShowCreate] = useState(false)
    const [createMode, setCreateMode] = useState<"manual" | "ai">("ai")
    const [newName, setNewName] = useState("")
    const [newDescription, setNewDescription] = useState("")
    const [creating, setCreating] = useState(false)
    const [runningId, setRunningId] = useState<string | null>(null)
    const [notice, setNotice] = useState<string | null>(null)
    const [importing, setImporting] = useState(false)
    const importInputRef = useRef<HTMLInputElement>(null)

    const load = useCallback(async () => {
        if (!token) return
        try {
            setLoading(true)
            const data = await getWorkflows(token)
            setWorkflows(data.workflows)
            setError(null)
        } catch (e: any) {
            setError(e.message || "Failed to load workflows")
        } finally {
            setLoading(false)
        }
    }, [token])

    useEffect(() => { load() }, [load])

    const handleCreate = async () => {
        if (createMode === "ai") {
            // AI builder collects the name/goal in a chat — go straight there.
            router.push("/workflows/new/ai")
            return
        }
        if (!token || !newName.trim()) return
        try {
            setCreating(true)
            const wf = await createWorkflow(token, {
                name: newName.trim(),
                description: newDescription.trim() || undefined,
                definition: {
                    nodes: [{
                        id: "trigger_1",
                        type: "trigger_manual",
                        position: { x: 80, y: 200 },
                        data: { label: "Manual Trigger", config: {} },
                    }],
                    edges: [],
                },
            })
            router.push(`/workflows/${wf.id}`)
        } catch (e: any) {
            setError(e.message)
            setCreating(false)
        }
    }

    const handleExport = async (wf: Workflow) => {
        if (!token) return
        try {
            const data = await exportWorkflow(token, wf.id)
            downloadWorkflowJson(data)
        } catch (e: any) {
            setNotice(`Export failed: ${e.message}`)
        }
    }

    const handleImportFile = async (file: File) => {
        if (!token) return
        try {
            setImporting(true)
            const text = await file.text()
            const parsed = JSON.parse(text) as WorkflowExport
            if (!parsed.name || !parsed.definition) {
                throw new Error("ไฟล์ไม่ถูกต้อง: ต้องมี name และ definition")
            }
            const res = await importWorkflow(token, {
                schema_version: parsed.schema_version ?? 1,
                name: parsed.name,
                description: parsed.description ?? null,
                schedule_cron: parsed.schedule_cron ?? null,
                schedule_enabled: !!parsed.schedule_enabled,
                definition: parsed.definition,
            })
            const warnCount = res.warnings?.length || 0
            router.push(`/workflows/${res.workflow.id}${warnCount ? "?warnings=1" : ""}`)
        } catch (e: any) {
            setNotice(`Import failed: ${e.message}`)
            setImporting(false)
        }
    }

    const handleRun = async (wf: Workflow) => {
        if (!token) return
        try {
            setRunningId(wf.id)
            const run = await runWorkflow(token, wf.id)
            router.push(`/workflows/${wf.id}?run=${run.id}`)
        } catch (e: any) {
            setNotice(`Run failed: ${e.message}`)
            setRunningId(null)
        }
    }

    const handleDelete = async (wf: Workflow) => {
        if (!token) return
        if (!confirm(`ลบ workflow "${wf.name}" และประวัติการรันทั้งหมด?`)) return
        try {
            await deleteWorkflow(token, wf.id)
            setWorkflows((prev) => prev.filter((w) => w.id !== wf.id))
        } catch (e: any) {
            setNotice(`Delete failed: ${e.message}`)
        }
    }

    const toggleActive = async (wf: Workflow) => {
        if (!token) return
        try {
            const updated = await updateWorkflow(token, wf.id, { is_active: !wf.is_active })
            setWorkflows((prev) => prev.map((w) => (w.id === wf.id ? updated : w)))
        } catch (e: any) {
            setNotice(`Update failed: ${e.message}`)
        }
    }

    return (
        <div className="max-w-6xl mx-auto">
            <div className="flex items-center justify-between mb-6">
                <div>
                    <h1 className="text-2xl font-bold text-[#0D1B2A] flex items-center gap-2">
                        <WorkflowIcon className="h-6 w-6 text-[#2786C2]" /> Workflow
                    </h1>
                    <p className="text-sm text-[#778DA9] mt-1">
                        สร้าง automation process สำหรับเอกสารแบบ drag & drop — รันเองหรือตั้งเวลาอัตโนมัติ
                    </p>
                </div>
                <div className="flex items-center gap-2">
                    <input
                        ref={importInputRef}
                        type="file"
                        accept=".json,application/json"
                        className="hidden"
                        onChange={(e) => {
                            const f = e.target.files?.[0]
                            if (f) handleImportFile(f)
                            e.target.value = ""
                        }}
                    />
                    <button
                        onClick={() => importInputRef.current?.click()}
                        disabled={importing}
                        className="flex items-center gap-2 px-4 py-2 rounded-lg border border-[#CBD5E1] text-[#0D1B2A] text-sm font-medium hover:bg-gray-50 disabled:opacity-50"
                    >
                        {importing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />} Import
                    </button>
                    <button
                        onClick={() => setShowCreate(true)}
                        className="flex items-center gap-2 px-4 py-2 rounded-lg bg-[#2786C2] text-white text-sm font-medium hover:bg-[#1F6FA3] transition-colors"
                    >
                        <Plus className="h-4 w-4" /> New Workflow
                    </button>
                </div>
            </div>

            {notice && (
                <div className="mb-4 px-4 py-2 rounded-lg bg-amber-50 text-amber-700 text-sm flex justify-between">
                    {notice}
                    <button onClick={() => setNotice(null)} className="font-bold ml-4">×</button>
                </div>
            )}
            {error && <div className="mb-4 px-4 py-2 rounded-lg bg-red-50 text-red-600 text-sm">{error}</div>}

            {loading ? (
                <div className="flex items-center justify-center py-20 text-[#778DA9]">
                    <Loader2 className="h-6 w-6 animate-spin mr-2" /> Loading…
                </div>
            ) : workflows.length === 0 ? (
                <div className="border border-dashed border-[#CBD5E1] rounded-xl py-16 text-center">
                    <WorkflowIcon className="h-10 w-10 text-[#CBD5E1] mx-auto mb-3" />
                    <p className="text-[#778DA9] mb-4">ยังไม่มี workflow — เริ่มสร้างกระบวนการอัตโนมัติแรกของคุณ</p>
                    <button
                        onClick={() => setShowCreate(true)}
                        className="px-4 py-2 rounded-lg bg-[#2786C2] text-white text-sm hover:bg-[#1F6FA3]"
                    >
                        สร้าง Workflow แรก
                    </button>
                </div>
            ) : (
                <div className="grid gap-3">
                    {workflows.map((wf) => (
                        <div
                            key={wf.id}
                            className="bg-white border border-[#E2E8F0] rounded-xl px-5 py-4 flex items-center gap-4 hover:shadow-sm transition-shadow"
                        >
                            <div className="flex-1 min-w-0 cursor-pointer" onClick={() => router.push(`/workflows/${wf.id}`)}>
                                <div className="flex items-center gap-2">
                                    <span className="font-semibold text-[#0D1B2A] truncate">{wf.name}</span>
                                    {statusBadge(wf)}
                                    {wf.schedule_enabled && wf.schedule_cron && (
                                        <span className="flex items-center gap-1 px-2 py-0.5 rounded-full text-xs bg-[#EBF4FB] text-[#2786C2]">
                                            <CalendarClock className="h-3 w-3" /> {wf.schedule_cron}
                                        </span>
                                    )}
                                </div>
                                {wf.description && <p className="text-sm text-[#778DA9] truncate mt-0.5">{wf.description}</p>}
                                <p className="text-xs text-[#9AA8BC] mt-1 flex items-center gap-3">
                                    <span>{(wf.definition?.nodes || []).length} nodes</span>
                                    {wf.last_run_at && (
                                        <span className="flex items-center gap-1">
                                            <Clock className="h-3 w-3" /> last run {new Date(wf.last_run_at).toLocaleString()}
                                        </span>
                                    )}
                                </p>
                            </div>

                            <div className="flex items-center gap-1 shrink-0">
                                <button
                                    onClick={() => handleRun(wf)}
                                    disabled={runningId === wf.id || !wf.is_active}
                                    title="Run now"
                                    className="p-2 rounded-lg text-emerald-600 hover:bg-emerald-50 disabled:opacity-40"
                                >
                                    {runningId === wf.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                                </button>
                                <button
                                    onClick={() => router.push(`/workflows/${wf.id}`)}
                                    title="Edit"
                                    className="p-2 rounded-lg text-[#2786C2] hover:bg-[#EBF4FB]"
                                >
                                    <Pencil className="h-4 w-4" />
                                </button>
                                <button
                                    onClick={() => handleExport(wf)}
                                    title="Export JSON"
                                    className="p-2 rounded-lg text-[#778DA9] hover:bg-gray-50"
                                >
                                    <Download className="h-4 w-4" />
                                </button>
                                <button
                                    onClick={() => toggleActive(wf)}
                                    title={wf.is_active ? "Deactivate" : "Activate"}
                                    className="p-2 rounded-lg hover:bg-gray-50"
                                >
                                    {wf.is_active
                                        ? <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                                        : <XCircle className="h-4 w-4 text-gray-400" />}
                                </button>
                                <button
                                    onClick={() => handleDelete(wf)}
                                    title="Delete"
                                    className="p-2 rounded-lg text-red-500 hover:bg-red-50"
                                >
                                    <Trash2 className="h-4 w-4" />
                                </button>
                            </div>
                        </div>
                    ))}
                </div>
            )}

            {/* Create modal */}
            {showCreate && (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={() => setShowCreate(false)}>
                    <div className="bg-white rounded-xl p-6 w-full max-w-md mx-4" onClick={(e) => e.stopPropagation()}>
                        <h2 className="text-lg font-semibold text-[#0D1B2A] mb-4">สร้าง Workflow ใหม่</h2>

                        {/* Mode selector: AI Agent (new) vs Manual (existing builder) */}
                        <div className="grid grid-cols-2 gap-2 mb-4">
                            <button
                                onClick={() => setCreateMode("ai")}
                                className={`flex flex-col items-start gap-1 p-3 rounded-lg border text-left transition-colors ${createMode === "ai" ? "border-[#2786C2] bg-[#EBF4FB]" : "border-[#E2E8F0] hover:bg-gray-50"}`}
                            >
                                <span className="flex items-center gap-1.5 font-medium text-sm text-[#0D1B2A]">
                                    <Sparkles className="h-4 w-4 text-[#2786C2]" /> AI Agent
                                </span>
                                <span className="text-xs text-[#778DA9]">บอกเป้าหมาย ให้ AI ออกแบบให้</span>
                            </button>
                            <button
                                onClick={() => setCreateMode("manual")}
                                className={`flex flex-col items-start gap-1 p-3 rounded-lg border text-left transition-colors ${createMode === "manual" ? "border-[#2786C2] bg-[#EBF4FB]" : "border-[#E2E8F0] hover:bg-gray-50"}`}
                            >
                                <span className="flex items-center gap-1.5 font-medium text-sm text-[#0D1B2A]">
                                    <PencilRuler className="h-4 w-4 text-[#2786C2]" /> Manual
                                </span>
                                <span className="text-xs text-[#778DA9]">ลาก & วางโหนดเอง</span>
                            </button>
                        </div>

                        {createMode === "manual" && (
                            <>
                                <label className="block text-sm text-[#0D1B2A] mb-1">ชื่อ Workflow *</label>
                                <input
                                    autoFocus
                                    value={newName}
                                    onChange={(e) => setNewName(e.target.value)}
                                    placeholder="เช่น สรุปใบเสนอราคารายวัน"
                                    className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm mb-3 focus:outline-none focus:ring-2 focus:ring-[#2786C2]/30"
                                />
                                <label className="block text-sm text-[#0D1B2A] mb-1">คำอธิบาย</label>
                                <textarea
                                    value={newDescription}
                                    onChange={(e) => setNewDescription(e.target.value)}
                                    rows={2}
                                    className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm mb-4 focus:outline-none focus:ring-2 focus:ring-[#2786C2]/30"
                                />
                            </>
                        )}
                        {createMode === "ai" && (
                            <p className="text-sm text-[#778DA9] mb-4">
                                จะเปิดหน้าแชทกับ AI — พิมพ์เป้าหมาย เช่น “ทุกเช้าดึงใบเสร็จจาก Job แล้วสรุปด้วย AI ส่งเข้า Google Drive” แล้ว AI จะออกแบบ workflow ให้ พร้อมถามข้อมูลที่จำเป็น
                            </p>
                        )}

                        <div className="flex justify-end gap-2">
                            <button onClick={() => setShowCreate(false)} className="px-4 py-2 rounded-lg text-sm text-[#778DA9] hover:bg-gray-50">
                                ยกเลิก
                            </button>
                            <button
                                onClick={handleCreate}
                                disabled={creating || (createMode === "manual" && !newName.trim())}
                                className="px-4 py-2 rounded-lg bg-[#2786C2] text-white text-sm hover:bg-[#1F6FA3] disabled:opacity-50 flex items-center gap-2"
                            >
                                {creating && <Loader2 className="h-4 w-4 animate-spin" />}
                                {createMode === "ai" ? "เริ่มกับ AI Agent" : "สร้างและเปิด Builder"}
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}
