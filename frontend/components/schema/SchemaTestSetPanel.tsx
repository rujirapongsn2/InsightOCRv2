"use client"

import { useCallback, useEffect, useRef, useState, type ChangeEvent } from "react"
import { CheckCircle2, Loader2, Play, Trash2, Upload, XCircle } from "lucide-react"
import { Button } from "@/components/ui/button"
import { getApiBaseUrl } from "@/lib/api"
import { editableText, parseTypedValue } from "@/lib/schema-studio"

const POLL_MS = 2000
// A run still "queued" after this long means no worker picked it up.
const QUEUED_TIMEOUT_MS = 120_000
const VALID_TYPES = ["application/pdf", "image/jpeg", "image/jpg", "image/png"]

interface LastRun {
  run_at: string
  schema_version: number | null
  error: string | null
  checked: number
  matched: number
}

interface StoredSample {
  id: string
  filename: string
  confirmed_fields: string[]
  outdated_fields?: string[]
  last_run: LastRun | null
  created_at: string
  expires_at: string | null
}

type RunCell = { value: unknown; status?: string }
type Comparison = { checked: number; matched: number; fields: Record<string, { expected: unknown; actual: unknown; match: boolean }>; ignored?: string[] }
type RunSample = { index: number; filename: string; sample_id: string; report?: { fields: Record<string, RunCell> }; comparison?: Comparison; error?: string }
type RunState = { status: "queued" | "running" | "completed" | "failed"; total: number | null; done: number; samples: RunSample[]; error?: string | null }

const ENGINES = [
  { value: "", label: "System default" },
  { value: "auto", label: "Auto" },
  { value: "softnix", label: "Softnix" },
  { value: "jev", label: "Jev (TypeSafe)" },
  { value: "llm", label: "LLM" },
]

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—"
  if (Array.isArray(value)) return `${value.length} row${value.length === 1 ? "" : "s"}`
  if (typeof value === "object") return JSON.stringify(value)
  return String(value)
}

function detailOf(data: unknown, fallback: string): string {
  const detail = (data as { detail?: unknown })?.detail
  return typeof detail === "string" ? detail : fallback
}

