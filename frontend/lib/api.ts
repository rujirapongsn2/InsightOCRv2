export const getApiBaseUrl = (): string => {
  const envApi = process.env.NEXT_PUBLIC_API_URL

  // If env is set to localhost but we're on a non-local host, prefer the current host to avoid CORS/loopback issues
  if (
    typeof window !== "undefined" &&
    envApi &&
    envApi.includes("localhost") &&
    !["localhost", "127.0.0.1"].includes(window.location.hostname)
  ) {
    const { protocol, hostname } = window.location
    const port =
      window.location.port && window.location.port !== "3000"
        ? window.location.port
        : "8000"

    return `${protocol}//${hostname}:${port}/api/v1`
  }

  if (envApi) {
    return envApi
  }

  if (typeof window !== "undefined") {
    const { protocol, hostname } = window.location
    const port =
      window.location.port && window.location.port !== "3000"
        ? window.location.port
        : "8000"

    return `${protocol}//${hostname}:${port}/api/v1`
  }

  return "http://localhost:8000/api/v1"
}
