"use client"

import { useEffect, useMemo, useRef, useState, type ChangeEvent, type PointerEvent } from "react"
import { Document, Page, pdfjs } from "react-pdf"
import { AlertCircle, ChevronLeft, ChevronRight, FileText, Loader2, Plus, ScanLine, Sparkles, Trash2, ZoomIn, ZoomOut } from "lucide-react"
import { Button } from "@/components/ui/button"
import { useSchemaWizard } from "@/contexts/SchemaWizardContext"
import type { ArrayColumn, ArrayConfig, BboxLocator, SchemaField } from "@/types/schema"
import { getApiBaseUrl } from "@/lib/api"
import { isValidFieldName } from "@/lib/schema-validation"
import "react-pdf/dist/Page/AnnotationLayer.css"
import "react-pdf/dist/Page/TextLayer.css"

pdfjs.GlobalWorkerOptions.workerSrc = `//unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`

const genId = () => `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
const BASE_PAGE_WIDTH = 760

type Selection = { x: number; y: number; width: number; height: number } | null
type PreviewValue = string | Array<Record<string, unknown>>

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

function clamp(value: number) {
  return Math.min(100, Math.max(0, value))
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
  const { fields, setFields, addField, updateField, removeField, nextStep } = useSchemaWizard()
  const [file, setFile] = useState<File | null>(null)
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

  const fileUrl = useMemo(() => file ? URL.createObjectURL(file) : null, [file])
  useEffect(() => () => { if (fileUrl) URL.revokeObjectURL(fileUrl) }, [fileUrl])

  const handleFileSelect = (event: ChangeEvent<HTMLInputElement>) => {
    const selected = event.target.files?.[0]
    if (!selected) return
    if (selected.type !== "application/pdf") {
      setError("Choose a PDF form for fixed-position fields")
      return
    }
    setFile(selected)
    setFields([])
    setPreviewValues({})
    setRawPreviewValues({})
    setSelection(null)
    setPageNumber(1)
    setNumPages(0)
    setZoom(1)
    setError(null)
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
    if (!file || event.button !== 0) return
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
  }

  const addSelection = () => {
    if (!selection) return
    const locator: BboxLocator = {
      type: "bbox",
      page: pageNumber,
      x: Number(selection.x.toFixed(2)),
      y: Number(selection.y.toFixed(2)),
      width: Number(selection.width.toFixed(2)),
      height: Number(selection.height.toFixed(2)),
    }
    addField({
      id: genId(),
      name: `field_${fields.length + 1}`,
      type: "text",
      description: "",
      required: false,
      locator: { ...locator, clean_placeholders: true },
    })
    setSelection(null)
  }

  const addCoordinateField = () => {
    addField({
      id: genId(),
      name: `field_${fields.length + 1}`,
      type: "text",
      description: "",
      required: false,
      locator: { type: "bbox", page: pageNumber, x: 0, y: 0, width: 10, height: 5, clean_placeholders: true },
    })
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
      formData.append("fields_json", JSON.stringify(fields.map((field) => {
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
    .filter((field) => field.type === "array" && !validArrayConfig(field.array_config))
    .map((field) => field.name || "(unnamed)")
  const canProceed = fields.length > 0 && !fieldValidationMessage && arrayValidationMessage.length === 0 && fields.every((field) => validLocator(field.locator))

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold text-slate-900">Fixed-position fields</h2>
          <p className="mt-1 text-sm text-slate-600">Draw a box for each value in a stable PDF form.</p>
        </div>
        {file && <div className="flex gap-2">
          <Button type="button" variant="outline" size="sm" onClick={addCoordinateField}>
            <Plus className="mr-1.5 h-4 w-4" />Add by coordinates
          </Button>
          <Button variant="outline" size="sm" onClick={previewFields} disabled={!canProceed || reading}>
            {reading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Sparkles className="mr-2 h-4 w-4" />}
            Read sample
          </Button>
        </div>}
      </div>

      {!file ? (
        <label className="flex min-h-48 cursor-pointer flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-blue-300 bg-blue-50/50 p-6 text-center hover:border-blue-500">
          <FileText className="h-9 w-9 text-blue-500" />
          <span className="font-medium text-blue-700">Choose PDF form</span>
          <input type="file" accept="application/pdf" className="hidden" onChange={handleFileSelect} />
        </label>
      ) : (
        <>
          <div className="flex items-center justify-between rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm">
            <span className="flex min-w-0 items-center gap-2 truncate text-slate-700"><FileText className="h-4 w-4 shrink-0" />{file.name}</span>
            <button className="text-slate-500 hover:text-red-600" onClick={() => { setFile(null); setFields([]); setPreviewValues({}); setRawPreviewValues({}); setSelection(null); setError(null) }}>Change</button>
          </div>

          <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_24rem] lg:items-start">
            <section className="min-w-0 rounded-lg border border-slate-200 bg-slate-50">
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-3 py-2 text-sm text-slate-600">
                <span className="font-medium">Page {pageNumber}{numPages ? ` of ${numPages}` : ""}</span>
                <div className="flex flex-wrap items-center justify-end gap-1">
                  <Button type="button" variant="outline" size="icon" className="h-8 w-8" aria-label="Previous page" title="Previous page" onClick={() => setPageNumber((page) => Math.max(1, page - 1))} disabled={pageNumber <= 1}><ChevronLeft className="h-4 w-4" /></Button>
                  <Button type="button" variant="outline" size="icon" className="h-8 w-8" aria-label="Next page" title="Next page" onClick={() => setPageNumber((page) => Math.min(numPages, page + 1))} disabled={!numPages || pageNumber >= numPages}><ChevronRight className="h-4 w-4" /></Button>
                  <span className="mx-1 h-5 w-px bg-slate-300" />
                  <Button type="button" variant="outline" size="icon" className="h-8 w-8" aria-label="Zoom out" title="Zoom out" onClick={() => setZoom((value) => Math.max(0.75, Number((value - 0.25).toFixed(2))))} disabled={zoom <= 0.75}><ZoomOut className="h-4 w-4" /></Button>
                  <span className="min-w-12 text-center text-xs font-medium text-slate-500">{Math.round(zoom * 100)}%</span>
                  <Button type="button" variant="outline" size="icon" className="h-8 w-8" aria-label="Zoom in" title="Zoom in" onClick={() => setZoom((value) => Math.min(1.75, Number((value + 0.25).toFixed(2))))} disabled={zoom >= 1.75}><ZoomIn className="h-4 w-4" /></Button>
                  <Button type="button" variant="ghost" size="sm" className="ml-1 h-8 px-2 text-xs" onClick={() => setZoom(1)}>Fit</Button>
                  <span className="mx-1 h-5 w-px bg-slate-300" />
                  <Button type="button" size="sm" className="h-8" onClick={addSelection} disabled={!selection} title={selection ? "Add the selected box as a field" : "Draw a box first"}>
                    <Plus className="mr-1.5 h-4 w-4" />Add field
                  </Button>
                </div>
              </div>
              <div className="max-h-[68vh] min-h-[32rem] overflow-auto p-5">
                <div className="flex min-w-full justify-center">
                <div
                  ref={surfaceRef}
                  className="relative inline-block touch-none select-none shadow-sm"
                  onPointerDown={handlePointerDown}
                  onPointerMove={handlePointerMove}
                  onPointerUp={handlePointerUp}
                >
                  {fileUrl && <Document file={fileUrl} loading={<div className="grid h-72 w-[760px] place-items-center"><Loader2 className="h-5 w-5 animate-spin" /></div>} onLoadSuccess={({ numPages: pages }) => setNumPages(pages)}>
                    <Page pageNumber={pageNumber} width={Math.round(BASE_PAGE_WIDTH * zoom)} renderTextLayer={false} renderAnnotationLayer={false} />
                  </Document>}
                  {fields.filter((field) => field.locator?.page === pageNumber).map((field) => field.locator && (
                    <div key={field.id} className="pointer-events-none absolute border-2 border-dashed border-blue-600 bg-blue-500/20 shadow-[0_0_0_1px_rgba(255,255,255,0.9)]" style={{ left: `${field.locator.x}%`, top: `${field.locator.y}%`, width: `${field.locator.width}%`, height: `${field.locator.height}%` }} />
                  ))}
                  {fields.filter((field) => field.type === "array" && field.locator?.page === pageNumber && field.array_config).map((field) => {
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
                  {selection && <div className="pointer-events-none absolute border-2 border-dashed border-emerald-600 bg-emerald-400/20 shadow-[0_0_0_1px_rgba(255,255,255,0.9)]" style={{ left: `${selection.x}%`, top: `${selection.y}%`, width: `${selection.width}%`, height: `${selection.height}%` }} />}
                </div>
              </div>
              </div>
            </section>

            <section className="min-w-0 space-y-2 lg:max-h-[68vh] lg:overflow-y-auto lg:pr-1">
              <div className="sticky top-0 z-10 flex items-center justify-between gap-2 bg-white pb-2 text-sm font-medium text-slate-700"><span className="flex items-center gap-2"><ScanLine className="h-4 w-4 text-emerald-600" />Fields</span><span className="text-xs font-normal text-slate-500">{fields.length} selected</span></div>
              {fields.length === 0 ? <div className="rounded-lg border border-dashed border-slate-300 p-4 text-sm text-slate-500">Draw a box, or add a field by coordinates.</div> : fields.map((field) => {
                const locator = field.locator
                const previewValue = previewValues[field.name]
                const rawPreviewValue = rawPreviewValues[field.name]
                if (!locator) return null
                return <div key={field.id} className="space-y-2 rounded-lg border border-slate-200 bg-white p-3">
                  <div className="flex gap-2">
                    <input aria-label="Field name" className="min-w-0 flex-1 rounded border border-slate-300 px-2 py-1.5 text-sm" value={field.name} onChange={(event) => updateField(field.id!, { name: event.target.value })} />
                    <select aria-label="Field type" className="rounded border border-slate-300 px-2 py-1.5 text-sm" value={field.type} onChange={(event) => updateFieldType(field.id!, event.target.value as SchemaField["type"])}>
                      <option value="text">Text</option><option value="number">Number</option><option value="date">Date</option><option value="currency">Currency</option><option value="array">Table array</option>
                    </select>
                    <button type="button" aria-label={`Remove ${field.name}`} title="Remove field" onClick={() => removeField(field.id!)} className="text-slate-400 hover:text-red-600"><Trash2 className="h-4 w-4" /></button>
                  </div>
                  <details className="rounded border border-slate-200 bg-slate-50 px-2 py-1.5">
                    <summary className="cursor-pointer text-xs font-medium text-slate-600">Fine-tune position</summary>
                    <div className="mt-2 grid grid-cols-5 gap-1">
                      {(["page", "x", "y", "width", "height"] as const).map((key) => <label key={key} className="text-[11px] font-medium text-slate-500">{key === "width" ? "W (%)" : key === "height" ? "H (%)" : key === "page" ? "Page" : `${key.toUpperCase()} (%)`}<input aria-label={`${field.name} ${key}`} type="number" min={key === "page" ? 1 : 0} step={key === "page" ? 1 : 0.01} className="mt-1 w-full rounded border border-slate-300 px-1.5 py-1 text-xs text-slate-700" value={locator[key]} onChange={(event) => updateLocator(field.id!, key, event.target.value)} /></label>)}
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
                      <p className="text-[11px] leading-4 text-slate-600">Add a column, then drag the blue dividers on the document to match the table.</p>
                      <div className="grid grid-cols-[minmax(0,1fr)_4.5rem_1.5rem] gap-1 text-[11px] font-medium text-slate-500">
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
                        <label className="text-[11px] font-medium text-slate-600">Rows
                          <select aria-label={`${field.name} row detection`} className="mt-1 w-full rounded border border-slate-300 px-1.5 py-1 text-xs" value={field.array_config.row_detection} onChange={(event) => updateArrayConfig(field.id!, { row_detection: event.target.value as ArrayConfig["row_detection"] })}>
                            <option value="anchor_column">Anchor column</option><option value="line">Each visual line</option>
                          </select>
                        </label>
                        <label className="text-[11px] font-medium text-slate-600">Header rows
                          <input aria-label={`${field.name} header rows`} type="number" min="0" step="1" className="mt-1 w-full rounded border border-slate-300 px-1.5 py-1 text-xs" value={field.array_config.header_rows} onChange={(event) => updateArrayConfig(field.id!, { header_rows: Number(event.target.value) })} />
                        </label>
                      </div>
                      {field.array_config.row_detection === "anchor_column" && <label className="block text-[11px] font-medium text-slate-600">Row starts at
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
                          <table className="min-w-full border-collapse text-left text-[11px]">
                            <thead><tr>{field.array_config?.columns.map((column) => <th key={column.name} className="border-b border-slate-200 px-1 py-1 font-medium text-slate-600">{column.name}</th>)}</tr></thead>
                            <tbody>{previewValue.map((row, rowIndex) => <tr key={rowIndex}>{field.array_config?.columns.map((column) => <td key={column.name} className="border-b border-slate-100 px-1 py-1 text-slate-700">{String(row[column.name] ?? "")}</td>)}</tr>)}</tbody>
                          </table>
                        </div>
                      ) : <>
                        {rawPreviewValue !== previewValue && (
                          <p className="break-words text-slate-500"><span className="font-medium">Raw:</span> {String(rawPreviewValue || "No text in this box")}</p>
                        )}
                        <p className="break-words text-emerald-700"><span className="font-medium">Extracted:</span> {String(previewValue || "No text in this box")}</p>
                      </>}
                    </div>
                  )}
                </div>
              } )}
            </section>
          </div>
        </>
      )}

      {error && <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700"><AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />{error}</div>}
      {fieldValidationMessage && <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800" role="alert"><AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />{fieldValidationMessage}</div>}
      {arrayValidationMessage.length > 0 && <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800" role="alert"><AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />Configure valid table columns and row detection for: {arrayValidationMessage.join(", ")}</div>}

      <div className="flex justify-end border-t pt-4"><Button type="button" onClick={nextStep} disabled={!canProceed || reading}>Next</Button></div>
    </div>
  )
}
