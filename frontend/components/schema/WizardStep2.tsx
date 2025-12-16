"use client"

import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { HelpTooltip } from "@/components/ui/help-tooltip"
import { InfoCard } from "@/components/ui/info-card"
import { useSchemaWizard } from "@/contexts/SchemaWizardContext"
import { validateSchemaData, hasErrors, getFieldErrors } from "@/lib/schema-validation"
import { DocumentType } from "@/types/schema"

const DOCUMENT_TYPE_OPTIONS: Array<{ value: DocumentType; label: string; description: string }> = [
  {
    value: "invoice",
    label: "Invoice",
    description: "Commercial invoices, billing statements"
  },
  {
    value: "receipt",
    label: "Receipt",
    description: "Purchase receipts, payment confirmations"
  },
  {
    value: "po",
    label: "Purchase Order",
    description: "Purchase orders, procurement documents"
  },
  {
    value: "contract",
    label: "Contract",
    description: "Legal contracts, agreements"
  },
  {
    value: "other",
    label: "Other",
    description: "Custom document type"
  }
]

export function WizardStep2() {
  const { schemaData, updateSchemaData, validationErrors, nextStep, previousStep } = useSchemaWizard()
  const [localErrors, setLocalErrors] = useState(validationErrors)

  // Validate on data change
  useEffect(() => {
    const errors = validateSchemaData(schemaData)
    setLocalErrors(errors)
  }, [schemaData])

  const handleNext = () => {
    const errors = validateSchemaData(schemaData)
    setLocalErrors(errors)

    // Only proceed if no errors (warnings are okay)
    if (!hasErrors(errors)) {
      nextStep()
    }
  }

  const nameErrors = getFieldErrors("name", localErrors)
  const documentTypeErrors = getFieldErrors("document_type", localErrors)
  const descriptionWarnings = getFieldErrors("description", localErrors)

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-slate-900">Basic Information</h2>
        <p className="text-sm text-slate-600 mt-1">
          Provide essential details about your schema
        </p>
      </div>

      <InfoCard type="tip" dismissible>
        Give your schema a clear, descriptive name so you and your team can easily identify it later.
      </InfoCard>

      {/* Schema Name Field */}
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <label htmlFor="schema-name" className="block text-sm font-medium text-slate-700">
            Schema Name <span className="text-red-500">*</span>
          </label>
          <HelpTooltip
            content={
              <div className="space-y-1">
                <p>A descriptive name for this schema.</p>
                <p className="text-xs text-slate-300">
                  Examples: "Standard Invoice", "Tax Receipt", "Purchase Order 2024"
                </p>
              </div>
            }
          />
        </div>
        <input
          id="schema-name"
          type="text"
          value={schemaData.name || ""}
          onChange={(e) => updateSchemaData({ name: e.target.value })}
          className={`w-full px-4 py-2 border rounded-lg focus:outline-none focus:ring-2 ${
            nameErrors.some(e => e.severity === "error")
              ? "border-red-300 focus:ring-red-500"
              : "border-slate-300 focus:ring-blue-500"
          }`}
          placeholder="e.g., Standard Invoice Schema"
        />
        {nameErrors.map((error, idx) => (
          <p key={idx} className={`text-sm ${error.severity === "error" ? "text-red-600" : "text-yellow-600"}`}>
            {error.message}
          </p>
        ))}
      </div>

      {/* Document Type Field */}
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <label htmlFor="document-type" className="block text-sm font-medium text-slate-700">
            Document Type <span className="text-red-500">*</span>
          </label>
          <HelpTooltip
            content={
              <div className="space-y-1">
                <p>Select the type of document this schema will process.</p>
                <p className="text-xs text-slate-300">
                  This helps the AI understand the document structure and suggest relevant fields.
                </p>
              </div>
            }
          />
        </div>
        <select
          id="document-type"
          value={schemaData.document_type}
          onChange={(e) => updateSchemaData({ document_type: e.target.value as DocumentType })}
          className={`w-full px-4 py-2 border rounded-lg focus:outline-none focus:ring-2 ${
            documentTypeErrors.some(e => e.severity === "error")
              ? "border-red-300 focus:ring-red-500"
              : "border-slate-300 focus:ring-blue-500"
          }`}
        >
          {DOCUMENT_TYPE_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label} - {option.description}
            </option>
          ))}
        </select>
        {documentTypeErrors.map((error, idx) => (
          <p key={idx} className={`text-sm ${error.severity === "error" ? "text-red-600" : "text-yellow-600"}`}>
            {error.message}
          </p>
        ))}
      </div>

      {/* Description Field */}
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <label htmlFor="description" className="block text-sm font-medium text-slate-700">
            Description
            <span className="text-slate-400 text-xs ml-2">(Recommended)</span>
          </label>
          <HelpTooltip
            content={
              <div className="space-y-1">
                <p>Explain when and how this schema should be used.</p>
                <p className="text-xs text-slate-300">
                  This helps team members understand which schema to use for different documents.
                </p>
              </div>
            }
          />
        </div>
        <textarea
          id="description"
          value={schemaData.description || ""}
          onChange={(e) => updateSchemaData({ description: e.target.value })}
          rows={4}
          className="w-full px-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          placeholder="e.g., Use this schema for processing vendor invoices from our accounting department..."
        />
        {descriptionWarnings.map((error, idx) => (
          <p key={idx} className="text-sm text-yellow-600">
            {error.message}
          </p>
        ))}
      </div>

      {/* Error Summary */}
      {hasErrors(localErrors) && (
        <InfoCard type="error">
          Please fix the errors above before continuing to the next step.
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
          disabled={hasErrors(localErrors)}
        >
          Next: Define Fields
        </Button>
      </div>
    </div>
  )
}
