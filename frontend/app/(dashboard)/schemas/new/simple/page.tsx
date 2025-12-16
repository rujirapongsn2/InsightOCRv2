"use client"

import { SchemaWizardProvider } from "@/contexts/SchemaWizardContext"
import { SchemaWizard } from "@/components/schema/SchemaWizard"

export default function SimpleWizardPage() {
  return (
    <SchemaWizardProvider>
      <SchemaWizard />
    </SchemaWizardProvider>
  )
}
