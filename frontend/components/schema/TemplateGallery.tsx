"use client"

import { useState, useEffect } from "react"
import { Template } from "@/types/schema"
import { Sparkles, FileText, FileCheck, FileClock } from "lucide-react"
import { Button } from "@/components/ui/button"

interface TemplateGalleryProps {
  onSelectTemplate: (template: Template) => void
}

const TEMPLATE_ICONS: Record<string, any> = {
  invoice: FileText,
  receipt: FileCheck,
  po: FileClock,
  contract: FileText,
}

export function TemplateGallery({ onSelectTemplate }: TemplateGalleryProps) {
  const [templates, setTemplates] = useState<Template[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [selectedCategory, setSelectedCategory] = useState<string>("all")

  useEffect(() => {
    fetchTemplates()
  }, [])

  const fetchTemplates = async () => {
    try {
      const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1"}/templates/`,
        {
          headers: {
            ...(token ? { Authorization: `Bearer ${token}` } : {})
          }
        }
      )

      if (res.ok) {
        const data = await res.json()
        setTemplates(data)
      } else {
        setError("Failed to load templates")
      }
    } catch (err) {
      console.error("Error fetching templates:", err)
      setError("Failed to load templates")
    } finally {
      setLoading(false)
    }
  }

  const categories = ["all", ...new Set(templates.map(t => t.category))]

  const filteredTemplates = selectedCategory === "all"
    ? templates
    : templates.filter(t => t.category === selectedCategory)

  if (loading) {
    return (
      <div className="text-center py-12">
        <div className="inline-block h-8 w-8 animate-spin rounded-full border-4 border-solid border-blue-600 border-r-transparent"></div>
        <p className="text-sm text-slate-500 mt-3">Loading templates...</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="text-center py-12">
        <p className="text-red-600">{error}</p>
        <Button onClick={fetchTemplates} variant="outline" className="mt-4">
          Try Again
        </Button>
      </div>
    )
  }

  if (templates.length === 0) {
    return (
      <div className="text-center py-12">
        <p className="text-slate-500">No templates available</p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Category Filter */}
      <div className="flex gap-2 flex-wrap">
        {categories.map(category => (
          <button
            key={category}
            onClick={() => setSelectedCategory(category)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              selectedCategory === category
                ? "bg-blue-600 text-white"
                : "bg-slate-100 text-slate-700 hover:bg-slate-200"
            }`}
          >
            {category.charAt(0).toUpperCase() + category.slice(1)}
          </button>
        ))}
      </div>

      {/* Template Grid */}
      <div className="grid md:grid-cols-2 gap-4">
        {filteredTemplates.map((template) => {
          const Icon = TEMPLATE_ICONS[template.document_type] || FileText

          return (
            <div
              key={template.id}
              className="border rounded-lg p-6 hover:border-blue-300 hover:shadow-md transition-all cursor-pointer bg-white"
              onClick={() => onSelectTemplate(template)}
            >
              <div className="flex items-start gap-4">
                <div className="p-3 bg-blue-50 rounded-lg">
                  <Icon className="h-6 w-6 text-blue-600" />
                </div>

                <div className="flex-1 min-w-0">
                  <div className="flex items-start justify-between gap-2">
                    <h3 className="font-semibold text-slate-900">
                      {template.name}
                    </h3>
                    {template.is_system_template && (
                      <span className="inline-flex items-center px-2 py-1 rounded text-xs font-medium bg-green-100 text-green-800 flex-shrink-0">
                        <Sparkles className="h-3 w-3 mr-1" />
                        System
                      </span>
                    )}
                  </div>

                  <p className="text-sm text-slate-600 mt-1 line-clamp-2">
                    {template.description}
                  </p>

                  <div className="flex items-center gap-4 mt-3 text-xs text-slate-500">
                    <span>{template.fields.length} fields</span>
                    {template.usage_count > 0 && (
                      <span>Used {template.usage_count}x</span>
                    )}
                    <span className="capitalize">{template.category}</span>
                  </div>

                  <Button
                    size="sm"
                    className="mt-4 w-full"
                    onClick={(e) => {
                      e.stopPropagation()
                      onSelectTemplate(template)
                    }}
                  >
                    Use Template
                  </Button>
                </div>
              </div>
            </div>
          )
        })}
      </div>

      {filteredTemplates.length === 0 && (
        <div className="text-center py-12">
          <p className="text-slate-500">No templates in this category</p>
        </div>
      )}
    </div>
  )
}
