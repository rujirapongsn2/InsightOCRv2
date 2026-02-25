"use client"

import { useState } from "react"
import { Upload, Loader2, FileText, AlertCircle, CheckCircle, Sparkles } from "lucide-react"
import { Button } from "@/components/ui/button"
import { InfoCard } from "@/components/ui/info-card"
import { SuggestedFieldCard } from "./SuggestedFieldCard"
import { useSchemaWizard } from "@/contexts/SchemaWizardContext"
import { SuggestedField } from "@/types/schema"
import { getApiBaseUrl } from "@/lib/api"

export function AISuggestionUpload() {
  const { schemaData, setFields, updateSchemaData, nextStep } = useSchemaWizard()
  const [file, setFile] = useState<File | null>(null)
  const [isProcessing, setIsProcessing] = useState(false)
  const [ocrContent, setOcrContent] = useState<string>("")
  const [suggestedFields, setSuggestedFields] = useState<SuggestedField[]>([])
  const [acceptedFields, setAcceptedFields] = useState<Set<string>>(new Set())
  const [error, setError] = useState<string | null>(null)
  const [confidenceScore, setConfidenceScore] = useState<number>(0)
  const [providerUsed, setProviderUsed] = useState<string>("")

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = e.target.files?.[0]
    if (selectedFile) {
      // Validate file type
      const validTypes = ["application/pdf", "image/jpeg", "image/jpg", "image/png"]
      if (!validTypes.includes(selectedFile.type)) {
        setError("Please upload a PDF, JPG, or PNG file")
        return
      }

      // Validate file size (max 50MB)
      if (selectedFile.size > 50 * 1024 * 1024) {
        setError("File size must be less than 50MB")
        return
      }

      setFile(selectedFile)
      setError(null)
      setSuggestedFields([])
      setAcceptedFields(new Set())
    }
  }

  const handleAnalyze = async () => {
    if (!file) return

    setIsProcessing(true)
    setError(null)

    try {
      const token = localStorage.getItem("token")

      // Step 1: Upload document and extract OCR
      const formData = new FormData()
      formData.append("file", file)

      const uploadRes = await fetch(
        `${getApiBaseUrl()}/documents/extract-ocr`,
        {
          method: "POST",
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          body: formData
        }
      )

      if (!uploadRes.ok) {
        let errorMessage = "Failed to upload document"
        try {
          const errorData = await uploadRes.json()
          errorMessage = errorData.detail || errorMessage
        } catch (e) {
          // Ignore json parse error and use default message
        }
        throw new Error(errorMessage)
      }

      const uploadData = await uploadRes.json()
      const extractedText = uploadData.ocr_text || uploadData.text_content || ""

      if (!extractedText) {
        throw new Error("No text could be extracted from the document")
      }

      setOcrContent(extractedText)

      // Step 2: Get AI field suggestions
      const suggestionRes = await fetch(
        `${getApiBaseUrl()}/ai-settings/suggest-fields`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(token ? { Authorization: `Bearer ${token}` } : {})
          },
          body: JSON.stringify({
            ocr_content: extractedText,
            document_type: schemaData.document_type || "other"
          })
        }
      )

      if (!suggestionRes.ok) {
        const errorData = await suggestionRes.json()
        throw new Error(errorData.detail || "Failed to get AI suggestions")
      }

      const suggestionData = await suggestionRes.json()

      setSuggestedFields(suggestionData.suggested_fields || [])
      setConfidenceScore(suggestionData.confidence_score || 0)
      setProviderUsed(suggestionData.provider_used || "AI")

      if (suggestionData.suggested_fields.length === 0) {
        setError("AI could not suggest any fields from this document. Try uploading a different document or start from scratch.")
      }
    } catch (err: any) {
      setError(err.message || "Failed to analyze document")
      setSuggestedFields([])
    } finally {
      setIsProcessing(false)
    }
  }

  const handleAcceptField = (field: SuggestedField) => {
    setAcceptedFields(prev => new Set(prev).add(field.name))
  }

  const handleRejectField = (fieldName: string) => {
    setAcceptedFields(prev => {
      const newSet = new Set(prev)
      newSet.delete(fieldName)
      return newSet
    })
  }

  const handleAcceptAll = () => {
    const allFieldNames = suggestedFields.map(f => f.name)
    setAcceptedFields(new Set(allFieldNames))
  }

  const handleRejectAll = () => {
    setAcceptedFields(new Set())
  }

  const handleContinue = () => {
    // Get accepted fields
    const fieldsToAdd = suggestedFields
      .filter(f => acceptedFields.has(f.name))
      .map(f => ({
        name: f.name,
        type: f.type,
        description: f.description,
        required: f.required,
        example: f.example_value
      }))

    // Add to wizard context
    setFields(fieldsToAdd)

    // Move to next step
    nextStep()
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-slate-900">AI-Assisted Field Suggestion</h2>
        <p className="text-sm text-slate-600 mt-1">
          Upload a sample document and let AI suggest fields automatically
        </p>
      </div>

      {/* Info Card */}
      <InfoCard type="tip">
        <strong>How it works:</strong>
        <ol className="list-decimal list-inside mt-2 space-y-1 text-sm">
          <li>Upload a sample document (PDF, JPG, or PNG)</li>
          <li>AI will extract text using OCR</li>
          <li>AI will analyze and suggest relevant fields</li>
          <li>Review, edit, and accept the suggestions you want</li>
        </ol>
      </InfoCard>

      {/* File Upload */}
      <div className="border-2 border-dashed border-slate-300 rounded-lg p-8 text-center hover:border-slate-400 transition-colors">
        <input
          type="file"
          id="document-upload"
          accept=".pdf,.jpg,.jpeg,.png"
          onChange={handleFileSelect}
          className="hidden"
          disabled={isProcessing}
        />
        <label
          htmlFor="document-upload"
          className="cursor-pointer flex flex-col items-center gap-3"
        >
          <div className="p-4 bg-blue-50 rounded-full">
            <Upload className="h-8 w-8 text-blue-600" />
          </div>
          <div>
            <p className="text-sm font-medium text-slate-900">
              {file ? file.name : "Click to upload or drag and drop"}
            </p>
            <p className="text-xs text-slate-500 mt-1">
              PDF, JPG, or PNG (max 50MB)
            </p>
          </div>
        </label>
      </div>

      {/* Analyze Button */}
      {file && !suggestedFields.length && (
        <Button
          onClick={handleAnalyze}
          disabled={isProcessing}
          className="w-full"
          size="lg"
        >
          {isProcessing ? (
            <>
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              Analyzing document...
            </>
          ) : (
            <>
              <Sparkles className="h-4 w-4 mr-2" />
              Analyze with AI
            </>
          )}
        </Button>
      )}

      {/* Error Message */}
      {error && (
        <InfoCard type="error">
          <div className="flex items-start gap-2">
            <AlertCircle className="h-4 w-4 mt-0.5 flex-shrink-0" />
            <span>{error}</span>
          </div>
        </InfoCard>
      )}

      {/* OCR Preview (collapsible) */}
      {ocrContent && (
        <details className="border rounded-lg">
          <summary className="p-3 cursor-pointer hover:bg-slate-50 flex items-center gap-2">
            <FileText className="h-4 w-4 text-slate-400" />
            <span className="text-sm font-medium">View extracted text ({ocrContent.length} characters)</span>
          </summary>
          <div className="p-4 border-t bg-slate-50">
            <pre className="text-xs text-slate-600 whitespace-pre-wrap max-h-48 overflow-auto">
              {ocrContent.substring(0, 1000)}
              {ocrContent.length > 1000 && "..."}
            </pre>
          </div>
        </details>
      )}

      {/* Suggested Fields */}
      {suggestedFields.length > 0 && (
        <div className="space-y-4">
          {/* Header with stats */}
          <div className="flex items-center justify-between">
            <div>
              <h3 className="font-medium text-slate-900">Suggested Fields ({suggestedFields.length})</h3>
              <p className="text-sm text-slate-600 mt-1">
                AI Provider: {providerUsed} | Overall Confidence: {Math.round(confidenceScore * 100)}%
              </p>
            </div>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={handleAcceptAll}
                disabled={acceptedFields.size === suggestedFields.length}
              >
                Accept All
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={handleRejectAll}
                disabled={acceptedFields.size === 0}
              >
                Clear All
              </Button>
            </div>
          </div>

          {/* Field Cards */}
          <div className="grid gap-3">
            {suggestedFields.map((field, idx) => (
              <SuggestedFieldCard
                key={`${field.name}-${idx}`}
                field={field}
                onAccept={handleAcceptField}
                onReject={handleRejectField}
                disabled={isProcessing}
                isAccepted={acceptedFields.has(field.name)}
              />
            ))}
          </div>

          {/* Summary */}
          {acceptedFields.size > 0 && (
            <InfoCard type="success">
              <div className="flex items-start gap-2">
                <CheckCircle className="h-4 w-4 mt-0.5 flex-shrink-0" />
                <div>
                  <strong>{acceptedFields.size} field{acceptedFields.size !== 1 ? "s" : ""} selected</strong>
                  <p className="text-sm mt-1">
                    Click "Continue" to proceed with these fields, or adjust your selections above.
                  </p>
                </div>
              </div>
            </InfoCard>
          )}

          {/* Continue Button */}
          <div className="flex justify-end">
            <Button
              onClick={handleContinue}
              disabled={acceptedFields.size === 0}
              size="lg"
            >
              Continue with {acceptedFields.size} field{acceptedFields.size !== 1 ? "s" : ""}
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
