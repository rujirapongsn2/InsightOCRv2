import { CircleAlert, CircleCheck, Eye, Info, OctagonAlert, TriangleAlert, type LucideIcon } from "lucide-react"
import {
    RISK_LEVELS,
    bySeverity,
    quoteSummary,
    riskCounts,
    type Change,
    type ChartPoint,
    type ChartSeries,
    type ComponentOf,
    type DocumentRef,
    type Measure,
    type RiskItem,
    type RiskLevel,
    type TableCell,
    type XKind,
} from "@/lib/a2ui"
import { axisUnit, describeChange, formatDate, formatMeasure, formatMonth, formatTick, formatX } from "@/lib/a2uiFormat"

type OpenDocument = ((documentId: string) => void) | undefined

/** Color carries sentiment only; the glyph carries direction, and both are also in text. */
const SENTIMENT_CLASS = { good: "text-viz-good", bad: "text-viz-bad", neutral: "text-viz-neutral" } as const

export function ChangeText({ change, measure }: { change: Change; measure: Measure }) {
    const view = describeChange(change, measure)
    return (
        <span className={`inline-flex flex-wrap items-baseline gap-x-1 text-xs ${SENTIMENT_CLASS[change.sentiment]}`}>
            <span aria-hidden="true">{view.glyph}</span>
            <span className="sr-only">{view.direction}</span>
            <span className="font-medium tabular-nums">{view.amount}</span>
            {view.sentiment && <span>({view.sentiment})</span>}
            {view.detail && <span className="text-viz-muted tabular-nums">{view.detail}</span>}
        </span>
    )
}

const RISK_VIEW: Record<RiskLevel, { label: string; Icon: LucideIcon; className: string }> = {
    critical: { label: "วิกฤต", Icon: OctagonAlert, className: "bg-viz-critical-bg text-viz-critical-fg" },
    high: { label: "สูง", Icon: TriangleAlert, className: "bg-viz-high-bg text-viz-high-fg" },
    medium: { label: "ปานกลาง", Icon: CircleAlert, className: "bg-viz-medium-bg text-viz-medium-fg" },
    low: { label: "ต่ำ", Icon: Info, className: "bg-viz-low-bg text-viz-low-fg" },
}

export function RiskBadge({ level }: { level: RiskLevel }) {
    const { label, Icon, className } = RISK_VIEW[level]
    return (
        <span className={`inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${className}`}>
            <Icon aria-hidden="true" className="h-3 w-3" />
            <span className="sr-only">ความเสี่ยง</span>
            {label}
        </span>
    )
}

export function OpenDocumentButton({ documentId, onOpen }: { documentId: string; onOpen: (documentId: string) => void }) {
    return (
        <button
            type="button"
            onClick={() => onOpen(documentId)}
            className="inline-flex shrink-0 items-center gap-1 text-xs font-medium text-softnix-blue hover:text-softnix-deep"
        >
            <Eye className="h-3.5 w-3.5" />
            เปิดดู
        </button>
    )
}

function DocumentName({ document, onOpen }: { document: DocumentRef; onOpen: OpenDocument }) {
    return (
        <span className="inline-flex min-w-0 max-w-full items-center gap-2">
            <span className="truncate" title={document.filename}>{document.filename}</span>
            {onOpen && <OpenDocumentButton documentId={document.document_id} onOpen={onOpen} />}
        </span>
    )
}

const Dash = () => <span className="text-viz-muted">–</span>

/** "AI คำนวณจาก N เอกสาร", opening to the documents the numbers came from. */
export function Sources({ component, onOpenDocument }: { component: ComponentOf<"Sources">; onOpenDocument: OpenDocument }) {
    return (
        <details className="text-xs">
            <summary className="cursor-pointer text-viz-muted hover:text-ink-navy">
                AI คำนวณจาก {component.documents.length} เอกสาร
            </summary>
            <ul className="mt-1 space-y-1 pl-4">
                {component.documents.map(document => (
                    <li key={document.document_id} className="text-ink-navy">
                        <DocumentName document={document} onOpen={onOpenDocument} />
                    </li>
                ))}
            </ul>
        </details>
    )
}

