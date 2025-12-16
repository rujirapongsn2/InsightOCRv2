"use client"

import { useEffect, useMemo, useState } from "react"
import { useAuth } from "@/components/auth-provider"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Modal } from "@/components/ui/modal"
import { Plus, Pencil, Trash2, Plug, Eye, ShieldCheck } from "lucide-react"

type IntegrationType = "api" | "workflow" | "llm"

type IntegrationConfig = {
    method?: "POST" | "PUT"
    endpoint?: string
    authHeader?: string
    headersJson?: string
    payloadTemplate?: string
    webhookUrl?: string
    parameters?: string
    model?: string
    // OpenAI-compatible LLM fields
    apiKey?: string
    baseUrl?: string
    // OpenAI Responses API fields
    instructions?: string
    reasoningEffort?: "low" | "medium" | "high"
}

interface Integration {
    id: string
    name: string
    type: IntegrationType
    description: string
    status: "active" | "paused"
    updatedAt: string
    config: IntegrationConfig
}

interface IntegrationFormState extends IntegrationConfig {
    name: string
    type: IntegrationType
    description: string
    status: "active" | "paused"
}

const defaultFormState: IntegrationFormState = {
    name: "",
    type: "api",
    description: "",
    status: "active",
    method: "POST",
    endpoint: "",
    authHeader: "",
    headersJson: "",
    payloadTemplate: "",
    webhookUrl: "",
    parameters: "",
    model: "",
    apiKey: "",
    baseUrl: "",
    instructions: "",
    reasoningEffort: "low",
}

const seedIntegrations: Integration[] = [
    {
        id: "int-api-1",
        name: "Core API",
        type: "api",
        description: "Push OCR results into the internal ERP via API",
        status: "active",
        updatedAt: "2025-01-10T10:00:00Z",
        config: {
            method: "POST",
            endpoint: "https://api.internal.example.com/erp/import",
            authHeader: "Bearer <service-token>",
            payloadTemplate: JSON.stringify({
                document_id: "<uuid>",
                file_url: "<signed-url>",
                fields: { invoice_no: "<value>", total: "<value>" }
            }, null, 2)
        }
    },
    {
        id: "int-workflow-1",
        name: "N8N Automation",
        type: "workflow",
        description: "Trigger a webhook to N8N and continue automation flows",
        status: "active",
        updatedAt: "2025-01-08T08:30:00Z",
        config: {
            webhookUrl: "https://n8n.example.com/webhook/ocr-finish",
            parameters: "jobId, status, fileUrl, payload, confidence"
        }
    },
    {
        id: "int-llm-1",
        name: "LLM Validation",
        type: "llm",
        description: "Send extracted text to an LLM for validation and enrichment",
        status: "paused",
        updatedAt: "2025-01-05T12:15:00Z",
        config: {
            method: "POST",
            endpoint: "https://llm-gateway.example.com/v1/validate",
            model: "gpt-4.1-mini",
            authHeader: "Bearer <llm-key>",
            payloadTemplate: JSON.stringify({
                prompt: "Validate extracted fields and suggest fixes",
                text: "<plain-text-content>",
                fields: { invoice_no: "<value>", supplier: "<value>" }
            }, null, 2)
        }
    },
]

