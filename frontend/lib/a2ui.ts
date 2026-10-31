// A2UI v0.9 panels for the Jobs agent, catalog v2. The backend composes every
// panel from a typed tool call and computes every comparison; a persisted tool
// result is still external data here, so parseSurface checks it once, resolves
// each component's bound data into typed values, and returns null for anything
// outside this catalog (older v1 panels included), so callers fall back to the
// ordinary tool-call entry.

export const A2UI_VERSION = "v0.9"
export const JOBS_CATALOG_ID = "https://insightdoc.app/a2ui/catalogs/jobs/v2"
export const ACTION_FENCE = "a2ui-action"

export const RISK_LEVELS = ["critical", "high", "medium", "low"] as const
export const MAX_CHART_SERIES = 8
const DIRECTIONS = ["up", "down", "flat"] as const
const SENTIMENTS = ["good", "bad", "neutral"] as const
const X_KINDS = ["text", "date", "month"] as const
const ACTION_EVENTS = ["approve_documents", "reject_documents"] as const

export type RiskLevel = (typeof RISK_LEVELS)[number]
export type Direction = (typeof DIRECTIONS)[number]
export type Sentiment = (typeof SENTIMENTS)[number]
export type XKind = (typeof X_KINDS)[number]
export type ActionEventName = (typeof ACTION_EVENTS)[number]

/** How a number reads; money always names its currency. */
export type Measure = { kind: "count" | "number" | "percent" } | { kind: "money"; currency: string }

/** A change the backend computed: delta in the measure's unit (points for a percent), percent relative. */
export interface Change {
    delta: number
    percent: number | null
    direction: Direction
    sentiment: Sentiment
}

export interface DocumentRef {
    document_id: string
    filename: string
}

export interface DocumentRow extends DocumentRef {
    status: string
    note?: string
}

export interface MetricValue {
    value: number
    previous?: number
    change?: Change
}

export type ColumnFormat =
    | { kind: "text" | "date" | "month" | "document" }
    | { kind: "measure"; measure: Measure }
    | { kind: "change"; measure: Measure }

export interface TableColumn {
    key: string
    label: string
    format: ColumnFormat
}

export type TableCell =
    | { kind: "empty" }
    | { kind: "text" | "date" | "month"; value: string }
    | { kind: "document"; value: DocumentRef }
    | { kind: "measure"; value: number; measure: Measure }
    | { kind: "change"; value: Change; measure: Measure }

export interface ChartSeries {
    key: string
    label: string
}

export interface ChartPoint {
    x: string
    /** One value per series, in series order; null where the series has no value. */
    values: (number | null)[]
}

export interface RiskItem {
    id: string
    title: string
    level: RiskLevel
    category: string
    description: string
    quote: string
    /** Set by the backend after looking for the quote in the document's text. */
    quoteVerified: boolean
    page?: number
    recommendation: string
}

type ActionContext = Record<string, unknown>
export type Binding = { path: string }

export type A2uiComponent =
    | { id: string; component: "Column"; children: string[] }
    | { id: string; component: "Row"; children: string[] }
    | { id: string; component: "Text"; text: string; variant: "body" | "caption" | "heading" }
    | { id: string; component: "DocumentList"; documents: DocumentRow[]; selectable: boolean; selection?: string }
    | {
        id: string
        component: "Button"
        label: string
        variant: "primary" | "secondary"
        action: { event: { name: ActionEventName; context: ActionContext } }
    }
    | { id: string; component: "Metric"; label: string; measure: Measure; previousLabel?: string; value: MetricValue }
    | { id: string; component: "DataTable"; columns: TableColumn[]; rows: TableCell[][] }
    | {
        id: string
        component: "Chart"
        type: "bar" | "line"
        title: string
        x: { label: string; kind: XKind }
        series: ChartSeries[]
        measure: Measure
        points: ChartPoint[]
    }
    | { id: string; component: "RiskList"; document: DocumentRef; items: RiskItem[] }
    | { id: string; component: "Sources"; documents: DocumentRef[] }

export type ComponentType = A2uiComponent["component"]
export type ComponentOf<K extends ComponentType> = Extract<A2uiComponent, { component: K }>
export type DataModel = Record<string, unknown>

export interface Surface {
    surfaceId: string
    catalogId: string
    components: Record<string, A2uiComponent>
    /** Only the selections a DocumentList writes and its buttons read live here after parsing. */
    dataModel: DataModel
}

export interface A2uiAction {
    name: ActionEventName
    surfaceId: string
    sourceComponentId: string
    timestamp: string
    context: ActionContext
}

