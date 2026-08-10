/**
 * Integration API Client
 * Handles all API calls related to integrations
 */

import { getApiBaseUrl, handleAuthError } from "./api"

const apiUrl = (path: string): string => `${getApiBaseUrl()}${path}`


export interface IntegrationConfig {
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
  reasoningEffort?: "low" | "medium" | "high"
  auth_mode?: "oauth" | "service_account" | "app"
  provider?: "google" | "microsoft"
  account_email?: string
  account_name?: string
  folder_id?: string
  folder_name?: string
  drive_id?: string
  drive_name?: string
}

export interface Integration {
  id: string
  user_id: string
  name: string
  type: "api" | "workflow" | "llm" | "softnix_genai" | "gdrive" | "onedrive"
  description?: string
  status: "active" | "paused"
  config: IntegrationConfig
  created_at: string
  updated_at: string
}

export interface IntegrationCreate {
  name: string
  type: "api" | "workflow" | "llm" | "softnix_genai" | "gdrive" | "onedrive"
  description?: string
  status?: "active" | "paused"
  config: Record<string, any>
}

export interface IntegrationUpdate {
  name?: string
  type?: "api" | "workflow" | "llm" | "softnix_genai" | "gdrive" | "onedrive"
  description?: string
  status?: "active" | "paused"
  config?: Record<string, any>
}

/**
 * Get all integrations for the current user
 */
export async function getIntegrations(
  token: string,
  status?: "active" | "paused"
): Promise<{ integrations: Integration[]; total: number }> {
  const url = new URL(apiUrl("/integrations/"), window.location.origin)
  if (status) {
    url.searchParams.set("status", status)
  }

  const response = await fetch(url.toString(), {
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
  })

  handleAuthError(response)
  if (!response.ok) {
    throw new Error(`Failed to fetch integrations: ${response.statusText}`)
  }

  return response.json()
}

/**
 * Get all active integrations for the current user
 */
export async function getActiveIntegrations(token: string): Promise<Integration[]> {
  const response = await fetch(apiUrl("/integrations/active"), {
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
  })

  handleAuthError(response)
  if (!response.ok) {
    throw new Error(`Failed to fetch active integrations: ${response.statusText}`)
  }

  return response.json()
}

/**
 * Get a specific integration by ID
 */
export async function getIntegration(token: string, id: string): Promise<Integration> {
  const response = await fetch(apiUrl(`/integrations/${id}`), {
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
  })

  handleAuthError(response)
  if (!response.ok) {
    throw new Error(`Failed to fetch integration: ${response.statusText}`)
  }

  return response.json()
}

/**
 * Create a new integration
 */
export async function createIntegration(
  token: string,
  data: IntegrationCreate
): Promise<Integration> {
  const response = await fetch(apiUrl("/integrations/"), {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(data),
  })

  handleAuthError(response)
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(error.detail || "Failed to create integration")
  }

  return response.json()
}

/**
 * Update an existing integration
 */
export async function updateIntegration(
  token: string,
  id: string,
  data: IntegrationUpdate
): Promise<Integration> {
  const response = await fetch(apiUrl(`/integrations/${id}`), {
    method: "PUT",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(data),
  })

  handleAuthError(response)
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(error.detail || "Failed to update integration")
  }

  return response.json()
}

/**
 * Delete an integration
 */
export async function deleteIntegration(token: string, id: string): Promise<void> {
  const response = await fetch(apiUrl(`/integrations/${id}`), {
    method: "DELETE",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
  })

  handleAuthError(response)
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(error.detail || "Failed to delete integration")
  }
}

/**
 * Test a Google Drive / OneDrive credential (issue token, reach the API).
 */
export async function testDriveIntegration(
  token: string,
  id: string,
  options?: { folderId?: string }
): Promise<{ ok: boolean; detail: any }> {
  const response = await fetch(apiUrl(`/integrations/${id}/test-drive`), {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify(options?.folderId ? { folder_id: options.folderId } : {}),
  })
  handleAuthError(response)
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(error.detail || "ทดสอบการเชื่อมต่อไม่สำเร็จ")
  }
  return response.json()
}

export async function getCloudOAuthStart(
  token: string,
  provider: "google" | "microsoft"
): Promise<{ provider: string; authorization_url: string }> {
  const response = await fetch(apiUrl(`/integrations/oauth/${provider}/start`), {
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
  })
  handleAuthError(response)
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(error.detail || "เริ่มเชื่อมต่อ cloud storage ไม่สำเร็จ")
  }
  return response.json()
}

export interface CloudFolder {
  id: string
  name: string
  is_folder: boolean
  mimeType?: string
  size?: number
}

export async function listCloudFolders(
  token: string,
  integrationId: string,
  parentId = "root"
): Promise<CloudFolder[]> {
  const url = new URL(apiUrl(`/integrations/${integrationId}/folders`), window.location.origin)
  url.searchParams.set("parent_id", parentId)
  const response = await fetch(url.toString(), {
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
  })
  handleAuthError(response)
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(error.detail || "อ่านโฟลเดอร์ไม่สำเร็จ")
  }
  return response.json()
}

export async function updateCloudDestination(
  token: string,
  integrationId: string,
  data: { name?: string; description?: string; status?: "active" | "paused"; folder_id: string; folder_name: string }
): Promise<Integration> {
  const response = await fetch(apiUrl(`/integrations/${integrationId}/cloud-destination`), {
    method: "PUT",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify(data),
  })
  handleAuthError(response)
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(error.detail || "บันทึกโฟลเดอร์ไม่สำเร็จ")
  }
  return response.json()
}
