"use client"

import { useEffect, useRef, useState, type ChangeEvent } from "react"
import {
    Loader2, AlertCircle, FileText, Sparkles, ArrowRight, Plus, Trash2, ChevronDown, ChevronRight,
    CheckCircle2, AlertTriangle, XCircle, MinusCircle, Play, RotateCcw, Undo2, X,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { useSchemaWizard } from "@/contexts/SchemaWizardContext"
import {
    ArrayColumnType, FieldEvidenceStatus, SampleEvidence, SchemaField, StudioSample, StudioSession, TableColumn,
} from "@/types/schema"
import { getApiBaseUrl } from "@/lib/api"
import { editableText, fromSuggestedField, parseTypedValue, splitList, toSchemaPayloadField, type SuggestedFieldResponse } from "@/lib/schema-studio"
import { isValidPattern, validateFields } from "@/lib/schema-validation"

// Generate a simple unique ID
const genId = () => `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`

const MAX_FILES = 5
const POLL_MS = 2000
// A run still "queued" after this long means no worker picked it up.
const QUEUED_TIMEOUT_MS = 120_000
const VALID_TYPES = ["application/pdf", "image/jpeg", "image/jpg", "image/png"]

type Summary = { total: number; verified: number; review: number; not_found: number }
type RunField = { value: unknown; status?: string; provider?: string; reason?: string | null }
type RunSample = { index: number; filename: string; report?: { fields: Record<string, RunField> }; error?: string }
type RunState = { status: "queued" | "running" | "completed" | "failed"; total: number | null; done: number; samples: RunSample[]; error?: string | null }
type Focus = { sample: number; line?: number; quote?: string }
type SuggestionResult = { suggested_fields: SuggestedFieldResponse[]; summary: Summary }
type SuggestionState = {
    status: "queued" | "running" | "completed" | "failed"; error?: string | null; result?: SuggestionResult | null
    // Files are read in the background first (OCR for scans), then AI suggests fields.
    stage?: "reading" | "suggesting"; done?: number; total?: number
    session_id?: string | null; samples?: StudioSample[]
}

const STATUS: Record<FieldEvidenceStatus, { label: string; cls: string; Icon: typeof CheckCircle2 }> = {
    verified: { label: "Verified", cls: "border-emerald-200 bg-emerald-50 text-emerald-700", Icon: CheckCircle2 },
    review: { label: "Check this", cls: "border-amber-200 bg-amber-50 text-amber-700", Icon: AlertTriangle },
    not_found: { label: "Not in document", cls: "border-red-200 bg-red-50 text-red-700", Icon: XCircle },
}

// What the engine could prove about the value; separate from the user's own confirmation.
const RESULT: Record<string, { label: string; cls: string; dot: string }> = {
    source_matched: { label: "Found in document", cls: "text-emerald-700", dot: "bg-emerald-500" },
    needs_review: { label: "Check against document", cls: "text-amber-700", dot: "bg-amber-500" },
    missing: { label: "No value found", cls: "text-slate-500", dot: "bg-slate-300" },
    failed: { label: "Could not extract", cls: "text-red-700", dot: "bg-red-500" },
}

const ENGINES: Array<{ value: string; label: string }> = [
    { value: "", label: "System default" },
    { value: "auto", label: "Auto" },
    { value: "softnix", label: "Softnix" },
    { value: "jev", label: "Jev (TypeSafe)" },
    { value: "llm", label: "LLM" },
]

const COLUMN_TYPES: ArrayColumnType[] = ["text", "number", "date", "currency"]

// FastAPI returns validation problems as a list; show them as one readable line.
function errorDetail(detail: unknown, fallback: string): string {
    if (typeof detail === "string") return detail
    if (Array.isArray(detail)) {
        const messages = detail
            .map((item) => (item && typeof item === "object" && "msg" in item ? String((item as { msg: unknown }).msg) : ""))
            .map((message) => message.replace(/^Value error, /, ""))
            .filter(Boolean)
        if (messages.length) return messages.join(" ")
    }
    return fallback
}

function formatValue(value: unknown): string {
    if (value === null || value === undefined || value === "") return "—"
    if (Array.isArray(value)) return `${value.length} row${value.length === 1 ? "" : "s"}`
    if (typeof value === "object") return JSON.stringify(value)
    return String(value)
}

const sameValue = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)


function Highlight({ text, quote }: { text: string; quote?: string }) {
    const index = quote ? text.indexOf(quote) : -1
    if (!quote || index < 0) return <>{text}</>
    return (
        <>
            {text.slice(0, index)}
            <mark className="rounded bg-yellow-200 px-0.5 text-slate-900">{quote}</mark>
            {text.slice(index + quote.length)}
        </>
    )
}

// Shows the raw text while typing (so spaces and commas stay put) but reports
// the parsed list on every keystroke, so an immediate Test/Next sees it.
function ListInput({ value, onCommit, className, placeholder }: {
    value: string[]
    onCommit: (items: string[]) => void
    className?: string
    placeholder?: string
}) {
    const joined = value.join(", ")
    const [text, setText] = useState(joined)
    const [editing, setEditing] = useState(false)
    return (
        <input
            type="text"
            className={className}
            placeholder={placeholder}
            value={editing ? text : joined}
            onFocus={() => { setText(joined); setEditing(true) }}
            onChange={(e) => { setText(e.target.value); onCommit(splitList(e.target.value)) }}
            onBlur={() => setEditing(false)}
        />
    )
}

function CheckIcon({ ok }: { ok: boolean | null }) {
    if (ok === true) return <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-600" />
    if (ok === false) return <XCircle className="h-3.5 w-3.5 shrink-0 text-red-500" />
    return <MinusCircle className="h-3.5 w-3.5 shrink-0 text-slate-400" />
}

