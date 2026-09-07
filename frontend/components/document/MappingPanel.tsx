"use client"

import { useEffect, useRef, useState } from "react"
import { AlertTriangle, Check, RefreshCw, Search } from "lucide-react"
import { getApiBaseUrl } from "@/lib/api"

type Evidence = { status?: string; reason?: string; quote?: string; raw_text?: string; page?: number; retained_previous_value?: boolean;
    alternative?: { value: unknown; provider: string };
    bbox?: { x: number; y: number; width: number; height: number } }
export type MappingReport = { status?: string; fields?: Record<string, Evidence>; attempts?: unknown[] }

export function MappingPanel({ documentId, report, onEvidence, onProposal }: {
    documentId: string; report?: MappingReport;
    onEvidence: (evidence: Evidence) => void;
    onProposal: (values: Record<string, unknown>) => void;
}) {
    const [engine, setEngine] = useState("auto")
    const [busy, setBusy] = useState(false)
    const [error, setError] = useState("")
    const [latest, setLatest] = useState(report)
    const [proposal, setProposal] = useState<Record<string, unknown> | null>(null)
    const controller = useRef<AbortController | null>(null)
    useEffect(() => () => controller.current?.abort(), [])

    async function retry(field?: string) {
        setBusy(true); setError(""); setProposal(null)
        const abort = new AbortController()
        controller.current = abort
        const headers = { Authorization: `Bearer ${localStorage.getItem("token")}`, "Content-Type": "application/json" }
        const url = `${getApiBaseUrl()}/documents/${documentId}`
        try {
            const response = await fetch(`${url}/retry-mapping`, {
                method: "POST", headers, signal: abort.signal,
                body: JSON.stringify({ engine, ...(field ? { fields: [field] } : {}) }),
            })
            if (!response.ok) throw new Error((await response.json()).detail || "Mapping retry failed")
            const started = Date.now()
            while (!abort.signal.aborted && Date.now() - started < 600_000) {
                await new Promise<void>((resolve) => {
                    const done = () => { clearTimeout(timer); abort.signal.removeEventListener("abort", done); resolve() }
                    const timer = setTimeout(done, 2000)
                    abort.signal.addEventListener("abort", done, { once: true })
                })
                if (abort.signal.aborted) return
                const result = await fetch(url, { headers, signal: abort.signal })
                if (!result.ok) throw new Error("Unable to retrieve mapping status")
                const doc = await result.json()
                if (!["queued", "processing"].includes(doc.status)) {
                    setLatest(doc.extraction_metadata?.mapping)
                    if (doc.extraction_metadata?.mapping_retry?.status === "failed") {
                        throw new Error(doc.processing_error || "Mapping retry failed")
                    }
                    setProposal(doc.extracted_data || {})
                    return
                }
            }
            if (!abort.signal.aborted) setError("Still processing. Reopen Preview to check the result.")
        } catch (e) {
            if (!abort.signal.aborted) setError(e instanceof Error ? e.message : "Mapping retry failed")
        } finally {
            if (!abort.signal.aborted) setBusy(false)
        }
    }

    return <div className="mb-3 shrink-0 space-y-2 text-xs">
        <div className="flex flex-wrap items-end gap-2">
            <label className="space-y-1 text-slate-600">Mapping engine
                <select aria-label="Mapping engine" value={engine} disabled={busy} onChange={e => setEngine(e.target.value)} className="block h-8 rounded border bg-white px-2">
                    <option value="auto">Auto</option><option value="softnix">Softnix Structured</option>
                    <option value="llm">Configured LLM provider</option><option value="fixed">Fixed position only</option>
                </select>
            </label>
            <button type="button" disabled={busy} onClick={() => retry()} className="inline-flex h-8 items-center gap-1 rounded border px-2 disabled:opacity-50">
                <RefreshCw className={`h-3.5 w-3.5 ${busy ? "animate-spin" : ""}`} />{busy ? "Mapping..." : "Retry Mapping"}
            </button>
        </div>
        {error && <p role="alert" className="text-red-700">{error}</p>}
        {proposal && <details className="rounded border p-2" open>
            <summary className="cursor-pointer font-medium">New mapping proposal</summary>
            <pre className="my-2 max-h-48 overflow-auto whitespace-pre-wrap break-all">{JSON.stringify(proposal, null, 2)}</pre>
            <button type="button" onClick={() => { onProposal(proposal); setProposal(null) }} className="rounded border px-2 py-1">Use proposal in editor</button>
        </details>}
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
                        {item.page && <button type="button" title={`Show source page ${item.page}`} aria-label={`Show evidence for ${name}`} onClick={() => onEvidence(item)}><Search className="h-4 w-4" /></button>}
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
