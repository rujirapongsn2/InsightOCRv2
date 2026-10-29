"use client"

import { useEffect, useState, useRef, useMemo } from "react"
import { useParams, useRouter } from "next/navigation"
import Link from "next/link"
import { ArrowLeft, Upload, FileText, Loader2, Eye, X, Trash2, AlertTriangle, Bot, ChevronDown, Pencil, Check, Plug, Workflow, Cloud, Send, Braces, RefreshCw, LocateFixed, FileCheck, Minus, XCircle, CheckCircle2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Modal } from "@/components/ui/modal"
import { Input } from "@/components/ui/input"
import dynamic from "next/dynamic"
import { getApiBaseUrl } from "@/lib/api"
import { useAuth } from "@/components/auth-provider"
import LlmResultRenderer from "@/components/LlmResultRenderer"
import AgentPanel from "@/components/agent/AgentPanel"
import { type MappingReport } from "@/components/document/MappingPanel"
import { evidenceSearchTexts, pageWordsFrom, type Highlight, type PageWord } from "@/lib/evidence-search"
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

const anyDocImageMimeTypes = new Set([
    "image/bmp",
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/tiff",
    "image/webp",
])
const anyDocImageExtensions = ["bmp", "jpeg", "jpg", "png", "tif", "tiff", "webp"]
const previewImageExtensions = new Set([...anyDocImageExtensions, "gif"])
interface Document {
    id: string
    filename: string
    status: string
    mime_type?: string
    schema_id?: string | null
    extracted_data?: Record<string, any> | Record<string, any>[]
    reviewed_data?: Record<string, any> | Record<string, any>[]
    ocr_text?: string
    uploaded_at?: string
    processing_error?: string
    extraction_metadata?: {
        pipeline?: string
        source?: "image"
        text_layer_pages?: number[]
        text_layer_invalid_pages?: number[]
        requested_ocr_engine?: "tesseract_ocr" | "softnix_ocr" | "ocr_fallback" | null
        tesseract_pages?: number[]
        softnix_ocr_pages?: number[]
        fallback_pages?: number[]
        legacy_fallback?: { reason?: string }
        mapping?: "not_requested" | "pending" | "deferred" | {
            status?: "completed" | "failed"
            schema?: string
            reason?: string
        }
    }
}
type OcrEngine = "tesseract_ocr" | "softnix_ocr" | "ocr_fallback"

const ocrEngineOptions: Array<{ value: OcrEngine; label: string }> = [
    { value: "tesseract_ocr", label: "TesseractOCR" },
    { value: "softnix_ocr", label: "Softnix OCR" },
    { value: "ocr_fallback", label: "OCR fallback" },
]

function supportsManualOcrRetry(document: Pick<Document, "filename" | "mime_type">): boolean {
    const filename = document.filename.toLowerCase()
    const mimeType = (document.mime_type || "").toLowerCase()
    return (
        mimeType === "application/pdf" ||
        filename.endsWith(".pdf") ||
        anyDocImageMimeTypes.has(mimeType) ||
        anyDocImageExtensions.some((extension) => filename.endsWith(`.${extension}`))
    )
}

