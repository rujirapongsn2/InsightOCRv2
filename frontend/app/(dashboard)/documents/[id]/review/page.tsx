"use client"

import { useEffect, useState, useMemo } from "react"
import { useParams, useRouter } from "next/navigation"
import Link from "next/link"
import { ArrowLeft, Save, CheckCircle, AlertTriangle, FileText, Image as ImageIcon } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { getApiBaseUrl } from "@/lib/api"
import { editableText, parseTypedValue } from "@/lib/schema-studio"

interface Document {
    id: string
    filename: string
    status: string
    ocr_text: string
    extracted_data: any
    reviewed_data: any
    job_id: string
    mime_type?: string
    schema_id?: string | null
}
type ExtractedEntry = Record<string, any>
type SchemaFieldInfo = { name: string; type: string; required?: boolean; description?: string | null }
type FormField = SchemaFieldInfo & { inSchema: boolean; structured: boolean }

const STRUCTURED_TYPES = new Set(["array", "object", "table"])

/** A single record, or the legacy one-item list, becomes the object that is edited and saved. */
function singleRecord(entries: ExtractedEntry[]): ExtractedEntry | null {
    return entries.length <= 1 ? (entries[0] || {}) : null
}

export default function ReviewDocumentPage() {
    const params = useParams()
    const router = useRouter()
    const documentId = params.id as string
    const [document, setDocument] = useState<Document | null>(null)
    const [formData, setFormData] = useState<ExtractedEntry[]>([])
    const [loading, setLoading] = useState(true)
    const [saving, setSaving] = useState(false)
    const [fileObjectUrl, setFileObjectUrl] = useState<string | null>(null)
    const [schemaFields, setSchemaFields] = useState<SchemaFieldInfo[]>([])
    // Text being edited per field (single-record documents); converted back to typed values on save.
    const [drafts, setDrafts] = useState<Record<string, string>>({})
    const [formError, setFormError] = useState<string | null>(null)

    const normalizeExtractedData = (data: any): ExtractedEntry[] => {
        if (!data) return []

        if (Array.isArray(data)) {
            return data
                .filter((entry) => entry && typeof entry === "object" && !Array.isArray(entry))
                .map((entry) => entry as ExtractedEntry)
        }

        if (typeof data === "string") {
            try {
                const parsed = JSON.parse(data)
                return normalizeExtractedData(parsed)
            } catch {
                return [{ extracted_text: data }]
            }
        }

        if (typeof data === "object") {
            return [data as ExtractedEntry]
        }

        return []
    }

    useEffect(() => {
        const fetchDocument = async () => {
            try {
                const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
                const res = await fetch(`${getApiBaseUrl()}/documents/${documentId}`, {
                    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
                })
                if (res.ok) {
                    const data = await res.json()
                    setDocument(data)
                    // Initialize form data with reviewed data if exists, else extracted data
                    const entries = normalizeExtractedData(data.reviewed_data || data.extracted_data)
                    setFormData(entries)
                    const record = singleRecord(entries)
                    if (record) {
                        setDrafts(Object.fromEntries(Object.entries(record).map(([key, value]) => [
                            key, value !== null && typeof value === "object" ? JSON.stringify(value, null, 2) : editableText(value),
                        ])))
                    }
                    if (data.schema_id) {
                        const schemaRes = await fetch(`${getApiBaseUrl()}/schemas/${data.schema_id}`, {
                            headers: token ? { Authorization: `Bearer ${token}` } : undefined,
                        })
                        if (schemaRes.ok) {
                            const schema = await schemaRes.json()
                            setSchemaFields((schema.fields || []).filter((field: SchemaFieldInfo) => field?.name))
                        }
                    }
                }
            } catch (error) {
                console.error("Failed to fetch document", error)
            } finally {
                setLoading(false)
            }
        }
        fetchDocument()
    }, [documentId])

    // Fetch file with authentication and create object URL
    useEffect(() => {
        if (!document) return

        const fetchFile = async () => {
            try {
                const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
                const res = await fetch(`${getApiBaseUrl()}/documents/${documentId}/file`, {
                    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
                })

                if (res.ok) {
                    const blob = await res.blob()
                    const objectUrl = URL.createObjectURL(blob)
                    setFileObjectUrl(objectUrl)
                }
            } catch (error) {
                console.error("Failed to fetch file", error)
            }
        }

        fetchFile()

        // Cleanup: revoke object URL when component unmounts
        return () => {
            if (fileObjectUrl) {
                URL.revokeObjectURL(fileObjectUrl)
            }
        }
    }, [document, documentId])

    const handleFieldChange = (index: number, key: string, value: any) => {
        setFormData((prev) => {
            const next = [...prev]
            next[index] = { ...(next[index] || {}), [key]: value }
            return next
        })
    }

    const record = useMemo(() => singleRecord(formData), [formData])

    // Every Schema field in Schema order (so values the engine missed can be typed in),
    // then any other keys the document already has.
    const formFields = useMemo<FormField[]>(() => {
        if (!record) return []
        const known = new Set(schemaFields.map((field) => field.name))
        const extra = Object.keys(record).filter((key) => !known.has(key)).map((key) => {
            const value = record[key]
            const structured = value !== null && typeof value === "object"
            return { name: key, type: structured ? "array" : typeof value === "number" ? "number" : "text", inSchema: false, structured }
        })
        return [
            ...schemaFields.map((field) => ({
                ...field, inSchema: true,
                structured: STRUCTURED_TYPES.has(field.type) || (record[field.name] !== null && typeof record[field.name] === "object"),
            })),
            ...extra,
        ]
    }, [record, schemaFields])

    const buildRecord = (): ExtractedEntry | null => {
        // Nothing extracted and no schema to fill in: keep what was saved before ([]).
        if (!record || formFields.length === 0) return null
        const out: ExtractedEntry = { ...record }
        for (const field of formFields) {
            const text = drafts[field.name] ?? ""
            if (field.structured) {
                if (!text.trim()) { out[field.name] = null; continue }
                try {
                    out[field.name] = JSON.parse(text)
                } catch {
                    throw new Error(`${field.name}: ข้อมูลตาราง/รายการต้องเป็น JSON ที่ถูกต้อง`)
                }
            } else {
                const typed = parseTypedValue(text, field.type)
                // parseTypedValue keeps unparseable text as-is; a number field must not store "1,2OO".
                if ((field.type === "number" || field.type === "currency") && typed !== undefined && typeof typed !== "number") {
                    throw new Error(`${field.name}: ต้องเป็นตัวเลข เช่น 1250 หรือ 1,250.00`)
                }
                out[field.name] = typed === undefined ? null : typed
            }
        }
        return out
    }

    const handleSave = async (markAsReviewed: boolean = false) => {
        let reviewed: ExtractedEntry | ExtractedEntry[]
        try {
            reviewed = buildRecord() ?? formData
        } catch (error) {
            setFormError(error instanceof Error ? error.message : "ข้อมูลไม่ถูกต้อง")
            return
        }
        setFormError(null)
        setSaving(true)
        try {
            const payload = {
                // Saved as one object, like the Jobs review, so accuracy reports can read it.
                reviewed_data: reviewed,
                status: markAsReviewed ? "reviewed" : undefined
            }

            const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
            const res = await fetch(`${getApiBaseUrl()}/documents/${documentId}`, {
                method: "PUT",
                headers: {
                    "Content-Type": "application/json",
                    ...(token ? { Authorization: `Bearer ${token}` } : {})
                },
                body: JSON.stringify(payload)
            })

            if (res.ok) {
                const updatedDoc = await res.json()
                setDocument(updatedDoc)
                if (markAsReviewed) {
                    router.push(`/jobs/${updatedDoc.job_id}`)
                } else {
                    alert("Saved successfully")
                }
            } else {
                alert("Failed to save")
            }
        } catch (error) {
            console.error("Error saving document", error)
        } finally {
            setSaving(false)
        }
    }

    const isPDF = useMemo(() => {
        return document?.mime_type === 'application/pdf' || document?.filename.toLowerCase().endsWith('.pdf')
    }, [document])

    const isImage = useMemo(() => {
        if (!document) return false
        const imageTypes = ['image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/webp']
        const imageExts = ['.jpg', '.jpeg', '.png', '.gif', '.webp']
        return imageTypes.includes(document.mime_type || '') ||
               imageExts.some(ext => document.filename.toLowerCase().endsWith(ext))
    }, [document])

    if (loading) return <div>Loading...</div>
    if (!document) return <div>Document not found</div>

    return (
        <div className="h-[calc(100vh-4rem)] flex flex-col">
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b bg-white">
                <div className="flex items-center gap-4">
                    <Link href={`/jobs/${document.job_id}`}>
                        <Button variant="ghost" size="icon">
                            <ArrowLeft className="h-4 w-4" />
                        </Button>
                    </Link>
                    <div>
                        <h2 className="text-lg font-semibold">{document.filename}</h2>
                        <div className="flex items-center gap-2 text-sm text-slate-500">
                            <span className="capitalize">{document.status.replace('_', ' ')}</span>
                        </div>
                    </div>
                </div>
                <div className="flex gap-2">
                    <Button variant="outline" onClick={() => handleSave(false)} disabled={saving}>
                        <Save className="mr-2 h-4 w-4" />
                        Save Draft
                    </Button>
                    <Button onClick={() => handleSave(true)} disabled={saving}>
                        <CheckCircle className="mr-2 h-4 w-4" />
                        Mark as Reviewed
                    </Button>
                </div>
            </div>

            {/* Content */}
            <div className="flex-1 flex overflow-hidden">
                {/* Left: Document Viewer */}
                <div className="w-1/2 bg-slate-100 border-r overflow-auto">
                    <div className="h-full flex flex-col">
                        {/* Document Display */}
                        <div className="flex-1 overflow-auto bg-slate-900 flex items-center justify-center p-4">
                            {!fileObjectUrl ? (
                                <div className="text-center text-slate-400">
                                    <FileText className="h-16 w-16 mx-auto mb-4 opacity-50 animate-pulse" />
                                    <p className="text-sm">Loading document...</p>
                                </div>
                            ) : isImage ? (
                                <img
                                    src={fileObjectUrl}
                                    alt={document.filename}
                                    className="max-w-full max-h-full object-contain"
                                    onError={(e) => {
                                        console.error('Failed to load image:', e)
                                    }}
                                />
                            ) : isPDF ? (
                                <div className="w-full h-full bg-white">
                                    <iframe
                                        src={fileObjectUrl}
                                        className="w-full h-full border-0"
                                        title={document.filename}
                                    />
                                </div>
                            ) : (
                                <div className="text-center text-slate-400">
                                    <FileText className="h-16 w-16 mx-auto mb-4 opacity-50" />
                                    <p className="text-sm">
                                        {document.mime_type ? `Unsupported file type: ${document.mime_type}` : 'Unknown file type'}
                                    </p>
                                    <p className="text-xs mt-2">{document.filename}</p>
                                </div>
                            )}
                        </div>

                        {/* OCR Text Panel (Collapsible) */}
                        {document.ocr_text && (
                            <details className="bg-white border-t">
                                <summary className="px-4 py-3 cursor-pointer hover:bg-slate-50 flex items-center gap-2 text-sm font-medium">
                                    <FileText className="h-4 w-4" />
                                    OCR Extracted Text ({document.ocr_text.length} characters)
                                </summary>
                                <div className="px-4 py-3 max-h-48 overflow-auto">
                                    <pre className="text-xs whitespace-pre-wrap text-slate-600 font-mono">
                                        {document.ocr_text}
                                    </pre>
                                </div>
                            </details>
                        )}
                    </div>
                </div>

                {/* Right: Extraction Form */}
                <div className="w-1/2 bg-white p-6 overflow-auto">
                    <h3 className="font-semibold mb-6">Extracted Data</h3>

                    {formError && <p role="alert" className="mb-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{formError}</p>}
                    {record && formFields.length > 0 ? (
                        <div className="space-y-4">
                            {formFields.map((field) => {
                                const inputId = `review-field-${field.name}`
                                const text = drafts[field.name] ?? ""
                                const missing = !(field.name in record) || record[field.name] === null || record[field.name] === ""
                                return (
                                    <div key={field.name} className="space-y-1">
                                        <label htmlFor={inputId} className="flex flex-wrap items-center gap-2 text-sm font-medium">
                                            {field.name}
                                            {field.required && <span className="rounded bg-red-50 px-1.5 py-0.5 text-xs text-red-700">Required</span>}
                                            {field.inSchema && missing && <span className="rounded bg-amber-50 px-1.5 py-0.5 text-xs text-amber-800">Not found — type the value if the document has it</span>}
                                            {!field.inSchema && schemaFields.length > 0 && <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">Not in schema</span>}
                                        </label>
                                        {field.description && <p className="text-xs text-slate-500">{field.description}</p>}
                                        {field.structured ? (
                                            <textarea id={inputId} value={text} rows={Math.min(12, Math.max(3, text.split("\n").length))}
                                                onChange={(e) => setDrafts((prev) => ({ ...prev, [field.name]: e.target.value }))}
                                                className="w-full rounded-md border border-slate-300 px-3 py-2 font-mono text-xs" />
                                        ) : (
                                            <Input id={inputId} value={text}
                                                inputMode={field.type === "number" || field.type === "currency" ? "decimal" : undefined}
                                                onChange={(e) => setDrafts((prev) => ({ ...prev, [field.name]: e.target.value }))} />
                                        )}
                                    </div>
                                )
                            })}
                        </div>
                    ) : formData.length === 0 ? (
                        <div className="flex flex-col items-center justify-center p-8 text-slate-500 border border-dashed rounded-lg">
                            <AlertTriangle className="h-8 w-8 mb-2 text-amber-500" />
                            <p>No data extracted yet.</p>
                        </div>
                    ) : (
                        <div className="space-y-6">
                            {formData.map((entry, idx) => (
                                <div key={idx} className="border rounded-md p-4 space-y-3">
                                    <div className="text-xs font-semibold text-slate-500 uppercase">
                                        Record {idx + 1}
                                    </div>
                                    {Object.entries(entry).map(([key, value]) => (
                                        <div key={key} className="space-y-2">
                                            <label className="text-sm font-medium capitalize">{key.replace(/_/g, ' ')}</label>
                                            <Input
                                                value={typeof value === "object" ? JSON.stringify(value) : (value ?? "")}
                                                onChange={(e) => handleFieldChange(idx, key, e.target.value)}
                                            />
                                        </div>
                                    ))}
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            </div>
        </div>
    )
}
