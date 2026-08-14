"use client"

import { useEffect, useMemo, useState } from "react"
import { useAuth } from "@/components/auth-provider"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { AlertCircle, Bot, CheckCircle2, ChevronDown, Eye, EyeOff, Loader2, Pencil, Plus, Trash2 } from "lucide-react"
import { getApiBaseUrl, getPublicApiBaseUrl } from "@/lib/api"
import { ApiAccessTokens } from "@/components/settings/ApiAccessTokens"
import { ApiWorkflowDocs } from "@/components/profile/ApiWorkflowDocs"
import { AgentSkillDownloads } from "@/components/profile/AgentSkillDownloads"
import { McpClientGuide } from "@/components/profile/McpClientGuide"
import {
  type AIProviderSetting,
  createAIProvider,
  deleteAIProvider,
  getAIProviderWithKey,
  listAIProviders,
  setAgentProvider,
  unsetAgentProvider,
  setWorkflowBuilderProvider,
  unsetWorkflowBuilderProvider,
  updateAIProvider,
} from "@/lib/ai-settings-api"

type SettingsTab = "ocr" | "tokens" | "mcp" | "api" | "skills"

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
  const [ocrFallbackEnabled, setOcrFallbackEnabled] = useState(false)
  const [ocrFallbackConfigured, setOcrFallbackConfigured] = useState(false)
  const [ocrFallbackSource, setOcrFallbackSource] = useState("none")
  const [ocrFallbackApiKey, setOcrFallbackApiKey] = useState("")
  const [showOcrFallbackKey, setShowOcrFallbackKey] = useState(false)
  const [ocrFallbackTesting, setOcrFallbackTesting] = useState(false)
  const [appCommitSha, setAppCommitSha] = useState("")
  const [result, setResult] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  // AI Agent Provider state
  const [aiProviders, setAiProviders] = useState<AIProviderSetting[]>([])
  const [aiProviderLoading, setAiProviderLoading] = useState(true)
  const [aiProviderError, setAiProviderError] = useState<string | null>(null)
  const [aiProviderSuccess, setAiProviderSuccess] = useState<string | null>(null)
  const [showProviderForm, setShowProviderForm] = useState(false)
  const [editingProvider, setEditingProvider] = useState<AIProviderSetting | null>(null)
  const [providerForm, setProviderForm] = useState({
    name: "", display_name: "", api_url: "", api_key: "",
    model: "gpt-4o-mini", provider_type: "openai_compatible", description: "",
  })
  const [showProviderKey, setShowProviderKey] = useState(false)
  const [savingProvider, setSavingProvider] = useState(false)
  const [savingFeatureProvider, setSavingFeatureProvider] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<SettingsTab>("ocr")
  const [publicApiBaseUrl, setPublicApiBaseUrl] = useState("/api/v1")
  const [tokenExample, setTokenExample] = useState("YOUR_API_ACCESS_TOKEN")

  const isAdmin = normalizedRole === "admin"

  const getAuthHeader = (): Record<string, string> => {
    const authToken = typeof window !== "undefined" ? localStorage.getItem("token") : null
    return authToken ? { Authorization: `Bearer ${authToken}` } : {}
  }

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
          setOcrFallbackEnabled(Boolean(data.ocr_fallback_enabled))
          setOcrFallbackConfigured(Boolean(data.ocr_fallback_configured))
          setOcrFallbackSource(data.ocr_fallback_source ?? "none")
          setOcrFallbackApiKey(data.ocr_fallback_api_key ?? "")
          setAppCommitSha(data.app_commit_sha ?? "")
        }
      } catch (err) {
        console.error("Failed to load settings", err)
      } finally {
        setIsLoadingConfig(false)
      }
    }
    fetchConfig()
  }, [])

  const fetchAiProviders = async () => {
    const tok = typeof window !== "undefined" ? localStorage.getItem("token") : null
    if (!tok) return
    setAiProviderLoading(true)
    try {
      const data = await listAIProviders(tok)
      setAiProviders(data)
    } catch {
      /* ignore */
    } finally {
      setAiProviderLoading(false)
    }
  }

  useEffect(() => { fetchAiProviders() }, [])

  useEffect(() => {
    setPublicApiBaseUrl(getPublicApiBaseUrl())
    if (!isAdmin && activeTab === "ocr") setActiveTab("tokens")
  }, [activeTab, isAdmin])

  const openCreateForm = () => {
    setEditingProvider(null)
    setProviderForm({ name: "", display_name: "", api_url: "", api_key: "", model: "gpt-4o-mini", provider_type: "openai_compatible", description: "" })
    setShowProviderKey(false)
    setShowProviderForm(true)
  }

  const openEditForm = async (provider: AIProviderSetting) => {
    const tok = typeof window !== "undefined" ? localStorage.getItem("token") : null
    if (!tok) return
    try {
      const full = await getAIProviderWithKey(tok, provider.id)
      setProviderForm({
        name: full.name, display_name: full.display_name, api_url: full.api_url,
        api_key: full.api_key || "", model: full.model || "gpt-4o-mini",
        provider_type: full.provider_type || "openai_compatible", description: full.description || "",
      })
    } catch {
      setProviderForm({
        name: provider.name, display_name: provider.display_name, api_url: provider.api_url,
        api_key: "", model: provider.model || "gpt-4o-mini",
        provider_type: provider.provider_type || "openai_compatible", description: provider.description || "",
      })
    }
    setEditingProvider(provider)
    setShowProviderKey(false)
    setShowProviderForm(true)
  }

  const handleSaveProvider = async () => {
    const tok = typeof window !== "undefined" ? localStorage.getItem("token") : null
    if (!tok) return
    setSavingProvider(true)
    setAiProviderError(null)
    setAiProviderSuccess(null)
    try {
      if (editingProvider) {
        await updateAIProvider(tok, editingProvider.id, {
          display_name: providerForm.display_name,
          api_url: providerForm.api_url,
          ...(providerForm.api_key ? { api_key: providerForm.api_key } : {}),
          model: providerForm.model,
          provider_type: providerForm.provider_type,
          description: providerForm.description || undefined,
        })
        setAiProviderSuccess("อัปเดต provider เรียบร้อยแล้ว")
      } else {
        await createAIProvider(tok, {
          ...providerForm,
          is_agent_provider: false,
          is_active: true,
        })
        setAiProviderSuccess("สร้าง provider เรียบร้อยแล้ว")
      }
      setShowProviderForm(false)
      fetchAiProviders()
    } catch (e: unknown) {
      setAiProviderError(e instanceof Error ? e.message : String(e))
    } finally {
      setSavingProvider(false)
    }
  }

  const handleDeleteProvider = async (id: string) => {
    if (!confirm("ต้องการลบ AI Provider นี้?")) return
    const tok = typeof window !== "undefined" ? localStorage.getItem("token") : null
    if (!tok) return
    setAiProviderError(null)
    try {
      await deleteAIProvider(tok, id)
      setAiProviderSuccess("ลบ provider เรียบร้อยแล้ว")
      fetchAiProviders()
    } catch (e: unknown) {
      setAiProviderError(e instanceof Error ? e.message : String(e))
    }
  }

  const handleFeatureProviderChange = async (feature: "agent" | "workflow_builder", providerId: string) => {
    const tok = typeof window !== "undefined" ? localStorage.getItem("token") : null
    if (!tok) return
    const currentProvider = aiProviders.find((provider) => feature === "agent"
      ? provider.is_agent_provider
      : provider.is_workflow_builder_provider)
    if (providerId === (currentProvider?.id ?? "")) return

    setAiProviderError(null)
    setSavingFeatureProvider(feature)
    try {
      if (providerId) {
        if (feature === "agent") {
          await setAgentProvider(tok, providerId)
          setAiProviderSuccess("อัปเดตโมเดลสำหรับ AI Agent แล้ว")
        } else {
          await setWorkflowBuilderProvider(tok, providerId)
          setAiProviderSuccess("อัปเดตโมเดลสำหรับ Workflow Builder แล้ว")
        }
      } else {
        if (currentProvider) {
          if (feature === "agent") {
            await unsetAgentProvider(tok, currentProvider.id)
          } else {
            await unsetWorkflowBuilderProvider(tok, currentProvider.id)
          }
        }
        setAiProviderSuccess(`ยกเลิกการกำหนดโมเดลสำหรับ ${feature === "agent" ? "AI Agent" : "Workflow Builder"} แล้ว`)
      }
      await fetchAiProviders()
    } catch (e: unknown) {
      setAiProviderError(e instanceof Error ? e.message : String(e))
    } finally {
      setSavingFeatureProvider(null)
    }
  }

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
          verify_ssl: false,
          ocr_fallback_enabled: ocrFallbackEnabled,
          ocr_fallback_api_key: ocrFallbackApiKey,
        })
      })
      const data = await res.json()
      if (res.ok) {
        setResult("Settings saved to backend.")
        setOcrFallbackConfigured(Boolean(data.ocr_fallback_configured))
        setOcrFallbackSource(data.ocr_fallback_source ?? "none")
        setOcrFallbackApiKey(data.ocr_fallback_api_key ?? "")
      } else {
        setError(data.detail || "Failed to save settings.")
      }
    } catch (err: unknown) {
      setError(`Error: ${err instanceof Error ? err.message : String(err)}`)
    }
  }

  const handleOcrFallbackToggle = (enabled: boolean) => {
    if (enabled && !ocrFallbackConfigured && !ocrFallbackApiKey.trim()) {
      setError("กรุณาระบุ Fallback API Key ในหน้านี้ หรือกำหนด MISTRAL_API_KEY ใน backend/.env ก่อนเปิดใช้งาน")
      return
    }
    setError(null)
    setOcrFallbackEnabled(enabled)
  }

  const handleTestOcrFallback = async () => {
    setOcrFallbackTesting(true)
    setResult(null)
    setError(null)
    try {
      const authToken = typeof window !== "undefined" ? localStorage.getItem("token") : null
      const res = await fetch(`${getApiBaseUrl()}/settings/ocr-fallback/test`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: JSON.stringify({ api_key: ocrFallbackApiKey }),
      })
      const data = await res.json()
      if (res.ok) {
        setResult(`Fallback connection successful (${data.status_code}).`)
      } else {
        setError(data.detail || "Fallback API key was rejected.")
      }
    } catch (err: unknown) {
      setError(`Error: ${err instanceof Error ? err.message : String(err)}`)
    } finally {
      setOcrFallbackTesting(false)
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
    } catch (err: unknown) {
      setError(`Error: ${err instanceof Error ? err.message : String(err)}`)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="max-w-6xl space-y-6">
      <div className="space-y-2">
        <h2 className="text-2xl font-bold tracking-tight">Settings</h2>
        <p className="text-slate-600">Manage OCR, providers, API access, and agent connections.</p>
        <p className="text-xs text-slate-500">
          Update commit: <span className="font-mono text-slate-700">{appCommitSha || "unknown"}</span>
        </p>
      </div>

      <div role="tablist" aria-label="Settings sections" className="grid grid-cols-2 gap-2 rounded-lg border border-slate-200 bg-white p-2 sm:grid-cols-5">
        {[
          ...(isAdmin ? [{ id: "ocr" as const, label: "OCR & Providers" }] : []),
          { id: "tokens" as const, label: "API Access Tokens" },
          { id: "mcp" as const, label: "MCP Access" },
          { id: "api" as const, label: "API Workflow Docs" },
          { id: "skills" as const, label: "AI Agent Skill Package" },
        ].map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={activeTab === tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`min-h-10 rounded-md px-3 py-2 text-sm font-medium transition-colors ${activeTab === tab.id
              ? "bg-[#EBF4FB] text-[#1F6FA8]"
              : "text-slate-600 hover:bg-slate-50 hover:text-slate-900"}`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === "tokens" && (
        <ApiAccessTokens onTokenCreated={setTokenExample} />
      )}
      {activeTab === "mcp" && (
        <McpClientGuide apiBaseUrl={publicApiBaseUrl} tokenExample={tokenExample} />
      )}
      {activeTab === "api" && (
        <ApiWorkflowDocs apiBaseUrl={publicApiBaseUrl} tokenExample={tokenExample} />
      )}
      {activeTab === "skills" && (
        <AgentSkillDownloads apiBaseUrl={publicApiBaseUrl} getAuthHeader={getAuthHeader} />
      )}

      {isAdmin && activeTab === "ocr" && (
        <>

      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
          <CardTitle>Softnix OCR Configuration</CardTitle>
            {isLoadingConfig && <Loader2 className="h-4 w-4 animate-spin text-slate-400" />}
          </div>
          <p className="text-sm text-slate-600 mt-1">
            Connection used after TesseractOCR cannot read a page.
          </p>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <label className="text-sm font-medium">Softnix OCR Endpoint</label>
            <Input
              value={ocrEndpoint}
              onChange={(e) => setOcrEndpoint(e.target.value)}
              placeholder="https://111.223.37.41:9001/v3/ai-process-file"
              disabled={isLoadingConfig}
            />
            <p className="text-xs text-slate-500">
              Used as the second OCR provider for scanned pages.
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
            <label className="text-sm font-medium">Softnix OCR API Token</label>
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
          <div className="flex items-center justify-between gap-3">
            <CardTitle>TesseractOCR</CardTitle>
            <span className="rounded-full bg-emerald-50 px-2 py-1 text-xs font-medium text-emerald-700">Local OCR</span>
          </div>
          <p className="text-sm text-slate-600 mt-1">Runs in this deployment first with Thai and English language data.</p>
        </CardHeader>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between gap-3">
            <CardTitle>OCR fallback</CardTitle>
            <span className={`rounded-full px-2 py-1 text-xs font-medium ${ocrFallbackConfigured ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700"}`}>
              {ocrFallbackConfigured ? "Ready" : "Key required"}
            </span>
          </div>
          <p className="text-sm text-slate-600 mt-1">
            Used only after TesseractOCR and Softnix OCR cannot return text.
          </p>
        </CardHeader>
        <CardContent className="space-y-3">
          <label className="flex cursor-pointer items-start gap-3 rounded-md border border-slate-200 p-3">
            <input
              type="checkbox"
              className="mt-0.5 h-4 w-4 accent-[#2786C2]"
              checked={ocrFallbackEnabled}
              onChange={(e) => handleOcrFallbackToggle(e.target.checked)}
              disabled={isLoadingConfig}
            />
            <span>
              <span className="block text-sm font-medium text-slate-800">Enable OCR fallback</span>
              <span className="mt-1 block text-xs text-slate-500">
                Use the saved key as an override, or leave it empty to use the backend environment key.
              </span>
            </span>
          </label>
          {!ocrFallbackConfigured && !ocrFallbackApiKey.trim() && (
            <p className="text-xs text-amber-700">
              ต้องตั้งค่า key ก่อนเปิดใช้งาน fallback: ใส่ key ในช่องนี้ หรือกำหนดไว้ใน backend/.env
            </p>
          )}
          <div className="space-y-2">
            <label className="text-sm font-medium">Fallback API Key</label>
            <div className="relative">
              <Input
                value={ocrFallbackApiKey}
                onChange={(e) => setOcrFallbackApiKey(e.target.value)}
                type={showOcrFallbackKey ? "text" : "password"}
                placeholder="Leave empty to use backend environment key"
                className="pr-10"
                disabled={isLoadingConfig}
              />
              <button
                type="button"
                onClick={() => setShowOcrFallbackKey(!showOcrFallbackKey)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                aria-label={showOcrFallbackKey ? "Hide fallback key" : "Show fallback key"}
              >
                {showOcrFallbackKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
            <p className="text-xs text-slate-500">
              A key saved here overrides the backend environment key. Clear this field to use the environment key.
            </p>
          </div>
          {!ocrFallbackConfigured && (
            <p className="text-xs text-amber-700">Add the fallback API key to backend/.env, then restart the backend and worker.</p>
          )}
          {ocrFallbackConfigured && (
            <p className="text-xs text-slate-500">Active key source: {ocrFallbackSource === "ui" ? "UI override" : "Environment"}</p>
          )}
          <div className="flex gap-2">
            <Button type="button" onClick={handleSaveBackend} disabled={isLoadingConfig}>
              Save OCR Fallback Settings
            </Button>
            <Button type="button" variant="outline" onClick={handleTestOcrFallback} disabled={isLoadingConfig || ocrFallbackTesting}>
              {ocrFallbackTesting && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
              Test Key
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* AI provider assignments and provider management */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Bot className="h-5 w-5 text-indigo-500" />
              <CardTitle>AI Provider</CardTitle>
              {aiProviderLoading && <Loader2 className="h-4 w-4 animate-spin text-slate-400" />}
            </div>
            {!showProviderForm && (
              <Button size="sm" variant="outline" onClick={openCreateForm}>
                <Plus className="h-4 w-4 mr-1" /> เพิ่ม Provider
              </Button>
            )}
          </div>
          <p className="text-sm text-slate-600 mt-1">
            เลือกโมเดลให้แต่ละ feature หรือเพิ่ม provider ของคุณเอง
          </p>
        </CardHeader>
        <CardContent className="space-y-4">
          {aiProviderError && (
            <div className="flex items-start gap-2 text-sm text-red-700 bg-red-50 p-3 rounded-md">
              <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
              <span>{aiProviderError}</span>
            </div>
          )}
          {aiProviderSuccess && (
            <div className="flex items-start gap-2 text-sm text-green-700 bg-green-50 p-3 rounded-md">
              <CheckCircle2 className="h-4 w-4 mt-0.5 shrink-0" />
              <span>{aiProviderSuccess}</span>
            </div>
          )}

          <div className="grid gap-3 md:grid-cols-2">
            <div className="rounded-lg border border-slate-200 bg-white p-3">
              <label htmlFor="workflow-builder-provider" className="block text-sm font-semibold text-slate-800">
                Workflow Builder
              </label>
              <p className="mt-1 text-xs text-slate-500">โมเดลสำหรับสร้าง workflow ด้วย AI</p>
              <select
                id="workflow-builder-provider"
                className="mt-3 flex h-9 w-full rounded-md border border-slate-200 bg-white px-2 text-sm text-slate-800"
                value={aiProviders.find((provider) => provider.is_workflow_builder_provider)?.id ?? ""}
                onChange={(event) => handleFeatureProviderChange("workflow_builder", event.target.value)}
                disabled={aiProviderLoading || savingFeatureProvider !== null}
              >
                <option value="">ใช้ค่าเริ่มต้นของระบบ</option>
                {aiProviders.filter((provider) => provider.is_active).map((provider) => (
                  <option key={provider.id} value={provider.id}>
                    {provider.model || provider.display_name} — {provider.display_name}
                  </option>
                ))}
              </select>
            </div>

            <div className="rounded-lg border border-indigo-200 bg-indigo-50/40 p-3">
              <label htmlFor="agent-provider" className="block text-sm font-semibold text-slate-800">
                AI Agent
              </label>
              <p className="mt-1 text-xs text-slate-500">โมเดลสำหรับสนทนาและเรียกใช้ tools</p>
              <select
                id="agent-provider"
                className="mt-3 flex h-9 w-full rounded-md border border-indigo-200 bg-white px-2 text-sm text-slate-800"
                value={aiProviders.find((provider) => provider.is_agent_provider)?.id ?? ""}
                onChange={(event) => handleFeatureProviderChange("agent", event.target.value)}
                disabled={aiProviderLoading || savingFeatureProvider !== null}
              >
                <option value="">ใช้ค่าเริ่มต้นของระบบ</option>
                {aiProviders.filter((provider) => provider.is_active).map((provider) => (
                  <option key={provider.id} value={provider.id}>
                    {provider.model || provider.display_name} — {provider.display_name}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Provider list */}
          {!aiProviderLoading && aiProviders.length === 0 && !showProviderForm && (
            <p className="text-sm text-slate-500 py-2">ยังไม่มี AI Provider — กด &quot;เพิ่ม Provider&quot; เพื่อเริ่มต้น</p>
          )}
          {aiProviders.map((p) => (
            <div key={p.id} className={`flex items-center justify-between p-3 rounded-lg border ${p.is_agent_provider ? "border-indigo-300 bg-indigo-50" : "border-slate-200 bg-white"}`}>
              <div className="min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-medium text-sm">{p.display_name}</span>
                  {p.is_agent_provider && (
                    <span className="text-xs font-semibold bg-indigo-100 text-indigo-700 px-2 py-0.5 rounded-full">Agent Provider</span>
                  )}
                  {p.is_workflow_builder_provider && (
                    <span className="text-xs font-semibold bg-[#EBF4FB] text-[#2786C2] px-2 py-0.5 rounded-full">Workflow Builder</span>
                  )}
                  <span className="text-xs bg-slate-100 text-slate-600 px-2 py-0.5 rounded-full">{p.provider_type}</span>
                  {!p.is_active && <span className="text-xs bg-red-100 text-red-600 px-2 py-0.5 rounded-full">ปิดใช้งาน</span>}
                </div>
                <p className="text-xs text-slate-500 mt-0.5 truncate max-w-xs">{p.api_url}</p>
                <p className="text-xs text-slate-400">model: {p.model || "gpt-4o-mini"}</p>
              </div>
              <div className="flex items-center gap-1 shrink-0 ml-2">
                <Button size="sm" variant="ghost" className="h-7 w-7 p-0" onClick={() => openEditForm(p)} aria-label={`แก้ไข ${p.display_name}`} title={`แก้ไข ${p.display_name}`}>
                  <Pencil className="h-3.5 w-3.5" />
                </Button>
                <Button size="sm" variant="ghost" className="h-7 w-7 p-0 text-red-500 hover:text-red-700 hover:bg-red-50" onClick={() => handleDeleteProvider(p.id)} aria-label={`ลบ ${p.display_name}`} title={`ลบ ${p.display_name}`}>
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>
            </div>
          ))}

          {/* Create / Edit form */}
          {showProviderForm && (
            <div className="border border-indigo-200 bg-indigo-50/40 rounded-lg p-4 space-y-3">
              <h4 className="text-sm font-semibold text-slate-800">
                {editingProvider ? "แก้ไข Provider" : "เพิ่ม Provider ใหม่"}
              </h4>
              {!editingProvider && (
                <div className="space-y-1">
                  <label className="text-xs font-medium text-slate-700">ชื่อ (ไม่ซ้ำ ใช้ตัวอักษร/เลข/ขีด)</label>
                  <Input
                    placeholder="my-openai"
                    value={providerForm.name}
                    onChange={(e) => setProviderForm((f) => ({ ...f, name: e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, "") }))}
                    className="h-8 text-sm"
                  />
                </div>
              )}
              <div className="space-y-1">
                <label className="text-xs font-medium text-slate-700">ชื่อที่แสดง</label>
                <Input
                  placeholder="OpenAI GPT-4o"
                  value={providerForm.display_name}
                  onChange={(e) => setProviderForm((f) => ({ ...f, display_name: e.target.value }))}
                  className="h-8 text-sm"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <label className="text-xs font-medium text-slate-700">Provider Type</label>
                  <select
                    title="Provider Type"
                    className="flex h-8 w-full rounded-md border border-slate-200 bg-white px-2 text-sm"
                    value={providerForm.provider_type}
                    onChange={(e) => setProviderForm((f) => ({ ...f, provider_type: e.target.value }))}
                  >
                    <option value="openai_compatible">OpenAI Compatible</option>
                    <option value="completion_messages">Completion Messages</option>
                  </select>
                </div>
                <div className="space-y-1">
                  <label className="text-xs font-medium text-slate-700">Model</label>
                  <Input
                    placeholder="gpt-4o-mini"
                    value={providerForm.model}
                    onChange={(e) => setProviderForm((f) => ({ ...f, model: e.target.value }))}
                    className="h-8 text-sm"
                  />
                </div>
              </div>
              <div className="space-y-1">
                <label className="text-xs font-medium text-slate-700">Base URL</label>
                <Input
                  placeholder="https://api.openai.com/v1  หรือ http://localhost:11434/v1"
                  value={providerForm.api_url}
                  onChange={(e) => setProviderForm((f) => ({ ...f, api_url: e.target.value }))}
                  className="h-8 text-sm"
                />
                <p className="text-xs text-slate-400">OpenAI: https://api.openai.com/v1 · Azure: https://&lt;resource&gt;.openai.azure.com/openai/deployments/&lt;deployment&gt; · Ollama: http://ollama:11434/v1</p>
              </div>
              <div className="space-y-1">
                <label className="text-xs font-medium text-slate-700">API Key {editingProvider && <span className="font-normal text-slate-400">(เว้นว่างเพื่อคงค่าเดิม)</span>}</label>
                <div className="relative">
                  <Input
                    type={showProviderKey ? "text" : "password"}
                    placeholder={editingProvider ? "••••••••" : "sk-..."}
                    value={providerForm.api_key}
                    onChange={(e) => setProviderForm((f) => ({ ...f, api_key: e.target.value }))}
                    className="h-8 text-sm pr-9"
                  />
                  <button type="button" onClick={() => setShowProviderKey(!showProviderKey)}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600">
                    {showProviderKey ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                  </button>
                </div>
              </div>
              <div className="space-y-1">
                <label className="text-xs font-medium text-slate-700">คำอธิบาย (ไม่จำเป็น)</label>
                <Input
                  placeholder="e.g. Production OpenAI account"
                  value={providerForm.description}
                  onChange={(e) => setProviderForm((f) => ({ ...f, description: e.target.value }))}
                  className="h-8 text-sm"
                />
              </div>
              <div className="flex gap-2">
                <Button size="sm" onClick={handleSaveProvider} disabled={savingProvider}>
                  {savingProvider && <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" />}
                  บันทึก
                </Button>
                <Button size="sm" variant="outline" onClick={() => setShowProviderForm(false)}>ยกเลิก</Button>
              </div>
            </div>
          )}

        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Softnix OCR Options</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <label className="text-sm font-medium">Engine requested from Softnix OCR</label>
            <div className="relative">
              <select
                aria-label="Select OCR Engine"
                className="flex h-10 w-full appearance-none rounded-md border border-slate-200 bg-white px-3 py-2 pr-10 text-sm transition-colors focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20 disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-slate-400"
                value={ocrEngine}
                onChange={(e) => setOcrEngine(e.target.value)}
                disabled={isLoadingConfig}
              >
                <option value="default">Provider default</option>
                <option value="tesseract">Tesseract</option>
                <option value="easyocr">EasyOCR</option>
              </select>
              <ChevronDown aria-hidden="true" className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
            </div>
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium">Model</label>
            <div className="relative">
              <select
                aria-label="Select OCR Model"
                className="flex h-10 w-full appearance-none rounded-md border border-slate-200 bg-white px-3 py-2 pr-10 text-sm transition-colors focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20 disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-slate-400"
                value={model}
                onChange={(e) => setModel(e.target.value)}
                disabled={isLoadingConfig}
              >
                <option value="default">Provider default</option>
                <option value="scb10x/typhoon-ocr-7b">Typhoon OCR 7B</option>
                <option value="gemma3:27b">Gemma 3 27B</option>
                <option value="qwen/qwen2.5-vl-72b-instruct">Qwen 2.5 VL 72B Instruct</option>
              </select>
              <ChevronDown aria-hidden="true" className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
            </div>
          </div>
          <div className="flex gap-2">
            <Button type="button" onClick={handleSaveBackend}>
              Save OCR Settings
            </Button>
          </div>
        </CardContent>
      </Card>
        </>
      )}
    </div>
  )
}