type Raw = Record<string, unknown>

function isRecord(value: unknown): value is Raw {
    return typeof value === "object" && value !== null && !Array.isArray(value)
}

const isFiniteNumber = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value)
const isString = (value: unknown): value is string => typeof value === "string"
const oneOf = <T extends string>(value: unknown, allowed: readonly T[]): T | null =>
    allowed.includes(value as T) ? (value as T) : null
const optional = <T>(value: unknown, parse: (value: unknown) => T | null): T | undefined | null =>
    value === undefined ? undefined : parse(value)
const asString = (value: unknown): string | null => (isString(value) ? value : null)
const asNumber = (value: unknown): number | null => (isFiniteNumber(value) ? value : null)

/** Every item parsed, or null if any is not. */
function all<T>(value: unknown, parse: (item: unknown) => T | null): T[] | null {
    if (!Array.isArray(value)) return null
    const items = value.map(parse)
    return items.every((item): item is T => item !== null) ? items : null
}

export function isBinding(value: unknown): value is Binding {
    return isRecord(value) && Object.keys(value).length === 1 && isString(value.path) && value.path.startsWith("/")
}

function pointerTokens(path: string): string[] {
    return path === "/" ? [] : path.split("/").slice(1).map(t => t.replace(/~1/g, "/").replace(/~0/g, "~"))
}

export function getPointer(data: unknown, path: string): unknown {
    let node: unknown = data
    for (const token of pointerTokens(path)) {
        if (Array.isArray(node) && /^\d+$/.test(token)) node = node[Number(token)]
        else if (isRecord(node)) node = node[token]
        else return undefined
    }
    return node
}

export function setPointer(data: DataModel, path: string, value: unknown): DataModel {
    const tokens = pointerTokens(path)
    if (tokens.length === 0) return isRecord(value) ? value : data
    const [head, ...rest] = tokens
    const child = isRecord(data[head]) ? (data[head] as DataModel) : {}
    return { ...data, [head]: rest.length === 0 ? value : setPointer(child, "/" + rest.join("/"), value) }
}

/** The data a component binds to, or undefined when the prop is not a binding. */
const bound = (data: DataModel, value: unknown): unknown => (isBinding(value) ? getPointer(data, value.path) : undefined)

// ── Values ──────────────────────────────────────────────────────────────────

function parseMeasure(kind: unknown, currency: unknown): Measure | null {
    if (kind === "money") return isString(currency) && /^[A-Z]{3}$/.test(currency) ? { kind, currency } : null
    return kind === "count" || kind === "number" || kind === "percent" ? { kind } : null
}

export function parseChange(value: unknown): Change | null {
    if (!isRecord(value) || !isFiniteNumber(value.delta)) return null
    const percent = value.percent === null ? null : asNumber(value.percent)
    const direction = oneOf(value.direction, DIRECTIONS)
    const sentiment = oneOf(value.sentiment, SENTIMENTS)
    if ((value.percent !== null && percent === null) || !direction || !sentiment) return null
    return { delta: value.delta, percent, direction, sentiment }
}

function parseDocumentRef(value: unknown): DocumentRef | null {
    return isRecord(value) && isString(value.document_id) && isString(value.filename)
        ? { document_id: value.document_id, filename: value.filename } : null
}

function parseDocumentRow(value: unknown): DocumentRow | null {
    const ref = parseDocumentRef(value)
    if (!ref || !isRecord(value) || !isString(value.status)) return null
    const note = optional(value.note, asString)
    return note === null ? null : { ...ref, status: value.status, ...(note ? { note } : {}) }
}

const ISO = { date: /^\d{4}-\d{2}-\d{2}$/, month: /^\d{4}-\d{2}$/ } as const

function parseX(value: unknown, kind: XKind): string | null {
    if (!isString(value)) return null
    return kind === "text" || ISO[kind].test(value) ? value : null
}

function parseMetricValue(value: unknown): MetricValue | null {
    if (!isRecord(value) || !isFiniteNumber(value.value)) return null
    const previous = optional(value.previous, asNumber)
    const change = optional(value.change, parseChange)
    if (previous === null || change === null) return null
    return { value: value.value, ...(previous !== undefined ? { previous } : {}), ...(change ? { change } : {}) }
}

