/**
 * Integration API Client
 * Handles all API calls related to integrations
 */

import { getApiBaseUrl, handleAuthError } from "./api"

const API_BASE = getApiBaseUrl()

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
}

export interface Integration {
  id: string
  user_id: string
  name: string
  type: "api" | "workflow" | "llm"
  description?: string
  status: "active" | "paused"
  config: IntegrationConfig
  created_at: string
  updated_at: string
}

export interface IntegrationCreate {
  name: string
  type: "api" | "workflow" | "llm"
  description?: string
  status?: "active" | "paused"
  config: Record<string, any>
}

export interface IntegrationUpdate {
  name?: string
  type?: "api" | "workflow" | "llm"
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
  const url = new URL(`${API_BASE}/integrations`)
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
  const response = await fetch(`${API_BASE}/integrations/active`, {
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
  const response = await fetch(`${API_BASE}/integrations/${id}`, {
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
  const response = await fetch(`${API_BASE}/integrations`, {
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
  const response = await fetch(`${API_BASE}/integrations/${id}`, {
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
  const response = await fetch(`${API_BASE}/integrations/${id}`, {
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
