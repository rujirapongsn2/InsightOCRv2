"use client"

import { useEffect, useMemo, useState } from "react"
import { useAuth } from "@/components/auth-provider"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Modal } from "@/components/ui/modal"
import { Plus, Pencil, Trash2, Plug, Eye, ShieldCheck, Maximize2, ChevronRight, ChevronDown, LayoutTemplate, X, FileCheck2, Receipt, Landmark, Scale, Lock, PackageCheck, Ship, BarChart2, Briefcase, ClipboardList, CalendarCheck, HeartPulse, FlaskConical, ClipboardCheck, TrendingUp, AlertOctagon, type LucideIcon } from "lucide-react"
import { getApiBaseUrl, handleAuthError } from "@/lib/api"
import {
    getIntegrations,
    createIntegration,
    updateIntegration,
    deleteIntegration,
    type Integration as APIIntegration,
} from "@/lib/integrations-api"
import { LLM_TEMPLATES, TEMPLATE_CATEGORIES, type LLMIntegrationTemplate, type TemplateCategory } from "@/lib/integration-templates"

const TEMPLATE_ICONS: Record<string, LucideIcon> = {
    FileCheck2, Receipt, Landmark, Scale, ShieldCheck, Lock,
    PackageCheck, Ship, BarChart2, Briefcase, ClipboardList,
    CalendarCheck, HeartPulse, FlaskConical, ClipboardCheck,
    TrendingUp, AlertOctagon,
}

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
    userPrompt?: string
    outputFormatPrompt?: string
    reasoningEffort?: "low" | "medium" | "high"
}

interface Integration {
    id: string
    user_id?: string
    name: string
    type: IntegrationType
    description?: string
    status: "active" | "paused"
    updatedAt?: string
    updated_at?: string
    created_at?: string
    config: IntegrationConfig
}

interface IntegrationFormState {
    name: string
    type: IntegrationType
    description: string
    status: "active" | "paused"
    method: "POST" | "PUT"
    endpoint: string
    authHeader: string
    headersJson: string
    payloadTemplate: string
    webhookUrl: string
    parameters: string
    model: string
    apiKey: string
    baseUrl: string
    instructions: string
    userPrompt: string
    outputFormatPrompt: string
    reasoningEffort: "low" | "medium" | "high"
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
    userPrompt: "",
    outputFormatPrompt: "",
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
    const isAdmin = user?.is_superuser || normalizedRole === "admin"
    const isManager = normalizedRole === "manager"
    const isUser = normalizedRole === "user"
    const token = typeof window !== 'undefined' ? localStorage.getItem("token") : null

    const [integrations, setIntegrations] = useState<Integration[]>([])
    const [showForm, setShowForm] = useState(false)
    const [editingId, setEditingId] = useState<string | null>(null)
    const [formState, setFormState] = useState<IntegrationFormState>(defaultFormState)
    const [curlInput, setCurlInput] = useState("")
    // Test LLM states
    const [testInput, setTestInput] = useState("")
    const [testResult, setTestResult] = useState<string | null>(null)
    const [testLoading, setTestLoading] = useState(false)
    // Instructions expand modal
    const [showInstructionsExpanded, setShowInstructionsExpanded] = useState(false)
    const [expandedInstructions, setExpandedInstructions] = useState("")
    // UserPrompt expand modal
    const [showUserPromptExpanded, setShowUserPromptExpanded] = useState(false)
    const [expandedUserPrompt, setExpandedUserPrompt] = useState("")
    // OutputFormatPrompt expand modal
    const [showOutputFormatExpanded, setShowOutputFormatExpanded] = useState(false)
    const [expandedOutputFormat, setExpandedOutputFormat] = useState("")
    // Loading and error states
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [expandedIntegrations, setExpandedIntegrations] = useState<Record<string, boolean>>({})
    // Template modal states
    const [showTemplateModal, setShowTemplateModal] = useState(false)
    const [templateCategory, setTemplateCategory] = useState<"all" | TemplateCategory>("all")

    // Load integrations from API
    useEffect(() => {
        loadIntegrations()
    }, [token])

