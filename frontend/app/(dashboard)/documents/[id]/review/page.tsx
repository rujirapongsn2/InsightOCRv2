"use client"

import { useEffect, useState } from "react"
import { useParams, useRouter } from "next/navigation"
import Link from "next/link"
import { ArrowLeft, Save, CheckCircle, AlertTriangle } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

interface Document {
    id: string
    filename: string
    status: string
    ocr_text: string
    extracted_data: any
    reviewed_data: any
    job_id: string
}
type ExtractedEntry = Record<string, any>

export default function ReviewDocumentPage() {
    const params = useParams()
    const router = useRouter()
    const documentId = params.id as string
    const [document, setDocument] = useState<Document | null>(null)
    const [formData, setFormData] = useState<ExtractedEntry[]>([])
    const [loading, setLoading] = useState(true)
    const [saving, setSaving] = useState(false)

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
                const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1'}/documents/${documentId}`, {
                    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
                })
                if (res.ok) {
                    const data = await res.json()
                    setDocument(data)
                    // Initialize form data with reviewed data if exists, else extracted data
                    setFormData(normalizeExtractedData(data.reviewed_data || data.extracted_data))
                }
            } catch (error) {
                console.error("Failed to fetch document", error)
            } finally {
                setLoading(false)
            }
        }
        fetchDocument()
    }, [documentId])

    const handleFieldChange = (index: number, key: string, value: any) => {
        setFormData((prev) => {
            const next = [...prev]
            next[index] = { ...(next[index] || {}), [key]: value }
            return next
        })
    }

    const handleSave = async (markAsReviewed: boolean = false) => {
        setSaving(true)
        try {
            const payload = {
                reviewed_data: formData,
                status: markAsReviewed ? "reviewed" : undefined
            }

            const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
            const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1'}/documents/${documentId}`, {
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
                {/* Left: Document Viewer (Placeholder) */}
                <div className="w-1/2 bg-slate-100 p-4 border-r overflow-auto flex items-center justify-center">
                    <div className="text-center text-slate-500">
                        <p>Document Viewer Placeholder</p>
                        <p className="text-xs mt-2">PDF/Image rendering would go here.</p>
                        <div className="mt-8 p-4 bg-white rounded shadow text-left max-w-md mx-auto text-xs font-mono whitespace-pre-wrap max-h-96 overflow-auto">
                            {document.ocr_text || "No OCR text available"}
                        </div>
                    </div>
                </div>

                {/* Right: Extraction Form */}
                <div className="w-1/2 bg-white p-6 overflow-auto">
                    <h3 className="font-semibold mb-6">Extracted Data</h3>

                    {formData.length === 0 ? (
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
