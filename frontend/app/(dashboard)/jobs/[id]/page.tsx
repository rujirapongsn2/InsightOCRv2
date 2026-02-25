"use client"

import { useEffect, useState, useRef, useMemo } from "react"
import { useParams, useRouter } from "next/navigation"
import Link from "next/link"
import { ArrowLeft, Upload, FileText, Loader2, Eye, X, Trash2, AlertTriangle } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Modal } from "@/components/ui/modal"
import { Textarea } from "@/components/ui/textarea"
import { Input } from "@/components/ui/input"
import dynamic from "next/dynamic"
import { getApiBaseUrl } from "@/lib/api"
import { useAuth } from "@/components/auth-provider"
import LlmResultRenderer from "@/components/LlmResultRenderer"
import { generateExportHtml, generateExportText } from "@/lib/exportReportHtml"

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
    user_id?: string
}

interface Document {
    id: string
    filename: string
    status: string
    schema_id?: string | null
    extracted_data?: Record<string, any> | Record<string, any>[]
    reviewed_data?: Record<string, any> | Record<string, any>[]
    ocr_text?: string
    uploaded_at?: string
    processing_error?: string
}
type ExtractedEntry = Record<string, any>
type FieldPathSegment = string | number

interface EditableField {
    path: FieldPathSegment[]
    label: string
    value: any
}

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
    const router = useRouter()
    const { user } = useAuth()
    const jobId = params.id as string
    const [job, setJob] = useState<Job | null>(null)
    const [documents, setDocuments] = useState<Document[]>([])
    const [schemas, setSchemas] = useState<Schema[]>([])
    const [uploading, setUploading] = useState(false)
    const [loading, setLoading] = useState(true)
    const [processingDocs, setProcessingDocs] = useState<Set<string>>(new Set())
    const [docProgress, setDocProgress] = useState<Record<string, { percent: number; stage: string }>>({})
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
    const [llmStreaming, setLlmStreaming] = useState(false)
    const [llmStreamText, setLlmStreamText] = useState("")
    const llmStreamRef = useRef<HTMLDivElement>(null)
    const userScrolledRef = useRef(false)
    // Delete confirmation (document)
    const [deleteConfirmDoc, setDeleteConfirmDoc] = useState<Document | null>(null)
    const [deleting, setDeleting] = useState(false)
    // Delete confirmation (job)
    const [showDeleteJobConfirm, setShowDeleteJobConfirm] = useState(false)
    const [deletingJob, setDeletingJob] = useState(false)
    // Image viewer state
    const [imageUrl, setImageUrl] = useState<string | null>(null)
    // Reject document from review modal
    const [rejectConfirm, setRejectConfirm] = useState(false)
    const [rejecting, setRejecting] = useState(false)
    // Integration result history
    const [resultHistory, setResultHistory] = useState<Array<{ id: string; status: string; model_used: string | null; integration_type: string | null; integration_name: string | null; created_at: string }>>([])
    const [loadingHistory, setLoadingHistory] = useState(false)

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

    // Reload integrations and reset state when integration modal opens
    useEffect(() => {
        if (showIntegrationModal) {
            setIntegrationMessage(null)
            loadIntegrations()
        }
    }, [showIntegrationModal])

    // Auto-scroll streaming content
    useEffect(() => {
        if (llmStreaming && llmStreamRef.current && !userScrolledRef.current) {
            llmStreamRef.current.scrollTop = llmStreamRef.current.scrollHeight
        }
    }, [llmStreamText, llmStreaming])

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
                const sorted = [...docs].sort((a: Document, b: Document) => {
                    const ta = a.uploaded_at ? new Date(a.uploaded_at).getTime() : 0
                    const tb = b.uploaded_at ? new Date(b.uploaded_at).getTime() : 0
                    return tb - ta
                })
                setDocuments(sorted)
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

    const loadResultHistory = async () => {
        const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
        if (!token) return
        setLoadingHistory(true)
        try {
            const res = await fetch(`${apiBase}/integrations/results?job_id=${jobId}`, {
                headers: { Authorization: `Bearer ${token}` },
            })
            if (res.ok) {
                setResultHistory(await res.json())
            }
        } catch (err) {
            console.error("Failed to load result history", err)
        } finally {
            setLoadingHistory(false)
        }
    }

    const handleViewHistoryResult = async (resultId: string) => {
        const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
        if (!token) return
        try {
            const res = await fetch(`${apiBase}/integrations/results/${resultId}`, {
                headers: { Authorization: `Bearer ${token}` },
            })
            if (!res.ok) throw new Error("Failed to fetch result")
            const data = await res.json()
            setLlmStreamText("")
            setLlmStreaming(false)
            if (data.status === "success" && data.output) {
                setLlmResults([{
                    id: data.id,
                    filename: job?.name ? `${job.name} — Validation Report` : "Validation Report",
                    output: data.output,
                    success: true,
                }])
            } else {
                setLlmResults([{
                    id: data.id,
                    filename: job?.name || "Result",
                    output: "",
                    success: false,
                    error: data.error_message || "Unknown error",
                }])
            }
            setShowLlmResultsModal(true)
        } catch (err) {
            console.error("Failed to load result", err)
        }
    }

    useEffect(() => {
        const hydrate = async () => {
            setLoading(true)
            await Promise.all([fetchJobData(), fetchDocuments(), fetchSchemas()])
            setLoading(false)
        }

        hydrate().then(() => {
            setDocuments(prev => {
                const inFlight = prev.filter(d => d.status === "processing" || d.status === "queued")
                inFlight.forEach(d => startPolling(d.id))
                return prev
            })
        })
        loadResultHistory()
    }, [jobId])

    const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
        if (!e.target.files || e.target.files.length === 0) return

        setUploading(true)
        const files = Array.from<File>(e.target.files)
        const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
        const failed: string[] = []

        for (const file of files) {
            const formData = new FormData()
            formData.append("file", file)
            formData.append("job_id", jobId)

            try {
                const res = await fetch(`${apiBase}/documents/upload`, {
                    method: "POST",
                    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
                    body: formData
                })

                if (res.ok) {
                    const newDoc: Document = await res.json()
                    setDocuments(prev => [newDoc, ...prev])
                } else {
                    failed.push(file.name)
                }
            } catch (error) {
                console.error("Upload error", error)
                failed.push(file.name)
            }
        }

        setUploading(false)
        if (fileInputRef.current) {
            fileInputRef.current.value = ""
        }
        if (failed.length > 0) {
            alert(`Upload failed for: ${failed.join(", ")}`)
        }
    }

    const handleSchemaChange = (docId: string, schemaId: string) => {
        const nextSchemaId = schemaId === "auto" ? null : schemaId
        setDocuments(prev => prev.map(doc =>
            doc.id === docId ? { ...doc, schema_id: nextSchemaId } : doc
        ))
    }

    const startPolling = (docId: string) => {
        const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
        setProcessingDocs(prev => new Set(prev).add(docId))
        const pollInterval = setInterval(async () => {
            try {
                const statusRes = await fetch(`${apiBase}/documents/${docId}/task-status`, {
                    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
                })
                if (!statusRes.ok) {
                    clearInterval(pollInterval)
                    setProcessingDocs(prev => { const s = new Set(prev); s.delete(docId); return s })
                    setDocProgress(prev => { const p = { ...prev }; delete p[docId]; return p })
                    return
                }

                const status = await statusRes.json()

                if (status.progress) {
                    setDocProgress(prev => ({
                        ...prev,
                        [docId]: {
                            percent: status.progress.percent ?? 0,
                            stage: status.progress.stage ?? "",
                        }
                    }))
                }

                if (status.status === "extraction_completed" || status.status === "reviewed" || status.status === "failed") {
                    clearInterval(pollInterval)
                    setProcessingDocs(prev => { const s = new Set(prev); s.delete(docId); return s })
                    setDocProgress(prev => { const p = { ...prev }; delete p[docId]; return p })
                    await fetchDocuments()
                }
            } catch (pollError) {
                console.error("Polling error", pollError)
                clearInterval(pollInterval)
                setProcessingDocs(prev => { const s = new Set(prev); s.delete(docId); return s })
                setDocProgress(prev => { const p = { ...prev }; delete p[docId]; return p })
            }
        }, 1000)
        return pollInterval
    }

    const handleProcess = async (docId: string) => {
        const doc = documents.find(d => d.id === docId)
        if (!doc) return

        setProcessingDocs(prev => new Set(prev).add(docId))
        setDocProgress(prev => ({ ...prev, [docId]: { percent: 0, stage: "queuing" } }))

        try {
            const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
            const res = await fetch(`${apiBase}/documents/${docId}/process`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    ...(token ? { Authorization: `Bearer ${token}` } : {})
                },
                body: JSON.stringify({ schema_id: doc.schema_id || null })
            })

            if (!res.ok) {
                alert("Failed to start processing")
                setProcessingDocs(prev => { const s = new Set(prev); s.delete(docId); return s })
                setDocProgress(prev => { const p = { ...prev }; delete p[docId]; return p })
                return
            }

            startPolling(docId)

        } catch (error) {
            console.error("Processing error", error)
            alert("Processing error")
            setProcessingDocs(prev => { const s = new Set(prev); s.delete(docId); return s })
            setDocProgress(prev => { const p = { ...prev }; delete p[docId]; return p })
        }
    }

    const handleProcessAll = async () => {
        const docsToProcess = documents.filter(d => d.status === "uploaded")

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

    const handleDeleteJob = async () => {
        try {
            setDeletingJob(true)
            const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
            const response = await fetch(`${apiBase}/jobs/${jobId}`, {
                method: "DELETE",
                headers: {
                    Authorization: `Bearer ${token}`,
                },
            })
            if (!response.ok) {
                throw new Error("Failed to delete job")
            }
            router.push("/jobs")
        } catch (error) {
            console.error("Delete job error:", error)
            alert("Failed to delete job. Please try again.")
        } finally {
            setDeletingJob(false)
            setShowDeleteJobConfirm(false)
        }
    }

    const handleRejectDocument = async () => {
        if (!reviewDoc) return
        try {
            setRejecting(true)
            const token = localStorage.getItem("token")
            const res = await fetch(`${apiBase}/documents/${reviewDoc.id}`, {
                method: "DELETE",
                headers: { Authorization: `Bearer ${token}` },
            })
            if (!res.ok) throw new Error("Failed to reject document")
            await fetchDocuments()
            setReviewDoc(null)
            setRejectConfirm(false)
        } catch (error) {
            console.error("Reject error:", error)
            alert("Failed to reject document. Please try again.")
        } finally {
            setRejecting(false)
        }
    }

    const canDeleteJob = user && job && (user.is_superuser || user.role === "admin" || user.id === job.user_id)

    const getSchemaSourceLabel = (doc: Document) => {
        if (!doc.schema_id) return "auto"
        const selectedSchema = schemas.find((schema) => schema.id === doc.schema_id)
        return selectedSchema ? selectedSchema.name : "selected schema"
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

        // Handle API structured wrapper with metadata + data payload
        if (
            typeof data === "object" &&
            data !== null &&
            'data' in data &&
            (
                'schema_source' in data ||
                'success' in data ||
                'schema' in data ||
                'structure_model' in data
            )
        ) {
            console.log("[normalizeExtractedData] Unwrapping structured metadata envelope")
            return normalizeExtractedData((data as any).data)
        }

        // Handle 'data' wrapper
        if (typeof data === "object" && data !== null && 'data' in data && Object.keys(data).length === 1) {
            console.log("[normalizeExtractedData] Unwrapping 'data' field")
            return normalizeExtractedData((data as any).data)
        }

        if (Array.isArray(data)) {
            return data
                .filter((entry) => entry && typeof entry === "object" && !Array.isArray(entry) && Object.keys(entry).length > 0)
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
            if (Object.keys(data as object).length === 0) {
                return []
            }
            return [data as ExtractedEntry]
        }

        return []
    }

    const formatFieldPathLabel = (path: FieldPathSegment[]): string => {
        return path.reduce<string>((acc, segment) => {
            if (typeof segment === "number") {
                return `${acc}[${segment}]`
            }
            return acc ? `${acc}.${segment}` : segment
        }, "")
    }

    const collectEditableFields = (value: any, currentPath: FieldPathSegment[] = []): EditableField[] => {
        if (Array.isArray(value)) {
            return value.flatMap((item, idx) => collectEditableFields(item, [...currentPath, idx]))
        }

        if (value && typeof value === "object") {
            return Object.entries(value).flatMap(([key, nestedValue]) =>
                collectEditableFields(nestedValue, [...currentPath, key])
            )
        }

        return [{
            path: currentPath,
            label: formatFieldPathLabel(currentPath),
            value,
        }]
    }

    const setValueAtPath = (source: any, path: FieldPathSegment[], nextValue: any): any => {
        if (path.length === 0) {
            return nextValue
        }

        const [head, ...tail] = path

        if (Array.isArray(source)) {
            const index = Number(head)
            const cloned = [...source]
            cloned[index] = setValueAtPath(cloned[index], tail, nextValue)
            return cloned
        }

        const safeSource = source && typeof source === "object" ? source : {}
        return {
            ...safeSource,
            [head]: setValueAtPath((safeSource as Record<string, any>)[String(head)], tail, nextValue),
        }
    }

    const handleReview = (doc: Document) => {
        setReviewDoc(doc)
        setRejectConfirm(false)
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

    const handleDataFieldChange = (index: number, fieldPath: FieldPathSegment[], value: string) => {
        setEditedData(prev => {
            const next = [...prev]
            next[index] = setValueAtPath(next[index] || {}, fieldPath, value)
            return next
        })
    }

    const handleSendToIntegration = async () => {
        if (!job || !selectedIntegration) return

        const integration = integrations.find(int => int.id === selectedIntegration)

        setSendingIntegration(true)
        setIntegrationMessage(null)

        const payload = {
            integration_id: selectedIntegration,
            job_id: jobId,
            job_name: job.name,
            documents: documents.map(doc => ({
                id: String(doc.id),
                filename: doc.filename || "unnamed",
                data: doc.reviewed_data || doc.extracted_data || {}
            }))
        }

        // Use streaming for LLM integrations
        if (integration?.type === "llm") {
            // Open modal immediately with streaming state
            setLlmStreamText("")
            setLlmStreaming(true)
            setLlmResults([])
            setShowLlmResultsModal(true)
            setShowIntegrationModal(false)
            userScrolledRef.current = false

            try {
                const token = localStorage.getItem("token")
                const res = await fetch(`${apiBase}/integrations/send-stream`, {
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
                    throw new Error(errMsg || `Stream failed: ${res.status}`)
                }

                const reader = res.body?.getReader()
                const decoder = new TextDecoder()
                let accumulated = ""
                let buffer = ""

                if (!reader) throw new Error("No response body")

                while (true) {
                    const { done, value } = await reader.read()
                    if (done) break

                    buffer += decoder.decode(value, { stream: true })
                    const lines = buffer.split("\n")
                    buffer = lines.pop() || ""

                    for (const line of lines) {
                        if (!line.startsWith("data: ")) continue
                        try {
                            const evt = JSON.parse(line.slice(6))
                            if (evt.type === "delta") {
                                accumulated += evt.text
                                setLlmStreamText(accumulated)
                            } else if (evt.type === "done") {
                                const finalText = evt.full_output || accumulated
                                setLlmStreamText(finalText)
                                setLlmResults([{
                                    id: "combined",
                                    filename: evt.filename || `${job.name} — Validation Report`,
                                    output: finalText,
                                    success: true
                                }])
                                setLlmStreaming(false)
                            } else if (evt.type === "error") {
                                setLlmResults([{
                                    id: "combined",
                                    filename: job.name,
                                    output: "",
                                    success: false,
                                    error: evt.message
                                }])
                                setLlmStreaming(false)
                            }
                        } catch {
                            // skip malformed lines
                        }
                    }
                }

                // If stream ended without done event
                if (accumulated && llmResults.length === 0) {
                    setLlmResults([{
                        id: "combined",
                        filename: `${job.name} — Validation Report`,
                        output: accumulated,
                        success: true
                    }])
                }
                setLlmStreaming(false)
                setIntegrationMessage("LLM processing completed")
                loadResultHistory()
            } catch (err: any) {
                setLlmStreaming(false)
                setIntegrationMessage(err?.message || "Failed to send")
                if (!llmResults.length) {
                    setLlmResults([{
                        id: "combined",
                        filename: job.name,
                        output: "",
                        success: false,
                        error: err?.message || "Stream failed"
                    }])
                }
            } finally {
                setSendingIntegration(false)
            }
            return
        }

        // Non-LLM integrations: use original /send endpoint
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
            setIntegrationMessage(result.message || "Sent successfully")
            loadResultHistory()
        } catch (err: any) {
            setIntegrationMessage(err?.message || "Failed to send")
            loadResultHistory()
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
                <div className="ml-auto flex items-center gap-3">
                    <span className={`px-3 py-1 rounded-full text-sm font-medium ${job.status === 'completed' ? 'bg-green-100 text-green-800' :
                        job.status === 'processing' ? 'bg-blue-100 text-blue-800' :
                            'bg-slate-100 text-slate-800'
                        }`}>
                        {job.status.toUpperCase()}
                    </span>
                    {canDeleteJob && (
                        <Button
                            variant="outline"
                            size="sm"
                            className="text-red-600 hover:text-red-700 hover:bg-red-50 border-red-200"
                            onClick={() => setShowDeleteJobConfirm(true)}
                        >
                            <Trash2 className="mr-2 h-4 w-4" />
                            Delete Job
                        </Button>
                    )}
                </div>
            </div>

            <div className="grid gap-6 md:grid-cols-3">
                <div className="md:col-span-2 space-y-6">
                    <div className="rounded-lg border bg-white p-6 shadow-sm">
                        <div className="flex items-center justify-between mb-4">
                            <h3 className="text-lg font-semibold">Documents</h3>
                            <div className="flex gap-2">
                                {documents.some(d => d.status === "uploaded") && (
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
                                    multiple
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
                                                {doc.processing_error && doc.status !== "failed" && (
                                                    <span className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-full bg-amber-50 text-amber-700 border border-amber-200" title={doc.processing_error}>
                                                        <AlertTriangle className="h-3 w-3" />
                                                        OCR Degraded
                                                    </span>
                                                )}
                                                <span className={`text-xs px-2.5 py-1 rounded-full border font-medium capitalize ${getStatusColor(doc.status)}`}>
                                                    {doc.status.replace(/_/g, ' ')}
                                                </span>
                                            </div>

                                            <div className="flex items-center gap-2">
                                                <select
                                                    className="flex h-9 w-full rounded-md border border-slate-200 bg-white px-3 py-1 text-sm"
                                                    value={doc.schema_id || "auto"}
                                                    onChange={(e) => handleSchemaChange(doc.id, e.target.value)}
                                                    disabled={doc.status !== "uploaded"}
                                                >
                                                    <option value="auto">Auto (default)</option>
                                                    {schemas.map(schema => (
                                                        <option key={schema.id} value={schema.id}>{schema.name}</option>
                                                    ))}
                                                </select>

                                                {(doc.status === "uploaded" || doc.status === "queued" || doc.status === "failed") && (
                                                    <>
                                                        <Button
                                                            onClick={() => handleProcess(doc.id)}
                                                            disabled={isProcessing}
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
                                                        Preview
                                                    </Button>
                                                )}
                                            </div>

                                            {/* Progress bar shown while processing */}
                                            {isProcessing && docProgress[doc.id] && (
                                                <div className="mt-2">
                                                    <div className="flex items-center justify-between mb-1">
                                                        <span className="text-xs text-slate-500 capitalize">
                                                            {docProgress[doc.id].stage
                                                                ? docProgress[doc.id].stage.replace(/_/g, ' ')
                                                                : "Processing..."}
                                                        </span>
                                                        <span className="text-xs font-medium text-slate-700">
                                                            {docProgress[doc.id].percent}%
                                                        </span>
                                                    </div>
                                                    <div className="w-full bg-slate-200 rounded-full h-1.5">
                                                        <div
                                                            className="bg-blue-500 h-1.5 rounded-full transition-all duration-500"
                                                            style={{ width: `${docProgress[doc.id].percent}%` }}
                                                        />
                                                    </div>
                                                </div>
                                            )}
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

                        {/* Integration History */}
                        {resultHistory.length > 0 && (
                            <div className="mt-4 pt-4 border-t">
                                <h4 className="text-sm font-semibold text-[#1a365d] mb-2 flex items-center gap-1.5">
                                    <FileText className="h-3.5 w-3.5" />
                                    ประวัติการเชื่อมต่อ ({resultHistory.length})
                                </h4>
                                <div className="space-y-1.5 max-h-60 overflow-y-auto">
                                    {resultHistory.map((r) => {
                                        const isLlm = r.integration_type === "llm"
                                        const typeBadge = r.integration_type === "llm" ? "LLM" : r.integration_type === "api" ? "API" : r.integration_type === "workflow" ? "Workflow" : r.integration_type || "—"
                                        const typeBgColor = r.integration_type === "llm" ? "bg-[#ebf8ff] text-[#2b6cb0]" : r.integration_type === "api" ? "bg-[#fffaf0] text-[#c05621]" : "bg-[#f0fff4] text-[#276749]"

                                        const rowContent = (
                                            <>
                                                <div className="flex items-center gap-2 min-w-0 flex-1">
                                                    <span className={`inline-block w-2 h-2 rounded-full flex-shrink-0 ${r.status === "success" ? "bg-[#276749]" : "bg-[#c53030]"}`} />
                                                    <span className="text-[#2d3748] truncate">
                                                        {new Date(r.created_at).toLocaleString("th-TH", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" })}
                                                    </span>
                                                </div>
                                                <div className="flex items-center gap-1.5 flex-shrink-0">
                                                    <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${typeBgColor}`}>{typeBadge}</span>
                                                    <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${r.status === "success" ? "bg-[#f0fff4] text-[#276749]" : "bg-[#fff5f5] text-[#c53030]"}`}>
                                                        {r.status === "success" ? "PASS" : "FAILED"}
                                                    </span>
                                                </div>
                                            </>
                                        )

                                        return isLlm ? (
                                            <button
                                                key={r.id}
                                                onClick={() => handleViewHistoryResult(r.id)}
                                                className="w-full text-left px-3 py-2 rounded-lg border border-[#e2e8f0] hover:bg-[#ebf8ff] hover:border-[#2b6cb0]/30 transition-colors text-xs flex items-center justify-between gap-2 cursor-pointer"
                                                title={r.integration_name || "ดูผลลัพธ์"}
                                            >
                                                {rowContent}
                                                <Eye className="h-3 w-3 text-[#2b6cb0] flex-shrink-0" />
                                            </button>
                                        ) : (
                                            <div
                                                key={r.id}
                                                className="w-full text-left px-3 py-2 rounded-lg border border-[#e2e8f0] text-xs flex items-center justify-between gap-2"
                                                title={r.integration_name || ""}
                                            >
                                                {rowContent}
                                            </div>
                                        )
                                    })}
                                </div>
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
                            <h2 className="text-xl font-semibold">Preview: {reviewDoc.filename}</h2>
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
                                {/* AI Processing Warning Banner */}
                                {reviewDoc.processing_error && (
                                    <div className="flex items-start gap-3 p-4 rounded-lg border border-amber-300 bg-amber-50">
                                        <AlertTriangle className="h-5 w-5 text-amber-600 flex-shrink-0 mt-0.5" />
                                        <div>
                                            <p className="text-sm font-semibold text-amber-800">OCR Quality Warning</p>
                                            <p className="text-xs text-amber-700 mt-1">
                                                AI text enhancement failed during OCR processing. The extracted text may contain errors, resulting in incomplete or inaccurate data extraction.
                                            </p>
                                            <details className="mt-2">
                                                <summary className="text-xs text-amber-600 cursor-pointer hover:underline">Show details</summary>
                                                <code className="text-xs text-amber-700 block mt-1 break-all whitespace-pre-wrap">{reviewDoc.processing_error}</code>
                                            </details>
                                        </div>
                                    </div>
                                )}

                                {/* OCR Text Section */}
                                <div className="bg-white border rounded-lg p-4">
                                    <label className="text-sm font-semibold mb-3 block text-slate-700">
                                        AI Extract
                                    </label>
                                    <p className="text-xs text-slate-500 mb-3">
                                        Schema Source: {getSchemaSourceLabel(reviewDoc)}
                                    </p>
                                    <Textarea
                                        value={editedOcrText}
                                        onChange={(e) => setEditedOcrText(e.target.value)}
                                        className="h-48 font-mono text-xs resize-none"
                                        placeholder="AI extracted text..."
                                    />
                                </div>

                                {/* Structured Data Section */}
                                <div className="bg-white border rounded-lg p-4 flex-1">
                                    <label className="text-sm font-semibold mb-3 block text-slate-700">
                                        Structured Data
                                    </label>
                                    <div className="space-y-3">
                                        {editedData.length === 0 && reviewDoc?.processing_error ? (
                                            <div className="text-sm text-amber-700 bg-amber-50 p-4 rounded border border-amber-200">
                                                <p className="font-medium mb-2">⚠️ Extraction Issue Detected:</p>
                                                <code className="text-xs break-all whitespace-pre-wrap">{reviewDoc.processing_error}</code>
                                            </div>
                                        ) : editedData.length === 0 ? (
                                            <p className="text-sm text-slate-500 text-center py-8">
                                                No structured data available
                                            </p>
                                        ) : (
                                            editedData.map((entry, idx) => (
                                                <div key={idx} className="border rounded-md p-3 space-y-2">
                                                    <div className="text-xs font-semibold text-slate-500 uppercase">
                                                        Record {idx + 1}
                                                    </div>
                                                    {collectEditableFields(entry).map((field) => (
                                                        <div key={`${idx}-${field.label}`} className="space-y-1.5">
                                                            <label className="text-xs font-mono font-medium text-slate-500">
                                                                {field.label}
                                                            </label>
                                                            <Input
                                                                value={field.value === null || field.value === undefined ? "" : String(field.value)}
                                                                onChange={(e) => handleDataFieldChange(idx, field.path, e.target.value)}
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
                        <div className="flex items-center justify-between px-6 py-4 border-t bg-slate-50">
                            {/* Left: Reject */}
                            <div>
                                {!rejectConfirm ? (
                                    <Button
                                        variant="outline"
                                        onClick={() => setRejectConfirm(true)}
                                        className="text-red-600 border-red-300 hover:bg-red-50"
                                    >
                                        Reject
                                    </Button>
                                ) : (
                                    <div className="flex items-center gap-2">
                                        <span className="text-sm text-red-600">Delete this document?</span>
                                        <Button
                                            onClick={handleRejectDocument}
                                            disabled={rejecting}
                                            className="bg-red-600 hover:bg-red-700 text-white"
                                        >
                                            {rejecting ? "Deleting..." : "Confirm Delete"}
                                        </Button>
                                        <Button variant="outline" onClick={() => setRejectConfirm(false)}>
                                            No
                                        </Button>
                                    </div>
                                )}
                            </div>
                            {/* Right: Cancel + Save */}
                            <div className="flex items-center gap-3">
                                <Button variant="outline" onClick={() => setReviewDoc(null)}>
                                    Cancel
                                </Button>
                                <Button onClick={handleSaveReview} className="min-w-[120px]">
                                    Save Changes
                                </Button>
                            </div>
                        </div>
                    </div>
                </div>
            )}

            {/* Integration Selection */}
            <Modal
                isOpen={showIntegrationModal}
                onClose={() => { setShowIntegrationModal(false); setIntegrationMessage(null) }}
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

            {/* LLM Results Modal with Export + Streaming */}
            {showLlmResultsModal && (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={() => { if (!llmStreaming) setShowLlmResultsModal(false) }}>
                    <div className="bg-white rounded-lg shadow-xl p-6 max-w-6xl w-full mx-4 max-h-[92vh] flex flex-col" onClick={e => e.stopPropagation()}>
                        <div className="flex items-center justify-between mb-4 flex-shrink-0">
                            <div className="flex items-center gap-3">
                                <h3 className="text-xl font-semibold">AI Agent Analysis Result</h3>
                                {llmStreaming && (
                                    <span className="flex items-center gap-1.5 text-sm text-blue-600">
                                        <Loader2 className="h-4 w-4 animate-spin" />
                                        Streaming...
                                    </span>
                                )}
                            </div>
                            <button onClick={() => { if (!llmStreaming) setShowLlmResultsModal(false) }} className={`text-slate-400 hover:text-slate-600 text-2xl ${llmStreaming ? 'opacity-30 cursor-not-allowed' : ''}`}>&times;</button>
                        </div>

                        {/* Export Buttons — disabled during streaming */}
                        <div className="flex flex-wrap gap-2 mb-4 pb-4 border-b flex-shrink-0">
                            <Button
                                size="sm"
                                variant="outline"
                                disabled={llmStreaming}
                                onClick={() => {
                                    const text = llmResults.map((r: { filename: string; output: string; success: boolean; error?: string }) => r.success ? generateExportText(r.output, r.filename) : `=== ${r.filename} ===\nError: ${r.error}`).join('\n\n')
                                    navigator.clipboard.writeText(text)
                                    alert('Copied to clipboard!')
                                }}
                            >
                                📋 Copy All
                            </Button>
                            <Button
                                size="sm"
                                variant="outline"
                                disabled={llmStreaming}
                                onClick={() => {
                                    const html = llmResults.map((r: { filename: string; output: string; success: boolean; error?: string }) => r.success ? generateExportHtml(r.output, r.filename) : `<h2>${r.filename}</h2><p style="color:red;">Error: ${r.error}</p>`).join('')
                                    const blob = new Blob([html], { type: 'application/msword;charset=utf-8' })
                                    const url = URL.createObjectURL(blob)
                                    const a = document.createElement('a')
                                    a.href = url
                                    a.download = 'validation_report.doc'
                                    a.click()
                                }}
                            >
                                📄 Export Docs
                            </Button>
                            <Button
                                size="sm"
                                variant="outline"
                                disabled={llmStreaming}
                                onClick={() => {
                                    const html = llmResults.map((r: { filename: string; output: string; success: boolean; error?: string }) => r.success ? generateExportHtml(r.output, r.filename) : `<h2>${r.filename}</h2><p style="color:red;">Error: ${r.error}</p>`).join('')
                                    const printWindow = window.open('', '_blank')
                                    if (printWindow) {
                                        printWindow.document.write(html)
                                        printWindow.document.close()
                                        printWindow.print()
                                    }
                                }}
                            >
                                🖨️ Export PDF
                            </Button>
                        </div>

                        {/* Content area — scrollable */}
                        <div
                            ref={llmStreamRef}
                            className="flex-1 overflow-y-auto min-h-0"
                            onScroll={(e) => {
                                if (!llmStreaming) return
                                const el = e.currentTarget
                                const isNearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80
                                userScrolledRef.current = !isNearBottom
                            }}
                        >
                            {/* Streaming view */}
                            {llmStreaming && (
                                <div className="p-4 rounded-lg border border-blue-200 bg-blue-50/30">
                                    <div className="flex items-center gap-2 mb-3">
                                        <Loader2 className="h-4 w-4 animate-spin text-blue-500" />
                                        <span className="text-sm font-medium text-blue-700">Receiving response...</span>
                                        <span className="text-xs text-blue-500 ml-auto">{llmStreamText.length.toLocaleString()} chars</span>
                                    </div>
                                    <div className="text-sm bg-white p-4 rounded border whitespace-pre-wrap font-mono leading-relaxed">
                                        {llmStreamText}
                                        <span className="inline-block w-2 h-4 bg-blue-500 animate-pulse ml-0.5 align-text-bottom" />
                                    </div>
                                </div>
                            )}

                            {/* Final results — shown after streaming completes */}
                            {!llmStreaming && llmResults.length > 0 && (
                                <div className="space-y-4">
                                    {llmResults.map((result: { id: string; filename: string; output: string; success: boolean; error?: string }, idx: number) => (
                                        <div key={idx}>
                                            <div className="flex items-center justify-between mb-3">
                                                <span className="font-semibold text-slate-800">{result.filename}</span>
                                                <div className="flex items-center gap-2">
                                                    <span className={`text-xs px-2 py-0.5 rounded ${result.success ? 'bg-emerald-100 text-emerald-800' : 'bg-red-100 text-red-800'}`}>
                                                        {result.success ? 'Success' : 'Error'}
                                                    </span>
                                                    <button
                                                        className="text-xs text-blue-600 hover:underline"
                                                        onClick={() => {
                                                            navigator.clipboard.writeText(result.success ? result.output : result.error || '')
                                                            alert('Copied!')
                                                        }}
                                                    >
                                                        Copy Raw
                                                    </button>
                                                </div>
                                            </div>
                                            {result.success ? (
                                                <LlmResultRenderer content={result.output} />
                                            ) : (
                                                <div className="text-red-600 font-mono whitespace-pre-wrap bg-red-50 p-4 rounded-lg border border-red-200">{result.error}</div>
                                            )}
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>

                        <div className="flex justify-end mt-4 pt-4 border-t flex-shrink-0">
                            <Button onClick={() => setShowLlmResultsModal(false)} disabled={llmStreaming}>Close</Button>
                        </div>
                    </div>
                </div>
            )}

            {/* Delete Document Confirmation Modal */}
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

            {/* Delete Job Confirmation Modal */}
            {showDeleteJobConfirm && (
                <div className="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-center justify-center">
                    <div className="bg-white rounded-lg shadow-xl p-6 max-w-md w-full mx-4">
                        <h3 className="text-lg font-semibold mb-4">Delete Job</h3>
                        <p className="text-slate-600 mb-6">
                            Are you sure you want to delete job <strong>{job.name}</strong>?
                            All associated documents will also be deleted. This action cannot be undone.
                        </p>
                        <div className="flex justify-end gap-3">
                            <Button
                                onClick={() => setShowDeleteJobConfirm(false)}
                                variant="outline"
                                disabled={deletingJob}
                            >
                                Cancel
                            </Button>
                            <Button
                                onClick={handleDeleteJob}
                                variant="destructive"
                                disabled={deletingJob}
                            >
                                {deletingJob ? (
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
