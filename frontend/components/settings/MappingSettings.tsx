"use client"

import { useEffect, useRef, useState } from "react"
import { Check, AlertTriangle, Loader2, Play, Save } from "lucide-react"
import { getApiBaseUrl } from "@/lib/api"

type Policy = { engine: string; fallback_provider_id: string | null; fallback_enabled: boolean }
type CheckResult = { engine: string; passed: boolean; elapsed_seconds: number }

export function MappingSettings({ providers }: { providers: Array<{ id: string; display_name: string; is_active: boolean; provider_type?: string }> }) {
    const [policy, setPolicy] = useState<Policy>({ engine: "auto", fallback_provider_id: null, fallback_enabled: true })
    const [loaded, setLoaded] = useState(false)
    const [busy, setBusy] = useState(false)
    const [message, setMessage] = useState("")
    const [checks, setChecks] = useState<CheckResult[]>([])
    const controller = useRef<AbortController | null>(null)
    const base = `${getApiBaseUrl()}/settings/mapping`
    const headers = () => ({ Authorization: `Bearer ${localStorage.getItem("token")}`, "Content-Type": "application/json" })
    useEffect(() => {
        const abort = new AbortController()
        fetch(`${base}/config`, { headers: headers(), signal: abort.signal })
            .then(async response => { if (!response.ok) throw new Error("Unable to load mapping configuration"); return response.json() })
            .then(data => { setPolicy(data); setLoaded(true) })
            .catch(error => { if (!abort.signal.aborted) setMessage(error.message) })
        return () => { abort.abort(); controller.current?.abort() }
    }, [base])

    async function save() {
        setBusy(true); setMessage("")
        try {
            const response = await fetch(`${base}/config`, { method: "PUT", headers: headers(), body: JSON.stringify(policy) })
            if (!response.ok) throw new Error((await response.json()).detail || "Save failed")
            setMessage("Mapping settings saved")
        } catch (error) { setMessage(error instanceof Error ? error.message : "Save failed") }
        finally { setBusy(false) }
    }

    async function test() {
        setBusy(true); setMessage(""); setChecks([])
        const abort = new AbortController(); controller.current = abort
        try {
            const response = await fetch(`${base}/test`, { method: "POST", headers: headers(), signal: abort.signal })
            if (!response.ok) throw new Error("Unable to start mapping test")
            const { run_id } = await response.json()
            const started = Date.now()
            while (!abort.signal.aborted && Date.now() - started < 600_000) {
                const result = await fetch(`${base}/test/${run_id}`, { headers: headers(), signal: abort.signal })
                if (!result.ok) throw new Error("Unable to retrieve mapping test")
                const report = await result.json()
                setChecks(report.checks || [])
                if (report.status === "completed") { setMessage("Test complete"); return }
                if (report.status === "failed") throw new Error("Mapping test failed")
                await new Promise<void>(resolve => {
                    const finish = () => { clearTimeout(timer); abort.signal.removeEventListener("abort", finish); resolve() }
                    const timer = setTimeout(finish, 2000)
                    abort.signal.addEventListener("abort", finish, { once: true })
                })
            }
            if (!abort.signal.aborted) setMessage("Test is still queued or running")
        } catch (error) { if (!abort.signal.aborted) setMessage(error instanceof Error ? error.message : "Test failed") }
        finally { if (!abort.signal.aborted) setBusy(false) }
    }

    return <section className="space-y-3 border-y py-4">
        <h3 className="text-sm font-semibold">Field Mapping</h3>
        <div className="grid gap-3 sm:grid-cols-2">
            <label className="space-y-1 text-sm">Default engine
                <select aria-label="Default mapping engine" disabled={!loaded || busy} value={policy.engine} onChange={e => setPolicy({ ...policy, engine: e.target.value })} className="block h-9 w-full rounded border bg-white px-2">
                    <option value="auto">Auto</option><option value="softnix">Softnix Structured</option>
                    <option value="llm">LLM Provider</option><option value="fixed">Fixed position only</option>
                </select>
            </label>
            <label className="space-y-1 text-sm">Mapping LLM provider
                <select aria-label="Mapping LLM provider" disabled={!loaded || busy} value={policy.fallback_provider_id || ""} onChange={e => setPolicy({ ...policy, fallback_provider_id: e.target.value || null })} className="block h-9 w-full rounded border bg-white px-2">
                    <option value="">Use default AI provider</option>
                    {providers.filter(p => p.is_active && p.provider_type === "openai_compatible").map(p => <option key={p.id} value={p.id}>{p.display_name}</option>)}
                </select>
            </label>
        </div>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={policy.fallback_enabled} disabled={!loaded || busy} onChange={e => setPolicy({ ...policy, fallback_enabled: e.target.checked })} />LLM fallback in Auto mode</label>
        <div className="flex flex-wrap gap-2">
            <button type="button" onClick={save} disabled={!loaded || busy} className="inline-flex items-center gap-1 rounded border px-3 py-2 text-sm disabled:opacity-50"><Save className="h-4 w-4" />Save mapping settings</button>
            <button type="button" onClick={test} disabled={!loaded || busy} title="Test saved providers using synthetic reference and amount fields" className="inline-flex items-center gap-1 rounded border px-3 py-2 text-sm disabled:opacity-50">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}Test saved providers</button>
        </div>
        {message && <p role="status" className="text-sm">{message}</p>}
        {checks.map(check => <div key={check.engine} className={`flex items-center gap-2 text-sm ${check.passed ? "text-green-700" : "text-red-700"}`}>
            {check.passed ? <Check className="h-4 w-4" /> : <AlertTriangle className="h-4 w-4" />}
            {check.engine}: {check.passed ? "Passed" : "Failed"} ({check.elapsed_seconds}s)
        </div>)}
    </section>
}
