/**
 * Workflow API Client
 */

import { getApiBaseUrl, handleAuthError } from "./api"

const apiUrl = (path: string): string => `${getApiBaseUrl()}${path}`

// ── Types ────────────────────────────────────────────────────────────
export interface WorkflowNodeData {
  label?: string
  config?: Record<string, any>
  [key: string]: any
}

export interface WorkflowNode {
  id: string
  type: string
  position: { x: number; y: number }
  data: WorkflowNodeData
}

export interface WorkflowEdge {
  id: string
  source: string
  target: string
  sourceHandle?: string | null
  targetHandle?: string | null
}

export interface WorkflowDefinition {
  nodes: WorkflowNode[]
  edges: WorkflowEdge[]
}

export interface Workflow {
  id: string
  name: string
  description?: string
  definition: WorkflowDefinition
  is_active: boolean
  schedule_cron?: string | null
  schedule_enabled: boolean
  next_run_at?: string | null
  last_run_at?: string | null
  webhook_enabled?: boolean
  webhook_secret_created_at?: string | null
  webhook_last_triggered_at?: string | null
  created_at?: string
  updated_at?: string
}

export interface WorkflowNodeRun {
  id: string
  node_id: string
  node_type: string
  node_label?: string
  status: "pending" | "running" | "succeeded" | "failed" | "skipped"
  input?: any
  output?: any
  logs?: string
  error?: string
  started_at?: string | null
  finished_at?: string | null
}

export interface WorkflowRun {
  id: string
  workflow_id: string
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled"
  trigger_type: "manual" | "schedule" | "webhook" | "node_test"
  result?: any
  result_node_id?: string | null
  error?: string | null
  started_at?: string | null
  finished_at?: string | null
  created_at?: string
  node_runs: WorkflowNodeRun[]
}

export interface NodeTypeField {
  name: string
  label: string
  type: string
  options?: string[]
  default?: any
  required?: boolean
  placeholder?: string
  hint?: string
  provider?: string
}

export interface OutputField {
  name: string
  label: string
}

export interface NodeTypeDef {
  type: string
  category: string
  label: string
  description: string
  config_fields: NodeTypeField[]
  output_fields?: OutputField[]
}

export interface WorkflowWebhookSecret {
  webhook_enabled: boolean
  webhook_url: string
  secret: string
  secret_created_at: string
}

// ── Helpers ──────────────────────────────────────────────────────────
const authHeaders = (token: string) => ({
  Authorization: `Bearer ${token}`,
  "Content-Type": "application/json",
})

async function request<T>(token: string, path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(apiUrl(path), {
    ...init,
    headers: { ...authHeaders(token), ...(init?.headers || {}) },
  })
  handleAuthError(response)
  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = await response.json()
      if (body?.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail)
    } catch { /* keep statusText */ }
    throw new Error(detail)
  }
  if (response.status === 204) return undefined as T
  return response.json()
}

// ── API calls ────────────────────────────────────────────────────────
export const getNodeTypes = (token: string) =>
  request<{ node_types: NodeTypeDef[] }>(token, "/workflows/node-types")

export const getWorkflows = (token: string) =>
  request<{ workflows: Workflow[]; total: number }>(token, "/workflows/")

export const getWorkflow = (token: string, id: string) =>
  request<Workflow>(token, `/workflows/${id}`)

export const createWorkflow = (
  token: string,
  payload: { name: string; description?: string; definition?: WorkflowDefinition; schedule_cron?: string | null; schedule_enabled?: boolean }
) => request<Workflow>(token, "/workflows/", { method: "POST", body: JSON.stringify(payload) })

export const updateWorkflow = (
  token: string,
  id: string,
  payload: Partial<{ name: string; description: string; definition: WorkflowDefinition; schedule_cron: string | null; schedule_enabled: boolean; is_active: boolean }>
) => request<Workflow>(token, `/workflows/${id}`, { method: "PUT", body: JSON.stringify(payload) })

export const deleteWorkflow = (token: string, id: string) =>
  request<void>(token, `/workflows/${id}`, { method: "DELETE" })

export const rotateWorkflowWebhookSecret = (token: string, id: string) =>
  request<WorkflowWebhookSecret>(token, `/workflows/${id}/webhook-secret`, { method: "POST" })

export const disableWorkflowWebhookSecret = (token: string, id: string) =>
  request<void>(token, `/workflows/${id}/webhook-secret`, { method: "DELETE" })

