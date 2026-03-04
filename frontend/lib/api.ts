export const handleAuthError = (response: Response): void => {
  if (response.status === 403 || response.status === 401) {
    if (typeof window !== "undefined") {
      localStorage.removeItem("token")
      window.location.href = "/login"
    }
  }
}

export const getApiBaseUrl = (): string => {
  // Client-side: Always use the same origin as the browser to avoid CORS issues
  // This works when Nginx proxies /api/v1 → backend
  if (typeof window !== "undefined") {
    return `${window.location.protocol}//${window.location.host}/api/v1`
  }

  // Server-side (SSR): Use internal Docker network
  return process.env.NEXT_PUBLIC_SSR_API_URL || "http://backend:8000/api/v1"
}
