"use client"

import { useEffect, useMemo, useState } from "react"
import { useAuth } from "@/components/auth-provider"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Modal } from "@/components/ui/modal"
import { Plus, Pencil, Trash2, Plug, Eye, ShieldCheck, Maximize2, ChevronRight, ChevronDown, LayoutTemplate, X, FileCheck2, Receipt, Landmark, Scale, Lock, PackageCheck, Ship, BarChart2, Briefcase, ClipboardList, CalendarCheck, HeartPulse, FlaskConical, ClipboardCheck, TrendingUp, AlertOctagon, type LucideIcon, Zap, Bot, Cloud, HardDrive, Folder, ChevronLeft, LoaderCircle, CheckCircle2 } from "lucide-react"
import { getApiBaseUrl, handleAuthError } from "@/lib/api"
import {
    getIntegrations,
    createIntegration,
    updateIntegration,
    deleteIntegration,
    testDriveIntegration,
    getCloudOAuthStart,
    listCloudFolders,
    updateCloudDestination,
    type CloudFolder,
    type Integration as APIIntegration,
} from "@/lib/integrations-api"
import { LLM_TEMPLATES, TEMPLATE_CATEGORIES, type LLMIntegrationTemplate, type TemplateCategory } from "@/lib/integration-templates"

const TEMPLATE_ICONS: Record<string, LucideIcon> = {
    FileCheck2, Receipt, Landmark, Scale, ShieldCheck, Lock,
    PackageCheck, Ship, BarChart2, Briefcase, ClipboardList,
    CalendarCheck, HeartPulse, FlaskConical, ClipboardCheck,
    TrendingUp, AlertOctagon,
}

type IntegrationType = "api" | "workflow" | "llm" | "softnix_genai" | "gdrive" | "onedrive"

const SOFTNIX_GENAI_BASE_URL = "https://genai.softnix.ai/external/openai"

type IntegrationConfig = {
    method?: "POST" | "PUT"
    endpoint?: string
    authHeader?: string
    headersJson?: string
    payloadTemplate?: string
    webhookUrl?: string
    parameters?: string
    model?: string
    apiKey?: string
    baseUrl?: string
    instructions?: string
    userPrompt?: string
    outputFormatPrompt?: string
    reasoningEffort?: "low" | "medium" | "high"
    client_email?: string
    private_key?: string
    token_uri?: string
    tenant_id?: string
    client_id?: string
    client_secret?: string
    drive_id?: string
    auth_mode?: "oauth" | "service_account" | "app"
    provider?: "google" | "microsoft"
    account_email?: string
    account_name?: string
    folder_id?: string
    folder_name?: string
    drive_name?: string
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
    serviceAccountJson: string
    tenant_id: string
    client_id: string
    client_secret: string
    drive_id: string
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
    serviceAccountJson: "",
    tenant_id: "",
    client_id: "",
    client_secret: "",
    drive_id: "",
}

// Catalog definition for each integration type
const CATALOG: {
    type: IntegrationType
    label: string
    sublabel: string
    logoUrl: string | null
    FallbackIcon: LucideIcon
    iconBg: string
    iconColor: string
    accentColor: string
}[] = [
    {
        type: "api",
        label: "Custom API",
        sublabel: "REST / POST / PUT",
        logoUrl: null,
        FallbackIcon: Plug,
        iconBg: "bg-slate-100",
        iconColor: "text-slate-600",
        accentColor: "border-slate-200 hover:border-slate-300",
    },
    {
        type: "workflow",
        label: "Workflow",
        sublabel: "N8N / Webhook",
        logoUrl: "/integrations/n8n.svg",
        FallbackIcon: Zap,
        iconBg: "bg-red-50",
        iconColor: "text-red-500",
        accentColor: "border-red-100 hover:border-red-200",
    },
    {
        type: "llm",
        label: "LLM Provider",
        sublabel: "OpenAI / Compatible",
        // This category includes multiple providers, so a neutral agent mark is more accurate than one vendor logo.
        logoUrl: null,
        FallbackIcon: Bot,
        iconBg: "bg-sky-50",
        iconColor: "text-sky-600",
        accentColor: "border-sky-100 hover:border-sky-200",
    },
    {
        type: "softnix_genai",
        label: "Softnix GenAI",
        sublabel: "OpenAI Compatible",
        logoUrl: null,
        FallbackIcon: Bot,
        iconBg: "bg-cyan-50",
        iconColor: "text-cyan-600",
        accentColor: "border-cyan-100 hover:border-cyan-200",
    },
    {
        type: "gdrive",
        label: "Google Drive",
        sublabel: "Connect account",
        logoUrl: "https://img.icons8.com/fluent/1200/google-drive--v1.jpg",
        FallbackIcon: HardDrive,
        iconBg: "bg-blue-50",
        iconColor: "text-blue-500",
        accentColor: "border-blue-100 hover:border-blue-200",
    },
    {
        type: "onedrive",
        label: "OneDrive",
        sublabel: "Connect account",
        logoUrl: "/integrations/onedrive.svg",
        FallbackIcon: Cloud,
        iconBg: "bg-sky-50",
        iconColor: "text-sky-500",
        accentColor: "border-sky-100 hover:border-sky-200",
    },
]

function LogoImage({
    src,
    alt,
    FallbackIcon,
    iconColor,
    size = "lg",
}: {
    src: string | null
    alt: string
    FallbackIcon: LucideIcon
    iconColor: string
    size?: "sm" | "lg"
}) {
    const [error, setError] = useState(false)
    const imgClass = size === "lg" ? "h-10 w-10 object-contain" : "h-5 w-5 object-contain"
    const iconClass = size === "lg" ? `h-8 w-8 ${iconColor}` : `h-4 w-4 ${iconColor}`
    if (!src || error) {
        return <FallbackIcon className={iconClass} />
    }
    return (
        <img src={src} alt={alt} className={imgClass} onError={() => setError(true)} />
    )
}

