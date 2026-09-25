// TypeScript types for Schema Creation Wizard

export type FieldType = "text" | "number" | "date" | "currency" | "boolean" | "array"

export type DocumentType = "invoice" | "receipt" | "contract" | "po" | "other"
export type ExtractionProfile = "legacy" | "anydoc_hybrid"

export type WizardStep = 1 | 2

export type StartingPoint = "template" | "ai" | "fixed" | "scratch" | "import"

export interface ValidationRule {
  min?: number
  max?: number
  pattern?: string
  format?: string
  source_labels?: string[]
}

// Column of a table field that is read from text (no BBox). Converted to
// array_config when the field is sent to the backend.
export interface TableColumn {
  name: string
  type: ArrayColumnType
}

export type FieldEvidenceStatus = "verified" | "review" | "not_found"

export interface FieldCheck {
  key: "evidence" | "type" | "labels" | "pattern" | "duplicate"
  ok: boolean | null
  message: string
}

export interface SampleEvidence {
  sample: number
  quote: string
  match: "once" | "multiple" | "none"
  count: number
  line_no?: number
  context?: string
  partial?: boolean
}

// Review metadata from AI suggestion; never saved with the schema.
export interface FieldInsight {
  label: string
  confidence: number
  status: FieldEvidenceStatus
  presence?: { found: number; total: number }
  evidence: SampleEvidence
  samples?: SampleEvidence[]
  checks: FieldCheck[]
}

export interface StudioSample {
  filename: string
  text: string
  truncated: boolean
}

// Uploaded samples for one schema draft. Files stay in the browser and are
// only sent again when the user agrees to keep them as the test set.
export interface StudioSession {
  sessionId: string | null
  files: File[]
  samples: StudioSample[]
  // Values a person confirmed as correct, per sample index then field id
  // (ids survive renames; names are resolved when the test set is saved).
  expected: Record<number, Record<string, unknown>>
  keepSamples: boolean
  retentionDays: number
}

export interface ArrayItems {
  type: string // e.g. 'object', 'string', 'number'
  description?: string
  properties?: Record<string, { type: string; description?: string }>
}

export type ArrayColumnType = "text" | "number" | "date" | "currency"

export interface ArrayColumn {
  name: string
  type: ArrayColumnType
  x: number
  width: number
}

export interface ArrayConfig {
  item_type: "object"
  row_detection: "anchor_column" | "line"
  anchor_column?: string
  header_rows: number
  columns: ArrayColumn[]
}

export interface SchemaField {
  id?: string // Temporary ID for frontend ordering (UUID)
  name: string
  type: FieldType
  description: string
  required: boolean
  items?: ArrayItems // For array type fields (JSON Schema)
  array_config?: ArrayConfig
  validation_rules?: ValidationRule
  help_text?: string
  example?: string
  order?: number
  locator?: BboxLocator
  table_columns?: TableColumn[]
  studio?: FieldInsight
}

export interface BboxLocator {
  type: "bbox"
  page: number
  x: number
  y: number
  width: number
  height: number
  clean_placeholders?: boolean
}

export interface SchemaData {
  name: string
  description: string
  document_type: DocumentType
  ocr_engine?: string
  extraction_profile?: ExtractionProfile
  template_id?: string
}

export interface SchemaWizardState {
  currentStep: WizardStep
  startingPoint: StartingPoint | null
  manualEntry: boolean
  schemaData: SchemaData
  fields: SchemaField[]
  validationErrors: ValidationError[]
  isSaving: boolean
  testResults?: TestResults
  studio: StudioSession | null
}

export interface ValidationError {
  field: string
  message: string
  severity: "error" | "warning"
}

export interface Template {
  id: string
  name: string
  description: string
  document_type: DocumentType
  category: string
  is_system_template: boolean
  thumbnail_url?: string
  usage_count: number
  fields: SchemaField[]
  created_at: string
  updated_at?: string
  created_by_email?: string
  created_by_name?: string
}

export interface TemplateListResponse {
  templates: Template[]
  total: number
  categories: string[]
}

export interface TestResults {
  extracted_data: Record<string, unknown>
  ocr_preview: string
  quality_metrics: QualityMetrics
  field_confidence: Record<string, number>
}

