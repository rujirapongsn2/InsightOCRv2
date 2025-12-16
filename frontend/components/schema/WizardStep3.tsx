"use client"

import { useState } from "react"
import { Plus, Trash2, AlertCircle } from "lucide-react"
import { Button } from "@/components/ui/button"
import { HelpTooltip } from "@/components/ui/help-tooltip"
import { InfoCard } from "@/components/ui/info-card"
import { useSchemaWizard } from "@/contexts/SchemaWizardContext"
import { validateFields, hasErrors, getFieldErrors } from "@/lib/schema-validation"
import { FieldType, SchemaField, FIELD_SUGGESTIONS } from "@/types/schema"

const FIELD_TYPE_OPTIONS: Array<{ value: FieldType; label: string }> = [
  { value: "text", label: "Text" },
  { value: "number", label: "Number" },
  { value: "date", label: "Date" },
  { value: "currency", label: "Currency" },
  { value: "boolean", label: "Yes/No" }
]

export function WizardStep3() {
  const { schemaData, fields, addField, updateField, removeField, validationErrors, nextStep, previousStep } = useSchemaWizard()
  const [showSuggestions, setShowSuggestions] = useState(true)

  const suggestions = FIELD_SUGGESTIONS[schemaData.document_type] || []
  const fieldErrors = validateFields(fields)

  const handleAddField = () => {
    const newField: SchemaField = {
      name: "",
      type: "text",
      description: "",
      required: false
    }
    addField(newField)
  }

  const handleAddSuggestedField = (suggestion: typeof suggestions[0]) => {
    const newField: SchemaField = {
      name: suggestion.name,
      type: suggestion.type,
      description: suggestion.description,
      required: suggestion.required
    }
    addField(newField)
  }

  const handleNext = () => {
    const errors = validateFields(fields)
    // Only proceed if no errors (warnings are okay)
    if (!hasErrors(errors)) {
      nextStep()
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-slate-900">Define Fields</h2>
        <p className="text-sm text-slate-600 mt-1">
          Specify what data to extract from your documents
        </p>
      </div>

      {fields.length === 0 && (
        <InfoCard type="tip">
          Start by adding fields that you want to extract from your documents.
          You can use the suggested fields below or create your own.
        </InfoCard>
      )}

      {/* Field Suggestions */}
      {suggestions.length > 0 && showSuggestions && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-medium text-blue-900">Suggested Fields</h3>
            <button
              onClick={() => setShowSuggestions(false)}
              className="text-xs text-blue-600 hover:text-blue-800"
            >
              Hide
            </button>
          </div>
          <div className="grid grid-cols-2 gap-2">
            {suggestions.map((suggestion, idx) => {
              const alreadyAdded = fields.some(f => f.name === suggestion.name)
              return (
                <button
                  key={idx}
                  onClick={() => handleAddSuggestedField(suggestion)}
                  disabled={alreadyAdded}
                  className={`text-left p-3 rounded-lg border text-sm transition-colors ${
                    alreadyAdded
                      ? "bg-slate-100 border-slate-200 cursor-not-allowed opacity-60"
                      : "bg-white border-blue-300 hover:border-blue-400 hover:bg-blue-50"
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <span className="text-lg">{suggestion.icon}</span>
                    <div className="flex-1 min-w-0">
                      <div className="font-medium text-slate-900 truncate">
                        {suggestion.name}
                      </div>
                      <div className="text-xs text-slate-500 truncate">
                        {suggestion.description}
                      </div>
                    </div>
                    {alreadyAdded && (
                      <span className="text-xs text-green-600">Added</span>
                    )}
                  </div>
                </button>
              )
            })}
          </div>
        </div>
      )}

      {/* Fields List */}
      {fields.length > 0 && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="font-medium text-slate-900">
              Fields ({fields.length})
            </h3>
          </div>

          {fields.map((field) => {
            const errors = getFieldErrors(field.id || "", fieldErrors)
            const hasError = errors.some(e => e.severity === "error")

            return (
              <div
                key={field.id}
                className={`border rounded-lg p-4 ${
                  hasError ? "border-red-300 bg-red-50" : "border-slate-200 bg-white"
                }`}
              >
                <div className="grid grid-cols-2 gap-4">
                  {/* Field Name */}
                  <div>
                    <div className="flex items-center gap-2 mb-2">
                      <label className="block text-sm font-medium text-slate-700">
                        Field Name <span className="text-red-500">*</span>
                      </label>
                      <HelpTooltip
                        content="Must be valid JSON Schema property name: start with letter or underscore, use letters (any language), numbers, underscores, hyphens. NO SPACES. Examples: invoice_number, เลขที่ใบแจ้งหนี้, customer_name"
                      />
                    </div>
                    <input
                      type="text"
                      value={field.name || ""}
                      onChange={(e) => updateField(field.id || "", { name: e.target.value })}
                      className={`w-full px-3 py-2 border rounded-lg text-sm focus:outline-none focus:ring-2 ${
                        hasError
                          ? "border-red-300 focus:ring-red-500"
                          : "border-slate-300 focus:ring-blue-500"
                      }`}
                      placeholder="e.g., invoice_number"
                    />
                  </div>

                  {/* Field Type */}
                  <div>
                    <div className="flex items-center gap-2 mb-2">
                      <label className="block text-sm font-medium text-slate-700">
                        Type <span className="text-red-500">*</span>
                      </label>
                      <HelpTooltip
                        content="The type of data this field will contain"
                      />
                    </div>
                    <select
                      value={field.type}
                      onChange={(e) => updateField(field.id || "", { type: e.target.value as FieldType })}
                      className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    >
                      {FIELD_TYPE_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </div>

                  {/* Field Description */}
                  <div className="col-span-2">
                    <div className="flex items-center gap-2 mb-2">
                      <label className="block text-sm font-medium text-slate-700">
                        Description
                      </label>
                      <HelpTooltip
                        content="Explain what this field represents. This helps the AI extract the correct data."
                      />
                    </div>
                    <input
                      type="text"
                      value={field.description || ""}
                      onChange={(e) => updateField(field.id || "", { description: e.target.value })}
                      className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                      placeholder="e.g., The unique invoice number from the document"
                    />
                  </div>

                  {/* Required Toggle and Delete Button */}
                  <div className="col-span-2 flex items-center justify-between pt-2 border-t">
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={field.required}
                        onChange={(e) => updateField(field.id || "", { required: e.target.checked })}
                        className="w-4 h-4 text-blue-600 border-slate-300 rounded focus:ring-blue-500"
                      />
                      <span className="text-sm text-slate-700">Required field</span>
                    </label>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => removeField(field.id || "")}
                      className="text-red-600 hover:text-red-700 hover:bg-red-50"
                    >
                      <Trash2 className="h-4 w-4 mr-1" />
                      Remove
                    </Button>
                  </div>
                </div>

                {/* Field Errors */}
                {errors.length > 0 && (
                  <div className="mt-3 space-y-1">
                    {errors.map((error, idx) => (
                      <div
                        key={idx}
                        className={`flex items-start gap-2 text-sm ${
                          error.severity === "error" ? "text-red-600" : "text-yellow-600"
                        }`}
                      >
                        <AlertCircle className="h-4 w-4 mt-0.5 flex-shrink-0" />
                        <span>{error.message}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* Add Field Button */}
      <Button
        variant="outline"
        onClick={handleAddField}
        className="w-full border-dashed border-2"
      >
        <Plus className="h-4 w-4 mr-2" />
        Add Custom Field
      </Button>

      {/* Error Summary */}
      {hasErrors(fieldErrors) && (
        <InfoCard type="error">
          Please fix the errors in your fields before continuing.
        </InfoCard>
      )}

      {/* Navigation Buttons */}
      <div className="flex justify-between pt-6 border-t">
        <Button
          variant="outline"
          onClick={previousStep}
        >
          Previous
        </Button>
        <Button
          onClick={handleNext}
          disabled={hasErrors(fieldErrors) || fields.length === 0}
        >
          Next: Review & Save
        </Button>
      </div>
    </div>
  )
}
