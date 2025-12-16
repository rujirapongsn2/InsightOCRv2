import { Upload, File, X } from "lucide-react"
import { useCallback, useState } from "react"

interface FileUploadProps {
  onFileSelect: (file: File) => void
  accept?: string
  maxSize?: number // in MB
  description?: string
  className?: string
}

export function FileUpload({
  onFileSelect,
  accept = ".pdf,image/*",
  maxSize = 10,
  description = "Click to upload or drag and drop",
  className = ""
}: FileUploadProps) {
  const [isDragging, setIsDragging] = useState(false)
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [error, setError] = useState<string>("")

  const validateFile = (file: File): boolean => {
    // Check file size
    const sizeInMB = file.size / (1024 * 1024)
    if (sizeInMB > maxSize) {
      setError(`File size must be less than ${maxSize}MB`)
      return false
    }

    setError("")
    return true
  }

  const handleFile = (file: File) => {
    if (validateFile(file)) {
      setSelectedFile(file)
      onFileSelect(file)
    }
  }

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
  }, [])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)

    const files = e.dataTransfer.files
    if (files && files.length > 0) {
      handleFile(files[0])
    }
  }, [])

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (files && files.length > 0) {
      handleFile(files[0])
    }
  }

  const handleRemove = () => {
    setSelectedFile(null)
    setError("")
  }

  return (
    <div className={className}>
      {!selectedFile ? (
        <div
          className={`relative border-2 border-dashed rounded-lg p-8 text-center transition-colors ${
            isDragging
              ? "border-blue-500 bg-blue-50"
              : error
              ? "border-red-300 bg-red-50"
              : "border-slate-300 hover:border-slate-400"
          }`}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
        >
          <input
            type="file"
            accept={accept}
            onChange={handleFileInput}
            className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
          />
          <div className="flex flex-col items-center gap-2">
            <div className={`p-3 rounded-full ${error ? "bg-red-100" : "bg-slate-100"}`}>
              <Upload className={`h-6 w-6 ${error ? "text-red-600" : "text-slate-600"}`} />
            </div>
            <div>
              <p className="text-sm font-medium text-slate-700">{description}</p>
              <p className="text-xs text-slate-500 mt-1">
                {accept.includes("pdf") && "PDF"}
                {accept.includes("pdf") && accept.includes("image") && " or "}
                {accept.includes("image") && "Image"} up to {maxSize}MB
              </p>
            </div>
            {error && (
              <p className="text-sm text-red-600 mt-1">{error}</p>
            )}
          </div>
        </div>
      ) : (
        <div className="flex items-center gap-3 p-4 border border-slate-200 rounded-lg bg-slate-50">
          <div className="p-2 bg-blue-100 rounded">
            <File className="h-5 w-5 text-blue-600" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-slate-900 truncate">
              {selectedFile.name}
            </p>
            <p className="text-xs text-slate-500">
              {(selectedFile.size / 1024).toFixed(1)} KB
            </p>
          </div>
          <button
            onClick={handleRemove}
            className="p-1 hover:bg-slate-200 rounded transition-colors"
            aria-label="Remove file"
          >
            <X className="h-4 w-4 text-slate-600" />
          </button>
        </div>
      )}
    </div>
  )
}
