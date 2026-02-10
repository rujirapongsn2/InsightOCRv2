"use client"

import { useState, useEffect } from "react"
import { X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { AISettingsPublic, AISettingsCreate, AISettingsUpdate } from "@/types/ai-settings"

interface AISettingFormProps {
  setting?: AISettingsPublic | null
  onSubmit: (data: AISettingsCreate | AISettingsUpdate) => Promise<void>
  onCancel: () => void
  isOpen: boolean
}

export function AISettingForm({ setting, onSubmit, onCancel, isOpen }: AISettingFormProps) {
  const [formData, setFormData] = useState({
    name: "",
    display_name: "",
    api_url: "",
    api_key: "",
    is_active: true,
    is_default: false,
    description: ""
  })
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const isEditMode = !!setting

  useEffect(() => {
    if (setting) {
      setFormData({
        name: setting.name,
        display_name: setting.display_name,
        api_url: setting.api_url,
        api_key: "", // Don't pre-fill API key for security
        is_active: setting.is_active,
        is_default: setting.is_default,
        description: setting.description || ""
      })
    } else {
      // Reset form for new provider
      setFormData({
        name: "",
        display_name: "",
        api_url: "",
        api_key: "",
        is_active: true,
        is_default: false,
        description: ""
      })
    }
    setError(null)
  }, [setting, isOpen])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setIsSubmitting(true)

    try {
      // Validation
      if (!isEditMode) {
        if (!formData.name.trim() || !formData.display_name.trim() || !formData.api_url.trim() || !formData.api_key.trim()) {
          throw new Error("Please fill in all required fields")
        }
      } else {
        if (!formData.display_name.trim() || !formData.api_url.trim()) {
          throw new Error("Please fill in all required fields")
        }
      }

      // Prepare data
      const submitData: any = {
        name: formData.name,
        display_name: formData.display_name,
        api_url: formData.api_url,
        is_active: formData.is_active,
        is_default: formData.is_default,
        description: formData.description || undefined
      }

      // Include API key only if provided (for create or update)
      if (formData.api_key.trim()) {
        submitData.api_key = formData.api_key
      } else if (!isEditMode) {
        throw new Error("API key is required for new providers")
      }

      await onSubmit(submitData)
      onCancel() // Close modal on success
    } catch (err: any) {
      setError(err.message || "Failed to save settings")
    } finally {
      setIsSubmitting(false)
    }
  }

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between p-6 border-b">
          <h2 className="text-xl font-semibold">
            {isEditMode ? "Edit AI Provider" : "Add AI Provider"}
          </h2>
          <button
            onClick={onCancel}
            className="text-slate-400 hover:text-slate-600"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {/* Name */}
          <div className="space-y-2">
            <label className="text-sm font-medium text-slate-700">
              Provider Name <span className="text-red-500">*</span>
            </label>
            <Input
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              placeholder="e.g., softnix_genai"
              disabled={isEditMode} // Can't change name in edit mode
              className={isEditMode ? "bg-slate-100" : ""}
            />
            <p className="text-xs text-slate-500">
              Unique identifier (lowercase, underscores only)
            </p>
          </div>

          {/* Display Name */}
          <div className="space-y-2">
            <label className="text-sm font-medium text-slate-700">
              Display Name <span className="text-red-500">*</span>
            </label>
            <Input
              value={formData.display_name}
              onChange={(e) => setFormData({ ...formData, display_name: e.target.value })}
              placeholder="e.g., Softnix GenAI"
            />
            <p className="text-xs text-slate-500">
              Human-readable name shown in UI
            </p>
          </div>

          {/* API URL */}
          <div className="space-y-2">
            <label className="text-sm font-medium text-slate-700">
              API URL <span className="text-red-500">*</span>
            </label>
            <Input
              value={formData.api_url}
              onChange={(e) => setFormData({ ...formData, api_url: e.target.value })}
              placeholder="https://api.example.com/endpoint"
            />
          </div>

          {/* API Key */}
          <div className="space-y-2">
            <label className="text-sm font-medium text-slate-700">
              API Key {!isEditMode && <span className="text-red-500">*</span>}
            </label>
            <Input
              type="password"
              value={formData.api_key}
              onChange={(e) => setFormData({ ...formData, api_key: e.target.value })}
              placeholder={isEditMode ? "Leave empty to keep existing key" : "Enter API key"}
            />
            {isEditMode && (
              <p className="text-xs text-slate-500">
                Leave empty to keep the existing API key
              </p>
            )}
          </div>

          {/* Description */}
          <div className="space-y-2">
            <label className="text-sm font-medium text-slate-700">
              Description
            </label>
            <textarea
              value={formData.description}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              placeholder="Optional description"
              rows={3}
              className="w-full px-3 py-2 border border-slate-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          {/* Checkboxes */}
          <div className="space-y-3 pt-2">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={formData.is_active}
                onChange={(e) => setFormData({ ...formData, is_active: e.target.checked })}
                className="w-4 h-4 text-blue-600 border-slate-300 rounded focus:ring-blue-500"
              />
              <span className="text-sm text-slate-700">Active (enable this provider)</span>
            </label>

            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={formData.is_default}
                onChange={(e) => setFormData({ ...formData, is_default: e.target.checked })}
                className="w-4 h-4 text-blue-600 border-slate-300 rounded focus:ring-blue-500"
              />
              <span className="text-sm text-slate-700">Set as default provider</span>
            </label>
          </div>

          {/* Error Message */}
          {error && (
            <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded text-sm">
              {error}
            </div>
          )}

          {/* Buttons */}
          <div className="flex justify-end gap-3 pt-4 border-t">
            <Button
              type="button"
              variant="outline"
              onClick={onCancel}
              disabled={isSubmitting}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? "Saving..." : isEditMode ? "Update Provider" : "Add Provider"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}
