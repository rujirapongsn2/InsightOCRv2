export const getApiBaseUrl = (): string => {
  const envApi = process.env.NEXT_PUBLIC_API_URL

  // Use environment variable if explicitly set
  if (envApi) {
    return envApi
  }

  // Client-side: Use same origin with /api/v1 path (works with Nginx reverse proxy)
  if (typeof window !== "undefined") {
    const { protocol, hostname } = window.location
    return `${protocol}//${hostname}/api/v1`
  }

  // Server-side: Use internal Docker network or fallback
  return process.env.NEXT_PUBLIC_SSR_API_URL || "http://backend:8000/api/v1"
}