export function Metric({ component }: { component: ComponentOf<"Metric"> }) {
    const { value, previous, change } = component.value
    return (
        <div className="h-full rounded-md border border-hairline px-3 py-2">
            <p className="text-xs text-viz-muted">{component.label}</p>
            <p className="text-lg font-semibold text-ink-navy tabular-nums">{formatMeasure(value, component.measure)}</p>
            {change && <ChangeText change={change} measure={component.measure} />}
            {previous !== undefined && (
                <p className="text-xs text-viz-muted">
                    เทียบ{component.previousLabel ? ` ${component.previousLabel}` : "ค่าก่อนหน้า"}:{" "}
                    <span className="tabular-nums">{formatMeasure(previous, component.measure)}</span>
                </p>
            )}
        </div>
    )
}

function Cell({ cell, onOpenDocument }: { cell: TableCell; onOpenDocument: OpenDocument }) {
    switch (cell.kind) {
        case "empty": return <Dash />
        case "text": return <>{cell.value}</>
        case "date": return <>{formatDate(cell.value)}</>
        case "month": return <>{formatMonth(cell.value)}</>
        case "document": return <DocumentName document={cell.value} onOpen={onOpenDocument} />
        case "measure": return <>{formatMeasure(cell.value, cell.measure)}</>
        case "change": return <ChangeText change={cell.value} measure={cell.measure} />
    }
}

const isNumeric = (kind: string) => kind === "measure" || kind === "change"

