"use client"

import { useEffect, useMemo, useState } from "react"
import { Plus, FileText, Receipt, FileSignature, File, Search, ScrollText, X, Trash2, Loader2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useAuth } from "@/components/auth-provider"
import { getApiBaseUrl } from "@/lib/api"
import { SchemaWizardProvider } from "@/contexts/SchemaWizardContext"
import { SchemaWizard } from "@/components/schema/SchemaWizard"

interface Schema {
    id: string
    name: string
    document_type: string
    description: string
    fields: any[]
    created_by?: string
    created_at?: string
    updated_at: string
}

interface SchemaField {
    name: string
    type: string
    description: string
    required: boolean
}

const getDocumentTypeIcon = (type: string) => {
    switch (type.toLowerCase()) {
        case 'invoice':
            return { Icon: Receipt, color: 'bg-emerald-100 text-emerald-600', badgeColor: 'bg-emerald-50 text-emerald-700' }
        case 'receipt':
            return { Icon: Receipt, color: 'bg-orange-100 text-orange-600', badgeColor: 'bg-orange-50 text-orange-700' }
        case 'contract':
            return { Icon: FileSignature, color: 'bg-blue-100 text-blue-600', badgeColor: 'bg-blue-50 text-blue-700' }
        case 'form':
            return { Icon: ScrollText, color: 'bg-purple-100 text-purple-600', badgeColor: 'bg-purple-50 text-purple-700' }
        default:
            return { Icon: File, color: 'bg-slate-100 text-slate-600', badgeColor: 'bg-slate-50 text-slate-700' }
    }
}

// ─── Edit Schema Modal ──────────────────────────────────────────────────────

