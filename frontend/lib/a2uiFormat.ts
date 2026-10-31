// The only place a panel value becomes text. The backend sends raw values with a
// kind (and computes every comparison); these functions decide how they read in Thai.

import type { Change, Measure, XKind } from "@/lib/a2ui"

const NUMBER = new Intl.NumberFormat("th-TH", { maximumFractionDigits: 2 })
const COUNT = new Intl.NumberFormat("th-TH", { maximumFractionDigits: 0 })
const MONEY = new Intl.NumberFormat("th-TH", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const PERCENT = new Intl.NumberFormat("th-TH", { maximumFractionDigits: 1 })
const COMPACT = new Intl.NumberFormat("th-TH", { notation: "compact", maximumFractionDigits: 1 })
// th-TH uses the Buddhist calendar: 2026-01-31 → "31 ม.ค. 2569", 2026-01 → "ม.ค. 69".
const DATE = new Intl.DateTimeFormat("th-TH", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" })
const MONTH = new Intl.DateTimeFormat("th-TH", { month: "short", year: "2-digit", timeZone: "UTC" })

const CURRENCY_LABEL: Record<string, string> = { THB: "บาท" }

export const currencyLabel = (code: string): string => CURRENCY_LABEL[code] ?? code

/** A number of a measure: "1,250.00 บาท", "12.5%", "1,234". */
export function formatMeasure(value: number, measure: Measure): string {
    switch (measure.kind) {
        case "count": return COUNT.format(value)
        case "number": return NUMBER.format(value)
        case "percent": return `${PERCENT.format(value)}%`
        case "money": return `${MONEY.format(value)} ${currencyLabel(measure.currency)}`
    }
}

const utc = (iso: string) => new Date(`${iso}T00:00:00Z`)

export const formatDate = (iso: string): string => DATE.format(utc(iso))
export const formatMonth = (iso: string): string => MONTH.format(utc(`${iso}-01`))

/** An x value of a chart, or a text, date or month cell. */
export function formatX(value: string, kind: XKind): string {
    return kind === "date" ? formatDate(value) : kind === "month" ? formatMonth(value) : value
}

/** A value-axis tick: compact digits ("1.3M"), with "%" on percent axes; any other unit is the axis title. */
export function formatTick(value: number, measure: Measure): string {
    const digits = COMPACT.format(value)
    return measure.kind === "percent" ? `${digits}%` : digits
}

export function axisUnit(measure: Measure): string | undefined {
    return measure.kind === "money" ? currencyLabel(measure.currency) : undefined
}

const signed = (text: string, value: number) => (value > 0 ? `+${text}` : text)

const DIRECTION_VIEW = {
    up: { glyph: "▲", word: "เพิ่มขึ้น" },
    down: { glyph: "▼", word: "ลดลง" },
    flat: { glyph: "▬", word: "คงที่" },
} as const

const SENTIMENT_WORD = { good: "ดีขึ้น", bad: "แย่ลง", neutral: "" } as const

export interface ChangeView {
    glyph: string
    /** The direction in words, for screen readers. */
    direction: string
    /** The headline change: relative ("+12.5%"), or points ("-1.5 จุด") for a percent, or the amount. */
    amount: string
    /** The amount in the measure's unit when the headline is a relative change ("+409.50 บาท"). */
    detail?: string
    sentiment: string
}

export function describeChange(change: Change, measure: Measure): ChangeView {
    const absolute = measure.kind === "percent"
        ? `${signed(PERCENT.format(change.delta), change.delta)} จุด`
        : signed(formatMeasure(change.delta, measure), change.delta)
    const relative = change.percent === null ? null : `${signed(PERCENT.format(change.percent), change.percent)}%`
    return {
        glyph: DIRECTION_VIEW[change.direction].glyph,
        direction: DIRECTION_VIEW[change.direction].word,
        amount: relative ?? absolute,
        ...(relative && change.direction !== "flat" ? { detail: absolute } : {}),
        sentiment: SENTIMENT_WORD[change.sentiment],
    }
}
