"use client"

import { useEffect, useRef, useState } from "react"
import { Loader2, Trash2 } from "lucide-react"
import { useAuth } from "@/components/auth-provider"
import { Button } from "@/components/ui/button"
import { Modal } from "@/components/ui/modal"
import { SchemaWizardProvider, useSchemaWizard } from "@/contexts/SchemaWizardContext"
import { getApiBaseUrl } from "@/lib/api"
import type { CreateSchemaResponse } from "@/types/schema"
import { SchemaWizard } from "./SchemaWizard"

type EditorProps = {
  schemaId: string
  onClose: () => void
  onSaved: () => void
  embedded?: boolean
}

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; schema: CreateSchemaResponse }

export function SchemaEditor({ schemaId, onClose, onSaved, embedded = true }: EditorProps) {
  const { user, loading } = useAuth()
  const [load, setLoad] = useState<LoadState>({ status: "loading" })

  useEffect(() => {
    const controller = new AbortController()
    async function fetchSchema() {
      try {
        const token = localStorage.getItem("token")
        const response = await fetch(`${getApiBaseUrl()}/schemas/${schemaId}`, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          signal: controller.signal,
        })
        if (!response.ok) throw new Error("Unable to load schema")
        const schema: CreateSchemaResponse = await response.json()
        if (!controller.signal.aborted) setLoad({ status: "ready", schema })
      } catch (error) {
        if (!controller.signal.aborted) setLoad({ status: "error", message: error instanceof Error ? error.message : "Unable to load schema" })
      }
    }
    void fetchSchema()
    return () => controller.abort()
  }, [schemaId])

  if (loading || load.status !== "ready" || load.schema.id !== schemaId) {
    const content = load.status === "error"
      ? <p role="alert" className="p-8 text-red-700">{load.message}</p>
      : <div role="status" className="grid min-h-48 place-items-center"><Loader2 aria-label="Loading schema" className="h-6 w-6 animate-spin" /></div>
    return embedded ? <Modal isOpen onClose={onClose} title="Edit Schema">{content}</Modal> : content
  }

  const canManage = load.schema.can_manage ?? (user?.role === "admin" || ((user?.role === "manager" || user?.role === "documents_admin") && load.schema.created_by === user.id))
  if (!canManage) {
    const content = <p role="alert" className="p-8">You do not have permission to edit this schema.</p>
    return embedded ? <Modal isOpen onClose={onClose} title="Edit Schema">{content}</Modal> : content
  }

  return <SchemaWizardProvider key={schemaId} initialSchema={load.schema} onSaved={onSaved}>
    <EditorContent embedded={embedded} onClose={onClose} onSaved={onSaved} />
  </SchemaWizardProvider>
}

function EditorContent({ embedded, onClose, onSaved }: Pick<EditorProps, "embedded" | "onClose" | "onSaved">) {
  const { schemaId, schemaData, fields, isSaving, referencePdf, isRemovingReference, fixedFieldCreationMode } = useSchemaWizard()
  const baseline = useRef(JSON.stringify({ schemaData, fields }))
  const [deleting, setDeleting] = useState(false)
  const [error, setError] = useState("")
  const close = () => {
    if (isSaving || deleting || isRemovingReference) return
    const hasChanges = fixedFieldCreationMode !== "idle" || JSON.stringify({ schemaData, fields }) !== baseline.current || (referencePdf.kind === "selected" && referencePdf.consent)
    if (hasChanges && !confirm("Discard unsaved schema changes?")) return
    onClose()
  }
  const remove = async () => {
    if (!confirm("Delete this schema? This cannot be undone.")) return
    setDeleting(true)
    setError("")
    try {
      const token = localStorage.getItem("token")
      const response = await fetch(`${getApiBaseUrl()}/schemas/${schemaId}`, {
        method: "DELETE", headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
      if (!response.ok) throw new Error("Unable to delete schema")
      onSaved()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to delete schema")
    } finally {
      setDeleting(false)
    }
  }
  const content = <>
    <fieldset disabled={isSaving || deleting || isRemovingReference} className="min-w-0">
      <SchemaWizard embedded />
    </fieldset>
    {error && <p role="alert" className="px-5 text-sm text-red-700">{error}</p>}
    <div className="sticky bottom-0 flex justify-between gap-3 border-t bg-white px-5 py-3">
      <Button variant="destructive" size="sm" disabled={isSaving || deleting || isRemovingReference} onClick={remove}>
        {deleting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Trash2 className="mr-2 h-4 w-4" />}Delete
      </Button>
      <Button variant="outline" size="sm" disabled={isSaving || deleting || isRemovingReference} onClick={close}>Cancel</Button>
    </div>
  </>
  return embedded
    ? <Modal isOpen purpose="form" onClose={close} title={`Edit Schema · ${schemaData.name}`} width="calc(100vw - 2rem)" bodyClassName="p-0">{content}</Modal>
    : <div className="min-w-0"><h1 className="px-5 text-xl font-semibold">Edit Schema</h1>{content}</div>
}