function parseColumn(raw: unknown): TableColumn | null {
    if (!isRecord(raw) || !isString(raw.key) || !isString(raw.label)) return null
    const column = (format: ColumnFormat | null) => (format ? { key: raw.key as string, label: raw.label as string, format } : null)
    switch (raw.kind) {
        case "text":
        case "date":
        case "month":
        case "document":
            return column({ kind: raw.kind })
        case "change": {
            const measure = parseMeasure(raw.value_kind, raw.currency)
            return column(measure && { kind: "change", measure })
        }
        default: {
            const measure = parseMeasure(raw.kind, raw.currency)
            return column(measure && { kind: "measure", measure })
        }
    }
}

function parseCell(value: unknown, format: ColumnFormat): TableCell | null {
    if (value === null || value === undefined) return { kind: "empty" }
    switch (format.kind) {
        case "text":
            return isString(value) ? { kind: "text", value } : null
        case "date":
        case "month": {
            const iso = parseX(value, format.kind)
            return iso === null ? null : { kind: format.kind, value: iso }
        }
        case "document": {
            const ref = parseDocumentRef(value)
            return ref && { kind: "document", value: ref }
        }
        case "measure":
            return isFiniteNumber(value) ? { kind: "measure", value, measure: format.measure } : null
        case "change": {
            const change = parseChange(value)
            return change && { kind: "change", value: change, measure: format.measure }
        }
    }
}

function parseRiskItem(raw: unknown): RiskItem | null {
    if (!isRecord(raw)) return null
    const level = oneOf(raw.level, RISK_LEVELS)
    const text = ["id", "title", "category", "description", "quote", "recommendation"].map(key => raw[key])
    const page = optional(raw.page, value => (Number.isInteger(value) && (value as number) > 0 ? value as number : null))
    if (!level || !text.every(isString) || typeof raw.quote_verified !== "boolean" || page === null) return null
    const [id, title, category, description, quote, recommendation] = text as string[]
    return { id, title, level, category, description, quote, quoteVerified: raw.quote_verified, recommendation,
        ...(page ? { page } : {}) }
}

// ── Components ──────────────────────────────────────────────────────────────

const children = (raw: Raw) => all(raw.children, asString)

const COMPONENT_PARSERS: { [K in ComponentType]: (raw: Raw, data: DataModel) => Omit<ComponentOf<K>, "id" | "component"> | null } = {
    Column: raw => {
        const ids = children(raw)
        return ids && { children: ids }
    },
    Row: raw => {
        const ids = children(raw)
        return ids && { children: ids }
    },
    Text: raw => {
        const variant = raw.variant === undefined ? "body" : oneOf(raw.variant, ["body", "caption", "heading"] as const)
        return isString(raw.text) && variant ? { text: raw.text, variant } : null
    },
    DocumentList: (raw, data) => {
        const documents = all(bound(data, raw.documents), parseDocumentRow)
        const selectable = raw.selectable === true
        const selection = isString(raw.selection) && raw.selection.startsWith("/") ? raw.selection : undefined
        if (!documents || (selectable && !selection)) return null
        return { documents, selectable, ...(selectable ? { selection } : {}) }
    },
    Button: raw => {
        const variant = oneOf(raw.variant, ["primary", "secondary"] as const)
        const event = isRecord(raw.action) && isRecord(raw.action.event) ? raw.action.event : null
        const name = event && oneOf(event.name, ACTION_EVENTS)
        if (!variant || !isString(raw.label) || !event || !name || !isRecord(event.context)) return null
        return { label: raw.label, variant, action: { event: { name, context: event.context } } }
    },
    Metric: (raw, data) => {
        const measure = parseMeasure(raw.kind, raw.currency)
        const previousLabel = optional(raw.previous_label, asString)
        const value = parseMetricValue(bound(data, raw.data))
        if (!isString(raw.label) || !measure || previousLabel === null || !value) return null
        return { label: raw.label, measure, value, ...(previousLabel ? { previousLabel } : {}) }
    },
    DataTable: (raw, data) => {
        const columns = all(raw.columns, parseColumn)
        const rows = columns && all(bound(data, raw.rows), row => {
            if (!isRecord(row)) return null
            const cells = columns.map(column => parseCell(row[column.key], column.format))
            return cells.every((cell): cell is TableCell => cell !== null) ? cells : null
        })
        if (!columns || columns.length === 0 || !rows) return null
        return { columns, rows }
    },
    Chart: (raw, data) => {
        const type = oneOf(raw.type, ["bar", "line"] as const)
        const x = isRecord(raw.x) ? raw.x : null
        const xKind = x && oneOf(x.kind, X_KINDS)
        const measure = parseMeasure(raw.value_kind, raw.currency)
        const series = all(raw.series, item => (isRecord(item) && isString(item.key) && isString(item.label)
            ? { key: item.key, label: item.label } : null))
        if (!type || !x || !isString(x.key) || !isString(x.label) || !xKind || !measure || !isString(raw.title)) return null
        if (!series || series.length === 0 || series.length > MAX_CHART_SERIES) return null
        const points = all(bound(data, raw.points), point => {
            if (!isRecord(point)) return null
            const label = parseX(point[x.key as string], xKind)
            const values = series.map(s => point[s.key] ?? null)
            return label !== null && values.every((v): v is number | null => v === null || isFiniteNumber(v))
                ? { x: label, values } : null
        })
        return points && { type, title: raw.title, x: { label: x.label, kind: xKind }, series, measure, points }
    },
    RiskList: (raw, data) => {
        const document = parseDocumentRef(bound(data, raw.document))
        const items = all(bound(data, raw.items), parseRiskItem)
        return document && items && { document, items }
    },
    Sources: (raw, data) => {
        const documents = all(bound(data, raw.documents), parseDocumentRef)
        return documents && { documents }
    },
}

