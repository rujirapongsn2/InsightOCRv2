export const handleAuthError = (response: Response): void => {
  if (response.status === 403 || response.status === 401) {
    if (typeof window !== "undefined") {
      localStorage.removeItem("token")
      window.location.href = "/login"
    }
  }
}

export const getApiBaseUrl = (): string => {
  return "/api/v1"
}
