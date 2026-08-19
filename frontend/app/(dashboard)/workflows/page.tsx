"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import {
    Plus, Play, Trash2, Pencil, CalendarClock, Loader2, Workflow as WorkflowIcon,
    CheckCircle2, XCircle, Clock, Sparkles, PencilRuler, Download, Upload, LayoutGrid, Table2,
} from "lucide-react"
import {
    Workflow, getWorkflows, createWorkflow, deleteWorkflow, runWorkflow, updateWorkflow,
    exportWorkflow, importWorkflow, downloadWorkflowJson, WorkflowExport,
} from "@/lib/workflows-api"

const statusBadge = (wf: Workflow) => {
    if (!wf.is_active) return <span className="px-2 py-0.5 rounded-full text-xs bg-gray-100 text-gray-500">Inactive</span>
    return <span className="px-2 py-0.5 rounded-full text-xs bg-emerald-50 text-emerald-600">Active</span>
}

const WORKFLOWS_PAGE_SIZE = 10

export default function WorkflowsPage() {
    const router = useRouter()
    const token = typeof window !== "undefined" ? localStorage.getItem("token") : null

    const [workflows, setWorkflows] = useState<Workflow[]>([])
    const [visibleWorkflowCount, setVisibleWorkflowCount] = useState(WORKFLOWS_PAGE_SIZE)
    const [viewMode, setViewMode] = useState<"cards" | "table">("cards")
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
            setVisibleWorkflowCount(WORKFLOWS_PAGE_SIZE)
            setError(null)
        } catch (e: unknown) {
            setError(e instanceof Error ? e.message : "Failed to load workflows")
        } finally {
            setLoading(false)
        }
    }, [token])

    useEffect(() => { load() }, [load])

    useEffect(() => {
        const savedViewMode = window.localStorage.getItem("workflows-view-mode")
        if (savedViewMode === "cards" || savedViewMode === "table") {
            setViewMode(savedViewMode)
        }
    }, [])

    const changeViewMode = (mode: "cards" | "table") => {
        setViewMode(mode)
        window.localStorage.setItem("workflows-view-mode", mode)
    }

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
        } catch (e: unknown) {
            setError(e instanceof Error ? e.message : "Failed to create workflow")
            setCreating(false)
        }
    }

    const handleExport = async (wf: Workflow) => {
        if (!token) return
        try {
            const data = await exportWorkflow(token, wf.id)
            downloadWorkflowJson(data)
        } catch (e: unknown) {
            setNotice(`Export failed: ${e instanceof Error ? e.message : "Unknown error"}`)
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
        } catch (e: unknown) {
            setNotice(`Import failed: ${e instanceof Error ? e.message : "Unknown error"}`)
            setImporting(false)
        }
    }

    const handleRun = async (wf: Workflow) => {
        if (!token) return
        try {
            setRunningId(wf.id)
            const run = await runWorkflow(token, wf.id)
            router.push(`/workflows/${wf.id}?run=${run.id}`)
        } catch (e: unknown) {
            setNotice(`Run failed: ${e instanceof Error ? e.message : "Unknown error"}`)
            setRunningId(null)
        }
    }

    const handleDelete = async (wf: Workflow) => {
        if (!token) return
        if (!confirm(`ลบ workflow "${wf.name}" และประวัติการรันทั้งหมด?`)) return
        try {
            await deleteWorkflow(token, wf.id)
            setWorkflows((prev) => prev.filter((w) => w.id !== wf.id))
        } catch (e: unknown) {
            setNotice(`Delete failed: ${e instanceof Error ? e.message : "Unknown error"}`)
        }
    }

    const toggleActive = async (wf: Workflow) => {
        if (!token) return
        try {
            const updated = await updateWorkflow(token, wf.id, { is_active: !wf.is_active })
            setWorkflows((prev) => prev.map((w) => (w.id === wf.id ? updated : w)))
        } catch (e: unknown) {
            setNotice(`Update failed: ${e instanceof Error ? e.message : "Unknown error"}`)
        }
    }

    const visibleWorkflows = workflows.slice(0, visibleWorkflowCount)
    const hasMoreWorkflows = visibleWorkflowCount < workflows.length

    return (
        <div className="w-full min-w-0 max-w-6xl mx-auto overflow-hidden">
            <div className="mb-6 flex min-w-0 flex-wrap items-center justify-between gap-3">
                <div className="min-w-0 flex-1">
                    <h1 className="text-2xl font-bold text-[#0D1B2A] flex items-center gap-2">
                        <WorkflowIcon className="h-6 w-6 text-[#2786C2]" /> Workflow
                    </h1>
                    <p className="text-sm text-[#778DA9] mt-1">
                        สร้าง automation process สำหรับเอกสารแบบ drag & drop — รันเองหรือตั้งเวลาอัตโนมัติ
                    </p>
                </div>
                <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
                    <div className="flex items-center rounded-lg border border-[#CBD5E1] bg-white p-1" role="group" aria-label="Workflow view">
                        <button
                            type="button"
                            aria-label="Card view"
                            aria-pressed={viewMode === "cards"}
                            title="Card view"
                            onClick={() => changeViewMode("cards")}
                            className={`inline-flex h-8 items-center gap-2 rounded px-2.5 text-sm transition-colors ${viewMode === "cards" ? "bg-[#EBF4FB] text-[#1F6FA3]" : "text-[#778DA9] hover:text-[#0D1B2A]"}`}
                        >
                            <LayoutGrid className="h-4 w-4" />
                            <span className="hidden sm:inline">Cards</span>
                        </button>
                        <button
                            type="button"
                            aria-label="Table view"
                            aria-pressed={viewMode === "table"}
                            title="Table view"
                            onClick={() => changeViewMode("table")}
                            className={`inline-flex h-8 items-center gap-2 rounded px-2.5 text-sm transition-colors ${viewMode === "table" ? "bg-[#EBF4FB] text-[#1F6FA3]" : "text-[#778DA9] hover:text-[#0D1B2A]"}`}
                        >
                            <Table2 className="h-4 w-4" />
                            <span className="hidden sm:inline">Table</span>
                        </button>
                    </div>
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
                <>
                    {viewMode === "table" ? (
                        <div className="max-w-full overflow-hidden rounded-xl border border-[#E2E8F0] bg-white shadow-sm">
                            <div className="max-w-full overflow-x-auto">
                                <table className="w-full min-w-[960px] table-fixed text-sm">
                                    <caption className="sr-only">Automation workflows</caption>
                                    <colgroup>
                                        <col className="w-[32%]" />
                                        <col className="w-[10%]" />
                                        <col className="w-[14%]" />
                                        <col className="w-[8%]" />
                                        <col className="w-[17%]" />
                                        <col className="w-[19%]" />
                                    </colgroup>
                                    <thead className="border-b border-[#E2E8F0] bg-[#F8FAFC] text-left text-xs uppercase tracking-wide text-[#778DA9]">
                                        <tr>
                                            <th scope="col" className="px-5 py-3 font-semibold">Workflow</th>
                                            <th scope="col" className="px-5 py-3 font-semibold">Status</th>
                                            <th scope="col" className="px-5 py-3 font-semibold">Schedule</th>
                                            <th scope="col" className="px-5 py-3 font-semibold">Nodes</th>
                                            <th scope="col" className="px-5 py-3 font-semibold">Last run</th>
                                            <th scope="col" className="px-5 py-3 text-right font-semibold">Actions</th>
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y divide-[#E2E8F0]">
                                        {visibleWorkflows.map((wf) => (
                                            <tr key={wf.id} className="transition-colors hover:bg-[#F8FAFC]">
                                                <td className="min-w-0 overflow-hidden px-5 py-4">
                                                    <button type="button" onClick={() => router.push(`/workflows/${wf.id}`)} className="block w-full min-w-0 overflow-hidden text-left">
                                                        <span className="block truncate font-semibold text-[#0D1B2A]" title={wf.name}>{wf.name}</span>
                                                        {wf.description && <span className="mt-0.5 block truncate text-sm text-[#778DA9]" title={wf.description}>{wf.description}</span>}
                                                    </button>
                                                </td>
                                                <td className="whitespace-nowrap px-5 py-4">{statusBadge(wf)}</td>
                                                <td className="min-w-0 overflow-hidden whitespace-nowrap px-5 py-4 text-[#778DA9]">
                                                    {wf.schedule_enabled && wf.schedule_cron ? (
                                                        <span className="inline-flex max-w-full items-center gap-1 truncate text-[#2786C2]" title={wf.schedule_cron}>
                                                            <CalendarClock className="h-3.5 w-3.5" /> {wf.schedule_cron}
                                                        </span>
                                                    ) : "-"}
                                                </td>
                                                <td className="whitespace-nowrap px-5 py-4 text-[#778DA9]">{(wf.definition?.nodes || []).length}</td>
                                                <td className="min-w-0 overflow-hidden whitespace-nowrap px-5 py-4 text-[#778DA9]">
                                                    {wf.last_run_at ? (
                                                        <span className="inline-flex max-w-full items-center gap-1 truncate" title={new Date(wf.last_run_at).toLocaleString()}>
                                                            <Clock className="h-3.5 w-3.5" /> {new Date(wf.last_run_at).toLocaleString()}
                                                        </span>
                                                    ) : "-"}
                                                </td>
                                                <td className="px-4 py-4">
                                                    <div className="flex justify-end gap-0.5">
                                                        <button type="button" onClick={() => handleRun(wf)} disabled={runningId === wf.id || !wf.is_active} title="Run now" aria-label={`Run ${wf.name} now`} className="rounded-lg p-2 text-emerald-600 hover:bg-emerald-50 disabled:opacity-40">
                                                            {runningId === wf.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                                                        </button>
                                                        <button type="button" onClick={() => router.push(`/workflows/${wf.id}`)} title="Edit" aria-label={`Edit ${wf.name}`} className="rounded-lg p-2 text-[#2786C2] hover:bg-[#EBF4FB]"><Pencil className="h-4 w-4" /></button>
                                                        <button type="button" onClick={() => handleExport(wf)} title="Export JSON" aria-label={`Export ${wf.name}`} className="rounded-lg p-2 text-[#778DA9] hover:bg-gray-50"><Download className="h-4 w-4" /></button>
                                                        <button type="button" onClick={() => toggleActive(wf)} title={wf.is_active ? "Deactivate" : "Activate"} aria-label={`${wf.is_active ? "Deactivate" : "Activate"} ${wf.name}`} className="rounded-lg p-2 hover:bg-gray-50">
                                                            {wf.is_active ? <CheckCircle2 className="h-4 w-4 text-emerald-500" /> : <XCircle className="h-4 w-4 text-gray-400" />}
                                                        </button>
                                                        <button type="button" onClick={() => handleDelete(wf)} title="Delete" aria-label={`Delete ${wf.name}`} className="rounded-lg p-2 text-red-500 hover:bg-red-50"><Trash2 className="h-4 w-4" /></button>
                                                    </div>
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    ) : (
                        <div className="grid min-w-0 gap-3">
                            {visibleWorkflows.map((wf) => (
                                <div key={wf.id} className="flex w-full min-w-0 max-w-full items-center gap-3 overflow-hidden rounded-xl border border-[#E2E8F0] bg-white px-4 py-4 transition-shadow hover:shadow-sm sm:gap-4 sm:px-5">
                                    <div className="min-w-0 flex-1 cursor-pointer overflow-hidden" onClick={() => router.push(`/workflows/${wf.id}`)}>
                                        <div className="flex min-w-0 items-center gap-2 overflow-hidden">
                                            <span className="min-w-0 flex-1 truncate font-semibold text-[#0D1B2A]" title={wf.name}>{wf.name}</span>
                                            {statusBadge(wf)}
                                            {wf.schedule_enabled && wf.schedule_cron && (
                                                <span className="hidden max-w-[180px] shrink-0 items-center gap-1 truncate rounded-full bg-[#EBF4FB] px-2 py-0.5 text-xs text-[#2786C2] sm:flex" title={wf.schedule_cron}>
                                                    <CalendarClock className="h-3 w-3" /> {wf.schedule_cron}
                                                </span>
                                            )}
                                        </div>
                                        {wf.description && <p className="mt-0.5 truncate text-sm text-[#778DA9]" title={wf.description}>{wf.description}</p>}
                                        <p className="mt-1 flex items-center gap-3 text-xs text-[#9AA8BC]">
                                            <span>{(wf.definition?.nodes || []).length} nodes</span>
                                            {wf.last_run_at && <span className="flex items-center gap-1"><Clock className="h-3 w-3" /> last run {new Date(wf.last_run_at).toLocaleString()}</span>}
                                        </p>
                                    </div>
                                    <div className="flex shrink-0 items-center gap-0.5 sm:gap-1">
                                        <button type="button" onClick={() => handleRun(wf)} disabled={runningId === wf.id || !wf.is_active} title="Run now" aria-label={`Run ${wf.name} now`} className="rounded-lg p-2 text-emerald-600 hover:bg-emerald-50 disabled:opacity-40">{runningId === wf.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}</button>
                                        <button type="button" onClick={() => router.push(`/workflows/${wf.id}`)} title="Edit" aria-label={`Edit ${wf.name}`} className="rounded-lg p-2 text-[#2786C2] hover:bg-[#EBF4FB]"><Pencil className="h-4 w-4" /></button>
                                        <button type="button" onClick={() => handleExport(wf)} title="Export JSON" aria-label={`Export ${wf.name}`} className="rounded-lg p-2 text-[#778DA9] hover:bg-gray-50"><Download className="h-4 w-4" /></button>
                                        <button type="button" onClick={() => toggleActive(wf)} title={wf.is_active ? "Deactivate" : "Activate"} aria-label={`${wf.is_active ? "Deactivate" : "Activate"} ${wf.name}`} className="rounded-lg p-2 hover:bg-gray-50">{wf.is_active ? <CheckCircle2 className="h-4 w-4 text-emerald-500" /> : <XCircle className="h-4 w-4 text-gray-400" />}</button>
                                        <button type="button" onClick={() => handleDelete(wf)} title="Delete" aria-label={`Delete ${wf.name}`} className="rounded-lg p-2 text-red-500 hover:bg-red-50"><Trash2 className="h-4 w-4" /></button>
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                    <div className="mt-5 flex flex-col items-center gap-2">
                        {hasMoreWorkflows && (
                            <button
                                type="button"
                                onClick={() => setVisibleWorkflowCount((count) => Math.min(count + WORKFLOWS_PAGE_SIZE, workflows.length))}
                                className="rounded-lg border border-[#CBD5E1] bg-white px-4 py-2 text-sm font-medium text-[#0D1B2A] hover:bg-gray-50"
                            >
                                Load more
                            </button>
                        )}
                        <p className="text-sm text-[#778DA9]">
                            Showing {visibleWorkflows.length} of {workflows.length} workflows
                        </p>
                    </div>
                </>
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