export const runWorkflow = (token: string, id: string, input?: Record<string, any>) =>
  request<WorkflowRun>(token, `/workflows/${id}/run`, {
    method: "POST",
    body: JSON.stringify({ input: input || {} }),
  })

export const testNode = (token: string, workflowId: string, nodeId: string) =>
  request<WorkflowRun>(token, `/workflows/${workflowId}/nodes/${encodeURIComponent(nodeId)}/test`, {
    method: "POST",
  })

export const getWorkflowRuns = (token: string, id: string, limit = 20) =>
  request<{ runs: WorkflowRun[]; total: number }>(token, `/workflows/${id}/runs?limit=${limit}`)

export const getRun = (token: string, runId: string) =>
  request<WorkflowRun>(token, `/workflows/runs/${runId}`)

export const runOutputDownloadUrl = (runId: string, filename: string) =>
  apiUrl(`/workflows/runs/${runId}/outputs/${encodeURIComponent(filename)}`)

/**
 * Download a workflow run output file. The endpoint requires auth, so we fetch
 * with the Bearer token and trigger a blob download (a plain <a> link can't
 * attach the Authorization header → "Not authenticated").
 */
export async function downloadRunOutput(
  token: string,
  runId: string,
  filename: string
): Promise<void> {
  const response = await fetch(runOutputDownloadUrl(runId, filename), {
    headers: { Authorization: `Bearer ${token}` },
  })
  handleAuthError(response)
  if (!response.ok) {
    let message = `Download failed (${response.status})`
    try {
      const data = await response.json()
      message = data?.detail || message
    } catch { /* keep default */ }
    throw new Error(message)
  }
  const blob = await response.blob()
  const objectUrl = URL.createObjectURL(blob)
  const link = document.createElement("a")
  link.href = objectUrl
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(objectUrl)
}

// ── AI variable finder ───────────────────────────────────────────────
export interface VariableCandidate {
  token: string
  label?: string
  sample?: string
  type?: string
}

export interface VariableSuggestion {
  token: string
  reason: string
  confidence: "high" | "medium" | "low"
}

export const suggestVariables = (
  token: string,
  workflowId: string,
  query: string,
  candidates: VariableCandidate[],
  integrationId?: string | null
) =>
  request<{ suggestions: VariableSuggestion[] }>(token, `/workflows/${workflowId}/suggest-variables`, {
    method: "POST",
    body: JSON.stringify({ query, candidates, integration_id: integrationId || null }),
  })

// ── Jobs (for the Jobs node picker) ──────────────────────────────────
export interface JobSummary {
  id: string
  name?: string | null
  status: string
}

export const getJobs = (token: string) =>
  request<JobSummary[]>(token, "/jobs/")

// ── Export / Import ──────────────────────────────────────────────────
export interface WorkflowExport {
  schema_version: number
  name: string
  description?: string | null
  schedule_cron?: string | null
  schedule_enabled: boolean
  definition: WorkflowDefinition
}

export interface WorkflowValidationIssue {
  node_id: string
  level: "error" | "warning"
  field?: string | null
  message: string
}

export interface WorkflowImportResponse {
  workflow: Workflow
  warnings: WorkflowValidationIssue[]
}

export const exportWorkflow = (token: string, id: string) =>
  request<WorkflowExport>(token, `/workflows/${id}/export`)

export const importWorkflow = (token: string, payload: WorkflowExport) =>
  request<WorkflowImportResponse>(token, "/workflows/import", {
    method: "POST",
    body: JSON.stringify(payload),
  })

/** Client-side JSON download of a workflow export (no server round-trip needed). */
export function downloadWorkflowJson(data: WorkflowExport): void {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" })
  const objectUrl = URL.createObjectURL(blob)
  const link = document.createElement("a")
  const safeName = (data.name || "workflow").replace(/[^\w\-]+/g, "_")
  link.href = objectUrl
  link.download = `${safeName}.workflow.json`
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(objectUrl)
}

// ── AI workflow builder (agent) ──────────────────────────────────────
export const createWorkflowConversation = (token: string) =>
  request<{ id: string; kind: string; max_iterations: number; created_at: string }>(
    token, "/agent/workflow-conversations", { method: "POST" }
  )

export const resolveCredential = (
  token: string,
  pendingActionId: string,
  payload: { integration_id?: string | null; ai_provider_id?: string | null; name?: string }
) => request<{ ok: boolean; result: any }>(token, `/agent/credential/${pendingActionId}`, {
  method: "POST",
  body: JSON.stringify(payload),
})