export default function IntegrationsPage() {
    const { user } = useAuth()
    const normalizedRole = useMemo(() => {
        if (!user?.role) return "user"
        return user.role === "documents_admin" ? "manager" : user.role
    }, [user?.role])
    const isReadOnly = normalizedRole === "manager"
    const isUser = normalizedRole === "user"

    const [integrations, setIntegrations] = useState<Integration[]>([])
    const [showForm, setShowForm] = useState(false)
    const [editingId, setEditingId] = useState<string | null>(null)
    const [formState, setFormState] = useState<IntegrationFormState>(defaultFormState)
    const [curlInput, setCurlInput] = useState("")
    // Test LLM states
    const [testInput, setTestInput] = useState("")
    const [testResult, setTestResult] = useState<string | null>(null)
    const [testLoading, setTestLoading] = useState(false)

    // Load persisted integrations (localStorage fallback)
    useEffect(() => {
        if (typeof window === "undefined") return
        const stored = localStorage.getItem("integrations")
        if (stored) {
            try {
                setIntegrations(JSON.parse(stored))
                return
            } catch {
                // ignore parse error and fall back to seeds
            }
        }
        setIntegrations(seedIntegrations)
    }, [])

    const persistIntegrations = (items: Integration[]) => {
        setIntegrations(items)
        if (typeof window !== "undefined") {
            localStorage.setItem("integrations", JSON.stringify(items))
        }
    }

    const openCreate = () => {
        setFormState(defaultFormState)
        setEditingId(null)
        setShowForm(true)
    }

    const openEdit = (integration: Integration) => {
        setFormState({
            name: integration.name,
            type: integration.type,
            description: integration.description,
            status: integration.status,
            method: integration.config.method || "POST",
            endpoint: integration.config.endpoint || "",
            authHeader: integration.config.authHeader || "",
            headersJson: integration.config.headersJson || "",
            payloadTemplate: integration.config.payloadTemplate || "",
            webhookUrl: integration.config.webhookUrl || "",
            parameters: integration.config.parameters || "",
            model: integration.config.model || "",
            apiKey: integration.config.apiKey || "",
            baseUrl: integration.config.baseUrl || "",
            instructions: integration.config.instructions || "",
            reasoningEffort: integration.config.reasoningEffort || "low",
        })
        setEditingId(integration.id)
        setShowForm(true)
    }

    const handleDelete = (id: string) => {
        if (normalizedRole !== "admin") return
        if (!confirm("Delete this integration?")) return
        persistIntegrations(integrations.filter((item) => item.id !== id))
    }

    const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
        e.preventDefault()
        if (normalizedRole !== "admin") return
        const payload: Integration = {
            id: editingId || `int-${Date.now()}`,
            name: formState.name,
            type: formState.type,
            description: formState.description,
            status: formState.status,
            updatedAt: new Date().toISOString(),
            config: {
                method: formState.type === "workflow" ? undefined : formState.method,
                endpoint: formState.type === "workflow" ? undefined : formState.endpoint,
                authHeader: formState.type === "workflow" ? undefined : formState.authHeader,
                headersJson: formState.type === "workflow" ? undefined : formState.headersJson,
                payloadTemplate: formState.type === "workflow" ? undefined : formState.payloadTemplate,
                webhookUrl: formState.type === "workflow" ? formState.webhookUrl : undefined,
                parameters: formState.parameters,
                model: formState.type === "llm" ? formState.model : undefined,
                apiKey: formState.type === "llm" ? formState.apiKey : undefined,
                baseUrl: formState.type === "llm" ? formState.baseUrl : undefined,
                instructions: formState.type === "llm" ? formState.instructions : undefined,
                reasoningEffort: formState.type === "llm" ? formState.reasoningEffort : undefined,
            }
        }

        if (editingId) {
            persistIntegrations(integrations.map((item) => item.id === editingId ? payload : item))
        } else {
            persistIntegrations([payload, ...integrations])
        }

        setShowForm(false)
        setEditingId(null)
        setFormState(defaultFormState)
    }

    const parseCurlCommand = (curlText: string) => {
        const result: Partial<IntegrationConfig> & { name?: string } = {}
        const methodMatch = curlText.match(/-X\s+([A-Z]+)/i)
        if (methodMatch) result.method = methodMatch[1].toUpperCase() as "POST" | "PUT"
        const urlMatch = curlText.match(/https?:\/\/[^\s"'\\]+/i)
        if (urlMatch) {
            const cleaned = urlMatch[0].replace(/["'\\]+$/g, "")
            result.endpoint = cleaned
        }

        const headerRegex = /-H\s+['\"]([^'\"]+)['\"]/gi
        const headers: Record<string, string> = {}
        let hMatch
        while ((hMatch = headerRegex.exec(curlText)) !== null) {
            const [key, ...rest] = hMatch[1].split(":")
            if (key && rest.length) {
                headers[key.trim()] = rest.join(":").trim()
            }
        }
        if (Object.keys(headers).length) {
            result.headersJson = JSON.stringify(headers, null, 2)
            const auth = Object.entries(headers)
                .filter(([k]) => /auth|token|key/i.test(k))
                .map(([k, v]) => `${k}: ${v}`)
                .join("\n")
            if (auth) result.authHeader = auth
        }

        const dataMatch = curlText.match(/(--data-raw|--data|-d)\s+(['\"])([\s\S]*?)\2/i)
        if (dataMatch) {
            const raw = dataMatch[3]
            try {
                const parsedBody = JSON.parse(raw)
                result.payloadTemplate = JSON.stringify(parsedBody, null, 2)
            } catch {
                result.payloadTemplate = raw
            }
        }
        return result
    }

    if (isUser) {
        return (
            <div className="bg-white rounded-lg border shadow-sm p-6">
                <h2 className="text-xl font-semibold text-slate-900">Access restricted</h2>
                <p className="text-slate-600 mt-2">Standard users cannot access Integration.</p>
            </div>
        )
    }

    const renderTypeFields = () => {
        switch (formState.type) {
            case "api":
                return (
                    <div className="space-y-4">
                        <div className="space-y-2">
                            <div className="flex items-center justify-between">
                                <label className="text-sm font-medium">Import from cURL</label>
                                {normalizedRole === "admin" && (
                                    <Button
                                        type="button"
                                        size="sm"
                                        variant="outline"
                                        onClick={() => {
                                            const parsed = parseCurlCommand(curlInput)
                                            setFormState((prev) => ({
                                                ...prev,
                                                method: parsed.method || prev.method,
                                                endpoint: parsed.endpoint || prev.endpoint,
                                                authHeader: parsed.authHeader ?? prev.authHeader,
                                                headersJson: parsed.headersJson ?? prev.headersJson,
                                                payloadTemplate: parsed.payloadTemplate ?? prev.payloadTemplate,
                                            }))
                                        }}
                                        disabled={!curlInput.trim()}
                                    >
                                        Apply
                                    </Button>
                                )}
                            </div>
                            <Textarea
                                placeholder='curl -X POST "https://api.example.com" -H "Authorization: Bearer token" -H "Content-Type: application/json" -d "{\"foo\":\"bar\"}"'
                                value={curlInput}
                                onChange={(e) => setCurlInput(e.target.value)}
                                rows={3}
                                disabled={isReadOnly}
                            />
                        </div>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <div className="space-y-2">
                                <label className="text-sm font-medium">HTTP Method</label>
                                <select
                                    className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm"
                                    value={formState.method}
                                    onChange={(e) => setFormState({ ...formState, method: e.target.value as "POST" | "PUT" })}
                                    required
                                    disabled={isReadOnly}
                                >
                                    <option value="POST">POST</option>
                                    <option value="PUT">PUT</option>
                                </select>
                            </div>
                            <div className="space-y-2">
                                <label className="text-sm font-medium">Endpoint URL</label>
                                <Input
                                    required
                                    placeholder="https://api.example.com/v1/ingest"
                                    value={formState.endpoint}
                                    onChange={(e) => setFormState({ ...formState, endpoint: e.target.value })}
                                    disabled={isReadOnly}
                                />
                            </div>
                        </div>
                        <div className="space-y-2">
                            <label className="text-sm font-medium">Authorization / Headers</label>
                            <Textarea
                                placeholder="Authorization: Bearer <token>"
                                value={formState.authHeader}
                                onChange={(e) => setFormState({ ...formState, authHeader: e.target.value })}
                                disabled={isReadOnly}
                            />
                        </div>
                        <div className="space-y-2">
                            <label className="text-sm font-medium">Headers (JSON)</label>
                            <Textarea
                                placeholder='{\n  "Authorization": "Bearer <token>",\n  "X-API-Key": "<key>"\n}'
                                value={formState.headersJson}
                                onChange={(e) => setFormState({ ...formState, headersJson: e.target.value })}
                                disabled={isReadOnly}
                                rows={4}
                            />
                        </div>
                        <div className="space-y-2">
                            <label className="text-sm font-medium">Payload Template</label>
                            <Textarea
                                placeholder='{ "document_id": "<uuid>", "payload": {} }'
                                value={formState.payloadTemplate}
                                onChange={(e) => setFormState({ ...formState, payloadTemplate: e.target.value })}
                                rows={5}
                                disabled={isReadOnly}
                            />
                        </div>
                        <div className="space-y-2">
                            <label className="text-sm font-medium">Required Parameters</label>
                            <Input
                                placeholder="document_id, file_url, fields"
                                value={formState.parameters}
                                onChange={(e) => setFormState({ ...formState, parameters: e.target.value })}
                                disabled={isReadOnly}
                            />
                        </div>
                    </div >
                )
            case "llm":
                return (
                    <div className="space-y-4">
                        {formState.type === "llm" && (
                            <div className="space-y-4 p-4 bg-slate-50 rounded-lg border">
                                <div className="text-sm font-semibold text-slate-700">OpenAI Responses API Settings</div>
                                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                    <div className="space-y-2">
                                        <label className="text-sm font-medium">API Key *</label>
                                        <Input
                                            type="password"
                                            placeholder="sk-..."
                                            value={formState.apiKey}
                                            onChange={(e) => setFormState({ ...formState, apiKey: e.target.value })}
                                            disabled={isReadOnly}
                                            required
                                        />
                                    </div>
                                    <div className="space-y-2">
                                        <label className="text-sm font-medium">Base URL (Optional)</label>
                                        <Input
                                            placeholder="https://api.openai.com/v1 (default)"
                                            value={formState.baseUrl}
                                            onChange={(e) => setFormState({ ...formState, baseUrl: e.target.value })}
                                            disabled={isReadOnly}
                                        />
                                        <p className="text-xs text-slate-500">Leave empty for OpenAI. Use custom URL for Azure, Groq, local LLMs, etc.</p>
                                    </div>
                                </div>
                                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                    <div className="space-y-2">
                                        <label className="text-sm font-medium">Model *</label>
                                        <select
                                            className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm"
                                            value={formState.model}
                                            onChange={(e) => setFormState({ ...formState, model: e.target.value })}
                                            disabled={isReadOnly}
                                            title="Select LLM Model"
                                            required
                                        >
                                            <option value="">Select a model...</option>
                                            <optgroup label="GPT-4o">
                                                <option value="gpt-4o">gpt-4o</option>
                                                <option value="gpt-4o-mini">gpt-4o-mini</option>
                                            </optgroup>
                                            <optgroup label="GPT-4">
                                                <option value="gpt-4-turbo">gpt-4-turbo</option>
                                                <option value="gpt-4">gpt-4</option>
                                            </optgroup>
                                            <optgroup label="GPT-3.5">
                                                <option value="gpt-3.5-turbo">gpt-3.5-turbo</option>
                                                <option value="gpt-3.5-turbo-0125">gpt-3.5-turbo-0125</option>
                                            </optgroup>
                                            <optgroup label="GPT-5 (Preview)">
                                                <option value="gpt-5-mini">gpt-5-mini</option>
                                            </optgroup>
                                        </select>
                                    </div>
                                    <div className="space-y-2">
                                        <label className="text-sm font-medium">Reasoning Effort</label>
                                        <select
                                            className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm"
                                            value={formState.reasoningEffort}
                                            onChange={(e) => setFormState({ ...formState, reasoningEffort: e.target.value as "low" | "medium" | "high" })}
                                            disabled={isReadOnly}
                                            title="Select Reasoning Effort Level"
                                        >
                                            <option value="low">Low</option>
                                            <option value="medium">Medium</option>
                                            <option value="high">High</option>
                                        </select>
                                        <p className="text-xs text-slate-500">Controls the depth of reasoning for responses</p>
                                    </div>
                                </div>
                                <div className="space-y-2">
                                    <label className="text-sm font-medium">Instructions *</label>
                                    <Textarea
                                        placeholder="Enter instructions for the LLM to process extracted data..."
                                        value={formState.instructions}
                                        onChange={(e) => setFormState({ ...formState, instructions: e.target.value })}
                                        disabled={isReadOnly}
                                        rows={4}
                                        required
                                    />
                                    <p className="text-xs text-slate-500">Instructions for the LLM. The extracted data from document processing will be passed as input.</p>
                                </div>
                                {/* Test Connection Section */}
                                <div className="space-y-3 pt-4 border-t">
                                    <div className="text-sm font-semibold text-slate-700">Test Connection</div>
                                    <div className="space-y-2">
                                        <label className="text-sm font-medium">Test Input</label>
                                        <Textarea
                                            placeholder="Enter test data to verify LLM configuration..."
                                            value={testInput}
                                            onChange={(e) => setTestInput(e.target.value)}
                                            disabled={isReadOnly || testLoading}
                                            rows={3}
                                        />
                                    </div>
                                    <Button
                                        type="button"
                                        variant="outline"
                                        onClick={async () => {
                                            if (!formState.apiKey || !formState.model || !formState.instructions) {
                                                alert("Please fill in API Key, Model, and Instructions first")
                                                return
                                            }
                                            if (!testInput.trim()) {
                                                alert("Please enter test input")
                                                return
                                            }
                                            setTestLoading(true)
                                            setTestResult(null)
                                            try {
                                                const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1'}/integrations/test-llm`, {
                                                    method: "POST",
                                                    headers: {
                                                        "Content-Type": "application/json",
                                                        "Authorization": `Bearer ${localStorage.getItem("token")}`
                                                    },
                                                    body: JSON.stringify({
                                                        apiKey: formState.apiKey,
                                                        baseUrl: formState.baseUrl || undefined,
                                                        model: formState.model,
                                                        reasoningEffort: formState.reasoningEffort,
                                                        instructions: formState.instructions,
                                                        testInput: testInput
                                                    })
                                                })
                                                const data = await response.json()
                                                if (response.ok) {
                                                    setTestResult(data.output || "Success!")
                                                } else {
                                                    setTestResult(`Error: ${data.detail || "Test failed"}`)
                                                }
                                            } catch (error) {
                                                setTestResult(`Error: ${error instanceof Error ? error.message : "Network error"}`)
                                            } finally {
                                                setTestLoading(false)
                                            }
                                        }}
                                        disabled={isReadOnly || testLoading || !testInput.trim()}
                                    >
                                        {testLoading ? "Testing..." : "Test Connection"}
                                    </Button>
                                    {testResult && (
                                        <div className={`p-3 rounded-md text-sm ${testResult.startsWith("Error") ? "bg-red-50 text-red-800" : "bg-green-50 text-green-800"}`}>
                                            <div className="font-semibold mb-1">Test Result:</div>
                                            <div className="whitespace-pre-wrap">{testResult}</div>
                                        </div>
                                    )}
                                </div>
                            </div>
                        )}
                    </div>
                )
            case "workflow":
                return (
                    <div className="space-y-4">
                        <div className="space-y-2">
                            <label className="text-sm font-medium">Webhook URL</label>
                            <Input
                                required
                                placeholder="https://hooks.n8n.cloud/webhook/..."
                                value={formState.webhookUrl}
                                onChange={(e) => setFormState({ ...formState, webhookUrl: e.target.value })}
                            />
                        </div>
                        <div className="space-y-2">
                            <label className="text-sm font-medium">Parameters to send</label>
                            <Textarea
                                placeholder="jobId, status, payload, confidence"
                                value={formState.parameters}
                                onChange={(e) => setFormState({ ...formState, parameters: e.target.value })}
                                rows={3}
                            />
                        </div>
                    </div>
                )
            default:
                return null
        }
    }

    const renderConfigDetails = (integration: Integration) => {
        switch (integration.type) {
            case "api":
                return (
                    <div className="space-y-2 text-sm text-slate-700">
                        <div className="flex items-center gap-2">
                            <span className="font-semibold">Method:</span>
                            <span>{integration.config.method}</span>
                        </div>
                        <div>
                            <div className="font-semibold">Endpoint</div>
                            <div className="text-slate-600 break-all">{integration.config.endpoint}</div>
                        </div>
                        {(integration.config.authHeader || integration.config.headersJson) && (
                            <div className="space-y-1">
                                <div className="font-semibold">Headers</div>
                                {integration.config.authHeader && (
                                    <pre className="mt-1 rounded-md bg-slate-50 p-3 text-xs text-slate-800 whitespace-pre-wrap">{integration.config.authHeader}</pre>
                                )}
                                {integration.config.headersJson && (
                                    <pre className="mt-1 rounded-md bg-slate-50 p-3 text-xs text-slate-800 whitespace-pre-wrap">{integration.config.headersJson}</pre>
                                )}
                            </div>
                        )}
                        {integration.config.payloadTemplate && (
                            <div>
                                <div className="font-semibold">Payload Template</div>
                                <pre className="mt-1 rounded-md bg-slate-50 p-3 text-xs text-slate-800 whitespace-pre-wrap">{integration.config.payloadTemplate}</pre>
                            </div>
                        )}
                        {integration.config.parameters && (
                            <div className="text-slate-600">
                                <span className="font-semibold">Required Params:</span> {integration.config.parameters}
                            </div>
                        )}
                    </div>
                )
            case "workflow":
                return (
                    <div className="space-y-2 text-sm text-slate-700">
                        <div>
                            <div className="font-semibold">Webhook URL</div>
                            <div className="text-slate-600 break-all">{integration.config.webhookUrl}</div>
                        </div>
                        {integration.config.parameters && (
                            <div>
                                <div className="font-semibold">Parameters</div>
                                <div className="text-slate-600">{integration.config.parameters}</div>
                            </div>
                        )}
                    </div>
                )
            case "llm":
                return (
                    <div className="space-y-3 text-sm text-slate-700">
                        <div className="flex flex-wrap gap-3">
                            {integration.config.model && (
                                <div className="flex items-center gap-2">
                                    <span className="font-semibold">Model:</span>
                                    <span className="bg-blue-100 text-blue-800 px-2 py-0.5 rounded text-xs font-medium">{integration.config.model}</span>
                                </div>
                            )}
                            {integration.config.reasoningEffort && (
                                <div className="flex items-center gap-2">
                                    <span className="font-semibold">Reasoning:</span>
                                    <span className="bg-purple-100 text-purple-800 px-2 py-0.5 rounded text-xs font-medium capitalize">{integration.config.reasoningEffort}</span>
                                </div>
                            )}
                            {integration.config.apiKey && (
                                <div className="flex items-center gap-2">
                                    <span className="font-semibold">API Key:</span>
                                    <span className="font-mono text-xs bg-slate-100 px-2 py-0.5 rounded">••••••••{integration.config.apiKey.slice(-4)}</span>
                                </div>
                            )}
                        </div>
                        {integration.config.baseUrl && (
                            <div>
                                <span className="font-semibold">Base URL:</span>
                                <span className="ml-2 text-slate-600 break-all">{integration.config.baseUrl}</span>
                            </div>
                        )}
                        {integration.config.instructions && (
                            <div className="space-y-1">
                                <div className="font-semibold">Instructions</div>
                                <div className="bg-slate-50 p-3 rounded-md text-slate-800 whitespace-pre-wrap">{integration.config.instructions}</div>
                            </div>
                        )}
                    </div>
                )
            default:
                return null
        }
    }

    return (
        <div className="space-y-6">
            <div className="flex items-center justify-between gap-4">
                <div>
                    <h2 className="text-2xl font-bold tracking-tight">Integration</h2>
                    <p className="text-slate-600">Manage outbound integration channels for the OCR pipeline</p>
                    <p className="text-xs text-slate-500 mt-1 flex items-center gap-2">
                        <ShieldCheck className="h-4 w-4" />
                        Admin: CRUD, Manager: View only
                    </p>
                </div>
                {normalizedRole === "admin" && (
                    <Button onClick={openCreate}>
                        <Plus className="mr-2 h-4 w-4" />
                        Add Integration
                    </Button>
                )}
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <Card>
                    <CardHeader>
                        <div className="flex items-center gap-2 text-slate-700">
                            <Plug className="h-5 w-5" />
                            <CardTitle>API</CardTitle>
                        </div>
                        <CardDescription>Send data via API (POST/PUT) with headers and payload template</CardDescription>
                    </CardHeader>
                </Card>
                <Card>
                    <CardHeader>
                        <div className="flex items-center gap-2 text-slate-700">
                            <Plug className="h-5 w-5" />
                            <CardTitle>Workflow Automation</CardTitle>
                        </div>
                        <CardDescription>Webhook into automation tools such as N8N or any workflow engine</CardDescription>
                    </CardHeader>
                </Card>
                <Card>
                    <CardHeader>
                        <div className="flex items-center gap-2 text-slate-700">
                            <Plug className="h-5 w-5" />
                            <CardTitle>LLM</CardTitle>
                        </div>
                        <CardDescription>Connect to LLM endpoints with API-like method, endpoint, and payload</CardDescription>
                    </CardHeader>
                </Card>
            </div>

            <div className="space-y-3">
                {integrations.map((integration) => (
                    <div key={integration.id} className="bg-white rounded-lg border shadow-sm p-5">
                        <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-4">
                            <div className="space-y-2">
                                <div className="flex items-center gap-3 flex-wrap">
                                    <span className="text-lg font-semibold text-slate-900">{integration.name}</span>
                                    <span className="rounded-full bg-slate-100 text-slate-700 px-3 py-1 text-xs capitalize">
                                        {integration.type === "workflow" ? "Workflow Automation" : integration.type.toUpperCase()}
                                    </span>
                                    <span className={`rounded-full px-3 py-1 text-xs ${integration.status === "active" ? "bg-green-100 text-green-800" : "bg-amber-100 text-amber-800"}`}>
                                        {integration.status === "active" ? "Active" : "Paused"}
                                    </span>
                                </div>
                                <p className="text-slate-600">{integration.description}</p>
                                <div className="text-xs text-slate-500">Updated {new Date(integration.updatedAt).toLocaleString()}</div>
                            </div>
                            <div className="flex items-center gap-2">
                                {normalizedRole === "manager" && (
                                    <div className="flex items-center gap-1 text-slate-500 text-sm">
                                        <Eye className="h-4 w-4" />
                                        View only
                                    </div>
                                )}
                                {normalizedRole === "admin" && (
                                    <>
                                        <Button variant="ghost" size="sm" onClick={() => openEdit(integration)}>
                                            <Pencil className="h-4 w-4 mr-1" /> Edit
                                        </Button>
                                        <Button variant="ghost" size="sm" className="text-red-600 hover:text-red-700" onClick={() => handleDelete(integration.id)}>
                                            <Trash2 className="h-4 w-4 mr-1" /> Delete
                                        </Button>
                                    </>
                                )}
                            </div>
                        </div>
                        <div className="mt-4">
                            {renderConfigDetails(integration)}
                        </div>
                    </div>
                ))}
            </div>

            <Modal
                isOpen={showForm}
                onClose={() => setShowForm(false)}
                title={editingId ? "Edit Integration" : "Add Integration"}
            >
                <form className="space-y-4" onSubmit={handleSubmit}>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div className="space-y-2">
                            <label className="text-sm font-medium">Name</label>
                            <Input
                                required
                                value={formState.name}
                                onChange={(e) => setFormState({ ...formState, name: e.target.value })}
                                disabled={isReadOnly}
                            />
                        </div>
                        <div className="space-y-2">
                            <label className="text-sm font-medium">Type</label>
                            <select
                                className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm"
                                value={formState.type}
                                onChange={(e) => setFormState({ ...formState, type: e.target.value as IntegrationType })}
                                disabled={isReadOnly}
                            >
                                <option value="api">API</option>
                                <option value="workflow">Workflow Automation</option>
                                <option value="llm">LLM</option>
                            </select>
                        </div>
                        <div className="space-y-2">
                            <label className="text-sm font-medium">Status</label>
                            <select
                                className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm"
                                value={formState.status}
                                onChange={(e) => setFormState({ ...formState, status: e.target.value as "active" | "paused" })}
                                disabled={isReadOnly}
                            >
                                <option value="active">Active</option>
                                <option value="paused">Paused</option>
                            </select>
                        </div>
                    </div>
                    <div className="space-y-2">
                        <label className="text-sm font-medium">Description</label>
                        <Textarea
                            placeholder="Describe what this integration sends"
                            value={formState.description}
                            onChange={(e) => setFormState({ ...formState, description: e.target.value })}
                            disabled={isReadOnly}
                        />
                    </div>

                    {renderTypeFields()}

                    {normalizedRole === "admin" ? (
                        <div className="flex justify-end gap-2">
                            <Button variant="outline" type="button" onClick={() => setShowForm(false)}>Cancel</Button>
                            <Button type="submit">{editingId ? "Save changes" : "Create"}</Button>
                        </div>
                    ) : (
                        <div className="flex justify-end">
                            <Button type="button" variant="outline" onClick={() => setShowForm(false)}>Close</Button>
                        </div>
                    )}
                </form>
            </Modal>
        </div>
    )
}
