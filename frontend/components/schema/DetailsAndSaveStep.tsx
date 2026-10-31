"use client"

import { useState } from "react"
import { CheckCircle, Loader2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { useSchemaWizard } from "@/contexts/SchemaWizardContext"
import { SchemaField } from "@/types/schema"
import { isValidFieldName, validateFields } from "@/lib/schema-validation"

export function DetailsAndSaveStep() {
    const { schemaId, schemaData, fields, updateSchemaData, isSaving, saveSchema, previousStep, studio, updateStudio, referencePdf, referencePdfInfo, setReferenceConsent, isRemovingReference, fixedFieldCreationMode } = useSchemaWizard()
    const confirmedValues = studio
        ? Object.values(studio.expected).reduce(
            (sum, values) => sum + fields.filter((field) => field.id && values[field.id] !== undefined).length, 0)
        : 0
    const [nameError, setNameError] = useState("")

    const fieldErrors = validateFields(fields).filter((error) => error.severity === "error")
    const hasInvalidFields = fieldErrors.length > 0
    const canSave = fixedFieldCreationMode === "idle" && fields.length > 0 && !hasInvalidFields && schemaData.name.trim().length > 0

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
                        <label htmlFor="schema-name" className="text-sm font-medium text-slate-700">Schema Name <span className="text-red-500">*</span></label>
                        <input
                            id="schema-name"
                            type="text"
                            value={schemaData.name}
                            onChange={e => { updateSchemaData({ name: e.target.value }); setNameError("") }}
                            className={`w-full px-4 py-2 border rounded-lg focus:outline-none focus:ring-2 ${nameError ? "border-red-400 focus:ring-red-400" : "border-slate-300 focus:ring-blue-500"}`}
                            placeholder="e.g. Standard Invoice 2026"
                        />
                        {nameError && <p className="text-sm text-red-600">{nameError}</p>}
                    </div>

                    <div className="space-y-1">
                        <label htmlFor="schema-description" className="text-sm font-medium text-slate-700">Description <span className="text-slate-400 text-xs">(optional)</span></label>
                        <textarea
                            id="schema-description"
                            value={schemaData.description}
                            onChange={e => updateSchemaData({ description: e.target.value })}
                            rows={1}
                            className="w-full px-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                            placeholder="Describe what this schema is used for..."
                        />
                    </div>
                    <label className="space-y-1 text-sm font-medium text-slate-700">
                        <span>Document Type</span>
                        <select aria-label="Document Type" className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                            value={schemaData.document_type}
                            onChange={(event) => {
                                const value = event.target.value
                                if (value === "invoice" || value === "receipt" || value === "contract" || value === "po" || value === "other") updateSchemaData({ document_type: value })
                            }}>
                            <option value="invoice">Invoice</option><option value="receipt">Receipt</option><option value="contract">Contract</option><option value="po">Purchase Order</option><option value="other">Other</option>
                        </select>
                    </label>
                </div>
            </div>

            <div className="pt-4 border-t text-sm text-slate-600">
                {referencePdf.kind === "stored" && <p className="mb-2 break-words">PDF: {referencePdf.file.name} · Saved attachment</p>}
                {referencePdf.kind === "selected" && <fieldset className="mb-4 space-y-2">
                    <legend className="mb-2 font-medium text-slate-900 break-words">Reference PDF: {referencePdf.file.name}</legend>
                    <label className="flex items-start gap-2">
                        <input type="radio" name="reference-pdf-storage" className="mt-1" checked={referencePdf.consent} onChange={() => setReferenceConsent(true)} />
                        <span>Keep this PDF with the schema<span className="block text-xs text-slate-500">I consent to storing this file until removed. Only schema managers can access it.</span></span>
                    </label>
                    <label className="flex items-start gap-2">
                        <input type="radio" name="reference-pdf-storage" className="mt-1" checked={!referencePdf.consent} onChange={() => setReferenceConsent(false)} />
                        <span>Do not attach this PDF{referencePdfInfo && <span className="block text-xs text-slate-500">The saved {referencePdfInfo.filename} remains attached.</span>}</span>
                    </label>
                    {referencePdf.consent === true && <p className="text-xs text-emerald-700">Will be attached when saved</p>}
                </fieldset>}
                <p>
                    {fields.length} field(s) ready for saving.
                </p>
                {hasInvalidFields && (
                    <p className="text-red-600 mt-2">
                        Fix the field names before saving: {fieldErrors.map((error) => error.message).join(" ")}
                    </p>
                )}
            </div>

            <div className="space-y-2 border-t pt-4">
                <h3 className="text-sm font-semibold text-slate-800">Fields in this schema</h3>
                <div className="flex flex-wrap gap-2" aria-label="Schema field names">
                    {fields.map((field: SchemaField) => (
                        <span key={field.id || field.name} className={`rounded-md border px-2.5 py-1 text-xs font-medium ${isValidFieldName(field.name) ? "border-slate-200 bg-slate-50 text-slate-700" : "border-red-200 bg-red-50 text-red-700"}`}>
                            {field.name || "(unnamed)"}
                        </span>
                    ))}
                </div>
            </div>

            {studio && studio.files.length > 0 && (
                <div className="space-y-2 border-t pt-4">
                    <h3 className="text-sm font-semibold text-slate-800">Test set</h3>
                    <label className="flex items-start gap-2 text-sm text-slate-700">
                        <input
                            type="checkbox"
                            className="mt-1"
                            checked={studio.keepSamples}
                            onChange={(e) => updateStudio({ keepSamples: e.target.checked })}
                            disabled={isSaving}
                        />
                        <span>
                            Keep {studio.files.length === 1 ? "this sample file" : `these ${studio.files.length} sample files`} as this schema&apos;s test set.
                            <span className="block text-xs text-slate-500">
                                The files and their text are stored for {studio.retentionDays} days and are visible only to people who can manage this schema.
                                They may contain personal data. You can delete them at any time from the schema page.
                                {confirmedValues > 0
                                    ? ` ${confirmedValues} confirmed value${confirmedValues === 1 ? "" : "s"} will be used to check future changes.`
                                    : " No values are confirmed yet, so tests can only show what is extracted."}
                            </span>
                        </span>
                    </label>
                </div>
            )}

            {/* Navigation */}
            <div className="flex justify-between pt-6 border-t mt-8">
                <Button variant="outline" onClick={previousStep} disabled={isSaving || isRemovingReference}>
                    ← Back to fields
                </Button>
                <Button onClick={handleSave} disabled={isSaving || isRemovingReference || !canSave} className="min-w-[140px] bg-blue-600 hover:bg-blue-700 text-white">
                    {isSaving ? (
                        <><Loader2 className="h-4 w-4 mr-2 animate-spin" /> Saving...</>
                    ) : (
                        <><CheckCircle className="h-4 w-4 mr-2" /> {schemaId ? "Save Changes" : "Save Schema"}</>
                    )}
                </Button>
            </div>
        </div>
    )
}
