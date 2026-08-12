"use client"

import { useEffect, useMemo, useRef, useState, type ChangeEvent, type PointerEvent } from "react"
import { Document, Page, pdfjs } from "react-pdf"
import { AlertCircle, ChevronLeft, ChevronRight, FileText, Loader2, Plus, ScanLine, Sparkles, Trash2, ZoomIn, ZoomOut } from "lucide-react"
import { Button } from "@/components/ui/button"
import { useSchemaWizard } from "@/contexts/SchemaWizardContext"
import type { BboxLocator, SchemaField } from "@/types/schema"
import { getApiBaseUrl } from "@/lib/api"
import { isValidFieldName } from "@/lib/schema-validation"
import "react-pdf/dist/Page/AnnotationLayer.css"
import "react-pdf/dist/Page/TextLayer.css"

pdfjs.GlobalWorkerOptions.workerSrc = `//unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`

const genId = () => `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
const BASE_PAGE_WIDTH = 760

type Selection = { x: number; y: number; width: number; height: number } | null

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

export function FixedPositionFieldsStep() {
  const { fields, setFields, addField, updateField, removeField, nextStep } = useSchemaWizard()
  const [file, setFile] = useState<File | null>(null)
  const [pageNumber, setPageNumber] = useState(1)
  const [numPages, setNumPages] = useState(0)
  const [selection, setSelection] = useState<Selection>(null)
  const [dragStart, setDragStart] = useState<{ x: number; y: number } | null>(null)
  const [previewValues, setPreviewValues] = useState<Record<string, string>>({})
  const [rawPreviewValues, setRawPreviewValues] = useState<Record<string, string>>({})
  const [reading, setReading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [zoom, setZoom] = useState(1)
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

  const toPercent = (event: PointerEvent<HTMLDivElement>) => {
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
  const canProceed = fields.length > 0 && !fieldValidationMessage && fields.every((field) => validLocator(field.locator))

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
                    <div key={field.id} className="pointer-events-none absolute border-2 border-blue-500 bg-blue-500/10" style={{ left: `${field.locator.x}%`, top: `${field.locator.y}%`, width: `${field.locator.width}%`, height: `${field.locator.height}%` }} />
                  ))}
                  {selection && <div className="pointer-events-none absolute border-2 border-dashed border-emerald-600 bg-emerald-400/15" style={{ left: `${selection.x}%`, top: `${selection.y}%`, width: `${selection.width}%`, height: `${selection.height}%` }} />}
                </div>
              </div>
              </div>
            </section>

            <section className="min-w-0 space-y-2 lg:max-h-[68vh] lg:overflow-y-auto lg:pr-1">
              <div className="sticky top-0 z-10 flex items-center justify-between gap-2 bg-white pb-2 text-sm font-medium text-slate-700"><span className="flex items-center gap-2"><ScanLine className="h-4 w-4 text-emerald-600" />Fields</span><span className="text-xs font-normal text-slate-500">{fields.length} selected</span></div>
              {fields.length === 0 ? <div className="rounded-lg border border-dashed border-slate-300 p-4 text-sm text-slate-500">Draw a box, or add a field by coordinates.</div> : fields.map((field) => {
                const locator = field.locator
                if (!locator) return null
                return <div key={field.id} className="space-y-2 rounded-lg border border-slate-200 bg-white p-3">
                  <div className="flex gap-2">
                    <input aria-label="Field name" className="min-w-0 flex-1 rounded border border-slate-300 px-2 py-1.5 text-sm" value={field.name} onChange={(event) => updateField(field.id!, { name: event.target.value })} />
                    <select aria-label="Field type" className="rounded border border-slate-300 px-2 py-1.5 text-sm" value={field.type} onChange={(event) => updateField(field.id!, { type: event.target.value as SchemaField["type"] })}>
                      <option value="text">Text</option><option value="number">Number</option><option value="date">Date</option><option value="currency">Currency</option>
                    </select>
                    <button type="button" aria-label={`Remove ${field.name}`} title="Remove field" onClick={() => removeField(field.id!)} className="text-slate-400 hover:text-red-600"><Trash2 className="h-4 w-4" /></button>
                  </div>
                  <div className="grid grid-cols-5 gap-1">
                    {(["page", "x", "y", "width", "height"] as const).map((key) => <label key={key} className="text-[11px] font-medium text-slate-500">{key === "width" ? "W (%)" : key === "height" ? "H (%)" : key === "page" ? "Page" : `${key.toUpperCase()} (%)`}<input aria-label={`${field.name} ${key}`} type="number" min={key === "page" ? 1 : 0} step={key === "page" ? 1 : 0.01} className="mt-1 w-full rounded border border-slate-300 px-1.5 py-1 text-xs text-slate-700" value={locator[key]} onChange={(event) => updateLocator(field.id!, key, event.target.value)} /></label>)}
                  </div>
                  <label className="flex items-center gap-2 text-xs text-slate-600">
                    <input
                      type="checkbox"
                      checked={locator.clean_placeholders !== false}
                      onChange={(event) => updateField(field.id!, { locator: { ...locator, clean_placeholders: event.target.checked } })}
                    />
                    Remove form placeholders
                  </label>
                  {previewValues[field.name] !== undefined && (
                    <div className="space-y-1 rounded-md bg-slate-50 p-2 text-xs">
                      {rawPreviewValues[field.name] !== previewValues[field.name] && (
                        <p className="break-words text-slate-500"><span className="font-medium">Raw:</span> {rawPreviewValues[field.name] || "No text in this box"}</p>
                      )}
                      <p className="break-words text-emerald-700"><span className="font-medium">Extracted:</span> {previewValues[field.name] || "No text in this box"}</p>
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

      <div className="flex justify-end border-t pt-4"><Button type="button" onClick={nextStep} disabled={!canProceed || reading}>Next</Button></div>
    </div>
  )
}