function parseComponent(raw: unknown, data: DataModel): A2uiComponent | null {
    if (!isRecord(raw) || !isString(raw.id) || !isString(raw.component)) return null
    if (!Object.hasOwn(COMPONENT_PARSERS, raw.component)) return null
    const parse = COMPONENT_PARSERS[raw.component as ComponentType] as (raw: Raw, data: DataModel) => object | null
    const props = parse(raw, data)
    return props && ({ ...props, id: raw.id, component: raw.component } as A2uiComponent)
}

function isTree(components: Record<string, A2uiComponent>): boolean {
    const visited = new Set<string>()
    const walk = (id: string): boolean => {
        const node = components[id]
        if (!node || visited.has(id)) return false
        visited.add(id)
        return !("children" in node) || node.children.every(walk)
    }
    return walk("root")
}

/** Fold a panel's message list into one typed surface; null when anything is outside this catalog. */
export function parseSurface(messages: unknown): Surface | null {
    if (!Array.isArray(messages)) return null
    let header: { surfaceId: string; catalogId: string } | null = null
    const rawComponents: unknown[] = []
    let dataModel: DataModel = {}
    for (const message of messages) {
        if (!isRecord(message) || message.version !== A2UI_VERSION) return null
        if (isRecord(message.createSurface)) {
            const { surfaceId, catalogId } = message.createSurface
            if (header || !isString(surfaceId) || catalogId !== JOBS_CATALOG_ID) return null
            header = { surfaceId, catalogId }
        } else if (isRecord(message.updateComponents)) {
            const update = message.updateComponents
            if (!header || update.surfaceId !== header.surfaceId || !Array.isArray(update.components)) return null
            rawComponents.push(...update.components)
        } else if (isRecord(message.updateDataModel)) {
            const update = message.updateDataModel
            if (!header || update.surfaceId !== header.surfaceId || update.path !== "/" || !isRecord(update.value)) return null
            dataModel = update.value
        } else {
            return null
        }
    }
    if (!header) return null
    const components: Record<string, A2uiComponent> = {}
    for (const raw of rawComponents) {
        const component = parseComponent(raw, dataModel)
        if (!component || Object.hasOwn(components, component.id)) return null
        components[component.id] = component
    }
    return isTree(components) ? { ...header, components, dataModel } : null
}

export function surfaceFromToolResult(result: unknown): Surface | null {
    return isRecord(result) && result.ok === true ? parseSurface(result.a2ui) : null
}

/** Risk items, most severe first; the backend's order is kept within a level. */
export function bySeverity(items: readonly RiskItem[]): RiskItem[] {
    return [...items].sort((a, b) => RISK_LEVELS.indexOf(a.level) - RISK_LEVELS.indexOf(b.level))
}

export function riskCounts(items: readonly RiskItem[]): Record<RiskLevel, number> {
    const counts = { critical: 0, high: 0, medium: 0, low: 0 }
    for (const item of items) counts[item.level] += 1
    return counts
}

/** The system-written verification line of a risk panel; it names every risk whose quote was not found. */
export function quoteSummary(items: readonly RiskItem[]): string {
    const missing = items.filter(item => !item.quoteVerified)
    if (missing.length === 0) return `ข้อความอ้างอิงตรวจพบในเอกสารครบทั้ง ${items.length} รายการ`
    const found = `ข้อความอ้างอิงตรวจพบในเอกสาร ${items.length - missing.length} จาก ${items.length} รายการ`
    return `${found} · ไม่พบ: ${missing.map(item => item.title).join(", ")}`
}

// ── Actions ─────────────────────────────────────────────────────────────────