function CloudConnectionWizard({
    integration,
    token,
    onClose,
    onSaved,
    onAdvanced,
}: {
    integration: Integration
    token: string
    onClose: () => void
    onSaved: (integration: APIIntegration) => void
    onAdvanced: () => void
}) {
    const providerLabel = integration.type === "gdrive" ? "Google Drive" : "OneDrive"
    const rootName = integration.type === "gdrive" ? "My Drive" : "OneDrive"
    const initialName = integration.config.folder_name || rootName
    const [name, setName] = useState(integration.name)
    const [selectedFolder, setSelectedFolder] = useState({ id: integration.config.folder_id || "root", name: initialName })
    const [path, setPath] = useState([{ id: "root", name: rootName }])
    const [folders, setFolders] = useState<CloudFolder[]>([])
    const [loading, setLoading] = useState(true)
    const [saving, setSaving] = useState(false)
    const [error, setError] = useState<string | null>(null)

    const loadFolders = async (parentId: string) => {
        setLoading(true)
        setError(null)
        try {
            const items = await listCloudFolders(token, integration.id, parentId)
            setFolders(items.filter((item) => item.is_folder))
        } catch (err) {
            setError(err instanceof Error ? err.message : "อ่านรายการโฟลเดอร์ไม่สำเร็จ")
        } finally {
            setLoading(false)
        }
    }

    useEffect(() => {
        loadFolders("root")
        // The selected folder is the starting point when reconnecting an existing integration.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [integration.id])

    const enterFolder = (folder: CloudFolder) => {
        const next = { id: folder.id, name: folder.name }
        setSelectedFolder(next)
        setPath((previous) => [...previous, next])
        loadFolders(folder.id)
    }

    const goUp = () => {
        if (path.length <= 1) return
        const nextPath = path.slice(0, -1)
        const parent = nextPath[nextPath.length - 1]
        setPath(nextPath)
        loadFolders(parent.id)
    }

    const save = async () => {
        setSaving(true)
        setError(null)
        try {
            const updated = await updateCloudDestination(token, integration.id, {
                name: name.trim() || integration.name,
                folder_id: selectedFolder.id,
                folder_name: selectedFolder.name,
                status: "active",
            })
            await testDriveIntegration(token, integration.id, { folderId: selectedFolder.id })
            onSaved(updated as APIIntegration)
        } catch (err) {
            setError(err instanceof Error ? err.message : "เชื่อมต่อโฟลเดอร์ไม่สำเร็จ")
        } finally {
            setSaving(false)
        }
    }

    return (
        <Modal isOpen onClose={onClose} title={`ตั้งค่า ${providerLabel}`} width="min(38rem, calc(100vw - 2rem))">
            <div className="space-y-4">
                <div className="flex items-center gap-3 rounded-lg border border-emerald-100 bg-emerald-50 px-4 py-3">
                    <CheckCircle2 className="h-5 w-5 shrink-0 text-emerald-600" />
                    <div className="min-w-0">
                        <div className="text-sm font-semibold text-slate-900">เชื่อมต่อบัญชีสำเร็จ</div>
                        <div className="truncate text-xs text-slate-600">{integration.config.account_email || integration.config.account_name || providerLabel}</div>
                    </div>
                </div>

                <div className="space-y-2">
                    <label className="text-sm font-medium text-slate-800" htmlFor="cloud-connection-name">ชื่อการเชื่อมต่อ</label>
                    <Input id="cloud-connection-name" value={name} onChange={(event) => setName(event.target.value)} />
                </div>

                <div className="rounded-lg border border-slate-200 bg-white">
                    <div className="flex items-center justify-between gap-3 border-b border-slate-100 px-4 py-3">
                        <div>
                            <div className="text-sm font-semibold text-slate-900">เลือกโฟลเดอร์ปลายทาง</div>
                            <div className="text-xs text-slate-500">ใช้โฟลเดอร์นี้สำหรับนำเข้าและส่งออกเอกสาร</div>
                        </div>
                        <Button type="button" variant="outline" size="sm" onClick={goUp} disabled={path.length <= 1 || loading} aria-label="ย้อนกลับหนึ่งระดับ">
                            <ChevronLeft className="mr-1 h-4 w-4" />ย้อนกลับ
                        </Button>
                    </div>
                    <div className="flex items-center gap-2 border-b border-slate-100 px-4 py-2 text-xs text-slate-500">
                        <Folder className="h-4 w-4 text-amber-500" />
                        <span className="truncate">{path.map((item) => item.name).join(" / ")}</span>
                    </div>
                    <div className="max-h-56 overflow-y-auto p-2">
                        {loading ? (
                            <div className="flex items-center justify-center gap-2 py-8 text-sm text-slate-500"><LoaderCircle className="h-4 w-4 animate-spin" />กำลังโหลดโฟลเดอร์</div>
                        ) : folders.length === 0 ? (
                            <div className="py-8 text-center text-sm text-slate-500">ไม่พบโฟลเดอร์ย่อย</div>
                        ) : (
                            folders.map((folder) => (
                                <button key={folder.id} type="button" onClick={() => enterFolder(folder)} className="flex w-full items-center gap-3 rounded-md px-3 py-2.5 text-left text-sm text-slate-700 transition-colors hover:bg-slate-50">
                                    <Folder className="h-4 w-4 shrink-0 text-amber-500" />
                                    <span className="truncate">{folder.name}</span>
                                    <ChevronRight className="ml-auto h-4 w-4 shrink-0 text-slate-400" />
                                </button>
                            ))
                        )}
                    </div>
                    <div className="flex items-center justify-between gap-3 border-t border-slate-100 bg-slate-50 px-4 py-3">
                        <span className="truncate text-sm font-medium text-slate-800">ใช้: {selectedFolder.name}</span>
                        <Button type="button" size="sm" onClick={save} disabled={saving || loading}>
                            {saving ? <LoaderCircle className="mr-2 h-4 w-4 animate-spin" /> : <CheckCircle2 className="mr-2 h-4 w-4" />}
                            {saving ? "กำลังบันทึก" : "ใช้โฟลเดอร์นี้"}
                        </Button>
                    </div>
                </div>

                {error && <div role="alert" className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}
                <div className="flex items-center justify-between gap-3 border-t border-slate-100 pt-3">
                    <button type="button" className="text-xs font-medium text-slate-500 underline underline-offset-2 hover:text-slate-700" onClick={onAdvanced}>ตั้งค่าแบบผู้ดูแลระบบ</button>
                    <Button type="button" variant="outline" onClick={onClose}>ยกเลิก</Button>
                </div>
            </div>
        </Modal>
    )
}

function DriveTestButton({ id }: { id: string }) {
    const [loading, setLoading] = useState(false)
    const [result, setResult] = useState<string | null>(null)
    const run = async () => {
        const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
        if (!token) return
        setLoading(true)
        setResult(null)
        try {
            const res = await testDriveIntegration(token, id)
            setResult("✓ เชื่อมต่อสำเร็จ: " + JSON.stringify(res.detail))
        } catch (e) {
            setResult("✗ " + (e instanceof Error ? e.message : "ล้มเหลว"))
        } finally {
            setLoading(false)
        }
    }
    return (
        <div className="space-y-2 pt-3 border-t">
            <Button type="button" variant="outline" onClick={run} disabled={loading}>
                {loading ? "กำลังทดสอบ…" : "ทดสอบการเชื่อมต่อ"}
            </Button>
            <p className="text-xs text-slate-500">ทดสอบ credential ที่บันทึกไว้ล่าสุด (กด Save ก่อนถ้าเพิ่งแก้ไข)</p>
            {result && (
                <div className={`p-3 rounded-md text-sm font-mono whitespace-pre-wrap break-all ${result.startsWith("✓") ? "bg-green-50 text-green-800 border border-green-200" : "bg-red-50 text-red-800 border border-red-200"}`}>
                    {result}
                </div>
            )}
        </div>
    )
}

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
    const [testInput, setTestInput] = useState("")
    const [testResult, setTestResult] = useState<string | null>(null)
    const [testLoading, setTestLoading] = useState(false)
    const [showInstructionsExpanded, setShowInstructionsExpanded] = useState(false)
    const [expandedInstructions, setExpandedInstructions] = useState("")
    const [showUserPromptExpanded, setShowUserPromptExpanded] = useState(false)
    const [expandedUserPrompt, setExpandedUserPrompt] = useState("")
    const [showOutputFormatExpanded, setShowOutputFormatExpanded] = useState(false)
    const [expandedOutputFormat, setExpandedOutputFormat] = useState("")
    const [loading, setLoading] = useState(false)
    const [expandedIntegrations, setExpandedIntegrations] = useState<Record<string, boolean>>({})
    const [showTemplateModal, setShowTemplateModal] = useState(false)
    const [templateCategory, setTemplateCategory] = useState<"all" | TemplateCategory>("all")
    const [cloudWizardIntegration, setCloudWizardIntegration] = useState<Integration | null>(null)

    useEffect(() => {
        loadIntegrations()
    }, [token])

    useEffect(() => {
        if (!token || integrations.length === 0 || typeof window === "undefined") return
        const params = new URLSearchParams(window.location.search)
        const oauthStatus = params.get("oauth")
        const integrationId = params.get("integration_id")
        if (oauthStatus === "success" && integrationId) {
            const connected = integrations.find((item) => item.id === integrationId)
            if (connected) setCloudWizardIntegration(connected)
            window.history.replaceState({}, "", window.location.pathname)
        } else if (oauthStatus === "error") {
            const message = params.get("message") || "เชื่อมต่อ cloud storage ไม่สำเร็จ"
            window.history.replaceState({}, "", window.location.pathname)
            alert(message)
        }
    }, [integrations, token])

    const loadIntegrations = async () => {
        if (!token) return
        setLoading(true)
        try {
            const data = await getIntegrations(token)
            setIntegrations(data.integrations as Integration[])
            await migrateLocalStorageData()
        } catch (err) {
            console.error("Failed to load integrations:", err)
        } finally {
            setLoading(false)
        }
    }

    const toggleIntegrationDetails = (integrationId: string) => {
        setExpandedIntegrations((prev) => ({ ...prev, [integrationId]: !prev[integrationId] }))
    }

    const migrateLocalStorageData = async () => {
        if (!token) return
        const migrated = localStorage.getItem("integrations_migrated")
        if (migrated === "true") return
        const stored = localStorage.getItem("integrations")
        if (!stored) { localStorage.setItem("integrations_migrated", "true"); return }
        try {
            const localIntegrations = JSON.parse(stored) as Integration[]
            const { integrations: dbIntegrations } = await getIntegrations(token)
            if (dbIntegrations.length > 0) { localStorage.setItem("integrations_migrated", "true"); return }
            for (const integration of localIntegrations) {
                try {
                    await createIntegration(token, {
                        name: integration.name, type: integration.type,
                        description: integration.description || "", status: integration.status, config: integration.config,
                    })
                } catch (error) { console.error(`Failed to migrate: ${integration.name}`, error) }
            }
            await loadIntegrations()
            localStorage.setItem("integrations_migrated", "true")
        } catch (error) { console.error("Migration failed:", error) }
    }

    const filteredTemplates = templateCategory === "all"
        ? LLM_TEMPLATES
        : LLM_TEMPLATES.filter(t => t.category === templateCategory)

    const startCloudOAuth = async (type: "gdrive" | "onedrive") => {
        if (!token) return
        try {
            const provider = type === "gdrive" ? "google" : "microsoft"
            const result = await getCloudOAuthStart(token, provider)
            window.location.assign(result.authorization_url)
        } catch (err) {
            const message = err instanceof Error ? err.message : "เริ่มเชื่อมต่อ cloud storage ไม่สำเร็จ"
            alert(message)
            if (!isUser) openManualCloud(type)
        }
    }

    const openManualCloud = (type: "gdrive" | "onedrive") => {
        setFormState({ ...defaultFormState, type })
        setEditingId(null)
        setTestResult(null)
        setTestInput("")
        setShowForm(true)
    }

    const openCreate = (type?: IntegrationType) => {
        if (type === "gdrive" || type === "onedrive") {
            startCloudOAuth(type)
            return
        }
        setFormState({
            ...defaultFormState,
            type: type || "api",
            ...(type === "softnix_genai" ? { baseUrl: SOFTNIX_GENAI_BASE_URL } : {}),
        })
        setEditingId(null)
        setTestResult(null)
        setTestInput("")
        setShowForm(true)
    }

    const applyTemplate = (template: LLMIntegrationTemplate) => {
        setShowTemplateModal(false)
        setTemplateCategory("all")
        setFormState({
            ...defaultFormState, type: "llm",
            name: template.name, description: template.description,
            model: template.config.model, instructions: template.config.instructions,
            userPrompt: template.config.userPrompt, outputFormatPrompt: template.config.outputFormatPrompt,
            reasoningEffort: template.config.reasoningEffort,
        })
        setEditingId(null)
        setShowForm(true)
    }

    const openEdit = (integration: Integration) => {
        if ((integration.type === "gdrive" || integration.type === "onedrive") && integration.config.auth_mode === "oauth") {
            setCloudWizardIntegration(integration)
            return
        }
        setFormState({
            name: integration.name, type: integration.type,
            description: integration.description || "", status: integration.status,
            method: (integration.config.method as "POST" | "PUT") || "POST",
            endpoint: integration.config.endpoint || "",
            authHeader: integration.config.authHeader || "",
            headersJson: integration.config.headersJson || "",
            payloadTemplate: integration.config.payloadTemplate || "",
            webhookUrl: integration.config.webhookUrl || "",
            parameters: integration.config.parameters || "",
            model: integration.config.model || "",
            apiKey: integration.config.apiKey || "",
            baseUrl: integration.config.baseUrl || (integration.type === "softnix_genai" ? SOFTNIX_GENAI_BASE_URL : ""),
            instructions: integration.config.instructions || "",
            userPrompt: integration.config.userPrompt || "",
            outputFormatPrompt: integration.config.outputFormatPrompt || "",
            reasoningEffort: integration.config.reasoningEffort || "low",
            serviceAccountJson: integration.config.client_email
                ? JSON.stringify({ client_email: integration.config.client_email, private_key: integration.config.private_key, token_uri: integration.config.token_uri || "https://oauth2.googleapis.com/token" }, null, 2)
                : "",
            tenant_id: integration.config.tenant_id || "",
            client_id: integration.config.client_id || "",
            client_secret: integration.config.client_secret || "",
            drive_id: integration.config.drive_id || "",
        })
        setEditingId(integration.id)
        setTestResult(null)
        setTestInput("")
        setShowForm(true)
    }

    const handleDelete = async (id: string) => {
        const integration = integrations.find(i => i.id === id)
        if (!integration) return
        const ownsOAuthConnection = integration.config.auth_mode === "oauth" && integration.user_id === user?.id
        if (isUser && !ownsOAuthConnection) { alert("Users cannot delete integrations"); return }
        if (isManager && integration.user_id !== user?.id) { alert("Managers can only delete their own integrations"); return }
        if (!confirm(ownsOAuthConnection ? "ยกเลิกการเชื่อมต่อบัญชีนี้หรือไม่?" : "Delete this integration?")) return
        if (!token) return
        try {
            await deleteIntegration(token, id)
            setIntegrations(integrations.filter((item) => item.id !== id))
        } catch (err) { alert(err instanceof Error ? err.message : "Failed to delete integration") }
    }

    const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
        e.preventDefault()
        if (isUser) { alert("Users cannot create or edit integrations"); return }
        if (editingId && isManager) {
            const integration = integrations.find(i => i.id === editingId)
            if (integration && integration.user_id !== user?.id) { alert("Managers can only edit their own integrations"); return }
        }
        if (!token) { alert("Please login to continue"); return }
        setLoading(true)

        let configData: Record<string, any>
        if (formState.type === "gdrive") {
            let sa: any
            try { sa = JSON.parse(formState.serviceAccountJson) } catch {
                setLoading(false); alert("Service Account JSON ไม่ถูกต้อง — กรุณาวางไฟล์ JSON ทั้งไฟล์"); return
            }
            if (!sa.client_email || !sa.private_key) {
                setLoading(false); alert("Service Account JSON ต้องมี client_email และ private_key"); return
            }
            configData = { client_email: sa.client_email, private_key: sa.private_key, token_uri: sa.token_uri || "https://oauth2.googleapis.com/token" }
        } else if (formState.type === "onedrive") {
            configData = { tenant_id: formState.tenant_id, client_id: formState.client_id, client_secret: formState.client_secret, drive_id: formState.drive_id }
        } else {
            configData = {
                method: formState.method, endpoint: formState.endpoint, authHeader: formState.authHeader,
                headersJson: formState.headersJson, payloadTemplate: formState.payloadTemplate,
                webhookUrl: formState.webhookUrl, parameters: formState.parameters,
                model: formState.model,
                apiKey: formState.apiKey,
                baseUrl: formState.type === "softnix_genai" ? SOFTNIX_GENAI_BASE_URL : formState.baseUrl,
                instructions: formState.instructions, userPrompt: formState.userPrompt,
                outputFormatPrompt: formState.outputFormatPrompt, reasoningEffort: formState.reasoningEffort,
            }
        }

        try {
            if (editingId) {
                const updated = await updateIntegration(token, editingId, { name: formState.name, type: formState.type, description: formState.description, status: formState.status, config: configData })
                setIntegrations(integrations.map((item) => (item.id === editingId ? updated as Integration : item)))
            } else {
                const created = await createIntegration(token, { name: formState.name, type: formState.type, description: formState.description, status: formState.status, config: configData })
                setIntegrations([...integrations, created as Integration])
            }
            setShowForm(false)
            setFormState(defaultFormState)
            setEditingId(null)
        } catch (err) {
            alert(err instanceof Error ? err.message : "Failed to save integration")
        } finally { setLoading(false) }
    }

    const parseCurlCommand = (curlText: string) => {
        const result: Partial<IntegrationConfig> & { name?: string } = {}
        const methodMatch = curlText.match(/-X\s+([A-Z]+)/i)
        if (methodMatch) result.method = methodMatch[1].toUpperCase() as "POST" | "PUT"
        const urlMatch = curlText.match(/https?:\/\/[^\s"'\\]+/i)
        if (urlMatch) result.endpoint = urlMatch[0].replace(/["'\\]+$/g, "")
        const headerRegex = /-H\s+['\"]([^'\"]+)['\"]/gi
        const headers: Record<string, string> = {}
        let hMatch
        while ((hMatch = headerRegex.exec(curlText)) !== null) {
            const [key, ...rest] = hMatch[1].split(":")
            if (key && rest.length) headers[key.trim()] = rest.join(":").trim()
        }
        if (Object.keys(headers).length) {
            result.headersJson = JSON.stringify(headers, null, 2)
            const auth = Object.entries(headers).filter(([k]) => /auth|token|key/i.test(k)).map(([k, v]) => `${k}: ${v}`).join("\n")
            if (auth) result.authHeader = auth
        }
        const dataMatch = curlText.match(/(--data-raw|--data|-d)\s+(['\"])([\s\S]*?)\2/i)
        if (dataMatch) {
            const raw = dataMatch[3]
            try { result.payloadTemplate = JSON.stringify(JSON.parse(raw), null, 2) } catch { result.payloadTemplate = raw }
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
                                    <Button type="button" size="sm" variant="outline"
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
                                        }} disabled={!curlInput.trim()}>Apply</Button>
                                )}
                            </div>
                            <Textarea
                                placeholder='curl -X POST "https://api.example.com" -H "Authorization: Bearer token" -H "Content-Type: application/json" -d "{\"foo\":\"bar\"}"'
                                value={curlInput} onChange={(e) => setCurlInput(e.target.value)} rows={3} disabled={isUser} />
                        </div>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <div className="space-y-2">
                                <label className="text-sm font-medium">HTTP Method</label>
                                <select className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm"
                                    value={formState.method} onChange={(e) => setFormState({ ...formState, method: e.target.value as "POST" | "PUT" })} required disabled={isUser}>
                                    <option value="POST">POST</option>
                                    <option value="PUT">PUT</option>
                                </select>
                            </div>
                            <div className="space-y-2">
                                <label className="text-sm font-medium">Endpoint URL</label>
                                <Input required placeholder="https://api.example.com/v1/ingest"
                                    value={formState.endpoint} onChange={(e) => setFormState({ ...formState, endpoint: e.target.value })} disabled={isUser} />
                            </div>
                        </div>
                        <div className="space-y-2">
                            <label className="text-sm font-medium">Authorization / Headers</label>
                            <Textarea placeholder="Authorization: Bearer <token>" value={formState.authHeader}
                                onChange={(e) => setFormState({ ...formState, authHeader: e.target.value })} disabled={isUser} />
                        </div>
                        <div className="space-y-2">
                            <label className="text-sm font-medium">Headers (JSON)</label>
                            <Textarea placeholder={'{\n  "Authorization": "Bearer <token>"\n}'} value={formState.headersJson}
                                onChange={(e) => setFormState({ ...formState, headersJson: e.target.value })} disabled={isUser} rows={4} />
                        </div>
                        <div className="space-y-2">
                            <label className="text-sm font-medium">Payload Template</label>
                            <Textarea placeholder='{ "document_id": "<uuid>", "payload": {} }' value={formState.payloadTemplate}
                                onChange={(e) => setFormState({ ...formState, payloadTemplate: e.target.value })} rows={5} disabled={isUser} />
                        </div>
                        <div className="space-y-2">
                            <label className="text-sm font-medium">Required Parameters</label>
                            <Input placeholder="document_id, file_url, fields" value={formState.parameters}
                                onChange={(e) => setFormState({ ...formState, parameters: e.target.value })} disabled={isUser} />
                        </div>
                    </div>
                )
            case "llm":
            case "softnix_genai":
                {
                const isSoftnixGenAI = formState.type === "softnix_genai"
                return (
                    <div className="space-y-4 p-4 bg-slate-50 rounded-lg border">
                        <div className="text-sm font-semibold text-slate-700">
                            {isSoftnixGenAI ? "Softnix GenAI API Settings" : "LLM API Settings"}
                        </div>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <div className="space-y-2">
                                <label className="text-sm font-medium">API Key *</label>
                                <Input type="password" placeholder="sk-..." value={formState.apiKey}
                                    onChange={(e) => setFormState({ ...formState, apiKey: e.target.value })} disabled={isUser} required />
                            </div>
                            <div className="space-y-2">
                                <label className="text-sm font-medium">{isSoftnixGenAI ? "API Endpoint" : "Base URL (Optional)"}</label>
                                <Input
                                    placeholder={isSoftnixGenAI ? SOFTNIX_GENAI_BASE_URL : "https://api.openai.com/v1 (default)"}
                                    value={isSoftnixGenAI ? SOFTNIX_GENAI_BASE_URL : formState.baseUrl}
                                    onChange={(e) => setFormState({ ...formState, baseUrl: e.target.value })}
                                    disabled={isUser || isSoftnixGenAI}
                                    readOnly={isSoftnixGenAI}
                                />
                                <p className="text-xs text-slate-500">
                                    {isSoftnixGenAI ? "ระบบจะเรียก Chat Completions และเติม /chat/completions ให้อัตโนมัติ" : "Leave empty for OpenAI. Use provider base URL such as https://openrouter.ai/api/v1."}
                                </p>
                            </div>
                        </div>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <div className="space-y-2">
                                <label className="text-sm font-medium">Model *</label>
                                <Input placeholder="gpt-4o-mini, openai/gpt-4o-mini, anthropic/claude-..." value={formState.model}
                                    onChange={(e) => setFormState({ ...formState, model: e.target.value })} disabled={isUser} required />
                                <p className="text-xs text-slate-500">Use the exact model id from your provider.</p>
                            </div>
                            <div className="space-y-2">
                                <label className="text-sm font-medium">Reasoning Effort</label>
                                <select className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm"
                                    value={formState.reasoningEffort} onChange={(e) => setFormState({ ...formState, reasoningEffort: e.target.value as "low" | "medium" | "high" })}
                                    disabled={isUser} title="Select Reasoning Effort Level">
                                    <option value="low">Low</option>
                                    <option value="medium">Medium</option>
                                    <option value="high">High</option>
                                </select>
                            </div>
                        </div>
                        <div className="space-y-2">
                            <label className="text-sm font-medium">Instructions *</label>
                            <div className="relative">
                                <Textarea placeholder="Enter instructions for LLM to process extracted data..."
                                    value={formState.instructions} onChange={(e) => setFormState({ ...formState, instructions: e.target.value })}
                                    disabled={isUser} rows={6} className="resize-y min-h-[120px] pr-8" required />
                                {!isUser && (
                                    <button type="button" title="Expand editor"
                                        onClick={() => { setExpandedInstructions(formState.instructions); setShowInstructionsExpanded(true) }}
                                        className="absolute bottom-2 right-2 p-1 text-slate-400 hover:text-slate-700 hover:bg-slate-100 rounded transition-colors">
                                        <Maximize2 className="h-3.5 w-3.5" />
                                    </button>
                                )}
                            </div>
                            <p className="text-xs text-slate-500">System instructions — defines role and behavior.</p>
                        </div>
                        <div className="space-y-2">
                            <div className="flex items-center gap-2">
                                <label className="text-sm font-medium">User Prompt</label>
                                <span className="text-xs text-slate-400">(optional)</span>
                            </div>
                            <div className="relative">
                                <Textarea placeholder="e.g. Compare the following documents and highlight discrepancies..."
                                    value={formState.userPrompt} onChange={(e) => setFormState({ ...formState, userPrompt: e.target.value })}
                                    disabled={isUser} rows={4} className="resize-y min-h-[90px] pr-8" />
                                {!isUser && (
                                    <button type="button" title="Expand editor"
                                        onClick={() => { setExpandedUserPrompt(formState.userPrompt); setShowUserPromptExpanded(true) }}
                                        className="absolute bottom-2 right-2 p-1 text-slate-400 hover:text-slate-700 hover:bg-slate-100 rounded transition-colors">
                                        <Maximize2 className="h-3.5 w-3.5" />
                                    </button>
                                )}
                            </div>
                        </div>
                        <div className="space-y-2">
                            <div className="flex items-center gap-2">
                                <label className="text-sm font-medium">Output Format Prompt</label>
                                <span className="text-xs text-slate-400">(optional)</span>
                            </div>
                            <div className="relative">
                                <Textarea placeholder="e.g. Respond in JSON with keys: summary, discrepancies, recommendation."
                                    value={formState.outputFormatPrompt} onChange={(e) => setFormState({ ...formState, outputFormatPrompt: e.target.value })}
                                    disabled={isUser} rows={3} className="resize-y min-h-[72px] pr-8" />
                                {!isUser && (
                                    <button type="button" title="Expand editor"
                                        onClick={() => { setExpandedOutputFormat(formState.outputFormatPrompt); setShowOutputFormatExpanded(true) }}
                                        className="absolute bottom-2 right-2 p-1 text-slate-400 hover:text-slate-700 hover:bg-slate-100 rounded transition-colors">
                                        <Maximize2 className="h-3.5 w-3.5" />
                                    </button>
                                )}
                            </div>
                        </div>
                        <div className="rounded-md bg-white border border-slate-200 p-3 text-xs text-slate-500 space-y-1">
                            <p className="font-semibold text-slate-600">Input sent to LLM:</p>
                            <p><span className="font-mono bg-slate-50 border border-slate-200 rounded px-1">User Prompt</span> + <span className="font-mono bg-blue-50 border border-blue-200 text-blue-700 rounded px-1">{'{{OCR Data}}'}</span> + <span className="font-mono bg-slate-50 border border-slate-200 rounded px-1">Output Format Prompt</span></p>
                        </div>
                        <div className="space-y-3 pt-4 border-t">
                            <div className="text-sm font-semibold text-slate-700">Test Connection</div>
                            <Button type="button" variant="outline"
                                onClick={async () => {
                                    if (!formState.apiKey || !formState.model) { alert("Please fill in API Key and Model first"); return }
                                    setTestLoading(true); setTestResult(null)
                                    try {
                                        const response = await fetch(`${getApiBaseUrl()}/integrations/test-llm`, {
                                            method: "POST",
                                            headers: { "Content-Type": "application/json", "Authorization": `Bearer ${localStorage.getItem("token")}` },
                                            body: JSON.stringify({ apiKey: formState.apiKey, baseUrl: formState.baseUrl || undefined, model: formState.model, reasoningEffort: formState.reasoningEffort, instructions: formState.instructions })
                                        })
                                        handleAuthError(response)
                                        const data = await response.json()
                                        setTestResult(response.ok ? `✓ ${data.output || "Success!"}` : `✗ Error: ${data.detail || "Test failed"}`)
                                    } catch (error) {
                                        setTestResult(`✗ Error: ${error instanceof Error ? error.message : "Network error"}`)
                                    } finally { setTestLoading(false) }
                                }} disabled={isUser || testLoading}>
                                {testLoading ? "Testing..." : "Test Connection"}
                            </Button>
                            {testResult && (
                                <div className={`p-3 rounded-md text-sm font-mono whitespace-pre-wrap ${testResult.startsWith("✓") ? "bg-green-50 text-green-800 border border-green-200" : "bg-red-50 text-red-800 border border-red-200"}`}>
                                    {testResult}
                                </div>
                            )}
                        </div>
                    </div>
                )
                }
            case "workflow":
                return (
                    <div className="space-y-4">
                        <div className="space-y-2">
                            <label className="text-sm font-medium">Webhook URL</label>
                            <Input required placeholder="https://hooks.n8n.cloud/webhook/..." value={formState.webhookUrl}
                                onChange={(e) => setFormState({ ...formState, webhookUrl: e.target.value })} disabled={isUser} />
                        </div>
                        <div className="space-y-2">
                            <label className="text-sm font-medium">Parameters to send</label>
                            <Textarea placeholder="jobId, status, payload, confidence" value={formState.parameters}
                                onChange={(e) => setFormState({ ...formState, parameters: e.target.value })} disabled={isUser} rows={3} />
                        </div>
                        <div className="space-y-3 pt-4 border-t">
                            <div className="text-sm font-semibold text-slate-700">Test Connection</div>
                            <div className="space-y-2">
                                <label className="text-sm font-medium">Test Payload (JSON)</label>
                                <Textarea placeholder='{"test": true, "message": "Connection test from InsightDOC"}' value={testInput}
                                    onChange={(e) => setTestInput(e.target.value)} disabled={isUser || testLoading} rows={3} />
                            </div>
                            <Button type="button" variant="outline"
                                onClick={async () => {
                                    if (!formState.webhookUrl?.trim()) { alert("Please enter a webhook URL first"); return }
                                    setTestLoading(true); setTestResult(null)
                                    try {
                                        let payload: any = { test: true, message: "Connection test from InsightDOC", timestamp: new Date().toISOString() }
                                        if (testInput.trim()) {
                                            try { payload = JSON.parse(testInput) } catch { setTestResult("Error: Invalid JSON format"); setTestLoading(false); return }
                                        }
                                        const response = await fetch(formState.webhookUrl, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) })
                                        const contentType = response.headers.get("content-type")
                                        const responseData = contentType?.includes("application/json") ? JSON.stringify(await response.json(), null, 2) : await response.text()
                                        setTestResult(response.ok ? `✓ Success! (Status: ${response.status})\n\nResponse:\n${responseData || "No response body"}` : `✗ Failed! (Status: ${response.status})\n\nError:\n${responseData}`)
                                    } catch (error) {
                                        setTestResult(`✗ Error: ${error instanceof Error ? error.message : "Network error"}`)
                                    } finally { setTestLoading(false) }
                                }} disabled={isUser || testLoading || !formState.webhookUrl}>
                                {testLoading ? "Testing..." : "Test Connection"}
                            </Button>
                            {testResult && (
                                <div className={`p-3 rounded-md text-sm font-mono whitespace-pre-wrap ${testResult.startsWith("✓") ? "bg-green-50 text-green-800 border border-green-200" : "bg-red-50 text-red-800 border border-red-200"}`}>
                                    {testResult}
                                </div>
                            )}
                        </div>
                    </div>
                )
            case "gdrive":
                return (
                    <div className="space-y-4 p-4 bg-slate-50 rounded-lg border">
                        <div className="text-sm font-semibold text-slate-700">Google Drive — Service Account</div>
                        <div className="space-y-2">
                            <label className="text-sm font-medium">Service Account JSON *</label>
                            <Textarea
                                placeholder='{ "type": "service_account", "client_email": "...", "private_key": "-----BEGIN PRIVATE KEY-----\\n..." }'
                                value={formState.serviceAccountJson} onChange={(e) => setFormState({ ...formState, serviceAccountJson: e.target.value })}
                                disabled={isUser} rows={8} className="font-mono text-xs" />
                            <p className="text-xs text-slate-500">
                                วางทั้งไฟล์ service-account JSON จาก Google Cloud — และ <span className="font-semibold">แชร์โฟลเดอร์ปลายทางใน Drive ให้อีเมล client_email</span> ของ service account นี้
                            </p>
                        </div>
                        {editingId && <DriveTestButton id={editingId} />}
                    </div>
                )
            case "onedrive":
                return (
                    <div className="space-y-4 p-4 bg-slate-50 rounded-lg border">
                        <div className="text-sm font-semibold text-slate-700">OneDrive / SharePoint — Azure App (client credentials)</div>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <div className="space-y-2">
                                <label className="text-sm font-medium">Tenant ID *</label>
                                <Input value={formState.tenant_id} disabled={isUser} onChange={(e) => setFormState({ ...formState, tenant_id: e.target.value })} />
                            </div>
                            <div className="space-y-2">
                                <label className="text-sm font-medium">Client ID *</label>
                                <Input value={formState.client_id} disabled={isUser} onChange={(e) => setFormState({ ...formState, client_id: e.target.value })} />
                            </div>
                            <div className="space-y-2">
                                <label className="text-sm font-medium">Client Secret *</label>
                                <Input type="password" value={formState.client_secret} disabled={isUser} onChange={(e) => setFormState({ ...formState, client_secret: e.target.value })} />
                            </div>
                            <div className="space-y-2">
                                <label className="text-sm font-medium">Drive ID *</label>
                                <Input value={formState.drive_id} disabled={isUser} onChange={(e) => setFormState({ ...formState, drive_id: e.target.value })} />
                            </div>
                        </div>
                        <p className="text-xs text-slate-500">
                            Azure app registration ต้องมีสิทธิ์ <span className="font-mono">Files.ReadWrite.All</span> (application) และ admin consent
                        </p>
                        {editingId && <DriveTestButton id={editingId} />}
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
                            <span className="font-semibold">Method:</span><span>{integration.config.method}</span>
                        </div>
                        <div>
                            <div className="font-semibold">Endpoint</div>
                            <div className="text-slate-600 break-all">{integration.config.endpoint}</div>
                        </div>
                        {(integration.config.authHeader || integration.config.headersJson) && (
                            <div className="space-y-1">
                                <div className="font-semibold">Headers</div>
                                {integration.config.authHeader && <pre className="mt-1 rounded-md bg-slate-50 p-3 text-xs text-slate-800 whitespace-pre-wrap">{integration.config.authHeader}</pre>}
                                {integration.config.headersJson && <pre className="mt-1 rounded-md bg-slate-50 p-3 text-xs text-slate-800 whitespace-pre-wrap">{integration.config.headersJson}</pre>}
                            </div>
                        )}
                        {integration.config.payloadTemplate && (
                            <div>
                                <div className="font-semibold">Payload Template</div>
                                <pre className="mt-1 rounded-md bg-slate-50 p-3 text-xs text-slate-800 whitespace-pre-wrap">{integration.config.payloadTemplate}</pre>
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
                            <div><div className="font-semibold">Parameters</div><div className="text-slate-600">{integration.config.parameters}</div></div>
                        )}
                    </div>
                )
            case "llm":
            case "softnix_genai":
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
                            <div><span className="font-semibold">{integration.type === "softnix_genai" ? "API Endpoint:" : "Base URL:"}</span><span className="ml-2 text-slate-600 break-all">{integration.config.baseUrl || (integration.type === "softnix_genai" ? SOFTNIX_GENAI_BASE_URL : "")}</span></div>
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
        <div className="space-y-8">
            {/* ─── Expanded text modals ─── */}
            {showUserPromptExpanded && (
                <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
                    <div className="bg-white rounded-xl shadow-2xl w-full max-w-3xl flex flex-col" style={{ height: "80vh" }}>
                        <div className="flex items-center justify-between px-5 py-4 border-b">
                            <h3 className="text-base font-semibold text-slate-800">User Prompt</h3>
                            <div className="flex gap-2">
                                <Button type="button" variant="outline" size="sm" onClick={() => setShowUserPromptExpanded(false)}>Cancel</Button>
                                <Button type="button" size="sm" onClick={() => { setFormState(prev => ({ ...prev, userPrompt: expandedUserPrompt })); setShowUserPromptExpanded(false) }}>Done</Button>
                            </div>
                        </div>
                        <textarea className="flex-1 w-full resize-none p-4 text-sm text-slate-800 focus:outline-none font-mono leading-relaxed"
                            placeholder="Enter user prompt..." value={expandedUserPrompt} onChange={(e) => setExpandedUserPrompt(e.target.value)} autoFocus />
                    </div>
                </div>
            )}
            {showOutputFormatExpanded && (
                <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
                    <div className="bg-white rounded-xl shadow-2xl w-full max-w-3xl flex flex-col" style={{ height: "80vh" }}>
                        <div className="flex items-center justify-between px-5 py-4 border-b">
                            <h3 className="text-base font-semibold text-slate-800">Output Format Prompt</h3>
                            <div className="flex gap-2">
                                <Button type="button" variant="outline" size="sm" onClick={() => setShowOutputFormatExpanded(false)}>Cancel</Button>
                                <Button type="button" size="sm" onClick={() => { setFormState(prev => ({ ...prev, outputFormatPrompt: expandedOutputFormat })); setShowOutputFormatExpanded(false) }}>Done</Button>
                            </div>
                        </div>
                        <textarea className="flex-1 w-full resize-none p-4 text-sm text-slate-800 focus:outline-none font-mono leading-relaxed"
                            placeholder="Enter output format prompt..." value={expandedOutputFormat} onChange={(e) => setExpandedOutputFormat(e.target.value)} autoFocus />
                    </div>
                </div>
            )}
            {showInstructionsExpanded && (
                <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
                    <div className="bg-white rounded-xl shadow-2xl w-full max-w-3xl flex flex-col" style={{ height: "80vh" }}>
                        <div className="flex items-center justify-between px-5 py-4 border-b">
                            <h3 className="text-base font-semibold text-slate-800">Instructions</h3>
                            <div className="flex gap-2">
                                <Button type="button" variant="outline" size="sm" onClick={() => setShowInstructionsExpanded(false)}>Cancel</Button>
                                <Button type="button" size="sm" onClick={() => { setFormState(prev => ({ ...prev, instructions: expandedInstructions })); setShowInstructionsExpanded(false) }}>Done</Button>
                            </div>
                        </div>
                        <textarea className="flex-1 w-full resize-none p-4 text-sm text-slate-800 focus:outline-none font-mono leading-relaxed"
                            placeholder="Enter instructions..." value={expandedInstructions} onChange={(e) => setExpandedInstructions(e.target.value)} autoFocus />
                    </div>
                </div>
            )}

            {/* ─── Template Browser Modal ─── */}
            {showTemplateModal && (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
                    <div className="bg-white rounded-xl shadow-2xl w-full max-w-5xl flex flex-col" style={{ maxHeight: "calc(100vh - 4rem)" }}>
                        <div className="flex items-center justify-between px-6 py-4 border-b shrink-0">
                            <div>
                                <h2 className="text-xl font-semibold text-slate-900">Add From Template</h2>
                                <p className="text-sm text-slate-500 mt-0.5">เลือกเทมเพลตสำเร็จรูปเพื่อเริ่มต้นอย่างรวดเร็ว — เพิ่มเพียง API Key และปรับแต่งตามต้องการ</p>
                            </div>
                            <button type="button" onClick={() => { setShowTemplateModal(false); setTemplateCategory("all") }}
                                className="text-slate-400 hover:text-slate-600 transition-colors p-1 rounded">
                                <X className="h-5 w-5" />
                            </button>
                        </div>
                        <div className="px-6 py-3 bg-slate-50 border-b shrink-0">
                            <div className="flex flex-wrap gap-2">
                                <button type="button" onClick={() => setTemplateCategory("all")}
                                    className={`px-3 py-1 rounded-full text-sm font-medium transition-colors ${templateCategory === "all" ? "bg-slate-900 text-white" : "bg-white text-slate-600 border border-slate-200 hover:border-slate-300"}`}>
                                    ทั้งหมด ({LLM_TEMPLATES.length})
                                </button>
                                {(Object.keys(TEMPLATE_CATEGORIES) as TemplateCategory[]).map(cat => {
                                    const catInfo = TEMPLATE_CATEGORIES[cat]
                                    const count = LLM_TEMPLATES.filter(t => t.category === cat).length
                                    return (
                                        <button key={cat} type="button" onClick={() => setTemplateCategory(cat)}
                                            className={`px-3 py-1 rounded-full text-sm font-medium transition-colors ${templateCategory === cat ? "bg-slate-900 text-white" : "bg-white text-slate-600 border border-slate-200 hover:border-slate-300"}`}>
                                            {catInfo.labelTh} ({count})
                                        </button>
                                    )
                                })}
                            </div>
                        </div>
                        <div className="overflow-y-auto flex-1 p-6">
                            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                                {filteredTemplates.map(template => {
                                    const cat = TEMPLATE_CATEGORIES[template.category]
                                    const IconComp = TEMPLATE_ICONS[template.icon] ?? LayoutTemplate
                                    return (
                                        <div key={template.id} className="bg-white border border-slate-200 rounded-lg p-4 flex flex-col gap-3 hover:border-slate-300 hover:shadow-sm transition-all">
                                            <div className="flex items-center gap-2">
                                                <div className={`w-12 h-12 rounded-2xl flex items-center justify-center shrink-0 shadow-sm ${cat.iconBgClass}`}>
                                                    <IconComp className={`h-6 w-6 ${cat.iconColorClass}`} />
                                                </div>
                                                <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${cat.badgeClass}`}>{cat.labelTh}</span>
                                            </div>
                                            <h3 className="font-semibold text-slate-900 text-sm leading-snug">{template.name}</h3>
                                            <p className="text-xs text-slate-500 leading-relaxed flex-1">{template.description}</p>
                                            <div className="flex flex-wrap gap-1">
                                                {template.tags.slice(0, 4).map(tag => (
                                                    <span key={tag} className="text-xs bg-slate-100 text-slate-600 px-2 py-0.5 rounded">{tag}</span>
                                                ))}
                                            </div>
                                            <div className="flex items-center justify-between pt-1 border-t border-slate-100">
                                                <span className="text-xs text-slate-400 capitalize">{template.config.model} · reasoning: {template.config.reasoningEffort}</span>
                                                <Button size="sm" onClick={() => applyTemplate(template)} className="text-xs h-7 px-3">Use Template</Button>
                                            </div>
                                        </div>
                                    )
                                })}
                            </div>
                        </div>
                    </div>
                </div>
            )}

            {/* ─── Page header ─── */}
            <div className="flex items-start justify-between gap-4">
                <div>
                    <h2 className="text-[1.625rem] font-bold leading-tight text-slate-950">Integrations</h2>
                    <p className="mt-1.5 text-[0.9375rem] leading-6 text-slate-600">Connect outbound channels for the OCR pipeline</p>
                </div>
                {(isAdmin || isManager) && (
                    <Button variant="outline" size="sm" onClick={() => setShowTemplateModal(true)} className="shrink-0">
                        <LayoutTemplate className="mr-2 h-4 w-4" />
                        Templates
                    </Button>
                )}
            </div>

            {/* ─── Integration type catalog ─── */}
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4">
                {CATALOG.map((cat) => {
                    const count = integrations.filter(i => i.type === cat.type).length
                    const activeCount = integrations.filter(i => i.type === cat.type && i.status === "active").length
                    return (
                        <div key={cat.type}
                            className={`bg-white rounded-xl border-2 ${cat.accentColor} p-5 flex flex-col items-center text-center gap-3 transition-all shadow-sm hover:shadow-md`}>
                            {/* Logo */}
                            <div className={`w-16 h-16 rounded-2xl ${cat.iconBg} flex items-center justify-center shadow-sm`}>
                                <LogoImage src={cat.logoUrl} alt={cat.label} FallbackIcon={cat.FallbackIcon} iconColor={cat.iconColor} size="lg" />
                            </div>
                            {/* Name */}
                            <div>
                                <div className="text-[0.9375rem] font-semibold leading-snug text-slate-950">{cat.label}</div>
                                <div className="mt-1 text-[0.8125rem] font-medium leading-5 text-slate-500">{cat.sublabel}</div>
                            </div>
                            {/* Status */}
                            {count > 0 ? (
                                <span className="inline-flex items-center gap-1 rounded-full border border-green-200 bg-green-50 px-2.5 py-1 text-[0.8125rem] font-semibold leading-none text-green-700">
                                    <span className="w-1.5 h-1.5 rounded-full bg-green-500 inline-block" />
                                    {activeCount > 0 ? `${activeCount} active` : `${count} paused`}
                                </span>
                            ) : (
                                <span className="text-[0.8125rem] font-medium leading-none text-slate-500">Not connected</span>
                            )}
                            {/* Add button */}
                            {(isAdmin || isManager || cat.type === "gdrive" || cat.type === "onedrive") && (
                                <div className="w-full space-y-2">
                                    <Button size="sm" variant="outline" className="h-9 w-full text-[0.8125rem]" onClick={() => openCreate(cat.type)}>
                                        <Plus className="h-3 w-3 mr-1" />
                                        {cat.type === "gdrive" || cat.type === "onedrive" ? "Connect" : "Add"}
                                    </Button>
                                    {(isAdmin || isManager) && (cat.type === "gdrive" || cat.type === "onedrive") && (
                                        <button type="button" className="text-xs font-medium text-slate-500 underline underline-offset-2 hover:text-slate-700" onClick={() => openManualCloud(cat.type as "gdrive" | "onedrive")}>
                                            ตั้งค่าแบบผู้ดูแลระบบ
                                        </button>
                                    )}
                                </div>
                            )}
                        </div>
                    )
                })}
            </div>

            {/* ─── Connected integrations list ─── */}
            {integrations.length > 0 && (
                <div className="space-y-3">
                    <h3 className="text-[0.8125rem] font-bold uppercase tracking-[0.08em] text-slate-600">Connected ({integrations.length})</h3>
                    {integrations.map((integration) => {
                        const cat = CATALOG.find(c => c.type === integration.type)
                        return (
                            <div key={integration.id} className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
                                <div className="flex items-center gap-4 p-4 md:p-5">
                                    {/* Small logo */}
                                    <div className={`w-10 h-10 rounded-xl ${cat?.iconBg || "bg-slate-100"} flex items-center justify-center shrink-0`}>
                                        <LogoImage src={cat?.logoUrl || null} alt={cat?.label || integration.type}
                                            FallbackIcon={cat?.FallbackIcon || Plug} iconColor={cat?.iconColor || "text-slate-500"} size="sm" />
                                    </div>
                                    {/* Info */}
                                    <button type="button" className="flex-1 text-left min-w-0" onClick={() => toggleIntegrationDetails(integration.id)}>
                                        <div className="flex items-center gap-2 flex-wrap">
                                            <span className="text-[0.9375rem] font-semibold leading-5 text-slate-950">{integration.name}</span>
                                            <span className={`rounded-full px-2.5 py-1 text-[0.75rem] font-semibold leading-none ${integration.status === "active" ? "bg-green-100 text-green-700" : "bg-amber-100 text-amber-700"}`}>
                                                {integration.status === "active" ? "Active" : "Paused"}
                                            </span>
                                        </div>
                                        {integration.description && (
                                            <p className="mt-1 text-[0.8125rem] font-medium leading-5 text-slate-600 line-clamp-2">{integration.description}</p>
                                        )}
                                    </button>
                                    {/* Type chip */}
                                    <span className="hidden sm:inline-flex shrink-0 rounded-lg bg-slate-100 px-2.5 py-1 text-[0.8125rem] font-semibold leading-none text-slate-600">
                                        {cat?.label || integration.type}
                                    </span>
                                    {/* Actions */}
                                    <div className="flex items-center gap-1 shrink-0">
                                        {isUser && integration.config.auth_mode !== "oauth" ? (
                                            <span className="flex items-center gap-1 text-[0.8125rem] font-medium text-slate-500"><Eye className="h-3.5 w-3.5" />View only</span>
                                        ) : (isAdmin || isManager || (integration.config.auth_mode === "oauth" && integration.user_id === user?.id)) ? (
                                            <>
                                                <Button variant="ghost" size="sm" className="h-8 w-8 p-0" onClick={() => openEdit(integration)} title="แก้ไขการเชื่อมต่อ">
                                                    <Pencil className="h-3.5 w-3.5" />
                                                </Button>
                                                <Button variant="ghost" size="sm" className="h-8 w-8 p-0 text-red-500 hover:text-red-600" onClick={() => handleDelete(integration.id)} title={integration.config.auth_mode === "oauth" ? "ยกเลิกการเชื่อมต่อ" : "ลบ integration"}>
                                                    <Trash2 className="h-3.5 w-3.5" />
                                                </Button>
                                            </>
                                        ) : null}
                                        <button type="button" onClick={() => toggleIntegrationDetails(integration.id)}
                                            className="ml-1 text-slate-400 hover:text-slate-600 p-1 rounded transition-colors">
                                            {expandedIntegrations[integration.id] ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                                        </button>
                                    </div>
                                </div>
                                {expandedIntegrations[integration.id] && (
                                    <div className="px-4 pb-4 border-t border-slate-100">
                                        <div className="pt-3">{renderConfigDetails(integration)}</div>
                                    </div>
                                )}
                            </div>
                        )
                    })}
                </div>
            )}

            {integrations.length === 0 && !loading && (
                <div className="text-center py-16 text-slate-400">
                    <Plug className="h-10 w-10 mx-auto mb-3 opacity-30" />
                    <p className="text-[0.9375rem] font-semibold text-slate-500">No integrations connected yet</p>
                    {(isAdmin || isManager) && <p className="mt-1 text-[0.8125rem] text-slate-500">Click &quot;+ Add&quot; on any card above to get started</p>}
                </div>
            )}

            {cloudWizardIntegration && token && (
                <CloudConnectionWizard
                    integration={cloudWizardIntegration}
                    token={token}
                    onClose={() => setCloudWizardIntegration(null)}
                    onSaved={(updated) => {
                        setIntegrations((items) => items.map((item) => item.id === updated.id ? updated as Integration : item))
                        setCloudWizardIntegration(null)
                    }}
                    onAdvanced={() => {
                        const integration = cloudWizardIntegration
                        setCloudWizardIntegration(null)
                        openManualCloud(integration.type as "gdrive" | "onedrive")
                    }}
                />
            )}

            {/* ─── Create / Edit Modal ─── */}
            <Modal isOpen={showForm} onClose={() => setShowForm(false)} title={editingId ? "Edit Integration" : "Add Integration"}>
                <form className="space-y-4" onSubmit={handleSubmit}>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div className="space-y-2">
                            <label className="text-sm font-medium">Name</label>
                            <Input required value={formState.name} onChange={(e) => setFormState({ ...formState, name: e.target.value })} disabled={isUser} />
                        </div>
                        <div className="space-y-2">
                            <label className="text-sm font-medium">Type</label>
                            <select className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm"
                                value={formState.type}
                                onChange={(e) => {
                                    const nextType = e.target.value as IntegrationType
                                    setFormState((previous) => ({
                                        ...previous,
                                        type: nextType,
                                        baseUrl: nextType === "softnix_genai"
                                            ? SOFTNIX_GENAI_BASE_URL
                                            : previous.type === "softnix_genai" ? "" : previous.baseUrl,
                                    }))
                                }}
                                disabled={isUser}>
                                <option value="api">Custom API</option>
                                <option value="workflow">Workflow / N8N</option>
                                <option value="llm">LLM Provider</option>
                                <option value="softnix_genai">Softnix GenAI</option>
                                <option value="gdrive">Google Drive</option>
                                <option value="onedrive">OneDrive / SharePoint</option>
                            </select>
                        </div>
                        <div className="space-y-2">
                            <label className="text-sm font-medium">Status</label>
                            <select className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm"
                                value={formState.status} onChange={(e) => setFormState({ ...formState, status: e.target.value as "active" | "paused" })} disabled={isUser}>
                                <option value="active">Active</option>
                                <option value="paused">Paused</option>
                            </select>
                        </div>
                    </div>
                    <div className="space-y-2">
                        <label className="text-sm font-medium">Description</label>
                        <Textarea placeholder="Describe what this integration sends" value={formState.description}
                            onChange={(e) => setFormState({ ...formState, description: e.target.value })} disabled={isUser} />
                    </div>

                    {renderTypeFields()}

                    {isUser ? (
                        <div className="flex justify-end">
                            <Button type="button" variant="outline" onClick={() => setShowForm(false)}>Close</Button>
                        </div>
                    ) : (
                        <div className="flex justify-end gap-2">
                            <Button variant="outline" type="button" onClick={() => setShowForm(false)}>Cancel</Button>
                            <Button type="submit" disabled={loading}>{editingId ? "Save changes" : "Create"}</Button>
                        </div>
                    )}
                </form>
            </Modal>
        </div>
    )
}