export interface QualityMetrics {
  completeness: number // Percentage (0-100)
  missing_required: string[]
  low_confidence_fields: string[]
  suggestions: string[]
}

export interface SuggestedField extends SchemaField {
  confidence: number // 0-1
  suggested?: boolean
  example_value?: string
}

export interface AISuggestionResponse {
  suggested_fields: SuggestedField[]
  document_preview: string
  confidence_score: number
}

// API Request/Response types
export interface CreateSchemaRequest {
  name: string
  description?: string
  document_type: DocumentType
  ocr_engine: string
  extraction_profile: ExtractionProfile
  fields: SchemaField[]
  template_id?: string
}

export interface CreateSchemaResponse {
  id: string
  name: string
  description?: string
  document_type: DocumentType
  ocr_engine: string
  extraction_profile: ExtractionProfile
  fields: SchemaField[]
  template_id?: string
  created_by?: string
  created_at: string
  updated_at?: string
}

// Wizard Context Actions
export interface SchemaWizardActions {
  setCurrentStep: (step: WizardStep) => void
  setStartingPoint: (point: StartingPoint) => void
  setManualEntry: (enabled: boolean) => void
  updateSchemaData: (data: Partial<SchemaData>) => void
  addField: (field: SchemaField) => void
  updateField: (id: string, updates: Partial<SchemaField>) => void
  removeField: (id: string) => void
  reorderFields: (startIndex: number, endIndex: number) => void
  setFields: (fields: SchemaField[]) => void
  validateCurrentStep: () => boolean
  nextStep: () => void
  previousStep: () => void
  saveSchema: () => Promise<void>
  testSchema: (file: File) => Promise<void>
  resetWizard: () => void
  setStudio: (studio: StudioSession | null) => void
  updateStudio: (updates: Partial<StudioSession>) => void
}

// Field Suggestions based on document type
export interface FieldSuggestion {
  name: string
  type: FieldType
  description: string
  icon: string
  required: boolean
}

export const FIELD_SUGGESTIONS: Record<DocumentType, FieldSuggestion[]> = {
  invoice: [
    { name: "invoice_number", type: "text", description: "Invoice number", icon: "#️⃣", required: true },
    { name: "invoice_date", type: "date", description: "Invoice date", icon: "📅", required: true },
    { name: "total_amount", type: "currency", description: "Total amount", icon: "💰", required: true },
    { name: "vendor_name", type: "text", description: "Vendor name", icon: "🏢", required: true },
    { name: "tax_amount", type: "currency", description: "Tax amount", icon: "💵", required: false },
  ],
  receipt: [
    { name: "receipt_number", type: "text", description: "Receipt number", icon: "#️⃣", required: true },
    { name: "date", type: "date", description: "Purchase date", icon: "📅", required: true },
    { name: "merchant_name", type: "text", description: "Merchant name", icon: "🏪", required: true },
    { name: "total_amount", type: "currency", description: "Total amount", icon: "💰", required: true },
    { name: "payment_method", type: "text", description: "Payment method", icon: "💳", required: false },
  ],
  po: [
    { name: "po_number", type: "text", description: "PO number", icon: "#️⃣", required: true },
    { name: "po_date", type: "date", description: "PO date", icon: "📅", required: true },
    { name: "vendor_name", type: "text", description: "Vendor name", icon: "🏢", required: true },
    { name: "total_amount", type: "currency", description: "Total amount", icon: "💰", required: true },
    { name: "delivery_date", type: "date", description: "Delivery date", icon: "🚚", required: false },
  ],
  contract: [
    { name: "contract_number", type: "text", description: "Contract number", icon: "#️⃣", required: true },
    { name: "contract_date", type: "date", description: "Contract date", icon: "📅", required: true },
    { name: "party_a", type: "text", description: "First party", icon: "👤", required: true },
    { name: "party_b", type: "text", description: "Second party", icon: "👥", required: true },
    { name: "start_date", type: "date", description: "Start date", icon: "▶️", required: false },
    { name: "end_date", type: "date", description: "End date", icon: "⏹️", required: false },
  ],
  other: []
}
