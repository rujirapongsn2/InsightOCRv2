// A2UI v0.9 surfaces for the Jobs agent. The server validates render_ui, but a
// persisted tool result is still external data here: parseSurface checks it once
// and returns null for anything this catalog cannot render, so callers fall back.

export const A2UI_VERSION = "v0.9"
export const JOBS_CATALOG_ID = "https://insightdoc.app/a2ui/catalogs/jobs/v1"
export const ACTION_FENCE = "a2ui-action"

export type Binding = { path: string }
export type Dynamic<T> = T | Binding
export type ActionEventName = "approve_documents" | "reject_documents" | "ask_agent"
type ActionContext = Record<string, unknown>

export const NUMBER_FORMATS = ["number", "currency", "percent"] as const
export const COLUMN_TYPES = ["text", "number", "currency", "percent", "date", "delta", "risk"] as const
export const RISK_LEVELS = ["critical", "high", "medium", "low"] as const
const DIRECTIONS = ["up", "down", "flat"] as const
const SENTIMENTS = ["good", "bad", "neutral"] as const
const ALIGNS = ["left", "center", "right"] as const
export const MAX_CHART_SERIES = 8

export type NumberFormat = (typeof NUMBER_FORMATS)[number]
export type ColumnType = (typeof COLUMN_TYPES)[number]
export type RiskLevel = (typeof RISK_LEVELS)[number]
export type Direction = (typeof DIRECTIONS)[number]
export type Sentiment = (typeof SENTIMENTS)[number]

/** A change: direction is which way the number moved, sentiment whether that is good for the user. */
export interface Delta {
    value: number
    direction: Direction
    sentiment: Sentiment
    label?: string
}

export interface TableColumn {
    key: string
    label: string
    type: ColumnType
    align: (typeof ALIGNS)[number]
}

export interface ChartSeries {
    key: string
    label: string
}

export interface RiskItem {
    title: string
    level: RiskLevel
    category?: string
    description: string
    quote?: string
    /** Set by the server after looking for the quote in the document's text. */
    quote_verified?: boolean
    document_id?: string
    page?: number
    recommendation?: string
}

export type A2uiComponent =
    | { id: string; component: "Column"; children: string[] }
    | { id: string; component: "Row"; children: string[] }
    | { id: string; component: "Text"; text: Dynamic<string>; variant: "body" | "caption" | "heading" }
    | { id: string; component: "DocumentList"; documents: Binding; selectable: boolean; selection?: string }
    | {
        id: string
        component: "Button"
        label: string
        variant: "primary" | "secondary"
        action: { event: { name: ActionEventName; context: ActionContext } }
    }
    | {
        id: string
        component: "Metric"
        label: string
        value: Dynamic<number>
        unit?: string
        format: NumberFormat
        delta?: Delta
    }
    | { id: string; component: "DataTable"; columns: TableColumn[]; rows: Binding; caption?: string }
    | {
        id: string
        component: "Chart"
        type: "bar" | "line"
        title?: string
        x: string
        series: ChartSeries[]
        data: Binding
        unit?: string
        format: NumberFormat
    }
    | { id: string; component: "RiskList"; items: Binding; title?: string }
    | { id: string; component: "RiskBadge"; level: RiskLevel }

/** Components that show numbers the agent computed; a surface with any of them says so. */
export const COMPUTED_COMPONENTS: readonly ComponentType[] = ["Metric", "DataTable", "Chart"]
export const COMPUTED_NOTE = "ตัวเลขในแผงนี้ AI คำนวณจากข้อมูลที่ดึงจากเอกสาร ควรตรวจทานก่อนนำไปใช้"

export type ComponentType = A2uiComponent["component"]
export type ComponentOf<K extends ComponentType> = Extract<A2uiComponent, { component: K }>
export type DataModel = Record<string, unknown>

export interface Surface {
    surfaceId: string
    catalogId: string
    components: Record<string, A2uiComponent>
    dataModel: DataModel
}

export interface DocumentRow {
    document_id: string
    filename: string
    status: string
    note?: string
}

export interface A2uiAction {
    name: ActionEventName
    surfaceId: string
    sourceComponentId: string
    timestamp: string
    context: ActionContext
}

