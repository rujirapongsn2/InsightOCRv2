"use client"

import { useEffect, useRef, useState } from "react"
import { AlertTriangle, Check, RefreshCw, Search } from "lucide-react"
import { getApiBaseUrl } from "@/lib/api"

type Evidence = { status?: string; reason?: string; quote?: string; raw_text?: string; page?: number; retained_previous_value?: boolean;
    alternative?: { value: unknown; provider: string; grounded?: boolean };
    bbox?: { x: number; y: number; width: number; height: number };
    lx_candidate?: { value?: unknown }; upgraded_from_conflict?: boolean }
export type MappingReport = { status?: string; fields?: Record<string, Evidence>; attempts?: unknown[]; unresolved_fields?: string[] }

export type MappingResult = { mapping?: MappingReport; values?: Record<string, unknown> }

/** Run a mapping retry (whole document or selected fields) and wait for it. */
export async function runMappingRetry(documentId: string, engine: string, fields?: string[], signal?: AbortSignal): Promise<MappingResult> {
    const headers = { Authorization: `Bearer ${localStorage.getItem("token")}`, "Content-Type": "application/json" }
    const url = `${getApiBaseUrl()}/documents/${documentId}`
    const response = await fetch(`${url}/retry-mapping`, {
        method: "POST", headers, signal,
        body: JSON.stringify({ engine, ...(fields?.length ? { fields } : {}) }),
    })
    if (!response.ok) throw new Error((await response.json()).detail || "Mapping retry failed")
    const started = Date.now()
    while (!signal?.aborted && Date.now() - started < 600_000) {
        await new Promise<void>((resolve) => {
            const timer = setTimeout(() => { signal?.removeEventListener("abort", done); resolve() }, 2000)
            const done = () => { clearTimeout(timer); resolve() }
            signal?.addEventListener("abort", done, { once: true })
        })
        if (signal?.aborted) throw new Error("aborted")
        const result = await fetch(url, { headers, signal })
        if (!result.ok) throw new Error("Unable to retrieve mapping status")
        const doc = await result.json()
        if (!["queued", "processing"].includes(doc.status)) {
            if (doc.extraction_metadata?.mapping_retry?.status === "failed") {
                throw new Error(doc.processing_error || "Mapping retry failed")
            }
            return { mapping: doc.extraction_metadata?.mapping, values: doc.extracted_data || {} }
        }
    }
    throw new Error("Still processing. Reopen Preview to check the result.")
}

const STATUS_LABELS: Record<string, string> = {
    source_matched: "Source matched", needs_review: "Needs review",
    missing: "Not returned", failed: "Failed",
}

export function MappingPanel({ documentId, report, onEvidence, onProposal, onReport, engine, onEngineChange }: {
    documentId: string; report?: MappingReport;
    onEvidence: (name: string, evidence: Evidence) => void;
    onProposal: (values: Record<string, unknown>) => void;
    onReport?: (report: MappingReport | undefined) => void;
    engine: string;
    onEngineChange: (engine: string) => void;
}) {
    const [busy, setBusy] = useState(false)
    const [error, setError] = useState("")
    const [latest, setLatest] = useState(report)
    const [summary, setSummary] = useState<{ updated: number; review: number } | null>(null)
    const controller = useRef<AbortController | null>(null)
    useEffect(() => () => controller.current?.abort(), [])

    async function applyResult(result: MappingResult) {
        setLatest(result.mapping)
        onReport?.(result.mapping)
        const values = result.values || {}
        onProposal(values)
        const reviewCount = Object.values(result.mapping?.fields || {})
            .filter((item) => (item?.status || "needs_review") === "needs_review").length
        setSummary({ updated: Object.keys(values).length, review: reviewCount })
    }

    async function retry(field?: string) {
        setBusy(true); setError(""); setSummary(null)
        const abort = new AbortController()
        controller.current = abort
        try {
            const result = await runMappingRetry(documentId, engine, field ? [field] : undefined, abort.signal)
            if (!abort.signal.aborted) await applyResult(result)
        } catch (e) {
            if (!abort.signal.aborted) setError(e instanceof Error && e.message !== "aborted" ? e.message : "")
        } finally {
            if (!abort.signal.aborted) setBusy(false)
        }
    }

    return <div className="mb-3 shrink-0 space-y-2 text-xs">
        <div className="flex flex-wrap items-end gap-2">
            <label className="space-y-1 text-slate-600">Mapping engine
                <select aria-label="Mapping engine" value={engine} disabled={busy} onChange={e => onEngineChange(e.target.value)} className="block h-8 rounded border bg-white px-2">
                    <option value="auto">Auto</option><option value="softnix">Softnix Structured</option>
                    <option value="jev">TypeSafe Jev</option>
                    <option value="lx">LangExtract (grounded)</option>
                    <option value="llm">Configured LLM provider</option><option value="fixed">Fixed position only</option>
                </select>
            </label>
            <button type="button" disabled={busy} onClick={() => retry()} className="inline-flex h-8 items-center gap-1 rounded border px-2 disabled:opacity-50">
                <RefreshCw className={`h-3.5 w-3.5 ${busy ? "animate-spin" : ""}`} />{busy ? "Mapping..." : "Retry Mapping"}
            </button>
        </div>
        {error && <p role="alert" className="text-red-700">{error}</p>}
        {summary && <p role="status" className="rounded border border-emerald-200 bg-emerald-50 px-2 py-1 text-emerald-800">
            อัปเดต {summary.updated} ฟิลด์เข้าตัวแก้ไขแล้ว · รอตรวจ {summary.review} รายการ
        </p>}
        {latest?.fields && <details className="rounded border p-2">
            <summary className="cursor-pointer font-medium">Field evidence</summary>
            <div className="max-h-56 space-y-2 overflow-auto pt-2">
                {Object.entries(latest.fields).map(([name, item]) => <div key={name} className="border-t pt-2">
                    <div className="flex flex-wrap items-center gap-2">
                        <span className="font-medium break-all">{name}</span>
                        <span className={`inline-flex items-center gap-1 ${item.status === "source_matched" ? "text-blue-700" : "text-amber-700"}`}>
                            {item.status === "source_matched" ? <Check className="h-3 w-3" /> : <AlertTriangle className="h-3 w-3" />}
                            {({ source_matched: "Source matched", needs_review: "Needs review", missing: "Not returned", failed: "Failed" } as Record<string, string>)[item.status || ""] || "Needs review"}
                        </span>
                        {(item.page || item.bbox || item.quote || item.raw_text || item.status === "source_matched") &&
                            <button type="button" title="Show where this value is in the document" aria-label={`Show evidence for ${name}`} onClick={() => onEvidence(name, item)}><Search className="h-4 w-4" /></button>}
                        <button type="button" disabled={busy} title="Retry this field" aria-label={`Retry mapping ${name}`} onClick={() => retry(name)}><RefreshCw className="h-3.5 w-3.5" /></button>
                    </div>
                    <p className="mt-1 text-slate-500">{item.reason}</p>
                    {item.retained_previous_value && <p className="text-amber-700">Previous value retained</p>}
                    {item.alternative && <details><summary className="cursor-pointer text-amber-700">Conflicting value</summary><pre className="max-h-32 overflow-auto whitespace-pre-wrap break-all">{JSON.stringify(item.alternative.value, null, 2)}</pre></details>}
                    {(item.quote || item.raw_text) && <blockquote className="mt-1 whitespace-pre-wrap break-words border-l-2 pl-2">{item.quote || item.raw_text}</blockquote>}
                </div>)}
            </div>
        </details>}
    </div>
}
