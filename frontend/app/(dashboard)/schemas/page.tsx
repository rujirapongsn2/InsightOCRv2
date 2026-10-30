"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import { Plus, FileText, Receipt, FileSignature, File, Search, ScrollText, X, Loader2, ListFilter, ArrowDownAZ, Download, Upload, CheckSquare, Square } from "lucide-react"
import { Button } from "@/components/ui/button"
import { useAuth } from "@/components/auth-provider"
import { getApiBaseUrl } from "@/lib/api"
import { SchemaWizardProvider } from "@/contexts/SchemaWizardContext"
import { SchemaWizard } from "@/components/schema/SchemaWizard"
import { SchemaEditor } from "@/components/schema/SchemaEditor"
import type { ExtractionProfile } from "@/types/schema"
import { Modal } from "@/components/ui/modal"

interface Schema {
    id: string
    name: string
    document_type: string
    description: string
    fields: SchemaField[]
    created_by?: string
    can_manage?: boolean
    created_at?: string
    updated_at?: string
    extraction_profile?: "legacy" | "anydoc_hybrid"
}

interface SchemaField {
    name: string
    type: string
    description: string
    required: boolean
    locator?: {
        type: "bbox"
        page: number
        x: number
        y: number
        width: number
        height: number
        clean_placeholders?: boolean
    }
}

type SchemaSort = "updated_desc" | "updated_asc" | "name_asc" | "name_desc" | "fields_desc" | "fields_asc"

const schemaActivityTimestamp = (schema: Schema) =>
    new Date(schema.updated_at || schema.created_at || 0).getTime()

const schemaActivityDate = (schema: Schema) =>
    schema.updated_at || schema.created_at

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

function EditSchemaModal(props: { schemaId: string; onClose: () => void; onSaved: () => void }) {
    return <SchemaEditor {...props} />
}

// ─── Create Schema Modal ────────────────────────────────────────────────────

