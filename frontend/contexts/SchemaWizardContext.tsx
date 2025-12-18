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
  ValidationError,
  TestResults
} from "@/types/schema"
import { validateSchema, hasErrors } from "@/lib/schema-validation"
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
  ocr_engine: "tesseract"
}

const initialState: SchemaWizardState = {
  currentStep: 1,
  startingPoint: null,
  schemaData: initialSchemaData,
  fields: [],
  validationErrors: [],
  isSaving: false,
  testResults: undefined
}

const SchemaWizardContext = createContext<
  (SchemaWizardState & SchemaWizardActions) | undefined
>(undefined)

export function SchemaWizardProvider({ children }: { children: ReactNode }) {
  const router = useRouter()
  const [state, setState] = useState<SchemaWizardState>(initialState)

  const setCurrentStep = (step: WizardStep) => {
    setState(prev => ({ ...prev, currentStep: step }))
  }

  const setStartingPoint = (point: StartingPoint) => {
    setState(prev => ({ ...prev, startingPoint: point }))
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
    if (state.currentStep < 4) {
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
        fields: state.fields.map(({ id, ...field }) => field), // Remove temporary ID
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

      if (res.ok) {
        // Success - redirect to schemas list
        router.push("/schemas")
      } else {
        const error = await res.json()
        throw new Error(error.detail || "Failed to create schema")
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

  const value = {
    ...state,
    setCurrentStep,
    setStartingPoint,
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
    resetWizard
  }

  return (
    <SchemaWizardContext.Provider value={value}>
      {children}
    </SchemaWizardContext.Provider>
  )
}

export function useSchemaWizard() {
  const context = useContext(SchemaWizardContext)
  if (context === undefined) {
    throw new Error("useSchemaWizard must be used within a SchemaWizardProvider")
  }
  return context
}