    const loadIntegrations = async () => {
        if (!token) return

        setLoading(true)
        setError(null)

        try {
            const data = await getIntegrations(token)
            setIntegrations(data.integrations as Integration[])

            // Migrate localStorage data if this is first load
            await migrateLocalStorageData()
        } catch (err) {
            console.error("Failed to load integrations:", err)
            setError(err instanceof Error ? err.message : "Failed to load integrations")
        } finally {
            setLoading(false)
        }
    }

    const toggleIntegrationDetails = (integrationId: string) => {
        setExpandedIntegrations((prev) => ({
            ...prev,
            [integrationId]: !prev[integrationId],
        }))
    }

    // Migrate localStorage data to database (runs once)
    const migrateLocalStorageData = async () => {
        if (!token) return

        const migrated = localStorage.getItem("integrations_migrated")
        if (migrated === "true") return

        const stored = localStorage.getItem("integrations")
        if (!stored) {
            localStorage.setItem("integrations_migrated", "true")
            return
        }

        try {
            const localIntegrations = JSON.parse(stored) as Integration[]

            // Only migrate if database is empty
            const { integrations: dbIntegrations } = await getIntegrations(token)
            if (dbIntegrations.length > 0) {
                localStorage.setItem("integrations_migrated", "true")
                return
            }

            // Migrate each integration
            console.log(`Migrating ${localIntegrations.length} integrations from localStorage...`)
            for (const integration of localIntegrations) {
                try {
                    await createIntegration(token, {
                        name: integration.name,
                        type: integration.type,
                        description: integration.description || "",
                        status: integration.status,
                        config: integration.config,
                    })
                } catch (error) {
                    console.error(`Failed to migrate integration: ${integration.name}`, error)
                }
            }

            // Reload integrations after migration
            await loadIntegrations()
            localStorage.setItem("integrations_migrated", "true")
            console.log("✓ Successfully migrated integrations to database")
        } catch (error) {
            console.error("Migration failed:", error)
        }
    }

    const filteredTemplates = templateCategory === "all"
        ? LLM_TEMPLATES
        : LLM_TEMPLATES.filter(t => t.category === templateCategory)

    const openCreate = () => {
        setFormState(defaultFormState)
        setEditingId(null)
        setShowForm(true)
    }

    const applyTemplate = (template: LLMIntegrationTemplate) => {
        setShowTemplateModal(false)
        setTemplateCategory("all")
        setFormState({
            ...defaultFormState,
            type: "llm",
            name: template.name,
            description: template.description,
            model: template.config.model,
            instructions: template.config.instructions,
            userPrompt: template.config.userPrompt,
            outputFormatPrompt: template.config.outputFormatPrompt,
            reasoningEffort: template.config.reasoningEffort,
        })
        setEditingId(null)
        setShowForm(true)
    }

    const openEdit = (integration: Integration) => {
        setFormState({
            name: integration.name,
            type: integration.type,
            description: integration.description || "",
            status: integration.status,
            method: (integration.config.method as "POST" | "PUT") || "POST",
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
            userPrompt: integration.config.userPrompt || "",
            outputFormatPrompt: integration.config.outputFormatPrompt || "",
            reasoningEffort: integration.config.reasoningEffort || "low",
        })
        setEditingId(integration.id)
        setShowForm(true)
    }

    const handleDelete = async (id: string) => {
        const integration = integrations.find(i => i.id === id)
        if (!integration) return

        if (isUser) {
            alert("Users cannot delete integrations")
            return
        }

        if (isManager && integration.user_id !== user?.id) {
            alert("Managers can only delete their own integrations")
            return
        }

        if (!confirm("Delete this integration?")) return
        if (!token) return

        try {
            await deleteIntegration(token, id)
            setIntegrations(integrations.filter((item) => item.id !== id))
        } catch (err) {
            console.error("Failed to delete integration:", err)
            alert(err instanceof Error ? err.message : "Failed to delete integration")
        }
    }

    const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
        e.preventDefault()

        if (isUser) {
            alert("Users cannot create or edit integrations")
            return
        }

        // For editing, check if manager owns the integration
        if (editingId && isManager) {
            const integration = integrations.find(i => i.id === editingId)
            if (integration && integration.user_id !== user?.id) {
                alert("Managers can only edit their own integrations")
                return
            }
        }

        if (!token) {
            alert("Please login to continue")
            return
        }

