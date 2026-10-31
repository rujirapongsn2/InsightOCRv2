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

export type A2uiComponent =
    | { id: string; component: "Column"; children: string[] }
    | { id: string; component: "Text"; text: Dynamic<string>; variant: "body" | "caption" | "heading" }
    | { id: string; component: "DocumentList"; documents: Binding; selectable: boolean; selection?: string }
    | {
        id: string
        component: "Button"
        label: string
        variant: "primary" | "secondary"
        action: { event: { name: ActionEventName; context: ActionContext } }
    }

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

const COMPONENT_PARSERS: { [K in ComponentType]: (raw: Raw, id: string) => ComponentOf<K> | null } = {
    Column: (raw, id) => {
        const children = raw.children
        if (!Array.isArray(children) || !children.every(c => typeof c === "string")) return null
        return { id, component: "Column", children: children as string[] }
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
        return node.component !== "Column" || node.children.every(walk)
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
            surface.dataModel = setPointer(surface.dataModel, update.path, update.value)
        } else {
            return null
        }
    }
    return surface && isTree(surface.components) ? surface : null
}

export function surfaceFromToolResult(result: unknown): Surface | null {
    return isRecord(result) && result.ok === true ? parseSurface(result.a2ui) : null
}

export function documentRows(value: unknown): DocumentRow[] {
    if (!Array.isArray(value)) return []
    return value.filter((row): row is DocumentRow =>
        isRecord(row) && typeof row.document_id === "string" && typeof row.filename === "string" && typeof row.status === "string")
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

const ACTION_BLOCK_RE = new RegExp("\\n*```" + ACTION_FENCE + "\\n[\\s\\S]*?\\n```\\s*$")

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