type RunStatus = { status: string; error?: string | null }

// Polls a background Schema Studio run until it completes, fails, or never
// starts. Handlers are read through a ref so callers can pass inline closures.
function usePolledRun<T extends RunStatus>(runId: string | null, onState: (state: T) => void, onError: (message: string) => void) {
    const handlers = useRef({ onState, onError })
    handlers.current = { onState, onError }
    useEffect(() => {
        if (!runId) return
        let cancelled = false
        const token = localStorage.getItem("token")
        const startedAt = Date.now()
        // `timer` is assigned below; stop() only runs after an await, so it is set by then.
        const stop = () => {
            cancelled = true
            clearInterval(timer)
        }
        const poll = async () => {
            try {
                const res = await fetch(`${getApiBaseUrl()}/schemas/sample-runs/${runId}`, {
                    headers: token ? { Authorization: `Bearer ${token}` } : {},
                })
                const data = await res.json().catch(() => ({}))
                if (cancelled) return
                if (!res.ok) throw new Error(errorDetail(data.detail, "Could not read progress"))
                if (data.status === "queued" && Date.now() - startedAt > QUEUED_TIMEOUT_MS) {
                    stop()
                    handlers.current.onError("The job did not start. The document worker may be busy or offline. Try again later.")
                    return
                }
                handlers.current.onState(data as T)
                if (data.status === "completed" || data.status === "failed") stop()
            } catch (err: unknown) {
                if (cancelled) return
                stop()
                handlers.current.onError(err instanceof Error ? err.message : "Could not read progress")
            }
        }
        poll()
        const timer = setInterval(poll, POLL_MS)
        return stop
    }, [runId])
}

function DocumentTextPanel({ samples, focus, onFocus }: { samples: StudioSample[]; focus: Focus; onFocus: (focus: Focus) => void }) {
    const container = useRef<HTMLDivElement>(null)
    const sample = samples[focus.sample]
    const lines = sample ? sample.text.split("\n") : []

    useEffect(() => {
        const box = container.current
        const target = box?.querySelector<HTMLElement>(`[data-line="${focus.line}"]`)
        if (box && target) box.scrollTop = Math.max(0, target.offsetTop - box.clientHeight / 3)
    }, [focus])

    if (!sample) return null
    return (
        <div className="space-y-1.5">
            <div className="flex flex-wrap items-center gap-1" role="tablist" aria-label="Sample documents">
                {samples.map((item, index) => (
                    <button
                        key={index}
                        type="button"
                        role="tab"
                        aria-selected={index === focus.sample}
                        onClick={() => onFocus({ sample: index })}
                        className={`rounded px-2 py-0.5 text-xs ${index === focus.sample ? "bg-blue-600 text-white" : "bg-white text-slate-600 border border-slate-200"}`}
                    >
                        S{index + 1} · {item.filename}
                    </button>
                ))}
            </div>
            <div ref={container} className="relative max-h-64 overflow-auto rounded border border-slate-200 bg-white font-mono text-xs leading-5">
                {lines.map((line, index) => {
                    const lineNo = index + 1
                    const active = lineNo === focus.line
                    return (
                        <div key={index} data-line={lineNo} className={`flex gap-2 px-2 ${active ? "bg-yellow-50" : ""}`}>
                            <span className="w-8 shrink-0 select-none text-right text-slate-400 tabular-nums">{lineNo}</span>
                            <span className="whitespace-pre-wrap break-words text-slate-700">
                                {active ? <Highlight text={line} quote={focus.quote} /> : line || " "}
                            </span>
                        </div>
                    )
                })}
            </div>
            {sample.truncated && <p className="text-xs text-amber-700">Only the first part of this sample was sent to AI.</p>}
        </div>
    )
}

