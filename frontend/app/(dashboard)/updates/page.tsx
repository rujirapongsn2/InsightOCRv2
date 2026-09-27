"use client"

import { useEffect, useMemo, useState } from "react"
import { ChevronDown, ChevronRight, Loader2, MapPin } from "lucide-react"

// Release notes are written per commit into public/updates.json (newest first).
type UpdateType = "feature" | "improvement" | "fix" | "security" | "maintenance"

interface UpdateEntry {
    commit: string
    date: string
    type: UpdateType
    title: string
    what: string
    benefit: string
    where: string
}

const PAGE_SIZE = 50

const TYPE_STYLE: Record<UpdateType, { label: string; className: string }> = {
    feature: { label: "ฟีเจอร์ใหม่", className: "bg-[#EBF4FB] text-[#2786C2]" },
    improvement: { label: "ปรับปรุง", className: "bg-emerald-50 text-emerald-700" },
    fix: { label: "แก้ไข", className: "bg-amber-50 text-amber-800" },
    security: { label: "ความปลอดภัย", className: "bg-red-50 text-red-700" },
    maintenance: { label: "ดูแลระบบ", className: "bg-slate-100 text-slate-600" },
}

function formatDate(value: string): string {
    const date = new Date(`${value}T00:00:00`)
    if (Number.isNaN(date.getTime())) return value
    return date.toLocaleDateString("th-TH", { year: "numeric", month: "short", day: "numeric" })
}

export default function UpdatesPage() {
    const [entries, setEntries] = useState<UpdateEntry[] | null>(null)
    const [error, setError] = useState<string | null>(null)
    const [visible, setVisible] = useState(PAGE_SIZE)
    const [open, setOpen] = useState<Set<string>>(new Set())

    useEffect(() => {
        fetch("/updates.json", { cache: "no-store" })
            .then(async (res) => {
                if (!res.ok) throw new Error("โหลดรายการอัปเดตไม่สำเร็จ")
                return res.json()
            })
            .then((data: UpdateEntry[]) => setEntries(Array.isArray(data) ? data : []))
            .catch((err: unknown) => setError(err instanceof Error ? err.message : "โหลดรายการอัปเดตไม่สำเร็จ"))
    }, [])

    const shown = useMemo(() => (entries || []).slice(0, visible), [entries, visible])

    const toggle = (commit: string) => {
        setOpen((current) => {
            const next = new Set(current)
            if (next.has(commit)) next.delete(commit)
            else next.add(commit)
            return next
        })
    }

    return (
        <div className="mx-auto max-w-3xl space-y-6">
            <div>
                <h2 className="text-2xl font-bold tracking-tight">Update</h2>
                <p className="mt-1 text-sm text-slate-500">
                    สิ่งที่เปลี่ยนในระบบ เรียงจากล่าสุด กดที่หัวข้อเพื่อดูว่าคืออะไร มีประโยชน์อย่างไร และอยู่ตรงไหน
                </p>
            </div>

            {error && <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
            {!entries && !error && (
                <p className="flex items-center gap-2 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" />กำลังโหลด...</p>
            )}
            {entries && entries.length === 0 && <p className="text-sm text-slate-500">ยังไม่มีรายการอัปเดต</p>}

            {shown.length > 0 && (
                <ul className="divide-y divide-[#E2E8F0] overflow-hidden rounded-xl border border-[#E2E8F0] bg-white">
                    {shown.map((entry) => {
                        const isOpen = open.has(entry.commit)
                        const style = TYPE_STYLE[entry.type] || TYPE_STYLE.maintenance
                        const panelId = `update-${entry.commit}`
                        return (
                            <li key={entry.commit}>
                                <button
                                    type="button"
                                    onClick={() => toggle(entry.commit)}
                                    aria-expanded={isOpen}
                                    aria-controls={panelId}
                                    className="flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-[#F8F9FA] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#2786C2]"
                                >
                                    {isOpen
                                        ? <ChevronDown className="mt-0.5 h-4 w-4 shrink-0 text-[#778DA9]" />
                                        : <ChevronRight className="mt-0.5 h-4 w-4 shrink-0 text-[#778DA9]" />}
                                    <span className="min-w-0 flex-1">
                                        <span className="block text-sm font-medium text-[#0D1B2A]">{entry.title}</span>
                                        <span className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                                            <span className={`rounded-full px-2 py-0.5 font-medium ${style.className}`}>{style.label}</span>
                                            <span>{formatDate(entry.date)}</span>
                                            <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-600">{entry.commit}</code>
                                        </span>
                                    </span>
                                </button>
                                {isOpen && (
                                    <div id={panelId} className="space-y-3 border-t border-[#F1F5F9] bg-[#FBFCFD] px-11 py-3 text-sm leading-6 text-slate-700">
                                        <div>
                                            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">คืออะไร</p>
                                            <p>{entry.what}</p>
                                        </div>
                                        <div>
                                            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">มีประโยชน์อย่างไร</p>
                                            <p>{entry.benefit}</p>
                                        </div>
                                        <div>
                                            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">อยู่ตรงไหน</p>
                                            <p className="flex items-start gap-1.5"><MapPin className="mt-1 h-3.5 w-3.5 shrink-0 text-[#2786C2]" />{entry.where}</p>
                                        </div>
                                    </div>
                                )}
                            </li>
                        )
                    })}
                </ul>
            )}

            {entries && visible < entries.length && (
                <div className="flex flex-col items-center gap-1">
                    <button
                        type="button"
                        onClick={() => setVisible((count) => count + PAGE_SIZE)}
                        className="rounded-lg border border-[#E2E8F0] bg-white px-4 py-2 text-sm font-medium text-[#2786C2] hover:bg-[#EBF4FB]"
                    >
                        Load more
                    </button>
                    <span className="text-xs text-slate-500">แสดง {shown.length} จาก {entries.length} รายการ</span>
                </div>
            )}
        </div>
    )
}
