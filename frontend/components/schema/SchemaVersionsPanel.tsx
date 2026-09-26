"use client"

import { useCallback, useEffect, useState } from "react"
import { ChevronDown, ChevronRight, Loader2 } from "lucide-react"
import { getApiBaseUrl } from "@/lib/api"

interface VersionField {
  name: string
  [key: string]: unknown
}

interface TestRun {
  run_at: string
  engine: string
  trigger: string
  samples: number
  errors: number
  checked: number
  matched: number
}

interface VersionTest {
  latest: TestRun
  runs: number
  compared_with_version: number | null
  comparison: { previous_engine: string | null; previous_matched: number | null; previous_checked: number | null; improved: string[]; regressed: string[] } | null
}

interface SchemaVersionRow {
  version: number
  note: string | null
  field_names: string[]
  created_at: string
  created_by_name: string | null
  fields: VersionField[]
  test: VersionTest | null
}

interface AutoTestStatus {
  enabled: boolean
  pending: boolean
  trigger?: string
  version?: number | null
}

const PENDING_POLL_MS = 15_000

const TRIGGER_LABEL: Record<string, string> = {
  manual: "run by hand",
  schema_change: "after the fields changed",
  samples_added: "after samples were added",
  engine_change: "after the mapping engine changed",
  review_suggestions: "after review suggestions were applied",
}

const ENGINE_LABEL: Record<string, string> = { auto: "Auto", softnix: "Softnix", jev: "Jev", llm: "LLM", fixed: "Fixed position" }

function TestSummary({ test }: { test: VersionTest }) {
  const run = test.latest
  const comparison = test.comparison
  const engineChanged = comparison?.previous_engine && comparison.previous_engine !== run.engine
  return (
    <span className="mt-1 block space-y-0.5 text-xs">
      <span className="block text-slate-700">
        Test set: <span className="font-medium tabular-nums">{run.matched}/{run.checked}</span> confirmed values matched
        <span className="text-slate-500"> · {ENGINE_LABEL[run.engine] || run.engine} · {TRIGGER_LABEL[run.trigger] || run.trigger} · {new Date(run.run_at).toLocaleString()}</span>
        {run.errors > 0 && <span className="text-red-700"> · {run.errors} sample{run.errors === 1 ? "" : "s"} failed</span>}
      </span>
      {comparison && (comparison.improved.length > 0 || comparison.regressed.length > 0) ? (
        <span className="block">
          <span className="text-slate-500">
            Compared with the run before{test.compared_with_version && test.compared_with_version !== undefined ? ` (v${test.compared_with_version}${engineChanged ? `, ${ENGINE_LABEL[comparison.previous_engine!] || comparison.previous_engine}` : ""})` : ""}:{" "}
          </span>
          {comparison.improved.length > 0 && <span className="text-emerald-700">better on {comparison.improved.join(", ")}</span>}
          {comparison.improved.length > 0 && comparison.regressed.length > 0 && <span className="text-slate-400"> · </span>}
          {comparison.regressed.length > 0 && <span className="font-medium text-red-700">worse on {comparison.regressed.join(", ")}</span>}
        </span>
      ) : comparison ? (
        <span className="block text-slate-500">Same results as the run before.</span>
      ) : null}
    </span>
  )
}

function describeChanges(current: VersionField[], previous: VersionField[] | undefined): string {
  if (!previous) return "First version"
  const before = new Map(previous.map((field) => [field.name, JSON.stringify(field)]))
  const after = new Map(current.map((field) => [field.name, JSON.stringify(field)]))
  const added = [...after.keys()].filter((name) => !before.has(name))
  const removed = [...before.keys()].filter((name) => !after.has(name))
  const changed = [...after.keys()].filter((name) => before.has(name) && before.get(name) !== after.get(name))
  const parts = [
    added.length ? `Added ${added.join(", ")}` : "",
    removed.length ? `Removed ${removed.join(", ")}` : "",
    changed.length ? `Changed ${changed.join(", ")}` : "",
  ].filter(Boolean)
  return parts.length ? parts.join(" · ") : "Field order or settings changed"
}

export function SchemaVersionsPanel({ schemaId }: { schemaId: string }) {
  const [versions, setVersions] = useState<SchemaVersionRow[] | null>(null)
  const [current, setCurrent] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [open, setOpen] = useState<number | null>(null)

  const [autoTest, setAutoTest] = useState<AutoTestStatus | null>(null)

  const load = useCallback(() => {
    const token = localStorage.getItem("token")
    return fetch(`${getApiBaseUrl()}/schemas/${schemaId}/versions`, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
      .then(async (res) => {
        if (!res.ok) throw new Error("Could not load versions")
        const data = await res.json()
        setVersions(data.versions || [])
        setCurrent(data.current_version ?? null)
        setAutoTest(data.auto_test ?? null)
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Could not load versions"))
  }, [schemaId])

  useEffect(() => { load() }, [load])

  // Refresh while an automatic test run is queued or running, so its result shows up here.
  useEffect(() => {
    if (!autoTest?.pending) return
    const timer = window.setTimeout(load, PENDING_POLL_MS)
    return () => window.clearTimeout(timer)
  }, [autoTest, load])

  if (error) return <p className="text-sm text-red-700">{error}</p>
  if (!versions) return <p className="text-sm text-slate-500"><Loader2 className="mr-1 inline h-4 w-4 animate-spin" />Loading versions...</p>
  if (!versions.length) return <p className="text-sm text-slate-500">No versions yet. A version is recorded the next time this schema is saved or used.</p>

  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-500">
        Every change to the fields creates a new version. New documents always use the latest version, and each processed document records the version it used.
        {autoTest?.enabled ? " When the schema has a test set, it runs automatically after each change so you can see whether results got better or worse." : ""}
      </p>
      {autoTest?.pending && (
        <p className="flex items-center gap-2 rounded-md bg-blue-50 px-3 py-2 text-sm text-blue-800">
          <Loader2 className="h-4 w-4 animate-spin" />
          The test set is running {TRIGGER_LABEL[autoTest.trigger || ""] || "automatically"}. Results appear here when it finishes.
        </p>
      )}
      <ul className="divide-y rounded-lg border">
        {versions.map((row, index) => {
          const isOpen = open === row.version
          return (
            <li key={row.version} className="p-3">
              <button type="button" onClick={() => setOpen(isOpen ? null : row.version)} className="flex w-full items-start gap-2 text-left" aria-expanded={isOpen}>
                {isOpen ? <ChevronDown className="mt-0.5 h-4 w-4 text-slate-400" /> : <ChevronRight className="mt-0.5 h-4 w-4 text-slate-400" />}
                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">Version {row.version}</span>
                    {row.version === current && <span className="rounded bg-blue-50 px-1.5 py-0.5 text-xs text-blue-700">Current</span>}
                    <span className="text-xs text-slate-500">
                      {new Date(row.created_at).toLocaleString()}
                      {row.created_by_name ? ` · ${row.created_by_name}` : ""}
                      {row.note ? ` · ${row.note}` : ""}
                    </span>
                  </span>
                  <span className="block text-xs text-slate-600">{describeChanges(row.fields, versions[index + 1]?.fields)}</span>
                  {row.test && <TestSummary test={row.test} />}
                </span>
              </button>
              {isOpen && (
                <div className="mt-2 flex flex-wrap gap-1.5 pl-6">
                  {row.field_names.map((name) => (
                    <span key={name} className="rounded border border-slate-200 bg-slate-50 px-2 py-0.5 text-xs text-slate-700">{name}</span>
                  ))}
                </div>
              )}
            </li>
          )
        })}
      </ul>
    </div>
  )
}
