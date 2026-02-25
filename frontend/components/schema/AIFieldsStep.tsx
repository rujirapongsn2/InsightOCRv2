"use client"

import { useState, type ChangeEvent } from "react"
import { Loader2, AlertCircle, FileText, Sparkles, ArrowRight, Plus, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { useSchemaWizard } from "@/contexts/SchemaWizardContext"
import { SchemaField } from "@/types/schema"
import { getApiBaseUrl } from "@/lib/api"

// Generate a simple unique ID
const genId = () => `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`

export function AIFieldsStep() {
    const { startingPoint, schemaData, fields, setFields, addField, updateField, removeField, nextStep } = useSchemaWizard()
    const isAIMode = startingPoint === "ai"

    // AI Upload State
    const [file, setFile] = useState<File | null>(null)
    const [isAnalyzing, setIsAnalyzing] = useState(false)
    const [aiError, setAiError] = useState<string | null>(null)
    const [analyzed, setAnalyzed] = useState(false)
    const [suggestedFieldsCount, setSuggestedFieldsCount] = useState(0)

    // For Template/Scratch modes, skip this step and go straight to config
    if (!isAIMode) {
        return (
            <div className="text-center py-12 space-y-4">
                <p className="text-slate-600">Skip AI analysis and continue to schema details.</p>
                <Button onClick={nextStep} className="gap-2">
                    Continue <ArrowRight className="h-4 w-4" />
                </Button>
            </div>
        )
    }

    const handleFileSelect = (e: ChangeEvent<HTMLInputElement>) => {
        const f = e.target.files?.[0]
        if (!f) return

        const validTypes = ["application/pdf", "image/jpeg", "image/jpg", "image/png"]
        if (!validTypes.includes(f.type)) {
            setAiError("Please upload a PDF, JPG, or PNG file")
            return
        }

        setFile(f)
        setAiError(null)
        setAnalyzed(false)
    }

    const handleAnalyze = async () => {
        if (!file) return
        setIsAnalyzing(true)
        setAiError(null)

        try {
            const token = localStorage.getItem("token")
            const formData = new FormData()
            formData.append("file", file)

            const params = new URLSearchParams()
            if (schemaData.document_type) {
                params.set("document_type", schemaData.document_type)
            }

            const suggestRes = await fetch(`${getApiBaseUrl()}/schemas/suggest-from-file?${params.toString()}`, {
                method: "POST",
                headers: token ? { Authorization: `Bearer ${token}` } : {},
                body: formData
            })
            if (!suggestRes.ok) {
                const err = await suggestRes.json().catch(() => ({}))
                throw new Error(err.detail || "AI suggestion failed")
            }

            const suggestData = await suggestRes.json()
            const suggested: SchemaField[] = (suggestData.suggested_fields || []).map((f: any) => ({
                id: genId(),
                name: f.name,
                type: f.type || "text",
                description: f.description || "",
                required: false,
                order: 0
            }))

            setFields(suggested)
            setSuggestedFieldsCount(suggested.length)
            setAnalyzed(true)

        } catch (err: any) {
            setAiError(err.message || "Analysis failed")
        } finally {
            setIsAnalyzing(false)
        }
    }

    const handleAddField = () => {
        addField({
            id: genId(),
            name: "",
            type: "text",
            description: "",
            required: false,
        })
    }

    const canProceed = fields.length > 0 && fields.every((f: SchemaField) => f.name.trim().length > 0)

    return (
        <div className="space-y-6 max-w-4xl mx-auto py-8">
            <div className="text-center space-y-2">
                <div className="mx-auto w-12 h-12 bg-purple-100 text-purple-600 rounded-full flex items-center justify-center mb-4">
                    <Sparkles className="h-6 w-6" />
                </div>
                <h2 className="text-2xl font-semibold text-slate-900">Upload Sample Document</h2>
                <p className="text-slate-500">
                    Analyze the uploaded file and generate editable JSON schema fields.
                </p>
            </div>

            <div className="bg-white border-2 border-dashed border-purple-200 rounded-xl p-8 transition-all hover:border-purple-400">
                <div className="flex flex-col items-center gap-4">
                    <FileText className="h-10 w-10 text-purple-300" />
                    <div className="text-center">
                        <label className="cursor-pointer">
                            <span className="text-purple-600 font-medium hover:text-purple-700">Browse files</span>
                            <span className="text-slate-500"> or drag and drop</span>
                            <input type="file" className="hidden" accept=".pdf,.jpg,.jpeg,.png" onChange={handleFileSelect} disabled={isAnalyzing || analyzed} />
                        </label>
                        <p className="text-xs text-slate-400 mt-1">PDF, JPG, PNG up to 10MB</p>
                    </div>

                    {file && (
                        <div className="w-full bg-slate-50 border border-slate-200 rounded-lg p-3 flex items-center justify-between">
                            <div className="flex items-center gap-2 overflow-hidden">
                                <FileText className="h-4 w-4 text-slate-400 flex-shrink-0" />
                                <span className="text-sm text-slate-700 truncate">{file.name}</span>
                            </div>
                            {!isAnalyzing && !analyzed && (
                                <button onClick={() => setFile(null)} className="text-slate-400 hover:text-red-500 text-xs">
                                    Remove
                                </button>
                            )}
                        </div>
                    )}

                    <Button
                        onClick={handleAnalyze}
                        disabled={!file || isAnalyzing || analyzed}
                        className="w-full mt-2 bg-purple-600 hover:bg-purple-700 text-white shadow-sm"
                        size="lg"
                    >
                        {isAnalyzing ? (
                            <><Loader2 className="h-4 w-4 mr-2 animate-spin" /> Analyzing document...</>
                        ) : analyzed ? (
                            <><Sparkles className="h-4 w-4 mr-2" /> Analysis completed ({suggestedFieldsCount} fields)</>
                        ) : (
                            <><Sparkles className="h-4 w-4 mr-2" /> Analyze with AI</>
                        )}
                    </Button>
                </div>
            </div>

            {aiError && (
                <div className="p-3 bg-red-50 text-red-700 rounded-lg border border-red-200 text-sm flex items-start gap-2">
                    <AlertCircle className="h-4 w-4 mt-0.5" />
                    <div>{aiError}</div>
                </div>
            )}

            {analyzed && (
                <div className="space-y-4 pt-2 border-t">
                    <div className="flex items-center justify-between">
                        <div>
                            <h3 className="text-lg font-semibold text-slate-900">Suggested Fields</h3>
                            <p className="text-sm text-slate-500">Edit suggested fields, or add new fields before continuing.</p>
                        </div>
                        <Button type="button" variant="outline" onClick={handleAddField}>
                            <Plus className="h-4 w-4 mr-1" /> Add Field
                        </Button>
                    </div>

                    {fields.length > 0 && (
                        <div className="grid grid-cols-12 gap-2 px-3 text-xs font-semibold text-slate-500 uppercase tracking-wide">
                            <div className="col-span-3">Field Name</div>
                            <div className="col-span-2">Type</div>
                            <div className="col-span-5">Description</div>
                            <div className="col-span-2">Required</div>
                        </div>
                    )}

                    <div className="space-y-2">
                        {fields.map((field: SchemaField) => (
                            <div key={field.id} className="grid grid-cols-12 gap-2 items-start p-3 border border-slate-200 rounded-lg bg-white">
                                <div className="col-span-3">
                                    <input
                                        type="text"
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
                                        onChange={(e) => updateField(field.id!, { type: e.target.value as SchemaField["type"] })}
                                    >
                                        <option value="text">Text</option>
                                        <option value="number">Number</option>
                                        <option value="date">Date</option>
                                        <option value="currency">Currency</option>
                                        <option value="boolean">Yes/No</option>
                                        <option value="array">Array/List</option>
                                    </select>
                                </div>
                                <div className="col-span-5">
                                    <input
                                        type="text"
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
                                    <button
                                        type="button"
                                        title="Remove field"
                                        onClick={() => removeField(field.id!)}
                                        className="text-slate-400 hover:text-red-500"
                                    >
                                        <Trash2 className="h-4 w-4" />
                                    </button>
                                </div>
                            </div>
                        ))}
                    </div>

                    <div className="flex justify-end">
                        <Button type="button" onClick={nextStep} disabled={!canProceed} className="gap-2">
                            Next <ArrowRight className="h-4 w-4" />
                        </Button>
                    </div>
                </div>
            )}

            <div className="text-center pt-4">
                <Button variant="ghost" className="text-slate-500" onClick={nextStep} disabled={isAnalyzing}>
                    Skip AI analysis (create fields manually) <ArrowRight className="h-4 w-4 ml-1" />
                </Button>
            </div>
        </div>
    )
}