const ACTION_EVENTS: readonly ActionEventName[] = ["approve_documents", "reject_documents", "ask_agent"]

type Raw = Record<string, unknown>

function isRecord(value: unknown): value is Raw {
    return typeof value === "object" && value !== null && !Array.isArray(value)
}

export function isBinding(value: unknown): value is Binding {
    return isRecord(value) && Object.keys(value).length === 1 && typeof value.path === "string" && value.path.startsWith("/")
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

/** Whether every parent on path is an object (or missing), so setPointer never replaces an array or a value. */
function isObjectPath(data: DataModel, path: string): boolean {
    let node: unknown = data
    for (const token of pointerTokens(path).slice(0, -1)) {
        if (!isRecord(node)) return false
        if (!Object.hasOwn(node, token)) return true
        node = node[token]
    }
    return isRecord(node)
}

const overlaps = (a: string, b: string) => a === b || a.startsWith(b + "/") || b.startsWith(a + "/")

/** The pointers the renderer reads rows from and writes selections to are plain object paths. */
function hasSafePointers(surface: Surface): boolean {
    return Object.values(surface.components).every(c => c.component !== "DocumentList" || (
        isObjectPath(surface.dataModel, c.documents.path)
        && (!c.selection || (isObjectPath(surface.dataModel, c.selection) && !overlaps(c.selection, c.documents.path)))
    ))
}

export function setPointer(data: DataModel, path: string, value: unknown): DataModel {
    const tokens = pointerTokens(path)
    if (tokens.length === 0) return isRecord(value) ? value : data
    const [head, ...rest] = tokens
    const child = isRecord(data[head]) ? (data[head] as DataModel) : {}
    return { ...data, [head]: rest.length === 0 ? value : setPointer(child, "/" + rest.join("/"), value) }
}

export function resolveValue<T>(value: Dynamic<T>, data: DataModel): unknown {
    return isBinding(value) ? getPointer(data, value.path) : value
}

const oneOf = <T extends string>(value: unknown, allowed: readonly T[], fallback: T): T | null =>
    value === undefined ? fallback : allowed.includes(value as T) ? (value as T) : null

export const isFiniteNumber = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value)
const optionalString = (value: unknown): string | undefined | null =>
    value === undefined ? undefined : typeof value === "string" ? value : null
const stringChildren = (value: unknown): string[] | null =>
    Array.isArray(value) && value.every(c => typeof c === "string") ? value : null

/** The values each direction allows, as the server checks them: "flat" is exactly no change. */
const DIRECTION_ALLOWS: Record<Direction, (value: number) => boolean> = {
    up: value => value >= 0,
    down: value => value <= 0,
    flat: value => value === 0,
}

export function parseDelta(value: unknown): Delta | null {
    if (!isRecord(value) || !isFiniteNumber(value.value)) return null
    const direction = DIRECTIONS.find(d => d === value.direction)
    const sentiment = SENTIMENTS.find(s => s === value.sentiment)
    const label = optionalString(value.label)
    if (!direction || !sentiment || label === null || !DIRECTION_ALLOWS[direction](value.value)) return null
    return { value: value.value, direction, sentiment, ...(label ? { label } : {}) }
}

function parseColumn(raw: unknown): TableColumn | null {
    if (!isRecord(raw) || typeof raw.key !== "string" || typeof raw.label !== "string") return null
    const type = COLUMN_TYPES.find(t => t === raw.type)
    if (!type) return null
    const numeric = type === "number" || type === "currency" || type === "percent" || type === "delta"
    const align = oneOf(raw.align, ALIGNS, numeric ? "right" : "left")
    return align ? { key: raw.key, label: raw.label, type, align } : null
}