function CreateSchemaModal({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
            <div className="bg-white rounded-xl shadow-2xl w-full max-w-[96vw] max-h-[96vh] flex flex-col">
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
    const [documentTypeFilter, setDocumentTypeFilter] = useState("all")
    const [pipelineFilter, setPipelineFilter] = useState<ExtractionProfile | "all">("all")
    const [sortBy, setSortBy] = useState<SchemaSort>("updated_desc")
    const [showCreateModal, setShowCreateModal] = useState(false)
    const [editSchemaId, setEditSchemaId] = useState<string | null>(null)
    const [selectedSchemaIds, setSelectedSchemaIds] = useState<string[]>([])
    const [showImportModal, setShowImportModal] = useState(false)
    const [importFile, setImportFile] = useState<File | null>(null)
    const [importConflict, setImportConflict] = useState<"suffix" | "skip" | "error">("suffix")
    const [importing, setImporting] = useState(false)
    const [exporting, setExporting] = useState(false)
    const [notice, setNotice] = useState<string | null>(null)
    const importInputRef = useRef<HTMLInputElement>(null)

    const resetImportFile = () => {
        setImportFile(null)
        if (importInputRef.current) importInputRef.current.value = ""
    }

    const closeImportModal = () => {
        if (importing) return
        setShowImportModal(false)
        resetImportFile()
    }

    const normalizedRole = useMemo(() => {
        if (!user?.role) return "user"
        return user.role === "documents_admin" ? "manager" : user.role
    }, [user?.role])

    const documentTypes = useMemo(() => (
        Array.from(new Set(schemas.map((schema) => schema.document_type.toLowerCase())))
            .sort((a, b) => a.localeCompare(b))
    ), [schemas])

    const filteredSchemas = useMemo(() => {
        const query = searchQuery.trim().toLowerCase()
        return schemas
            .filter((schema) => {
                const matchesQuery = !query ||
                    schema.name.toLowerCase().includes(query) ||
                    schema.description?.toLowerCase().includes(query) ||
                    schema.document_type.toLowerCase().includes(query)
                const matchesType = documentTypeFilter === "all" || schema.document_type.toLowerCase() === documentTypeFilter
                const matchesPipeline = pipelineFilter === "all" || (schema.extraction_profile || "legacy") === pipelineFilter
                return matchesQuery && matchesType && matchesPipeline
            })
            .sort((a, b) => {
                switch (sortBy) {
                    case "name_asc": return a.name.localeCompare(b.name)
                    case "name_desc": return b.name.localeCompare(a.name)
                    case "fields_desc": return b.fields.length - a.fields.length
                    case "fields_asc": return a.fields.length - b.fields.length
                    case "updated_asc": return schemaActivityTimestamp(a) - schemaActivityTimestamp(b)
                    case "updated_desc":
                    default: return schemaActivityTimestamp(b) - schemaActivityTimestamp(a)
                }
            })
    }, [schemas, searchQuery, documentTypeFilter, pipelineFilter, sortBy])

    const hasActiveFilters = documentTypeFilter !== "all" || pipelineFilter !== "all"
    const clearFilters = () => {
        setDocumentTypeFilter("all")
        setPipelineFilter("all")
    }

    const canManageSchema = (schema: Schema) =>
        schema.can_manage ?? (normalizedRole === "admin" || (normalizedRole === "manager" && schema.created_by === user?.id))

    const manageableFilteredIds = filteredSchemas.filter(canManageSchema).map((schema) => schema.id)
    const allManageableSelected = manageableFilteredIds.length > 0 && manageableFilteredIds.every((id) => selectedSchemaIds.includes(id))

    const toggleSchemaSelection = (schemaId: string) => {
        setSelectedSchemaIds((current) => current.includes(schemaId)
            ? current.filter((id) => id !== schemaId)
            : [...current, schemaId])
    }

    const toggleAllVisible = () => {
        setSelectedSchemaIds((current) => allManageableSelected
            ? current.filter((id) => !manageableFilteredIds.includes(id))
            : Array.from(new Set([...current, ...manageableFilteredIds])))
    }

    const handleExportSelected = async () => {
        if (!selectedSchemaIds.length || exporting) return
        setExporting(true)
        setNotice(null)
        try {
            const token = localStorage.getItem("token")
            const response = await fetch(`${getApiBaseUrl()}/schemas/export`, {
                method: "POST",
                headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
                body: JSON.stringify({ schema_ids: selectedSchemaIds }),
            })
            if (!response.ok) {
                const payload = await response.json().catch(() => null)
                throw new Error(payload?.detail || "Failed to export schemas")
            }
            const blob = await response.blob()
            const url = URL.createObjectURL(blob)
            const link = document.createElement("a")
            link.href = url
            link.download = "insightdoc-schemas.json"
            document.body.appendChild(link)
            link.click()
            link.remove()
            setTimeout(() => URL.revokeObjectURL(url), 1000)
            setNotice(`${selectedSchemaIds.length} schema${selectedSchemaIds.length === 1 ? "" : "s"} exported`)
        } catch (error) {
            setNotice(error instanceof Error ? error.message : "Failed to export schemas")
        } finally { setExporting(false) }
    }

    const handleImport = async () => {
        if (!importFile || importing) return
        setImporting(true)
        setNotice(null)
        try {
            const token = localStorage.getItem("token")
            const form = new FormData()
            form.append("file", importFile)
            form.append("on_conflict", importConflict)
            const response = await fetch(`${getApiBaseUrl()}/schemas/import`, {
                method: "POST",
                headers: token ? { Authorization: `Bearer ${token}` } : undefined,
                body: form,
            })
            const payload = await response.json().catch(() => null)
            if (!response.ok) throw new Error(payload?.detail?.message || payload?.detail || "Failed to import schemas")
            setShowImportModal(false)
            resetImportFile()
            setSelectedSchemaIds([])
            await fetchSchemas()
            setNotice(`${payload.count} schema${payload.count === 1 ? "" : "s"} imported`)
        } catch (error) {
            setNotice(error instanceof Error ? error.message : "Failed to import schemas")
        } finally { setImporting(false) }
    }

    const fetchSchemas = async () => {
        try {
            const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
            const res = await fetch(`${getApiBaseUrl()}/schemas/`, {
                headers: token ? { Authorization: `Bearer ${token}` } : undefined,
            })
            if (res.ok) {
                const nextSchemas: Schema[] = await res.json()
                setSchemas(nextSchemas)
                const availableIds = new Set(nextSchemas.map((schema) => schema.id))
                setSelectedSchemaIds((current) => current.filter((id) => availableIds.has(id)))
            }
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
            <Modal isOpen={showImportModal} onClose={closeImportModal} title="Import Schemas">
                <div className="space-y-4">
                    <input
                        ref={importInputRef}
                        type="file"
                        accept=".json,application/json"
                        className="hidden"
                        onChange={(event) => setImportFile(event.target.files?.[0] || null)}
                    />
                    <button
                        type="button"
                        onClick={() => importInputRef.current?.click()}
                        className="flex w-full items-center gap-3 rounded-md border border-dashed border-slate-300 px-4 py-5 text-left hover:border-[#2786C2] hover:bg-slate-50"
                    >
                        <FileText className="h-5 w-5 text-slate-500" />
                        <span className="min-w-0">
                            <span className="block text-sm font-medium text-slate-800">{importFile?.name || "Choose a schema package"}</span>
                            <span className="block text-xs text-slate-500">InsightDOC JSON package, up to 5 MB</span>
                        </span>
                    </button>
                    <label className="block space-y-1.5 text-sm font-medium text-slate-700">
                        If a schema name already exists
                        <select value={importConflict} onChange={(event) => setImportConflict(event.target.value as typeof importConflict)} className="h-10 w-full rounded-md border border-slate-300 bg-white px-3 text-sm font-normal">
                            <option value="suffix">Create a copy with an imported suffix</option>
                            <option value="skip">Skip the existing schema</option>
                            <option value="error">Stop and show the conflicts</option>
                        </select>
                    </label>
                    <div className="flex justify-end gap-2 border-t pt-4">
                        <Button variant="outline" onClick={closeImportModal} disabled={importing}>Cancel</Button>
                        <Button onClick={handleImport} disabled={!importFile || importing}>
                            {importing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
                            {importing ? "Importing..." : "Import"}
                        </Button>
                    </div>
                </div>
            </Modal>

            {/* Header */}
            <div className="flex items-center justify-between">
                <div>
                    <h2 className="text-2xl font-bold tracking-tight">Document Schemas</h2>
                    <p className="text-slate-500">Manage extraction schemas for your documents.</p>
                </div>
                <div className="flex flex-wrap justify-end gap-2">
                    <Button variant="outline" onClick={() => setShowImportModal(true)}>
                        <Upload className="h-4 w-4" /> Import
                    </Button>
                    <Button variant="outline" onClick={handleExportSelected} disabled={!selectedSchemaIds.length || exporting}>
                        {exporting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
                        {exporting ? "Exporting..." : `Export${selectedSchemaIds.length ? ` (${selectedSchemaIds.length})` : ""}`}
                    </Button>
                    <Button onClick={() => setShowCreateModal(true)}>
                        <Plus className="h-4 w-4" /> Create Schema
                    </Button>
                </div>
            </div>

            {notice && (
                <div role="status" className="flex items-center justify-between rounded-md border border-blue-100 bg-blue-50 px-3 py-2 text-sm text-blue-800">
                    <span>{notice}</span>
                    <button type="button" aria-label="Dismiss notification" onClick={() => setNotice(null)}><X className="h-4 w-4" /></button>
                </div>
            )}

            {/* Search and filters */}
            {schemas.length > 0 && (
                <div className="space-y-3">
                    <div className="relative">
                        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                        <input
                            type="text"
                            placeholder="Search schemas by name, description, or type..."
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                            className="w-full rounded-lg border border-slate-300 py-2 pl-10 pr-4 text-sm focus:border-transparent focus:outline-none focus:ring-2 focus:ring-blue-500"
                        />
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                        <div className="flex items-center gap-1.5 text-sm font-medium text-slate-600">
                            <ListFilter className="h-4 w-4" />
                            Filter
                        </div>
                        <select
                            aria-label="Filter by document type"
                            value={documentTypeFilter}
                            onChange={(event) => setDocumentTypeFilter(event.target.value)}
                            className="h-9 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
                        >
                            <option value="all">All document types</option>
                            {documentTypes.map((type) => <option key={type} value={type}>{type}</option>)}
                        </select>
                        <select
                            aria-label="Filter by extraction pipeline"
                            value={pipelineFilter}
                            onChange={(event) => setPipelineFilter(event.target.value as ExtractionProfile | "all")}
                            className="h-9 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
                        >
                            <option value="all">All pipelines</option>
                            <option value="anydoc_hybrid">AnyDoc hybrid</option>
                            <option value="legacy">Legacy</option>
                        </select>
                        <div className="ml-auto flex items-center gap-1.5 text-sm font-medium text-slate-600">
                            <ArrowDownAZ className="h-4 w-4" />
                            Sort by
                        </div>
                        <select
                            aria-label="Sort schemas"
                            value={sortBy}
                            onChange={(event) => setSortBy(event.target.value as SchemaSort)}
                            className="h-9 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
                        >
                            <option value="updated_desc">Recently updated</option>
                            <option value="updated_asc">Oldest updated</option>
                            <option value="name_asc">Name A-Z</option>
                            <option value="name_desc">Name Z-A</option>
                            <option value="fields_desc">Most fields</option>
                            <option value="fields_asc">Fewest fields</option>
                        </select>
                        {hasActiveFilters && (
                            <Button type="button" variant="ghost" size="sm" onClick={clearFilters}>
                                Clear filters
                            </Button>
                        )}
                        {manageableFilteredIds.length > 0 && (
                            <Button type="button" variant="ghost" size="sm" onClick={toggleAllVisible}>
                                {allManageableSelected ? <CheckSquare className="h-4 w-4" /> : <Square className="h-4 w-4" />}
                                {allManageableSelected ? "Clear selection" : "Select visible"}
                            </Button>
                        )}
                    </div>
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
                        {searchQuery ? `No results for "${searchQuery}"` : hasActiveFilters ? "Try changing the filters" : "Try a different search term"}
                    </p>
                </div>
            ) : (
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                    {filteredSchemas.map((schema: Schema) => {
                        const canManage = canManageSchema(schema)
                        const { Icon, color, badgeColor } = getDocumentTypeIcon(schema.document_type)
                        return (
                            <div key={schema.id} className="group relative rounded-lg border bg-white p-4 shadow-sm hover:shadow-md hover:border-slate-300 transition-all">
                                    <div className="flex items-start justify-between mb-3">
                                        <div className={`h-10 w-10 rounded-lg ${color} flex items-center justify-center`}>
                                            <Icon className="h-5 w-5" />
                                        </div>
                                        <div className="flex items-center gap-2">
                                            {canManageSchema(schema) && (
                                                <button type="button" aria-label={`${selectedSchemaIds.includes(schema.id) ? "Deselect" : "Select"} ${schema.name}`} onClick={() => toggleSchemaSelection(schema.id)} className="rounded p-1 text-slate-500 hover:bg-slate-100 hover:text-[#2786C2]">
                                                    {selectedSchemaIds.includes(schema.id) ? <CheckSquare className="h-4 w-4 text-[#2786C2]" /> : <Square className="h-4 w-4" />}
                                                </button>
                                            )}
                                            <span className={`text-xs font-medium px-2 py-0.5 rounded ${badgeColor}`}>
                                                {schema.document_type}
                                            </span>
                                        </div>
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
                                    <span>{schemaActivityDate(schema)
                                        ? new Date(schemaActivityDate(schema)!).toLocaleDateString('en-GB', { day: '2-digit', month: 'short' })
                                        : "-"}
                                    </span>
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