export function selectedIds(data: DataModel, path: string | undefined): string[] {
    const value = path ? getPointer(data, path) : undefined
    return Array.isArray(value) ? value.filter(isString) : []
}

export function resolveContext(context: ActionContext, data: DataModel): ActionContext {
    return Object.fromEntries(Object.entries(context).map(([key, value]) => [key, isBinding(value) ? getPointer(data, value.path) : value]))
}

/** A button bound to a selection is usable only once something is selected. */
export function hasEmptyBinding(context: ActionContext, data: DataModel): boolean {
    return Object.values(context).some(value => {
        if (!isBinding(value)) return false
        const resolved = getPointer(data, value.path)
        return resolved === undefined || (Array.isArray(resolved) && resolved.length === 0)
    })
}

export function buildAction(surface: Surface, button: ComponentOf<"Button">, data: DataModel, timestamp: string): A2uiAction {
    return {
        name: button.action.event.name,
        surfaceId: surface.surfaceId,
        sourceComponentId: button.id,
        timestamp,
        context: resolveContext(button.action.event.context, data),
    }
}

function describeAction(action: A2uiAction, label: string): string {
    const list = Object.values(action.context).find(Array.isArray)
    if (!list) return label
    return action.name === "approve_documents"
        ? `อนุมัติเอกสาร ${list.length} รายการที่เลือก`
        : `ปฏิเสธเอกสาร ${list.length} รายการที่เลือก`
}

/** The user message a button click sends: a readable line, then the action for the agent. */
export function actionMessage(action: A2uiAction, label: string): string {
    return `${describeAction(action, label)}\n\n\`\`\`${ACTION_FENCE}\n${JSON.stringify(action)}\n\`\`\``
}

const ACTION_BLOCK_RE = new RegExp("\\n*```" + ACTION_FENCE + "\\n([\\s\\S]*?)\\n```\\s*$")

/** The readable part of a user message, without its a2ui-action block. */
export function visibleUserText(content: string): string {
    return content.replace(ACTION_BLOCK_RE, "")
}

export const DOCUMENT_STATUS_LABEL: Record<string, string> = {
    uploaded: "อัปโหลดแล้ว",
    ocr_processing: "กำลังอ่านเอกสาร",
    ocr_completed: "อ่านเอกสารแล้ว",
    extraction_pending: "รอดึงข้อมูล",
    extraction_completed: "รอตรวจ",
    reviewed: "อนุมัติแล้ว",
    rejected: "ปฏิเสธแล้ว",
    failed: "ล้มเหลว",
}

export function documentStatusLabel(status: string): string {
    return DOCUMENT_STATUS_LABEL[status] ?? status.replace(/_/g, " ")
}

/** The surfaces whose buttons the user already clicked, read from the a2ui-action blocks of their messages. */
export function answeredSurfaceIds(userMessages: readonly string[]): Set<string> {
    const ids = new Set<string>()
    for (const content of userMessages) {
        const block = ACTION_BLOCK_RE.exec(content)?.[1]
        if (!block) continue
        try {
            const action: unknown = JSON.parse(block)
            if (isRecord(action) && isString(action.surfaceId)) ids.add(action.surfaceId)
        } catch {
            // Not an action this panel sent; it answers nothing.
        }
    }
    return ids
}

/** The newest panel among tool results given in conversation order. */
export function latestSurfaceId(results: readonly unknown[]): string | null {
    for (let index = results.length - 1; index >= 0; index--) {
        const surface = surfaceFromToolResult(results[index])
        if (surface) return surface.surfaceId
    }
    return null
}

export interface SurfaceConversation {
    latestSurfaceId: string | null
    answered: ReadonlySet<string>
    /** A run is queued or running; a click now would start a second one. */
    runActive: boolean
}

export const SURFACE_NOTES = {
    answered: "ส่งคำสั่งแล้ว",
    outdated: "แผงนี้ไม่ใช่แผงล่าสุด สถานะเอกสารอาจไม่เป็นปัจจุบัน",
} as const

/** Only the newest surface stays actionable, until it is answered, and never while a run is active. */
export function surfaceAvailability(surfaceId: string, conversation: SurfaceConversation): { actionable: boolean; notes: string[] } {
    const answered = conversation.answered.has(surfaceId)
    const outdated = surfaceId !== conversation.latestSurfaceId
    const notes: string[] = []
    if (answered) notes.push(SURFACE_NOTES.answered)
    if (outdated) notes.push(SURFACE_NOTES.outdated)
    return { actionable: !answered && !outdated && !conversation.runActive, notes }
}
