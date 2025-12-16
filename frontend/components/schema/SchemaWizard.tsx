"use client"

import { ArrowLeft } from "lucide-react"
import Link from "next/link"
import { Button } from "@/components/ui/button"
import { Stepper } from "@/components/ui/stepper"
import { useSchemaWizard } from "@/contexts/SchemaWizardContext"
import { WizardStep1 } from "./WizardStep1"
import { WizardStep2 } from "./WizardStep2"
import { WizardStep3 } from "./WizardStep3"
import { WizardStep4 } from "./WizardStep4"

export function SchemaWizard() {
  const { currentStep, previousStep } = useSchemaWizard()

  const steps = [
    { number: 1 as const, title: "Start", description: "Choose how to begin" },
    { number: 2 as const, title: "Details", description: "Schema information" },
    { number: 3 as const, title: "Fields", description: "Define fields" },
    { number: 4 as const, title: "Review", description: "Preview & test" }
  ]

  return (
    <div className="max-w-6xl mx-auto p-8 space-y-8">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Link href="/schemas/new">
          <Button variant="ghost" size="icon">
            <ArrowLeft className="h-4 w-4" />
          </Button>
        </Link>
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Create New Schema</h1>
          <p className="text-slate-500">Simple Mode - Guided wizard</p>
        </div>
      </div>

      {/* Progress Stepper */}
      <Stepper
        steps={steps}
        currentStep={currentStep}
        completedSteps={Array.from({ length: currentStep - 1 }, (_, i) => (i + 1) as any)}
      />

      {/* Wizard Content */}
      <div className="bg-white border rounded-lg p-8 min-h-[500px]">
        {currentStep === 1 && <WizardStep1 />}
        {currentStep === 2 && <WizardStep2 />}
        {currentStep === 3 && <WizardStep3 />}
        {currentStep === 4 && <WizardStep4 />}
      </div>
    </div>
  )
}
