import { CircleAlert, CircleCheck, Eye, Info, OctagonAlert, TriangleAlert, type LucideIcon } from "lucide-react"
import {
    RISK_LEVELS,
    chartPoints,
    getPointer,
    isFiniteNumber,
    parseDelta,
    resolveValue,
    riskCounts,
    riskItems,
    tableRows,
    type ChartPoint,
    type ChartSeries,
    type ComponentOf,
    type DataModel,
    type Delta,
    type NumberFormat,
    type RiskItem,
    type RiskLevel,
    type TableColumn,
} from "@/lib/a2ui"

const NUMBER = new Intl.NumberFormat("th-TH", { maximumFractionDigits: 2 })
const CURRENCY = new Intl.NumberFormat("th-TH", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const COMPACT = new Intl.NumberFormat("th-TH", { notation: "compact", maximumFractionDigits: 1 })
const DATE = new Intl.DateTimeFormat("th-TH", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" })

export function formatNumber(value: number, format: NumberFormat, unit?: string): string {
    const digits = (format === "currency" ? CURRENCY : NUMBER).format(value)
    if (format === "percent") return `${digits}%`
    return unit ? `${digits} ${unit}` : digits
}

function formatDate(value: unknown): string | null {
    if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null
    const date = new Date(`${value}T00:00:00Z`)
    return Number.isNaN(date.getTime()) ? null : DATE.format(date)
}

const DIRECTION_VIEW = {
    up: { glyph: "▲", word: "เพิ่มขึ้น" },
    down: { glyph: "▼", word: "ลดลง" },
    flat: { glyph: "▬", word: "คงที่" },
} as const

/** Color carries sentiment only; the glyph carries direction, and both are also in text. */
const SENTIMENT_VIEW = {
    good: { className: "text-viz-good", word: "ดีขึ้น" },
    bad: { className: "text-viz-bad", word: "แย่ลง" },
    neutral: { className: "text-viz-neutral", word: "" },
} as const

export function DeltaText({ delta, format = "number", unit }: { delta: Delta; format?: NumberFormat; unit?: string }) {
    const direction = DIRECTION_VIEW[delta.direction]
    const sentiment = SENTIMENT_VIEW[delta.sentiment]
    const amount = formatNumber(delta.value, format, unit)
    return (
        <span className={`inline-flex flex-wrap items-baseline gap-x-1 text-xs ${sentiment.className}`}>
            <span aria-hidden="true">{direction.glyph}</span>
            <span className="sr-only">{direction.word}</span>
            <span className="font-medium tabular-nums">{delta.value > 0 ? `+${amount}` : amount}</span>
            {sentiment.word && <span>({sentiment.word})</span>}
            {delta.label && <span className="text-viz-muted">{delta.label}</span>}
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

const Dash = () => <span className="text-viz-muted">–</span>

export function Metric({ component, data }: { component: ComponentOf<"Metric">; data: DataModel }) {
    const value = resolveValue(component.value, data)
    return (
        <div className="h-full rounded-md border border-hairline px-3 py-2">
            <p className="text-xs text-viz-muted">{component.label}</p>
            <p className="text-lg font-semibold text-ink-navy">
                {isFiniteNumber(value) ? formatNumber(value, component.format, component.unit) : <Dash />}
            </p>
            {component.delta && <DeltaText delta={component.delta} format={component.format} unit={component.unit} />}
        </div>
    )
}

const ALIGN_CLASS = { left: "text-left", center: "text-center", right: "text-right" } as const

function Cell({ column, value }: { column: TableColumn; value: unknown }) {
    switch (column.type) {
        case "number":
        case "currency":
        case "percent":
            return isFiniteNumber(value) ? <>{formatNumber(value, column.type, column.unit)}</> : <Dash />
        case "date":
            return <>{formatDate(value) ?? <Dash />}</>
        case "delta": {
            const delta = parseDelta(value)
            return delta ? <DeltaText delta={delta} format={column.format} unit={column.unit} /> : <Dash />
        }
        case "risk":
            return RISK_LEVELS.includes(value as RiskLevel) ? <RiskBadge level={value as RiskLevel} /> : <Dash />
        case "text":
            return typeof value === "string" && value ? <>{value}</> : <Dash />
    }
}

export function DataTable({ component, data, onOpenDocument }: {
    component: ComponentOf<"DataTable">
    data: DataModel
    onOpenDocument?: (documentId: string) => void
}) {
    const rows = tableRows(getPointer(data, component.rows.path))
    const showOpen = Boolean(onOpenDocument) && rows.some(row => typeof row.document_id === "string")
    if (rows.length === 0) return <p className="text-xs text-viz-muted">ไม่มีข้อมูล</p>
    return (
        <div className="max-h-80 overflow-auto rounded-md border border-hairline">
            <table className="w-full min-w-max border-collapse text-sm">
                {component.caption && (
                    <caption className="px-3 py-2 text-left text-xs font-medium text-ink-navy">{component.caption}</caption>
                )}
                <thead className="sticky top-0 bg-off-white">
                    <tr>
                        {component.columns.map(column => (
                            <th key={column.key} scope="col"
                                className={`px-3 py-1.5 text-xs font-medium text-viz-muted ${ALIGN_CLASS[column.align]}`}>
                                {column.label}
                            </th>
                        ))}
                        {showOpen && <th scope="col" className="px-3 py-1.5"><span className="sr-only">เอกสาร</span></th>}
                    </tr>
                </thead>
                <tbody className="divide-y divide-hairline">
                    {rows.map((row, index) => (
                        <tr key={index}>
                            {component.columns.map(column => (
                                <td key={column.key}
                                    className={`px-3 py-1.5 text-ink-navy tabular-nums ${ALIGN_CLASS[column.align]}`}>
                                    <Cell column={column} value={row[column.key]} />
                                </td>
                            ))}
                            {showOpen && (
                                <td className="px-3 py-1.5 text-right">
                                    {typeof row.document_id === "string" && onOpenDocument && (
                                        <OpenDocumentButton documentId={row.document_id} onOpen={onOpenDocument} />
                                    )}
                                </td>
                            )}
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

const BAR_HEIGHT = 12
const BAR_GAP = 2

function BarChart({ points, series, format }: { points: ChartPoint[]; series: ChartSeries[]; format: (value: number) => string }) {
    // No value axis here (each bar is labelled), so the longest bar may fill the track.
    const values = points.flatMap(point => point.values.filter(isFiniteNumber))
    const min = Math.min(0, ...values)
    const max = Math.max(0, ...values)
    const percent = (value: number) => (max === min ? 0 : round(((value - min) / (max - min)) * 100))
    const zero = percent(0)
    const height = series.length * BAR_HEIGHT + (series.length - 1) * BAR_GAP
    return (
        <div className="space-y-1.5">
            {points.map((point, pointIndex) => (
                <div key={pointIndex}
                    className="grid grid-cols-[minmax(0,6rem)_minmax(0,1fr)_auto] items-center gap-x-2 sm:grid-cols-[minmax(0,9rem)_minmax(0,1fr)_auto]">
                    <span className="truncate text-xs text-charcoal" title={point.label}>{point.label}</span>
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
                                <title>{`${point.label} · ${series[seriesIndex].label}: ${format(value)}`}</title>
                            </rect>
                        ))}
                    </svg>
                    <div className="flex flex-col text-right text-[11px] leading-[14px] text-ink-navy tabular-nums">
                        {point.values.map((value, seriesIndex) => (
                            <span key={seriesIndex}>{value === null ? "–" : format(value)}</span>
                        ))}
                    </div>
                </div>
            ))}
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

function LineChart({ points, series, format }: { points: ChartPoint[]; series: ChartSeries[]; format: (value: number) => string }) {
    const count = points.length
    const { min, max, ticks } = niceScale(points.flatMap(point => point.values.filter(isFiniteNumber)), false)
    const x = (index: number) => (count === 1 ? 50 : (index / (count - 1)) * 100)
    const y = (value: number) => 100 - ((value - min) / (max - min)) * 100
    const step = Math.max(1, Math.ceil((count - 1) / (MAX_X_LABELS - 1)))
    const labelled = points.map((_, index) => index).filter(index => index % step === 0 || index === count - 1)
    // Every point gets a marker while they stay legible; past that, only each series' last point does.
    const marked = (seriesIndex: number, index: number) => count <= MAX_MARKED_POINTS
        || index === points.map(point => point.values[seriesIndex]).findLastIndex(value => value !== null)
    return (
        <div className="relative mb-6 ml-12 mr-3 mt-2 h-40">
            {ticks.map(tick => (
                <span key={tick} className="absolute -left-12 w-10 -translate-y-1/2 text-right text-[11px] text-viz-muted tabular-nums"
                    style={{ top: `${round(y(tick))}%` }}>
                    {COMPACT.format(tick)}
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
                                        <title>{`${points[index].label} · ${item.label}: ${format(value)}`}</title>
                                    </path>
                                </g>
                            ))}
                        </g>
                    )
                })}
            </svg>
            {labelled.map(index => (
                <span key={index}
                    className="absolute top-full mt-1 whitespace-nowrap text-[11px] text-viz-muted"
                    style={{
                        left: `${round(x(index))}%`,
                        transform: count === 1 ? "translateX(-50%)"
                            : index === 0 ? undefined : index === count - 1 ? "translateX(-100%)" : "translateX(-50%)",
                    }}>
                    {points[index].label}
                </span>
            ))}
        </div>
    )
}

export function Chart({ component, data }: { component: ComponentOf<"Chart">; data: DataModel }) {
    const points = chartPoints(getPointer(data, component.data.path), component.x, component.series)
    const format = (value: number) => formatNumber(value, component.format, component.unit)
    const hasValues = points.some(point => point.values.some(isFiniteNumber))
    const kind = component.type === "bar" ? "กราฟแท่ง" : "กราฟเส้น"
    return (
        <figure className="space-y-2">
            {component.title && <figcaption className="text-sm font-semibold text-ink-navy">{component.title}</figcaption>}
            {component.series.length > 1 && (
                <ul className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-ink-navy">
                    {component.series.map((item, index) => (
                        <li key={item.key} className="inline-flex items-center gap-1.5">
                            <span aria-hidden="true" className={`inline-block bg-current ${SERIES_CLASS[index]} ${
                                component.type === "line" ? "h-0.5 w-3" : "h-2.5 w-2.5 rounded-sm"}`} />
                            {item.label}
                        </li>
                    ))}
                </ul>
            )}
            {hasValues ? (
                <div role="img" aria-label={`${kind}${component.title ? ` ${component.title}` : ""} ${points.length} รายการ ดูค่าในตารางด้านล่าง`}>
                    {component.type === "bar"
                        ? <BarChart points={points} series={component.series} format={format} />
                        : <LineChart points={points} series={component.series} format={format} />}
                </div>
            ) : (
                <p className="text-xs text-viz-muted">ไม่มีข้อมูล</p>
            )}
            {hasValues && (
                <details className="text-xs">
                    <summary className="cursor-pointer text-viz-muted hover:text-ink-navy">ดูข้อมูลเป็นตาราง</summary>
                    <div className="mt-1 max-h-60 overflow-auto">
                        <table className="w-full min-w-max border-collapse">
                            <thead>
                                <tr>
                                    <th scope="col" className="px-2 py-1 text-left font-medium text-viz-muted">รายการ</th>
                                    {component.series.map(item => (
                                        <th key={item.key} scope="col" className="px-2 py-1 text-right font-medium text-viz-muted">{item.label}</th>
                                    ))}
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-hairline">
                                {points.map((point, index) => (
                                    <tr key={index}>
                                        <th scope="row" className="px-2 py-1 text-left font-normal text-ink-navy">{point.label}</th>
                                        {point.values.map((value, seriesIndex) => (
                                            <td key={seriesIndex} className="px-2 py-1 text-right text-ink-navy tabular-nums">
                                                {value === null ? "–" : format(value)}
                                            </td>
                                        ))}
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </details>
            )}
        </figure>
    )
}

export const QUOTE_NOTES = {
    verified: "พบในเอกสาร",
    unverified: "ไม่พบข้อความนี้ในเอกสาร ควรตรวจสอบ",
} as const

function Quote({ item }: { item: RiskItem & { quote: string } }) {
    const verified = item.quote_verified === true
    return (
        <figure className="space-y-1">
            <blockquote className={`border-l-2 pl-2 text-xs text-charcoal ${verified ? "border-hairline" : "border-viz-bad"}`}>
                “{item.quote}”
            </blockquote>
            <figcaption className={`inline-flex items-center gap-1 text-xs ${verified ? "text-viz-good" : "font-medium text-viz-bad"}`}>
                {verified
                    ? <CircleCheck aria-hidden="true" className="h-3.5 w-3.5" />
                    : <TriangleAlert aria-hidden="true" className="h-3.5 w-3.5" />}
                {verified ? QUOTE_NOTES.verified : QUOTE_NOTES.unverified}
                {item.page ? ` · หน้า ${item.page}` : ""}
            </figcaption>
        </figure>
    )
}

export function RiskList({ component, data, onOpenDocument }: {
    component: ComponentOf<"RiskList">
    data: DataModel
    onOpenDocument?: (documentId: string) => void
}) {
    const items = riskItems(getPointer(data, component.items.path))
    const counts = riskCounts(items)
    return (
        <section className="space-y-2">
            {component.title && <h3 className="text-sm font-semibold text-ink-navy">{component.title}</h3>}
            <ul aria-label="จำนวนความเสี่ยงตามระดับ" className="flex flex-wrap gap-x-3 gap-y-1">
                {RISK_LEVELS.map(level => (
                    <li key={level} className="inline-flex items-center gap-1 text-xs text-ink-navy">
                        <RiskBadge level={level} />
                        <span className="tabular-nums" data-risk-count={level}>{counts[level]}</span>
                    </li>
                ))}
            </ul>
            {items.length === 0 ? (
                <p className="text-xs text-viz-muted">ไม่พบความเสี่ยง</p>
            ) : (
                <ol className="max-h-[32rem] divide-y divide-hairline overflow-y-auto rounded-md border border-hairline">
                    {items.map((item, index) => (
                        <li key={index} className="space-y-1.5 px-3 py-2.5">
                            <div className="flex flex-wrap items-center gap-2">
                                <RiskBadge level={item.level} />
                                <span className="text-sm font-medium text-ink-navy">{item.title}</span>
                                {item.category && (
                                    <span className="rounded-full border border-hairline px-2 py-0.5 text-xs text-viz-muted">{item.category}</span>
                                )}
                            </div>
                            <p className="text-sm text-charcoal">{item.description}</p>
                            {item.quote && <Quote item={{ ...item, quote: item.quote }} />}
                            {item.recommendation && (
                                <p className="text-xs text-ink-navy">
                                    <span className="font-medium">ข้อเสนอแนะ: </span>{item.recommendation}
                                </p>
                            )}
                            {item.document_id && onOpenDocument && (
                                <OpenDocumentButton documentId={item.document_id} onOpen={onOpenDocument} />
                            )}
                        </li>
                    ))}
                </ol>
            )}
        </section>
    )
}