        // Set loading state
        setLoading(true)

        const configData = {
            method: formState.method,
            endpoint: formState.endpoint,
            authHeader: formState.authHeader,
            headersJson: formState.headersJson,
            payloadTemplate: formState.payloadTemplate,
            webhookUrl: formState.webhookUrl,
            parameters: formState.parameters,
            model: formState.model,
            apiKey: formState.apiKey,
            baseUrl: formState.baseUrl,
            instructions: formState.instructions,
            userPrompt: formState.userPrompt,
            outputFormatPrompt: formState.outputFormatPrompt,
            reasoningEffort: formState.reasoningEffort,
        }

        try {
            if (editingId) {
                // Update existing integration
                const updated = await updateIntegration(token, editingId, {
                    name: formState.name,
                    type: formState.type,
                    description: formState.description,
                    status: formState.status,
                    config: configData,
                })
                setIntegrations(integrations.map((item) => (item.id === editingId ? updated as Integration : item)))
            } else {
                // Create new integration
                const created = await createIntegration(token, {
                    name: formState.name,
                    type: formState.type,
                    description: formState.description,
                    status: formState.status,
                    config: configData,
                })
                setIntegrations([...integrations, created as Integration])
            }
            setShowForm(false)
            setFormState(defaultFormState)
            setEditingId(null)
        } catch (err) {
            console.error("Failed to save integration:", err)
            alert(err instanceof Error ? err.message : "Failed to save integration")
        } finally {
            setLoading(false)
        }
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

