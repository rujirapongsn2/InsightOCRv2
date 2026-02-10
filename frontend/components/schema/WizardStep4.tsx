"use client"

import { CheckCircle, FileText, AlertCircle } from "lucide-react"
import { Button } from "@/components/ui/button"
import { InfoCard } from "@/components/ui/info-card"
import { useSchemaWizard } from "@/contexts/SchemaWizardContext"

const FIELD_TYPE_LABELS: Record<string, string> = {
  text: "Text",
  number: "Number",
  date: "Date",
  currency: "Currency",
  boolean: "Yes/No"
}

const DOCUMENT_TYPE_LABELS: Record<string, string> = {
  invoice: "Invoice",
  receipt: "Receipt",
  po: "Purchase Order",
  contract: "Contract",
  other: "Other"
}

export function WizardStep4() {
  const { schemaData, fields, isSaving, saveSchema, previousStep } = useSchemaWizard()

  const requiredFieldsCount = fields.filter(f => f.required).length
  const optionalFieldsCount = fields.length - requiredFieldsCount

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-slate-900">Review & Save</h2>
        <p className="text-sm text-slate-600 mt-1">
          Review your schema configuration before saving
        </p>
      </div>

      <InfoCard type="success">
        Your schema is ready to be created! Review the details below and click Save when you're ready.
      </InfoCard>

      {/* Schema Summary */}
      <div className="bg-slate-50 border border-slate-200 rounded-lg p-6 space-y-4">
        <div className="flex items-start gap-3">
          <div className="p-2 bg-blue-100 rounded-lg">
            <FileText className="h-5 w-5 text-blue-600" />
          </div>
          <div className="flex-1">
            <h3 className="font-semibold text-lg text-slate-900">{schemaData.name}</h3>
            {schemaData.description && (
              <p className="text-sm text-slate-600 mt-1">{schemaData.description}</p>
            )}
            <div className="flex items-center gap-4 mt-3 text-sm text-slate-500">
              <span className="flex items-center gap-1">
                <span className="font-medium">Type:</span>
                {DOCUMENT_TYPE_LABELS[schemaData.document_type] || schemaData.document_type}
              </span>
              <span className="flex items-center gap-1">
                <span className="font-medium">Fields:</span>
                {fields.length}
              </span>
              {requiredFieldsCount > 0 && (
                <span className="flex items-center gap-1">
                  <span className="font-medium">Required:</span>
                  {requiredFieldsCount}
                </span>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Fields Preview */}
      <div>
        <h3 className="font-medium text-slate-900 mb-3">Fields to Extract</h3>
        <div className="space-y-2">
          {fields.map((field, idx) => (
            <div
              key={field.id || idx}
              className="bg-white border border-slate-200 rounded-lg p-4 hover:border-slate-300 transition-colors"
            >
              <div className="flex items-start justify-between">
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-slate-900">{field.name}</span>
                    <span className="text-xs px-2 py-0.5 rounded bg-slate-100 text-slate-600">
                      {FIELD_TYPE_LABELS[field.type] || field.type}
                    </span>
                    {field.required && (
                      <span className="text-xs px-2 py-0.5 rounded bg-blue-100 text-blue-700 flex items-center gap-1">
                        <AlertCircle className="h-3 w-3" />
                        Required
                      </span>
                    )}
                  </div>
                  {field.description && (
                    <p className="text-sm text-slate-600 mt-1">{field.description}</p>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Testing Notice */}
      <InfoCard type="info">
        <strong>What's next?</strong> After creating this schema, you can test it by processing sample documents
        to verify the extraction works correctly.
      </InfoCard>

      {/* Save Button */}
      <div className="bg-blue-50 border border-blue-200 rounded-lg p-6">
        <div className="flex items-start gap-3">
          <CheckCircle className="h-5 w-5 text-blue-600 mt-0.5" />
          <div className="flex-1">
            <h4 className="font-medium text-blue-900">Ready to create schema</h4>
            <p className="text-sm text-blue-700 mt-1">
              Click the button below to save your schema and start using it for document processing.
            </p>
          </div>
        </div>
      </div>

      {/* Navigation Buttons */}
      <div className="flex justify-between pt-6 border-t">
        <Button
          variant="outline"
          onClick={previousStep}
          disabled={isSaving}
        >
          Previous
        </Button>
        <Button
          onClick={saveSchema}
          disabled={isSaving}
          className="min-w-[150px]"
        >
          {isSaving ? (
            <>
              <div className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-solid border-white border-r-transparent mr-2"></div>
              Saving...
            </>
          ) : (
            <>
              <CheckCircle className="h-4 w-4 mr-2" />
              Save Schema
            </>
          )}
        </Button>
      </div>
    </div>
  )
}