const COMPONENT_PARSERS: { [K in ComponentType]: (raw: Raw, id: string) => ComponentOf<K> | null } = {
    Column: (raw, id) => {
        const children = stringChildren(raw.children)
        return children && { id, component: "Column", children }
    },
    Row: (raw, id) => {
        const children = stringChildren(raw.children)
        return children && { id, component: "Row", children }
    },
    Metric: (raw, id) => {
        const format = oneOf(raw.format, NUMBER_FORMATS, "number")
        const unit = optionalString(raw.unit)
        const delta = raw.delta === undefined ? undefined : parseDelta(raw.delta)
        const value = raw.value
        if (typeof raw.label !== "string" || !format || unit === null || delta === null) return null
        if (!isFiniteNumber(value) && !isBinding(value)) return null
        return { id, component: "Metric", label: raw.label, value, unit, format, delta }
    },
    DataTable: (raw, id) => {
        const columns = Array.isArray(raw.columns) ? raw.columns.map(parseColumn) : []
        const caption = optionalString(raw.caption)
        if (columns.length === 0 || columns.some(c => c === null) || !isBinding(raw.rows) || caption === null) return null
        return { id, component: "DataTable", columns: columns as TableColumn[], rows: raw.rows, caption }
    },
    Chart: (raw, id) => {
        const type = raw.type === "bar" || raw.type === "line" ? raw.type : null
        const format = oneOf(raw.format, NUMBER_FORMATS, "number")
        const title = optionalString(raw.title)
        const unit = optionalString(raw.unit)
        const series = Array.isArray(raw.series) && raw.series.length > 0 && raw.series.length <= MAX_CHART_SERIES
            && raw.series.every(s => isRecord(s) && typeof s.key === "string" && typeof s.label === "string")
            ? raw.series.map(s => ({ key: s.key, label: s.label }) as ChartSeries) : null
        if (!type || !format || title === null || unit === null || !series) return null
        if (typeof raw.x !== "string" || !isBinding(raw.data)) return null
        return { id, component: "Chart", type, title, x: raw.x, series, data: raw.data, unit, format }
    },
    RiskList: (raw, id) => {
        const title = optionalString(raw.title)
        return isBinding(raw.items) && title !== null ? { id, component: "RiskList", items: raw.items, title } : null
    },
    RiskBadge: (raw, id) => {
        const level = RISK_LEVELS.find(l => l === raw.level)
        return level ? { id, component: "RiskBadge", level } : null
    },
    Text: (raw, id) => {
        const variant = oneOf(raw.variant, ["body", "caption", "heading"] as const, "body")
        if (!variant || !(typeof raw.text === "string" || isBinding(raw.text))) return null
        return { id, component: "Text", text: raw.text, variant }
    },
    DocumentList: (raw, id) => {
        if (!isBinding(raw.documents)) return null
        const selectable = raw.selectable === true
        const selection = typeof raw.selection === "string" && raw.selection.startsWith("/") ? raw.selection : undefined
        if (selectable && !selection) return null
        return { id, component: "DocumentList", documents: raw.documents, selectable, selection }
    },
    Button: (raw, id) => {
        const variant = oneOf(raw.variant, ["primary", "secondary"] as const, "secondary")
        const event = isRecord(raw.action) && isRecord(raw.action.event) ? raw.action.event : null
        if (!variant || typeof raw.label !== "string" || !event) return null
        const name = ACTION_EVENTS.find(allowed => allowed === event.name)
        if (!name) return null
        const context = event.context === undefined ? {} : event.context
        if (!isRecord(context)) return null
        return { id, component: "Button", label: raw.label, variant, action: { event: { name, context } } }
    },
}

