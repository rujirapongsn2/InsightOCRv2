"use client"

import { createContext, useContext, useState, ReactNode } from "react"
import { useRouter } from "next/navigation"
import {
  SchemaWizardState,
  SchemaWizardActions,
  WizardStep,
  StartingPoint,
  SchemaData,
  SchemaField,
  StudioSession,
} from "@/types/schema"
import { validateSchema, hasErrors } from "@/lib/schema-validation"
import { toSchemaPayloadField } from "@/lib/schema-studio"
import { getApiBaseUrl } from "@/lib/api"

// Helper function to generate unique IDs
const generateId = () => {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return crypto.randomUUID()
  }
  // Fallback for older browsers
  return `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`
}

const initialSchemaData: SchemaData = {
  name: "",
  description: "",
  document_type: "invoice",
  ocr_engine: "tesseract",
  extraction_profile: "anydoc_hybrid"
}

const initialState: SchemaWizardState = {
  currentStep: 1,
  startingPoint: null,
  manualEntry: false,
  schemaData: initialSchemaData,
  fields: [],
  validationErrors: [],
  isSaving: false,
  testResults: undefined,
  studio: null
}

const SchemaWizardContext = createContext<
  (SchemaWizardState & SchemaWizardActions) | undefined
>(undefined)

export function SchemaWizardProvider({ children, onSaved }: { children: ReactNode; onSaved?: () => void }) {
  const router = useRouter()
  const [state, setState] = useState<SchemaWizardState>(initialState)

  const setCurrentStep = (step: WizardStep) => {
    setState(prev => ({ ...prev, currentStep: step }))
  }

  const setStartingPoint = (point: StartingPoint) => {
    setState(prev => ({ ...prev, startingPoint: point, manualEntry: false }))
  }

  const setManualEntry = (enabled: boolean) => {
    setState(prev => ({ ...prev, manualEntry: enabled, currentStep: 1 }))
  }

  const updateSchemaData = (data: Partial<SchemaData>) => {
    setState(prev => ({
      ...prev,
      schemaData: { ...prev.schemaData, ...data }
    }))
  }

  const addField = (field: SchemaField) => {
    const newField = {
      ...field,
      id: field.id || generateId(),
      order: field.order || state.fields.length
    }
    setState(prev => ({
      ...prev,
      fields: [...prev.fields, newField]
    }))
  }

  const updateField = (id: string, updates: Partial<SchemaField>) => {
    setState(prev => ({
      ...prev,
      fields: prev.fields.map(field =>
        field.id === id ? { ...field, ...updates } : field
      )
    }))
  }

  const removeField = (id: string) => {
    setState(prev => ({
      ...prev,
      fields: prev.fields.filter(field => field.id !== id)
    }))
  }

  const reorderFields = (startIndex: number, endIndex: number) => {
    setState(prev => {
      const result = Array.from(prev.fields)
      const [removed] = result.splice(startIndex, 1)
      result.splice(endIndex, 0, removed)

      // Update order property
      return {
        ...prev,
        fields: result.map((field, index) => ({
          ...field,
          order: index
        }))
      }
    })
  }

  const setFields = (fields: SchemaField[]) => {
    setState(prev => ({
      ...prev,
      fields: fields.map((field, index) => ({
        ...field,
        id: field.id || generateId(),
        order: index
      }))
    }))
  }

  const validateCurrentStep = (): boolean => {
    const errors = validateSchema(state.schemaData, state.fields)
    setState(prev => ({ ...prev, validationErrors: errors }))
    return !hasErrors(errors)
  }

  const nextStep = () => {
    if (state.currentStep < 2) {
      setState(prev => ({ ...prev, currentStep: (prev.currentStep + 1) as WizardStep }))
    }
  }

  const previousStep = () => {
    if (state.currentStep > 1) {
      setState(prev => ({ ...prev, currentStep: (prev.currentStep - 1) as WizardStep }))
    }
  }

  const saveSchema = async () => {
    setState(prev => ({ ...prev, isSaving: true }))

    try {
      // Validate before saving
      if (!validateCurrentStep()) {
        setState(prev => ({ ...prev, isSaving: false }))
        return
      }

      const token = typeof window !== "undefined" ? localStorage.getItem("token") : null

      const payload = {
        name: state.schemaData.name,
        description: state.schemaData.description,
        document_type: state.schemaData.document_type,
        ocr_engine: state.schemaData.ocr_engine || "tesseract",
        extraction_profile: "anydoc_hybrid",
        fields: state.fields.map(toSchemaPayloadField),
        template_id: state.schemaData.template_id
      }

      const res = await fetch(
        `${getApiBaseUrl()}/schemas/`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(token ? { Authorization: `Bearer ${token}` } : {})
          },
          body: JSON.stringify(payload)
        }
      )

      if (!res.ok) {
        const error = await res.json()
        throw new Error(typeof error.detail === "string" ? error.detail : "Failed to create schema")
      }
      const created = await res.json()
      const studio = state.studio
      if (studio?.keepSamples && studio.files.length) {
        const kept = await storeTestSet(created.id, studio, state.fields, token)
        if (!kept) {
          alert("The schema was saved, but the sample files could not be kept as its test set. You can add them later from the schema page.")
        }
      }
      if (onSaved) {
        onSaved()
      } else {
        router.push("/schemas")
      }
    } catch (error) {
      console.error("Error creating schema:", error)
      alert(error instanceof Error ? error.message : "Failed to create schema")
    } finally {
      setState(prev => ({ ...prev, isSaving: false }))
    }
  }

  const testSchema = async (file: File) => {
    // TODO: Implement test extraction
    // This will be implemented in Phase 1 - Week 3 (AI Features)
    console.log("Test schema with file:", file.name)
  }

  const resetWizard = () => {
    setState(initialState)
  }

  const setStudio = (studio: StudioSession | null) => {
    setState(prev => ({ ...prev, studio }))
  }

  const updateStudio = (updates: Partial<StudioSession>) => {
    setState(prev => (prev.studio ? { ...prev, studio: { ...prev.studio, ...updates } } : prev))
  }

  const value = {
    ...state,
    setCurrentStep,
    setStartingPoint,
    setManualEntry,
    updateSchemaData,
    addField,
    updateField,
    removeField,
    reorderFields,
    setFields,
    validateCurrentStep,
    nextStep,
    previousStep,
    saveSchema,
    testSchema,
    resetWizard,
    setStudio,
    updateStudio
  }

  return (
    <SchemaWizardContext.Provider value={value}>
      {children}
    </SchemaWizardContext.Provider>
  )
}

async function storeTestSet(schemaId: string, studio: StudioSession, fields: SchemaField[], token: string | null): Promise<boolean> {
  const form = new FormData()
  studio.files.forEach((file) => form.append("files", file))
  // Confirmations are keyed by field id; send them under the fields' final names.
  const byName = studio.files.map((_, index) => {
    const confirmed = studio.expected[index] || {}
    return Object.fromEntries(fields
      .filter((field) => field.id && confirmed[field.id] !== undefined)
      .map((field) => [field.name, confirmed[field.id!]]))
  })
  form.append("expected", JSON.stringify(byName))
  if (studio.sessionId) form.append("session_id", studio.sessionId)
  form.append("consent", "true")
  try {
    const res = await fetch(`${getApiBaseUrl()}/schemas/${schemaId}/samples`, {
      method: "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: form,
    })
    return res.ok
  } catch {
    return false
  }
}

export function useSchemaWizard() {
  const context = useContext(SchemaWizardContext)
  if (context === undefined) {
    throw new Error("useSchemaWizard must be used within a SchemaWizardProvider")
  }
  return context
}
