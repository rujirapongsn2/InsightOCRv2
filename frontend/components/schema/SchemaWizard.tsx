"use client"

import { ArrowLeft } from "lucide-react"
import Link from "next/link"
import { Button } from "@/components/ui/button"
import { Stepper } from "@/components/ui/stepper"
import { useSchemaWizard } from "@/contexts/SchemaWizardContext"
import { WizardStep1 } from "./WizardStep1"
import { AIFieldsStep } from "./AIFieldsStep"
import { ImportSchemaStep } from "./ImportSchemaStep"
import { DetailsAndSaveStep } from "./DetailsAndSaveStep"

export function SchemaWizard({ embedded = false }: { embedded?: boolean }) {
  const { currentStep, previousStep, startingPoint } = useSchemaWizard()

  // We only show the stepper and content after a starting point is chosen
  const showStepper = startingPoint !== null

  const steps = [
    { number: 1 as const, title: "Fields", description: "Generate and edit fields" },
    { number: 2 as const, title: "Save", description: "Name and save schema" },
  ]

  return (
    <div className="max-w-4xl mx-auto p-8 space-y-8">
      {/* Header — hidden when embedded inside a modal */}
      {!embedded && (
        <div className="flex items-center gap-4">
          <Link href="/schemas/new">
            <Button variant="ghost" size="icon">
              <ArrowLeft className="h-4 w-4" />
            </Button>
          </Link>
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Create New Schema</h1>
            <p className="text-slate-500 text-sm">
              {startingPoint === "ai" ? "AI-Assisted Mode" :
                startingPoint === "import" ? "Import Schema Mode" :
                  startingPoint === "scratch" ? "Manual Mode" :
                    startingPoint === "template" ? "From Template" :
                      "Simple Mode — Choose a starting method"}
            </p>
          </div>
        </div>
      )}

      {/* Progress Stepper — only show after mode is selected */}
      {showStepper && (
        <Stepper
          steps={steps}
          currentStep={currentStep}
          completedSteps={Array.from({ length: currentStep - 1 }, (_, i) => (i + 1) as any)}
        />
      )}

      {/* Wizard Content */}
      <div className="bg-white border rounded-lg p-8 min-h-[400px]">
        {/* Mode Selection (before any startingPoint is chosen) */}
        {startingPoint === null && <WizardStep1 />}

        {/* Step 1: Fields (AI upload + field list) */}
        {startingPoint === "ai" && currentStep === 1 && <AIFieldsStep />}

        {/* Step 1: Import Schema (upload file / paste JSON) */}
        {startingPoint === "import" && currentStep === 1 && <ImportSchemaStep />}

        {/* Step 2: Name + Save */}
        {startingPoint !== null && currentStep === 2 && <DetailsAndSaveStep />}
      </div>
    </div>
  )
}
