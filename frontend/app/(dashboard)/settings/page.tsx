"use client"

import { useEffect, useMemo, useState } from "react"
import { useAuth } from "@/components/auth-provider"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { AlertCircle, Bot, CheckCircle2, Eye, EyeOff, Loader2, Pencil, Plus, Trash2 } from "lucide-react"
import { getApiBaseUrl } from "@/lib/api"
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

  const handleSetAgentProvider = async (id: string, currentlyAgent: boolean) => {
    const tok = typeof window !== "undefined" ? localStorage.getItem("token") : null
    if (!tok) return
    setAiProviderError(null)
    try {
      if (currentlyAgent) {
        await unsetAgentProvider(tok, id)
        setAiProviderSuccess("ยกเลิก Agent Provider แล้ว")
      } else {
        await setAgentProvider(tok, id)
        setAiProviderSuccess("ตั้ง Agent Provider เรียบร้อยแล้ว")
      }
      fetchAiProviders()
    } catch (e: unknown) {
      setAiProviderError(e instanceof Error ? e.message : String(e))
    }
  }

  const handleSetWorkflowBuilderProvider = async (id: string, currentlyWfb: boolean) => {
    const tok = typeof window !== "undefined" ? localStorage.getItem("token") : null
    if (!tok) return
    setAiProviderError(null)
    try {
      if (currentlyWfb) {
        await unsetWorkflowBuilderProvider(tok, id)
        setAiProviderSuccess("ยกเลิก Workflow Builder Provider แล้ว")
      } else {
        await setWorkflowBuilderProvider(tok, id)
        setAiProviderSuccess("ตั้ง Workflow Builder Provider เรียบร้อยแล้ว")
      }
      fetchAiProviders()
    } catch (e: unknown) {
      setAiProviderError(e instanceof Error ? e.message : String(e))
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
        <p className="text-xs text-slate-500">
          Update commit: <span className="font-mono text-slate-700">{appCommitSha || "unknown"}</span>
        </p>
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

      {/* AI Agent Provider */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Bot className="h-5 w-5 text-indigo-500" />
              <CardTitle>AI Agent Provider</CardTitle>
              {aiProviderLoading && <Loader2 className="h-4 w-4 animate-spin text-slate-400" />}
            </div>
            {!showProviderForm && (
              <Button size="sm" variant="outline" onClick={openCreateForm}>
                <Plus className="h-4 w-4 mr-1" /> เพิ่ม Provider
              </Button>
            )}
          </div>
          <p className="text-sm text-slate-600 mt-1">
            กำหนด OpenAI-compatible LLM ที่ AI Agent ใช้งาน (เช่น OpenAI, Azure OpenAI, Ollama, LM Studio)
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
                <Button
                  size="sm"
                  variant={p.is_agent_provider ? "default" : "outline"}
                  className={p.is_agent_provider ? "bg-indigo-600 hover:bg-indigo-700 text-xs h-7 px-2" : "text-xs h-7 px-2"}
                  onClick={() => handleSetAgentProvider(p.id, p.is_agent_provider)}
                >
                  {p.is_agent_provider ? "ยกเลิก Agent" : "ตั้งเป็น Agent"}
                </Button>
                <Button
                  size="sm"
                  variant={p.is_workflow_builder_provider ? "default" : "outline"}
                  className={p.is_workflow_builder_provider ? "bg-[#2786C2] hover:bg-[#1F6FA3] text-xs h-7 px-2" : "text-xs h-7 px-2"}
                  onClick={() => handleSetWorkflowBuilderProvider(p.id, p.is_workflow_builder_provider)}
                >
                  {p.is_workflow_builder_provider ? "ยกเลิก Workflow" : "ตั้งเป็น Workflow"}
                </Button>
                <Button size="sm" variant="ghost" className="h-7 w-7 p-0" onClick={() => openEditForm(p)}>
                  <Pencil className="h-3.5 w-3.5" />
                </Button>
                <Button size="sm" variant="ghost" className="h-7 w-7 p-0 text-red-500 hover:text-red-700 hover:bg-red-50" onClick={() => handleDeleteProvider(p.id)}>
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

          <div className="text-xs text-slate-400 pt-1 space-y-0.5">
            <p>• <strong>OpenAI Compatible</strong> — รองรับ function calling เต็มรูปแบบ (แนะนำ) ใช้กับ OpenAI, Azure, Together, Groq, Ollama</p>
            <p>• <strong>Completion Messages</strong> — สำหรับ provider ที่ไม่รองรับ native tool calling (fallback)</p>
            <p>• ตั้งเป็น <strong>Agent Provider</strong> เพื่อให้ AI Agent ใช้ provider นี้ (มีได้ 1 ตัวในแต่ละเวลา)</p>
            <p>• ตั้งเป็น <strong>Workflow Builder</strong> เพื่อเลือก LLM ที่มีประสิทธิภาพสูงสุดสำหรับสร้าง workflow ด้วย AI โดยเฉพาะ — หากไม่ตั้ง จะใช้ Agent Provider / Active Provider ตามค่าเริ่มต้นของระบบ</p>
          </div>
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
