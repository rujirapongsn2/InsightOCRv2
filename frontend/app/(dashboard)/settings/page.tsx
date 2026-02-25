"use client"

import { useEffect, useMemo, useState } from "react"
import { useAuth } from "@/components/auth-provider"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { AlertCircle, CheckCircle2, Eye, EyeOff, Loader2 } from "lucide-react"
import { getApiBaseUrl } from "@/lib/api"

export default function SettingsPage() {
  const { user } = useAuth()
  const normalizedRole = useMemo(() => {
    if (!user?.role) return "user"
    return user.role === "documents_admin" ? "manager" : user.role
  }, [user?.role])

  // Separate endpoints for different purposes
  const [ocrEndpoint, setOcrEndpoint] = useState("")
  const [structuredOutputEndpoint, setStructuredOutputEndpoint] = useState("")
  const [schemaSuggestionEndpoint, setSchemaSuggestionEndpoint] = useState("")
  const [testEndpoint, setTestEndpoint] = useState("")
  const [token, setToken] = useState("")
  const [showToken, setShowToken] = useState(false)
  const [isLoadingConfig, setIsLoadingConfig] = useState(true)
  const [ocrEngine, setOcrEngine] = useState("default")
  const [model, setModel] = useState("default")
  const [result, setResult] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    const fetchConfig = async () => {
      try {
        const authToken = typeof window !== "undefined" ? localStorage.getItem("token") : null
        const res = await fetch(`${getApiBaseUrl()}/settings/config`, {
          headers: authToken ? { Authorization: `Bearer ${authToken}` } : undefined,
        })
        if (res.ok) {
          const data = await res.json()
          // Show 'default' in UI if empty string is stored
          setOcrEngine(data.ocr_engine || 'default')
          setModel(data.model || 'default')
          setOcrEndpoint(data.ocr_endpoint ?? "")
          setStructuredOutputEndpoint(data.structured_output_endpoint ?? "")
          setSchemaSuggestionEndpoint(data.schema_suggestion_endpoint ?? "")
          setTestEndpoint(data.test_endpoint ?? "")
          setToken(data.api_token ?? "")
        }
      } catch (err) {
        console.error("Failed to load settings", err)
      } finally {
        setIsLoadingConfig(false)
      }
    }
    fetchConfig()
  }, [])

  const handleSaveBackend = async () => {
    setResult(null)
    setError(null)
    try {
      const authToken = typeof window !== "undefined" ? localStorage.getItem("token") : null

      // Convert 'default' to empty string for OCR engine and model
      const finalOcrEngine = ocrEngine === 'default' ? '' : ocrEngine
      const finalModel = model === 'default' ? '' : model

      const res = await fetch(`${getApiBaseUrl()}/settings/config`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {})
        },
        body: JSON.stringify({
          ocr_engine: finalOcrEngine,
          model: finalModel,
          ocr_endpoint: ocrEndpoint,
          structured_output_endpoint: structuredOutputEndpoint,
          schema_suggestion_endpoint: schemaSuggestionEndpoint,
          test_endpoint: testEndpoint,
          api_token: token,
          verify_ssl: false
        })
      })
      const data = await res.json()
      if (res.ok) {
        setResult("Settings saved to backend.")
      } else {
        setError(data.detail || "Failed to save settings.")
      }
    } catch (err: any) {
      setError(`Error: ${err?.message || err}`)
    }
  }

  const handleTest = async () => {
    setLoading(true)
    setResult(null)
    setError(null)
    try {
      const authToken = typeof window !== "undefined" ? localStorage.getItem("token") : null
      const res = await fetch(`${getApiBaseUrl()}/settings/test`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {})
        },
        body: JSON.stringify({ url: testEndpoint, token })
      })
      const data = await res.json()
      if (res.ok) {
        setResult(`Success (${data.status_code}): ${data.body}`)
      } else {
        setError(data.detail || `Failed (${data.status_code || res.status})`)
      }
    } catch (err: any) {
      setError(`Error: ${err?.message || err}`)
    } finally {
      setLoading(false)
    }
  }

  if (normalizedRole !== "admin") {
    return (
      <div className="bg-white rounded-lg border shadow-sm p-6">
        <h2 className="text-xl font-semibold text-slate-900">Access restricted</h2>
        <p className="text-slate-600 mt-2">Settings are available to Admin only.</p>
      </div>
    )
  }

  return (
    <div className="max-w-3xl space-y-6">
      <div className="space-y-2">
        <h2 className="text-2xl font-bold tracking-tight">Settings</h2>
        <p className="text-slate-600">Configure and test external API endpoint.</p>
      </div>

      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <CardTitle>External API Configuration</CardTitle>
            {isLoadingConfig && <Loader2 className="h-4 w-4 animate-spin text-slate-400" />}
          </div>
          <p className="text-sm text-slate-600 mt-1">
            Configure connection to your external AI service
          </p>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <label className="text-sm font-medium">OCR Processing Endpoint</label>
            <Input
              value={ocrEndpoint}
              onChange={(e) => setOcrEndpoint(e.target.value)}
              placeholder="https://111.223.37.41:9001/v3/ai-process-file"
              disabled={isLoadingConfig}
            />
            <p className="text-xs text-slate-500">
              Used for extracting text from documents (POST with file upload)
            </p>
          </div>

          <div className="space-y-2">
            <label className="text-sm font-medium">Schema Suggestion Endpoint</label>
            <Input
              value={schemaSuggestionEndpoint}
              onChange={(e) => setSchemaSuggestionEndpoint(e.target.value)}
              placeholder="https://111.223.37.41:9001/suggest-schema"
              disabled={isLoadingConfig}
            />
            <p className="text-xs text-slate-500">
              Used for suggesting JSON schema from document samples (POST with file upload)
            </p>
          </div>

          <div className="space-y-2">
            <label className="text-sm font-medium">Structured Output Endpoint</label>
            <Input
              value={structuredOutputEndpoint}
              onChange={(e) => setStructuredOutputEndpoint(e.target.value)}
              placeholder="https://111.223.37.41:9001/structured-output"
              disabled={isLoadingConfig}
            />
            <p className="text-xs text-slate-500">
              Used for extracting structured JSON output from processed document content
            </p>
          </div>

          <div className="space-y-2">
            <label className="text-sm font-medium">Test Connection Endpoint</label>
            <Input
              value={testEndpoint}
              onChange={(e) => setTestEndpoint(e.target.value)}
              placeholder="https://111.223.37.41:9001/me"
              disabled={isLoadingConfig}
            />
            <p className="text-xs text-slate-500">
              Used to verify API authentication (GET request)
            </p>
          </div>

          <div className="space-y-2">
            <label className="text-sm font-medium">Bearer Token</label>
            <div className="relative">
              <Input
                value={token}
                onChange={(e) => setToken(e.target.value)}
                type={showToken ? "text" : "password"}
                placeholder="Enter API key (required)"
                className="pr-10"
                disabled={isLoadingConfig}
              />
              <button
                type="button"
                onClick={() => setShowToken(!showToken)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                aria-label={showToken ? "Hide token" : "Show token"}
              >
                {showToken ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
            <p className="text-xs text-slate-500">
              API authentication token for both endpoints
            </p>
          </div>

          <div className="flex gap-2">
            <Button type="button" variant="outline" onClick={handleSaveBackend} disabled={isLoadingConfig}>
              Save Connection Settings
            </Button>
            <Button type="button" onClick={handleTest} disabled={loading || isLoadingConfig}>
              {loading && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
              Test Connection
            </Button>
          </div>

          {result && (
            <div className="flex items-start gap-2 text-sm text-green-700 bg-green-50 p-3 rounded-md">
              <CheckCircle2 className="h-4 w-4 mt-0.5" />
              <span className="break-all">{result}</span>
            </div>
          )}
          {error && (
            <div className="flex items-start gap-2 text-sm text-red-700 bg-red-50 p-3 rounded-md">
              <AlertCircle className="h-4 w-4 mt-0.5" />
              <span className="break-all">{error}</span>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>OCR Engine</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <label className="text-sm font-medium">Engine</label>
            <select
              title="Select OCR Engine"
              className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm"
              value={ocrEngine}
              onChange={(e) => setOcrEngine(e.target.value)}
            >
              <option value="default">default</option>
              <option value="tesseract">tesseract</option>
              <option value="easyocr">easyocr</option>
            </select>
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium">Model</label>
            <select
              title="Select OCR Model"
              className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm"
              value={model}
              onChange={(e) => setModel(e.target.value)}
            >
              <option value="default">default</option>
              <option value="scb10x/typhoon-ocr-7b">scb10x/typhoon-ocr-7b</option>
              <option value="gemma3:27b">gemma3:27b</option>
              <option value="qwen/qwen2.5-vl-72b-instruct">qwen/qwen2.5-vl-72b-instruct</option>
            </select>
          </div>
          <div className="flex gap-2">
            <Button type="button" onClick={handleSaveBackend}>
              Save OCR Settings
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
