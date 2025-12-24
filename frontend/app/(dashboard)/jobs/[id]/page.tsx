"use client"

import { useEffect, useState, useRef, useMemo } from "react"
import { useParams } from "next/navigation"
import Link from "next/link"
import { ArrowLeft, Upload, FileText, Loader2, Eye, X, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Modal } from "@/components/ui/modal"
import { Textarea } from "@/components/ui/textarea"
import { Input } from "@/components/ui/input"
import dynamic from "next/dynamic"
import { getApiBaseUrl } from "@/lib/api"

const PDFViewer = dynamic(
    () => import("@/components/document/PDFViewer").then(mod => mod.PDFViewer),
    {
        ssr: false,
        loading: () => <div className="flex items-center justify-center h-full text-sm text-slate-500">Loading document...</div>
    }
)

interface Job {
    id: string
    name: string
    description: string
    status: string
    created_at?: string
    user_name?: string
}

interface Document {
    id: string
    filename: string
    status: string
    schema_id?: string
    extracted_data?: Record<string, any> | Record<string, any>[]
    reviewed_data?: Record<string, any> | Record<string, any>[]
    ocr_text?: string
    uploaded_at?: string
    processing_error?: string
}
type ExtractedEntry = Record<string, any>

type IntegrationType = "api" | "workflow" | "llm"

interface IntegrationConfig {
    method?: "POST" | "PUT"
    endpoint?: string
    authHeader?: string
    payloadTemplate?: string
    webhookUrl?: string
    parameters?: string
    model?: string
    headersJson?: string
    // LLM-specific fields
    apiKey?: string
    baseUrl?: string
    instructions?: string
    reasoningEffort?: string
}

interface Integration {
    id: string
    name: string
    type: IntegrationType
    description?: string
    status: "active" | "paused"
    config: IntegrationConfig
}

interface Schema {
    id: string
    name: string
    fields: Array<{
        name: string
        type: string
        description: string
        required: boolean
    }>
}

