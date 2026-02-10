// TypeScript types for AI Settings

export interface AISettings {
  id: string
  name: string
  display_name: string
  api_url: string
  api_key: string
  is_active: boolean
  is_default: boolean
  description?: string
  created_at: string
  updated_at?: string
  created_by?: string
}

export interface AISettingsPublic {
  id: string
  name: string
  display_name: string
  api_url: string
  is_active: boolean
  is_default: boolean
  description?: string
  created_at: string
  updated_at?: string
}

export interface AISettingsCreate {
  name: string
  display_name: string
  api_url: string
  api_key: string
  is_active?: boolean
  is_default?: boolean
  description?: string
}

export interface AISettingsUpdate {
  name?: string
  display_name?: string
  api_url?: string
  api_key?: string
  is_active?: boolean
  is_default?: boolean
  description?: string
}

export interface ConnectionTestResult {
  success: boolean
  provider: string
  message: string
  fields_suggested?: number
}
