// Find where an extracted value sits on a PDF page, using the page's own text
// layer (pdf.js text items carry exact positions). Works for any PDF with a
// text layer; scanned pages have none, so callers fall back to the page only.

export type Box = { x: number; y: number; width: number; height: number } // percent of the page

export type Highlight = {
    page?: number
    bbox?: Box
    /** Text to look for, most specific first (the verbatim quote before the normalised value). */
    texts?: string[]
    label?: string
}

export type TextItemLike = { str: string; transform: number[]; width: number; height: number }

type ViewportLike = {
    width: number
    height: number
    convertToViewportRectangle: (rect: number[]) => number[]
}

const MIN_SEARCH_LENGTH = 2

/** One spelling for matching: SARA AM decomposed, as OCR words often keep it ("จํากัด"). */
function searchForm(text: string): string {
    return text.replace(/\u0E33/g, "\u0E4D\u0E32").toLowerCase()
}

function compact(text: string): string {
    return searchForm(text.replace(/\s+/g, ""))
}

/** Ways the value may be printed in the document, e.g. 1250 → "1,250.00". */
export function evidenceSearchTexts(value: unknown, evidence?: { quote?: string; raw_text?: string } | null, type?: string): string[] {
    const texts: string[] = []
    const add = (text: unknown) => {
        if (typeof text !== "string") return
        const trimmed = text.trim()
        if (compact(trimmed).length >= MIN_SEARCH_LENGTH && !texts.includes(trimmed)) texts.push(trimmed)
    }
    add(evidence?.quote)
    add(evidence?.raw_text)
    if (value === null || value === undefined || typeof value === "object" || typeof value === "boolean") return texts
    const raw = String(value)
    add(raw)
    const number = typeof value === "number" ? value : (type === "number" || type === "currency") ? Number(raw.replace(/,/g, "")) : NaN
    if (Number.isFinite(number)) {
        add(number.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }))
        add(number.toLocaleString("en-US", { maximumFractionDigits: 2 }))
        add(number.toFixed(2))
    }
    const iso = /^(\d{4})-(\d{2})-(\d{2})$/.exec(raw)
    if (iso) {
        const [, year, month, day] = iso
        const be = String(Number(year) + 543) // Thai documents often print the Buddhist year
        for (const y of [year, be]) {
            add(`${day}/${month}/${y}`)
            add(`${Number(day)}/${Number(month)}/${y}`)
        }
    }
    return texts
}

/**
 * The box (percent of the page) around the first place one of ``texts`` appears.
 * Matching ignores spaces and case, because text items split words unpredictably.
 */
export function findTextBox(items: TextItemLike[], viewport: ViewportLike, texts: string[]): Box | null {
    let joined = ""
    const owner: Array<{ item: number; char: number }> = []
    items.forEach((item, index) => {
        for (let char = 0; char < item.str.length; char += 1) {
            if (/\s/.test(item.str[char])) continue
            for (const part of searchForm(item.str[char])) {
                joined += part
                owner.push({ item: index, char })
            }
        }
    })
    for (const text of texts) {
        const needle = compact(text)
        if (needle.length < MIN_SEARCH_LENGTH) continue
        const start = joined.indexOf(needle)
        if (start < 0) continue
        const first = owner[start]
        const last = owner[start + needle.length - 1]
        let left = Infinity, right = -Infinity, bottom = Infinity, top = -Infinity
        for (let index = first.item; index <= last.item; index += 1) {
            const item = items[index]
            if (!item.str.length) continue
            const [, , c, d, e, f] = item.transform
            const size = Math.hypot(c, d) || item.height || 10
            const from = index === first.item ? first.char : 0
            const to = index === last.item ? last.char + 1 : item.str.length
            left = Math.min(left, e + item.width * (from / item.str.length))
            right = Math.max(right, e + item.width * (to / item.str.length))
            bottom = Math.min(bottom, f - size * 0.25)
            top = Math.max(top, f + size)
        }
        if (!Number.isFinite(left)) continue
        const [x1, y1, x2, y2] = viewport.convertToViewportRectangle([left, bottom, right, top])
        const pad = 0.4
        const x = Math.max(0, (Math.min(x1, x2) / viewport.width) * 100 - pad)
        const y = Math.max(0, (Math.min(y1, y2) / viewport.height) * 100 - pad)
        return {
            x, y,
            width: Math.min(100 - x, (Math.abs(x2 - x1) / viewport.width) * 100 + pad * 2),
            height: Math.min(100 - y, (Math.abs(y2 - y1) / viewport.height) * 100 + pad * 2),
        }
    }
    return null
}

/** A recognised word on a scanned page (Tesseract), in percent of the page. */
export type PageWord = { text: string; x: number; y: number; width: number; height: number }

/** Word positions per page number, from a document's ``ocr_pages[].words``. */
export function pageWordsFrom(ocrPages: unknown): Record<number, PageWord[]> {
    const result: Record<number, PageWord[]> = {}
    if (!Array.isArray(ocrPages)) return result
    for (const page of ocrPages) {
        if (!page || typeof page !== "object") continue
        const { page_number: number, words } = page as { page_number?: unknown; words?: unknown }
        if (typeof number !== "number" || !Array.isArray(words)) continue
        result[number] = words.filter((word): word is PageWord =>
            !!word && typeof word.text === "string" && typeof word.x === "number" && typeof word.y === "number"
            && typeof word.width === "number" && typeof word.height === "number")
    }
    return result
}

/** Same matching as ``findTextBox`` but over OCR words, whose boxes are already in percent. */
export function findWordBox(words: PageWord[], texts: string[]): Box | null {
    let joined = ""
    const owner: number[] = []
    words.forEach((word, index) => {
        for (const char of searchForm(word.text)) {
            if (/\s/.test(char)) continue
            joined += char
            owner.push(index)
        }
    })
    for (const text of texts) {
        const needle = compact(text)
        if (needle.length < MIN_SEARCH_LENGTH) continue
        const start = joined.indexOf(needle)
        if (start < 0) continue
        const span = words.slice(owner[start], owner[start + needle.length - 1] + 1)
        const left = Math.min(...span.map((word) => word.x))
        const top = Math.min(...span.map((word) => word.y))
        const right = Math.max(...span.map((word) => word.x + word.width))
        const bottom = Math.max(...span.map((word) => word.y + word.height))
        const pad = 0.4
        const x = Math.max(0, left - pad)
        const y = Math.max(0, top - pad)
        return { x, y, width: Math.min(100 - x, right - left + pad * 2), height: Math.min(100 - y, bottom - top + pad * 2) }
    }
    return null
}
