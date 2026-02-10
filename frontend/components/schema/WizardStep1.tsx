"use client"

import { useState } from "react"
import { Sparkles, FileText, Wand2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { InfoCard } from "@/components/ui/info-card"
import { TemplateGallery } from "./TemplateGallery"
import { AISuggestionUpload } from "./AISuggestionUpload"
import { useSchemaWizard } from "@/contexts/SchemaWizardContext"
import { Template, StartingPoint } from "@/types/schema"
import { getApiBaseUrl } from "@/lib/api"

export function WizardStep1() {
  const { setStartingPoint, setFields, updateSchemaData, nextStep } = useSchemaWizard()
  const [selectedOption, setSelectedOption] = useState<StartingPoint | null>(null)

  const handleTemplateSelect = async (template: Template) => {
    // Set fields from template
    setFields(template.fields)

    // Set template_id in schema data
    updateSchemaData({
      template_id: template.id,
      document_type: template.document_type,
      description: template.description
    })

    // Track template usage
    try {
      const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
      await fetch(
        `${getApiBaseUrl()}/templates/${template.id}/use`,
        {
          method: "POST",
          headers: {
            ...(token ? { Authorization: `Bearer ${token}` } : {})
          }
        }
      )
    } catch (err) {
      console.error("Failed to track template usage:", err)
    }

    // Set starting point and go to next step
    setStartingPoint("template")
    nextStep()
  }

  const handleStartFromScratch = () => {
    setStartingPoint("scratch")
    setFields([])
    nextStep()
  }

  const handleAIAssisted = () => {
    setStartingPoint("ai")
    setSelectedOption("ai")
  }

  const options = [
    {
      id: "template" as StartingPoint,
      icon: Sparkles,
      title: "Start from Template",
      description: "Choose from pre-built templates for common document types",
      recommended: true,
      color: "blue",
      available: true
    },
    {
      id: "ai" as StartingPoint,
      icon: Wand2,
      title: "AI-Assisted",
      description: "Upload a sample document and let AI suggest fields",
      recommended: false,
      color: "purple",
      available: true // Now available!
    },
    {
      id: "scratch" as StartingPoint,
      icon: FileText,
      title: "Start from Scratch",
      description: "Manually create your schema with guided help",
      recommended: false,
      color: "slate",
      available: true
    }
  ]

  if (selectedOption === "template") {
    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-xl font-semibold text-slate-900">Choose a Template</h2>
            <p className="text-sm text-slate-600 mt-1">
              Select a pre-built template to get started quickly
            </p>
          </div>
          <Button
            variant="outline"
            onClick={() => setSelectedOption(null)}
          >
            Back to Options
          </Button>
        </div>

        <TemplateGallery onSelectTemplate={handleTemplateSelect} />
      </div>
    )
  }

  if (selectedOption === "ai") {
    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <Button
            variant="outline"
            onClick={() => setSelectedOption(null)}
          >
            Back to Options
          </Button>
        </div>

        <AISuggestionUpload />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-slate-900">How would you like to start?</h2>
        <p className="text-sm text-slate-600 mt-1">
          Choose the method that works best for you
        </p>
      </div>

      <InfoCard type="tip" dismissible>
        <strong>New to schema creation?</strong> We recommend starting with a template.
        You can customize it to fit your exact needs.
      </InfoCard>

      <div className="grid gap-4">
        {options.map((option) => {
          const Icon = option.icon
          const isDisabled = !option.available

          return (
            <button
              key={option.id}
              onClick={() => {
                if (option.id === "template") {
                  setSelectedOption("template")
                } else if (option.id === "scratch") {
                  handleStartFromScratch()
                } else if (option.id === "ai") {
                  handleAIAssisted()
                }
              }}
              disabled={isDisabled}
              className={`relative text-left border-2 rounded-lg p-6 transition-all ${
                isDisabled
                  ? "border-slate-200 bg-slate-50 cursor-not-allowed opacity-60"
                  : option.color === "blue"
                  ? "border-blue-200 bg-blue-50 hover:border-blue-300 hover:shadow-md"
                  : option.color === "purple"
                  ? "border-purple-200 bg-purple-50 hover:border-purple-300 hover:shadow-md"
                  : "border-slate-200 bg-white hover:border-slate-300 hover:shadow-md"
              }`}
            >
              {option.recommended && (
                <div className="absolute top-4 right-4">
                  <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-medium bg-green-100 text-green-800">
                    Recommended
                  </span>
                </div>
              )}

              {isDisabled && (
                <div className="absolute top-4 right-4">
                  <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-medium bg-slate-200 text-slate-600">
                    Coming Soon
                  </span>
                </div>
              )}

              <div className="flex items-start gap-4">
                <div className={`p-3 rounded-lg ${
                  option.color === "blue" ? "bg-blue-100" :
                  option.color === "purple" ? "bg-purple-100" :
                  "bg-slate-100"
                }`}>
                  <Icon className={`h-6 w-6 ${
                    option.color === "blue" ? "text-blue-600" :
                    option.color === "purple" ? "text-purple-600" :
                    "text-slate-600"
                  }`} />
                </div>

                <div className="flex-1">
                  <h3 className="font-semibold text-slate-900 text-lg">
                    {option.title}
                  </h3>
                  <p className="text-slate-600 mt-1">
                    {option.description}
                  </p>
                </div>
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}