function EditSchemaModal({ schemaId, onClose, onSaved }: { schemaId: string; onClose: () => void; onSaved: () => void }) {
    const [loading, setLoading] = useState(true)
    const [saving, setSaving] = useState(false)
    const [deleting, setDeleting] = useState(false)
    const [schema, setSchema] = useState<{ id: string; name: string; description: string; document_type: string; ocr_engine: string } | null>(null)
    const [fields, setFields] = useState<SchemaField[]>([])

    useEffect(() => {
        const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
        fetch(`${getApiBaseUrl()}/schemas/${schemaId}`, {
            headers: token ? { Authorization: `Bearer ${token}` } : undefined,
        })
            .then(r => r.ok ? r.json() : null)
            .then(data => { if (data) { setSchema(data); setFields(data.fields || []) } })
            .finally(() => setLoading(false))
    }, [schemaId])

    const addField = () => setFields((f: SchemaField[]) => [...f, { name: "", type: "text", description: "", required: false }])
    const removeField = (i: number) => setFields((f: SchemaField[]) => f.filter((_: SchemaField, idx: number) => idx !== i))
    const updateField = (i: number, key: keyof SchemaField, value: any) =>
        setFields((f: SchemaField[]) => f.map((field: SchemaField, idx: number) => idx === i ? { ...field, [key]: value } : field))

    const handleSave = async () => {
        if (!schema) return
        setSaving(true)
        try {
            const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
            const res = await fetch(`${getApiBaseUrl()}/schemas/${schemaId}`, {
                method: "PUT",
                headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
                body: JSON.stringify({ name: schema.name, description: schema.description, document_type: schema.document_type, ocr_engine: schema.ocr_engine, fields }),
            })
            if (res.ok) { onSaved(); onClose() } else alert("Failed to save schema")
        } catch { alert("Error saving schema") } finally { setSaving(false) }
    }

    const handleDelete = async () => {
        if (!confirm("Delete this schema? This cannot be undone.")) return
        setDeleting(true)
        try {
            const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
            const res = await fetch(`${getApiBaseUrl()}/schemas/${schemaId}`, {
                method: "DELETE",
                headers: token ? { Authorization: `Bearer ${token}` } : undefined,
            })
            if (res.ok) {
                onSaved()
                onClose()
            } else {
                let message = "Failed to delete schema"
                try {
                    const payload = await res.json()
                    if (payload?.detail) message = payload.detail
                } catch { }
                alert(message)
            }
        } catch { alert("Error deleting schema") } finally { setDeleting(false) }
    }

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
            <div className="bg-white rounded-xl shadow-2xl w-full max-w-3xl max-h-[90vh] flex flex-col">
                <div className="flex items-center justify-between px-6 py-4 border-b">
                    <h2 className="text-lg font-semibold">Edit Schema</h2>
                    <button onClick={onClose} className="p-1 rounded hover:bg-slate-100"><X className="h-5 w-5 text-slate-500" /></button>
                </div>
                {loading ? (
                    <div className="flex-1 flex items-center justify-center py-16"><Loader2 className="h-6 w-6 animate-spin text-slate-400" /></div>
                ) : !schema ? (
                    <div className="flex-1 flex items-center justify-center py-16 text-slate-500">Schema not found</div>
                ) : (
                    <div className="flex-1 overflow-y-auto p-6 space-y-6">
                        <div className="grid gap-4 md:grid-cols-2">
                            <div className="space-y-1.5">
                                <label className="text-sm font-medium text-slate-700">Schema Name <span className="text-red-500">*</span></label>
                                <Input value={schema.name} onChange={e => setSchema({ ...schema, name: e.target.value })} placeholder="e.g. Standard Invoice" />
                            </div>
                            <div className="space-y-1.5">
                                <label className="text-sm font-medium text-slate-700">Document Type</label>
                                <select className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                                    value={schema.document_type} onChange={e => setSchema({ ...schema, document_type: e.target.value })}>
                                    <option value="invoice">Invoice</option>
                                    <option value="receipt">Receipt</option>
                                    <option value="contract">Contract</option>
                                    <option value="po">Purchase Order</option>
                                    <option value="other">Other</option>
                                </select>
                            </div>
                            <div className="space-y-1.5 md:col-span-2">
                                <label className="text-sm font-medium text-slate-700">Description</label>
                                <Input value={schema.description || ""} onChange={e => setSchema({ ...schema, description: e.target.value })} placeholder="Describe this schema..." />
                            </div>
                        </div>
                        <div className="space-y-3">
                            <div className="flex items-center justify-between">
                                <h3 className="text-sm font-semibold text-slate-900">Extraction Fields</h3>
                                <Button type="button" variant="outline" size="sm" onClick={addField}><Plus className="h-3.5 w-3.5 mr-1" />Add Field</Button>
                            </div>
                            {fields.length === 0 && (
                                <p className="text-sm text-slate-400 py-4 text-center border border-dashed rounded-lg">No fields yet.</p>
                            )}
                            {fields.map((field, index) => (
                                <div key={index} className="flex items-start gap-3 p-3 rounded-lg bg-slate-50 border">
                                    <div className="grid gap-3 flex-1 sm:grid-cols-4">
                                        <div className="space-y-1">
                                            <label className="text-xs font-medium text-slate-600">Field Name</label>
                                            <Input placeholder="field_name" value={field.name} onChange={e => updateField(index, "name", e.target.value)} className="h-8 text-sm" />
                                        </div>
                                        <div className="space-y-1">
                                            <label className="text-xs font-medium text-slate-600">Type</label>
                                            <select className="flex h-8 w-full rounded-md border border-slate-200 bg-white px-2 text-sm"
                                                value={field.type} onChange={e => updateField(index, "type", e.target.value)}>
                                                <option value="text">Text</option>
                                                <option value="number">Number</option>
                                                <option value="date">Date</option>
                                                <option value="currency">Currency</option>
                                                <option value="boolean">Boolean</option>
                                                <option value="array">Array</option>
                                            </select>
                                        </div>
                                        <div className="space-y-1 sm:col-span-2">
                                            <label className="text-xs font-medium text-slate-600">Description / Prompt</label>
                                            <Input placeholder="Instructions for LLM..." value={field.description} onChange={e => updateField(index, "description", e.target.value)} className="h-8 text-sm" />
                                        </div>
                                    </div>
                                    <button onClick={() => removeField(index)} className="mt-5 p-1 rounded text-red-400 hover:text-red-600 hover:bg-red-50">
                                        <Trash2 className="h-4 w-4" />
                                    </button>
                                </div>
                            ))}
                        </div>
                    </div>
                )}
                {!loading && schema && (
                    <div className="flex items-center justify-between px-6 py-4 border-t bg-slate-50 rounded-b-xl">
                        <Button variant="destructive" size="sm" onClick={handleDelete} disabled={deleting || saving}>
                            {deleting ? <><Loader2 className="h-4 w-4 mr-1.5 animate-spin" />Deleting...</> : <><Trash2 className="h-4 w-4 mr-1.5" />Delete</>}
                        </Button>
                        <div className="flex gap-2">
                            <Button variant="outline" onClick={onClose} disabled={saving || deleting}>Cancel</Button>
                            <Button onClick={handleSave} disabled={saving || deleting || !schema.name.trim()}>
                                {saving ? <><Loader2 className="h-4 w-4 mr-1.5 animate-spin" />Saving...</> : "Save Changes"}
                            </Button>
                        </div>
                    </div>
                )}
            </div>
        </div>
    )
}

