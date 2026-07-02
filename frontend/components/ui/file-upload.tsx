import { FileInput } from "@astryxdesign/core/FileInput"
import { useState } from "react"

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
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [error, setError] = useState<string>("")

  const handleChange = (file: File | File[] | null) => {
    const nextFile = Array.isArray(file) ? file[0] ?? null : file

    if (!nextFile) {
      setSelectedFile(null)
      setError("")
      return
    }

    const sizeInMB = nextFile.size / (1024 * 1024)
    if (sizeInMB > maxSize) {
      setSelectedFile(null)
      setError(`File size must be less than ${maxSize}MB`)
      return
    }

    setSelectedFile(nextFile)
    setError("")
    onFileSelect(nextFile)
  }

  return (
    <FileInput
      label={description}
      isLabelHidden
      value={selectedFile}
      onChange={handleChange}
      accept={accept}
      maxSize={maxSize * 1024 * 1024}
      mode="dropzone"
      placeholder={description}
      description={`${accept.includes("pdf") ? "PDF" : ""}${accept.includes("pdf") && accept.includes("image") ? " or " : ""}${accept.includes("image") ? "Image" : "File"} up to ${maxSize}MB`}
      status={error ? { type: "error", message: error } : undefined}
      width="100%"
      className={className}
    />
  )
}
