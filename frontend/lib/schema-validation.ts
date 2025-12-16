import { SchemaField, SchemaData, ValidationError } from "@/types/schema"

/**
 * Validate field name format for JSON Schema compatibility
 * - Must not be empty
 * - Can contain letters (including Unicode/Thai), numbers, underscores, and hyphens
 * - NO SPACES allowed (required for valid JSON Schema property names)
 * - Must start with a letter or underscore
 */
export function isValidFieldName(name: string): boolean {
  if (!name) return false

  // Check for leading/trailing spaces
  if (name !== name.trim()) return false

  // JSON Schema property name rules:
  // - Start with letter (Unicode) or underscore
  // - Contain only letters, numbers, underscores, hyphens
  // - NO SPACES (important for JSON Schema)
  const pattern = /^[\p{L}_][\p{L}\p{N}_-]*$/u
  return pattern.test(name)
}

/**
 * Generate a user-friendly suggestion for invalid field names
 * Converts to valid JSON Schema property name format
 */
export function suggestFieldName(invalidName: string): string {
  if (!invalidName) return ""

  // Trim spaces
  let suggested = invalidName.trim()

  // Replace spaces with underscores (important for JSON Schema)
  suggested = suggested.replace(/\s+/g, "_")

  // Replace special characters (except letters, numbers, underscore, hyphen) with underscore
  suggested = suggested.replace(/[^\p{L}\p{N}_-]/gu, "_")

  // Remove leading numbers or hyphens (must start with letter or underscore)
  suggested = suggested.replace(/^[\p{N}-]+/u, "")

  // Remove consecutive underscores
  suggested = suggested.replace(/_+/g, "_")

  // Remove trailing underscores or hyphens
  suggested = suggested.replace(/[_-]+$/g, "")

  // If starts with special char, prepend underscore
  if (suggested && !/^[\p{L}_]/u.test(suggested)) {
    suggested = "_" + suggested
  }

  // If empty after cleaning, provide a default
  if (!suggested) {
    suggested = "field_name"
  }

  return suggested
}

/**
 * Check if a field name is unique in the list of fields
 */
export function isUniqueFieldName(name: string, fields: SchemaField[], excludeId?: string): boolean {
  return !fields.some(field =>
    field.name === name && field.id !== excludeId
  )
}

/**
 * Validate a single schema field
 */
export function validateField(field: SchemaField, allFields: SchemaField[]): ValidationError[] {
  const errors: ValidationError[] = []

  // Check if field name is empty
  if (!field.name || field.name.trim() === "") {
    errors.push({
      field: field.id || field.name,
      message: "Field name is required",
      severity: "error"
    })
    return errors
  }

  // Check field name format (required for valid JSON Schema)
  if (!isValidFieldName(field.name)) {
    const suggestion = suggestFieldName(field.name)
    errors.push({
      field: field.id || field.name,
      message: `Field name "${field.name}" is not valid for JSON Schema. Must start with a letter or underscore, and contain only letters, numbers, underscores, or hyphens (no spaces). Try "${suggestion}" instead.`,
      severity: "error"
    })
  }

  // Check for duplicate field names
  if (!isUniqueFieldName(field.name, allFields, field.id)) {
    errors.push({
      field: field.id || field.name,
      message: `Duplicate field name "${field.name}". Each field must have a unique name.`,
      severity: "error"
    })
  }

  // Warn if description is empty (optional but recommended)
  if (!field.description || field.description.trim() === "") {
    errors.push({
      field: field.id || field.name,
      message: `Field "${field.name}" has no description. Adding a description helps the AI extract data more accurately.`,
      severity: "warning"
    })
  }

  // Warn if description is too short
  if (field.description && field.description.trim().length < 10) {
    errors.push({
      field: field.id || field.name,
      message: `Field "${field.name}" description is very short. Be more specific about what to extract.`,
      severity: "warning"
    })
  }

  return errors
}

/**
 * Validate all fields in a schema
 */
export function validateFields(fields: SchemaField[]): ValidationError[] {
  const errors: ValidationError[] = []

  // Check if there's at least one field
  if (fields.length === 0) {
    errors.push({
      field: "general",
      message: "Schema must have at least one field",
      severity: "error"
    })
    return errors
  }

  // Validate each field
  fields.forEach(field => {
    const fieldErrors = validateField(field, fields)
    errors.push(...fieldErrors)
  })

  // Warn if no required fields
  const hasRequired = fields.some(f => f.required)
  if (!hasRequired) {
    errors.push({
      field: "general",
      message: "Consider marking at least one field as required to ensure essential data is captured",
      severity: "warning"
    })
  }

  return errors
}

/**
 * Validate schema basic information
 */
export function validateSchemaData(data: SchemaData): ValidationError[] {
  const errors: ValidationError[] = []

  // Check schema name
  if (!data.name || data.name.trim() === "") {
    errors.push({
      field: "name",
      message: "Schema name is required",
      severity: "error"
    })
  } else if (data.name.trim().length < 3) {
    errors.push({
      field: "name",
      message: "Schema name should be at least 3 characters long",
      severity: "error"
    })
  }

  // Check document type
  if (!data.document_type) {
    errors.push({
      field: "document_type",
      message: "Document type is required",
      severity: "error"
    })
  }

  // Warn if description is empty (optional but recommended)
  if (!data.description || data.description.trim() === "") {
    errors.push({
      field: "description",
      message: "Adding a description helps others understand when to use this schema",
      severity: "warning"
    })
  }

  return errors
}

/**
 * Validate complete schema (both data and fields)
 */
export function validateSchema(data: SchemaData, fields: SchemaField[]): ValidationError[] {
  const dataErrors = validateSchemaData(data)
  const fieldErrors = validateFields(fields)

  return [...dataErrors, ...fieldErrors]
}

/**
 * Check if there are any errors (severity: error)
 */
export function hasErrors(errors: ValidationError[]): boolean {
  return errors.some(e => e.severity === "error")
}

/**
 * Check if there are any warnings (severity: warning)
 */
export function hasWarnings(errors: ValidationError[]): boolean {
  return errors.some(e => e.severity === "warning")
}

/**
 * Get errors for a specific field
 */
export function getFieldErrors(fieldId: string, errors: ValidationError[]): ValidationError[] {
  return errors.filter(e => e.field === fieldId)
}

/**
 * Get general errors (not field-specific)
 */
export function getGeneralErrors(errors: ValidationError[]): ValidationError[] {
  return errors.filter(e => e.field === "general" || e.field === "name" || e.field === "document_type" || e.field === "description")
}

/**
 * Format validation error for display
 */
export function formatValidationError(error: ValidationError): string {
  const icon = error.severity === "error" ? "❌" : "⚠️"
  return `${icon} ${error.message}`
}
