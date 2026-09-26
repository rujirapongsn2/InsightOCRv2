"use client"

import { useState, useEffect, useMemo, useRef } from "react"
import { Document, Page, pdfjs } from "react-pdf"
import { ZoomIn, ZoomOut, RotateCw, ChevronLeft, ChevronRight, SearchX } from "lucide-react"
import { Button } from "@/components/ui/button"
import { findTextBox, findWordBox, type Box, type Highlight, type PageWord, type TextItemLike } from "@/lib/evidence-search"
import "react-pdf/dist/Page/AnnotationLayer.css"
import "react-pdf/dist/Page/TextLayer.css"

// Configure PDF.js worker — use CDN matching the exact pdfjs version from react-pdf
pdfjs.GlobalWorkerOptions.workerSrc = `//unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`

interface PDFViewerProps {
  fileUrl: string
  className?: string
  highlight?: Highlight | null
  /** OCR word positions per page, used where a page has no text layer (scans). */
  pageWords?: Record<number, PageWord[]>
}

type PdfProxy = {
  numPages: number
  getPage: (page: number) => Promise<{
    getViewport: (options: { scale: number }) => { width: number; height: number; convertToViewportRectangle: (rect: number[]) => number[] }
    getTextContent: () => Promise<{ items: Array<Partial<TextItemLike>> }>
  }>
}

