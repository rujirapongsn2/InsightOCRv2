import { getApiBaseUrl } from "@/lib/api"

export function normalizeAgentFilePath(filePath: string): string {
  const cleaned = filePath.trim().replace(/^[./]+/, "").replace(/[),.;:]+$/, "")
  const outputsIndex = cleaned.indexOf("outputs/")
  if (outputsIndex >= 0) return cleaned.slice(outputsIndex)
  return cleaned.includes("/") ? cleaned : `outputs/${cleaned}`
}

export function buildAgentDownloadUrl(conversationId: string, filePath: string): string {
  const base = getApiBaseUrl()
  const normalizedPath = normalizeAgentFilePath(filePath)
  return `${base}/agent/files/download?conversation_id=${encodeURIComponent(conversationId)}&path=${encodeURIComponent(normalizedPath)}`
}

function filenameFromPath(filePath: string): string {
  return filePath.split("/").pop() || "download"
}

export async function downloadAgentFile(conversationId: string, filePath: string): Promise<void> {
  const normalizedPath = normalizeAgentFilePath(filePath)
  const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
  const response = await fetch(buildAgentDownloadUrl(conversationId, normalizedPath), {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  })

  if (!response.ok) {
    let message = `Download failed (${response.status})`
    try {
      const data = await response.json()
      message = data?.detail || message
    } catch {
      try {
        message = await response.text() || message
      } catch {}
    }
    throw new Error(message)
  }

  const blob = await response.blob()
  const objectUrl = URL.createObjectURL(blob)
  const link = document.createElement("a")
  link.href = objectUrl
  link.download = filenameFromPath(normalizedPath)
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(objectUrl)
}