export function DataTable({ component, onOpenDocument }: { component: ComponentOf<"DataTable">; onOpenDocument: OpenDocument }) {
    return (
        <div className="max-h-80 overflow-auto rounded-md border border-hairline">
            <table className="w-full min-w-max border-collapse text-sm">
                <thead className="sticky top-0 bg-off-white">
                    <tr>
                        {component.columns.map(column => (
                            <th key={column.key} scope="col" className={`px-3 py-1.5 text-xs font-medium text-viz-muted ${
                                isNumeric(column.format.kind) ? "text-right" : "text-left"}`}>
                                {column.label}
                            </th>
                        ))}
                    </tr>
                </thead>
                <tbody className="divide-y divide-hairline">
                    {component.rows.map((row, index) => (
                        <tr key={index}>
                            {row.map((cell, columnIndex) => (
                                <td key={component.columns[columnIndex].key} className={`px-3 py-1.5 text-ink-navy tabular-nums ${
                                    isNumeric(component.columns[columnIndex].format.kind) ? "text-right" : "text-left"}`}>
                                    <Cell cell={cell} onOpenDocument={onOpenDocument} />
                                </td>
                            ))}
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    )
}

// Fixed slot order (see the viz tokens in globals.css); a series keeps its slot.
const SERIES_CLASS = [
    "text-viz-1", "text-viz-2", "text-viz-3", "text-viz-4",
    "text-viz-5", "text-viz-6", "text-viz-7", "text-viz-8",
] as const

const round = (value: number) => Math.round(value * 100) / 100
const isValue = (value: number | null): value is number => value !== null

function niceStep(raw: number): number {
    const power = 10 ** Math.floor(Math.log10(raw))
    const fraction = raw / power
    return (fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 5 ? 5 : 10) * power
}

/** A value axis with round tick values covering values (and zero when asked). */
export function niceScale(values: number[], includeZero: boolean): { min: number; max: number; ticks: number[] } {
    let low = Math.min(...values)
    let high = Math.max(...values)
    if (includeZero) {
        low = Math.min(low, 0)
        high = Math.max(high, 0)
    }
    const step = niceStep((high - low || Math.abs(high) || 1) / 4)
    const min = Math.floor(low / step) * step
    const max = Math.max(Math.ceil(high / step) * step, min + step)
    const ticks: number[] = []
    for (let tick = min; tick <= max + step / 2; tick += step) ticks.push(Number(tick.toPrecision(12)))
    return { min, max, ticks }
}

interface PlotProps {
    points: ChartPoint[]
    series: ChartSeries[]
    measure: Measure
    xKind: XKind
}

const BAR_HEIGHT = 12
const BAR_GAP = 2

function BarChart({ points, series, measure, xKind }: PlotProps) {
    // No value axis here (each bar is labelled), so the longest bar may fill the track.
    const values = points.flatMap(point => point.values.filter(isValue))
    const min = Math.min(0, ...values)
    const max = Math.max(0, ...values)
    const percent = (value: number) => (max === min ? 0 : round(((value - min) / (max - min)) * 100))
    const zero = percent(0)
    const height = series.length * BAR_HEIGHT + (series.length - 1) * BAR_GAP
    return (
        <div className="space-y-1.5">
            {points.map((point, pointIndex) => {
                const label = formatX(point.x, xKind)
                return (
                    <div key={pointIndex}
                        className="grid grid-cols-[minmax(0,6rem)_minmax(0,1fr)_auto] items-center gap-x-2 sm:grid-cols-[minmax(0,9rem)_minmax(0,1fr)_auto]">
                        <span className="truncate text-xs text-charcoal" title={label}>{label}</span>
                        <svg width="100%" height={height} aria-hidden="true" className="block overflow-visible">
                            {min < 0 && <line x1={`${zero}%`} x2={`${zero}%`} y1={0} y2={height} className="stroke-viz-grid" strokeWidth={1} />}
                            {point.values.map((value, seriesIndex) => value !== null && (
                                <rect
                                    key={seriesIndex}
                                    data-bar=""
                                    x={`${Math.min(zero, percent(value))}%`}
                                    y={seriesIndex * (BAR_HEIGHT + BAR_GAP)}
                                    width={`${Math.abs(percent(value) - zero)}%`}
                                    height={BAR_HEIGHT}
                                    rx={3}
                                    fill="currentColor"
                                    className={SERIES_CLASS[seriesIndex]}
                                >
                                    <title>{`${label} · ${series[seriesIndex].label}: ${formatMeasure(value, measure)}`}</title>
                                </rect>
                            ))}
                        </svg>
                        <div className="flex flex-col text-right text-[11px] leading-[14px] text-ink-navy tabular-nums">
                            {point.values.map((value, seriesIndex) => (
                                <span key={seriesIndex}>{value === null ? "–" : formatMeasure(value, measure)}</span>
                            ))}
                        </div>
                    </div>
                )
            })}
        </div>
    )
}

const MAX_MARKED_POINTS = 24
const MAX_X_LABELS = 5

function linePath(values: (number | null)[], x: (index: number) => number, y: (value: number) => number): string {
    let path = ""
    let penDown = false
    values.forEach((value, index) => {
        if (value === null) {
            penDown = false
            return
        }
        path += `${penDown ? "L" : "M"}${round(x(index))} ${round(y(value))}`
        penDown = true
    })
    return path
}

/**
 * The point indices that get an x label: the first, every step-th, and the last, at most
 * maxLabels. A step label closer than step to the last one is dropped so the two never collide.
 */
export function xLabelIndices(count: number, maxLabels: number): number[] {
    if (count <= 0) return []
    const last = count - 1
    const step = Math.max(1, Math.ceil(last / (maxLabels - 1)))
    const indices: number[] = []
    for (let index = 0; index < last; index += step) indices.push(index)
    if (indices.length > 1 && last - indices[indices.length - 1] < step) indices.pop()
    return [...indices, last]
}

function LineChart({ points, series, measure, xKind }: PlotProps) {
    const count = points.length
    const { min, max, ticks } = niceScale(points.flatMap(point => point.values.filter(isValue)), false)
    const x = (index: number) => (count === 1 ? 50 : (index / (count - 1)) * 100)
    const y = (value: number) => 100 - ((value - min) / (max - min)) * 100
    const labelled = xLabelIndices(count, MAX_X_LABELS)
    // Every point gets a marker while they stay legible; past that, only each series' last point does.
    const lastIndex = series.map((_, seriesIndex) => points.findLastIndex(point => point.values[seriesIndex] !== null))
    const marked = (seriesIndex: number, index: number) => count <= MAX_MARKED_POINTS || index === lastIndex[seriesIndex]
    const unit = axisUnit(measure)
    return (
        <div className={`relative mb-6 ml-12 mr-3 h-40 ${unit ? "mt-7" : "mt-2"}`}>
            {unit && (
                <span data-axis-title="" className="absolute -left-12 bottom-full mb-3 whitespace-nowrap text-[11px] text-viz-muted">
                    {unit}
                </span>
            )}
            {ticks.map(tick => (
                <span key={tick} data-tick="" className="absolute -left-12 w-10 -translate-y-1/2 text-right text-[11px] text-viz-muted tabular-nums"
                    style={{ top: `${round(y(tick))}%` }}>
                    {formatTick(tick, measure)}
                </span>
            ))}
            <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true"
                className="absolute inset-0 h-full w-full overflow-visible">
                {ticks.map(tick => (
                    <line key={tick} x1={0} x2={100} y1={round(y(tick))} y2={round(y(tick))}
                        className="stroke-viz-grid" strokeWidth={1} vectorEffect="non-scaling-stroke" />
                ))}
                {series.map((item, seriesIndex) => {
                    const values = points.map(point => point.values[seriesIndex])
                    return (
                        <g key={item.key} className={SERIES_CLASS[seriesIndex]}>
                            <path d={linePath(values, x, y)} fill="none" stroke="currentColor" strokeWidth={2}
                                strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
                            {values.map((value, index) => value !== null && marked(seriesIndex, index) && (
                                <g key={index}>
                                    <path d={`M${round(x(index))} ${round(y(value))}h0`} className="stroke-viz-surface"
                                        strokeWidth={12} strokeLinecap="round" vectorEffect="non-scaling-stroke" />
                                    <path data-point="" d={`M${round(x(index))} ${round(y(value))}h0`} stroke="currentColor"
                                        strokeWidth={8} strokeLinecap="round" vectorEffect="non-scaling-stroke">
                                        <title>{`${formatX(points[index].x, xKind)} · ${item.label}: ${formatMeasure(value, measure)}`}</title>
                                    </path>
                                </g>
                            ))}
                        </g>
                    )
                })}
            </svg>
            {labelled.map(index => (
                <span key={index} data-x-label=""
                    className="absolute top-full mt-1 whitespace-nowrap text-[11px] text-viz-muted"
                    style={{
                        left: `${round(x(index))}%`,
                        transform: count === 1 ? "translateX(-50%)"
                            : index === 0 ? undefined : index === count - 1 ? "translateX(-100%)" : "translateX(-50%)",
                    }}>
                    {formatX(points[index].x, xKind)}
                </span>
            ))}
        </div>
    )
}

export function Chart({ component }: { component: ComponentOf<"Chart"> }) {
    const { points, series, measure } = component
    const plot = { points, series, measure, xKind: component.x.kind }
    const kind = component.type === "bar" ? "กราฟแท่ง" : "กราฟเส้น"
    return (
        <figure className="space-y-2">
            <figcaption className="text-sm font-semibold text-ink-navy">{component.title}</figcaption>
            {series.length > 1 && (
                <ul className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-ink-navy">
                    {series.map((item, index) => (
                        <li key={item.key} className="inline-flex items-center gap-1.5">
                            <span aria-hidden="true" className={`inline-block bg-current ${SERIES_CLASS[index]} ${
                                component.type === "line" ? "h-0.5 w-3" : "h-2.5 w-2.5 rounded-sm"}`} />
                            {item.label}
                        </li>
                    ))}
                </ul>
            )}
            <div role="img" aria-label={`${kind} ${component.title} ${points.length} รายการ ดูค่าในตารางด้านล่าง`}>
                {component.type === "bar" ? <BarChart {...plot} /> : <LineChart {...plot} />}
            </div>
            <details className="text-xs">
                <summary className="cursor-pointer text-viz-muted hover:text-ink-navy">ดูข้อมูลเป็นตาราง</summary>
                <div className="mt-1 max-h-60 overflow-auto">
                    <table className="w-full min-w-max border-collapse">
                        <thead>
                            <tr>
                                <th scope="col" className="px-2 py-1 text-left font-medium text-viz-muted">{component.x.label}</th>
                                {series.map(item => (
                                    <th key={item.key} scope="col" className="px-2 py-1 text-right font-medium text-viz-muted">{item.label}</th>
                                ))}
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-hairline">
                            {points.map((point, index) => (
                                <tr key={index}>
                                    <th scope="row" className="px-2 py-1 text-left font-normal text-ink-navy">{formatX(point.x, component.x.kind)}</th>
                                    {point.values.map((value, seriesIndex) => (
                                        <td key={seriesIndex} className="px-2 py-1 text-right text-ink-navy tabular-nums">
                                            {value === null ? "–" : formatMeasure(value, measure)}
                                        </td>
                                    ))}
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </details>
        </figure>
    )
}

export const QUOTE_NOTES = {
    verified: "พบในเอกสาร",
    unverified: "ไม่พบข้อความนี้ในเอกสาร ควรตรวจสอบ",
} as const

function Quote({ item }: { item: RiskItem }) {
    const verified = item.quoteVerified
    return (
        <figure className="space-y-1">
            <blockquote className={`border-l-2 pl-2 text-xs text-charcoal ${verified ? "border-hairline" : "border-viz-bad"}`}>
                “{item.quote}”
            </blockquote>
            <figcaption data-quote={verified ? "found" : "not_found"}
                className={`inline-flex items-center gap-1 text-xs ${verified ? "text-viz-good" : "font-medium text-viz-bad"}`}>
                {verified
                    ? <CircleCheck aria-hidden="true" className="h-3.5 w-3.5" />
                    : <TriangleAlert aria-hidden="true" className="h-3.5 w-3.5" />}
                {verified ? QUOTE_NOTES.verified : QUOTE_NOTES.unverified}
                {item.page ? ` · หน้า ${item.page}` : ""}
            </figcaption>
        </figure>
    )
}

export function RiskList({ component, onOpenDocument }: { component: ComponentOf<"RiskList">; onOpenDocument: OpenDocument }) {
    const items = bySeverity(component.items)
    const counts = riskCounts(items)
    const allFound = items.every(item => item.quoteVerified)
    return (
        <section className="space-y-2">
            <p className="text-xs text-ink-navy">
                <DocumentName document={component.document} onOpen={onOpenDocument} />
            </p>
            <ul aria-label="จำนวนความเสี่ยงตามระดับ" className="flex flex-wrap gap-x-3 gap-y-1">
                {RISK_LEVELS.map(level => (
                    <li key={level} className="inline-flex items-center gap-1 text-xs text-ink-navy">
                        <RiskBadge level={level} />
                        <span className="tabular-nums" data-risk-count={level}>{counts[level]}</span>
                    </li>
                ))}
            </ul>
            <p data-quote-summary="" className={`inline-flex items-start gap-1 text-xs ${allFound ? "text-viz-good" : "text-viz-bad"}`}>
                {allFound
                    ? <CircleCheck aria-hidden="true" className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                    : <TriangleAlert aria-hidden="true" className="mt-0.5 h-3.5 w-3.5 shrink-0" />}
                {quoteSummary(items)}
            </p>
            <ol className="max-h-[32rem] divide-y divide-hairline overflow-y-auto rounded-md border border-hairline">
                {items.map(item => (
                    <li key={item.id} className="space-y-1.5 px-3 py-2.5">
                        <div className="flex flex-wrap items-center gap-2">
                            <RiskBadge level={item.level} />
                            <span className="text-sm font-medium text-ink-navy">{item.title}</span>
                            <span className="rounded-full border border-hairline px-2 py-0.5 text-xs text-viz-muted">{item.category}</span>
                        </div>
                        <p className="text-sm text-charcoal">{item.description}</p>
                        <Quote item={item} />
                        <p className="text-xs text-ink-navy">
                            <span className="font-medium">ข้อเสนอแนะ: </span>{item.recommendation}
                        </p>
                    </li>
                ))}
            </ol>
        </section>
    )
}