export default function JobDetailPage() {
    const params = useParams()
    const jobId = params.id as string
    const [job, setJob] = useState<Job | null>(null)
    const [documents, setDocuments] = useState<Document[]>([])
    const [schemas, setSchemas] = useState<Schema[]>([])
    const [uploading, setUploading] = useState(false)
    const [loading, setLoading] = useState(true)
    const [processingDocs, setProcessingDocs] = useState<Set<string>>(new Set())
    const [reviewDoc, setReviewDoc] = useState<Document | null>(null)
    const [editedOcrText, setEditedOcrText] = useState("")
    const [editedData, setEditedData] = useState<ExtractedEntry[]>([])
    const fileInputRef = useRef<HTMLInputElement>(null)
    const [showIntegrationModal, setShowIntegrationModal] = useState(false)
    const [selectedIntegration, setSelectedIntegration] = useState<string>("")
    const [sendingIntegration, setSendingIntegration] = useState(false)
    const [integrationMessage, setIntegrationMessage] = useState<string | null>(null)
    const [integrations, setIntegrations] = useState<Integration[]>([])
    // LLM Results for export
    const [llmResults, setLlmResults] = useState<Array<{ id: string; filename: string; output: string; success: boolean; error?: string }>>([])
    const [showLlmResultsModal, setShowLlmResultsModal] = useState(false)
    // Delete confirmation
    const [deleteConfirmDoc, setDeleteConfirmDoc] = useState<Document | null>(null)
    const [deleting, setDeleting] = useState(false)
    // Image viewer state
    const [imageUrl, setImageUrl] = useState<string | null>(null)

    const apiBase = getApiBaseUrl()

    // Function to load integrations from API
    const loadIntegrations = async () => {
        const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
        if (!token) return

        try {
            const { getActiveIntegrations } = await import("@/lib/integrations-api")
            const activeIntegrations = await getActiveIntegrations(token)
            setIntegrations(activeIntegrations)
        } catch (error) {
            console.error("Failed to load integrations:", error)
            // Fallback to empty array on error
            setIntegrations([])
        }
    }

    // Load integrations on mount
    useEffect(() => {
        loadIntegrations()
    }, [])

    // Reload integrations when integration modal opens to get latest data
    useEffect(() => {
        if (showIntegrationModal) {
            loadIntegrations()
        }
    }, [showIntegrationModal])

    const fetchJobData = async () => {
        try {
            const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
            const jobRes = await fetch(`${apiBase}/jobs/${jobId}`, {
                headers: token ? { Authorization: `Bearer ${token}` } : undefined,
            })
            if (jobRes.ok) {
                setJob(await jobRes.json())
            }
        } catch (error) {
            console.error("Failed to fetch job data", error)
        }
    }

    const fetchDocuments = async () => {
        try {
            const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
            const docsRes = await fetch(`${apiBase}/documents/job/${jobId}`, {
                headers: token ? { Authorization: `Bearer ${token}` } : undefined,
            })
            if (docsRes.ok) {
                const docs = await docsRes.json()
                setDocuments(docs)
            }
        } catch (error) {
            console.error("Failed to fetch documents", error)
        }
    }

    const fetchSchemas = async () => {
        try {
            const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
            const res = await fetch(`${apiBase}/schemas/`, {
                headers: token ? { Authorization: `Bearer ${token}` } : undefined,
            })
            if (res.ok) {
                const data = await res.json()
                setSchemas(data)
            }
        } catch (error) {
            console.error("Failed to fetch schemas", error)
        }
    }

    useEffect(() => {
        const hydrate = async () => {
            setLoading(true)
            await Promise.all([fetchJobData(), fetchDocuments(), fetchSchemas()])
            setLoading(false)
        }

        hydrate()
    }, [jobId])

    const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
        if (!e.target.files || e.target.files.length === 0) return

        setUploading(true)
        const file = e.target.files[0]
        const formData = new FormData()
        formData.append("file", file)
        formData.append("job_id", jobId)

        try {
            const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
            const res = await fetch(`${apiBase}/documents/upload`, {
                method: "POST",
                headers: token ? { Authorization: `Bearer ${token}` } : undefined,
                body: formData
            })

            if (res.ok) {
                await fetchDocuments()
            } else {
                alert("Upload failed")
            }
        } catch (error) {
            console.error("Upload error", error)
            alert("Upload error")
        } finally {
            setUploading(false)
            if (fileInputRef.current) {
                fileInputRef.current.value = ""
            }
        }
    }

    const handleSchemaChange = (docId: string, schemaId: string) => {
        setDocuments(prev => prev.map(doc =>
            doc.id === docId ? { ...doc, schema_id: schemaId } : doc
        ))
    }

    const handleProcess = async (docId: string) => {
        const doc = documents.find(d => d.id === docId)
        if (!doc || !doc.schema_id) {
            alert("Please select a schema first")
            return
        }

        setProcessingDocs(prev => new Set(prev).add(docId))

        try {
            const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
            // Dispatch the background task
            const res = await fetch(`${apiBase}/documents/${docId}/process`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    ...(token ? { Authorization: `Bearer ${token}` } : {})
                },
                body: JSON.stringify({ schema_id: doc.schema_id })
            })

            if (!res.ok) {
                alert("Failed to start processing")
                setProcessingDocs(prev => {
                    const newSet = new Set(prev)
                    newSet.delete(docId)
                    return newSet
                })
                return
            }

            // Poll for task completion
            const pollInterval = setInterval(async () => {
                try {
                    const statusRes = await fetch(`${apiBase}/documents/${docId}/task-status`, {
                        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
                    })
                    if (!statusRes.ok) {
                        console.error("[Poll] Failed to check status")
                        clearInterval(pollInterval)
                        setProcessingDocs(prev => {
                            const newSet = new Set(prev)
                            newSet.delete(docId)
                            return newSet
                        })
                        return
                    }

                    const status = await statusRes.json()
                    console.log(`[Poll] Document ${docId} status: ${status.status}`)

                    // Check if processing is complete
                    if (status.status === "extraction_completed" || status.status === "reviewed" || status.status === "failed") {
                        console.log(`[Poll] Processing complete for ${docId}, refreshing documents...`)
                        clearInterval(pollInterval)

                        // Remove from processing set immediately to avoid race conditions
                        setProcessingDocs(prev => {
                            const newSet = new Set(prev)
                            newSet.delete(docId)
                            return newSet
                        })

                        await fetchDocuments()
                        console.log(`[Poll] Documents refreshed`)
                    }
                } catch (pollError) {
                    console.error("Polling error", pollError)
                    clearInterval(pollInterval)
                    setProcessingDocs(prev => {
                        const newSet = new Set(prev)
                        newSet.delete(docId)
                        return newSet
                    })
                }
            }, 2000)  // Poll every 2 seconds

        } catch (error) {
            console.error("Processing error", error)
            alert("Processing error")
            setProcessingDocs(prev => {
                const newSet = new Set(prev)
                newSet.delete(docId)
                return newSet
            })
        }
    }

    const handleProcessAll = async () => {
        const docsToProcess = documents.filter(d => d.schema_id && d.status === "uploaded")

        for (const doc of docsToProcess) {
            await handleProcess(doc.id)
        }
    }

    const handleDeleteDocument = async () => {
        if (!deleteConfirmDoc) return

        try {
            setDeleting(true)
            const token = typeof window !== "undefined" ? localStorage.getItem("token") : null

            const response = await fetch(`${apiBase}/documents/${deleteConfirmDoc.id}`, {
                method: "DELETE",
                headers: {
                    Authorization: `Bearer ${token}`,
                },
            })

            if (!response.ok) {
                throw new Error("Failed to delete document")
            }

            // Refresh documents list
            await fetchDocuments()
            setDeleteConfirmDoc(null)
        } catch (error) {
            console.error("Delete error:", error)
            alert("Failed to delete document. Please try again.")
        } finally {
            setDeleting(false)
        }
    }

    const normalizeExtractedData = (data: unknown): ExtractedEntry[] => {
        if (!data) return []

        // Handle 'answer' wrapper from some API responses
        if (typeof data === "object" && data !== null && 'answer' in data) {
            console.log("[normalizeExtractedData] Unwrapping 'answer' field")
            return normalizeExtractedData((data as any).answer)
        }

        // Handle 'structured_output' wrapper
        if (typeof data === "object" && data !== null && 'structured_output' in data) {
            console.log("[normalizeExtractedData] Unwrapping 'structured_output' field")
            return normalizeExtractedData((data as any).structured_output)
        }

        // Handle 'data' wrapper
        if (typeof data === "object" && data !== null && 'data' in data && Object.keys(data).length === 1) {
            console.log("[normalizeExtractedData] Unwrapping 'data' field")
            return normalizeExtractedData((data as any).data)
        }

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

    const handleReview = (doc: Document) => {
        setReviewDoc(doc)
        setEditedOcrText(doc.ocr_text || "")
        // Normalize extracted data so multi-page/JSON-string responses display correctly
        const normalizedData = normalizeExtractedData(doc.reviewed_data || doc.extracted_data)
        setEditedData(normalizedData)
    }

    const handleSaveReview = async () => {
        if (!reviewDoc) return

        try {
            const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
            const res = await fetch(`${apiBase}/documents/${reviewDoc.id}`, {
                method: "PUT",
                headers: {
                    "Content-Type": "application/json",
                    ...(token ? { Authorization: `Bearer ${token}` } : {})
                },
                body: JSON.stringify({
                    ocr_text: editedOcrText,
                    extracted_data: editedData,
                    status: "reviewed"
                })
            })

            if (res.ok) {
                await fetchDocuments()
                setReviewDoc(null)
            } else {
                alert("Save failed")
            }
        } catch (error) {
            console.error("Save error", error)
            alert("Save error")
        }
    }

    const handleDataFieldChange = (index: number, fieldName: string, value: any) => {
        setEditedData(prev => {
            const next = [...prev]
            next[index] = { ...(next[index] || {}), [fieldName]: value }
            return next
        })
    }

    const handleSendToIntegration = async () => {
        if (!job || !selectedIntegration) return

        setSendingIntegration(true)
        setIntegrationMessage(null)

        const payload = {
            integration_id: selectedIntegration,
            job_name: job.name,
            documents: documents.map(doc => ({
                id: String(doc.id),
                filename: doc.filename || "unnamed",
                data: doc.reviewed_data || doc.extracted_data || {}
            }))
        }

        try {
            const token = localStorage.getItem("token")
            const res = await fetch(`${apiBase}/integrations/send`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "Authorization": `Bearer ${token}`
                },
                body: JSON.stringify(payload)
            })

            if (!res.ok) {
                const errData = await res.json().catch(() => ({}))
                const errMsg = typeof errData.detail === "string" ? errData.detail : JSON.stringify(errData.detail || errData)
                throw new Error(errMsg || `Integration send failed: ${res.status}`)
            }

            const result = await res.json()

            const integration = integrations.find(int => int.id === selectedIntegration)

            if (integration?.type === "llm" && result.results) {
                setLlmResults(result.results)
                setShowLlmResultsModal(true)
                setShowIntegrationModal(false)
                setIntegrationMessage("LLM processing completed")
            } else {
                setIntegrationMessage(result.message || "Sent successfully")
            }
        } catch (err: any) {
            setIntegrationMessage(err?.message || "Failed to send")
        } finally {
            setSendingIntegration(false)
        }
    }

    // Fetch image with auth when review modal opens for image files
    useEffect(() => {
        if (!reviewDoc) {
            // Clean up previous image URL
            if (imageUrl) {
                URL.revokeObjectURL(imageUrl)
                setImageUrl(null)
            }
            return
        }

        const fileExt = reviewDoc.filename.toLowerCase().split('.').pop() || ''
        const imageExtensions = ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'tiff', 'webp']

        if (imageExtensions.includes(fileExt)) {
            const fetchImage = async () => {
                try {
                    const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
                    const response = await fetch(`${apiBase}/documents/${reviewDoc.id}/file`, {
                        headers: {
                            Authorization: `Bearer ${token}`,
                        },
                    })

                    if (response.ok) {
                        const blob = await response.blob()
                        const url = URL.createObjectURL(blob)
                        setImageUrl(url)
                    } else {
                        console.error("Failed to fetch image:", response.status)
                    }
                } catch (error) {
                    console.error("Failed to load image:", error)
                }
            }

            fetchImage()
        }

        // Cleanup function
        return () => {
            if (imageUrl) {
                URL.revokeObjectURL(imageUrl)
            }
        }
    }, [reviewDoc])

    // Memoize PDF URL to prevent unnecessary reloads; must stay before any early returns to keep hook order stable
    const pdfFileUrl = useMemo(() => {
        return reviewDoc ? `${apiBase}/documents/${reviewDoc.id}/file` : ""
    }, [reviewDoc?.id, apiBase])

    if (loading) return <div>Loading...</div>
    if (!job) return <div>Job not found</div>

    const createdDateTime = job.created_at ? new Date(job.created_at).toLocaleString('th-TH', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit'
    }) : new Date().toLocaleString('th-TH')
    const allHaveSchema = documents.length > 0 && documents.every(d => d.schema_id)

    // Helper function to get status badge color
    const getStatusColor = (status: string) => {
        switch (status.toLowerCase()) {
            case 'uploaded':
                return 'bg-amber-100 text-amber-700 border-amber-200'
            case 'processing':
                return 'bg-blue-100 text-blue-700 border-blue-200'
            case 'extraction_completed':
                return 'bg-emerald-100 text-emerald-700 border-emerald-200'
            case 'reviewed':
                return 'bg-purple-100 text-purple-700 border-purple-200'
            default:
                return 'bg-slate-100 text-slate-700 border-slate-200'
        }
    }

    // Calculate document counts by status
    const docCounts = {
        uploaded: documents.filter(d => d.status === 'uploaded').length,
        processing: documents.filter(d => d.status === 'processing').length,
        extraction_completed: documents.filter(d => d.status === 'extraction_completed').length,
        reviewed: documents.filter(d => d.status === 'reviewed').length
    }
    const allDocsReviewed = documents.length > 0 && documents.every(d => d.status === "reviewed")

    return (
        <div className="space-y-6">
            <div className="flex items-center space-x-4">
                <Link href="/jobs">
                    <Button variant="ghost" size="icon">
                        <ArrowLeft className="h-4 w-4" />
                    </Button>
                </Link>
                <div>
                    <h2 className="text-2xl font-bold tracking-tight">{job.name}</h2>
                    <p className="text-slate-500">{job.description}</p>
                </div>
                <div className="ml-auto">
                    <span className={`px-3 py-1 rounded-full text-sm font-medium ${job.status === 'completed' ? 'bg-green-100 text-green-800' :
                        job.status === 'processing' ? 'bg-blue-100 text-blue-800' :
                            'bg-slate-100 text-slate-800'
                        }`}>
                        {job.status.toUpperCase()}
                    </span>
                </div>
            </div>

            <div className="grid gap-6 md:grid-cols-3">
                <div className="md:col-span-2 space-y-6">
                    <div className="rounded-lg border bg-white p-6 shadow-sm">
                        <div className="flex items-center justify-between mb-4">
                            <h3 className="text-lg font-semibold">Documents</h3>
                            <div className="flex gap-2">
                                {allHaveSchema && documents.some(d => d.status === "uploaded") && (
                                    <Button onClick={handleProcessAll} variant="outline">
                                        Process All
                                    </Button>
                                )}
                                <input
                                    type="file"
                                    ref={fileInputRef}
                                    className="hidden"
                                    onChange={handleFileUpload}
                                    accept=".pdf,image/*"
                                />
                                <Button onClick={() => fileInputRef.current?.click()} disabled={uploading}>
                                    <Upload className="mr-2 h-4 w-4" />
                                    {uploading ? "Uploading..." : "Upload Document"}
                                </Button>
                            </div>
                        </div>

                        {documents.length === 0 ? (
                            <div className="text-center py-12 text-slate-500 border-2 border-dashed rounded-lg">
                                <FileText className="h-10 w-10 mx-auto mb-3 text-slate-300" />
                                <p>No documents uploaded yet.</p>
                            </div>
                        ) : (
                            <div className="space-y-3">
                                {documents.map(doc => {
                                    const isProcessing = processingDocs.has(doc.id) || doc.status === "processing"
                                    const canReview = doc.status === "extraction_completed" || doc.status === "reviewed"

                                    return (
                                        <div key={doc.id} className="p-4 border rounded-md bg-slate-50">
                                            <div className="flex items-center gap-3 mb-3">
                                                <FileText className="h-5 w-5 text-slate-500" />
                                                <span className="font-medium text-sm flex-1">{doc.filename}</span>
                                                <span className={`text-xs px-2.5 py-1 rounded-full border font-medium capitalize ${getStatusColor(doc.status)}`}>
                                                    {doc.status.replace(/_/g, ' ')}
                                                </span>
                                            </div>

                                            <div className="flex items-center gap-2">
                                                <select
                                                    className="flex h-9 w-full rounded-md border border-slate-200 bg-white px-3 py-1 text-sm"
                                                    value={doc.schema_id || ""}
                                                    onChange={(e) => handleSchemaChange(doc.id, e.target.value)}
                                                    disabled={doc.status !== "uploaded"}
                                                >
                                                    <option value="">Select Schema...</option>
                                                    {schemas.map(schema => (
                                                        <option key={schema.id} value={schema.id}>{schema.name}</option>
                                                    ))}
                                                </select>

                                                {(doc.status === "uploaded" || doc.status === "queued" || doc.status === "failed") && (
                                                    <>
                                                        <Button
                                                            onClick={() => handleProcess(doc.id)}
                                                            disabled={!doc.schema_id || isProcessing}
                                                            size="sm"
                                                            variant={doc.status === "failed" ? "outline" : "default"}
                                                            className={doc.status === "failed" ? "bg-[rgba(243,144,63,0.1)] text-[rgb(243,144,63)] border-[rgb(243,144,63)] hover:bg-[rgba(243,144,63,0.2)]" : ""}
                                                        >
                                                            {isProcessing ? (
                                                                <>
                                                                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                                                                    {doc.status === "failed" ? "Retrying..." : "Processing"}
                                                                </>
                                                            ) : (
                                                                doc.status === "uploaded" ? "Process" : "Retry"
                                                            )}
                                                        </Button>
                                                        {doc.status === "failed" && (
                                                            <Button
                                                                onClick={() => setDeleteConfirmDoc(doc)}
                                                                size="sm"
                                                                variant="outline"
                                                                className="text-red-600 hover:text-red-700 hover:bg-red-50"
                                                            >
                                                                <Trash2 className="h-4 w-4" />
                                                            </Button>
                                                        )}
                                                    </>
                                                )}

                                                {canReview && (
                                                    <Button
                                                        onClick={() => handleReview(doc)}
                                                        size="sm"
                                                        variant="outline"
                                                    >
                                                        <Eye className="mr-2 h-4 w-4" />
                                                        Review
                                                    </Button>
                                                )}
                                            </div>
                                        </div>
                                    )
                                })}
                            </div>
                        )}
                    </div>
                </div>

                <div className="space-y-6">
                    <div className="rounded-lg border bg-white p-6 shadow-sm">
                        <h3 className="text-lg font-semibold mb-4">Job Info</h3>
                        <div className="space-y-2 text-sm">
                            <div className="flex justify-between py-2 border-b">
                                <span className="text-slate-500">Status</span>
                                <span className="font-medium capitalize">{job.status}</span>
                            </div>
                            {job.user_name && (
                                <div className="flex justify-between py-2 border-b">
                                    <span className="text-slate-500">Uploaded By</span>
                                    <span className="font-medium">{job.user_name}</span>
                                </div>
                            )}
                            <div className="flex justify-between py-2 border-b">
                                <span className="text-slate-500">Created</span>
                                <span className="font-medium">{createdDateTime}</span>
                            </div>
                            <div className="flex justify-between py-2 border-b">
                                <span className="text-slate-500">Documents</span>
                                <span className="font-medium">{documents.length}</span>
                            </div>
                        </div>

                        {/* Document Status Breakdown */}
                        {documents.length > 0 && (
                            <div className="mt-6 pt-4 border-t">
                                <h4 className="text-sm font-semibold text-slate-700 mb-3">Status Breakdown</h4>
                                <div className="space-y-2 text-sm">
                                    {docCounts.uploaded > 0 && (
                                        <div className="flex items-center justify-between py-1.5">
                                            <div className="flex items-center gap-2">
                                                <div className="w-2 h-2 rounded-full bg-amber-500"></div>
                                                <span className="text-slate-600">Uploaded</span>
                                            </div>
                                            <span className="font-medium text-slate-900">{docCounts.uploaded}</span>
                                        </div>
                                    )}
                                    {docCounts.processing > 0 && (
                                        <div className="flex items-center justify-between py-1.5">
                                            <div className="flex items-center gap-2">
                                                <div className="w-2 h-2 rounded-full bg-blue-500"></div>
                                                <span className="text-slate-600">Processing</span>
                                            </div>
                                            <span className="font-medium text-slate-900">{docCounts.processing}</span>
                                        </div>
                                    )}
                                    {docCounts.extraction_completed > 0 && (
                                        <div className="flex items-center justify-between py-1.5">
                                            <div className="flex items-center gap-2">
                                                <div className="w-2 h-2 rounded-full bg-emerald-500"></div>
                                                <span className="text-slate-600">Extraction Completed</span>
                                            </div>
                                            <span className="font-medium text-slate-900">{docCounts.extraction_completed}</span>
                                        </div>
                                    )}
                                    {docCounts.reviewed > 0 && (
                                        <div className="flex items-center justify-between py-1.5">
                                            <div className="flex items-center gap-2">
                                                <div className="w-2 h-2 rounded-full bg-purple-500"></div>
                                                <span className="text-slate-600">Reviewed</span>
                                            </div>
                                            <span className="font-medium text-slate-900">{docCounts.reviewed}</span>
                                        </div>
                                    )}
                                </div>
                            </div>
                        )}
                        {allDocsReviewed && (
                            <div className="mt-6 pt-4 border-t">
                                <Button className="w-full" onClick={() => setShowIntegrationModal(true)}>
                                    Next: Send to Integration
                                </Button>
                                <p className="text-xs text-slate-500 mt-2">All documents are reviewed. Choose an integration channel to continue.</p>
                            </div>
                        )}
                    </div>
                </div>
            </div>

            {/* Review Modal - Full Screen */}
            {reviewDoc && (
                <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4">
                    <div className="bg-white rounded-lg shadow-xl w-full h-full max-w-[95vw] max-h-[95vh] flex flex-col">
                        {/* Header */}
                        <div className="flex items-center justify-between px-6 py-4 border-b">
                            <h2 className="text-xl font-semibold">Review: {reviewDoc.filename}</h2>
                            <Button
                                variant="ghost"
                                size="icon"
                                onClick={() => setReviewDoc(null)}
                            >
                                <X className="h-5 w-5" />
                            </Button>
                        </div>

                        {/* Content - 2 Columns */}
                        <div className="flex-1 overflow-hidden grid grid-cols-2 gap-4 p-4">
                            {/* Left Column - Document Viewer (PDF or Image) */}
                            <div className="bg-slate-50 rounded-lg overflow-hidden">
                                {(() => {
                                    const fileExt = reviewDoc.filename.toLowerCase().split('.').pop() || ''
                                    const imageExtensions = ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'tiff', 'webp']

                                    if (imageExtensions.includes(fileExt)) {
                                        // Display Image
                                        return (
                                            <div className="h-full overflow-auto bg-slate-900 p-4">
                                                {imageUrl ? (
                                                    <img
                                                        src={imageUrl}
                                                        alt={reviewDoc.filename}
                                                        className="w-full h-auto shadow-2xl rounded"
                                                    />
                                                ) : (
                                                    <div className="flex items-center justify-center h-full">
                                                        <div className="text-center">
                                                            <div className="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mb-2"></div>
                                                            <p className="text-sm text-slate-300">Loading image...</p>
                                                        </div>
                                                    </div>
                                                )}
                                            </div>
                                        )
                                    } else {
                                        // Display PDF
                                        return (
                                            <PDFViewer
                                                fileUrl={pdfFileUrl}
                                            />
                                        )
                                    }
                                })()}
                            </div>

                            {/* Right Column - Editable Data */}
                            <div className="flex flex-col space-y-4 overflow-y-auto pr-2">
                                {/* OCR Text Section */}
                                <div className="bg-white border rounded-lg p-4">
                                    <label className="text-sm font-semibold mb-3 block text-slate-700">
                                        OCR Text
                                    </label>
                                    <Textarea
                                        value={editedOcrText}
                                        onChange={(e) => setEditedOcrText(e.target.value)}
                                        className="h-48 font-mono text-xs resize-none"
                                        placeholder="OCR extracted text..."
                                    />
                                </div>

                                {/* Extracted Data Section */}
                                <div className="bg-white border rounded-lg p-4 flex-1">
                                    <label className="text-sm font-semibold mb-3 block text-slate-700">
                                        Extracted Data
                                    </label>
                                    <div className="space-y-3">
                                        {editedData.length === 0 && reviewDoc?.processing_error ? (
                                            <div className="text-sm text-amber-700 bg-amber-50 p-4 rounded border border-amber-200">
                                                <p className="font-medium mb-2">⚠️ Extraction Issue Detected:</p>
                                                <code className="text-xs break-all whitespace-pre-wrap">{reviewDoc.processing_error}</code>
                                            </div>
                                        ) : editedData.length === 0 ? (
                                            <p className="text-sm text-slate-500 text-center py-8">
                                                No extracted data available
                                            </p>
                                        ) : (
                                            editedData.map((entry, idx) => (
                                                <div key={idx} className="border rounded-md p-3 space-y-2">
                                                    <div className="text-xs font-semibold text-slate-500 uppercase">
                                                        Record {idx + 1}
                                                    </div>
                                                    {Object.entries(entry).map(([key, value]) => (
                                                        <div key={key} className="space-y-1.5">
                                                            <label className="text-xs font-semibold text-slate-600 uppercase tracking-wide">
                                                                {key.replace(/_/g, ' ')}
                                                            </label>
                                                            <Input
                                                                value={typeof value === "object" ? JSON.stringify(value) : (value ?? "")}
                                                                onChange={(e) => handleDataFieldChange(idx, key, e.target.value)}
                                                                className="font-medium"
                                                            />
                                                        </div>
                                                    ))}
                                                </div>
                                            ))
                                        )}
                                    </div>
                                </div>
                            </div>
                        </div>

                        {/* Footer - Action Buttons */}
                        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t bg-slate-50">
                            <Button variant="outline" onClick={() => setReviewDoc(null)}>
                                Cancel
                            </Button>
                            <Button onClick={handleSaveReview} className="min-w-[120px]">
                                Save Changes
                            </Button>
                        </div>
                    </div>
                </div>
            )}

            {/* Integration Selection */}
            <Modal
                isOpen={showIntegrationModal}
                onClose={() => setShowIntegrationModal(false)}
                title="Select Integration"
            >
                <div className="space-y-4">
                    <p className="text-sm text-slate-600">Send reviewed documents to an integration endpoint.</p>

                    <div className="space-y-3 max-h-80 overflow-auto">
                        {integrations.map((integration) => (
                            <label
                                key={integration.id}
                                className={`border rounded-lg p-3 flex items-start gap-3 cursor-pointer ${selectedIntegration === integration.id ? "border-blue-500 bg-blue-50" : "border-slate-200"}`}
                            >
                                <input
                                    type="radio"
                                    className="mt-1"
                                    checked={selectedIntegration === integration.id}
                                    onChange={() => setSelectedIntegration(integration.id)}
                                />
                                <div>
                                    <div className="flex items-center gap-2">
                                        <span className="font-semibold">{integration.name}</span>
                                        <span className="text-xs uppercase px-2 py-0.5 rounded-full bg-slate-100 text-slate-600">{integration.type}</span>
                                    </div>
                                    <p className="text-sm text-slate-600">{integration.description}</p>
                                </div>
                            </label>
                        ))}
                    </div>

                    {integrationMessage && (
                        <div className="text-sm text-slate-600">{integrationMessage}</div>
                    )}

                    <div className="flex justify-end gap-2">
                        <Button
                            variant="outline"
                            onClick={() => {
                                setShowIntegrationModal(false)
                                setIntegrationMessage(null)
                            }}
                        >
                            {integrationMessage === "Sent successfully" ? "Close" : "Cancel"}
                        </Button>
                        <Button
                            onClick={handleSendToIntegration}
                            disabled={!selectedIntegration || sendingIntegration}
                        >
                            {sendingIntegration ? "Sending..." : integrationMessage === "Sent successfully" ? "Retry" : "Send"}
                        </Button>
                    </div>
                </div>
            </Modal>

            {/* LLM Results Modal with Export */}
            {showLlmResultsModal && (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={() => setShowLlmResultsModal(false)}>
                    <div className="bg-white rounded-lg shadow-xl p-6 max-w-4xl w-full mx-4 max-h-[80vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
                        <div className="flex items-center justify-between mb-4">
                            <h3 className="text-xl font-semibold">LLM Processing Results</h3>
                            <button onClick={() => setShowLlmResultsModal(false)} className="text-slate-400 hover:text-slate-600 text-2xl">&times;</button>
                        </div>

                        {/* Export Buttons */}
                        <div className="flex flex-wrap gap-2 mb-4 pb-4 border-b">
                            <Button
                                size="sm"
                                variant="outline"
                                onClick={() => {
                                    const text = llmResults.map(r => `=== ${r.filename} ===\n${r.success ? r.output : 'Error: ' + r.error}`).join('\n\n')
                                    navigator.clipboard.writeText(text)
                                    alert('Copied to clipboard!')
                                }}
                            >
                                📋 Copy All
                            </Button>
                            <Button
                                size="sm"
                                variant="outline"
                                onClick={() => {
                                    const csv = 'Filename,Status,Output\n' + llmResults.map(r =>
                                        `"${r.filename}","${r.success ? 'Success' : 'Error'}","${(r.success ? r.output : r.error || '').replace(/"/g, '""')}"`
                                    ).join('\n')
                                    const blob = new Blob([csv], { type: 'text/csv' })
                                    const url = URL.createObjectURL(blob)
                                    const a = document.createElement('a')
                                    a.href = url
                                    a.download = 'llm_results.csv'
                                    a.click()
                                }}
                            >
                                📊 Export CSV
                            </Button>
                            <Button
                                size="sm"
                                variant="outline"
                                onClick={() => {
                                    const html = `<html><body><table border="1"><tr><th>Filename</th><th>Status</th><th>Output</th></tr>` +
                                        llmResults.map(r => `<tr><td>${r.filename}</td><td>${r.success ? 'Success' : 'Error'}</td><td>${r.success ? r.output : r.error}</td></tr>`).join('') +
                                        `</table></body></html>`
                                    const blob = new Blob([html], { type: 'application/vnd.ms-excel' })
                                    const url = URL.createObjectURL(blob)
                                    const a = document.createElement('a')
                                    a.href = url
                                    a.download = 'llm_results.xls'
                                    a.click()
                                }}
                            >
                                📗 Export Excel
                            </Button>
                            <Button
                                size="sm"
                                variant="outline"
                                onClick={() => {
                                    const content = llmResults.map(r => `## ${r.filename}\n\n${r.success ? r.output : 'Error: ' + r.error}\n\n---`).join('\n\n')
                                    const blob = new Blob([content], { type: 'application/msword' })
                                    const url = URL.createObjectURL(blob)
                                    const a = document.createElement('a')
                                    a.href = url
                                    a.download = 'llm_results.doc'
                                    a.click()
                                }}
                            >
                                📄 Export Docs
                            </Button>
                            <Button
                                size="sm"
                                variant="outline"
                                onClick={() => {
                                    const printContent = llmResults.map(r =>
                                        `<h2>${r.filename}</h2><p>${r.success ? r.output.replace(/\n/g, '<br>') : '<span style="color:red">Error: ' + r.error + '</span>'}</p><hr>`
                                    ).join('')
                                    const printWindow = window.open('', '_blank')
                                    if (printWindow) {
                                        printWindow.document.write(`<html><head><title>LLM Results</title></head><body>${printContent}</body></html>`)
                                        printWindow.document.close()
                                        printWindow.print()
                                    }
                                }}
                            >
                                🖨️ Export PDF
                            </Button>
                        </div>

                        {/* Results */}
                        <div className="space-y-4">
                            {llmResults.map((result, idx) => (
                                <div key={idx} className={`p-4 rounded-lg border ${result.success ? 'bg-green-50 border-green-200' : 'bg-red-50 border-red-200'}`}>
                                    <div className="flex items-center justify-between mb-2">
                                        <span className="font-semibold">{result.filename}</span>
                                        <div className="flex items-center gap-2">
                                            <span className={`text-xs px-2 py-0.5 rounded ${result.success ? 'bg-green-200 text-green-800' : 'bg-red-200 text-red-800'}`}>
                                                {result.success ? 'Success' : 'Error'}
                                            </span>
                                            <button
                                                className="text-xs text-blue-600 hover:underline"
                                                onClick={() => {
                                                    navigator.clipboard.writeText(result.success ? result.output : result.error || '')
                                                    alert('Copied!')
                                                }}
                                            >
                                                Copy
                                            </button>
                                        </div>
                                    </div>
                                    <div className="text-sm bg-white p-3 rounded border max-h-60 overflow-y-auto">
                                        {result.success ? (
                                            (() => {
                                                const content = result.output
                                                // Simple check for Markdown table
                                                if (content.includes('|') && content.includes('---')) {
                                                    try {
                                                        const lines = content.trim().split('\n').filter(l => l.trim())
                                                        // Find table start (lines with pipes)
                                                        const tableLines = lines.filter(l => l.includes('|'))

                                                        if (tableLines.length >= 3) {
                                                            const headers = tableLines[0].split('|').filter(c => c.trim()).map(c => c.trim())
                                                            const rows = tableLines.slice(2).map(line =>
                                                                line.split('|').filter((c, i) => i > 0 && i < tableLines[0].split('|').length - 1).map(c => c.trim())
                                                            )

                                                            return (
                                                                <div className="overflow-x-auto">
                                                                    <table className="min-w-full border-collapse text-left">
                                                                        <thead>
                                                                            <tr className="bg-slate-100">
                                                                                {headers.map((h, i) => (
                                                                                    <th key={i} className="border p-2 font-medium">{h}</th>
                                                                                ))}
                                                                            </tr>
                                                                        </thead>
                                                                        <tbody>
                                                                            {rows.map((row, i) => (
                                                                                <tr key={i} className="border-b hover:bg-slate-50">
                                                                                    {row.map((cell, j) => (
                                                                                        <td key={j} className="border p-2">{cell}</td>
                                                                                    ))}
                                                                                </tr>
                                                                            ))}
                                                                        </tbody>
                                                                    </table>
                                                                </div>
                                                            )
                                                        }
                                                    } catch {
                                                        // Fallback to raw
                                                    }
                                                }
                                                return <div className="whitespace-pre-wrap">{content}</div>
                                            })()
                                        ) : (
                                            <div className="text-red-600 font-mono whitespace-pre-wrap">{result.error}</div>
                                        )}
                                    </div>
                                </div>
                            ))}
                        </div>

                        <div className="flex justify-end mt-4 pt-4 border-t">
                            <Button onClick={() => setShowLlmResultsModal(false)}>Close</Button>
                        </div>
                    </div>
                </div>
            )}

            {/* Delete Confirmation Modal */}
            {deleteConfirmDoc && (
                <div className="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-center justify-center">
                    <div className="bg-white rounded-lg shadow-xl p-6 max-w-md w-full mx-4">
                        <h3 className="text-lg font-semibold mb-4">Delete Document</h3>
                        <p className="text-slate-600 mb-6">
                            Are you sure you want to delete <strong>{deleteConfirmDoc.filename}</strong>?
                            This action cannot be undone.
                        </p>
                        <div className="flex justify-end gap-3">
                            <Button
                                onClick={() => setDeleteConfirmDoc(null)}
                                variant="outline"
                                disabled={deleting}
                            >
                                Cancel
                            </Button>
                            <Button
                                onClick={handleDeleteDocument}
                                variant="destructive"
                                disabled={deleting}
                            >
                                {deleting ? (
                                    <>
                                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                                        Deleting...
                                    </>
                                ) : (
                                    "Delete"
                                )}
                            </Button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}
