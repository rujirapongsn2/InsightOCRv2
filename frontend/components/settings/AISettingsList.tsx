"use client"

import { useState } from "react"
import { Pencil, Trash2, Star, StarOff, Loader2, CheckCircle, XCircle } from "lucide-react"
import { Button } from "@/components/ui/button"
import { AISettingsPublic } from "@/types/ai-settings"

interface AISettingsListProps {
  settings: AISettingsPublic[]
  onEdit: (setting: AISettingsPublic) => void
  onDelete: (id: string) => void
  onSetDefault: (id: string) => void
  onTestConnection: (name: string) => void
  isLoading?: boolean
}

export function AISettingsList({
  settings,
  onEdit,
  onDelete,
  onSetDefault,
  onTestConnection,
  isLoading = false
}: AISettingsListProps) {
  const [testingProvider, setTestingProvider] = useState<string | null>(null)
  const [testResults, setTestResults] = useState<Record<string, { success: boolean; message: string }>>({})

  const handleTest = async (name: string) => {
    setTestingProvider(name)
    setTestResults(prev => ({ ...prev, [name]: undefined as any }))

    try {
      await onTestConnection(name)
      // The result will be handled by the parent component
    } catch (error) {
      setTestResults(prev => ({
        ...prev,
        [name]: { success: false, message: "Connection failed" }
      }))
    } finally {
      setTestingProvider(null)
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
      </div>
    )
  }

  if (settings.length === 0) {
    return (
      <div className="text-center py-8 text-slate-500">
        <p>No AI providers configured yet.</p>
        <p className="text-sm mt-1">Click "Add Provider" to get started.</p>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {settings.map((setting) => (
        <div
          key={setting.id}
          className={`border rounded-lg p-4 ${
            setting.is_default ? "border-blue-300 bg-blue-50" : "border-slate-200 bg-white"
          }`}
        >
          <div className="flex items-start justify-between">
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <h3 className="font-semibold text-slate-900">{setting.display_name}</h3>
                {setting.is_default && (
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs bg-blue-100 text-blue-700">
                    <Star className="h-3 w-3 fill-current" />
                    Default
                  </span>
                )}
                {!setting.is_active && (
                  <span className="px-2 py-0.5 rounded-full text-xs bg-slate-100 text-slate-600">
                    Inactive
                  </span>
                )}
              </div>
              <p className="text-sm text-slate-600 mt-1">{setting.name}</p>
              <p className="text-xs text-slate-500 mt-1 font-mono">{setting.api_url}</p>
              {setting.description && (
                <p className="text-sm text-slate-600 mt-2">{setting.description}</p>
              )}

              {/* Test Result */}
              {testResults[setting.name] && (
                <div className={`mt-2 flex items-center gap-2 text-sm ${
                  testResults[setting.name].success ? "text-green-700" : "text-red-700"
                }`}>
                  {testResults[setting.name].success ? (
                    <CheckCircle className="h-4 w-4" />
                  ) : (
                    <XCircle className="h-4 w-4" />
                  )}
                  <span>{testResults[setting.name].message}</span>
                </div>
              )}
            </div>

            <div className="flex items-center gap-2 ml-4">
              {/* Test Connection Button */}
              <Button
                variant="outline"
                size="sm"
                onClick={() => handleTest(setting.name)}
                disabled={testingProvider === setting.name}
              >
                {testingProvider === setting.name ? (
                  <>
                    <Loader2 className="h-3 w-3 mr-1 animate-spin" />
                    Testing...
                  </>
                ) : (
                  "Test"
                )}
              </Button>

              {/* Set Default Button */}
              {!setting.is_default && setting.is_active && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => onSetDefault(setting.id)}
                  title="Set as default provider"
                >
                  <StarOff className="h-4 w-4" />
                </Button>
              )}

              {/* Edit Button */}
              <Button
                variant="ghost"
                size="sm"
                onClick={() => onEdit(setting)}
                title="Edit provider"
              >
                <Pencil className="h-4 w-4" />
              </Button>

              {/* Delete Button */}
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  if (confirm(`Are you sure you want to delete "${setting.display_name}"?`)) {
                    onDelete(setting.id)
                  }
                }}
                title="Delete provider"
                className="text-red-600 hover:text-red-700 hover:bg-red-50"
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}
