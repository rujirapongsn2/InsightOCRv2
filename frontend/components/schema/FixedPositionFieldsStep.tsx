"use client"

import { useEffect, useMemo, useRef, useState, type ChangeEvent, type PointerEvent, type KeyboardEvent } from "react"
import { Document, Page, pdfjs } from "react-pdf"
import { AlertCircle, ChevronDown, ChevronLeft, ChevronRight, FileText, Loader2, LocateFixed, Plus, ScanLine, Sparkles, SquareDashed, Trash2, X, ZoomIn, ZoomOut } from "lucide-react"
import { Button } from "@/components/ui/button"
import { useSchemaWizard } from "@/contexts/SchemaWizardContext"
import type { ArrayColumn, ArrayConfig, BboxLocator, FixedFieldCreationMode, SchemaField } from "@/types/schema"
import { getApiBaseUrl } from "@/lib/api"
import { isValidFieldName } from "@/lib/schema-validation"
import { evidenceSearchTexts, findTextBox, findWordBox, type Box, type PageWord, type TextItemLike } from "@/lib/evidence-search"
import "react-pdf/dist/Page/AnnotationLayer.css"
import "react-pdf/dist/Page/TextLayer.css"

pdfjs.GlobalWorkerOptions.workerSrc = `//unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`

const genId = () => `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
const BASE_PAGE_WIDTH = 760

type Selection = { x: number; y: number; width: number; height: number } | null
const fieldTypes: ReadonlyArray<{ value: SchemaField["type"]; label: string }> = [
  { value: "text", label: "Text" }, { value: "number", label: "Number" },
  { value: "date", label: "Date" }, { value: "currency", label: "Currency" },
  { value: "boolean", label: "Yes/No" }, { value: "array", label: "Table array" },
]
type PdfProxy = {
  numPages: number
  getPage: (page: number) => Promise<{
    getViewport: (options: { scale: number }) => { width: number; height: number; convertToViewportRectangle: (rect: number[]) => number[] }
    getTextContent: () => Promise<{ items: Array<Partial<TextItemLike>> }>
  }>
}

/** Room for longer values than the sample's: widen to the right, keep the line height. */
function widenForValues(box: Box): Selection {
  const width = Math.min(100 - box.x, Math.max(box.width * 1.5, box.width + 4))
  return { x: Number(box.x.toFixed(2)), y: Number(box.y.toFixed(2)), width: Number(width.toFixed(2)), height: Number(box.height.toFixed(2)) }
}
type PreviewValue = string | number | boolean | null | Array<Record<string, unknown>>

const defaultArrayConfig = (): ArrayConfig => ({
  item_type: "object",
  row_detection: "anchor_column",
  anchor_column: "line_no",
  header_rows: 1,
  columns: [
    { name: "line_no", type: "number", x: 0, width: 8 },
    { name: "description", type: "text", x: 8, width: 55 },
    { name: "quantity", type: "number", x: 63, width: 8 },
    { name: "unit_price", type: "currency", x: 71, width: 18 },
    { name: "amount", type: "currency", x: 89, width: 11 },
  ],
})

function clamp(value: number, min = 0, max = 100) {
  return Math.min(max, Math.max(min, value))
}

function validLocator(locator?: BboxLocator) {
  return Boolean(
    locator && locator.page >= 1 && locator.x >= 0 && locator.y >= 0 &&
    Number.isInteger(locator.page) &&
    locator.width > 0 && locator.height > 0 &&
    locator.x + locator.width <= 100 && locator.y + locator.height <= 100,
  )
}

function validArrayConfig(config?: ArrayConfig) {
  if (!config || !config.columns.length) return false
  const names = config.columns.map((column) => column.name.trim())
  if (names.some((name) => !isValidFieldName(name)) || new Set(names).size !== names.length) return false
  if (config.header_rows < 0 || !Number.isInteger(config.header_rows)) return false
  if (config.row_detection === "anchor_column" && !names.includes(config.anchor_column || "")) return false
  const columns = [...config.columns].sort((left, right) => left.x - right.x)
  return columns.every((column) => column.x >= 0 && column.width > 0 && column.x + column.width <= 100) &&
    columns.every((column, index) => index === 0 || columns[index - 1].x + columns[index - 1].width <= column.x)
}

export function FixedPositionFieldsStep() {
  const { schemaId, fields, addField, updateField, removeField, nextStep,
    fixedFieldCreationMode: creationMode, setFixedFieldCreationMode: setCreationMode,
    referencePdf, referencePdfInfo, selectReferencePdf, setReferenceConsent, loadReferencePdf, removeReferencePdf,
    isRemovingReference: removingReference } = useSchemaWizard()
  const file = referencePdf.kind === "stored" || referencePdf.kind === "selected" ? referencePdf.file : null
  const [pageNumber, setPageNumber] = useState(1)
  const [numPages, setNumPages] = useState(0)
  const [selection, setSelection] = useState<Selection>(null)
  const [dragStart, setDragStart] = useState<{ x: number; y: number } | null>(null)
  const [previewValues, setPreviewValues] = useState<Record<string, PreviewValue>>({})
  const [rawPreviewValues, setRawPreviewValues] = useState<Record<string, PreviewValue>>({})
  const [reading, setReading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [zoom, setZoom] = useState(1)
  const [draggingColumnBoundary, setDraggingColumnBoundary] = useState<{ fieldId: string; boundaryIndex: number } | null>(null)
  const surfaceRef = useRef<HTMLDivElement>(null)
  const pageContainerRef = useRef<HTMLDivElement>(null)
  const [fitWidth, setFitWidth] = useState(BASE_PAGE_WIDTH)
  const [renderedPage, setRenderedPage] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [selectedFieldId, setSelectedFieldId] = useState<string | null>(fields.find((field) => field.locator)?.id || null)
  const methodsRef = useRef<HTMLDetailsElement>(null)
  const draftEditorRef = useRef<HTMLElement>(null)
  const draftNameRef = useRef<HTMLInputElement>(null)
  const searchInputRef = useRef<HTMLInputElement>(null)
  const sidebarRef = useRef<HTMLElement>(null)
  const boxRefs = useRef(new Map<string, HTMLDivElement>())
  const rowRefs = useRef(new Map<string, HTMLDivElement>())
  const draftBoxRef = useRef<HTMLDivElement>(null)
  const boxDrag = useRef<{ id: string; mode: "move" | "resize"; point: { x: number; y: number }; locator: BboxLocator } | null>(null)
  const draftDrag = useRef<{ mode: "move" | "resize"; point: { x: number; y: number }; box: NonNullable<Selection> } | null>(null)
  const pdfRef = useRef<PdfProxy | null>(null)
  // Find a value in the sample and propose its box.
  const [findValue, setFindValue] = useState("")
  const [finding, setFinding] = useState(false)
  const [findMessage, setFindMessage] = useState<string | null>(null)
  const [pendingField, setPendingField] = useState<{ name: string; type: SchemaField["type"] } | null>(null)
  const ocrWords = useRef<Record<number, PageWord[]> | null>(null)

  const cancelCreation = () => {
    setCreationMode("idle")
    setSelection(null)
    setDragStart(null)
    setPendingField(null)
    setFindMessage(null)
  }
  const beginCreation = (mode: Exclude<FixedFieldCreationMode, "idle">) => {
    if (methodsRef.current) methodsRef.current.open = false
    let number = fields.length + 1
    while (fields.some((field) => field.name === `field_${number}`)) number += 1
    setPendingField({ name: `field_${number}`, type: "text" })
    setCreationMode(mode)
    setSelectedFieldId(null)
    setSelection(mode === "coordinates" ? { x: 0, y: 0, width: 10, height: 5 } : null)
    setFindMessage(null)
    setFindValue("")
    if (sidebarRef.current) sidebarRef.current.scrollTop = 0
  }
  const selectField = (field: SchemaField) => {
    cancelCreation()
    setSelectedFieldId(field.id || null)
    if (field.locator) setPageNumber(field.locator.page)
  }

  useEffect(() => {
    const dismissOutside = (event: Event) => {
      const menu = methodsRef.current
      if (menu?.open && event.target instanceof Node && !menu.contains(event.target)) menu.open = false
    }
    // Safari may blur the summary before delivering a menu item's click.
    document.addEventListener("pointerdown", dismissOutside, true)
    document.addEventListener("focusin", dismissOutside)
    return () => {
      document.removeEventListener("pointerdown", dismissOutside, true)
      document.removeEventListener("focusin", dismissOutside)
    }
  }, [])

  useEffect(() => {
    if (creationMode !== "search" && creationMode !== "coordinates") return
    const frame = requestAnimationFrame(() => {
      const input = creationMode === "search" ? searchInputRef.current : draftNameRef.current
      input?.focus({ preventScroll: true })
      draftEditorRef.current?.scrollIntoView({ block: "nearest" })
    })
    return () => cancelAnimationFrame(frame)
  }, [creationMode])

  useEffect(() => {
    const reveal = (container: HTMLElement | null, target?: HTMLElement) => {
      if (!container || !target) return
      const parent = container.getBoundingClientRect()
      const child = target.getBoundingClientRect()
      if (child.top < parent.top || child.bottom > parent.bottom) container.scrollTop += child.top - parent.top
      if (child.left < parent.left || child.right > parent.right) container.scrollLeft += child.left - parent.left
    }
    if (selectedFieldId) {
      if (!boxDrag.current) reveal(pageContainerRef.current, boxRefs.current.get(selectedFieldId))
      reveal(sidebarRef.current, rowRefs.current.get(selectedFieldId))
    } else if (selection && !dragStart && !draftDrag.current && validLocator({ type: "bbox", page: pageNumber, ...selection })) {
      reveal(pageContainerRef.current, draftBoxRef.current || undefined)
    }
  }, [selectedFieldId, renderedPage, selection, dragStart, pageNumber])

  const fileUrl = useMemo(() => file ? URL.createObjectURL(file) : null, [file])
  const pageWidth = Math.round(fitWidth * zoom)
  const renderKey = `${fileUrl}:${pageNumber}:${pageWidth}`
  useEffect(() => () => { if (fileUrl) URL.revokeObjectURL(fileUrl) }, [fileUrl])
  useEffect(() => {
    const container = pageContainerRef.current
    if (!container) return
    const observer = new ResizeObserver(([entry]) => {
      if (entry.contentRect.width > 0) setFitWidth(Math.min(BASE_PAGE_WIDTH, entry.contentRect.width))
    })
    observer.observe(container)
    return () => observer.disconnect()
  }, [])

  const handleFileSelect = (event: ChangeEvent<HTMLInputElement>) => {
    const selected = event.target.files?.[0]
    if (!selected) return
    if (selected.type !== "application/pdf") {
      setError("Choose a PDF form for fixed-position fields")
      return
    }
    selectReferencePdf(selected)
    cancelCreation()
    ocrWords.current = null
    setPendingField(null)
    setFindMessage(null)
    pdfRef.current = null
    setPreviewValues({})
    setRawPreviewValues({})
    setSelection(null)
    setPageNumber(1)
    setNumPages(0)
    setZoom(1)
    setError(null)
  }

  const removeSavedPdf = async () => {
    if (!confirm("Remove the saved PDF? Fields and boxes will be kept.")) return
    try {
      await removeReferencePdf()
      cancelCreation()
      if (referencePdf.kind !== "selected") {
        pdfRef.current = null
        ocrWords.current = null
      }
      setPreviewValues({})
      setRawPreviewValues({})
      setSelection(null)
    } catch (error) {
      setError(error instanceof Error ? error.message : "Unable to remove the saved PDF")
    }
  }

  const toPercent = (event: PointerEvent<Element>) => {
    const bounds = surfaceRef.current?.getBoundingClientRect()
    if (!bounds) return null
    return {
      x: clamp(((event.clientX - bounds.left) / bounds.width) * 100),
      y: clamp(((event.clientY - bounds.top) / bounds.height) * 100),
    }
  }

  const handlePointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (creationMode !== "draw" || !file || renderedPage !== renderKey || event.button !== 0) return
    const point = toPercent(event)
    if (!point) return
    event.currentTarget.setPointerCapture(event.pointerId)
    setDragStart(point)
    setSelection({ ...point, width: 0, height: 0 })
  }

  const handlePointerMove = (event: PointerEvent<HTMLDivElement>) => {
    if (!dragStart) return
    const point = toPercent(event)
    if (!point) return
    setSelection({
      x: Math.min(dragStart.x, point.x),
      y: Math.min(dragStart.y, point.y),
      width: Math.abs(point.x - dragStart.x),
      height: Math.abs(point.y - dragStart.y),
    })
  }

  const handlePointerUp = (event: PointerEvent<HTMLDivElement>) => {
    if (!dragStart) return
    event.currentTarget.releasePointerCapture(event.pointerId)
    setDragStart(null)
    setSelection((current) => current && current.width >= 0.5 && current.height >= 0.5 ? current : null)
    if (window.matchMedia("(max-width: 1023px)").matches) sidebarRef.current?.scrollIntoView({ block: "nearest" })
  }

  const startDraftDrag = (event: PointerEvent<HTMLButtonElement>, mode: "move" | "resize") => {
    if (!selection || event.button !== 0) return
    event.stopPropagation()
    const point = toPercent(event)
    if (!point) return
    event.currentTarget.setPointerCapture(event.pointerId)
    draftDrag.current = { mode, point, box: selection }
  }
  const moveDraft = (event: PointerEvent<HTMLButtonElement>) => {
    const drag = draftDrag.current
    if (!drag) return
    event.stopPropagation()
    const point = toPercent(event)
    if (!point) return
    const dx = point.x - drag.point.x
    const dy = point.y - drag.point.y
    setSelection(drag.mode === "move"
      ? { ...drag.box, x: clamp(drag.box.x + dx, 0, 100 - drag.box.width), y: clamp(drag.box.y + dy, 0, 100 - drag.box.height) }
      : { ...drag.box, width: clamp(drag.box.width + dx, 0.5, 100 - drag.box.x), height: clamp(drag.box.height + dy, 0.5, 100 - drag.box.y) })
  }
  const endDraftDrag = (event: PointerEvent<HTMLButtonElement>) => {
    event.stopPropagation()
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
    draftDrag.current = null
  }

  const startBoxDrag = (event: PointerEvent<HTMLButtonElement>, field: SchemaField, mode: "move" | "resize") => {
    if (creationMode !== "idle" || event.button !== 0 || !field.id || !field.locator) return
    event.stopPropagation()
    const point = toPercent(event)
    if (!point) return
    event.currentTarget.setPointerCapture(event.pointerId)
    setSelectedFieldId(field.id)
    setSelection(null)
    boxDrag.current = { id: field.id, mode, point, locator: { ...field.locator } }
  }

  const moveBox = (event: PointerEvent<HTMLButtonElement>) => {
    const drag = boxDrag.current
    if (!drag) return
    event.stopPropagation()
    const point = toPercent(event)
    if (!point) return
    const dx = point.x - drag.point.x
    const dy = point.y - drag.point.y
    const locator = drag.mode === "move"
      ? { ...drag.locator, x: clamp(drag.locator.x + dx, 0, 100 - drag.locator.width), y: clamp(drag.locator.y + dy, 0, 100 - drag.locator.height) }
      : { ...drag.locator, width: clamp(drag.locator.width + dx, 0.5, 100 - drag.locator.x), height: clamp(drag.locator.height + dy, 0.5, 100 - drag.locator.y) }
    updateField(drag.id, { locator })
    setPreviewValues({})
    setRawPreviewValues({})
  }

  const endBoxDrag = (event: PointerEvent<HTMLButtonElement>) => {
    event.stopPropagation()
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
    boxDrag.current = null
  }

  const nudgeBox = (event: KeyboardEvent<HTMLButtonElement>, field: SchemaField, resize = false) => {
    if (!field.locator || !field.id || !["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) return
    event.preventDefault()
    const step = event.shiftKey ? 1 : 0.1
    const dx = event.key === "ArrowLeft" ? -step : event.key === "ArrowRight" ? step : 0
    const dy = event.key === "ArrowUp" ? -step : event.key === "ArrowDown" ? step : 0
    const box = field.locator
    updateField(field.id, { locator: resize
      ? { ...box, width: clamp(box.width + dx, 0.5, 100 - box.x), height: clamp(box.height + dy, 0.5, 100 - box.y) }
      : { ...box, x: clamp(box.x + dx, 0, 100 - box.width), y: clamp(box.y + dy, 0, 100 - box.height) } })
    setSelectedFieldId(field.id)
  }

  const addSelection = () => {
    if (!selection || !pendingField || !validLocator({ type: "bbox", page: pageNumber, ...selection }) ||
        !isValidFieldName(pendingField.name.trim()) || fields.some((field) => field.name === pendingField.name.trim()) ||
        (numPages > 0 && pageNumber > numPages)) return
    const locator: BboxLocator = {
      type: "bbox",
      page: pageNumber,
      x: Number(selection.x.toFixed(2)),
      y: Number(selection.y.toFixed(2)),
      width: Number(selection.width.toFixed(2)),
      height: Number(selection.height.toFixed(2)),
    }
    const type = pendingField?.type || "text"
    const id = genId()
    addField({
      id,
      name: pendingField.name.trim(),
      type,
      description: "",
      required: false,
      locator: { ...locator, clean_placeholders: true },
      array_config: type === "array" ? defaultArrayConfig() : undefined,
    })
    cancelCreation()
    setSelectedFieldId(id)
  }

  const readOcrWords = async (): Promise<Record<number, PageWord[]>> => {
    if (ocrWords.current) return ocrWords.current
    const token = localStorage.getItem("token")
    const formData = new FormData()
    formData.append("file", file!)
    const response = await fetch(`${getApiBaseUrl()}/schemas/sample-words`, {
      method: "POST", headers: token ? { Authorization: `Bearer ${token}` } : {}, body: formData,
    })
    const data = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Could not read the scanned sample")
    ocrWords.current = Object.fromEntries(Object.entries(data.pages || {}).map(([page, words]) => [Number(page), words as PageWord[]]))
    return ocrWords.current
  }

  // Look for the typed value in the PDF text first, then in words read by OCR (scanned forms).
  const findInForm = async () => {
    const pdf = pdfRef.current
    const texts = evidenceSearchTexts(findValue, null, pendingField?.type || "text")
    if (!file || !pdf || !texts.length) return
    setFinding(true)
    setSelection(null)
    setFindMessage(null)
    try {
      let found: { page: number; box: Box } | null = null
      for (let page = 1; page <= pdf.numPages && !found; page += 1) {
        const proxy = await pdf.getPage(page)
        const content = await proxy.getTextContent()
        const items = content.items.filter((item): item is TextItemLike =>
          typeof item.str === "string" && Array.isArray(item.transform) && typeof item.width === "number")
        const box = findTextBox(items, proxy.getViewport({ scale: 1 }), texts)
        if (box) found = { page, box }
      }
      if (!found) {
        const words = await readOcrWords()
        for (const [page, pageWords] of Object.entries(words)) {
          const box = findWordBox(pageWords, texts)
          if (box) { found = { page: Number(page), box }; break }
        }
      }
      if (!found) {
        setFindMessage(`"${findValue}" was not found in this form. Check the spelling, or draw the box yourself.`)
        return
      }
      setPageNumber(found.page)
      setSelection(widenForValues(found.box))
      setFindMessage(`Found on page ${found.page}`)
    } catch (err) {
      setFindMessage(err instanceof Error ? err.message : "Could not search the form")
    } finally {
      setFinding(false)
    }
  }

  const updateLocator = (id: string, key: keyof BboxLocator, value: string) => {
    const field = fields.find((item) => item.id === id)
    if (!field?.locator || key === "type") return
    updateField(id, { locator: { ...field.locator, [key]: Number(value) } })
  }

  const updateFieldType = (id: string, type: SchemaField["type"]) => {
    const field = fields.find((item) => item.id === id)
    if (!field) return
    updateField(id, {
      type,
      array_config: type === "array" ? field.array_config || defaultArrayConfig() : undefined,
    })
  }

  const updateArrayConfig = (id: string, updates: Partial<ArrayConfig>) => {
    const field = fields.find((item) => item.id === id)
    if (!field || field.type !== "array") return
    updateField(id, { array_config: { ...(field.array_config || defaultArrayConfig()), ...updates } })
  }

  const updateArrayColumn = (id: string, index: number, updates: Partial<ArrayColumn>) => {
    const field = fields.find((item) => item.id === id)
    const config = field?.array_config
    if (!field || !config) return
    updateArrayConfig(id, {
      columns: config.columns.map((column, columnIndex) => columnIndex === index ? { ...column, ...updates } : column),
    })
  }

  const addArrayColumn = (id: string) => {
    const field = fields.find((item) => item.id === id)
    const config = field?.array_config
    if (!field || !config || config.columns.length >= 12) return
    const widestIndex = config.columns.reduce((widest, column, index, columns) => {
      const widestColumn = columns[widest]
      if (column.type === "text" && widestColumn.type !== "text") return index
      return column.width > widestColumn.width ? index : widest
    }, 0)
    const widest = config.columns[widestIndex]
    const firstWidth = Number((widest.width / 2).toFixed(2))
    const secondWidth = Number((widest.width - firstWidth).toFixed(2))
    const nextName = `column_${config.columns.length + 1}`
    updateArrayConfig(id, {
      columns: config.columns.flatMap((column, index) => index === widestIndex
        ? [
            { ...column, width: firstWidth },
            { name: nextName, type: "text", x: Number((column.x + firstWidth).toFixed(2)), width: secondWidth },
          ]
        : [column]),
    })
  }

  const resizeArrayColumnBoundary = (id: string, boundaryIndex: number, relativeX: number) => {
    const field = fields.find((item) => item.id === id)
    const config = field?.array_config
    if (!field || !config) return
    const left = config.columns[boundaryIndex]
    const right = config.columns[boundaryIndex + 1]
    if (!left || !right) return

    const minimumWidth = 3
    const rightEdge = right.x + right.width
    const boundary = Math.min(rightEdge - minimumWidth, Math.max(left.x + minimumWidth, relativeX))
    updateArrayConfig(id, {
      columns: config.columns.map((column, index) => {
        if (index === boundaryIndex) return { ...column, width: Number((boundary - left.x).toFixed(2)) }
        if (index === boundaryIndex + 1) return { ...column, x: Number(boundary.toFixed(2)), width: Number((rightEdge - boundary).toFixed(2)) }
        return column
      }),
    })
  }

  const removeArrayColumn = (id: string, index: number) => {
    const field = fields.find((item) => item.id === id)
    const config = field?.array_config
    if (!field || !config || config.columns.length === 1) return
    const columns = config.columns.filter((_, columnIndex) => columnIndex !== index)
    updateArrayConfig(id, {
      columns,
      anchor_column: columns.some((column) => column.name === config.anchor_column)
        ? config.anchor_column
        : columns[0]?.name,
    })
  }

  const previewFields = async () => {
    if (!file || !fields.length) return
    setReading(true)
    setError(null)
    try {
      const token = localStorage.getItem("token")
      const formData = new FormData()
      formData.append("file", file)
      formData.append("fields_json", JSON.stringify(fields.filter((field) => field.locator).map((field) => {
        const payload = { ...field }
        delete payload.id
        delete payload.order
        return payload
      })))
      const response = await fetch(`${getApiBaseUrl()}/schemas/preview-fixed-fields`, {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: formData,
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(data.detail || "Unable to read fixed-position fields")
      setPreviewValues(data.values || {})
      setRawPreviewValues(data.raw_values || {})
      if (data.errors && Object.keys(data.errors).length) {
        setError(`Fields requiring review: ${Object.keys(data.errors).join(", ")}`)
      }
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to read fixed-position fields")
    } finally {
      setReading(false)
    }
  }

  const duplicateNames = new Set(
    fields
      .map((field) => field.name.trim())
      .filter((name, index, names) => name && names.indexOf(name) !== index),
  )
  const invalidNames = fields
    .filter((field) => !field.name.trim() || !isValidFieldName(field.name))
    .map((field) => field.name.trim() || "(unnamed)")
  const duplicateNameList = Array.from(duplicateNames)
  const fieldValidationMessage = invalidNames.length > 0
    ? `Use English letters, numbers, and underscores only; names must start with a letter or underscore. Invalid: ${invalidNames.join(", ")}`
    : duplicateNameList.length > 0
      ? `Each field name must be unique. Duplicate: ${duplicateNameList.join(", ")}`
      : null
  const arrayValidationMessage = fields
    .filter((field) => field.type === "array" && field.locator && !validArrayConfig(field.array_config))
    .map((field) => field.name || "(unnamed)")
  const fixedFields = fields.filter((field) => field.locator)
  const canProceed = fields.length > 0 && !fieldValidationMessage && arrayValidationMessage.length === 0 && fields.every((field) => (!field.locator && schemaId) || validLocator(field.locator))

  return (
    <div className="space-y-5" onKeyDown={(event) => { if (event.key === "Escape" && creationMode !== "idle") { event.preventDefault(); event.stopPropagation(); if (!finding) cancelCreation() } }}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold text-slate-900">Fixed-position fields</h2>
        </div>
        <div className="flex flex-wrap gap-2">
          <div className="relative flex">
            <Button type="button" size="sm" className="rounded-r-none" onClick={() => beginCreation("draw")} disabled={!file || !numPages || reading || finding || creationMode !== "idle"}>
              <Plus className="mr-1.5 h-4 w-4" />Add field
            </Button>
            <details ref={methodsRef}
              onKeyDown={(event) => { if (event.key === "Escape" && event.currentTarget.open) { event.stopPropagation(); event.currentTarget.open = false; event.currentTarget.querySelector("summary")?.focus() } }}>
              <summary aria-label="More field methods" title="More field methods" className="flex h-8 w-8 cursor-pointer list-none items-center justify-center rounded-r-md border-l border-white/30 bg-[#2786C2] text-white hover:bg-[#1A5A8A] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#2786C2] [&::-webkit-details-marker]:hidden"><ChevronDown className="h-4 w-4" /></summary>
              <div className="absolute left-0 top-full z-30 mt-1 w-60 rounded-md border border-slate-200 bg-white p-1 shadow-lg sm:left-auto sm:right-0">
                <button type="button" className="flex w-full items-center gap-2 rounded px-3 py-2 text-left text-sm hover:bg-slate-100 disabled:opacity-40" disabled={!file || !numPages || reading || finding} onClick={() => beginCreation("draw")}><SquareDashed className="h-4 w-4" />Draw on document</button>
                <button type="button" className="flex w-full items-center gap-2 rounded px-3 py-2 text-left text-sm hover:bg-slate-100 disabled:opacity-40" disabled={!file || !numPages || reading || finding} onClick={() => beginCreation("search")}><LocateFixed className="h-4 w-4" />Find text to place box</button>
                <button type="button" className="flex w-full items-center gap-2 rounded px-3 py-2 text-left text-sm hover:bg-slate-100 disabled:opacity-40" disabled={reading || finding} onClick={() => beginCreation("coordinates")}><ScanLine className="h-4 w-4" />Enter coordinates</button>
              </div>
            </details>
          </div>
          <Button variant="outline" size="sm" onClick={previewFields} disabled={!file || !fixedFields.length || !canProceed || reading || creationMode !== "idle"}>
            {reading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Sparkles className="mr-2 h-4 w-4" />}
            Test extraction
          </Button>
        </div>
      </div>

      <input ref={fileInputRef} id="fixed-schema-sample" aria-label="Sample PDF" type="file" accept="application/pdf" className="hidden" onChange={handleFileSelect} disabled={reading || finding || removingReference} />
      {referencePdf.kind === "loading" && <p role="status" className="flex items-center gap-2 text-sm text-slate-600"><Loader2 className="h-4 w-4 animate-spin" />Loading saved PDF…</p>}
      {referencePdf.kind === "error" && <div role="alert" className="flex flex-wrap items-center gap-2 text-sm text-red-700"><span>{referencePdf.message}</span><Button variant="outline" size="sm" onClick={loadReferencePdf}>Retry PDF</Button></div>}
      {referencePdfInfo && referencePdf.kind !== "stored" && <div className="flex items-center justify-between gap-2 rounded-md border border-slate-200 p-2 text-sm text-slate-700">
        <span className="min-w-0 break-words">Saved attachment: {referencePdfInfo.filename}</span>
        <button type="button" aria-label="Remove saved PDF" title="Remove saved PDF" disabled={removingReference || reading || finding} onClick={removeSavedPdf} className="shrink-0 text-slate-500 hover:text-red-600">{removingReference ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}</button>
      </div>}
      {!file && (
        <button type="button" onClick={() => fileInputRef.current?.click()} className="flex min-h-32 w-full cursor-pointer flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-blue-300 bg-blue-50/50 p-6 text-center hover:border-blue-500">
          <FileText className="h-9 w-9 text-blue-500" />
          <span className="font-medium text-blue-700">Choose PDF form</span>
        </button>
      )}
        <>
          {file && <div className="flex items-center justify-between rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm">
            <span className="flex min-w-0 items-center gap-2 truncate text-slate-700"><FileText className="h-4 w-4 shrink-0" />{file.name}</span>
            <div className="flex shrink-0 items-center gap-3">
              {referencePdf.kind === "stored" && <span className="text-xs text-emerald-700">Saved PDF</span>}
              <button disabled={reading || finding || removingReference} className="text-slate-500 hover:text-red-600" onClick={() => fileInputRef.current?.click()}>Change</button>
              {referencePdf.kind === "stored" && <button type="button" aria-label="Remove saved PDF" title="Remove saved PDF" disabled={reading || finding || removingReference} onClick={removeSavedPdf} className="text-slate-500 hover:text-red-600">{removingReference ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}</button>}
            </div>
          </div>}
          {referencePdf.kind === "selected" && <label className="flex items-start gap-2 text-sm text-slate-700">
            <input type="checkbox" className="mt-1" checked={referencePdf.consent === true} onChange={(event) => setReferenceConsent(event.target.checked)} />
            <span>Keep this PDF with the schema<span className="block text-xs text-slate-500">May contain personal data. Stored until removed and accessible only to schema managers. Unchecked files are preview only.</span></span>
          </label>}

          <div className={`grid gap-5 ${file ? "lg:grid-cols-[minmax(0,1fr)_24rem]" : ""} lg:items-start`}>
            <section className={`${file ? "" : "hidden"} min-w-0 rounded-lg border border-slate-200 bg-slate-50`}>
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-3 py-2 text-sm text-slate-600">
                <span className="font-medium">Page {pageNumber}{numPages ? ` of ${numPages}` : ""}</span>
                <div className="flex flex-wrap items-center justify-end gap-1">
                  <Button type="button" variant="outline" size="icon" className="h-8 w-8" aria-label="Previous page" title="Previous page" onClick={() => setPageNumber((page) => Math.max(1, page - 1))} disabled={pageNumber <= 1 || creationMode !== "idle"}><ChevronLeft className="h-4 w-4" /></Button>
                  <Button type="button" variant="outline" size="icon" className="h-8 w-8" aria-label="Next page" title="Next page" onClick={() => setPageNumber((page) => Math.min(numPages, page + 1))} disabled={!numPages || pageNumber >= numPages || creationMode !== "idle"}><ChevronRight className="h-4 w-4" /></Button>
                  <span className="mx-1 h-5 w-px bg-slate-300" />
                  <Button type="button" variant="outline" size="icon" className="h-8 w-8" aria-label="Zoom out" title="Zoom out" onClick={() => setZoom((value) => Math.max(0.75, Number((value - 0.25).toFixed(2))))} disabled={zoom <= 0.75}><ZoomOut className="h-4 w-4" /></Button>
                  <span className="min-w-12 text-center text-xs font-medium text-slate-500">{Math.round(zoom * 100)}%</span>
                  <Button type="button" variant="outline" size="icon" className="h-8 w-8" aria-label="Zoom in" title="Zoom in" onClick={() => setZoom((value) => Math.min(1.75, Number((value + 0.25).toFixed(2))))} disabled={zoom >= 1.75}><ZoomIn className="h-4 w-4" /></Button>
                  <Button type="button" variant="ghost" size="sm" className="ml-1 h-8 px-2 text-xs" onClick={() => setZoom(1)}>Fit</Button>
                </div>
              </div>
              {creationMode !== "idle" && <div role="status" className="flex items-center justify-between gap-2 border-b border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-800">
                <span>{creationMode === "draw" ? selection ? "Box selected" : "Draw a box" : creationMode === "search" ? "Find text to place box" : "Enter coordinates"}</span>
                <button type="button" aria-label="Cancel new field" title="Cancel new field" disabled={finding} onClick={cancelCreation}><X className="h-4 w-4" /></button>
              </div>}
              <div ref={pageContainerRef} className="max-h-[68vh] min-h-[32rem] overflow-auto p-5">
                <div className="flex min-w-full justify-center">
                <div
                  ref={surfaceRef}
                  className={`relative inline-block select-none shadow-sm ${creationMode === "draw" ? "touch-none cursor-crosshair" : ""}`}
                  onPointerDown={handlePointerDown}
                  onPointerMove={handlePointerMove}
                  onPointerUp={handlePointerUp}
                  onPointerCancel={() => { setDragStart(null); setSelection(null) }}
                >
                  {fileUrl && <Document file={fileUrl} loading={<div style={{ width: pageWidth }} className="grid h-72 place-items-center"><Loader2 className="h-5 w-5 animate-spin" /></div>} onLoadSuccess={(pdf) => { pdfRef.current = pdf as unknown as PdfProxy; setNumPages(pdf.numPages) }}>
                    <Page pageNumber={pageNumber} width={pageWidth} renderTextLayer={false} renderAnnotationLayer={false} onRenderSuccess={() => setRenderedPage(renderKey)} />
                  </Document>}
                  {renderedPage === renderKey && fields.filter((field) => field.locator?.page === pageNumber).map((field) => field.locator && (
                    <div key={field.id} ref={(node) => { if (field.id) { if (node) boxRefs.current.set(field.id, node); else boxRefs.current.delete(field.id) } }} className={`absolute border-2 ${creationMode !== "idle" ? "pointer-events-none" : ""} ${selectedFieldId === field.id ? "z-10 border-emerald-600 bg-emerald-500/15" : "border-blue-600 bg-blue-500/15"}`} style={{ left: `${field.locator.x}%`, top: `${field.locator.y}%`, width: `${field.locator.width}%`, height: `${field.locator.height}%` }}>
                      <button type="button" aria-label={`Move ${field.name} box`} title={`Move ${field.name}`} aria-pressed={selectedFieldId === field.id}
                        className="absolute inset-0 touch-none cursor-move focus-visible:outline-2 focus-visible:outline-emerald-600"
                        disabled={creationMode !== "idle"}
                        onClick={() => setSelectedFieldId(field.id || null)}
                        onPointerDown={(event) => startBoxDrag(event, field, "move")} onPointerMove={moveBox} onPointerUp={endBoxDrag} onPointerCancel={endBoxDrag}
                        onKeyDown={(event) => nudgeBox(event, field)} />
                      {selectedFieldId === field.id && <>
                        <span className="pointer-events-none absolute bottom-full left-0 max-w-48 truncate bg-emerald-700 px-1 text-xs text-white">{field.name}</span>
                        <button type="button" aria-label={`Resize ${field.name} box`} title={`Resize ${field.name}`} className="absolute -bottom-2 -right-2 h-4 w-4 touch-none cursor-nwse-resize border border-white bg-emerald-600"
                          onPointerDown={(event) => startBoxDrag(event, field, "resize")} onPointerMove={moveBox} onPointerUp={endBoxDrag} onPointerCancel={endBoxDrag}
                          onKeyDown={(event) => nudgeBox(event, field, true)} />
                      </>}
                    </div>
                  ))}
                  {creationMode === "idle" && renderedPage === renderKey && fields.filter((field) => field.type === "array" && field.locator?.page === pageNumber && field.array_config).map((field) => {
                    const locator = field.locator!
                    const columns = field.array_config!.columns
                    return (
                      <div key={`${field.id}-column-guides`} className="pointer-events-none absolute" style={{ left: `${locator.x}%`, top: `${locator.y}%`, width: `${locator.width}%`, height: `${locator.height}%` }}>
                        {columns.slice(0, -1).map((column, boundaryIndex) => (
                          <button
                            key={`${field.id}-boundary-${boundaryIndex}`}
                            type="button"
                            aria-label={`Resize boundary after ${column.name}`}
                            title={`Drag to resize ${column.name}`}
                            className="pointer-events-auto absolute top-0 z-10 h-full w-3 -translate-x-1/2 cursor-col-resize touch-none"
                            style={{ left: `${column.x + column.width}%` }}
                            onClick={(event) => event.stopPropagation()}
                            onPointerDown={(event) => {
                              event.stopPropagation()
                              event.currentTarget.setPointerCapture(event.pointerId)
                              setDraggingColumnBoundary({ fieldId: field.id!, boundaryIndex })
                            }}
                            onPointerMove={(event) => {
                              const activeBoundary = draggingColumnBoundary
                              if (!activeBoundary || activeBoundary.fieldId !== field.id || activeBoundary.boundaryIndex !== boundaryIndex) return
                              const point = toPercent(event)
                              if (!point) return
                              resizeArrayColumnBoundary(field.id!, boundaryIndex, ((point.x - locator.x) / locator.width) * 100)
                            }}
                            onPointerUp={(event) => {
                              event.stopPropagation()
                              if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
                              setDraggingColumnBoundary(null)
                            }}
                          >
                            <span className="pointer-events-none absolute left-1/2 top-0 h-full w-0.5 -translate-x-1/2 bg-blue-600 shadow-[0_0_0_1px_rgba(255,255,255,0.85)]" />
                          </button>
                        ))}
                      </div>
                    )
                  })}
                  {selection && <div ref={draftBoxRef} className="pointer-events-none absolute z-20 border-2 border-dashed border-emerald-600 bg-emerald-400/20 shadow-[0_0_0_1px_rgba(255,255,255,0.9)]" style={{ left: `${selection.x}%`, top: `${selection.y}%`, width: `${selection.width}%`, height: `${selection.height}%` }}>
                    {!dragStart && validLocator({ type: "bbox", page: pageNumber, ...selection }) && <>
                      <button type="button" aria-label="Move new field box" title="Move new field box" className="pointer-events-auto absolute inset-0 touch-none cursor-move" onPointerDown={(event) => startDraftDrag(event, "move")} onPointerMove={moveDraft} onPointerUp={endDraftDrag} onPointerCancel={endDraftDrag} />
                      <button type="button" aria-label="Resize new field box" title="Resize new field box" className="pointer-events-auto absolute -bottom-2 -right-2 h-4 w-4 touch-none cursor-nwse-resize border border-white bg-emerald-600" onPointerDown={(event) => startDraftDrag(event, "resize")} onPointerMove={moveDraft} onPointerUp={endDraftDrag} onPointerCancel={endDraftDrag} />
                    </>}
                  </div>}
                </div>
              </div>
              </div>
            </section>

            <section ref={sidebarRef} className="min-w-0 space-y-2 lg:max-h-[68vh] lg:overflow-y-auto lg:pr-1">
              {creationMode !== "idle" && pendingField && <section ref={draftEditorRef} aria-label="New field" className="space-y-3 border-b border-slate-200 pb-4">
                <h3 className="text-sm font-semibold text-slate-900">New field</h3>
                {creationMode === "search" && <form className="space-y-2" onSubmit={(event) => { event.preventDefault(); void findInForm() }}>
                  <label className="block text-xs font-medium text-slate-600">Text in document
                    <input ref={searchInputRef} aria-label="Text in document" value={findValue} onChange={(event) => { setFindValue(event.target.value); setSelection(null); setFindMessage(null) }} disabled={finding} className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 text-sm" />
                  </label>
                  <Button type="submit" size="sm" variant="outline" disabled={finding || !findValue.trim() || !numPages}>
                    {finding ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : <LocateFixed className="mr-1.5 h-4 w-4" />}Find text
                  </Button>
                  {findMessage && <p role="status" className="text-xs text-slate-700">{findMessage}</p>}
                </form>}
                <label className="block text-xs font-medium text-slate-600">Field name
                  <input ref={draftNameRef} aria-label="New field name" className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 text-sm" value={pendingField.name} disabled={finding} onChange={(event) => setPendingField({ ...pendingField, name: event.target.value })} />
                </label>
                <label className="block text-xs font-medium text-slate-600">Type
                  <select aria-label="New field type" className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 text-sm" value={pendingField.type} disabled={finding} onChange={(event) => { const type = fieldTypes.find((item) => item.value === event.target.value)?.value; if (type) setPendingField({ ...pendingField, type }) }}>
                    {fieldTypes.map((type) => <option key={type.value} value={type.value}>{type.label}</option>)}
                  </select>
                </label>
                {(creationMode === "coordinates" || selection) && <details open={creationMode === "coordinates"} className="border-t border-slate-200 pt-2">
                  <summary className="cursor-pointer text-xs font-medium text-slate-600">Position</summary>
                  <div className="mt-2 grid grid-cols-2 gap-2">
                    {(["page", "x", "y", "width", "height"] as const).map((key) => <label key={key} className="text-xs text-slate-600">{key === "page" ? "Page" : `${key} (%)`}
                      <input aria-label={`New field ${key}`} type="number" min={key === "page" ? 1 : 0} max={key === "page" ? numPages || undefined : 100} step={key === "page" ? 1 : 0.01} value={key === "page" ? pageNumber : selection?.[key] ?? 0} className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 text-sm" onChange={(event) => { const value = Number(event.target.value); if (key === "page") setPageNumber(clamp(Math.trunc(value), 1, numPages || Math.max(1, value))); else setSelection((box) => ({ ...(box || { x: 0, y: 0, width: 10, height: 5 }), [key]: value })) }} />
                    </label>)}
                  </div>
                </details>}
                {(!isValidFieldName(pendingField.name.trim()) || fields.some((field) => field.name === pendingField.name.trim())) && <p role="alert" className="text-xs text-red-700">Use a unique field name with letters, numbers or underscores.</p>}
                {selection && (!validLocator({ type: "bbox", page: pageNumber, ...selection }) || (numPages > 0 && pageNumber > numPages)) && <p role="alert" className="text-xs text-red-700">Keep the box within a valid document page.</p>}
                <div className="flex gap-2">
                  <Button type="button" size="sm" onClick={addSelection} disabled={finding || !selection || !validLocator({ type: "bbox", page: pageNumber, ...selection }) || (numPages > 0 && pageNumber > numPages) || !isValidFieldName(pendingField.name.trim()) || fields.some((field) => field.name === pendingField.name.trim())}><Plus className="mr-1 h-4 w-4" />Add</Button>
                  <Button type="button" size="sm" variant="outline" disabled={finding} onClick={cancelCreation}>Cancel field</Button>
                </div>
              </section>}
              <div className="sticky top-0 z-10 flex items-center justify-between gap-2 bg-white pb-2 text-sm font-medium text-slate-700"><span className="flex items-center gap-2"><ScanLine className="h-4 w-4 text-emerald-600" />Fixed fields</span><span className="text-xs font-normal text-slate-500">{fixedFields.length} fields</span></div>
              {fixedFields.length === 0 ? <p className="py-3 text-sm text-slate-500">No fields yet</p> : fixedFields.map((field) => {
                const locator = field.locator
                const previewValue = previewValues[field.name]
                const rawPreviewValue = rawPreviewValues[field.name]
                if (!locator) return null
                return <div key={field.id} ref={(node) => { if (field.id) { if (node) rowRefs.current.set(field.id, node); else rowRefs.current.delete(field.id) } }} className={`space-y-2 border-b bg-white p-3 ${selectedFieldId === field.id ? "border-emerald-300" : "border-slate-200"}`}>
                  <button type="button" aria-label={`Edit ${field.name}`} aria-expanded={selectedFieldId === field.id} disabled={finding} onClick={() => selectField(field)} className="flex min-h-8 w-full min-w-0 items-center justify-between gap-2 text-left text-sm">
                    <span className="min-w-0 break-words font-medium text-slate-800">{field.name || "Unnamed field"}</span><span className="flex shrink-0 items-center gap-2 text-xs text-slate-500">p. {locator.page} · {fieldTypes.find((type) => type.value === field.type)?.label}<ChevronDown className={`h-3.5 w-3.5 ${selectedFieldId === field.id ? "rotate-180" : ""}`} /></span>
                  </button>
                  {selectedFieldId === field.id && <>
                  <div className="flex gap-2">
                    <input aria-label="Field name" className="min-w-0 flex-1 rounded border border-slate-300 px-2 py-1.5 text-sm" value={field.name} onChange={(event) => updateField(field.id!, { name: event.target.value })} />
                    <select aria-label="Field type" className="rounded border border-slate-300 px-2 py-1.5 text-sm" value={field.type} onChange={(event) => updateFieldType(field.id!, event.target.value as SchemaField["type"])}>
                      <option value="text">Text</option><option value="number">Number</option><option value="date">Date</option><option value="currency">Currency</option><option value="boolean">Yes/No</option><option value="array">Table array</option>
                    </select>
                    <button type="button" aria-label={`Remove ${field.name}`} title="Remove field" onClick={() => removeField(field.id!)} className="text-slate-400 hover:text-red-600"><Trash2 className="h-4 w-4" /></button>
                  </div>
                  <label className="block text-xs text-slate-600">Description / Prompt<input aria-label={`${field.name} description`} className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 text-sm" value={field.description} onChange={(event) => updateField(field.id!, { description: event.target.value })} /></label>
                  <label className="flex items-center gap-2 text-xs text-slate-600"><input type="checkbox" checked={field.required} onChange={(event) => updateField(field.id!, { required: event.target.checked })} />Required</label>
                  <details className="rounded border border-slate-200 bg-slate-50 px-2 py-1.5">
                    <summary className="cursor-pointer text-xs font-medium text-slate-600">Advanced position</summary>
                    <div className="mt-2 grid grid-cols-5 gap-1">
                      {(["page", "x", "y", "width", "height"] as const).map((key) => <label key={key} className="text-xs font-medium text-slate-500">{key === "width" ? "W (%)" : key === "height" ? "H (%)" : key === "page" ? "Page" : `${key.toUpperCase()} (%)`}<input aria-label={`${field.name} ${key}`} type="number" min={key === "page" ? 1 : 0} step={key === "page" ? 1 : 0.01} className="mt-1 w-full rounded border border-slate-300 px-1.5 py-1 text-xs text-slate-700" value={locator[key]} onChange={(event) => updateLocator(field.id!, key, event.target.value)} /></label>)}
                    </div>
                  </details>
                  <label className="flex items-center gap-2 text-xs text-slate-600">
                    <input
                      type="checkbox"
                      checked={locator.clean_placeholders !== false}
                      onChange={(event) => updateField(field.id!, { locator: { ...locator, clean_placeholders: event.target.checked } })}
                    />
                    Remove form placeholders
                  </label>
                  {field.type === "array" && field.array_config && (
                    <div className="space-y-3 rounded-md border border-blue-100 bg-blue-50/50 p-2.5">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-xs font-semibold text-slate-700">Table columns</span>
                        <Button type="button" variant="outline" size="sm" className="h-7 px-2 text-xs" onClick={() => addArrayColumn(field.id!)} disabled={field.array_config.columns.length >= 12} title="Split the widest column, then drag the divider on the document"><Plus className="mr-1 h-3.5 w-3.5" />Column</Button>
                      </div>
                      <p className="text-xs leading-4 text-slate-600">Add a column, then drag the blue dividers on the document to match the table.</p>
                      <div className="grid grid-cols-[minmax(0,1fr)_4.5rem_1.5rem] gap-1 text-xs font-medium text-slate-500">
                        <span>Name</span><span>Type</span><span />
                      </div>
                      {field.array_config.columns.map((column, columnIndex) => (
                        <div key={`${field.id}-column-${columnIndex}`} className="grid grid-cols-[minmax(0,1fr)_4.5rem_1.5rem] gap-1">
                          <input aria-label={`${field.name} column name`} className="min-w-0 rounded border border-slate-300 px-1.5 py-1 text-xs" value={column.name} onChange={(event) => updateArrayColumn(field.id!, columnIndex, { name: event.target.value })} />
                          <select aria-label={`${field.name} column type`} className="rounded border border-slate-300 px-1 py-1 text-xs" value={column.type} onChange={(event) => updateArrayColumn(field.id!, columnIndex, { type: event.target.value as ArrayColumn["type"] })}>
                            <option value="text">Text</option><option value="number">No.</option><option value="date">Date</option><option value="currency">Money</option>
                          </select>
                          <button type="button" aria-label={`Remove ${column.name}`} title="Remove column" disabled={field.array_config!.columns.length === 1} onClick={() => removeArrayColumn(field.id!, columnIndex)} className="text-slate-400 hover:text-red-600 disabled:cursor-not-allowed disabled:opacity-40"><Trash2 className="h-3.5 w-3.5" /></button>
                        </div>
                      ))}
                      <div className="grid grid-cols-2 gap-2">
                        <label className="text-xs font-medium text-slate-600">Rows
                          <select aria-label={`${field.name} row detection`} className="mt-1 w-full rounded border border-slate-300 px-1.5 py-1 text-xs" value={field.array_config.row_detection} onChange={(event) => updateArrayConfig(field.id!, { row_detection: event.target.value as ArrayConfig["row_detection"] })}>
                            <option value="anchor_column">Anchor column</option><option value="line">Each visual line</option>
                          </select>
                        </label>
                        <label className="text-xs font-medium text-slate-600">Header rows
                          <input aria-label={`${field.name} header rows`} type="number" min="0" step="1" className="mt-1 w-full rounded border border-slate-300 px-1.5 py-1 text-xs" value={field.array_config.header_rows} onChange={(event) => updateArrayConfig(field.id!, { header_rows: Number(event.target.value) })} />
                        </label>
                      </div>
                      {field.array_config.row_detection === "anchor_column" && <label className="block text-xs font-medium text-slate-600">Row starts at
                        <select aria-label={`${field.name} anchor column`} className="mt-1 w-full rounded border border-slate-300 px-1.5 py-1 text-xs" value={field.array_config.anchor_column || ""} onChange={(event) => updateArrayConfig(field.id!, { anchor_column: event.target.value })}>
                          {field.array_config.columns.map((column) => <option key={column.name} value={column.name}>{column.name}</option>)}
                        </select>
                      </label>}
                    </div>
                  )}
                  {previewValue !== undefined && (
                    <div className="space-y-1 rounded-md bg-slate-50 p-2 text-xs">
                      {Array.isArray(previewValue) ? (
                        <div className="overflow-x-auto">
                          <p className="mb-1 font-medium text-emerald-700">Extracted {previewValue.length} rows</p>
                          <table className="min-w-full border-collapse text-left text-xs">
                            <thead><tr>{field.array_config?.columns.map((column) => <th key={column.name} className="border-b border-slate-200 px-1 py-1 font-medium text-slate-600">{column.name}</th>)}</tr></thead>
                            <tbody>{previewValue.map((row, rowIndex) => <tr key={rowIndex}>{field.array_config?.columns.map((column) => <td key={column.name} className="border-b border-slate-100 px-1 py-1 text-slate-700">{String(row[column.name] ?? "")}</td>)}</tr>)}</tbody>
                          </table>
                        </div>
                      ) : <>
                        {rawPreviewValue !== previewValue && (
                          <p className="break-words text-slate-500"><span className="font-medium">Raw:</span> {String(rawPreviewValue || "No text in this box")}</p>
                        )}
                        <p className="break-words text-emerald-700"><span className="font-medium">Extracted:</span> {String(previewValue ?? "No text in this box")}</p>
                      </>}
                    </div>
                  )}
                  </>}
                </div>
              } )}
            </section>
          </div>
        </>

      {error && <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700"><AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />{error}</div>}
      {fieldValidationMessage && <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800" role="alert"><AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />{fieldValidationMessage}</div>}
      {arrayValidationMessage.length > 0 && <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800" role="alert"><AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />Configure valid table columns and row detection for: {arrayValidationMessage.join(", ")}</div>}

      <div className="flex justify-end border-t pt-4"><Button type="button" onClick={nextStep} disabled={!canProceed || reading || finding || creationMode !== "idle"}>Next</Button></div>
    </div>
  )
}