export function PDFViewer({ fileUrl, className = "", highlight, pageWords }: PDFViewerProps) {
  const [numPages, setNumPages] = useState<number>(0)
  const [pageNumber, setPageNumber] = useState<number>(1)
  const [scale, setScale] = useState<number>(1.0)
  const [rotation, setRotation] = useState<number>(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [pdfData, setPdfData] = useState<Uint8Array | null>(null)
  const pdfRef = useRef<PdfProxy | null>(null)
  // Where the highlighted text was found: a stored bbox, or one located in the text layer.
  const [located, setLocated] = useState<{ page: number; bbox: Box } | null>(null)
  const [searchState, setSearchState] = useState<"idle" | "searching" | "not_found">("idle")
  const boxRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    let cancelled = false
    setLocated(null)
    setSearchState("idle")
    if (!highlight || !numPages) return
    const pageExists = !!highlight.page && highlight.page >= 1 && highlight.page <= numPages
    if (pageExists) {
      setPageNumber(highlight.page!)
      setRotation(0)
    }
    // A stored box is only usable on a page that exists; otherwise search the text instead.
    if (pageExists && highlight.bbox) {
      setLocated({ page: highlight.page!, bbox: highlight.bbox })
      return
    }
    if (!highlight.texts?.length || !pdfRef.current) {
      if (highlight.bbox) setSearchState("not_found")
      return
    }
    const pdf = pdfRef.current
    const texts = highlight.texts
    // The page the evidence names first, then every other page.
    const order = [
      ...(pageExists ? [highlight.page!] : []),
      ...Array.from({ length: numPages }, (_, index) => index + 1).filter((page) => page !== highlight.page),
    ]
    setSearchState("searching")
    ;(async () => {
      for (const page of order) {
        const proxy = await pdf.getPage(page)
        const content = await proxy.getTextContent()
        const items = content.items.filter((item): item is TextItemLike =>
          typeof item.str === "string" && Array.isArray(item.transform) && typeof item.width === "number")
        const bbox = findTextBox(items, proxy.getViewport({ scale: 1 }), texts)
          ?? (pageWords?.[page]?.length ? findWordBox(pageWords[page], texts) : null)
        if (cancelled) return
        if (bbox) {
          setLocated({ page, bbox })
          setPageNumber(page)
          setRotation(0)
          setSearchState("idle")
          return
        }
      }
      if (!cancelled) setSearchState("not_found")
    })().catch(() => { if (!cancelled) setSearchState("not_found") })
    return () => { cancelled = true }
  }, [highlight, numPages, pageWords])

  // Bring the box into view once per new result; later re-renders (zoom, status) must not pull the view back.
  useEffect(() => {
    if (!located) return
    const frame = window.requestAnimationFrame(() =>
      boxRef.current?.scrollIntoView({ block: "center", inline: "center", behavior: "smooth" }))
    return () => window.cancelAnimationFrame(frame)
  }, [located])

  // Fetch PDF with auth headers
  useEffect(() => {
    const fetchPDF = async () => {
      try {
        setLoading(true)
        setError(null)
        setPdfData(null)
        setNumPages(0)
        setPageNumber(1)

        const token = typeof window !== "undefined" ? localStorage.getItem("token") : null

        const response = await fetch(fileUrl, {
          headers: {
            Authorization: `Bearer ${token}`,
          },
        })

        if (!response.ok) {
          throw new Error(`Failed to load PDF: ${response.status} ${response.statusText}`)
        }

        const arrayBuffer = await response.arrayBuffer()
        // Convert to Uint8Array to avoid detached buffer issues
        const uint8Array = new Uint8Array(arrayBuffer)
        setPdfData(prev => {
          if (
            prev &&
            prev.length === uint8Array.length &&
            !prev.some((byte, idx) => byte !== uint8Array[idx])
          ) {
            // Avoid needless updates so react-pdf doesn't warn about equal file prop changes
            return prev
          }
          return uint8Array
        })
      } catch (err) {
        console.error("PDF fetch error:", err)
        setError("Failed to load PDF. Please try again.")
        setLoading(false)
      }
    }

    if (fileUrl) {
      fetchPDF()
    }
  }, [fileUrl])

  // Memoize file object to prevent unnecessary reloads
  const fileData = useMemo(() => {
    return pdfData ? { data: pdfData } : null
  }, [pdfData])

  const onDocumentLoadSuccess = (pdf: { numPages: number }) => {
    pdfRef.current = pdf as unknown as PdfProxy
    setNumPages(pdf.numPages)
    setLoading(false)
    setError(null)
  }

  const onDocumentLoadError = (error: Error) => {
    console.error("PDF load error:", error)
    setError("Failed to load PDF. Please try again.")
    setLoading(false)
  }

  const handleZoomIn = () => {
    setScale((prev) => Math.min(prev + 0.2, 3.0))
  }

  const handleZoomOut = () => {
    setScale((prev) => Math.max(prev - 0.2, 0.5))
  }

  const handleRotate = () => {
    setRotation((prev) => (prev + 90) % 360)
  }

  const handlePreviousPage = () => {
    setPageNumber((prev) => Math.max(prev - 1, 1))
  }

  const handleNextPage = () => {
    setPageNumber((prev) => Math.min(prev + 1, numPages))
  }

  return (
    <div className={`flex flex-col h-full ${className}`}>
      {/* Controls */}
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 px-4 py-3 bg-slate-100 border-b border-slate-200 rounded-t-lg">
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={handleZoomOut}
            disabled={scale <= 0.5}
            title="Zoom Out"
          >
            <ZoomOut className="h-4 w-4" />
          </Button>
          <span className="text-sm font-medium min-w-[60px] text-center">
            {Math.round(scale * 100)}%
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={handleZoomIn}
            disabled={scale >= 3.0}
            title="Zoom In"
          >
            <ZoomIn className="h-4 w-4" />
          </Button>
          <div className="w-px h-6 bg-slate-300 mx-2"></div>
          <Button
            variant="outline"
            size="sm"
            onClick={handleRotate}
            title="Rotate"
          >
            <RotateCw className="h-4 w-4" />
          </Button>
        </div>

        {highlight && searchState !== "idle" && (
          <span role="status" className={`inline-flex items-center gap-1 text-xs ${searchState === "not_found" ? "text-amber-700" : "text-slate-500"}`}>
            {searchState === "searching" ? "Finding the value in the document..." : <>
              <SearchX className="h-3.5 w-3.5" />
              {highlight.label ? `${highlight.label}: ` : ""}not found in this document&apos;s text
            </>}
          </span>
        )}

        {/* Page Navigation */}
        {numPages > 1 && (
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={handlePreviousPage}
              aria-label="Previous page"
              disabled={pageNumber <= 1}
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <span className="whitespace-nowrap text-sm font-medium">
              Page {pageNumber} of {numPages}
            </span>
            <Button
              variant="outline"
              size="sm"
              onClick={handleNextPage}
              aria-label="Next page"
              disabled={pageNumber >= numPages}
            >
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        )}
      </div>

      {/* PDF Display */}
      <div className="flex-1 overflow-auto bg-slate-50 p-4">
        {loading && (
          <div className="flex items-center justify-center h-full">
            <div className="text-center">
              <div className="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mb-2"></div>
              <p className="text-sm text-slate-600">Loading PDF...</p>
            </div>
          </div>
        )}

        {error && (
          <div className="flex items-center justify-center h-full">
            <div className="text-center text-red-600">
              <p className="font-medium">{error}</p>
            </div>
          </div>
        )}

        {!error && fileData && (
          <div className="flex w-max min-w-full justify-center">
            <Document
              file={fileData}
              onLoadSuccess={onDocumentLoadSuccess}
              onLoadError={onDocumentLoadError}
              loading=""
            >
              <div className="relative">
              <Page
                pageNumber={pageNumber}
                scale={scale}
                rotate={rotation}
                renderTextLayer={true}
                renderAnnotationLayer={true}
                className="shadow-lg"
              />
              {located?.page === pageNumber && rotation === 0 && <div
                ref={boxRef}
                aria-label={highlight?.label ? `Source of ${highlight.label}` : "Source evidence region"}
                className="pointer-events-none absolute rounded-sm border-2 border-amber-500 bg-amber-300/25"
                style={{ left: `${located.bbox.x}%`, top: `${located.bbox.y}%`, width: `${located.bbox.width}%`, height: `${located.bbox.height}%` }}
              />}
              </div>
            </Document>
          </div>
        )}
      </div>
    </div>
  )
}