export function SchemaTestSetPanel({ schemaId, fields }: { schemaId: string; fields: Array<{ name: string; type: string }> }) {
  const fieldNames = fields.map((field) => field.name)
  const [editing, setEditing] = useState<{ key: string; text: string } | null>(null)
  const [samples, setSamples] = useState<StoredSample[] | null>(null)
  const [retentionDays, setRetentionDays] = useState(180)
  const [error, setError] = useState<string | null>(null)
  const [files, setFiles] = useState<File[]>([])
  const [consent, setConsent] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  const [engine, setEngine] = useState("")
  const [runId, setRunId] = useState<string | null>(null)
  const [run, setRun] = useState<RunState | null>(null)
  const [expectedById, setExpectedById] = useState<Record<string, Record<string, unknown>>>({})
  // Latest confirmed values per sample, updated synchronously so quick clicks
  // build on each other; saves for one sample run one after another because
  // each PUT replaces the whole set.
  const expectedRef = useRef<Record<string, Record<string, unknown>>>({})
  const saveQueue = useRef<Record<string, Promise<void>>>({})

  const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
  const auth: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {}

  const load = useCallback(async () => {
    const res = await fetch(`${getApiBaseUrl()}/schemas/${schemaId}/samples`, { headers: auth })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) {
      setError(detailOf(data, "Could not load the test set"))
      return
    }
    setSamples(data.samples || [])
    setRetentionDays(data.retention_days || 180)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [schemaId, token])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    if (!runId) return
    let cancelled = false
    const startedAt = Date.now()
    const poll = async () => {
      const res = await fetch(`${getApiBaseUrl()}/schemas/sample-runs/${runId}`, { headers: auth })
      const data = await res.json().catch(() => ({}))
      if (cancelled) return
      if (!res.ok) {
        setError(detailOf(data, "Could not read test progress"))
        setRunId(null)
        return
      }
      setRun(data as RunState)
      if (data.status === "completed" || data.status === "failed") {
        setRunId(null)
        if (data.status === "failed") setError(data.error || "The test run failed. Try again.")
        load()
      } else if (data.status === "queued" && Date.now() - startedAt > QUEUED_TIMEOUT_MS) {
        setRunId(null)
        setError("The test did not start. The document worker may be busy or offline. Try again later.")
      }
    }
    poll()
    const timer = setInterval(poll, POLL_MS)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, load])

  const handleFiles = (e: ChangeEvent<HTMLInputElement>) => {
    const chosen = Array.from(e.target.files || []).filter((f) => VALID_TYPES.includes(f.type))
    e.target.value = ""
    setFiles(chosen)
  }

  const handleUpload = async () => {
    if (!files.length || !consent) return
    setUploading(true)
    setError(null)
    const form = new FormData()
    files.forEach((f) => form.append("files", f))
    form.append("expected", "[]")
    form.append("consent", "true")
    try {
      const res = await fetch(`${getApiBaseUrl()}/schemas/${schemaId}/samples`, { method: "POST", headers: auth, body: form })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(detailOf(data, "Could not keep the files"))
      setFiles([])
      setConsent(false)
      await load()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not keep the files")
    } finally {
      setUploading(false)
    }
  }

  const handleDelete = async (id: string) => {
    setConfirmDelete(null)
    const res = await fetch(`${getApiBaseUrl()}/schemas/${schemaId}/samples/${id}`, { method: "DELETE", headers: auth })
    if (!res.ok) setError("Could not delete the sample")
    await load()
  }

  const handleRun = async () => {
    setError(null)
    setRun(null)
    // The new run's comparison carries the saved values.
    expectedRef.current = {}
    setExpectedById({})
    const res = await fetch(`${getApiBaseUrl()}/schemas/${schemaId}/samples/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...auth },
      body: JSON.stringify({ engine: engine || null }),
    })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) {
      setError(detailOf(data, "Could not start the test"))
      return
    }
    setRun({ status: "queued", total: data.total, done: 0, samples: [] })
    setRunId(data.run_id)
  }

  const markCorrect = (sample: RunSample, field: string, value: unknown) => {
    const id = sample.sample_id
    const stored = samples?.find((s) => s.id === id)
    const base = expectedRef.current[id] ?? Object.fromEntries(
      Object.entries(sample.comparison?.fields || {}).map(([name, item]) => [name, item.expected]))
    const previous = base[field]
    const hadPrevious = field in base
    const next = { ...base, [field]: value }
    expectedRef.current = { ...expectedRef.current, [id]: next }
    setExpectedById(expectedRef.current)

    const save = async () => {
      const res = await fetch(`${getApiBaseUrl()}/schemas/${schemaId}/samples/${id}/expected`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", ...auth },
        // Send the newest set at the time this save runs, not the one from the click.
        body: JSON.stringify({ expected: expectedRef.current[id] }),
      })
      if (!res.ok) {
        const reverted = { ...expectedRef.current[id] }
        if (hadPrevious) reverted[field] = previous
        else delete reverted[field]
        expectedRef.current = { ...expectedRef.current, [id]: reverted }
        setExpectedById(expectedRef.current)
        setError(`Could not save the confirmed value for ${field} in ${stored?.filename || "the sample"}`)
      }
    }
    const queued = (saveQueue.current[id] || Promise.resolve()).then(save, save)
    saveQueue.current[id] = queued
    queued.then(() => {
      if (saveQueue.current[id] === queued) load()
    })
  }

  if (error && samples === null) return <p className="text-sm text-red-700">{error}</p>
  if (samples === null) return <p className="text-sm text-slate-500"><Loader2 className="mr-1 inline h-4 w-4 animate-spin" />Loading test set...</p>

  const running = runId !== null

  return (
    <div className="space-y-5">
      <p className="text-sm text-slate-500">
        Sample documents with confirmed values. Run the test after changing fields or engines to see which values still come out right.
        Files are kept for {retentionDays} days, then deleted automatically.
      </p>
      {error && <p className="text-sm text-red-700">{error}</p>}

      {samples.length > 0 ? (
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full min-w-[560px] text-sm">
            <thead>
              <tr className="border-b bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="px-3 py-2 font-semibold">File</th>
                <th className="px-3 py-2 font-semibold">Confirmed values</th>
                <th className="px-3 py-2 font-semibold">Last test</th>
                <th className="px-3 py-2 font-semibold">Deleted on</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {samples.map((sample) => (
                <tr key={sample.id} className="border-b last:border-0 align-top">
                  <td className="px-3 py-2 font-medium text-slate-800">{sample.filename}</td>
                  <td className="px-3 py-2 tabular-nums text-slate-700">
                    {sample.confirmed_fields.length} of {fieldNames.length}
                    {!!sample.outdated_fields?.length && (
                      <span className="block text-xs text-slate-500" title={sample.outdated_fields.join(", ")}>
                        {sample.outdated_fields.length} for fields no longer in the schema (not tested)
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-slate-700">
                    {sample.last_run ? (
                      sample.last_run.error ? <span className="text-red-700">Failed</span> : (
                        <span className="tabular-nums">
                          <span className={sample.last_run.matched === sample.last_run.checked ? "text-emerald-700" : "text-amber-700"}>
                            {sample.last_run.matched} of {sample.last_run.checked} match
                          </span>
                          <span className="block text-xs text-slate-500">
                            {new Date(sample.last_run.run_at).toLocaleString()}
                            {sample.last_run.schema_version ? ` · version ${sample.last_run.schema_version}` : ""}
                          </span>
                        </span>
                      )
                    ) : <span className="text-slate-500">Not tested</span>}
                  </td>
                  <td className="px-3 py-2 text-slate-500">{sample.expires_at ? new Date(sample.expires_at).toLocaleDateString() : "—"}</td>
                  <td className="px-3 py-2 text-right">
                    {confirmDelete === sample.id ? (
                      <span className="inline-flex items-center gap-2 text-xs">
                        Delete this file?
                        <button type="button" className="font-medium text-red-700" onClick={() => handleDelete(sample.id)}>Delete</button>
                        <button type="button" className="text-slate-500" onClick={() => setConfirmDelete(null)}>Cancel</button>
                      </span>
                    ) : (
                      <button type="button" title={`Delete ${sample.filename}`} onClick={() => setConfirmDelete(sample.id)} className="text-slate-400 hover:text-red-500">
                        <Trash2 className="h-4 w-4" />
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="text-sm text-slate-500">No sample files yet. Add some below, or keep the samples when you create a schema from uploaded documents.</p>
      )}

      {samples.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <select aria-label="Extraction engine" className="rounded border border-slate-300 px-2 py-1.5 text-sm" value={engine} onChange={(e) => setEngine(e.target.value)} disabled={running}>
            {ENGINES.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
          <Button type="button" onClick={handleRun} disabled={running} className="gap-1">
            {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            {running ? "Testing..." : "Run test set"}
          </Button>
          <span className="text-xs text-slate-500">Uses the same engines as real jobs and may use Softnix or LLM credits.</span>
          {running && run && (
            <span className="w-full text-sm text-slate-600 tabular-nums">Tested {run.done} of {run.total ?? samples.length} samples. This can take a few minutes.</span>
          )}
        </div>
      )}

      {run?.status === "completed" && run.samples.map((sample) => (
        <div key={sample.index} className="rounded-lg border p-3 space-y-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h4 className="text-sm font-semibold text-slate-800">{sample.filename}</h4>
            {sample.comparison && (
              <span className={`text-sm tabular-nums ${sample.comparison.matched === sample.comparison.checked ? "text-emerald-700" : "text-amber-700"}`}>
                {sample.comparison.matched} of {sample.comparison.checked} confirmed values match
              </span>
            )}
          </div>
          {!!sample.comparison?.ignored?.length && (
            <p className="text-xs text-slate-500">
              Not counted: confirmed values for fields no longer in the schema ({sample.comparison.ignored.join(", ")}).
            </p>
          )}
          {sample.error ? <p className="text-sm text-red-700">This sample could not be tested.</p> : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[520px] text-sm">
                <thead>
                  <tr className="border-b text-left text-xs uppercase tracking-wide text-slate-500">
                    <th className="py-1.5 pr-3 font-semibold">Field</th>
                    <th className="py-1.5 pr-3 font-semibold">Confirmed value</th>
                    <th className="py-1.5 pr-3 font-semibold">Extracted now</th>
                    <th className="py-1.5 font-semibold" />
                  </tr>
                </thead>
                <tbody>
                  {fieldNames.map((name) => {
                    const compared = sample.comparison?.fields[name]
                    const actual = sample.report?.fields[name]?.value
                    const confirmed = expectedById[sample.sample_id]?.[name] ?? compared?.expected
                    const hasActual = actual !== null && actual !== undefined && actual !== ""
                    return (
                      <tr key={name} className="border-b last:border-0 align-top">
                        <td className="py-1.5 pr-3 font-medium text-slate-800">{name}</td>
                        <td className="py-1.5 pr-3 text-slate-700">
                          {editing?.key === `${sample.sample_id}:${name}` ? (
                            <form
                              className="flex items-center gap-1"
                              onSubmit={(e) => {
                                e.preventDefault()
                                const type = fields.find((field) => field.name === name)?.type || "text"
                                const typed = parseTypedValue(editing.text, type)
                                if (typed !== undefined) markCorrect(sample, name, typed)
                                setEditing(null)
                              }}
                            >
                              <input
                                autoFocus
                                aria-label={`Correct value for ${name}`}
                                className="w-40 rounded border border-slate-300 px-1.5 py-0.5 text-xs"
                                value={editing.text}
                                onChange={(e) => setEditing({ key: `${sample.sample_id}:${name}`, text: e.target.value })}
                                onKeyDown={(e) => { if (e.key === "Escape") setEditing(null) }}
                              />
                              <button type="submit" className="text-xs font-medium text-emerald-700">Save</button>
                              <button type="button" className="text-xs text-slate-500" onClick={() => setEditing(null)}>Cancel</button>
                            </form>
                          ) : (
                            <span className="inline-flex flex-wrap items-center gap-x-2">
                              {confirmed === undefined ? <span className="text-slate-400">Not confirmed</span> : formatValue(confirmed)}
                              {fields.find((field) => field.name === name)?.type !== "array" && (
                                <button
                                  type="button"
                                  className="text-xs text-blue-700 hover:text-blue-800"
                                  onClick={() => setEditing({ key: `${sample.sample_id}:${name}`, text: editableText(confirmed) })}
                                >
                                  {confirmed === undefined ? "Enter value" : "Edit"}
                                </button>
                              )}
                            </span>
                          )}
                        </td>
                        <td className="py-1.5 pr-3 text-slate-700">
                          <span className="inline-flex items-start gap-1">
                            {compared && (compared.match
                              ? <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-600" />
                              : <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-red-500" />)}
                            {formatValue(actual)}
                          </span>
                        </td>
                        <td className="py-1.5 text-right">
                          {hasActual && !(compared?.match) && (
                            <button
                              type="button"
                              title="Save this extracted value as the correct answer"
                              className="rounded-full border border-slate-300 bg-white px-2.5 py-1 text-xs font-medium text-slate-700 hover:border-emerald-500 hover:text-emerald-700"
                              onClick={() => markCorrect(sample, name, actual)}
                            >
                              Mark correct
                            </button>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      ))}

      <div className="rounded-lg border border-dashed p-3 space-y-2">
        <h4 className="text-sm font-semibold text-slate-800">Add sample files</h4>
        <input type="file" multiple accept=".pdf,.jpg,.jpeg,.png" onChange={handleFiles} aria-label="Sample files" className="text-sm" />
        {files.length > 0 && <p className="text-xs text-slate-600">{files.map((f) => f.name).join(", ")}</p>}
        <label className="flex items-start gap-2 text-sm text-slate-700">
          <input type="checkbox" className="mt-1" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
          <span>
            Store these files and their text for {retentionDays} days as this schema&apos;s test set.
            <span className="block text-xs text-slate-500">They may contain personal data and are visible only to people who can manage this schema.</span>
          </span>
        </label>
        <Button type="button" variant="outline" size="sm" onClick={handleUpload} disabled={!files.length || !consent || uploading} className="gap-1">
          {uploading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
          Keep files
        </Button>
      </div>
    </div>
  )
}
