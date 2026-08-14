export type RefreshResult = "refreshed" | "expired" | "unavailable"

let refreshPromise: Promise<RefreshResult> | null = null

/**
 * Rotate the short-lived access token using the long-lived browser session.
 * Concurrent 401s share one request so a busy screen cannot rotate several
 * refresh tokens at the same time.
 */
export const refreshAccessToken = (): Promise<RefreshResult> => {
  if (typeof window === "undefined") return Promise.resolve("unavailable")
  if (refreshPromise) return refreshPromise

  const refreshToken = localStorage.getItem("refresh_token")
  if (!refreshToken) return Promise.resolve("expired")

  const request: Promise<RefreshResult> = fetch(`${getApiBaseUrl()}/login/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  })
    .then(async (response): Promise<RefreshResult> => {
      if (response.status === 401 || response.status === 403) return "expired"
      if (!response.ok) return "unavailable"

      const data = await response.json()
      if (!data?.access_token || !data?.refresh_token) return "expired"
      localStorage.setItem("token", data.access_token)
      localStorage.setItem("refresh_token", data.refresh_token)
      return "refreshed"
    })
    .catch((): RefreshResult => "unavailable")

  refreshPromise = request.finally(() => {
    refreshPromise = null
  })
  return refreshPromise
}

export const handleAuthError = (response: Response): void => {
  if ((response.status === 401 || response.status === 403) && typeof window !== "undefined") {
    void refreshAccessToken().then((result) => {
      if (result === "expired") {
        window.dispatchEvent(new Event("auth:expired"))
      }
    })
  }
}

export const getApiBaseUrl = (): string => {
  return "/api/v1"
}

/**
 * Resolve an API URL that can be copied to an external client.
 * Internal browser calls stay relative so they continue to work behind the
 * reverse proxy, while copied MCP/curl examples need the current public host.
 */
export const getPublicApiBaseUrl = (): string => {
  const baseUrl = getApiBaseUrl()
  if (typeof window === "undefined") return baseUrl
  if (/^https?:\/\//i.test(baseUrl)) return baseUrl.replace(/\/$/, "")
  return `${window.location.origin}/${baseUrl.replace(/^\/+/, "")}`.replace(/\/$/, "")
}
