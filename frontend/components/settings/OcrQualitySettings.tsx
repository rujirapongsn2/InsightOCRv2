"use client"

import { useEffect, useState } from "react"
import { Loader2, Save } from "lucide-react"
import { getApiBaseUrl } from "@/lib/api"

type Stats = { days: number; available: boolean; scored?: number; low_quality?: number; escalated?: number; auto_review_held?: number }
type Policy = {
    routing: boolean
    jev: boolean
    jev_configured: boolean
    softnix_configured: boolean
    thresholds: { good_confidence: number; poor_confidence: number; max_low_lines: number; field_min_confidence: number; jev_threshold: number }
    stats: Stats
}

export function OcrQualitySettings() {
    const [policy, setPolicy] = useState<Policy | null>(null)
    const [routing, setRouting] = useState(false)
    const [jev, setJev] = useState(false)
    const [busy, setBusy] = useState(false)
    const [message, setMessage] = useState("")
    const url = `${getApiBaseUrl()}/settings/ocr-quality`
    const headers = () => ({ Authorization: `Bearer ${localStorage.getItem("token")}`, "Content-Type": "application/json" })

    const apply = (data: Policy) => {
        setPolicy(data)
        setRouting(data.routing)
        setJev(data.jev)
    }

    useEffect(() => {
        const abort = new AbortController()
        fetch(url, { headers: headers(), signal: abort.signal })
            .then(async (response) => { if (!response.ok) throw new Error("โหลดการตั้งค่าคุณภาพ OCR ไม่สำเร็จ"); return response.json() })
            .then(apply)
            .catch((error) => { if (!abort.signal.aborted) setMessage(error.message) })
        return () => abort.abort()
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [url])

    async function save() {
        setBusy(true)
        setMessage("")
        try {
            const response = await fetch(url, { method: "PUT", headers: headers(), body: JSON.stringify({ routing, jev }) })
            const data = await response.json().catch(() => ({}))
            if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "บันทึกไม่สำเร็จ")
            apply(data)
            setMessage("บันทึกแล้ว มีผลกับเอกสารที่ประมวลผลหลังจากนี้")
        } catch (error) {
            setMessage(error instanceof Error ? error.message : "บันทึกไม่สำเร็จ")
        } finally {
            setBusy(false)
        }
    }

    if (!policy) return <p className="text-sm text-slate-500">{message || "กำลังโหลด..."}</p>

    const dirty = routing !== policy.routing || jev !== policy.jev
    const t = policy.thresholds
    const stats = policy.stats

    return <section className="space-y-4">
        <div className="rounded-md border bg-slate-50 p-3 text-sm text-slate-700">
            <p className="font-medium">ระบบให้คะแนนทุกหน้าที่ Tesseract อ่านอยู่แล้ว</p>
            <p className="mt-1 text-xs text-slate-600">
                หน้าที่ความมั่นใจเฉลี่ยต่ำกว่า {t.poor_confidence} หรือมีบรรทัดที่อ่านไม่ชัดตั้งแต่ {t.max_low_lines} บรรทัดขึ้นไป ถือว่าคุณภาพต่ำ
                ค่าที่ดึงจากคำที่ความมั่นใจต่ำกว่า {t.field_min_confidence} และเลข 13 หลักที่ checksum ไม่ผ่าน จะถูกส่งไปตรวจทานเสมอ
                และเอกสารที่มีฟิลด์รอตรวจหรือหน้าคุณภาพต่ำจะไม่ถูกยืนยันอัตโนมัติ
            </p>
            {stats.available && (
                <p className="mt-2 text-xs tabular-nums text-slate-700">
                    {stats.days} วันที่ผ่านมา: ให้คะแนนแล้ว {stats.scored} เอกสาร · คุณภาพต่ำ {stats.low_quality} · ส่งต่อ OCR แล้ว {stats.escalated} · งดยืนยันอัตโนมัติ {stats.auto_review_held}
                </p>
            )}
        </div>

        <label className="flex items-start gap-3 text-sm">
            <input id="ocr-quality-routing" type="checkbox" className="mt-1 h-4 w-4" checked={routing} disabled={busy} onChange={(event) => setRouting(event.target.checked)} />
            <span>
                <span className="font-medium">ส่งหน้าที่คุณภาพต่ำให้ OCR ตัวถัดไปอ่านใหม่</span>
                <span className="block text-xs text-slate-600">
                    ใช้ Softnix OCR หรือ OCR สำรองอ่านหน้านั้นใหม่ ถ้าอ่านไม่ได้จะใช้ข้อความเดิมต่อ · ปิดอยู่ = บันทึกผลอย่างเดียว ไม่เปลี่ยนข้อความ
                    {!policy.softnix_configured && " · ยังไม่ได้ตั้งค่า Softnix OCR จะใช้ OCR สำรองแทน (ถ้าเปิดไว้)"}
                </span>
                {routing && <span className="block text-xs text-amber-700">มีค่าใช้จ่ายของ OCR ตัวถัดไปเฉพาะหน้าที่ถูกส่งต่อ ดูจำนวนหน้าคุณภาพต่ำด้านบนเพื่อประเมินได้</span>}
            </span>
        </label>

        <label className="flex items-start gap-3 text-sm">
            <input id="ocr-quality-jev" type="checkbox" className="mt-1 h-4 w-4" checked={jev} disabled={busy || !policy.jev_configured} onChange={(event) => setJev(event.target.checked)} />
            <span>
                <span className="font-medium">ให้ Jev ช่วยตัดสินหน้าที่ก้ำกึ่ง</span>
                <span className="block text-xs text-slate-600">
                    หน้าที่ความมั่นใจอยู่ระหว่าง {t.poor_confidence}–{t.good_confidence} จะถาม Jev ว่าข้อความอ่านได้ถูกต้องหรือไม่ (ผ่านเมื่อโอกาส ≥ {t.jev_threshold})
                    ใช้ร่วมกับตัวเลือกด้านบนจึงจะส่งหน้าไปอ่านใหม่ได้
                </span>
                {!policy.jev_configured && <span className="block text-xs text-amber-700">ต้องตั้งค่า TypeSafe (Jev) ด้านล่างก่อน</span>}
            </span>
        </label>

        <div className="flex flex-wrap items-center gap-3">
            <button type="button" onClick={save} disabled={busy || !dirty} className="inline-flex items-center gap-1 rounded border px-3 py-2 text-sm disabled:opacity-50">
                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}บันทึกการตั้งค่าคุณภาพ OCR{dirty ? " •" : ""}
            </button>
            {message && <p role="status" className="text-sm text-slate-700">{message}</p>}
        </div>
    </section>
}
