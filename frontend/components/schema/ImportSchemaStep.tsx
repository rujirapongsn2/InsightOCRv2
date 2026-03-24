"use client"

import { useState, useRef } from "react"
import { Upload, FileJson, AlertCircle, Loader2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { useSchemaWizard } from "@/contexts/SchemaWizardContext"
import { getApiBaseUrl } from "@/lib/api"
import { SchemaField } from "@/types/schema"

type Tab = "upload" | "paste"

function repairTruncatedJson(text: string): string | null {
  const stack: string[] = []
  let inString = false
  let escape = false

  for (const char of text) {
    if (inString) {
      if (escape) {
        escape = false
        continue
      }
      if (char === "\\") {
        escape = true
      } else if (char === '"') {
        inString = false
      }
      continue
    }

    if (char === '"') {
      inString = true
    } else if (char === "{") {
      stack.push("}")
    } else if (char === "[") {
      stack.push("]")
    } else if (char === "}" || char === "]") {
      if (stack.length === 0 || stack.pop() !== char) {
        return null
      }
    }
  }

  if (inString || stack.length === 0) {
    return null
  }

  return text + stack.reverse().join("")
}

export function ImportSchemaStep() {
  const { resetWizard, setFields, nextStep } = useSchemaWizard()

  const [activeTab, setActiveTab] = useState<Tab>("upload")
  const [jsonText, setJsonText] = useState("")
  const [fileName, setFileName] = useState<string | null>(null)
  const [isValidating, setIsValidating] = useState(false)
  const [validationError, setValidationError] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setFileName(file.name)
    setValidationError(null)
    const reader = new FileReader()
    reader.onload = (ev) => {
      setJsonText(ev.target?.result as string)
    }
    reader.readAsText(file)
  }

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    const file = e.dataTransfer.files?.[0]
    if (!file) return
    setFileName(file.name)
    setValidationError(null)
    const reader = new FileReader()
    reader.onload = (ev) => {
      setJsonText(ev.target?.result as string)
    }
    reader.readAsText(file)
  }

  const handleValidate = async () => {
    setValidationError(null)

    // Client-side JSON parse check
    let parsedText = jsonText
    try {
      JSON.parse(parsedText)
    } catch (err) {
      const repaired = repairTruncatedJson(parsedText)
      if (!repaired) {
        setValidationError(`Invalid JSON syntax: ${(err as Error).message}`)
        return
      }

      try {
        JSON.parse(repaired)
        parsedText = repaired
      } catch (repairErr) {
        setValidationError(`Invalid JSON syntax: ${(repairErr as Error).message}`)
        return
      }
    }

    setIsValidating(true)
    try {
      const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
      const res = await fetch(`${getApiBaseUrl()}/schemas/validate-import`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ json_schema: parsedText }),
      })

      const data = await res.json()
      if (!res.ok) {
        setValidationError(data.detail || "Validation failed")
        return
      }

      setFields(data.suggested_fields as SchemaField[])
      nextStep()
    } catch (err) {
      setValidationError("Network error — could not reach the server")
    } finally {
      setIsValidating(false)
    }
  }

  const canValidate = jsonText.trim().length > 0 && !isValidating

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-slate-900">Import JSON Schema</h2>
        <p className="text-sm text-slate-600 mt-1">
          Upload a JSON Schema file or paste JSON directly. The schema will be validated and its fields imported.
        </p>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-slate-200">
        <button
          onClick={() => setActiveTab("upload")}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            activeTab === "upload"
              ? "border-purple-500 text-purple-700"
              : "border-transparent text-slate-500 hover:text-slate-700"
          }`}
        >
          Upload File
        </button>
        <button
          onClick={() => setActiveTab("paste")}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            activeTab === "paste"
              ? "border-purple-500 text-purple-700"
              : "border-transparent text-slate-500 hover:text-slate-700"
          }`}
        >
          Paste JSON
        </button>
      </div>

      {/* Upload tab */}
      {activeTab === "upload" && (
        <div className="space-y-3">
          <div
            onDrop={handleDrop}
            onDragOver={(e) => e.preventDefault()}
            onClick={() => fileInputRef.current?.click()}
            className="border-2 border-dashed border-slate-300 rounded-lg p-10 text-center cursor-pointer hover:border-purple-400 hover:bg-purple-50 transition-colors"
          >
            <FileJson className="h-10 w-10 mx-auto text-slate-400 mb-3" />
            <p className="text-slate-600 font-medium">Drop JSON file here</p>
            <p className="text-sm text-slate-400 mt-1">or click to browse (.json only)</p>
            <input
              ref={fileInputRef}
              type="file"
              accept=".json,application/json"
              onChange={handleFileChange}
              className="hidden"
            />
          </div>
          {fileName && (
            <div className="flex items-center gap-2 text-sm text-slate-600 bg-slate-50 border rounded px-3 py-2">
              <Upload className="h-4 w-4 text-slate-400" />
              <span>{fileName}</span>
            </div>
          )}
        </div>
      )}

      {/* Paste tab */}
      {activeTab === "paste" && (
        <textarea
          value={jsonText}
          onChange={(e) => {
            setJsonText(e.target.value)
            setValidationError(null)
          }}
          placeholder='Paste your JSON Schema here...\n\nExample:\n{\n  "type": "object",\n  "properties": {\n    "invoice_number": { "type": "string" }\n  }\n}'
          rows={12}
          className="w-full border border-slate-300 rounded-lg p-3 font-mono text-sm resize-y focus:outline-none focus:ring-2 focus:ring-purple-400 focus:border-transparent"
        />
      )}

      {/* Error message */}
      {validationError && (
        <div className="flex items-start gap-2 text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg px-4 py-3">
          <AlertCircle className="h-4 w-4 mt-0.5 flex-shrink-0" />
          <span>{validationError}</span>
        </div>
      )}

      {/* Actions */}
      <div className="flex justify-between pt-2">
        <Button variant="outline" onClick={resetWizard}>
          Back
        </Button>
        <Button
          onClick={handleValidate}
          disabled={!canValidate}
          className="bg-purple-600 hover:bg-purple-700 text-white"
        >
          {isValidating ? (
            <>
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              Validating...
            </>
          ) : (
            "Validate & Import →"
          )}
        </Button>
      </div>
    </div>
  )
}