// ─── Create Schema Modal ────────────────────────────────────────────────────

function CreateSchemaModal({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
            <div className="bg-white rounded-xl shadow-2xl w-full max-w-4xl max-h-[92vh] flex flex-col">
                <div className="flex items-center justify-between px-6 py-4 border-b">
                    <h2 className="text-lg font-semibold">Create New Schema</h2>
                    <button onClick={onClose} className="p-1 rounded hover:bg-slate-100"><X className="h-5 w-5 text-slate-500" /></button>
                </div>
                <div className="flex-1 overflow-y-auto">
                    <SchemaWizardProvider onSaved={onSaved}>
                        <SchemaWizard embedded />
                    </SchemaWizardProvider>
                </div>
            </div>
        </div>
    )
}

export default function SchemasPage() {
    const { user, loading: authLoading } = useAuth()
    const [schemas, setSchemas] = useState<Schema[]>([])
    const [loading, setLoading] = useState(true)
    const [searchQuery, setSearchQuery] = useState("")
    const [showCreateModal, setShowCreateModal] = useState(false)
    const [editSchemaId, setEditSchemaId] = useState<string | null>(null)

    const normalizedRole = useMemo(() => {
        if (!user?.role) return "user"
        return user.role === "documents_admin" ? "manager" : user.role
    }, [user?.role])

    const filteredSchemas = useMemo(() => {
        if (!searchQuery.trim()) return schemas
        const q = searchQuery.toLowerCase()
        return schemas.filter((s: Schema) =>
            s.name.toLowerCase().includes(q) ||
            s.description?.toLowerCase().includes(q) ||
            s.document_type.toLowerCase().includes(q)
        )
    }, [schemas, searchQuery])

    const fetchSchemas = async () => {
        try {
            const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
            const res = await fetch(`${getApiBaseUrl()}/schemas/`, {
                headers: token ? { Authorization: `Bearer ${token}` } : undefined,
            })
            if (res.ok) setSchemas(await res.json())
        } catch (error) {
            console.error("Failed to fetch schemas", error)
        } finally {
            setLoading(false)
        }
    }

    useEffect(() => { fetchSchemas() }, [])

    if (authLoading || loading) return (
        <div className="flex items-center justify-center h-40">
            <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
        </div>
    )

    if (normalizedRole === "user") {
        return (
            <div className="bg-white rounded-lg border shadow-sm p-6">
                <h2 className="text-xl font-semibold text-slate-900">Access restricted</h2>
                <p className="text-slate-600 mt-2">Schemas can be managed by Managers or Admins.</p>
            </div>
        )
    }

    return (
        <div className="space-y-6">
            {/* Modals */}
            {showCreateModal && (
                <CreateSchemaModal
                    onClose={() => setShowCreateModal(false)}
                    onSaved={() => { setShowCreateModal(false); fetchSchemas() }}
                />
            )}
            {editSchemaId && (
                <EditSchemaModal
                    schemaId={editSchemaId}
                    onClose={() => setEditSchemaId(null)}
                    onSaved={() => { setEditSchemaId(null); fetchSchemas() }}
                />
            )}

            {/* Header */}
            <div className="flex items-center justify-between">
                <div>
                    <h2 className="text-2xl font-bold tracking-tight">Document Schemas</h2>
                    <p className="text-slate-500">Manage extraction schemas for your documents.</p>
                </div>
                <Button onClick={() => setShowCreateModal(true)}>
                    <Plus className="mr-2 h-4 w-4" />
                    Create Schema
                </Button>
            </div>

            {/* Search */}
            {schemas.length > 0 && (
                <div className="relative">
                    <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                    <input
                        type="text"
                        placeholder="Search schemas by name, description, or type..."
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        className="w-full pl-10 pr-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent text-sm"
                    />
                </div>
            )}

            {/* Empty states */}
            {schemas.length === 0 ? (
                <div className="flex flex-col items-center justify-center rounded-lg border border-dashed p-10 text-center">
                    <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-slate-100 mb-4">
                        <FileText className="h-6 w-6 text-slate-600" />
                    </div>
                    <h3 className="text-lg font-semibold">No schemas created</h3>
                    <p className="mt-2 mb-5 text-sm text-slate-500 max-w-sm">
                        Create your first schema to start extracting structured data from documents.
                    </p>
                    <Button onClick={() => setShowCreateModal(true)}>
                        <Plus className="mr-2 h-4 w-4" />
                        Create your first Schema
                    </Button>
                </div>
            ) : filteredSchemas.length === 0 ? (
                <div className="flex flex-col items-center justify-center rounded-lg border border-dashed p-8 text-center">
                    <Search className="h-10 w-10 text-slate-400 mb-3" />
                    <h3 className="text-lg font-semibold">No schemas found</h3>
                    <p className="text-sm text-slate-500 mt-1">
                        {searchQuery ? `No results for "${searchQuery}"` : "Try a different search term"}
                    </p>
                </div>
            ) : (
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                    {filteredSchemas.map((schema: Schema) => {
                        const canManage = normalizedRole === "admin" || (normalizedRole === "manager" && schema.created_by === user?.id)
                        const { Icon, color, badgeColor } = getDocumentTypeIcon(schema.document_type)
                        return (
                            <div key={schema.id} className="group relative rounded-lg border bg-white p-4 shadow-sm hover:shadow-md hover:border-slate-300 transition-all">
                                <div className="flex items-start justify-between mb-3">
                                    <div className={`h-10 w-10 rounded-lg ${color} flex items-center justify-center`}>
                                        <Icon className="h-5 w-5" />
                                    </div>
                                    <span className={`text-xs font-medium px-2 py-0.5 rounded ${badgeColor}`}>
                                        {schema.document_type}
                                    </span>
                                </div>
                                <h3 className="font-semibold text-base mb-1 line-clamp-1">{schema.name}</h3>
                                <p className="text-xs text-slate-500 mb-3 line-clamp-2 min-h-[2.5rem]">
                                    {schema.description || "No description provided."}
                                </p>
                                <div className="flex items-center justify-between text-xs text-slate-400 mb-3 pb-3 border-b">
                                    <span className="flex items-center gap-1">
                                        <FileText className="h-3 w-3" />
                                        {schema.fields.length} fields
                                    </span>
                                    <span>{new Date(schema.updated_at || Date.now()).toLocaleDateString('en-GB', { day: '2-digit', month: 'short' })}</span>
                                </div>
                                {canManage && (
                                    <Button
                                        size="sm"
                                        variant="outline"
                                        className="w-full"
                                        onClick={() => setEditSchemaId(schema.id)}
                                    >
                                        <FileText className="h-3.5 w-3.5 mr-1.5" />
                                        Edit
                                    </Button>
                                )}
                            </div>
                        )
                    })}
                </div>
            )}
        </div>
    )
}