export function AIFieldsStep() {
    const {
        startingPoint, schemaData, fields, setFields, addField, updateField, removeField, nextStep, setManualEntry,
        studio, setStudio, updateStudio,
    } = useSchemaWizard()
    const isAIMode = startingPoint === "ai"

    const [pendingFiles, setPendingFiles] = useState<File[]>([])
    const [isAnalyzing, setIsAnalyzing] = useState(false)
    const [aiError, setAiError] = useState<string | null>(null)
    const [analyzed, setAnalyzed] = useState(fields.length > 0)
    const [summary, setSummary] = useState<Summary | null>(null)
    const [notFound, setNotFound] = useState<SchemaField[]>([])
    const [showNotFound, setShowNotFound] = useState(false)
    const [expanded, setExpanded] = useState<Record<string, boolean>>({})
    const [focusByField, setFocusByField] = useState<Record<string, Focus>>({})
    const [engine, setEngine] = useState("")
    const [runId, setRunId] = useState<string | null>(null)
    const [run, setRun] = useState<RunState | null>(null)
    const [runSignature, setRunSignature] = useState<string | null>(null)
    const [runError, setRunError] = useState<string | null>(null)
    const [suggestRunId, setSuggestRunId] = useState<string | null>(null)
    const [analyzeStage, setAnalyzeStage] = useState<"reading" | "suggesting">("reading")
    const [readProgress, setReadProgress] = useState<{ done: number; total: number } | null>(null)
    const pendingStudio = useRef<StudioSession | null>(null)
    const [editing, setEditing] = useState<{ key: string; text: string } | null>(null)

    const samples = studio?.samples || []
    const expected = studio?.expected || {}

    usePolledRun<RunState>(runId, (state) => {
        setRun(state)
        if (state.status === "completed" || state.status === "failed") {
            if (state.status === "failed") setRunError(state.error || "The test run failed. Try again.")
            setRunId(null)
        }
    }, (message) => {
        setRunError(message)
        setRunId(null)
    })

    usePolledRun<SuggestionState>(suggestRunId, (state) => {
        if (state.stage) setAnalyzeStage(state.stage)
        if (typeof state.done === "number" && typeof state.total === "number") setReadProgress({ done: state.done, total: state.total })
        if (state.session_id && pendingStudio.current && !pendingStudio.current.sessionId) {
            pendingStudio.current = {
                ...pendingStudio.current,
                sessionId: state.session_id,
                samples: (state.samples || []).map((s) => ({
                    filename: s.filename, text: s.text, truncated: s.truncated, garbled_pages: s.garbled_pages || [],
                })),
            }
        }
        if (state.status === "completed" && state.result) {
            applySuggestion(state.result)
            setSuggestRunId(null)
            setIsAnalyzing(false)
        } else if (state.status === "failed") {
            setAiError(state.error || "AI suggestion failed. Try again.")
            setSuggestRunId(null)
            setIsAnalyzing(false)
        }
    }, (message) => {
        setAiError(message)
        setSuggestRunId(null)
        setIsAnalyzing(false)
    })

    if (!isAIMode) {
        return (
            <div className="text-center py-12 space-y-4">
                <p className="text-slate-600">Continue to define fields manually.</p>
                <Button onClick={nextStep} className="gap-2">
                    Continue <ArrowRight className="h-4 w-4" />
                </Button>
            </div>
        )
    }

    const payloadFields = fields.map(toSchemaPayloadField)
    const signature = JSON.stringify(payloadFields)
    const fieldErrors = validateFields(fields).filter((error) => error.severity === "error")
    const running = runId !== null
    const runStale = run?.status === "completed" && runSignature !== signature
    const confirmedCount = Object.values(expected).reduce(
        (sum, values) => sum + fields.filter((f) => values[f.id!] !== undefined).length, 0)

    const handleFileSelect = (e: ChangeEvent<HTMLInputElement>) => {
        const chosen = Array.from(e.target.files || [])
        e.target.value = ""
        if (!chosen.length) return
        if (chosen.some((f) => !VALID_TYPES.includes(f.type))) {
            setAiError("Please upload PDF, JPG, or PNG files")
            return
        }
        const next = [...pendingFiles, ...chosen].slice(0, MAX_FILES)
        if (pendingFiles.length + chosen.length > MAX_FILES) setAiError(`Up to ${MAX_FILES} sample files. Extra files were left out.`)
        else setAiError(null)
        setPendingFiles(next)
    }

    const handleAnalyze = async () => {
        if (!pendingFiles.length) return
        setIsAnalyzing(true)
        setAnalyzeStage("reading")
        setReadProgress(null)
        setAiError(null)
        try {
            const token = localStorage.getItem("token")
            const formData = new FormData()
            pendingFiles.forEach((f) => formData.append("files", f))
            const params = new URLSearchParams()
            if (schemaData.document_type) params.set("document_type", schemaData.document_type)

            const res = await fetch(`${getApiBaseUrl()}/schemas/suggest-from-file?${params.toString()}`, {
                method: "POST",
                headers: token ? { Authorization: `Bearer ${token}` } : {},
                body: formData,
            })
            if (!res.ok) {
                const err = await res.json().catch(() => ({}))
                throw new Error(errorDetail(err.detail, "AI suggestion failed"))
            }
            const data = await res.json()
            // Kept aside until the suggestion finishes, so a failed run leaves no half-set state.
            // The session and sample texts arrive with the run's progress once the files are read.
            pendingStudio.current = {
                sessionId: null,
                files: pendingFiles,
                samples: [],
                expected: {},
                keepSamples: false,
                retentionDays: data.sample_retention_days || 180,
            }
            setReadProgress({ done: 0, total: data.total || pendingFiles.length })
            setSuggestRunId(data.run_id)
        } catch (err: unknown) {
            setAiError(err instanceof Error ? err.message : "Analysis failed")
            setIsAnalyzing(false)
        }
    }

    function applySuggestion(result: SuggestionResult) {
        const suggested: SchemaField[] = (result.suggested_fields || []).map((f) => fromSuggestedField(f, genId()))
        setFields(suggested.filter((f) => f.studio?.status !== "not_found"))
        setNotFound(suggested.filter((f) => f.studio?.status === "not_found"))
        setSummary(result.summary || null)
        setStudio(pendingStudio.current)
        pendingStudio.current = null
        setExpanded({})
        setFocusByField({})
        setRun(null)
        setRunError(null)
        setAnalyzed(true)
    }

    const handleStartOver = () => {
        setFields([])
        setNotFound([])
        setSummary(null)
        setStudio(null)
        setRun(null)
        setRunId(null)
        setRunError(null)
        setPendingFiles([])
        setAnalyzed(false)
    }

    const handleAddField = () => {
        addField({ id: genId(), name: "", type: "text", description: "", required: false })
    }

    const handleAddBack = (field: SchemaField) => {
        addField(field)
        setNotFound((current) => current.filter((item) => item.id !== field.id))
    }

    const updateRules = (field: SchemaField, patch: NonNullable<SchemaField["validation_rules"]>) => {
        updateField(field.id!, { validation_rules: { ...(field.validation_rules || {}), ...patch } })
    }

    const focusFor = (field: SchemaField): Focus => {
        const chosen = focusByField[field.id!]
        if (chosen) return chosen
        const primary = field.studio?.evidence
        return primary ? { sample: primary.sample ?? 0, line: primary.line_no, quote: primary.quote } : { sample: 0 }
    }

    // Confirmations are keyed by field id so renaming a field keeps them.
    const setConfirmed = (sampleIndex: number, fieldId: string, value: unknown, confirmed: boolean) => {
        if (!studio) return
        const current = { ...(studio.expected[sampleIndex] || {}) }
        if (confirmed) current[fieldId] = value
        else delete current[fieldId]
        updateStudio({ expected: { ...studio.expected, [sampleIndex]: current } })
    }

    const clearSample = (sampleIndex: number) => {
        if (!studio) return
        updateStudio({ expected: { ...studio.expected, [sampleIndex]: {} } })
    }

    const confirmAllFound = (sample: RunSample) => {
        if (!studio || !sample.report) return
        const current = { ...(studio.expected[sample.index] || {}) }
        for (const field of fields) {
            const cell = sample.report.fields[field.name]
            if (cell && cell.value !== null && cell.value !== undefined && cell.value !== "") current[field.id!] = cell.value
        }
        updateStudio({ expected: { ...studio.expected, [sample.index]: current } })
    }

    const handleRun = async () => {
        if (!studio?.sessionId || fieldErrors.length) return
        setRunError(null)
        setRun(null)
        try {
            const token = localStorage.getItem("token")
            const res = await fetch(`${getApiBaseUrl()}/schemas/sample-dry-run`, {
                method: "POST",
                headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
                body: JSON.stringify({ session_id: studio.sessionId, fields: payloadFields, engine: engine || null }),
            })
            const data = await res.json().catch(() => ({}))
            if (!res.ok) {
                if (res.status === 404) updateStudio({ sessionId: null })
                throw new Error(errorDetail(data.detail, "Test failed. Check the fields and try again."))
            }
            setRunSignature(signature)
            setRun({ status: "queued", total: data.total, done: 0, samples: [] })
            setRunId(data.run_id)
        } catch (err: unknown) {
            setRunError(err instanceof Error ? err.message : "Test failed")
        }
    }

    const canProceed = fields.length > 0 && fields.every((f: SchemaField) => f.name.trim().length > 0)

    return (
        <div className="space-y-5 max-w-5xl mx-auto py-4">
            <div>
                <h2 className="text-xl font-semibold text-slate-900">Upload sample documents</h2>
                <p className="text-sm text-slate-500 mt-1">
                    Add 1–{MAX_FILES} documents of the same kind, ideally from different senders or months. AI suggests fields, then each suggestion is checked against every file.
                </p>
            </div>

            {!analyzed && (
                <div className="bg-white border border-dashed border-blue-300 rounded-lg p-6 transition-colors hover:border-blue-500">
                    <div className="flex flex-col items-center gap-4">
                        <FileText className="h-9 w-9 text-blue-300" />
                        <div className="text-center">
                            <label className="cursor-pointer">
                                <span className="text-blue-700 font-medium hover:text-blue-800">
                                    {pendingFiles.length ? "Add more files" : "Choose files"}
                                </span>
                                <input type="file" multiple className="hidden" accept=".pdf,.jpg,.jpeg,.png" onChange={handleFileSelect}
                                    disabled={isAnalyzing || pendingFiles.length >= MAX_FILES} />
                            </label>
                            <p className="text-xs text-slate-500 mt-1">PDF, JPG or PNG · up to {MAX_FILES} files</p>
                        </div>

                        {pendingFiles.length > 0 && (
                            <ul className="w-full space-y-1.5">
                                {pendingFiles.map((f, index) => (
                                    <li key={`${f.name}-${index}`} className="bg-slate-50 border border-slate-200 rounded-lg px-3 py-2 flex items-center justify-between gap-2">
                                        <span className="flex min-w-0 items-center gap-2 text-sm text-slate-700">
                                            <span className="text-xs font-medium text-slate-400">S{index + 1}</span>
                                            <span className="truncate">{f.name}</span>
                                        </span>
                                        {!isAnalyzing && (
                                            <button
                                                type="button"
                                                title={`Remove ${f.name}`}
                                                onClick={() => setPendingFiles(pendingFiles.filter((_, i) => i !== index))}
                                                className="text-slate-400 hover:text-red-500"
                                            >
                                                <X className="h-4 w-4" />
                                            </button>
                                        )}
                                    </li>
                                ))}
                            </ul>
                        )}

                        <Button
                            onClick={handleAnalyze}
                            disabled={!pendingFiles.length || isAnalyzing}
                            className="w-full mt-2 bg-blue-600 hover:bg-blue-700 text-white shadow-sm"
                            size="lg"
                        >
                            {isAnalyzing ? (
                                <><Loader2 className="h-4 w-4 mr-2 animate-spin" />
                                    {analyzeStage === "reading"
                                        ? (readProgress && readProgress.total > 1
                                            ? `Reading documents (${readProgress.done} of ${readProgress.total} done). Scanned pages can take a few minutes...`
                                            : "Reading the document. Scanned pages can take a few minutes...")
                                        : "AI is suggesting and checking fields. This usually takes 1–3 minutes..."}
                                </>
                            ) : (
                                <><Sparkles className="h-4 w-4 mr-2" /> Suggest fields</>
                            )}
                        </Button>
                    </div>
                </div>
            )}

            {aiError && (
                <div className="p-3 bg-red-50 text-red-700 rounded-lg border border-red-200 text-sm flex items-start gap-2">
                    <AlertCircle className="h-4 w-4 mt-0.5" />
                    <div>{aiError}</div>
                </div>
            )}

            {analyzed && (
                <div className="space-y-4">
                    <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white p-3">
                        <div className="text-sm text-slate-700">
                            {summary ? (
                                <span>
                                    <b>{summary.total}</b> fields suggested ·{" "}
                                    <span className="text-emerald-700">{summary.verified} verified</span> ·{" "}
                                    <span className="text-amber-700">{summary.review} to check</span> ·{" "}
                                    <span className="text-red-700">{summary.not_found} not in document</span>
                                </span>
                            ) : (
                                <span>{fields.length} fields</span>
                            )}
                            {samples.length > 0 && <span className="text-slate-400"> · {samples.length} sample{samples.length === 1 ? "" : "s"}</span>}
                        </div>
                        <Button type="button" variant="ghost" size="sm" onClick={handleStartOver} className="gap-1 text-slate-600">
                            <RotateCcw className="h-3.5 w-3.5" /> Use other files
                        </Button>
                    </div>

                    {samples.some((sample) => sample.garbled_pages?.length) && (
                        <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
                            <p className="font-medium">Thai text in some samples looks garbled</p>
                            <p className="mt-0.5 text-xs">
                                {samples
                                    .map((sample, index) => (sample.garbled_pages?.length
                                        ? `Sample ${index + 1} (page${sample.garbled_pages.length > 1 ? "s" : ""} ${sample.garbled_pages.join(", ")})`
                                        : null))
                                    .filter(Boolean)
                                    .join(" · ")}
                                {" "}uses a PDF font that stores Thai characters incorrectly, so words like “ภาษีมูลค่าเพิ่ม” can appear misspelled.
                                Suggested values and labels may contain wrong characters. Check them carefully, or use a scanned or re-exported copy of the file.
                            </p>
                        </div>
                    )}

                    <div className="flex items-center justify-between">
                        <h3 className="text-lg font-semibold text-slate-900">Suggested fields</h3>
                        <Button type="button" variant="outline" onClick={handleAddField}>
                            <Plus className="h-4 w-4 mr-1" /> Add field
                        </Button>
                    </div>

                    {fields.length > 0 && (
                        <div className="grid grid-cols-12 gap-2 px-3 text-xs font-semibold text-slate-500 uppercase tracking-wide">
                            <div className="col-span-3">Field name</div>
                            <div className="col-span-2">Type</div>
                            <div className="col-span-5">Description</div>
                            <div className="col-span-2">Required</div>
                        </div>
                    )}

                    <div className="space-y-2">
                        {fields.map((field: SchemaField) => {
                            const insight = field.studio
                            const status = insight ? STATUS[insight.status] : null
                            const isOpen = Boolean(expanded[field.id!])
                            const presence = insight?.presence
                            const pattern = field.validation_rules?.pattern
                            const patternInvalid = Boolean(pattern && !isValidPattern(pattern))
                            return (
                                <div key={field.id} className="p-3 border border-slate-200 rounded-lg bg-white space-y-2">
                                    <div className="flex flex-wrap items-center gap-2 text-xs">
                                        {status ? (
                                            <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 font-medium ${status.cls}`}>
                                                <status.Icon className="h-3.5 w-3.5" /> {status.label}
                                            </span>
                                        ) : (
                                            <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-slate-600">Added by you</span>
                                        )}
                                        {presence && presence.total > 1 && (
                                            <span className={`tabular-nums ${presence.found === presence.total ? "text-emerald-700" : "text-amber-700"}`}>
                                                In {presence.found} of {presence.total} samples
                                            </span>
                                        )}
                                        {insight && (
                                            <span className="text-slate-500 tabular-nums">Confidence {Math.round(insight.confidence * 100)}%</span>
                                        )}
                                        {insight?.evidence.quote && (
                                            <span className="min-w-0 truncate text-slate-500" title={insight.evidence.quote}>
                                                Sample value: <span className="text-slate-800">“{insight.evidence.quote}”</span>
                                            </span>
                                        )}
                                        <button
                                            type="button"
                                            onClick={() => setExpanded((current) => ({ ...current, [field.id!]: !isOpen }))}
                                            className="ml-auto inline-flex items-center gap-0.5 text-blue-700 hover:text-blue-800"
                                            aria-expanded={isOpen}
                                        >
                                            {isOpen ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                                            Details
                                        </button>
                                    </div>

                                    <div className="grid grid-cols-12 gap-2 items-start">
                                        <div className="col-span-3">
                                            <input
                                                type="text"
                                                aria-label="Field name"
                                                className="w-full px-2 py-1.5 text-sm border border-slate-300 rounded"
                                                placeholder="field_name"
                                                value={field.name}
                                                onChange={(e) => updateField(field.id!, { name: e.target.value })}
                                            />
                                        </div>
                                        <div className="col-span-2">
                                            <select
                                                title="Field type"
                                                className="w-full px-2 py-1.5 text-sm border border-slate-300 rounded"
                                                value={field.type}
                                                onChange={(e) => {
                                                    const type = e.target.value as SchemaField["type"]
                                                    updateField(field.id!, type === "array" && !field.table_columns ? { type, table_columns: [] } : { type })
                                                }}
                                            >
                                                <option value="text">Text</option>
                                                <option value="number">Number</option>
                                                <option value="date">Date</option>
                                                <option value="currency">Currency</option>
                                                <option value="boolean">Yes/No</option>
                                                <option value="array">Table</option>
                                            </select>
                                        </div>
                                        <div className="col-span-5">
                                            <input
                                                type="text"
                                                aria-label="Description"
                                                className="w-full px-2 py-1.5 text-sm border border-slate-300 rounded"
                                                placeholder="Describe what this field should capture"
                                                value={field.description}
                                                onChange={(e) => updateField(field.id!, { description: e.target.value })}
                                            />
                                        </div>
                                        <div className="col-span-2 flex items-center justify-between pt-1">
                                            <label className="flex items-center gap-1 text-xs text-slate-600">
                                                <input
                                                    type="checkbox"
                                                    checked={field.required}
                                                    onChange={(e) => updateField(field.id!, { required: e.target.checked })}
                                                />
                                                Required
                                            </label>
                                            <button type="button" title="Remove field" onClick={() => removeField(field.id!)} className="text-slate-400 hover:text-red-500">
                                                <Trash2 className="h-4 w-4" />
                                            </button>
                                        </div>
                                    </div>

                                    {isOpen && (
                                        <div className="space-y-3 rounded-md bg-slate-50 p-3 text-sm">
                                            <div className="grid gap-3 md:grid-cols-2">
                                                <div className="space-y-2">
                                                    {insight ? (
                                                        <>
                                                            <ul className="space-y-1">
                                                                {(insight.samples || [insight.evidence]).map((item: SampleEvidence) => (
                                                                    <li key={item.sample} className="flex items-start gap-1.5 text-xs">
                                                                        <span className="mt-0.5"><CheckIcon ok={item.match !== "none"} /></span>
                                                                        <span className="min-w-0 flex-1 text-slate-700">
                                                                            <span className="font-medium">S{item.sample + 1}</span>{" "}
                                                                            {item.match === "none"
                                                                                ? <span className="text-slate-500">{item.quote ? `“${item.quote}” not found` : "Not in this sample"}</span>
                                                                                : <>“{item.quote}” <span className="text-slate-500">line {item.line_no}</span></>}
                                                                        </span>
                                                                        {item.match !== "none" && samples.length > 0 && (
                                                                            <button
                                                                                type="button"
                                                                                className="shrink-0 text-blue-700 hover:text-blue-800"
                                                                                onClick={() => setFocusByField((current) => ({ ...current, [field.id!]: { sample: item.sample, line: item.line_no, quote: item.quote } }))}
                                                                            >
                                                                                Show
                                                                            </button>
                                                                        )}
                                                                    </li>
                                                                ))}
                                                            </ul>
                                                            <ul className="space-y-1 border-t border-slate-200 pt-2">
                                                                {insight.checks.map((check, index) => (
                                                                    <li key={`${check.key}-${index}`} className="flex items-start gap-1.5 text-xs text-slate-700">
                                                                        <span className="mt-0.5"><CheckIcon ok={check.ok} /></span>
                                                                        {check.message}
                                                                    </li>
                                                                ))}
                                                            </ul>
                                                        </>
                                                    ) : (
                                                        <p className="text-xs text-slate-500">You added this field, so there is no sample check. Use “Test on the samples” below to see what it extracts.</p>
                                                    )}
                                                </div>

                                                <div className="space-y-2">
                                                    {field.type === "array" ? (
                                                        <TableColumnsEditor columns={field.table_columns || []} onChange={(columns) => updateField(field.id!, { table_columns: columns })} />
                                                    ) : (
                                                        <>
                                                            <label className="block text-xs font-medium text-slate-600">
                                                                Labels printed before the value
                                                                <ListInput
                                                                    className="mt-1 w-full rounded border border-slate-300 bg-white px-2 py-1.5 text-sm font-normal"
                                                                    placeholder="e.g. Invoice No, เลขที่"
                                                                    value={field.validation_rules?.source_labels || []}
                                                                    onCommit={(labels) => updateRules(field, { source_labels: labels })}
                                                                />
                                                                <span className="mt-0.5 block font-normal text-slate-500">
                                                                    When a label matches exactly one line, the value after it is used without calling AI.
                                                                </span>
                                                            </label>
                                                            <label className="block text-xs font-medium text-slate-600">
                                                                Format rule (regular expression)
                                                                <input
                                                                    type="text"
                                                                    className={`mt-1 w-full rounded border bg-white px-2 py-1.5 font-mono text-sm font-normal ${patternInvalid ? "border-amber-400" : "border-slate-300"}`}
                                                                    placeholder="e.g. ^INV-\d{6}$"
                                                                    value={pattern || ""}
                                                                    onChange={(e) => updateRules(field, { pattern: e.target.value })}
                                                                />
                                                                {patternInvalid ? (
                                                                    <span className="mt-0.5 block font-normal text-amber-700">
                                                                        This rule could not be checked in the browser. It is checked when you test or save.
                                                                    </span>
                                                                ) : (
                                                                    <span className="mt-0.5 block font-normal text-slate-500">Values that don&apos;t match are sent for review.</span>
                                                                )}
                                                            </label>
                                                        </>
                                                    )}
                                                </div>
                                            </div>
                                            {samples.length > 0 && (
                                                <DocumentTextPanel
                                                    samples={samples}
                                                    focus={focusFor(field)}
                                                    onFocus={(focus) => setFocusByField((current) => ({ ...current, [field.id!]: focus }))}
                                                />
                                            )}
                                        </div>
                                    )}
                                </div>
                            )
                        })}
                    </div>

                    {notFound.length > 0 && (
                        <div className="rounded-lg border border-slate-200 bg-white">
                            <button type="button" onClick={() => setShowNotFound(!showNotFound)} className="flex w-full items-center gap-1 px-3 py-2 text-sm text-slate-700" aria-expanded={showNotFound}>
                                {showNotFound ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                                Not found in the samples ({notFound.length}) — left out of the schema
                            </button>
                            {showNotFound && (
                                <ul className="divide-y border-t">
                                    {notFound.map((field) => (
                                        <li key={field.id} className="flex items-center gap-3 px-3 py-2 text-sm">
                                            <span className="font-medium text-slate-800">{field.name}</span>
                                            <span className="min-w-0 flex-1 truncate text-xs text-slate-500">
                                                {field.studio?.evidence.quote ? `AI suggested “${field.studio.evidence.quote}”, which is not in the documents` : field.description}
                                            </span>
                                            <Button type="button" variant="ghost" size="sm" onClick={() => handleAddBack(field)} className="gap-1">
                                                <Undo2 className="h-3.5 w-3.5" /> Add back
                                            </Button>
                                        </li>
                                    ))}
                                </ul>
                            )}
                        </div>
                    )}

                    <div className="rounded-lg border border-slate-200 bg-white p-4 space-y-3">
                        <div className="flex flex-wrap items-end justify-between gap-3">
                            <div>
                                <h3 className="text-sm font-semibold text-slate-900">Test on the samples</h3>
                                <p className="text-xs text-slate-500">
                                    See what this schema extracts from your files, using the same engines as real jobs (this can use Softnix or LLM credits).
                                </p>
                            </div>
                            <div className="flex items-center gap-2">
                                <select aria-label="Extraction engine" className="rounded border border-slate-300 px-2 py-1.5 text-sm" value={engine} onChange={(e) => setEngine(e.target.value)} disabled={running}>
                                    {ENGINES.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                                </select>
                                <Button type="button" onClick={handleRun} disabled={!studio?.sessionId || running || fields.length === 0 || fieldErrors.length > 0} className="gap-1">
                                    {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                                    {running ? "Testing..." : "Test extraction"}
                                </Button>
                            </div>
                        </div>
                        {!studio?.sessionId && (
                            <p className="text-xs text-slate-500">The samples are no longer available for testing. Choose “Use other files” and upload them again.</p>
                        )}
                        {fieldErrors.length > 0 && (
                            <div className="text-sm text-red-700">
                                <p>Fix these before testing:</p>
                                <ul className="list-disc pl-5">
                                    {fieldErrors.map((error, index) => <li key={index}>{error.message}</li>)}
                                </ul>
                            </div>
                        )}
                        {running && run && (
                            <p className="text-sm text-slate-600 tabular-nums">
                                <Loader2 className="mr-1 inline h-3.5 w-3.5 animate-spin" />
                                Tested {run.done} of {run.total ?? samples.length} sample{(run.total ?? samples.length) === 1 ? "" : "s"}. This can take a few minutes.
                            </p>
                        )}
                        {runError && <p className="text-sm text-red-700">{runError}</p>}
                        {run && run.samples.length > 0 && (
                            <div className="space-y-3">
                                <div className="rounded-md border border-blue-100 bg-blue-50 p-3 text-sm text-slate-700">
                                    <p className="font-medium text-slate-900">Check the results, then confirm the correct values</p>
                                    <p className="mt-0.5 text-xs text-slate-600">
                                        Compare each value with the document. Click <b>Mark correct</b> when it is right, or <b>Type the correct value</b> when it is wrong.
                                        Confirmed values become this schema&apos;s answer key: later tests are scored against them.
                                    </p>
                                </div>
                                {runStale && <p className="text-xs text-amber-700">Fields changed since this test. Run it again to see current results.</p>}
                                <div className="overflow-x-auto">
                                    <table className="w-full min-w-[560px] text-sm">
                                        <thead>
                                            <tr className="border-b text-left align-bottom">
                                                <th className="py-2 pr-3 text-xs font-semibold uppercase tracking-wide text-slate-500">Field</th>
                                                {run.samples.map((sample) => {
                                                    const confirmedHere = fields.filter((f) => expected[sample.index]?.[f.id!] !== undefined).length
                                                    return (
                                                        <th key={sample.index} className="py-2 pr-3 font-normal">
                                                            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Sample {sample.index + 1}</div>
                                                            <div className="max-w-[220px] truncate text-sm text-slate-800" title={sample.filename}>{sample.filename}</div>
                                                            {sample.report && (
                                                                <div className="mt-1.5 flex flex-wrap items-center gap-2">
                                                                    <Button type="button" variant="outline" size="sm" className="h-7 gap-1 px-2 text-xs" onClick={() => confirmAllFound(sample)}>
                                                                        <CheckCircle2 className="h-3.5 w-3.5" /> Confirm all
                                                                    </Button>
                                                                    {confirmedHere > 0 && (
                                                                        <button type="button" className="text-xs text-slate-500 hover:text-slate-700" onClick={() => clearSample(sample.index)}>
                                                                            Clear
                                                                        </button>
                                                                    )}
                                                                    <span className="text-xs text-slate-500 tabular-nums">{confirmedHere} of {fields.length} confirmed</span>
                                                                </div>
                                                            )}
                                                        </th>
                                                    )
                                                })}
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {fields.map((field) => (
                                                <tr key={field.id} className="border-b last:border-0 align-top">
                                                    <td className="py-2 pr-3 font-medium text-slate-800">{field.name}</td>
                                                    {run.samples.map((sample) => {
                                                        if (sample.error) return <td key={sample.index} className="py-2 pr-3 text-red-700">Test failed</td>
                                                        const cell = sample.report?.fields[field.name]
                                                        const result = cell?.status ? RESULT[cell.status] : null
                                                        const value = formatValue(cell?.value)
                                                        const confirmedValue = expected[sample.index]?.[field.id!]
                                                        const isConfirmed = confirmedValue !== undefined
                                                        const hasValue = cell && cell.value !== null && cell.value !== undefined && cell.value !== ""
                                                        const differs = isConfirmed && !sameValue(confirmedValue, cell?.value)
                                                        const editKey = `${sample.index}:${field.id}`
                                                        const isEditing = editing?.key === editKey
                                                        const canType = field.type !== "array"
                                                        return (
                                                            <td key={sample.index} className="py-1 pr-3">
                                                                <div className={`flex items-start justify-between gap-3 rounded-md px-2 py-1.5 ${isConfirmed ? "bg-emerald-50" : ""}`}>
                                                                    <div className="min-w-0">
                                                                        <div className="max-w-[220px] break-words text-slate-800" title={value}>{value}</div>
                                                                        <div className={`mt-0.5 flex items-center gap-1 text-xs ${result?.cls || "text-slate-500"}`} title={cell?.reason || undefined}>
                                                                            <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${result?.dot || "bg-slate-300"}`} />
                                                                            {cell ? (result?.label || cell.status) : "Not tested"}
                                                                        </div>
                                                                        {differs && (
                                                                            <div className="mt-0.5 text-xs text-slate-700">
                                                                                Correct value: <span className="font-medium">{formatValue(confirmedValue)}</span>
                                                                            </div>
                                                                        )}
                                                                        {isEditing ? (
                                                                            <form
                                                                                className="mt-1 flex items-center gap-1"
                                                                                onSubmit={(e) => {
                                                                                    e.preventDefault()
                                                                                    const typed = parseTypedValue(editing.text, field.type)
                                                                                    if (typed !== undefined) setConfirmed(sample.index, field.id!, typed, true)
                                                                                    setEditing(null)
                                                                                }}
                                                                            >
                                                                                <input
                                                                                    autoFocus
                                                                                    aria-label={`Correct value for ${field.name} in sample ${sample.index + 1}`}
                                                                                    className="w-40 rounded border border-slate-300 px-1.5 py-0.5 text-xs"
                                                                                    value={editing.text}
                                                                                    onChange={(e) => setEditing({ key: editKey, text: e.target.value })}
                                                                                    onKeyDown={(e) => { if (e.key === "Escape") setEditing(null) }}
                                                                                />
                                                                                <button type="submit" className="text-xs font-medium text-emerald-700">Save</button>
                                                                                <button type="button" className="text-xs text-slate-500" onClick={() => setEditing(null)}>Cancel</button>
                                                                            </form>
                                                                        ) : canType && (
                                                                            <button
                                                                                type="button"
                                                                                className="mt-0.5 text-xs text-blue-700 hover:text-blue-800"
                                                                                onClick={() => setEditing({
                                                                                    key: editKey,
                                                                                    text: editableText(isConfirmed ? confirmedValue : cell?.value),
                                                                                })}
                                                                            >
                                                                                {hasValue || isConfirmed ? "Type the correct value" : "Enter the value"}
                                                                            </button>
                                                                        )}
                                                                    </div>
                                                                    {isConfirmed ? (
                                                                        <button
                                                                            type="button"
                                                                            onClick={() => setConfirmed(sample.index, field.id!, undefined, false)}
                                                                            title="Click to undo"
                                                                            aria-pressed="true"
                                                                            className="inline-flex shrink-0 items-center gap-1 rounded-full bg-emerald-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-emerald-700"
                                                                        >
                                                                            <CheckCircle2 className="h-3.5 w-3.5" /> Correct
                                                                        </button>
                                                                    ) : hasValue ? (
                                                                        <button
                                                                            type="button"
                                                                            onClick={() => setConfirmed(sample.index, field.id!, cell?.value, true)}
                                                                            aria-pressed="false"
                                                                            className="shrink-0 rounded-full border border-slate-300 bg-white px-2.5 py-1 text-xs font-medium text-slate-700 hover:border-emerald-500 hover:text-emerald-700"
                                                                        >
                                                                            Mark correct
                                                                        </button>
                                                                    ) : (
                                                                        <span className="shrink-0 px-1 py-1 text-xs text-slate-400">Nothing to confirm</span>
                                                                    )}
                                                                </div>
                                                            </td>
                                                        )
                                                    })}
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </div>
                                <p className="text-xs text-slate-500 tabular-nums">
                                    {confirmedCount} value{confirmedCount === 1 ? "" : "s"} confirmed.
                                    {" "}On the next step you can keep the sample files so these values are used to test future changes.
                                </p>
                            </div>
                        )}
                    </div>

                    <div className="flex justify-end">
                        <Button type="button" onClick={nextStep} disabled={!canProceed} className="gap-2">
                            Next <ArrowRight className="h-4 w-4" />
                        </Button>
                    </div>
                </div>
            )}

            <div className="text-center pt-4">
                <Button variant="ghost" className="text-slate-500" onClick={() => setManualEntry(true)} disabled={isAnalyzing}>
                    Enter fields manually <ArrowRight className="h-4 w-4 ml-1" />
                </Button>
            </div>
        </div>
    )
}

