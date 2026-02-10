"use client"

import { useState, useEffect } from "react"
import { Plus, RefreshCw } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { AISettingsList } from "./AISettingsList"
import { AISettingForm } from "./AISettingForm"
import { AISettingsPublic, AISettingsCreate, AISettingsUpdate } from "@/types/ai-settings"
import { getApiBaseUrl } from "@/lib/api"

export function AISettingsCard() {
  const [settings, setSettings] = useState<AISettingsPublic[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [isFormOpen, setIsFormOpen] = useState(false)
  const [editingSetting, setEditingSetting] = useState<AISettingsPublic | null>(null)
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null)

  useEffect(() => {
    fetchSettings()
  }, [])

  const fetchSettings = async () => {
    setIsLoading(true)
    try {
      const token = localStorage.getItem("token")
      const res = await fetch(
        `${getApiBaseUrl()}/ai-settings/`,
        {
          headers: token ? { Authorization: `Bearer ${token}` } : {}
        }
      )

      if (res.ok) {
        const data = await res.json()
        setSettings(data)
      } else {
        throw new Error("Failed to fetch AI settings")
      }
    } catch (error: any) {
      showMessage("error", error.message || "Failed to load AI providers")
    } finally {
      setIsLoading(false)
    }
  }

  const showMessage = (type: "success" | "error", text: string) => {
    setMessage({ type, text })
    setTimeout(() => setMessage(null), 5000)
  }

  const handleAdd = () => {
    setEditingSetting(null)
    setIsFormOpen(true)
  }

  const handleEdit = (setting: AISettingsPublic) => {
    setEditingSetting(setting)
    setIsFormOpen(true)
  }

  const handleSubmit = async (data: AISettingsCreate | AISettingsUpdate) => {
    const token = localStorage.getItem("token")
    const url = `${getApiBaseUrl()}/ai-settings/${
      editingSetting ? editingSetting.id : ""
    }`

    try {
      const res = await fetch(url, {
        method: editingSetting ? "PUT" : "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {})
        },
        body: JSON.stringify(data)
      })

      if (!res.ok) {
        const errorData = await res.json()
        throw new Error(errorData.detail || "Failed to save provider")
      }

      showMessage("success", `Provider ${editingSetting ? "updated" : "added"} successfully`)
      fetchSettings() // Refresh list
      setIsFormOpen(false)
      setEditingSetting(null)
    } catch (error: any) {
      throw error // Let form handle the error
    }
  }

  const handleDelete = async (id: string) => {
    const token = localStorage.getItem("token")

    try {
      const res = await fetch(
        `${getApiBaseUrl()}/ai-settings/${id}`,
        {
          method: "DELETE",
          headers: token ? { Authorization: `Bearer ${token}` } : {}
        }
      )

      if (!res.ok) {
        throw new Error("Failed to delete provider")
      }

      showMessage("success", "Provider deleted successfully")
      fetchSettings()
    } catch (error: any) {
      showMessage("error", error.message || "Failed to delete provider")
    }
  }

  const handleSetDefault = async (id: string) => {
    const token = localStorage.getItem("token")

    try {
      const res = await fetch(
        `${getApiBaseUrl()}/ai-settings/${id}/set-default`,
        {
          method: "POST",
          headers: token ? { Authorization: `Bearer ${token}` } : {}
        }
      )

      if (!res.ok) {
        throw new Error("Failed to set default provider")
      }

      showMessage("success", "Default provider updated")
      fetchSettings()
    } catch (error: any) {
      showMessage("error", error.message || "Failed to set default provider")
    }
  }

  const handleTestConnection = async (providerName: string) => {
    const token = localStorage.getItem("token")

    try {
      const res = await fetch(
        `${getApiBaseUrl()}/ai-settings/test-connection`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(token ? { Authorization: `Bearer ${token}` } : {})
          },
          body: JSON.stringify({ provider_name: providerName })
        }
      )

      const data = await res.json()

      if (res.ok) {
        showMessage("success", `Connection test successful: ${data.message}`)
      } else {
        showMessage("error", `Connection test failed: ${data.detail || data.message}`)
      }
    } catch (error: any) {
      showMessage("error", `Connection test failed: ${error.message}`)
    }
  }

  return (
    <>
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>AI Field Suggestion</CardTitle>
              <p className="text-sm text-slate-600 mt-1">
                Configure AI providers for automatic field suggestions
              </p>
            </div>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={fetchSettings}
                disabled={isLoading}
              >
                <RefreshCw className={`h-4 w-4 ${isLoading ? "animate-spin" : ""}`} />
              </Button>
              <Button size="sm" onClick={handleAdd}>
                <Plus className="h-4 w-4 mr-1" />
                Add Provider
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {/* Success/Error Message */}
          {message && (
            <div
              className={`mb-4 p-3 rounded-md text-sm ${
                message.type === "success"
                  ? "bg-green-50 text-green-700 border border-green-200"
                  : "bg-red-50 text-red-700 border border-red-200"
              }`}
            >
              {message.text}
            </div>
          )}

          {/* AI Settings List */}
          <AISettingsList
            settings={settings}
            onEdit={handleEdit}
            onDelete={handleDelete}
            onSetDefault={handleSetDefault}
            onTestConnection={handleTestConnection}
            isLoading={isLoading}
          />
        </CardContent>
      </Card>

      {/* Add/Edit Form Modal */}
      <AISettingForm
        setting={editingSetting}
        onSubmit={handleSubmit}
        onCancel={() => {
          setIsFormOpen(false)
          setEditingSetting(null)
        }}
        isOpen={isFormOpen}
      />
    </>
  )
}
