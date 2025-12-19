"use client"

import { useState, useEffect, useMemo } from "react"
import { Document, Page, pdfjs } from "react-pdf"
import { ZoomIn, ZoomOut, RotateCw, ChevronLeft, ChevronRight } from "lucide-react"
import { Button } from "@/components/ui/button"
import "react-pdf/dist/Page/AnnotationLayer.css"
import "react-pdf/dist/Page/TextLayer.css"

// Configure PDF.js worker
pdfjs.GlobalWorkerOptions.workerSrc = `//unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`

interface PDFViewerProps {
  fileUrl: string
  className?: string
}

export function PDFViewer({ fileUrl, className = "" }: PDFViewerProps) {
  const [numPages, setNumPages] = useState<number>(0)
  const [pageNumber, setPageNumber] = useState<number>(1)
  const [scale, setScale] = useState<number>(1.0)
  const [rotation, setRotation] = useState<number>(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [pdfData, setPdfData] = useState<Uint8Array | null>(null)

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

  const onDocumentLoadSuccess = ({ numPages }: { numPages: number }) => {
    setNumPages(numPages)
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
      <div className="flex items-center justify-between px-4 py-3 bg-slate-100 border-b border-slate-200 rounded-t-lg">
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

        {/* Page Navigation */}
        {numPages > 1 && (
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={handlePreviousPage}
              disabled={pageNumber <= 1}
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <span className="text-sm font-medium">
              Page {pageNumber} of {numPages}
            </span>
            <Button
              variant="outline"
              size="sm"
              onClick={handleNextPage}
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
          <div className="flex justify-center">
            <Document
              file={fileData}
              onLoadSuccess={onDocumentLoadSuccess}
              onLoadError={onDocumentLoadError}
              loading=""
            >
              <Page
                pageNumber={pageNumber}
                scale={scale}
                rotate={rotation}
                renderTextLayer={true}
                renderAnnotationLayer={true}
                className="shadow-lg"
              />
            </Document>
          </div>
        )}
      </div>
    </div>
  )
}