    const renderTypeFields = () => {
        switch (formState.type) {
            case "api":
                return (
                    <div className="space-y-4">
                        <div className="space-y-2">
                            <div className="flex items-center justify-between">
                                <label className="text-sm font-medium">Import from cURL</label>
                                {!isUser && (
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
                                disabled={isUser}
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
                                    disabled={isUser}
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
                                    disabled={isUser}
                                />
                            </div>
                        </div>
                        <div className="space-y-2">
                            <label className="text-sm font-medium">Authorization / Headers</label>
                            <Textarea
                                placeholder="Authorization: Bearer <token>"
                                value={formState.authHeader}
                                onChange={(e) => setFormState({ ...formState, authHeader: e.target.value })}
                                disabled={isUser}
                            />
                        </div>
                        <div className="space-y-2">
                            <label className="text-sm font-medium">Headers (JSON)</label>
                            <Textarea
                                placeholder='{\n  "Authorization": "Bearer <token>",\n  "X-API-Key": "<key>"\n}'
                                value={formState.headersJson}
                                onChange={(e) => setFormState({ ...formState, headersJson: e.target.value })}
                                disabled={isUser}
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
                                disabled={isUser}
                            />
                        </div>
                        <div className="space-y-2">
                            <label className="text-sm font-medium">Required Parameters</label>
                            <Input
                                placeholder="document_id, file_url, fields"
                                value={formState.parameters}
                                onChange={(e) => setFormState({ ...formState, parameters: e.target.value })}
                                disabled={isUser}
                            />
                        </div>
                    </div>
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
                                            disabled={isUser}
                                            required
                                        />
                                    </div>
                                    <div className="space-y-2">
                                        <label className="text-sm font-medium">Base URL (Optional)</label>
                                        <Input
                                            placeholder="https://api.openai.com/v1 (default)"
                                            value={formState.baseUrl}
                                            onChange={(e) => setFormState({ ...formState, baseUrl: e.target.value })}
                                            disabled={isUser}
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
                                            disabled={isUser}
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
                                            disabled={isUser}
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
                                    <div className="relative">
                                        <Textarea
                                            placeholder="Enter instructions for LLM to process extracted data..."
                                            value={formState.instructions}
                                            onChange={(e) => setFormState({ ...formState, instructions: e.target.value })}
                                            disabled={isUser}
                                            rows={6}
                                            className="resize-y min-h-[120px] pr-8"
                                            required
                                        />
                                        {!isUser && (
                                            <button
                                                type="button"
                                                title="Expand editor"
                                                onClick={() => {
                                                    setExpandedInstructions(formState.instructions)
                                                    setShowInstructionsExpanded(true)
                                                }}
                                                className="absolute bottom-2 right-2 p-1 text-slate-400 hover:text-slate-700 hover:bg-slate-100 rounded transition-colors"
                                            >
                                                <Maximize2 className="h-3.5 w-3.5" />
                                            </button>
                                        )}
                                    </div>
                                    <p className="text-xs text-slate-500">System instructions for LLM — defines role and behavior. Passed as the <code className="bg-slate-100 px-1 rounded">instructions</code> parameter.</p>
                                </div>

                                {/* User Prompt */}
                                <div className="space-y-2">
                                    <div className="flex items-center gap-2">
                                        <label className="text-sm font-medium">User Prompt</label>
                                        <span className="text-xs text-slate-400">(optional)</span>
                                    </div>
                                    <div className="relative">
                                        <Textarea
                                            placeholder="e.g. Compare the following documents and highlight discrepancies..."
                                            value={formState.userPrompt}
                                            onChange={(e) => setFormState({ ...formState, userPrompt: e.target.value })}
                                            disabled={isUser}
                                            rows={4}
                                            className="resize-y min-h-[90px] pr-8"
                                        />
                                        {!isUser && (
                                            <button
                                                type="button"
                                                title="Expand editor"
                                                onClick={() => {
                                                    setExpandedUserPrompt(formState.userPrompt)
                                                    setShowUserPromptExpanded(true)
                                                }}
                                                className="absolute bottom-2 right-2 p-1 text-slate-400 hover:text-slate-700 hover:bg-slate-100 rounded transition-colors"
                                            >
                                                <Maximize2 className="h-3.5 w-3.5" />
                                            </button>
                                        )}
                                    </div>
                                    <p className="text-xs text-slate-500">Prepended before the injected OCR structured data. If empty, only the OCR data is sent as input.</p>
                                </div>

                                {/* Output Format Prompt */}
                                <div className="space-y-2">
                                    <div className="flex items-center gap-2">
                                        <label className="text-sm font-medium">Output Format Prompt</label>
                                        <span className="text-xs text-slate-400">(optional)</span>
                                    </div>
                                    <div className="relative">
                                        <Textarea
                                            placeholder="e.g. Respond in JSON with keys: summary, discrepancies, recommendation."
                                            value={formState.outputFormatPrompt}
                                            onChange={(e) => setFormState({ ...formState, outputFormatPrompt: e.target.value })}
                                            disabled={isUser}
                                            rows={3}
                                            className="resize-y min-h-[72px] pr-8"
                                        />
                                        {!isUser && (
                                            <button
                                                type="button"
                                                title="Expand editor"
                                                onClick={() => {
                                                    setExpandedOutputFormat(formState.outputFormatPrompt)
                                                    setShowOutputFormatExpanded(true)
                                                }}
                                                className="absolute bottom-2 right-2 p-1 text-slate-400 hover:text-slate-700 hover:bg-slate-100 rounded transition-colors"
                                            >
                                                <Maximize2 className="h-3.5 w-3.5" />
                                            </button>
                                        )}
                                    </div>
                                    <p className="text-xs text-slate-500">Appended after the OCR data. Use this to define the expected output structure or format.</p>
                                </div>

                                {/* Input preview */}
                                <div className="rounded-md bg-slate-50 border border-slate-200 p-3 text-xs text-slate-500 space-y-1">
                                    <p className="font-semibold text-slate-600">Input sent to LLM:</p>
                                    <p><span className="font-mono bg-white border border-slate-200 rounded px-1">User Prompt</span> + <span className="font-mono bg-blue-50 border border-blue-200 text-blue-700 rounded px-1">{'{{OCR Data}}'}</span> + <span className="font-mono bg-white border border-slate-200 rounded px-1">Output Format Prompt</span></p>
                                </div>
                                {/* Test Connection Section */}
                                <div className="space-y-3 pt-4 border-t">
                                    <div className="text-sm font-semibold text-slate-700">Test Connection</div>
                                    <p className="text-xs text-slate-500">
                                        Sends only <span className="font-mono">hello</span> to verify connectivity.
                                    </p>
                                    <Button
                                        type="button"
                                        variant="outline"
                                        onClick={async () => {
                                            if (!formState.apiKey || !formState.model) {
                                                alert("Please fill in API Key and Model first")
                                                return
                                            }
                                            setTestLoading(true)
                                            setTestResult(null)
                                            try {
                                                const response = await fetch(`${getApiBaseUrl()}/integrations/test-llm`, {
                                                    method: "POST",
                                                    headers: {
                                                        "Content-Type": "application/json",
                                                        "Authorization": `Bearer ${localStorage.getItem("token")}`
                                                    },
                                                    body: JSON.stringify({
                                                        apiKey: formState.apiKey,
                                                        baseUrl: formState.baseUrl || undefined,
                                                        model: formState.model,
                                                        reasoningEffort: formState.reasoningEffort
                                                    })
                                                })
                                                handleAuthError(response)
                                                const data = await response.json()
                                                if (response.ok) {
                                                    setTestResult(`✓ ${data.output || "Success!"}`)
                                                } else {
                                                    setTestResult(`✗ Error: ${data.detail || "Test failed"}`)
                                                }
                                            } catch (error) {
                                                setTestResult(`✗ Error: ${error instanceof Error ? error.message : "Network error"}`)
                                            } finally {
                                                setTestLoading(false)
                                            }
                                        }}
                                        disabled={isUser || testLoading}
                                    >
                                        {testLoading ? "Testing..." : "Test Connection"}
                                    </Button>
                                    {testResult && (
                                        <div className={`p-3 rounded-md text-sm font-mono whitespace-pre-wrap ${testResult.startsWith("✓")
                                                ? "bg-green-50 text-green-800 border border-green-200"
                                                : "bg-red-50 text-red-800 border border-red-200"
                                            }`}>
                                            {testResult}
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
                                disabled={isUser}
                            />
                        </div>
                        <div className="space-y-2">
                            <label className="text-sm font-medium">Parameters to send</label>
                            <Textarea
                                placeholder="jobId, status, payload, confidence"
                                value={formState.parameters}
                                onChange={(e) => setFormState({ ...formState, parameters: e.target.value })}
                                disabled={isUser}
                                rows={3}
                            />
                        </div>

                        {/* Test Connection Section */}
                        <div className="space-y-3 pt-4 border-t">
                            <div className="text-sm font-semibold text-slate-700">Test Connection</div>
                            <div className="space-y-2">
                                <label className="text-sm font-medium">Test Payload (JSON)</label>
                                <Textarea
                                    placeholder='{"test": true, "message": "Connection test from InsightDOC"}'
                                    value={testInput}
                                    onChange={(e) => setTestInput(e.target.value)}
                                    disabled={isUser || testLoading}
                                    rows={3}
                                />
                            </div>
                            <Button
                                type="button"
                                variant="outline"
                                onClick={async () => {
                                    if (!formState.webhookUrl || !formState.webhookUrl.trim()) {
                                        alert("Please enter a webhook URL first")
                                        return
                                    }

                                    setTestLoading(true)
                                    setTestResult(null)

                                    try {
                                        // Prepare test payload
                                        let payload: any = {
                                            test: true,
                                            message: "Connection test from InsightDOC",
                                            timestamp: new Date().toISOString()
                                        }

                                        // If user provided custom test input, use it
                                        if (testInput.trim()) {
                                            try {
                                                payload = JSON.parse(testInput)
                                            } catch (e) {
                                                setTestResult("Error: Invalid JSON format in test payload")
                                                setTestLoading(false)
                                                return
                                            }
                                        }

                                        const response = await fetch(formState.webhookUrl, {
                                            method: "POST",
                                            headers: {
                                                "Content-Type": "application/json"
                                            },
                                            body: JSON.stringify(payload)
                                        })

                                        if (response.ok) {
                                            const contentType = response.headers.get("content-type")
                                            let responseData = ""

                                            if (contentType && contentType.includes("application/json")) {
                                                const data = await response.json()
                                                responseData = JSON.stringify(data, null, 2)
                                            } else {
                                                responseData = await response.text()
                                            }

                                            setTestResult(`✓ Success! (Status: ${response.status})\n\nResponse:\n${responseData || "No response body"}`)
                                        } else {
                                            const errorText = await response.text().catch(() => "No error details")
                                            setTestResult(`✗ Failed! (Status: ${response.status})\n\nError:\n${errorText}`)
                                        }
                                    } catch (error) {
                                        setTestResult(`✗ Error: ${error instanceof Error ? error.message : "Network error or invalid URL"}`)
                                    } finally {
                                        setTestLoading(false)
                                    }
                                }}
                                disabled={isUser || testLoading || !formState.webhookUrl}
                            >
                                {testLoading ? "Testing..." : "Test Connection"}
                            </Button>
                            {testResult && (
                                <div className={`p-3 rounded-md text-sm font-mono whitespace-pre-wrap ${testResult.startsWith("✓")
                                        ? "bg-green-50 text-green-800 border border-green-200"
                                        : "bg-red-50 text-red-800 border border-red-200"
                                    }`}>
                                    {testResult}
                                </div>
                            )}
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
            {/* User Prompt Expanded Modal */}
            {showUserPromptExpanded && (
                <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
                    <div className="bg-white rounded-xl shadow-2xl w-full max-w-3xl flex flex-col" style={{ height: "80vh" }}>
                        <div className="flex items-center justify-between px-5 py-4 border-b">
                            <h3 className="text-base font-semibold text-slate-800">User Prompt</h3>
                            <div className="flex gap-2">
                                <Button type="button" variant="outline" size="sm" onClick={() => setShowUserPromptExpanded(false)}>Cancel</Button>
                                <Button type="button" size="sm" onClick={() => {
                                    setFormState(prev => ({ ...prev, userPrompt: expandedUserPrompt }))
                                    setShowUserPromptExpanded(false)
                                }}>Done</Button>
                            </div>
                        </div>
                        <textarea
                            className="flex-1 w-full resize-none p-4 text-sm text-slate-800 focus:outline-none font-mono leading-relaxed"
                            placeholder="Enter user prompt..."
                            value={expandedUserPrompt}
                            onChange={(e) => setExpandedUserPrompt(e.target.value)}
                            autoFocus
                        />
                    </div>
                </div>
            )}

            {/* Output Format Prompt Expanded Modal */}
            {showOutputFormatExpanded && (
                <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
                    <div className="bg-white rounded-xl shadow-2xl w-full max-w-3xl flex flex-col" style={{ height: "80vh" }}>
                        <div className="flex items-center justify-between px-5 py-4 border-b">
                            <h3 className="text-base font-semibold text-slate-800">Output Format Prompt</h3>
                            <div className="flex gap-2">
                                <Button type="button" variant="outline" size="sm" onClick={() => setShowOutputFormatExpanded(false)}>Cancel</Button>
                                <Button type="button" size="sm" onClick={() => {
                                    setFormState(prev => ({ ...prev, outputFormatPrompt: expandedOutputFormat }))
                                    setShowOutputFormatExpanded(false)
                                }}>Done</Button>
                            </div>
                        </div>
                        <textarea
                            className="flex-1 w-full resize-none p-4 text-sm text-slate-800 focus:outline-none font-mono leading-relaxed"
                            placeholder="Enter output format prompt..."
                            value={expandedOutputFormat}
                            onChange={(e) => setExpandedOutputFormat(e.target.value)}
                            autoFocus
                        />
                    </div>
                </div>
            )}

            {/* Instructions Expanded Modal */}
            {showInstructionsExpanded && (
                <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
                    <div className="bg-white rounded-xl shadow-2xl w-full max-w-3xl flex flex-col" style={{ height: "80vh" }}>
                        <div className="flex items-center justify-between px-5 py-4 border-b">
                            <h3 className="text-base font-semibold text-slate-800">Instructions</h3>
                            <div className="flex gap-2">
                                <Button
                                    type="button"
                                    variant="outline"
                                    size="sm"
                                    onClick={() => setShowInstructionsExpanded(false)}
                                >
                                    Cancel
                                </Button>
                                <Button
                                    type="button"
                                    size="sm"
                                    onClick={() => {
                                        setFormState(prev => ({ ...prev, instructions: expandedInstructions }))
                                        setShowInstructionsExpanded(false)
                                    }}
                                >
                                    Done
                                </Button>
                            </div>
                        </div>
                        <textarea
                            className="flex-1 w-full resize-none p-4 text-sm text-slate-800 focus:outline-none font-mono leading-relaxed"
                            placeholder="Enter instructions for LLM to process extracted data..."
                            value={expandedInstructions}
                            onChange={(e) => setExpandedInstructions(e.target.value)}
                            autoFocus
                        />
                    </div>
                </div>
            )}

            {/* Template Browser Modal */}
            {showTemplateModal && (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
                    <div className="bg-white rounded-xl shadow-2xl w-full max-w-5xl flex flex-col" style={{ maxHeight: "calc(100vh - 4rem)" }}>
                        {/* Header */}
                        <div className="flex items-center justify-between px-6 py-4 border-b shrink-0">
                            <div>
                                <h2 className="text-xl font-semibold text-slate-900">Add From Template</h2>
                                <p className="text-sm text-slate-500 mt-0.5">เลือกเทมเพลตสำเร็จรูปเพื่อเริ่มต้นอย่างรวดเร็ว — เพิ่มเพียง API Key และปรับแต่งตามต้องการ</p>
                            </div>
                            <button
                                type="button"
                                onClick={() => { setShowTemplateModal(false); setTemplateCategory("all") }}
                                className="text-slate-400 hover:text-slate-600 transition-colors p-1 rounded"
                            >
                                <X className="h-5 w-5" />
                            </button>
                        </div>

                        {/* Category filter pills */}
                        <div className="px-6 py-3 bg-slate-50 border-b shrink-0">
                            <div className="flex flex-wrap gap-2">
                                <button
                                    type="button"
                                    onClick={() => setTemplateCategory("all")}
                                    className={`px-3 py-1 rounded-full text-sm font-medium transition-colors ${
                                        templateCategory === "all"
                                            ? "bg-slate-900 text-white"
                                            : "bg-white text-slate-600 border border-slate-200 hover:border-slate-300"
                                    }`}
                                >
                                    ทั้งหมด ({LLM_TEMPLATES.length})
                                </button>
                                {(Object.keys(TEMPLATE_CATEGORIES) as TemplateCategory[]).map(cat => {
                                    const catInfo = TEMPLATE_CATEGORIES[cat]
                                    const count = LLM_TEMPLATES.filter(t => t.category === cat).length
                                    return (
                                        <button
                                            key={cat}
                                            type="button"
                                            onClick={() => setTemplateCategory(cat)}
                                            className={`px-3 py-1 rounded-full text-sm font-medium transition-colors ${
                                                templateCategory === cat
                                                    ? "bg-slate-900 text-white"
                                                    : "bg-white text-slate-600 border border-slate-200 hover:border-slate-300"
                                            }`}
                                        >
                                            {catInfo.labelTh} ({count})
                                        </button>
                                    )
                                })}
                            </div>
                        </div>

                        {/* Scrollable template grid */}
                        <div className="overflow-y-auto flex-1 p-6">
                            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                                {filteredTemplates.map(template => {
                                    const cat = TEMPLATE_CATEGORIES[template.category]
                                    const IconComp = TEMPLATE_ICONS[template.icon] ?? LayoutTemplate
                                    return (
                                        <div key={template.id} className="bg-white border border-slate-200 rounded-lg p-4 flex flex-col gap-3 hover:border-slate-300 hover:shadow-sm transition-all">
                                            {/* Icon + Category badge */}
                                            <div className="flex items-center gap-2">
                                                <div className={`w-12 h-12 rounded-2xl flex items-center justify-center shrink-0 shadow-sm ${cat.iconBgClass}`}>
                                                    <IconComp className={`h-6 w-6 ${cat.iconColorClass}`} />
                                                </div>
                                                <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${cat.badgeClass}`}>
                                                    {cat.labelTh}
                                                </span>
                                            </div>
                                            {/* Name */}
                                            <h3 className="font-semibold text-slate-900 text-sm leading-snug">{template.name}</h3>
                                            {/* Description */}
                                            <p className="text-xs text-slate-500 leading-relaxed flex-1">{template.description}</p>
                                            {/* Tags */}
                                            <div className="flex flex-wrap gap-1">
                                                {template.tags.slice(0, 4).map(tag => (
                                                    <span key={tag} className="text-xs bg-slate-100 text-slate-600 px-2 py-0.5 rounded">
                                                        {tag}
                                                    </span>
                                                ))}
                                            </div>
                                            {/* Footer */}
                                            <div className="flex items-center justify-between pt-1 border-t border-slate-100">
                                                <span className="text-xs text-slate-400 capitalize">
                                                    {template.config.model} · reasoning: {template.config.reasoningEffort}
                                                </span>
                                                <Button
                                                    size="sm"
                                                    onClick={() => applyTemplate(template)}
                                                    className="text-xs h-7 px-3"
                                                >
                                                    Use Template
                                                </Button>
                                            </div>
                                        </div>
                                    )
                                })}
                            </div>
                        </div>
                    </div>
                </div>
            )}

            <div className="flex items-center justify-between gap-4">
                <div>
                    <h2 className="text-2xl font-bold tracking-tight">Integration</h2>
                    <p className="text-slate-600">Manage outbound integration channels for the OCR pipeline</p>
                    <p className="text-xs text-slate-500 mt-1 flex items-center gap-2">
                        <ShieldCheck className="h-4 w-4" />
                        Admin: All CRUD, Manager: View + Own CRUD, User: View/Use only
                    </p>
                </div>
                {(isAdmin || isManager) && (
                    <div className="flex items-center gap-2">
                        <Button variant="outline" onClick={() => setShowTemplateModal(true)}>
                            <LayoutTemplate className="mr-2 h-4 w-4" />
                            Add From Template
                        </Button>
                        <Button onClick={openCreate}>
                            <Plus className="mr-2 h-4 w-4" />
                            Add Integration
                        </Button>
                    </div>
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
                            <button
                                type="button"
                                className="space-y-2 text-left flex-1"
                                onClick={() => toggleIntegrationDetails(integration.id)}
                                aria-expanded={!!expandedIntegrations[integration.id]}
                            >
                                <div className="flex items-center gap-2 flex-wrap">
                                    {expandedIntegrations[integration.id] ? (
                                        <ChevronDown className="h-4 w-4 text-slate-500" />
                                    ) : (
                                        <ChevronRight className="h-4 w-4 text-slate-500" />
                                    )}
                                    <span className="text-lg font-semibold text-slate-900">{integration.name}</span>
                                    <span className="rounded-full bg-slate-100 text-slate-700 px-3 py-1 text-xs capitalize">
                                        {integration.type === "workflow" ? "Workflow Automation" : integration.type.toUpperCase()}
                                    </span>
                                    <span className={`rounded-full px-3 py-1 text-xs ${integration.status === "active" ? "bg-green-100 text-green-800" : "bg-amber-100 text-amber-800"}`}>
                                        {integration.status === "active" ? "Active" : "Paused"}
                                    </span>
                                </div>
                                <p className="text-slate-600">{integration.description}</p>
                                <div className="text-xs text-slate-500">Updated {new Date(integration.updatedAt || integration.updated_at || integration.created_at || Date.now()).toLocaleString()}</div>
                            </button>
                            <div className="flex items-center gap-2">
                                {isUser && (
                                    <div className="flex items-center gap-1 text-slate-500 text-sm">
                                        <Eye className="h-4 w-4" />
                                        View only
                                    </div>
                                )}
                                {(isAdmin || (isManager && integration.user_id === user?.id)) && (
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
                        {expandedIntegrations[integration.id] && (
                            <div className="mt-4 border-t pt-4">
                                {renderConfigDetails(integration)}
                            </div>
                        )}
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
                                disabled={isUser}
                            />
                        </div>
                        <div className="space-y-2">
                            <label className="text-sm font-medium">Type</label>
                            <select
                                className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm"
                                value={formState.type}
                                onChange={(e) => setFormState({ ...formState, type: e.target.value as IntegrationType })}
                                disabled={isUser}
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
                                disabled={isUser}
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
                            disabled={isUser}
                        />
                    </div>

                    {renderTypeFields()}

                    {isUser ? (
                        <div className="flex justify-end">
                            <Button type="button" variant="outline" onClick={() => setShowForm(false)}>Close</Button>
                        </div>
                    ) : (
                        <div className="flex justify-end gap-2">
                            <Button variant="outline" type="button" onClick={() => setShowForm(false)}>Cancel</Button>
                            <Button type="submit">{editingId ? "Save changes" : "Create"}</Button>
                        </div>
                    )}
                </form>
            </Modal>
        </div>
    )
}
