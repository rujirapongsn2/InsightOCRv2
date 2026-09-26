"use client"

import { Fragment, useCallback, useEffect, useState } from "react"
import Link from "next/link"
import { ChevronDown, ChevronRight, Loader2, Wand2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { getApiBaseUrl } from "@/lib/api"

type Outcome = "correct" | "corrected" | "missed" | "cleared"

interface Bucket {
  checked: number
  correct: number
  accuracy: number | null
}

interface FieldExample {
  document_id: string
  filename: string
  outcome: Outcome
  extracted: unknown
  reviewed: unknown
  version: number | null
}

interface FieldAccuracy extends Bucket, Record<Outcome, number> {
  name: string
  type: string
  required: boolean
  by_provider: Array<Bucket & { provider: string }>
  by_version: Array<Bucket & { version: number | null }>
  examples: FieldExample[]
}

interface AccuracyReport {
  current_version: number | null
  reviewed_documents: number
  truncated: boolean
  limit: number
  overall: Bucket
  versions: Array<Bucket & { version: number | null; documents: number }>
  fields: FieldAccuracy[]
}

type SuggestionKind = "add_labels" | "replace_pattern" | "remove_pattern" | "make_optional"

interface Suggestion {
  field: string
  kind: SuggestionKind
  labels?: string[]
  pattern?: string
  current_pattern?: string
  reason: string
  documents_fixed?: number
  documents_rejected?: number
  documents_checked?: number
  documents_empty?: number
  examples: Array<{ document_id: string; filename: string; line?: string; value?: string }>
}

interface ImprovementReport {
  reviewed_documents: number
  label_pass_active: boolean
  suggestions: Suggestion[]
}

const PERIODS = [
  { value: "", label: "All time" },
  { value: "30", label: "Last 30 days" },
  { value: "90", label: "Last 90 days" },
]

const OUTCOME_STYLE: Record<Outcome, { label: string; className: string; hint: string }> = {
  correct: { label: "Correct", className: "bg-emerald-50 text-emerald-700", hint: "Reviewer kept the extracted value" },
  corrected: { label: "Corrected", className: "bg-amber-50 text-amber-800", hint: "Reviewer changed the value" },
  missed: { label: "Missed", className: "bg-red-50 text-red-700", hint: "Nothing was extracted, the reviewer typed a value" },
  cleared: { label: "Removed", className: "bg-slate-100 text-slate-700", hint: "A value was extracted, the reviewer removed it" },
}

const PROVIDER_LABEL: Record<string, string> = {
  bbox: "Fixed position",
  label: "Label",
  softnix: "Softnix",
  jev: "Jev",
  llm: "LLM",
  not_found: "Not found",
  unknown: "Source not recorded",
}

function percent(value: number | null): string {
  return value === null ? "—" : `${Math.round(value * 100)}%`
}

function tone(value: number | null): string {
  if (value === null) return "bg-slate-300"
  if (value >= 0.95) return "bg-emerald-500"
  if (value >= 0.8) return "bg-amber-500"
  return "bg-red-500"
}

function show(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—"
  if (Array.isArray(value)) return `${value.length} row${value.length === 1 ? "" : "s"}`
  if (typeof value === "object") return JSON.stringify(value)
  return String(value)
}

function detailOf(data: unknown, fallback: string): string {
  const detail = (data as { detail?: unknown })?.detail
  return typeof detail === "string" ? detail : fallback
}

function suggestionKey(item: Suggestion): string {
  return `${item.field}:${item.kind}`
}

function describeSuggestion(item: Suggestion): { title: string; detail: string } {
  switch (item.kind) {
    case "add_labels":
      return {
        title: `Add label${item.labels!.length > 1 ? "s" : ""} ${item.labels!.map((label) => `“${label}”`).join(", ")}`,
        detail: `Would have found the confirmed value in ${item.documents_fixed} document${item.documents_fixed === 1 ? "" : "s"} where it was missed or wrong, without changing any document that was already right.`,
      }
    case "replace_pattern":
      return {
        title: `Change the format rule to ${item.pattern}`,
        detail: `The current rule ${item.current_pattern} rejected ${item.documents_rejected} of ${item.documents_checked} confirmed values. The new rule accepts all of them.`,
      }
    case "remove_pattern":
      return {
        title: "Remove the format rule",
        detail: `The rule ${item.current_pattern} rejected ${item.documents_rejected} of ${item.documents_checked} confirmed values, and those values don't share one format.`,
      }
    case "make_optional":
      return {
        title: "Make this field optional",
        detail: `Reviewers left it empty in ${item.documents_empty} of ${item.documents_checked} documents.`,
      }
  }
}

export function SchemaAccuracyPanel({ schemaId, onSchemaUpdated }: { schemaId: string; onSchemaUpdated?: (schema: unknown) => void }) {
  const [days, setDays] = useState("")
  const [report, setReport] = useState<AccuracyReport | null>(null)
  const [improvements, setImprovements] = useState<ImprovementReport | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [open, setOpen] = useState<string | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [applying, setApplying] = useState(false)
  const [applyMessage, setApplyMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null)

  const load = useCallback(async () => {
    const token = localStorage.getItem("token")
    const headers: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {}
    const query = days ? `?days=${days}` : ""
    setLoading(true)
    setError(null)
    try {
      const [accuracyRes, improvementRes] = await Promise.all([
        fetch(`${getApiBaseUrl()}/schemas/${schemaId}/accuracy${query}`, { headers }),
        fetch(`${getApiBaseUrl()}/schemas/${schemaId}/improvements${query}`, { headers }),
      ])
      const accuracy = await accuracyRes.json().catch(() => ({}))
      const suggested = await improvementRes.json().catch(() => ({}))
      if (!accuracyRes.ok) throw new Error(detailOf(accuracy, "Could not load accuracy"))
      setReport(accuracy)
      if (improvementRes.ok) {
        setImprovements(suggested)
        setSelected(new Set((suggested.suggestions || []).map(suggestionKey)))
      } else {
        setImprovements(null)
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not load accuracy")
    } finally {
      setLoading(false)
    }
  }, [schemaId, days])

  useEffect(() => { load() }, [load])

  const toggle = (key: string) => {
    setSelected((current) => {
      const next = new Set(current)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const apply = async () => {
    const changes = (improvements?.suggestions || []).filter((item) => selected.has(suggestionKey(item)))
      .map(({ field, kind, labels, pattern }) => ({ field, kind, labels, pattern }))
    if (!changes.length) return
    const token = localStorage.getItem("token")
    setApplying(true)
    setApplyMessage(null)
    try {
      const res = await fetch(`${getApiBaseUrl()}/schemas/${schemaId}/improvements/apply`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({ changes }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(detailOf(data, "Could not apply the changes"))
      onSchemaUpdated?.(data)
      setApplyMessage({
        kind: "ok",
        text: `Saved as version ${data.current_version}. If this schema has a test set, it runs automatically in about a minute; see the Versions tab for the result.`,
      })
      await load()
    } catch (err: unknown) {
      setApplyMessage({ kind: "error", text: err instanceof Error ? err.message : "Could not apply the changes" })
    } finally {
      setApplying(false)
    }
  }

  if (error) return <p className="text-sm text-red-700">{error}</p>
  if (!report) return <p className="text-sm text-slate-500"><Loader2 className="mr-1 inline h-4 w-4 animate-spin" />Loading accuracy...</p>

  const fields = [...report.fields].sort((a, b) => (a.accuracy ?? 2) - (b.accuracy ?? 2) || b.checked - a.checked)
  const suggestions = improvements?.suggestions || []

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <p className="max-w-2xl text-sm text-slate-500">
          Compares what the engine extracted with what reviewers confirmed. Only documents a person reviewed and confirmed are counted; auto-confirmed documents are left out.
        </p>
        <label className="flex items-center gap-2 text-sm text-slate-600" htmlFor="accuracy-period">
          Period
          <select id="accuracy-period" value={days} onChange={(event) => setDays(event.target.value)}
            className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm">
            {PERIODS.map((period) => <option key={period.value} value={period.value}>{period.label}</option>)}
          </select>
          {loading && <Loader2 className="h-4 w-4 animate-spin text-slate-400" />}
        </label>
      </div>

      {report.reviewed_documents === 0 ? (
        <div className="rounded-lg border border-dashed p-6 text-center text-sm text-slate-500">
          No reviewed documents yet. Accuracy appears here after reviewers confirm documents processed with this schema.
        </div>
      ) : (
        <>
          <div className="flex flex-wrap gap-x-8 gap-y-3 rounded-lg border bg-slate-50 p-4">
            <div>
              <div className="text-xs uppercase tracking-wide text-slate-500">Values kept as extracted</div>
              <div className="text-2xl font-semibold tabular-nums">{percent(report.overall.accuracy)}</div>
              <div className="text-xs text-slate-500 tabular-nums">{report.overall.correct} of {report.overall.checked} values</div>
            </div>
            <div>
              <div className="text-xs uppercase tracking-wide text-slate-500">Reviewed documents</div>
              <div className="text-2xl font-semibold tabular-nums">{report.reviewed_documents}</div>
              {report.truncated && <div className="text-xs text-slate-500">Latest {report.limit} only</div>}
            </div>
            {report.versions.length > 1 && (
              <div>
                <div className="text-xs uppercase tracking-wide text-slate-500">By version</div>
                <div className="mt-1 flex flex-wrap gap-1.5">
                  {report.versions.map((item) => (
                    <span key={item.version ?? "none"} className="rounded border bg-white px-2 py-0.5 text-xs tabular-nums">
                      {item.version ? `v${item.version}` : "No version"}: {percent(item.accuracy)} · {item.documents} docs
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>

          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-3 py-2">Field</th>
                  <th className="px-3 py-2">Accuracy</th>
                  <th className="px-3 py-2">What reviewers did</th>
                  <th className="px-3 py-2">By source</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {fields.map((item) => {
                  const isOpen = open === item.name
                  const hasDetail = item.examples.length > 0 || item.by_version.length > 1
                  return (
                    <Fragment key={item.name}>
                      <tr className="align-top">
                        <td className="px-3 py-2">
                          <button type="button" disabled={!hasDetail} onClick={() => setOpen(isOpen ? null : item.name)}
                            className="flex items-center gap-1 text-left font-medium disabled:cursor-default" aria-expanded={isOpen}>
                            {hasDetail ? (isOpen ? <ChevronDown className="h-4 w-4 text-slate-400" /> : <ChevronRight className="h-4 w-4 text-slate-400" />) : <span className="w-4" />}
                            {item.name}
                          </button>
                          <div className="pl-5 text-xs text-slate-500">{item.type}{item.required ? " · required" : ""}</div>
                        </td>
                        <td className="px-3 py-2">
                          {item.checked ? (
                            <div className="w-36">
                              <div className="flex justify-between text-xs tabular-nums">
                                <span className="font-medium">{percent(item.accuracy)}</span>
                                <span className="text-slate-500">{item.correct}/{item.checked}</span>
                              </div>
                              <div className="mt-1 h-1.5 rounded bg-slate-100">
                                <div className={`h-1.5 rounded ${tone(item.accuracy)}`} style={{ width: `${Math.round((item.accuracy ?? 0) * 100)}%` }} />
                              </div>
                            </div>
                          ) : <span className="text-xs text-slate-400">Empty in every reviewed document</span>}
                        </td>
                        <td className="px-3 py-2">
                          <div className="flex flex-wrap gap-1">
                            {(Object.keys(OUTCOME_STYLE) as Outcome[]).filter((outcome) => item[outcome] > 0).map((outcome) => (
                              <span key={outcome} title={OUTCOME_STYLE[outcome].hint}
                                className={`rounded px-1.5 py-0.5 text-xs tabular-nums ${OUTCOME_STYLE[outcome].className}`}>
                                {OUTCOME_STYLE[outcome].label} {item[outcome]}
                              </span>
                            ))}
                          </div>
                        </td>
                        <td className="px-3 py-2">
                          <div className="flex flex-wrap gap-1">
                            {item.by_provider.map((source) => (
                              <span key={source.provider} className="rounded border px-1.5 py-0.5 text-xs tabular-nums text-slate-600">
                                {PROVIDER_LABEL[source.provider] || source.provider}{" "}
                                {source.provider === "not_found" ? source.checked : `${percent(source.accuracy)} of ${source.checked}`}
                              </span>
                            ))}
                          </div>
                        </td>
                      </tr>
                      {isOpen && (
                        <tr className="bg-slate-50/60">
                          <td colSpan={4} className="space-y-3 px-3 py-3 pl-8">
                            {item.by_version.length > 1 && (
                              <div className="flex flex-wrap gap-1.5 text-xs">
                                {item.by_version.map((version) => (
                                  <span key={version.version ?? "none"} className="rounded border bg-white px-2 py-0.5 tabular-nums">
                                    {version.version ? `v${version.version}` : "No version"}: {percent(version.accuracy)} of {version.checked}
                                  </span>
                                ))}
                              </div>
                            )}
                            {item.examples.length > 0 && (
                              <table className="text-xs">
                                <thead className="text-left text-slate-500">
                                  <tr><th className="pr-4 font-normal">Document</th><th className="pr-4 font-normal">Extracted</th><th className="pr-4 font-normal">Confirmed</th><th className="font-normal" /></tr>
                                </thead>
                                <tbody>
                                  {item.examples.map((example) => (
                                    <tr key={example.document_id}>
                                      <td className="max-w-[14rem] truncate py-0.5 pr-4">
                                        <Link href={`/documents/${example.document_id}/review`} className="text-blue-700 hover:underline">{example.filename}</Link>
                                      </td>
                                      <td className="max-w-[14rem] truncate pr-4 text-slate-500 line-through decoration-slate-300">{show(example.extracted)}</td>
                                      <td className="max-w-[14rem] truncate pr-4 font-medium">{show(example.reviewed)}</td>
                                      <td><span className={`rounded px-1.5 py-0.5 ${OUTCOME_STYLE[example.outcome].className}`}>{OUTCOME_STYLE[example.outcome].label}</span></td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            )}
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  )
                })}
              </tbody>
            </table>
          </div>
        </>
      )}

      <section className="space-y-3">
        <div>
          <h3 className="flex items-center gap-2 text-base font-semibold"><Wand2 className="h-4 w-4 text-blue-600" />Suggested schema changes</h3>
          <p className="text-sm text-slate-500">
            Based on what reviewers corrected. Each suggestion is checked against every reviewed document first. Applying creates a new version.
          </p>
        </div>
        {improvements && !improvements.label_pass_active && suggestions.some((item) => item.kind === "add_labels") && (
          <p className="rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-800">
            Labels are only read when the mapping engine is set to Auto. They are saved either way and start working once Auto is selected.
          </p>
        )}
        {!suggestions.length ? (
          <p className="text-sm text-slate-500">
            {report.reviewed_documents ? "No changes to suggest. A label suggestion needs the same label in at least two corrected documents." : "Suggestions appear after reviewers correct some documents."}
          </p>
        ) : (
          <>
            <ul className="divide-y rounded-lg border">
              {suggestions.map((item) => {
                const key = suggestionKey(item)
                const text = describeSuggestion(item)
                return (
                  <li key={key} className="flex gap-3 p-3">
                    <input id={`suggestion-${key}`} type="checkbox" className="mt-1 h-4 w-4" checked={selected.has(key)} onChange={() => toggle(key)} />
                    <label htmlFor={`suggestion-${key}`} className="min-w-0 flex-1 cursor-pointer space-y-1">
                      <span className="block text-sm"><span className="font-medium">{item.field}</span>: {text.title}</span>
                      <span className="block text-xs text-slate-600">{text.detail}</span>
                      {item.examples.length > 0 && (
                        <span className="block space-y-0.5 text-xs text-slate-500">
                          {item.examples.slice(0, 3).map((example, index) => (
                            <span key={`${example.document_id}-${index}`} className="block truncate">
                              {example.filename}: <code className="rounded bg-slate-100 px-1">{example.line ?? example.value}</code>
                            </span>
                          ))}
                        </span>
                      )}
                    </label>
                  </li>
                )
              })}
            </ul>
            <div className="flex flex-wrap items-center gap-3">
              <Button onClick={apply} disabled={applying || selected.size === 0}>
                {applying && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Apply {selected.size} selected
              </Button>
            </div>
          </>
        )}
        {applyMessage && (
          <p className={`text-sm ${applyMessage.kind === "ok" ? "text-emerald-700" : "text-red-700"}`}>{applyMessage.text}</p>
        )}
      </section>
    </div>
  )
}
