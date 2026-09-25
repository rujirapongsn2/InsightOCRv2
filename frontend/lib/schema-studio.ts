import { ArrayColumnType, FieldInsight, SchemaField, TableColumn } from "@/types/schema"

const COLUMN_TYPES: ArrayColumnType[] = ["text", "number", "date", "currency"]

/** Field as the backend expects it: no UI-only keys, text tables as array_config. */
export function toSchemaPayloadField(field: SchemaField): Record<string, unknown> {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const { id, studio, table_columns, items, ...rest } = field
  const payload: Record<string, unknown> = { ...rest }
  if (field.type === "array" && items) payload.items = items
  if (field.type === "array" && !field.locator && table_columns?.length) {
    payload.array_config = { item_type: "object", row_detection: "line", header_rows: 1, columns: table_columns }
  }
  if (field.validation_rules) {
    const rules = { ...field.validation_rules }
    if (!rules.source_labels?.length) delete rules.source_labels
    if (!rules.pattern) delete rules.pattern
    if (Object.keys(rules).length) payload.validation_rules = rules
    else delete payload.validation_rules
  }
  return payload
}

export interface SuggestedFieldResponse {
  name: string
  type?: SchemaField["type"]
  description?: string
  validation_rules?: SchemaField["validation_rules"]
  array_config?: { columns?: Array<{ name?: string; type?: string }> }
  required?: boolean
  studio?: FieldInsight
}

/** Suggestion from the backend -> editable wizard field. */
export function fromSuggestedField(field: SuggestedFieldResponse, id: string): SchemaField {
  const columns: TableColumn[] = (field.array_config?.columns || [])
    .filter((column) => column.name)
    .map((column) => ({
      name: String(column.name),
      type: COLUMN_TYPES.includes(column.type as ArrayColumnType) ? (column.type as ArrayColumnType) : "text",
    }))
  return {
    id,
    name: field.name,
    type: field.type || "text",
    description: field.description || "",
    // Suggested as required only when the field was found in every sample.
    required: Boolean(field.required),
    order: 0,
    validation_rules: field.validation_rules,
    table_columns: field.type === "array" ? columns : undefined,
    studio: field.studio,
  }
}

export function splitList(value: string): string[] {
  return value.split(",").map((item) => item.trim()).filter(Boolean)
}
