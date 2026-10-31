"use client"

import { Component, useState, type ReactNode } from "react"
import { Button } from "@/components/ui/button"
import { Chart, DataTable, Metric, OpenDocumentButton, RiskBadge, RiskList } from "@/components/agent/a2ui/analytics"
import {
    COMPUTED_COMPONENTS,
    COMPUTED_NOTE,
    actionMessage,
    buildAction,
    documentRows,
    documentStatusLabel,
    getPointer,
    hasEmptyBinding,
    resolveValue,
    selectedIds,
    setPointer,
    type A2uiComponent,
    type ComponentOf,
    type ComponentType,
    type DataModel,
    type Surface,
} from "@/lib/a2ui"

export interface A2uiSurfaceProps {
    surface: Surface
    /** Shown instead of the surface if rendering fails. */
    fallback: ReactNode
    actionsDisabled?: boolean
    /** Short lines under the surface saying why its buttons are off. */
    notes?: string[]
    /** Receives the user message a button click sends to the agent. */
    onAction?: (message: string) => void
    onOpenDocument?: (documentId: string) => void
}

interface RenderContext {
    surface: Surface
    data: DataModel
    setData: (path: string, value: unknown) => void
    actionsDisabled: boolean
    onAction?: (message: string) => void
    onOpenDocument?: (documentId: string) => void
    render: (id: string) => ReactNode
}

const TEXT_CLASS = {
    heading: "text-sm font-semibold text-ink-navy",
    body: "text-sm text-ink-navy",
    caption: "text-xs text-slate-gray",
} as const

function DocumentList({ component, ctx }: { component: ComponentOf<"DocumentList">; ctx: RenderContext }) {
    const rows = documentRows(getPointer(ctx.data, component.documents.path))
    const selected = new Set(selectedIds(ctx.data, component.selection))
    const setSelected = (ids: string[]) => component.selection && ctx.setData(component.selection, ids)
    const toggle = (id: string) => setSelected(
        selected.has(id) ? [...selected].filter(other => other !== id) : [...selected, id])
    const allSelected = rows.length > 0 && rows.every(row => selected.has(row.document_id))

    if (rows.length === 0) return <p className="text-xs text-slate-gray">ไม่มีเอกสาร</p>
    return (
        <div className="overflow-hidden rounded-md border border-hairline">
            {component.selectable && (
                <label className="flex items-center gap-2 border-b border-hairline bg-off-white px-3 py-2 text-xs text-slate-gray">
                    <input
                        type="checkbox"
                        checked={allSelected}
                        onChange={() => setSelected(allSelected ? [] : rows.map(row => row.document_id))}
                        className="h-3.5 w-3.5 accent-softnix-blue"
                    />
                    เลือกทั้งหมด ({selected.size}/{rows.length})
                </label>
            )}
            <ul className="max-h-72 divide-y divide-hairline overflow-y-auto">
                {rows.map(row => (
                    <li key={row.document_id} className="flex items-start gap-2 px-3 py-2">
                        {component.selectable && (
                            <input
                                type="checkbox"
                                aria-label={`เลือก ${row.filename}`}
                                checked={selected.has(row.document_id)}
                                onChange={() => toggle(row.document_id)}
                                className="mt-0.5 h-3.5 w-3.5 accent-softnix-blue"
                            />
                        )}
                        <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-2">
                                <span className="truncate text-sm text-ink-navy" title={row.filename}>{row.filename}</span>
                                <span className="shrink-0 rounded-full border border-hairline px-2 py-0.5 text-xs text-slate-gray">
                                    {documentStatusLabel(row.status)}
                                </span>
                            </div>
                            {row.note && <p className="mt-0.5 text-xs text-slate-gray">{row.note}</p>}
                        </div>
                        {ctx.onOpenDocument && <OpenDocumentButton documentId={row.document_id} onOpen={ctx.onOpenDocument} />}
                    </li>
                ))}
            </ul>
        </div>
    )
}

const CATALOG: { [K in ComponentType]: (component: ComponentOf<K>, ctx: RenderContext) => ReactNode } = {
    Column: (component, ctx) => (
        <div className="flex flex-col gap-2">
            {component.children.map(id => <div key={id}>{ctx.render(id)}</div>)}
        </div>
    ),
    Row: (component, ctx) => (
        <div className="flex flex-wrap gap-2">
            {component.children.map(id => <div key={id} className="min-w-[9rem] flex-1">{ctx.render(id)}</div>)}
        </div>
    ),
    Metric: (component, ctx) => <Metric component={component} data={ctx.data} />,
    DataTable: (component, ctx) => <DataTable component={component} data={ctx.data} onOpenDocument={ctx.onOpenDocument} />,
    Chart: (component, ctx) => <Chart component={component} data={ctx.data} />,
    RiskList: (component, ctx) => <RiskList component={component} data={ctx.data} onOpenDocument={ctx.onOpenDocument} />,
    RiskBadge: component => <RiskBadge level={component.level} />,
    Text: (component, ctx) => {
        const text = resolveValue(component.text, ctx.data)
        return <p className={TEXT_CLASS[component.variant]}>{typeof text === "string" ? text : ""}</p>
    },
    DocumentList: (component, ctx) => <DocumentList component={component} ctx={ctx} />,
    Button: (component, ctx) => {
        const disabled = ctx.actionsDisabled || !ctx.onAction || hasEmptyBinding(component.action.event.context, ctx.data)
        return (
            <Button
                size="sm"
                variant={component.variant === "primary" ? "default" : "outline"}
                disabled={disabled}
                onClick={() => ctx.onAction?.(actionMessage(
                    buildAction(ctx.surface, component, ctx.data, new Date().toISOString()), component.label))}
            >
                {component.label}
            </Button>
        )
    },
}

class SurfaceBoundary extends Component<{ fallback: ReactNode; children: ReactNode }, { failed: boolean }> {
    state = { failed: false }

    static getDerivedStateFromError() {
        return { failed: true }
    }

    render() {
        return this.state.failed ? this.props.fallback : this.props.children
    }
}

function SurfaceBody({ surface, actionsDisabled = false, notes = [], onAction, onOpenDocument }: Omit<A2uiSurfaceProps, "fallback">) {
    const [data, setDataModel] = useState<DataModel>(surface.dataModel)
    const ctx: RenderContext = {
        surface,
        data,
        setData: (path, value) => setDataModel(current => setPointer(current, path, value)),
        actionsDisabled,
        onAction,
        onOpenDocument,
        render: id => {
            const component = surface.components[id]
            const render = CATALOG[component.component] as (component: A2uiComponent, ctx: RenderContext) => ReactNode
            return render(component, ctx)
        },
    }
    return (
        <div className="mx-3 rounded-lg border border-hairline bg-white p-3" data-surface-id={surface.surfaceId}>
            {ctx.render("root")}
            {Object.values(surface.components).some(c => COMPUTED_COMPONENTS.includes(c.component)) && (
                <p className="mt-2 text-xs text-viz-muted">{COMPUTED_NOTE}</p>
            )}
            {notes.map(note => <p key={note} className="mt-2 text-xs text-slate-gray">{note}</p>)}
        </div>
    )
}

export default function A2uiSurface({ fallback, ...props }: A2uiSurfaceProps) {
    return (
        <SurfaceBoundary fallback={fallback}>
            <SurfaceBody {...props} />
        </SurfaceBoundary>
    )
}
