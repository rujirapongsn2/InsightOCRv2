"use client"

import { useEffect, useState } from "react"
import { ChevronDown, ChevronRight, Loader2 } from "lucide-react"
import { getApiBaseUrl } from "@/lib/api"

interface VersionField {
  name: string
  [key: string]: unknown
}

interface SchemaVersionRow {
  version: number
  note: string | null
  field_names: string[]
  created_at: string
  created_by_name: string | null
  fields: VersionField[]
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

  useEffect(() => {
    const token = localStorage.getItem("token")
    fetch(`${getApiBaseUrl()}/schemas/${schemaId}/versions`, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
      .then(async (res) => {
        if (!res.ok) throw new Error("Could not load versions")
        const data = await res.json()
        setVersions(data.versions || [])
        setCurrent(data.current_version ?? null)
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Could not load versions"))
  }, [schemaId])

  if (error) return <p className="text-sm text-red-700">{error}</p>
  if (!versions) return <p className="text-sm text-slate-500"><Loader2 className="mr-1 inline h-4 w-4 animate-spin" />Loading versions...</p>
  if (!versions.length) return <p className="text-sm text-slate-500">No versions yet. A version is recorded the next time this schema is saved or used.</p>

  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-500">
        Every change to the fields creates a new version. New documents always use the latest version, and each processed document records the version it used.
      </p>
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
