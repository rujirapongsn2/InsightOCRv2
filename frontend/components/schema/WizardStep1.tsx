"use client"

import { Wand2, FileJson } from "lucide-react"
import { InfoCard } from "@/components/ui/info-card"
import { useSchemaWizard } from "@/contexts/SchemaWizardContext"

export function WizardStep1() {
  const { setStartingPoint, setCurrentStep } = useSchemaWizard()

  const handleSelect = (mode: "ai" | "import") => {
    setCurrentStep(1)
    setStartingPoint(mode)
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-slate-900">Choose How to Create Schema</h2>
        <p className="text-sm text-slate-600 mt-1">Pick the starting method that fits your workflow.</p>
      </div>

      <InfoCard type="tip" dismissible>
        <strong>Tip:</strong> Use AI-Assisted mode — upload a document and AI will suggest schema fields automatically.
      </InfoCard>

      <div className="grid gap-4">
        {/* AI-Assisted */}
        <button
          onClick={() => handleSelect("ai")}
          className="relative text-left border-2 rounded-lg p-6 transition-all border-purple-200 bg-purple-50 hover:border-purple-300 hover:shadow-md"
        >
          <div className="absolute top-4 right-4">
            <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-medium bg-green-100 text-green-800">
              Recommended
            </span>
          </div>
          <div className="flex items-start gap-4">
            <div className="p-3 rounded-lg bg-purple-100">
              <Wand2 className="h-6 w-6 text-purple-600" />
            </div>
            <div className="flex-1">
              <h3 className="font-semibold text-slate-900 text-lg">AI-Assisted</h3>
              <p className="text-slate-600 mt-1">Upload a sample document and let AI generate schema fields automatically</p>
            </div>
          </div>
        </button>

        {/* Import Schema */}
        <button
          onClick={() => handleSelect("import")}
          className="relative text-left border-2 rounded-lg p-6 transition-all border-slate-200 bg-white hover:border-slate-300 hover:shadow-md"
        >
          <div className="flex items-start gap-4">
            <div className="p-3 rounded-lg bg-slate-100">
              <FileJson className="h-6 w-6 text-slate-600" />
            </div>
            <div className="flex-1">
              <h3 className="font-semibold text-slate-900 text-lg">Import Schema</h3>
              <p className="text-slate-600 mt-1">Upload a JSON Schema file or paste JSON to import and validate</p>
            </div>
          </div>
        </button>
      </div>
    </div>
  )
}