function TableColumnsEditor({ columns, onChange }: { columns: TableColumn[]; onChange: (columns: TableColumn[]) => void }) {
    const update = (index: number, patch: Partial<TableColumn>) =>
        onChange(columns.map((column, i) => (i === index ? { ...column, ...patch } : column)))
    return (
        <div className="space-y-1.5">
            <div className="text-xs font-medium text-slate-600">Table columns</div>
            {columns.length === 0 && <p className="text-xs text-slate-500">Add the columns to read from each row.</p>}
            {columns.map((column, index) => (
                <div key={index} className="flex items-center gap-2">
                    <input
                        type="text"
                        aria-label={`Column ${index + 1} name`}
                        className="min-w-0 flex-1 rounded border border-slate-300 bg-white px-2 py-1 text-sm"
                        placeholder="column_name"
                        value={column.name}
                        onChange={(e) => update(index, { name: e.target.value })}
                    />
                    <select
                        aria-label={`Column ${index + 1} type`}
                        className="rounded border border-slate-300 bg-white px-2 py-1 text-sm"
                        value={column.type}
                        onChange={(e) => update(index, { type: e.target.value as ArrayColumnType })}
                    >
                        {COLUMN_TYPES.map((type) => <option key={type} value={type}>{type}</option>)}
                    </select>
                    <button type="button" title="Remove column" onClick={() => onChange(columns.filter((_, i) => i !== index))} className="text-slate-400 hover:text-red-500">
                        <Trash2 className="h-3.5 w-3.5" />
                    </button>
                </div>
            ))}
            <Button type="button" variant="outline" size="sm" onClick={() => onChange([...columns, { name: "", type: "text" }])} className="gap-1">
                <Plus className="h-3.5 w-3.5" /> Add column
            </Button>
        </div>
    )
}