function parseComponent(raw: unknown): A2uiComponent | null {
    if (!isRecord(raw) || typeof raw.id !== "string" || typeof raw.component !== "string") return null
    if (!Object.hasOwn(COMPONENT_PARSERS, raw.component)) return null
    const parse = COMPONENT_PARSERS[raw.component as ComponentType] as (raw: Raw, id: string) => A2uiComponent | null
    return parse(raw, raw.id)
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

/** Fold a render_ui message list into one surface; null when anything is outside this catalog. */
export function parseSurface(messages: unknown): Surface | null {
    if (!Array.isArray(messages)) return null
    let surface: Surface | null = null
    for (const message of messages) {
        if (!isRecord(message) || message.version !== A2UI_VERSION) return null
        if (isRecord(message.createSurface)) {
            const { surfaceId, catalogId } = message.createSurface
            if (surface || typeof surfaceId !== "string" || catalogId !== JOBS_CATALOG_ID) return null
            surface = { surfaceId, catalogId, components: {}, dataModel: {} }
        } else if (isRecord(message.updateComponents)) {
            const update = message.updateComponents
            if (!surface || update.surfaceId !== surface.surfaceId || !Array.isArray(update.components)) return null
            for (const raw of update.components) {
                const component = parseComponent(raw)
                if (!component) return null
                surface.components[component.id] = component
            }
        } else if (isRecord(message.updateDataModel)) {
            const update = message.updateDataModel
            if (!surface || update.surfaceId !== surface.surfaceId || typeof update.path !== "string") return null
            if (!isObjectPath(surface.dataModel, update.path)) return null
            surface.dataModel = setPointer(surface.dataModel, update.path, update.value)
        } else {
            return null
        }
    }
    return surface && isTree(surface.components) && hasSafePointers(surface) ? surface : null
}

export function surfaceFromToolResult(result: unknown): Surface | null {
    return isRecord(result) && result.ok === true ? parseSurface(result.a2ui) : null
}

export function documentRows(value: unknown): DocumentRow[] {
    if (!Array.isArray(value)) return []
    return value.filter((row): row is DocumentRow =>
        isRecord(row) && typeof row.document_id === "string" && typeof row.filename === "string" && typeof row.status === "string")
}

export function tableRows(value: unknown): Raw[] {
    return Array.isArray(value) ? value.filter(isRecord) : []
}

export interface ChartPoint {
    label: string
    /** One value per series, in series order; null where the series has no value. */
    values: (number | null)[]
}

export function chartPoints(value: unknown, x: string, series: readonly ChartSeries[]): ChartPoint[] {
    return tableRows(value)
        .filter(point => typeof point[x] === "string" || isFiniteNumber(point[x]))
        .map(point => ({
            label: String(point[x]),
            values: series.map(s => (isFiniteNumber(point[s.key]) ? point[s.key] as number : null)),
        }))
}

function parseRiskItem(raw: unknown): RiskItem | null {
    if (!isRecord(raw) || typeof raw.title !== "string" || typeof raw.description !== "string") return null
    const level = RISK_LEVELS.find(l => l === raw.level)
    if (!level) return null
    const text = (key: string) => (typeof raw[key] === "string" && raw[key] ? { [key]: raw[key] as string } : {})
    return {
        title: raw.title,
        level,
        description: raw.description,
        ...text("category"),
        ...text("quote"),
        ...text("document_id"),
        ...text("recommendation"),
        ...(typeof raw.quote_verified === "boolean" ? { quote_verified: raw.quote_verified } : {}),
        ...(Number.isInteger(raw.page) && (raw.page as number) > 0 ? { page: raw.page as number } : {}),
    }
}

/** Risk items, most severe first; the server's order is kept within a level. */
export function riskItems(value: unknown): RiskItem[] {
    const items = Array.isArray(value) ? value.map(parseRiskItem).filter((item): item is RiskItem => item !== null) : []
    return items.sort((a, b) => RISK_LEVELS.indexOf(a.level) - RISK_LEVELS.indexOf(b.level))
}

export function riskCounts(items: readonly RiskItem[]): Record<RiskLevel, number> {
    const counts = { critical: 0, high: 0, medium: 0, low: 0 }
    for (const item of items) counts[item.level] += 1
    return counts
}

export function selectedIds(data: DataModel, path: string | undefined): string[] {
    const value = path ? getPointer(data, path) : undefined
    return Array.isArray(value) ? value.filter((id): id is string => typeof id === "string") : []
}

export function resolveContext(context: ActionContext, data: DataModel): ActionContext {
    return Object.fromEntries(Object.entries(context).map(([key, value]) => [key, resolveValue(value, data)]))
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
    if (action.name === "approve_documents" && list) return `อนุมัติเอกสาร ${list.length} รายการที่เลือก`
    if (action.name === "reject_documents" && list) return `ปฏิเสธเอกสาร ${list.length} รายการที่เลือก`
    const question = action.context.question
    return typeof question === "string" && question.trim() ? question.trim() : label
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
            if (isRecord(action) && typeof action.surfaceId === "string") ids.add(action.surfaceId)
        } catch {
            // Not an action this panel sent; it answers nothing.
        }
    }
    return ids
}

/** The newest render_ui surface among tool results given in conversation order. */
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