type IntegrationType = "api" | "workflow" | "llm" | "softnix_genai" | "gdrive" | "onedrive"

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
    document_type: string
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
    const [editedStructuredData, setEditedStructuredData] = useState<Record<string, any> | Record<string, any>[] | null>(null)
    const [liveMapping, setLiveMapping] = useState<MappingReport | null>(null)
    const [mappingEngine, setMappingEngine] = useState("auto")
    const [fieldFilter, setFieldFilter] = useState<"all" | "needs_review" | "source_matched" | "missing" | "failed">("needs_review")
    const [confirmedFields, setConfirmedFields] = useState<Set<string>>(new Set())
    const [confirmedMissing, setConfirmedMissing] = useState<Set<string>>(new Set())
    const [dirtyFields, setDirtyFields] = useState<Set<string>>(new Set())
    const [applyBar, setApplyBar] = useState<{ updated: number; review: number; keptEdits: number } | null>(null)
    const [fieldRetryBusy, setFieldRetryBusy] = useState<string | null>(null)
    const applySnapshot = useRef<{ data: Record<string, any> | Record<string, any>[] | null; drafts: Record<string, string>; json: string; mapping: MappingReport | null; confirmed: Set<string>; missing: Set<string> } | null>(null)
    const [arrayDrafts, setArrayDrafts] = useState<Record<string, string>>({})
    const [structuredDataTab, setStructuredDataTab] = useState<"fields" | "advanced">("fields")
    const [reviewTab, setReviewTab] = useState<"fields" | "json" | "text" | "ocr">("fields")
    const [expandedField, setExpandedField] = useState<string | null>(null)
    const [mappingBusy, setMappingBusy] = useState(false)
    const [mappingError, setMappingError] = useState("")
    const [mobileView, setMobileView] = useState<"pdf" | "fields">("fields")
    const [saveNotice, setSaveNotice] = useState("")
    const reviewOverlayRef = useRef<HTMLDivElement | null>(null)
    const initialReviewRef = useRef<{ ocr: string; data: string } | null>(null)
    const keydownHandlerRef = useRef<((event: KeyboardEvent) => void) | null>(null)
    const [structuredJsonDraft, setStructuredJsonDraft] = useState("{}")
    const [structuredJsonError, setStructuredJsonError] = useState<string | null>(null)
    const [retryEngine, setRetryEngine] = useState<OcrEngine>("tesseract_ocr")
    const [documentRetryEngines, setDocumentRetryEngines] = useState<Record<string, OcrEngine>>({})
    const [retryingDocId, setRetryingDocId] = useState<string | null>(null)
    const [mappingHighlight, setMappingHighlight] = useState<Highlight | null>(null)
    // OCR word positions of the document under review (the job list omits ocr_pages).
    const [reviewPageWords, setReviewPageWords] = useState<Record<number, PageWord[]>>({})
    const reviewDocId = useRef<string | null>(null)
    const fileInputRef = useRef<HTMLInputElement>(null)
    const pollingIntervalsRef = useRef<Map<string, AbortController>>(new Map())
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
    const [activeTab, setActiveTab] = useState<"documents" | "agent">("documents")
    const [showJobDetails, setShowJobDetails] = useState(false)
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
    const [renamingJob, setRenamingJob] = useState(false)
    const [renameDraft, setRenameDraft] = useState("")
    const [savingJobName, setSavingJobName] = useState(false)
    const renameInputRef = useRef<HTMLInputElement>(null)

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

        return () => {
            // Tear down any active SSE streams on unmount
            pollingIntervalsRef.current.forEach(controller => controller.abort())
            pollingIntervalsRef.current.clear()
        }
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
            doc.id === docId ? {
                ...doc,
                schema_id: nextSchemaId,
            } : doc
        ))
    }

    // AnyDoc may use the backend's 20-minute document budget. Keep observing
    // long enough for its OCR fallback and avoid clearing a live job early.
    const MAX_POLL_MS = 25 * 60 * 1000

    const startPolling = (docId: string) => {
        const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
        const controller = new AbortController()
        const startTime = Date.now()
        setProcessingDocs(prev => new Set(prev).add(docId))
        pollingIntervalsRef.current.set(docId, controller)

        const cleanup = async () => {
            pollingIntervalsRef.current.delete(docId)
            setProcessingDocs(prev => { const s = new Set(prev); s.delete(docId); return s })
            setDocProgress(prev => { const p = { ...prev }; delete p[docId]; return p })
        }

        const hardTimeout = window.setTimeout(() => {
            controller.abort()
            cleanup().then(fetchDocuments)
        }, MAX_POLL_MS);

        (async () => {
            try {
                const res = await fetch(`${apiBase}/documents/${docId}/progress-stream`, {
                    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
                    signal: controller.signal,
                })
                if (!res.ok || !res.body) {
                    clearTimeout(hardTimeout)
                    await cleanup()
                    return
                }
                const reader = res.body.getReader()
                const decoder = new TextDecoder()
                let buffer = ""
                while (true) {
                    const { done, value } = await reader.read()
                    if (done) break
                    buffer += decoder.decode(value, { stream: true })
                    const lines = buffer.split("\n")
                    buffer = lines.pop() || ""
                    for (const line of lines) {
                        if (!line.startsWith("data: ")) continue
                        let evt: any
                        try {
                            evt = JSON.parse(line.slice(6))
                        } catch {
                            continue
                        }
                        if (evt.percent !== undefined) {
                            setDocProgress(prev => ({
                                ...prev,
                                [docId]: { percent: evt.percent ?? 0, stage: evt.stage ?? "" },
                            }))
                        }
                        if (
                            evt.type === "done" ||
                            evt.type === "timeout" ||
                            ["extraction_completed", "reviewed", "failed"].includes(evt.status)
                        ) {
                            clearTimeout(hardTimeout)
                            controller.abort()
                            await cleanup()
                            await fetchDocuments()
                            return
                        }
                    }
                }
            } catch (err) {
                if ((err as Error)?.name !== "AbortError") {
                    console.error("Progress stream error", err)
                }
            } finally {
                clearTimeout(hardTimeout)
                await cleanup()
            }
        })()

        return controller
    }

    const handleProcess = async (docId: string, ocrEngine?: OcrEngine) => {
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
                body: JSON.stringify({
                    schema_id: doc.schema_id || null,
                    ...(ocrEngine ? {
                        extraction_profile: "anydoc_hybrid",
                        ocr_engine: ocrEngine,
                    } : {}),
                })
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

    const handleRetryOcr = async () => {
        if (!reviewDoc || retryingDocId) return

        try {
            setRetryingDocId(reviewDoc.id)
            const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
            const res = await fetch(`${apiBase}/documents/${reviewDoc.id}/process`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    ...(token ? { Authorization: `Bearer ${token}` } : {}),
                },
                body: JSON.stringify({
                    schema_id: reviewDoc.schema_id || null,
                    extraction_profile: "anydoc_hybrid",
                    ocr_engine: retryEngine,
                }),
            })
            if (!res.ok) {
                const payload = await res.json().catch(() => null)
                throw new Error(payload?.detail || "Failed to retry OCR")
            }

            const docId = reviewDoc.id
            setReviewDoc(null)
            await fetchDocuments()
            startPolling(docId)
        } catch (error) {
            console.error("OCR retry error", error)
            alert(error instanceof Error ? error.message : "OCR retry failed")
        } finally {
            setRetryingDocId(null)
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

    const startRenameJob = () => {
        if (!job) return
        setRenameDraft(job.name)
        setRenamingJob(true)
        window.setTimeout(() => renameInputRef.current?.select(), 0)
    }

    const cancelRenameJob = () => {
        setRenamingJob(false)
        setRenameDraft(job?.name || "")
    }

    const saveJobName = async () => {
        if (!job || savingJobName) return
        const nextName = renameDraft.trim()
        if (!nextName) {
            alert("Job name cannot be empty")
            setRenameDraft(job.name)
            setRenamingJob(false)
            return
        }
        if (nextName === job.name) {
            setRenamingJob(false)
            return
        }

        try {
            setSavingJobName(true)
            const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
            const response = await fetch(`${apiBase}/jobs/${jobId}`, {
                method: "PUT",
                headers: {
                    "Content-Type": "application/json",
                    ...(token ? { Authorization: `Bearer ${token}` } : {}),
                },
                body: JSON.stringify({ name: nextName }),
            })
            if (!response.ok) {
                const error = await response.json().catch(() => null)
                throw new Error(error?.detail || "Failed to rename job")
            }
            const updatedJob = await response.json()
            setJob(updatedJob)
            setRenamingJob(false)
        } catch (error) {
            console.error("Rename job error:", error)
            alert(error instanceof Error ? error.message : "Failed to rename job")
        } finally {
            setSavingJobName(false)
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
    const canEditJob = canDeleteJob
    const reviewSchema = reviewDoc?.schema_id
        ? schemas.find((schema) => schema.id === reviewDoc.schema_id)
        : undefined
    const reviewMappingFailed = Boolean(
        reviewDoc?.extraction_metadata?.mapping
        && typeof reviewDoc.extraction_metadata.mapping !== "string"
        && reviewDoc.extraction_metadata.mapping.status === "failed"
    )

    // Live evidence: the report from the doc, or the newest one after a retry.
    const mappingReport: MappingReport | undefined = liveMapping
        ?? (reviewDoc?.extraction_metadata?.mapping && typeof reviewDoc.extraction_metadata.mapping === "object"
            ? reviewDoc.extraction_metadata.mapping as MappingReport
            : undefined)
    const evidenceFor = (name: string) => mappingReport?.fields?.[name]
    const fieldStatusOf = (name: string) => evidenceFor(name)?.status || "needs_review"
    const isFieldResolved = (name: string) =>
        dirtyFields.has(name) || confirmedFields.has(name) || confirmedMissing.has(name)
    const statusCounts = useMemo(() => {
        const counts = { all: 0, needs_review: 0, source_matched: 0, missing: 0, failed: 0 }
        for (const field of reviewSchema?.fields || []) {
            counts.all += 1
            const status = fieldStatusOf(field.name)
            if (status in counts) counts[status as keyof typeof counts] += 1
            else counts.needs_review += 1
        }
        return counts
    }, [reviewSchema, mappingReport])
    const resolvedCount = (reviewSchema?.fields || []).filter((field) => isFieldResolved(field.name)).length
    const undecidedRequired = (reviewSchema?.fields || []).filter(
        (field) => field.required && !isFieldResolved(field.name) && !(fieldStatusOf(field.name) === "missing" && confirmedMissing.has(field.name)))
    const visibleFields = useMemo(() => {
        const fields = [...(reviewSchema?.fields || [])]
        fields.sort((a, b) => {
            const rank = (name: string) => (isFieldResolved(name) ? 9 : fieldStatusOf(name) === "needs_review" ? 0 : fieldStatusOf(name) === "failed" ? 1 : 2)
            return rank(a.name) - rank(b.name)
        })
        if (fieldFilter === "all") return fields
        return fields.filter((field) => fieldStatusOf(field.name) === fieldFilter)
    }, [reviewSchema, fieldFilter, mappingReport, confirmedFields, confirmedMissing, dirtyFields])

    const confirmField = (name: string) => setConfirmedFields((previous) => new Set(previous).add(name))
    const confirmFieldMissing = (name: string) => setConfirmedMissing((previous) => new Set(previous).add(name))
    const confirmAllMatched = () => {
        const next = new Set(confirmedFields)
        for (const field of reviewSchema?.fields || []) {
            if (fieldStatusOf(field.name) === "source_matched") next.add(field.name)
        }
        setConfirmedFields(next)
    }
    const retrySingleField = async (name: string) => {
        if (!reviewDoc || fieldRetryBusy) return
        setFieldRetryBusy(name)
        try {
            const { runMappingRetry } = await import("@/components/document/MappingPanel")
            const result = await runMappingRetry(reviewDoc.id, mappingEngine, [name])
            setLiveMapping(result.mapping ?? null)
            const value = result.values?.[name]
            if (value !== undefined && value !== null && value !== "") updateStructuredField(name, value)
        } catch {
            // Field-level retry failures stay visible via the evidence status.
        } finally {
            setFieldRetryBusy(null)
        }
    }

    /** Apply a mapping result straight into the editor (retry = no intermediate proposal step). */
    const applyMappingValues = (values: Record<string, unknown>, report?: MappingReport) => {
        applySnapshot.current = {
            data: editedStructuredData, drafts: arrayDrafts, json: structuredJsonDraft,
            mapping: liveMapping, confirmed: confirmedFields, missing: confirmedMissing,
        }
        const previous = editedStructuredData && !Array.isArray(editedStructuredData) ? editedStructuredData : {}
        let keptEdits = 0
        const merged: Record<string, unknown> = { ...previous }
        for (const [key, value] of Object.entries(values || {})) {
            if (dirtyFields.has(key) && previous[key] !== value) { keptEdits += 1; continue }
            merged[key] = value
        }
        setEditedStructuredData(merged)
        setStructuredJsonDraft(JSON.stringify(merged, null, 2))
        setStructuredJsonError(null)
        const reviewCount = Object.values(report?.fields || {}).filter((item) => (item?.status || "needs_review") === "needs_review").length
        setApplyBar({ updated: Object.keys(values || {}).length - keptEdits, review: reviewCount, keptEdits })
        setFieldFilter("needs_review")
        setReviewDoc(previousDoc => previousDoc ? { ...previousDoc, extraction_metadata: { ...previousDoc.extraction_metadata, mapping: { status: "completed" } } } : previousDoc)
        const firstReview = (reviewSchema?.fields || []).find((field) => (report?.fields?.[field.name]?.status || "needs_review") === "needs_review")
        setExpandedField(firstReview?.name ?? null)
    }

    const retryAll = async () => {
        if (!reviewDoc || mappingBusy) return
        setMappingBusy(true)
        setMappingError("")
        try {
            const { runMappingRetry } = await import("@/components/document/MappingPanel")
            const result = await runMappingRetry(reviewDoc.id, mappingEngine)
            setLiveMapping(result.mapping ?? null)
            applyMappingValues(result.values || {}, result.mapping)
        } catch (e) {
            setMappingError(e instanceof Error ? e.message : "Mapping retry failed")
        } finally {
            setMappingBusy(false)
        }
    }

    /** Human-readable preview for compact field rows: arrays/objects/booleans never render as [object Object]. */
    const previewOf = (value: unknown, missing?: boolean): string => {
        if (value === null || value === undefined || value === "") return missing ? "— ไม่พบ —" : "—"
        if (Array.isArray(value)) {
            if (value.length === 0) return "— รายการว่าง —"
            const first = value[0]
            const firstSummary = first !== null && typeof first === "object" ? JSON.stringify(first) : String(first)
            const clipped = firstSummary.length > 48 ? `${firstSummary.slice(0, 48)}…` : firstSummary
            return `${value.length} รายการ · ${clipped}`
        }
        if (typeof value === "object") {
            const json = JSON.stringify(value)
            return json.length > 64 ? `${json.slice(0, 64)}…` : json
        }
        if (typeof value === "boolean") return value ? "ใช่" : "ไม่ใช่"
        return String(value)
    }

    /** Status is always shape + color (never hue alone) so color-blind reviewers can tell states apart. */
    const statusVisual = (status: string, resolved: boolean): { Icon: typeof AlertTriangle; cls: string; label: string } => {
        if (resolved) return { Icon: CheckCircle2, cls: "text-emerald-600", label: "ตรวจแล้ว" }
        if (status === "source_matched") return { Icon: FileCheck, cls: "text-blue-600", label: "ตรงเอกสาร" }
        if (status === "missing") return { Icon: Minus, cls: "text-slate-400", label: "ไม่พบ" }
        if (status === "failed") return { Icon: XCircle, cls: "text-red-600", label: "ผิดพลาด" }
        return { Icon: AlertTriangle, cls: "text-amber-500", label: "รอตรวจ" }
    }

    const hasUnsavedChanges = () => {
        if (!reviewDoc || !initialReviewRef.current) return false
        const ocrChanged = editedOcrText !== initialReviewRef.current.ocr
        const dataChanged = JSON.stringify(editedStructuredData ?? null) !== initialReviewRef.current.data
        return ocrChanged || dataChanged
    }

    /** Close the review overlay, guarding against losing unsaved edits (Escape and Cancel both route here). */
    const closeReview = () => {
        if (hasUnsavedChanges()) {
            const proceed = window.confirm("ยังมีการแก้ไขที่ยังไม่ได้บันทึก — ปิดหน้าตรวจเลยหรือไม่? (ยกเลิก = กลับไปทำงานต่อ)")
            if (!proceed) return
        }
        setReviewDoc(null)
        setSaveNotice("")
    }

    /** Jump to the next unresolved field in the given direction (wraps around); returns its name or null. */
    const goNextField = (afterName?: string, direction: 1 | -1 = 1): string | null => {
        const fields = reviewSchema?.fields || []
        if (fields.length === 0) return null
        const startIdx = afterName ? fields.findIndex((field) => field.name === afterName) : direction === 1 ? -1 : 0
        for (let step = 1; step <= fields.length; step += 1) {
            const field = fields[((startIdx + direction * step) % fields.length + fields.length) % fields.length]
            if (!isFieldResolved(field.name)) {
                setFieldFilter("all")
                setExpandedField(field.name)
                locateFieldByName(field.name)
                requestAnimationFrame(() => document.getElementById(`field-row-${field.name}`)?.scrollIntoView({ behavior: "smooth", block: "center" }))
                return field.name
            }
        }
        return null
    }

    /** Resolve the current field the right way for its state, then move to the next unresolved one. */
    const resolveAndNext = (fieldName: string) => {
        const status = fieldStatusOf(fieldName)
        if (status === "source_matched") confirmField(fieldName)
        else if (status === "missing") confirmFieldMissing(fieldName)
        else if (!dirtyFields.has(fieldName)) {
            // Typed values resolve through dirtyFields on change; empty untouched
            // values still count as a decision once the reviewer moves on.
            confirmField(fieldName)
        }
        const next = goNextField(fieldName)
        if (!next) setExpandedField(null)
    }

    // Keep the overlay-scoped keyboard handler fresh without re-binding listeners.
    keydownHandlerRef.current = (event: KeyboardEvent) => {
        if (!reviewDoc) return
        if (event.key === "Escape") {
            event.preventDefault()
            closeReview()
            return
        }
        if (event.key === "Tab") {
            const overlay = reviewOverlayRef.current
            if (!overlay) return
            const focusables = Array.from(overlay.querySelectorAll<HTMLElement>('button, input, select, textarea, a[href], [tabindex]:not([tabindex="-1"])'))
                .filter((el) => !(el as HTMLButtonElement).disabled && el.offsetParent !== null)
            if (focusables.length === 0) return
            const first = focusables[0]
            const last = focusables[focusables.length - 1]
            const active = document.activeElement
            if (!overlay.contains(active)) { event.preventDefault(); first.focus() }
            else if (event.shiftKey && active === first) { event.preventDefault(); last.focus() }
            else if (!event.shiftKey && active === last) { event.preventDefault(); first.focus() }
            return
        }
        const target = event.target as HTMLElement | null
        const typing = target?.closest("input, textarea, select, [contenteditable]")
        if (!typing && (event.key === "n" || event.key === "p") && (reviewTab === "fields" || reviewTab === "json")) {
            event.preventDefault()
            goNextField(expandedField ?? undefined, event.key === "n" ? 1 : -1)
        }
    }

    useEffect(() => {
        const listener = (event: KeyboardEvent) => keydownHandlerRef.current?.(event)
        window.addEventListener("keydown", listener)
        return () => window.removeEventListener("keydown", listener)
    }, [])

    // Move focus into the dialog when it opens.
    useEffect(() => {
        if (reviewDoc) reviewOverlayRef.current?.focus()
    }, [reviewDoc?.id])

    const handleReviewTab = (tab: "fields" | "json" | "text" | "ocr") => {
        if (tab === "json") handleStructuredDataTabChange("advanced")
        else if (structuredDataTab === "advanced") handleStructuredDataTabChange("fields")
        setStructuredDataTab(tab === "json" ? "advanced" : "fields")
        setReviewTab(tab)
    }

    const updateStructuredField = (fieldName: string, value: unknown) => {
        setDirtyFields((previous) => new Set(previous).add(fieldName))
        setEditedStructuredData((previous) => ({
            ...(previous && !Array.isArray(previous) ? previous : {}),
            [fieldName]: value,
        }))
    }

    const parseStructuredJsonDraft = (): Record<string, any> | Record<string, any>[] | null => {
        try {
            const parsed = JSON.parse(structuredJsonDraft)
            if (!parsed || typeof parsed !== "object") {
                throw new Error("Structured Data must be a JSON object or array")
            }
            setStructuredJsonError(null)
            return parsed
        } catch (error) {
            setStructuredJsonError(error instanceof Error ? error.message : "Invalid JSON")
            return null
        }
    }

    const handleStructuredDataTabChange = (nextTab: "fields" | "advanced") => {
        if (nextTab === "fields" && structuredDataTab === "advanced") {
            const parsed = parseStructuredJsonDraft()
            if (!parsed) return
            setEditedStructuredData(parsed)
            setArrayDrafts({})
        }
        if (nextTab === "advanced") {
            let nextData: Record<string, any> | Record<string, any>[] = editedStructuredData || {}
            if (!Array.isArray(nextData) && Object.keys(arrayDrafts).length > 0) {
                nextData = { ...nextData }
                for (const [fieldName, draft] of Object.entries(arrayDrafts)) {
                    try {
                        nextData[fieldName] = JSON.parse(draft)
                    } catch {
                        setStructuredJsonError(`The ${fieldName} list must be valid JSON before opening Advanced JSON`)
                        return
                    }
                }
                setEditedStructuredData(nextData)
                setArrayDrafts({})
            }
            setStructuredJsonDraft(JSON.stringify(nextData, null, 2))
            setStructuredJsonError(null)
        }
        setStructuredDataTab(nextTab)
    }

    const handleReview = (doc: Document) => {
        setMappingHighlight(null)
        setReviewPageWords({})
        reviewDocId.current = doc.id
        setLiveMapping(null)
        setFieldFilter("needs_review")
        setConfirmedFields(new Set())
        setConfirmedMissing(new Set())
        setDirtyFields(new Set())
        setApplyBar(null)
        applySnapshot.current = null
        setFieldRetryBusy(null)
        setReviewTab("fields")
        setExpandedField(null)
        setMappingBusy(false)
        setMappingError("")
        setMobileView("fields")
        const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
        fetch(`${apiBase}/documents/${doc.id}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
            .then((res) => res.ok ? res.json() : null)
            .then((detail) => {
                // Ignore a slow answer for a document the reviewer has already left.
                if (!detail || reviewDocId.current !== doc.id) return
                setReviewPageWords(pageWordsFrom(detail.ocr_pages))
                // Seed review decisions persisted from a previous session (Save).
                const savedReview = detail?.extraction_metadata?.review?.fields
                if (savedReview && typeof savedReview === "object") {
                    const confirmed = new Set<string>()
                    const missing = new Set<string>()
                    const edited = new Set<string>()
                    for (const [name, info] of Object.entries(savedReview as Record<string, { state?: string }>)) {
                        if (info?.state === "confirmed") confirmed.add(name)
                        else if (info?.state === "confirmed_missing") missing.add(name)
                        else if (info?.state === "edited") edited.add(name)
                    }
                    setConfirmedFields(confirmed)
                    setConfirmedMissing(missing)
                    setDirtyFields(edited)
                }
            })
            .catch(() => { /* positions are optional; the text layer is still searched */ })
        setReviewDoc(doc)
        setRejectConfirm(false)
        setEditedOcrText(doc.ocr_text || "")
        const structuredData = doc.reviewed_data || doc.extracted_data || {}
        setEditedStructuredData(
            structuredData && typeof structuredData === "object"
                ? structuredData
                : null
        )
        setArrayDrafts({})
        setStructuredDataTab("fields")
        setStructuredJsonDraft(JSON.stringify(structuredData && typeof structuredData === "object" ? structuredData : {}, null, 2))
        initialReviewRef.current = { ocr: doc.ocr_text || "", data: JSON.stringify(structuredData && typeof structuredData === "object" ? structuredData : null) }
        setSaveNotice("")
        setStructuredJsonError(null)
        setRetryEngine("tesseract_ocr")
    }

    const handleSaveReview = async () => {
        if (!reviewDoc) return

        // Save gate: remind the reviewer about required fields still lacking a decision.
        if (undecidedRequired.length > 0 && reviewSchema?.fields.length) {
            const proceed = window.confirm(
                `ยังมีฟิลด์ที่ต้องกรอก (required) อีก ${undecidedRequired.length} รายการที่ยังไม่ได้ตรวจสอบ:\n`
                + undecidedRequired.slice(0, 8).map((field) => `• ${field.name}`).join("\n")
                + (undecidedRequired.length > 8 ? `\n… และอีก ${undecidedRequired.length - 8} รายการ` : "")
                + "\n\nต้องการบันทึกเลยหรือไม่? (ยกเลิก = กลับไปตรวจก่อน)"
            )
            if (!proceed) { setFieldFilter("all"); return }
        }

        let reviewedData: Record<string, any> | Record<string, any>[] | undefined = editedStructuredData || undefined
        if (structuredDataTab === "advanced") {
            const parsed = parseStructuredJsonDraft()
            if (!parsed) {
                alert("Structured Data must be valid JSON before saving")
                return
            }
            reviewedData = parsed
        }
        if (reviewedData) {
            for (const [fieldName, draft] of Object.entries(arrayDrafts)) {
                try {
                    reviewedData = { ...reviewedData, [fieldName]: JSON.parse(draft) }
                } catch {
                    alert(`The ${fieldName} list must be valid JSON before saving`)
                    return
                }
            }
        }

        try {
            const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
            // Persist per-field review decisions so reopening the document keeps them.
            const reviewedAt = new Date().toISOString()
            const reviewFields: Record<string, { state: string; at: string }> = {}
            confirmedFields.forEach((name) => { reviewFields[name] = { state: "confirmed", at: reviewedAt } })
            confirmedMissing.forEach((name) => { reviewFields[name] = { state: "confirmed_missing", at: reviewedAt } })
            dirtyFields.forEach((name) => { if (!reviewFields[name]) reviewFields[name] = { state: "edited", at: reviewedAt } })
            const nextMetadata = { ...(reviewDoc.extraction_metadata || {}), review: { fields: reviewFields } }
            const res = await fetch(`${apiBase}/documents/${reviewDoc.id}`, {
                method: "PUT",
                headers: {
                    "Content-Type": "application/json",
                    ...(token ? { Authorization: `Bearer ${token}` } : {})
                },
                body: JSON.stringify({
                    ocr_text: editedOcrText,
                    status: "reviewed",
                    ...(reviewedData !== undefined ? { reviewed_data: reviewedData } : {}),
                    extraction_metadata: nextMetadata,
                })
            })

            if (res.ok) {
                // Review queue: move straight to the next document waiting for review.
                const nextDoc = documents.find((d) => d.id !== reviewDoc.id && d.status === "extraction_completed")
                await fetchDocuments()
                if (nextDoc) {
                    handleReview(nextDoc)
                    setSaveNotice(`บันทึกแล้ว — กำลังตรวจถัดไป: ${nextDoc.filename}`)
                } else {
                    setReviewDoc(null)
                    setSaveNotice("")
                }
            } else {
                alert("Save failed")
            }
        } catch (error) {
            console.error("Save error", error)
            alert("Save error")
        }
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
        if (integration?.type === "llm" || integration?.type === "softnix_genai") {
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

    // Show where a field's value is on the PDF: the stored box for fixed-position
    // fields, otherwise the page text is searched for the quote or the value.
    const locateField = (name: string, value: unknown, type?: string,
                         given?: { page?: number; bbox?: Highlight["bbox"]; quote?: string; raw_text?: string }) => {
        const evidence = given ?? (reviewDoc?.extraction_metadata?.mapping as MappingReport | undefined)?.fields?.[name]
        setMappingHighlight({
            page: evidence?.page, bbox: evidence?.bbox, label: name,
            texts: evidenceSearchTexts(value, evidence, type),
        })
    }

    /** Expand-and-show: locate a field's evidence by name (row click and keyboard queue both use this). */
    const locateFieldByName = (name: string) => {
        const value = editedStructuredData && !Array.isArray(editedStructuredData) ? editedStructuredData[name] : undefined
        locateField(name, value, reviewSchema?.fields.find((field) => field.name === name)?.type, mappingReport?.fields?.[name])
    }
    const reviewIsPdf = !!reviewDoc && !(previewImageExtensions.has(reviewDoc.filename.toLowerCase().split('.').pop() || '')
        || reviewDoc.mime_type?.startsWith('image/'))

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
    const selectedIntegrationDetails = integrations.find(integration => integration.id === selectedIntegration)
    const integrationTypeMeta: Record<IntegrationType, { label: string; icon: typeof Plug; className: string }> = {
        api: { label: "Custom API", icon: Plug, className: "bg-slate-100 text-slate-600" },
        workflow: { label: "Workflow", icon: Workflow, className: "bg-red-50 text-red-600" },
        llm: { label: "LLM Provider", icon: Bot, className: "bg-emerald-50 text-emerald-700" },
        softnix_genai: { label: "Softnix GenAI", icon: Bot, className: "bg-cyan-50 text-cyan-700" },
        gdrive: { label: "Google Drive", icon: Cloud, className: "bg-blue-50 text-blue-600" },
        onedrive: { label: "OneDrive", icon: Cloud, className: "bg-sky-50 text-sky-600" },
    }

    return (
        <div className="space-y-6">
            <div className="flex items-center space-x-4">
                <Link href="/jobs">
                    <Button variant="ghost" size="icon">
                        <ArrowLeft className="h-4 w-4" />
                    </Button>
                </Link>
                <div className="min-w-0 flex-1">
                    <div className="flex min-h-10 items-center gap-2">
                        {renamingJob ? (
                            <>
                                <Input
                                    ref={renameInputRef}
                                    value={renameDraft}
                                    onChange={(event) => setRenameDraft(event.target.value)}
                                    onBlur={saveJobName}
                                    onKeyDown={(event) => {
                                        if (event.key === "Enter") {
                                            event.preventDefault()
                                            saveJobName()
                                        }
                                        if (event.key === "Escape") {
                                            event.preventDefault()
                                            cancelRenameJob()
                                        }
                                    }}
                                    disabled={savingJobName}
                                    className="h-10 max-w-xl text-2xl font-bold tracking-tight"
                                    aria-label="Job name"
                                />
                                <Button type="button" variant="ghost" size="icon" onMouseDown={(event) => event.preventDefault()} onClick={saveJobName} disabled={savingJobName} title="Save job name">
                                    {savingJobName ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
                                </Button>
                                <Button type="button" variant="ghost" size="icon" onMouseDown={(event) => event.preventDefault()} onClick={cancelRenameJob} disabled={savingJobName} title="Cancel rename">
                                    <X className="h-4 w-4" />
                                </Button>
                            </>
                        ) : (
                            <>
                                <h2 className="truncate text-2xl font-bold tracking-tight">{job.name}</h2>
                                {canEditJob && (
                                    <Button type="button" variant="ghost" size="icon" onClick={startRenameJob} title="Rename job">
                                        <Pencil className="h-4 w-4" />
                                    </Button>
                                )}
                            </>
                        )}
                    </div>
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

            {/* Job Summary Bar */}
            <div className="rounded-lg border bg-white p-4 shadow-sm">
                <div className="flex items-center gap-4 flex-wrap">
                    <div className="flex items-center gap-2 text-sm">
                        <span className="text-slate-500">Docs:</span>
                        <span className="font-medium text-slate-700">{documents.length}</span>
                    </div>
                    {docCounts.uploaded > 0 && (
                        <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-amber-50 text-amber-700 border border-amber-200">
                            <span className="w-1.5 h-1.5 rounded-full bg-amber-500" /> {docCounts.uploaded} Uploaded
                        </span>
                    )}
                    {docCounts.processing > 0 && (
                        <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-blue-50 text-blue-700 border border-blue-200">
                            <span className="w-1.5 h-1.5 rounded-full bg-blue-500" /> {docCounts.processing} Processing
                        </span>
                    )}
                    {docCounts.extraction_completed > 0 && (
                        <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200">
                            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" /> {docCounts.extraction_completed} Extracted
                        </span>
                    )}
                    {docCounts.reviewed > 0 && (
                        <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-purple-50 text-purple-700 border border-purple-200">
                            <span className="w-1.5 h-1.5 rounded-full bg-purple-500" /> {docCounts.reviewed} Reviewed
                        </span>
                    )}

                    <div className="ml-auto flex items-center gap-2">
                        {allDocsReviewed && (
                            <Button size="sm" onClick={() => setShowIntegrationModal(true)}>
                                Next: Send to Integration
                            </Button>
                        )}
                        {resultHistory.length > 0 && (
                            <Button variant="ghost" size="sm"
                                onClick={() => { setShowJobDetails(!showJobDetails); if (!showJobDetails) loadResultHistory() }}
                                className="text-slate-500">
                                <FileText className="h-3.5 w-3.5 mr-1.5" />
                                History ({resultHistory.length})
                            </Button>
                        )}
                        <Button variant="ghost" size="sm"
                            onClick={() => setShowJobDetails(!showJobDetails)}
                            className="text-slate-500">
                            <ChevronDown className={`h-3.5 w-3.5 mr-1 transition-transform ${showJobDetails ? "rotate-180" : ""}`} />
                            {showJobDetails ? "Hide Details" : "Details"}
                        </Button>
                    </div>
                </div>

                {/* Collapsible Details Panel */}
                {showJobDetails && (
                    <div className="mt-4 pt-4 border-t grid grid-cols-1 md:grid-cols-2 gap-6">
                        <div>
                            <h4 className="text-sm font-semibold text-slate-700 mb-2">Job Info</h4>
                            <dl className="space-y-1.5 text-sm">
                                <div className="flex justify-between py-1 border-b border-dashed border-slate-100">
                                    <dt className="text-slate-500">Created</dt>
                                    <dd className="font-medium text-slate-900">{createdDateTime}</dd>
                                </div>
                                {job.user_name && (
                                    <div className="flex justify-between py-1 border-b border-dashed border-slate-100">
                                        <dt className="text-slate-500">Uploaded By</dt>
                                        <dd className="font-medium text-slate-900">{job.user_name}</dd>
                                    </div>
                                )}
                                <div className="flex justify-between py-1 border-b border-dashed border-slate-100">
                                    <dt className="text-slate-500">Status</dt>
                                    <dd className="font-medium text-slate-900 capitalize">{job.status}</dd>
                                </div>
                                <div className="flex justify-between py-1 border-b border-dashed border-slate-100">
                                    <dt className="text-slate-500">Documents</dt>
                                    <dd className="font-medium text-slate-900">{documents.length}</dd>
                                </div>
                                {job.description && (
                                    <div className="flex justify-between py-1 border-b border-dashed border-slate-100">
                                        <dt className="text-slate-500">Description</dt>
                                        <dd className="font-medium text-slate-900 truncate max-w-[200px]">{job.description}</dd>
                                    </div>
                                )}
                            </dl>
                        </div>
                        <div>
                            <h4 className="text-sm font-semibold text-slate-700 mb-2">Integration History</h4>
                            {resultHistory.length === 0 ? (
                                <p className="text-xs text-slate-400">No integration results yet.</p>
                            ) : (
                                <div className="space-y-1.5 max-h-48 overflow-y-auto">
                                    {resultHistory.map((r) => {
                                        const isLlm = r.integration_type === "llm" || r.integration_type === "softnix_genai"
                                        const typeBadge = r.integration_type === "llm" ? "LLM" : r.integration_type === "softnix_genai" ? "Softnix GenAI" : r.integration_type === "api" ? "API" : r.integration_type === "workflow" ? "Workflow" : r.integration_type || "—"
                                        const typeBgColor = isLlm ? "bg-[#ebf8ff] text-[#2b6cb0]" : r.integration_type === "api" ? "bg-[#fffaf0] text-[#c05621]" : "bg-[#f0fff4] text-[#276749]"
                                        const rowContent = (
                                            <>
                                                <div className="flex items-center gap-2 min-w-0 flex-1">
                                                    <span className={`inline-block w-2 h-2 rounded-full flex-shrink-0 ${r.status === "success" ? "bg-[#276749]" : "bg-[#c53030]"}`} />
                                                    <span className="text-[#2d3748] truncate text-xs">
                                                        {new Date(r.created_at).toLocaleString("th-TH", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" })}
                                                    </span>
                                                </div>
                                                <div className="flex items-center gap-1.5 flex-shrink-0">
                                                    <span className={`text-xs font-medium px-1.5 py-0.5 rounded ${typeBgColor}`}>{typeBadge}</span>
                                                    <span className={`text-xs font-bold px-1.5 py-0.5 rounded-full ${r.status === "success" ? "bg-[#f0fff4] text-[#276749]" : "bg-[#fff5f5] text-[#c53030]"}`}>
                                                        {r.status === "success" ? "PASS" : "FAILED"}
                                                    </span>
                                                </div>
                                            </>
                                        )
                                        return isLlm ? (
                                            <button key={r.id} onClick={() => handleViewHistoryResult(r.id)}
                                                className="w-full text-left px-3 py-2 rounded-lg border border-[#e2e8f0] hover:bg-[#ebf8ff] hover:border-[#2b6cb0]/30 transition-colors text-xs flex items-center justify-between gap-2 cursor-pointer"
                                                title={r.integration_name || "ดูผลลัพธ์"}>
                                                {rowContent}
                                                <Eye className="h-3 w-3 text-[#2b6cb0] flex-shrink-0" />
                                            </button>
                                        ) : (
                                            <div key={r.id}
                                                className="w-full text-left px-3 py-2 rounded-lg border border-[#e2e8f0] text-xs flex items-center justify-between gap-2"
                                                title={r.integration_name || ""}>
                                                {rowContent}
                                            </div>
                                        )
                                    })}
                                </div>
                            )}
                        </div>
                    </div>
                )}
            </div>

            {/* Tabs */}
            <div className="flex border-b border-slate-200">
                <button
                    onClick={() => setActiveTab("documents")}
                    className={`px-5 py-3 text-sm font-medium border-b-2 transition-colors flex items-center gap-2 ${
                        activeTab === "documents"
                            ? "border-blue-600 text-blue-600"
                            : "border-transparent text-slate-500 hover:text-slate-700 hover:border-slate-300"
                    }`}
                >
                    <FileText className="h-4 w-4" />
                    Document List
                </button>
                <button
                    onClick={() => setActiveTab("agent")}
                    className={`px-5 py-3 text-sm font-medium border-b-2 transition-colors flex items-center gap-2 ${
                        activeTab === "agent"
                            ? "border-blue-600 text-blue-600"
                            : "border-transparent text-slate-500 hover:text-slate-700 hover:border-slate-300"
                    }`}
                >
                    <Bot className="h-4 w-4" />
                    AI Agent
                </button>
            </div>

            {/* Tab Content */}
            {activeTab === "documents" && (
                <div className="space-y-6">
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
                                    const pipeline = doc.extraction_metadata?.pipeline
                                    const canManuallyRetryOcr = doc.status === "failed" && supportsManualOcrRetry(doc)

                                    return (
                                        <div key={doc.id} className="p-4 border rounded-md bg-slate-50">
                                            <div className="mb-3 flex items-center gap-3">
                                                <FileText className="h-5 w-5 shrink-0 text-slate-500" />
                                                <span className="min-w-0 flex-1 truncate text-sm font-medium">{doc.filename}</span>
                                                <div className="flex shrink-0 items-center gap-2">
                                                    {doc.processing_error && doc.status !== "failed" && (
                                                        <span className="inline-flex items-center gap-1 rounded-full border border-amber-200 bg-amber-50 px-2 py-1 text-xs text-amber-700" title={doc.processing_error}>
                                                            <AlertTriangle className="h-3 w-3" />
                                                            {doc.extraction_metadata?.mapping && typeof doc.extraction_metadata.mapping !== "string" && doc.extraction_metadata.mapping.status === "failed"
                                                                ? "Mapping failed"
                                                                : "OCR degraded"}
                                                        </span>
                                                    )}
                                                    <span className={`rounded-full border px-2.5 py-1 text-xs font-medium capitalize ${getStatusColor(doc.status)}`}>
                                                        {doc.status.replace(/_/g, ' ')}
                                                    </span>
                                                    {canReview && (
                                                        <Button
                                                            onClick={() => handleReview(doc)}
                                                            size="sm"
                                                            variant="outline"
                                                            className="h-8"
                                                        >
                                                            <Eye className="mr-2 h-4 w-4" />
                                                            Preview
                                                        </Button>
                                                    )}
                                                </div>
                                            </div>

                                            {pipeline && (
                                                <div className="mb-3 flex flex-wrap items-center gap-2 text-xs">
                                                    {pipeline === "anydoc_hybrid" && doc.extraction_metadata?.source === "image" && <span className="rounded-full bg-slate-100 px-2 py-1 font-medium text-slate-700">Image</span>}
                                                    {pipeline === "anydoc_hybrid" && (doc.extraction_metadata?.text_layer_pages?.length ?? 0) > 0 && <span className="rounded-full bg-sky-50 px-2 py-1 font-medium text-sky-700">AnyDoc Text Layer</span>}
                                                    {(doc.extraction_metadata?.text_layer_invalid_pages?.length ?? 0) > 0 && <span className="rounded-full bg-amber-50 px-2 py-1 font-medium text-amber-700">Text Layer repaired</span>}
                                                    {(doc.extraction_metadata?.tesseract_pages?.length ?? 0) > 0 && <span className="rounded-full bg-violet-50 px-2 py-1 font-medium text-violet-700">TesseractOCR</span>}
                                                    {(doc.extraction_metadata?.softnix_ocr_pages?.length ?? 0) > 0 && <span className="rounded-full bg-blue-50 px-2 py-1 font-medium text-blue-700">Softnix OCR</span>}
                                                    {(pipeline === "ocr_fallback" || doc.extraction_metadata?.fallback_pages?.length) ? <span className="rounded-full bg-amber-50 px-2 py-1 font-medium text-amber-700">OCR fallback</span> : null}
                                                    {pipeline === "legacy_fallback" && <span className="rounded-full bg-amber-50 px-2 py-1 font-medium text-amber-700" title={doc.extraction_metadata?.legacy_fallback?.reason}>Legacy fallback</span>}
                                                </div>
                                            )}

                                            <div className={`grid gap-2 ${canManuallyRetryOcr ? "md:grid-cols-[minmax(0,1fr)_minmax(10rem,0.35fr)_auto_auto]" : "md:grid-cols-[minmax(0,1fr)_auto]"}`}>
                                                <div className="min-w-0 space-y-1">
                                                    <label className="text-xs font-medium text-slate-500">Schema</label>
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
                                                </div>

                                                {canManuallyRetryOcr && (
                                                    <div className="min-w-0 space-y-1">
                                                        <label className="text-xs font-medium text-slate-500" htmlFor={`ocr-engine-${doc.id}`}>
                                                            OCR engine
                                                        </label>
                                                        <select
                                                            id={`ocr-engine-${doc.id}`}
                                                            value={documentRetryEngines[doc.id] || "tesseract_ocr"}
                                                            onChange={(event) => setDocumentRetryEngines((previous) => ({
                                                                ...previous,
                                                                [doc.id]: event.target.value as OcrEngine,
                                                            }))}
                                                            disabled={isProcessing}
                                                            className="flex h-9 w-full rounded-md border border-slate-200 bg-white px-3 py-1 text-sm"
                                                        >
                                                            {ocrEngineOptions.map((option) => (
                                                                <option key={option.value} value={option.value}>{option.label}</option>
                                                            ))}
                                                        </select>
                                                    </div>
                                                )}

                                                {(doc.status === "uploaded" || doc.status === "queued" || doc.status === "failed") && (
                                                    <>
                                                        <Button
                                                            onClick={() => handleProcess(
                                                                doc.id,
                                                                canManuallyRetryOcr
                                                                    ? (documentRetryEngines[doc.id] || "tesseract_ocr")
                                                                    : undefined,
                                                            )}
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
            )}

            {activeTab === "agent" && (
                <AgentPanel jobId={jobId} mode="inline" />
            )}

            {/* Review Modal - Full Screen */}
            {reviewDoc && (
                <div ref={reviewOverlayRef} role="dialog" aria-modal="true" aria-label={`ตรวจเอกสาร ${reviewDoc.filename}`} tabIndex={-1}
                    className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 outline-none">
                    <div className="flex h-[calc(100dvh-2rem)] w-full max-w-[min(96vw,1600px)] flex-col rounded-lg bg-white shadow-xl">
                        {/* Header */}
                        <div className="flex items-center justify-between gap-4 px-6 py-3 border-b">
                            <div className="min-w-0">
                                <h2 className="truncate text-lg font-semibold">Preview: {reviewDoc.filename}</h2>
                                {saveNotice && <p role="status" className="mt-0.5 truncate text-xs text-emerald-700">{saveNotice}</p>}
                            </div>
                            {reviewSchema && (reviewTab === "fields" || reviewTab === "json") && (
                                <div className="flex shrink-0 items-center gap-3 text-xs text-slate-500">
                                    {resolvedCount < statusCounts.all && (
                                        <button type="button" onClick={() => goNextField()}
                                            title="ถัดไป (n) · ก่อนหน้า (p) · Enter ในแถวที่ขยาย = ยืนยันและถัดไป"
                                            className="rounded-full border border-slate-300 px-2 py-0.5 text-slate-600 hover:bg-slate-50">ถัดไป →</button>
                                    )}
                                    <div className="flex items-center gap-2">
                                        <span className="whitespace-nowrap">ตรวจแล้ว {resolvedCount}/{statusCounts.all}</span>
                                        <div className="h-1.5 w-24 overflow-hidden rounded-full bg-slate-200">
                                            <div className="h-full rounded-full bg-emerald-500 transition-all" style={{ width: `${statusCounts.all ? (resolvedCount / statusCounts.all) * 100 : 0}%` }} />
                                        </div>
                                    </div>
                                </div>
                            )}
                            <Button
                                variant="ghost"
                                size="icon"
                                onClick={closeReview}
                                aria-label="ปิดหน้าตรวจ"
                            >
                                <X className="h-5 w-5" />
                            </Button>
                        </div>

                        {/* Content - document preview and a full-height extraction editor */}
                        <div className="grid flex-1 min-h-0 grid-cols-1 gap-4 overflow-y-auto p-4 lg:grid-cols-[minmax(0,1.15fr)_minmax(30rem,42rem)] lg:overflow-hidden">
                            {/* Left Column - Document Viewer (PDF or Image) */}
                            <div className={`min-h-[22rem] overflow-hidden rounded-lg bg-slate-50 lg:block lg:min-h-0 ${mobileView === "pdf" ? "block" : "hidden"}`}>
                                {(() => {
                                    const fileExt = reviewDoc.filename.toLowerCase().split('.').pop() || ''
                                    const imageExtensions = previewImageExtensions

                                    if (imageExtensions.has(fileExt) || reviewDoc.mime_type?.startsWith('image/')) {
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
                                                highlight={mappingHighlight}
                                                pageWords={reviewPageWords}
                                            />
                                        )
                                    }
                                })()}
                            </div>

                            {/* Right Column - Editable extraction */}
                            <div className={`min-h-0 flex-col gap-3 ${mobileView === "fields" ? "flex" : "hidden"} lg:flex lg:overflow-hidden`}>
                                {/* Workspace tabs + mobile view toggle */}
                                <div className="flex shrink-0 items-center gap-2">
                                    <div className="inline-flex rounded-md border border-slate-200 bg-slate-50 p-0.5 text-xs" role="tablist" aria-label="Review workspace"
                                        onKeyDown={(event) => {
                                            if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return
                                            event.preventDefault()
                                            const order = ["fields", "json", "text", "ocr"] as const
                                            const idx = order.indexOf(reviewTab)
                                            const next = order[(idx + (event.key === "ArrowRight" ? 1 : order.length - 1)) % order.length]
                                            handleReviewTab(next)
                                            requestAnimationFrame(() => document.getElementById(`review-tab-${next}`)?.focus())
                                        }}>
                                        {([
                                            ["fields", "ฟิลด์"],
                                            ["json", "{} JSON"],
                                            ["text", "ข้อความ"],
                                            ["ocr", "OCR"],
                                        ] as const).map(([key, text]) => (
                                            <button key={key} type="button" role="tab" id={`review-tab-${key}`} aria-selected={reviewTab === key}
                                                tabIndex={reviewTab === key ? 0 : -1}
                                                onClick={() => handleReviewTab(key)}
                                                className={`rounded px-2.5 py-1 font-medium transition-colors ${reviewTab === key ? "bg-white text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-700"}`}>
                                                {text}
                                            </button>
                                        ))}
                                    </div>
                                    <div className="ml-auto flex items-center gap-1 lg:hidden">
                                        <button type="button" aria-label="ดูเอกสาร" onClick={() => setMobileView("pdf")}
                                            className={`rounded border px-2 py-1 text-xs ${mobileView === "pdf" ? "border-blue-400 bg-blue-50 text-blue-700" : "border-slate-200 text-slate-500"}`}>เอกสาร</button>
                                        <button type="button" aria-label="ดูฟิลด์" onClick={() => setMobileView("fields")}
                                            className={`rounded border px-2 py-1 text-xs ${mobileView === "fields" ? "border-blue-400 bg-blue-50 text-blue-700" : "border-slate-200 text-slate-500"}`}>ฟิลด์</button>
                                    </div>
                                </div>

                                {/* AI Processing Warning Banner */}
                                {reviewDoc.processing_error && (
                                    <div className="flex shrink-0 items-start gap-3 rounded-lg border border-amber-300 bg-amber-50 p-4">
                                        <AlertTriangle className="h-5 w-5 text-amber-600 flex-shrink-0 mt-0.5" />
                                        <div>
                                            <p className="text-sm font-semibold text-amber-800">
                                                {reviewMappingFailed ? "Schema Mapping Warning" : "OCR Quality Warning"}
                                            </p>
                                            <p className="mt-1 text-xs text-amber-700">
                                                {reviewMappingFailed
                                                    ? "AI Extract is available, but Structured Data was not created."
                                                    : "The extracted text may need review."}
                                            </p>
                                            <details className="mt-2">
                                                <summary className="text-xs text-amber-600 cursor-pointer hover:underline">Show details</summary>
                                                <code className="text-xs text-amber-700 block mt-1 break-all whitespace-pre-wrap">{reviewDoc.processing_error}</code>
                                            </details>
                                        </div>
                                    </div>
                                )}

                                {/* Manual OCR retry */}
                                {reviewTab === "ocr" && (
                                <div className="flex min-h-0 flex-1 flex-col items-start justify-center gap-3 rounded-lg border border-slate-200 bg-slate-50 p-4">
                                    <div className="min-w-0">
                                        <p className="text-sm font-semibold text-slate-700">Re-run OCR</p>
                                        <p className="mt-0.5 text-xs text-slate-500">
                                            เลือก engine เพื่ออ่านเอกสารใหม่แทนผลเดิม
                                            {(reviewDoc.extraction_metadata?.text_layer_invalid_pages?.length ?? 0) > 0 && " พบ Text Layer encoding ผิด"}
                                        </p>
                                    </div>
                                    <div className="flex items-end gap-2">
                                        <label className="text-xs font-medium text-slate-600">
                                            OCR engine
                                            <select
                                                value={retryEngine}
                                                onChange={(event) => setRetryEngine(event.target.value as OcrEngine)}
                                                disabled={retryingDocId === reviewDoc.id}
                                                className="mt-1 flex h-9 min-w-40 rounded-md border border-slate-200 bg-white px-2.5 text-sm font-normal text-slate-800"
                                            >
                                                {ocrEngineOptions.map((option) => (
                                                    <option key={option.value} value={option.value}>{option.label}</option>
                                                ))}
                                            </select>
                                        </label>
                                        <Button
                                            type="button"
                                            variant="outline"
                                            onClick={handleRetryOcr}
                                            disabled={retryingDocId === reviewDoc.id}
                                            className="h-9"
                                        >
                                            {retryingDocId === reviewDoc.id ? (
                                                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                                            ) : (
                                                <RefreshCw className="mr-2 h-4 w-4" />
                                            )}
                                            {retryingDocId === reviewDoc.id ? "Retrying..." : "Retry OCR"}
                                        </Button>
                                    </div>
                                </div>
                                )}

                                {/* OCR Text Section */}
                                {reviewTab === "text" && (
                                <div className="flex min-h-0 flex-1 flex-col rounded-lg border bg-white p-4">
                                    <label className="mb-3 block text-sm font-semibold text-slate-700">
                                        AI Extract
                                    </label>
                                    <textarea
                                        value={editedOcrText}
                                        onChange={(e) => setEditedOcrText(e.target.value)}
                                        aria-label="AI Extract"
                                        className="min-h-[26rem] w-full flex-1 resize-y rounded-md border border-slate-200 bg-white px-3 py-2 font-mono text-sm leading-6 text-slate-900 outline-none transition-colors placeholder:text-slate-400 focus:border-blue-500 focus:ring-2 focus:ring-blue-100 lg:min-h-0 lg:resize-none"
                                        placeholder="AI extracted text..."
                                    />
                                </div>
                                )}

                                {reviewDoc.schema_id && (reviewTab === "fields" || reviewTab === "json") && (
                                    <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border bg-white p-4">
                                        {structuredDataTab !== "advanced" && (
                                            <label className="mb-2 block shrink-0 text-sm font-semibold text-slate-700">Structured Data</label>
                                        )}
                                        {structuredDataTab === "advanced" ? (
                                            <div className="flex min-h-0 flex-1 flex-col">
                                                <textarea
                                                    value={structuredJsonDraft}
                                                    onChange={(event) => {
                                                        setStructuredJsonDraft(event.target.value)
                                                        setStructuredJsonError(null)
                                                    }}
                                                    aria-label="Advanced Structured Data JSON"
                                                    spellCheck={false}
                                                    className="min-h-64 w-full flex-1 resize-y rounded-md border border-slate-200 bg-slate-950 px-3 py-2 font-mono text-xs leading-5 text-slate-100 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100 lg:min-h-0 lg:resize-none"
                                                />
                                                {structuredJsonError && <p className="mt-2 text-xs text-red-600">{structuredJsonError}</p>}
                                            </div>
                                        ) : reviewSchema && editedStructuredData && !Array.isArray(editedStructuredData) ? (
                                            <div className="min-h-0 flex-1 space-y-3 overflow-y-auto pr-1">
                                                {applyBar && (
                                                    <div role="status" className="flex flex-wrap items-center justify-between gap-2 rounded border border-emerald-200 bg-emerald-50 px-2 py-1.5 text-xs text-emerald-800">
                                                        <span>
                                                            อัปเดต {applyBar.updated} ฟิลด์เข้าตัวแก้ไขแล้ว · รอตรวจ {applyBar.review} รายการ
                                                            {applyBar.keptEdits > 0 && ` · คงค่าที่คุณแก้ไว้ ${applyBar.keptEdits} ฟิลด์`}
                                                        </span>
                                                        <span className="flex items-center gap-2">
                                                            {applyBar.review > 0 && (
                                                                <button type="button" onClick={() => setFieldFilter("needs_review")} className="rounded border border-emerald-300 px-2 py-0.5">เริ่มตรวจ</button>
                                                            )}
                                                            <button type="button" onClick={() => {
                                                                const snapshot = applySnapshot.current
                                                                if (!snapshot) return
                                                                setEditedStructuredData(snapshot.data)
                                                                setArrayDrafts(snapshot.drafts)
                                                                setStructuredJsonDraft(snapshot.json)
                                                                setLiveMapping(snapshot.mapping)
                                                                setConfirmedFields(snapshot.confirmed)
                                                                setConfirmedMissing(snapshot.missing)
                                                                setApplyBar(null)
                                                            }} className="rounded border px-2 py-0.5">เลิกทำ</button>
                                                        </span>
                                                    </div>
                                                )}
                                                <div className="flex shrink-0 items-center gap-1.5 overflow-x-auto px-0.5 pb-1 text-xs [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
                                                    {([
                                                        ["needs_review", `รอตรวจ ${statusCounts.needs_review}`, "border-amber-300 bg-amber-50 text-amber-800"],
                                                        ["source_matched", `ตรงเอกสาร ${statusCounts.source_matched}`, "border-blue-300 bg-blue-50 text-blue-800"],
                                                        ["missing", `ไม่พบ ${statusCounts.missing}`, "border-slate-300 bg-slate-50 text-slate-700"],
                                                        ["failed", `ผิดพลาด ${statusCounts.failed}`, "border-red-300 bg-red-50 text-red-700"],
                                                        ["all", `ทั้งหมด ${statusCounts.all}`, "border-slate-300 text-slate-600"],
                                                    ] as const).map(([key, text, className]) => (
                                                        <button key={key} type="button"
                                                            aria-pressed={fieldFilter === key}
                                                            onClick={() => setFieldFilter(key)}
                                                            className={`shrink-0 whitespace-nowrap rounded-full border px-2 py-0.5 transition-opacity ${className} ${fieldFilter === key ? "ring-1 ring-inset ring-blue-500 shadow-sm font-medium" : "opacity-80 hover:opacity-100"}`}>
                                                            {text}
                                                        </button>
                                                    ))}
                                                    {statusCounts.source_matched > 0 && (
                                                        <button type="button" onClick={confirmAllMatched} title="ทำเครื่องหมายยืนยันทุกฟิลด์ที่ตรงเอกสาร"
                                                            className="shrink-0 whitespace-nowrap rounded-full border border-emerald-300 bg-emerald-50 px-2 py-0.5 text-emerald-800">
                                                            ✓ ยืนยันทั้งหมดที่ตรงเอกสาร
                                                        </button>
                                                    )}
                                                </div>
                                                {visibleFields.length === 0 && (
                                                    <p className="rounded border border-emerald-200 bg-emerald-50 px-2 py-1.5 text-xs text-emerald-800">
                                                        {fieldFilter === "needs_review" ? "ไม่มีฟิลด์ที่รอตรวจ — ทุกอย่างเรียบร้อย ✅" : "ไม่มีฟิลด์ในหมวดนี้"}
                                                    </p>
                                                )}
                                                {visibleFields.map((field) => {
                                                    const value = editedStructuredData[field.name]
                                                    const fieldStatus = fieldStatusOf(field.name)
                                                    const fieldResolved = isFieldResolved(field.name)
                                                    const fieldEvidence = evidenceFor(field.name)
                                                    const expanded = expandedField === field.name
                                                    const stringValue = value === null || value === undefined ? "" : String(value)
                                                    const candidateValue = fieldEvidence?.lx_candidate?.value ?? fieldEvidence?.alternative?.value
                                                    const candidateLabel = fieldEvidence?.alternative ? "engine อื่นเสนอ" : "ค่าที่ AI เสนอ"
                                                    const statusText = fieldStatus === "source_matched" ? "ตรงเอกสาร" : fieldStatus === "missing" ? "ไม่พบ" : fieldStatus === "failed" ? "ผิดพลาด" : "รอตรวจ"
                                                    const statusGlyph = statusVisual(fieldStatus, fieldResolved)
                                                    const rowBorder = fieldResolved ? "border-emerald-200 bg-emerald-50/30"
                                                        : expanded ? "border-blue-300 bg-blue-50/30"
                                                        : fieldStatus === "needs_review" ? "border-amber-200"
                                                        : "border-slate-200"
                                                    return (
                                                        <div key={field.name} id={`field-row-${field.name}`} className={`shrink-0 overflow-hidden rounded border ${rowBorder}`}>
                                                            <button type="button" aria-expanded={expanded}
                                                                aria-label={`${field.name}, ${fieldResolved ? "ตรวจแล้ว" : statusText}, ${previewOf(value, fieldStatus === "missing")}`}
                                                                onClick={() => {
                                                                    setExpandedField(expanded ? null : field.name)
                                                                    // Expanding a row immediately shows where its value lives in the document.
                                                                    if (!expanded) locateFieldByName(field.name)
                                                                }}
                                                                className="flex w-full items-center gap-2 px-2 py-1.5 text-left">
                                                                <statusGlyph.Icon aria-hidden="true" className={`h-4 w-4 shrink-0 ${statusGlyph.cls}`} />
                                                                <span className="w-2/5 shrink-0 truncate text-sm font-medium text-slate-700" title={field.name}>
                                                                    {field.name}{field.required && <span className="text-red-500"> *</span>}
                                                                </span>
                                                                <span className="min-w-0 flex-1 truncate text-sm font-normal text-slate-500" title={previewOf(value, fieldStatus === "missing")}>
                                                                    {previewOf(value, fieldStatus === "missing")}
                                                                </span>
                                                                {fieldResolved && <Check className="h-3.5 w-3.5 shrink-0 text-emerald-600" />}
                                                                <ChevronDown className={`h-4 w-4 shrink-0 text-slate-400 transition-transform ${expanded ? "rotate-180" : ""}`} />
                                                            </button>
                                                            {expanded && (
                                                                <div className="space-y-2 border-t border-slate-100 bg-white px-2 py-2"
                                                                    onKeyDown={(event) => {
                                                                        const target = event.target as HTMLElement
                                                                        if (event.key === "Enter" && !target.closest("textarea") && !target.closest("button")) {
                                                                            event.preventDefault()
                                                                            resolveAndNext(field.name)
                                                                        }
                                                                    }}>
                                                                    {field.type === "boolean" ? (
                                                                        <select
                                                                            value={value === true ? "true" : value === false ? "false" : ""}
                                                                            onChange={(event) => updateStructuredField(field.name, event.target.value === "" ? null : event.target.value === "true")}
                                                                            aria-label={field.name}
                                                                            className="flex h-9 w-full rounded-md border border-slate-200 bg-white px-2 text-sm"
                                                                        >
                                                                            <option value="">Not provided</option>
                                                                            <option value="true">Yes</option>
                                                                            <option value="false">No</option>
                                                                        </select>
                                                                    ) : field.type === "array" ? (
                                                                        <textarea
                                                                            value={arrayDrafts[field.name] ?? JSON.stringify(value ?? [], null, 2)}
                                                                            onChange={(event) => setArrayDrafts((previous) => ({ ...previous, [field.name]: event.target.value }))}
                                                                            aria-label={field.name}
                                                                            className="min-h-24 w-full resize-y rounded-md border border-slate-200 bg-white px-2 py-1.5 font-mono text-xs leading-5"
                                                                        />
                                                                    ) : (
                                                                        <Input
                                                                            type={field.type === "date" ? "date" : field.type === "number" || field.type === "currency" ? "number" : "text"}
                                                                            value={stringValue}
                                                                            aria-label={field.name}
                                                                            onChange={(event) => {
                                                                                const nextValue = event.target.value
                                                                                updateStructuredField(
                                                                                    field.name,
                                                                                    (field.type === "number" || field.type === "currency") && nextValue !== ""
                                                                                        ? Number(nextValue)
                                                                                        : nextValue || null
                                                                                )
                                                                            }}
                                                                        />
                                                                    )}
                                                                    {((fieldStatus === "needs_review" || fieldEvidence?.upgraded_from_conflict)) && candidateValue !== undefined && candidateValue !== null && previewOf(candidateValue) !== previewOf(value) && (
                                                                        <span className="flex flex-wrap items-center gap-2 text-xs text-amber-800">
                                                                            {fieldEvidence?.upgraded_from_conflict
                                                                                ? "ค่าเดิมที่ถูกแทนที่ (ค่าปัจจุบันมีตำแหน่งยืนยันในเอกสาร):"
                                                                                : fieldEvidence?.alternative?.grounded
                                                                                    ? "engine อื่นเสนอ (มีตำแหน่งในเอกสาร):"
                                                                                    : `${candidateLabel}:`}
                                                                            <code className="max-w-full truncate rounded bg-amber-50 px-1" title={previewOf(candidateValue)}>{previewOf(candidateValue)}</code>
                                                                            <button type="button" onClick={() => { updateStructuredField(field.name, candidateValue); confirmField(field.name) }}
                                                                                className="rounded border border-amber-300 bg-amber-50 px-1.5 py-0.5">ใช้ค่านี้</button>
                                                                        </span>
                                                                    )}
                                                                    <div className="flex flex-wrap items-center gap-1.5 text-xs">
                                                                        <span className="inline-flex items-center gap-1 rounded bg-slate-100 px-1.5 py-0.5 font-medium text-slate-700">
                                                                            <statusGlyph.Icon aria-hidden="true" className={`h-3 w-3 ${statusGlyph.cls}`} />
                                                                            {fieldResolved ? "ตรวจแล้ว" : statusText}
                                                                        </span>
                                                                        {!fieldResolved && fieldStatus !== "missing" && fieldStatus !== "failed" && (
                                                                            <button type="button" onClick={() => confirmField(field.name)}
                                                                                className="rounded border border-emerald-300 bg-emerald-50 px-1.5 py-0.5 text-emerald-800"
                                                                                title={fieldStatus === "source_matched" ? "ยืนยันว่าค่านี้ตรงกับเอกสารแล้ว" : "ตรวจแล้วค่านี้ถูกต้อง — ทำเครื่องหมายว่ายืนยัน"}
                                                                                onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); resolveAndNext(field.name) } }}>
                                                                                {fieldStatus === "source_matched" ? "ยืนยัน" : "ยืนยันถูกต้อง"}
                                                                            </button>
                                                                        )}
                                                                        {fieldStatus === "missing" && !confirmedMissing.has(field.name) && (
                                                                            <button type="button" onClick={() => confirmFieldMissing(field.name)}
                                                                                className="rounded border px-1.5 py-0.5 text-slate-600"
                                                                                title="ยืนยันว่าเอกสารนี้ไม่มีข้อมูลฟิลด์นี้">ยืนยันว่าเอกสารไม่มี</button>
                                                                        )}
                                                                        {fieldStatus === "failed" && (
                                                                            <button type="button" disabled={fieldRetryBusy === field.name} onClick={() => retrySingleField(field.name)}
                                                                                className="inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-red-700 disabled:opacity-50"
                                                                                title="ลองสกัดฟิลด์นี้ใหม่">
                                                                                <RefreshCw className={`h-3 w-3 ${fieldRetryBusy === field.name ? "animate-spin" : ""}`} /> Retry ฟิลด์นี้
                                                                            </button>
                                                                        )}
                                                                        {reviewIsPdf && ((typeof value === "string" || typeof value === "number") || fieldEvidence?.quote || fieldEvidence?.raw_text) && (
                                                                            <button type="button" onClick={() => locateField(field.name, value, field.type, fieldEvidence)}
                                                                                className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-blue-700 hover:bg-blue-50"
                                                                                title={`Show where ${field.name} is in the document`}>
                                                                                <LocateFixed className="h-3.5 w-3.5" /> Show in document
                                                                            </button>
                                                                        )}
                                                                        {fieldEvidence?.lx_candidate && (
                                                                            <span title="ค่านี้มาจากโมเดลแต่หาตำแหน่งในเอกสารต้นฉบับไม่พบ ควรตรวจสอบเป็นพิเศษ" className="rounded bg-amber-100 px-1.5 py-0.5 text-amber-800">ไม่พบตำแหน่งในเอกสาร</span>
                                                                        )}
                                                                        {dirtyFields.has(field.name) && (
                                                                            <span className="rounded bg-slate-100 px-1.5 py-0.5 text-slate-600">คุณแก้ไว้แล้ว</span>
                                                                        )}
                                                                    </div>
                                                                    {(fieldEvidence?.quote || fieldEvidence?.raw_text || fieldEvidence?.reason || fieldEvidence?.page) && (
                                                                        <div className="rounded bg-slate-50 px-2 py-1.5 text-xs text-slate-500">
                                                                            {(fieldEvidence?.quote || fieldEvidence?.raw_text) && (
                                                                                <p className="whitespace-pre-wrap break-words border-l-2 border-slate-300 pl-2">{fieldEvidence?.quote || fieldEvidence?.raw_text}</p>
                                                                            )}
                                                                            {fieldEvidence?.reason && <p className="mt-1">{fieldEvidence.reason}</p>}
                                                                            {fieldEvidence?.page ? <p className="mt-1">หน้า {fieldEvidence.page}{fieldStatus === "source_matched" ? " · value verbatim in source, field association not independently verified" : ""}</p> : null}
                                                                        </div>
                                                                    )}
                                                                </div>
                                                            )}
                                                        </div>
                                                    )
                                                })}
                                            </div>
                                        ) : (
                                            <p className="text-sm text-slate-500">No structured fields were returned for this document.</p>
                                        )}
                                    </div>
                                )}

                            </div>
                        </div>

                        {/* Footer - Action Buttons */}
                        <div className="flex flex-wrap items-center justify-between gap-3 px-6 py-3 border-t bg-slate-50">
                            {/* Left: Reject + mapping tools */}
                            <div className="flex flex-wrap items-center gap-2">
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
                                {reviewDoc.schema_id && (reviewTab === "fields" || reviewTab === "json") && (
                                    <span className="flex items-center gap-1.5 text-xs text-slate-500">
                                        <select aria-label="Mapping engine" value={mappingEngine} disabled={mappingBusy} onChange={(e) => setMappingEngine(e.target.value)}
                                            className="h-8 rounded border border-slate-200 bg-white px-1.5 text-xs">
                                            <option value="auto">Auto</option><option value="softnix">Softnix Structured</option>
                                            <option value="jev">TypeSafe Jev</option><option value="lx">LangExtract (grounded)</option>
                                            <option value="llm">Configured LLM provider</option><option value="fixed">Fixed position only</option>
                                        </select>
                                        <button type="button" onClick={retryAll} disabled={mappingBusy}
                                            className="inline-flex h-8 items-center gap-1 rounded border border-slate-200 bg-white px-2 text-xs disabled:opacity-50">
                                            <RefreshCw className={`h-3.5 w-3.5 ${mappingBusy ? "animate-spin" : ""}`} />{mappingBusy ? "Mapping..." : "Retry Mapping"}
                                        </button>
                                    </span>
                                )}
                            </div>
                            {/* Right: Cancel + Save */}
                            <div className="flex items-center gap-3">
                                {mappingError && <span className="max-w-xs truncate text-xs text-red-600" title={mappingError}>{mappingError}</span>}
                                <Button variant="outline" onClick={closeReview}>
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
                width="min(52rem, calc(100vw - 2rem))"
                bodyClassName="p-0"
            >
                <div className="flex max-h-[calc(100vh-8rem)] flex-col">
                    <div className="border-b border-slate-100 px-6 py-5">
                        <p className="text-[0.9375rem] leading-6 text-slate-600">
                            Send reviewed documents from this job to an active integration endpoint.
                        </p>
                        <div className="mt-3 flex flex-wrap gap-2 text-[0.8125rem]">
                            <span className="rounded-full bg-slate-100 px-2.5 py-1 font-semibold text-slate-600">
                                Docs: {documents.length}
                            </span>
                            <span className="rounded-full bg-purple-50 px-2.5 py-1 font-semibold text-purple-700">
                                Reviewed: {docCounts.reviewed}
                            </span>
                        </div>
                    </div>

                    <div className="min-h-[13rem] flex-1 overflow-y-auto px-6 py-5">
                        {integrations.length === 0 ? (
                            <div className="flex min-h-[12rem] flex-col items-center justify-center rounded-xl border border-dashed border-slate-200 bg-slate-50 text-center">
                                <Plug className="h-8 w-8 text-slate-300" />
                                <p className="mt-3 text-sm font-semibold text-slate-700">No active integrations</p>
                                <p className="mt-1 max-w-sm text-xs leading-5 text-slate-500">
                                    Add or activate an integration before sending reviewed documents.
                                </p>
                            </div>
                        ) : (
                            <div className="grid grid-cols-1 gap-3">
                                {integrations.map((integration) => {
                                    const meta = integrationTypeMeta[integration.type]
                                    const Icon = meta.icon
                                    const selected = selectedIntegration === integration.id
                                    return (
                                        <label
                                            key={integration.id}
                                            className={`group grid cursor-pointer grid-cols-[auto_auto_minmax(0,1fr)] items-start gap-4 rounded-2xl border p-4 transition-all ${
                                                selected
                                                    ? "border-softnix-blue bg-[#F0F8FD] shadow-sm ring-1 ring-softnix-blue/20"
                                                    : "border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50"
                                            }`}
                                        >
                                            <input
                                                type="radio"
                                                className="mt-3 h-4 w-4 accent-[#2786C2]"
                                                checked={selected}
                                                onChange={() => setSelectedIntegration(integration.id)}
                                            />
                                            <span className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl ${meta.className}`}>
                                                <Icon className="h-5 w-5" />
                                            </span>
                                            <span className="min-w-0 flex-1">
                                                <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                                                    <span className="text-[1rem] font-semibold leading-6 text-slate-950">{integration.name}</span>
                                                    <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-bold uppercase tracking-wide text-slate-600">
                                                        {integration.type}
                                                    </span>
                                                </span>
                                                <span className="mt-1.5 block max-w-[42rem] text-[0.875rem] leading-5 text-slate-600">
                                                    {integration.description || meta.label}
                                                </span>
                                            </span>
                                        </label>
                                    )
                                })}
                            </div>
                        )}
                    </div>

                    {integrationMessage && (
                        <div className={`mx-6 mb-4 rounded-xl border px-4 py-3 text-sm ${
                            integrationMessage === "Sent successfully" || integrationMessage === "LLM processing completed"
                                ? "border-emerald-200 bg-emerald-50 text-emerald-800"
                                : "border-amber-200 bg-amber-50 text-amber-800"
                        }`}>
                            {integrationMessage}
                        </div>
                    )}

                    <div className="flex flex-col gap-3 border-t border-slate-100 bg-slate-50 px-6 py-5 sm:flex-row sm:items-center sm:justify-between">
                        <div className="min-w-0 text-sm">
                            <p className="font-semibold text-slate-800">
                                {selectedIntegrationDetails ? selectedIntegrationDetails.name : "Choose an integration"}
                            </p>
                            <p className="mt-0.5 text-xs text-slate-500">
                                {selectedIntegrationDetails
                                    ? `${integrationTypeMeta[selectedIntegrationDetails.type].label} will receive reviewed document data.`
                                    : "Select one active destination before sending."}
                            </p>
                        </div>
                        <div className="flex justify-end gap-2">
                            <Button
                                variant="outline"
                                onClick={() => {
                                    setShowIntegrationModal(false)
                                    setIntegrationMessage(null)
                                }}
                                className="min-w-[5.5rem]"
                            >
                                {integrationMessage === "Sent successfully" ? "Close" : "Cancel"}
                            </Button>
                            <Button
                                onClick={handleSendToIntegration}
                                disabled={!selectedIntegration || sendingIntegration}
                                className="min-w-[6.5rem]"
                            >
                                {sendingIntegration ? (
                                    <>
                                        <Loader2 className="h-4 w-4 animate-spin" />
                                        Sending
                                    </>
                                ) : (
                                    <>
                                        <Send className="h-4 w-4" />
                                        {integrationMessage === "Sent successfully" ? "Retry" : "Send"}
                                    </>
                                )}
                            </Button>
                        </div>
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
