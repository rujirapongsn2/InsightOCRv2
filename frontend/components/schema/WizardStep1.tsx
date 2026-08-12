"use client"

import { FileJson, ScanText } from "lucide-react"
import { useSchemaWizard } from "@/contexts/SchemaWizardContext"

export function WizardStep1() {
  const { setStartingPoint, setCurrentStep } = useSchemaWizard()

  const handleSelect = (mode: "ai" | "import") => {
    setCurrentStep(1)
    setStartingPoint(mode)
  }

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-xl font-semibold text-slate-900">Create Schema</h2>
      </div>

      <div className="grid gap-3">
        {/* AI-Assisted */}
        <button
          onClick={() => handleSelect("ai")}
          className="relative text-left border rounded-lg p-5 transition-colors border-blue-200 bg-blue-50 hover:border-blue-400"
        >
          <div className="absolute top-4 right-4">
              <span className="inline-flex items-center px-2 py-1 rounded text-xs font-medium bg-blue-100 text-blue-700">
                Suggested
            </span>
          </div>
          <div className="flex items-start gap-4">
            <div className="p-2 rounded-md bg-blue-100">
              <ScanText className="h-5 w-5 text-blue-700" />
            </div>
            <div className="flex-1">
              <h3 className="font-semibold text-slate-900">Upload sample document</h3>
              <p className="text-sm text-slate-600 mt-1">Generate editable fields from a PDF or image.</p>
            </div>
          </div>
        </button>

        {/* Import Schema */}
        <button
          onClick={() => handleSelect("import")}
          className="relative text-left border rounded-lg p-5 transition-colors border-slate-200 bg-white hover:border-slate-400"
        >
          <div className="flex items-start gap-4">
            <div className="p-2 rounded-md bg-slate-100">
              <FileJson className="h-5 w-5 text-slate-600" />
            </div>
            <div className="flex-1">
              <h3 className="font-semibold text-slate-900">Import JSON schema</h3>
              <p className="text-sm text-slate-600 mt-1">Upload or paste an existing JSON schema.</p>
            </div>
          </div>
        </button>
      </div>
    </div>
  )
}
