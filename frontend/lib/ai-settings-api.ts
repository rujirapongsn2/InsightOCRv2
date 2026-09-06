import { getApiBaseUrl } from "./api"

export interface AIProviderSetting {
  id: string
  name: string
  display_name: string
  api_url: string
  is_active: boolean
  is_default: boolean
  model: string | null
  is_agent_provider: boolean
  supports_tool_calling: boolean
  agent_tools_checked_at?: string | null
  agent_tools_verification_error?: string | null
  is_workflow_builder_provider: boolean
  provider_type: string
  description: string | null
  created_at: string
  updated_at: string | null
}

export type AIProviderTestStatus = "passed" | "failed" | "unavailable" | "skipped"

export interface AIProviderTestStep {
  key: "connection" | "model_response" | "schema_extraction" | "tool_calling"
  status: AIProviderTestStatus
  detail: string
  latency_ms?: number | null
}

export interface AIProviderTestResult {
  provider_id: string
  provider: string
  provider_type: string
  model: string | null
  success: boolean
  agent_ready: boolean
  checked_at: string
  steps: AIProviderTestStep[]
}

export interface AIProviderCreate {
  name: string
  display_name: string
  api_url: string
  api_key: string
  model?: string
  provider_type?: string
  is_active?: boolean
  is_default?: boolean
  is_agent_provider?: boolean
  description?: string
}

export interface AIProviderUpdate {
  display_name?: string
  api_url?: string
  api_key?: string
  model?: string
  provider_type?: string
  is_active?: boolean
  is_agent_provider?: boolean
  description?: string
}

function authHeaders(token: string) {
  return { "Content-Type": "application/json", Authorization: `Bearer ${token}` }
}

export async function listAIProviders(token: string): Promise<AIProviderSetting[]> {
  const res = await fetch(`${getApiBaseUrl()}/ai-settings/`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error("Failed to load AI providers")
  return res.json()
}

export async function createAIProvider(token: string, data: AIProviderCreate): Promise<AIProviderSetting> {
  const res = await fetch(`${getApiBaseUrl()}/ai-settings/`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(data),
  })
  const body = await res.json()
  if (!res.ok) throw new Error(body.detail || "Failed to create provider")
  return body
}

export async function updateAIProvider(token: string, id: string, data: AIProviderUpdate): Promise<AIProviderSetting> {
  const res = await fetch(`${getApiBaseUrl()}/ai-settings/${id}`, {
    method: "PUT",
    headers: authHeaders(token),
    body: JSON.stringify(data),
  })
  const body = await res.json()
  if (!res.ok) throw new Error(body.detail || "Failed to update provider")
  return body
}

export async function deleteAIProvider(token: string, id: string): Promise<void> {
  const res = await fetch(`${getApiBaseUrl()}/ai-settings/${id}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || "Failed to delete provider")
  }
}

export async function setAgentProvider(token: string, id: string): Promise<AIProviderSetting> {
  const res = await fetch(`${getApiBaseUrl()}/ai-settings/${id}/set-agent-provider`, {
    method: "POST",
    headers: authHeaders(token),
  })
  const body = await res.json()
  if (!res.ok) throw new Error(body.detail || "Failed to set agent provider")
  return body
}

export async function verifyAIProviderAgentTools(token: string, id: string): Promise<AIProviderSetting> {
  const res = await fetch(`${getApiBaseUrl()}/ai-settings/${id}/verify-agent-tools`, {
    method: "POST",
    headers: authHeaders(token),
  })
  const body = await res.json()
  if (!res.ok) throw new Error(body.detail || "Failed to verify Agent tools")
  return body
}

export async function testAIProvider(token: string, id: string): Promise<AIProviderTestResult> {
  const res = await fetch(`${getApiBaseUrl()}/ai-settings/${id}/test`, {
    method: "POST",
    headers: authHeaders(token),
  })
  const body = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(body.detail || "Failed to test provider")
  return body
}

export async function unsetAgentProvider(token: string, id: string): Promise<void> {
  const res = await fetch(`${getApiBaseUrl()}/ai-settings/${id}/set-agent-provider`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || "Failed to unset agent provider")
  }
}

export async function setWorkflowBuilderProvider(token: string, id: string): Promise<AIProviderSetting> {
  const res = await fetch(`${getApiBaseUrl()}/ai-settings/${id}/set-workflow-builder-provider`, {
    method: "POST",
    headers: authHeaders(token),
  })
  const body = await res.json()
  if (!res.ok) throw new Error(body.detail || "Failed to set workflow builder provider")
  return body
}

export async function unsetWorkflowBuilderProvider(token: string, id: string): Promise<void> {
  const res = await fetch(`${getApiBaseUrl()}/ai-settings/${id}/set-workflow-builder-provider`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || "Failed to unset workflow builder provider")
  }
}

export async function getAIProviderWithKey(token: string, id: string): Promise<AIProviderSetting & { api_key: string }> {
  const res = await fetch(`${getApiBaseUrl()}/ai-settings/${id}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  const body = await res.json()
  if (!res.ok) throw new Error(body.detail || "Failed to load provider")
  return body
}
