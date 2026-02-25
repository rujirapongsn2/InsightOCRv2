"use client"

import { useState } from "react"
import { CheckCircle, Loader2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { useSchemaWizard } from "@/contexts/SchemaWizardContext"
import { SchemaField } from "@/types/schema"

function isValidFieldName(name: string) {
    return /^[a-zA-Z_][a-zA-Z0-9_\-]*$/.test(name)
}

export function DetailsAndSaveStep() {
    const { schemaData, fields, updateSchemaData, isSaving, saveSchema, previousStep } = useSchemaWizard()
    const [nameError, setNameError] = useState("")

    const hasInvalidFields = fields.some((f: SchemaField) => !f.name || !isValidFieldName(f.name))
    const canSave = fields.length > 0 && !hasInvalidFields && schemaData.name.trim().length > 0

    const handleSave = () => {
        if (!schemaData.name.trim()) {
            setNameError("Schema name is required")
            return
        }
        if (hasInvalidFields) return
        setNameError("")
        saveSchema()
    }

    return (
        <div className="space-y-8">
            {/* Schema Info */}
            <div className="space-y-4">
                <div>
                    <h2 className="text-xl font-semibold text-slate-900">Name and Save Schema</h2>
                    <p className="text-sm text-slate-500 mt-1">Provide schema name and description, then save.</p>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="space-y-1">
                        <label className="text-sm font-medium text-slate-700">Schema Name <span className="text-red-500">*</span></label>
                        <input
                            type="text"
                            value={schemaData.name}
                            onChange={e => { updateSchemaData({ name: e.target.value }); setNameError("") }}
                            className={`w-full px-4 py-2 border rounded-lg focus:outline-none focus:ring-2 ${nameError ? "border-red-400 focus:ring-red-400" : "border-slate-300 focus:ring-blue-500"}`}
                            placeholder="e.g. Standard Invoice 2026"
                        />
                        {nameError && <p className="text-sm text-red-600">{nameError}</p>}
                    </div>

                    <div className="space-y-1">
                        <label className="text-sm font-medium text-slate-700">Description <span className="text-slate-400 text-xs">(optional)</span></label>
                        <textarea
                            value={schemaData.description}
                            onChange={e => updateSchemaData({ description: e.target.value })}
                            rows={1}
                            className="w-full px-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                            placeholder="Describe what this schema is used for..."
                        />
                    </div>
                </div>
            </div>

            <div className="pt-4 border-t text-sm text-slate-600">
                <p>
                    {fields.length} field(s) ready for saving.
                </p>
                {hasInvalidFields && (
                    <p className="text-red-600 mt-2">
                        Some field names are invalid. Go back and fix them before saving.
                    </p>
                )}
            </div>

            {/* Navigation */}
            <div className="flex justify-between pt-6 border-t mt-8">
                <Button variant="outline" onClick={previousStep} disabled={isSaving}>
                    ← Back to fields
                </Button>
                <Button onClick={handleSave} disabled={isSaving || !canSave} className="min-w-[140px] bg-blue-600 hover:bg-blue-700 text-white">
                    {isSaving ? (
                        <><Loader2 className="h-4 w-4 mr-2 animate-spin" /> Saving...</>
                    ) : (
                        <><CheckCircle className="h-4 w-4 mr-2" /> Save Schema</>
                    )}
                </Button>
            </div>
        </div>
    )
}
