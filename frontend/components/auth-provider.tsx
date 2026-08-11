"use client"

import React, { createContext, useCallback, useContext, useEffect, useState } from "react"
import { useRouter, usePathname } from "next/navigation"
import { getApiBaseUrl, refreshAccessToken } from "@/lib/api"

interface User {
    id: string
    email: string
    full_name: string
    role: string
    is_superuser: boolean
}

interface AuthContextType {
    user: User | null
    loading: boolean
    login: (token: string, refreshToken?: string) => void
    logout: () => void
    refreshUser: () => Promise<void>
}

const AuthContext = createContext<AuthContextType>({
    user: null,
    loading: true,
    login: () => { },
    logout: () => { },
    refreshUser: async () => { },
})

export const useAuth = () => useContext(AuthContext)

const isLikelyJwt = (token: string) => token.split(".").length === 3

const tokenExpiresAt = (token: string): number | null => {
    try {
        const encoded = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")
        const payload = JSON.parse(atob(encoded.padEnd(Math.ceil(encoded.length / 4) * 4, "=")))
        return typeof payload.exp === "number" ? payload.exp * 1000 : null
    } catch {
        return null
    }
}

export const AuthProvider = ({ children }: { children: React.ReactNode }) => {
    const [user, setUser] = useState<User | null>(null)
    const [loading, setLoading] = useState(true)
    const router = useRouter()
    const pathname = usePathname()

    const clearSession = useCallback(() => {
        localStorage.removeItem("token")
        localStorage.removeItem("refresh_token")
        setUser(null)
        if (window.location.pathname !== "/login") router.push("/login")
    }, [router])

    const loadUser = async (token: string): Promise<boolean> => {
        const res = await fetch(`${getApiBaseUrl()}/login/test-token`, {
            method: "POST",
            headers: { Authorization: `Bearer ${token}` },
        })
        if (!res.ok) {
            if (res.status === 401 || res.status === 403) return false
            throw new Error(`Auth check failed (${res.status})`)
        }
        const refreshToken = res.headers.get("X-Refresh-Token")
        if (refreshToken) localStorage.setItem("refresh_token", refreshToken)
        setUser(await res.json())
        return true
    }

    useEffect(() => {
        const handleExpired = () => clearSession()
        window.addEventListener("auth:expired", handleExpired)
        return () => window.removeEventListener("auth:expired", handleExpired)
    }, [clearSession])

    useEffect(() => {
        let cancelled = false

        const initAuth = async () => {
            const token = localStorage.getItem("token")
            if (!token || !isLikelyJwt(token)) {
                if (token) localStorage.removeItem("token")
                if (!cancelled) setLoading(false)
                return
            }

            try {
                let valid = await loadUser(token)
                if (!valid) {
                    const result = await refreshAccessToken()
                    if (result === "refreshed") {
                        const refreshedToken = localStorage.getItem("token")
                        valid = refreshedToken ? await loadUser(refreshedToken) : false
                    } else if (result === "expired") {
                        clearSession()
                    }
                }
                if (!valid && !localStorage.getItem("refresh_token")) {
                    clearSession()
                }
            } catch (error) {
                // Keep the session on transient network failures. The next
                // request or focus event will retry without forcing a login.
                console.error("Auth init error", error)
            } finally {
                if (!cancelled) setLoading(false)
            }
        }

        void initAuth()
        return () => { cancelled = true }
    }, [clearSession]) // Auth bootstrap should run once per page load.

    useEffect(() => {
        if (!user) return

        let timer: number | undefined
        const scheduleRefresh = () => {
            if (timer) window.clearTimeout(timer)
            const token = localStorage.getItem("token")
            const expiresAt = token ? tokenExpiresAt(token) : null
            if (!expiresAt || !localStorage.getItem("refresh_token")) return

            const refreshIn = Math.max(30_000, expiresAt - Date.now() - 5 * 60_000)
            timer = window.setTimeout(async () => {
                const result = await refreshAccessToken()
                if (result === "expired") {
                    window.dispatchEvent(new Event("auth:expired"))
                    return
                }
                scheduleRefresh()
            }, refreshIn)
        }

        const refreshWhenReturning = () => {
            const token = localStorage.getItem("token")
            const expiresAt = token ? tokenExpiresAt(token) : null
            if (expiresAt && expiresAt - Date.now() < 10 * 60_000) {
                void refreshAccessToken().then((result) => {
                    if (result === "expired") window.dispatchEvent(new Event("auth:expired"))
                    else if (result === "refreshed") scheduleRefresh()
                })
            }
        }

        scheduleRefresh()
        window.addEventListener("focus", refreshWhenReturning)
        document.addEventListener("visibilitychange", refreshWhenReturning)
        return () => {
            if (timer) window.clearTimeout(timer)
            window.removeEventListener("focus", refreshWhenReturning)
            document.removeEventListener("visibilitychange", refreshWhenReturning)
        }
    }, [user])

    const login = async (token: string, refreshToken?: string) => {
        if (!isLikelyJwt(token)) {
            clearSession()
            return
        }
        localStorage.setItem("token", token)
        if (refreshToken) localStorage.setItem("refresh_token", refreshToken)

        try {
            if (await loadUser(token)) router.push("/dashboard")
        } catch (error) {
            console.error("Login fetch error", error)
        }
    }

    const refreshUser = async () => {
        const token = localStorage.getItem("token")
        if (!token || !isLikelyJwt(token)) return clearSession()
        try {
            if (!(await loadUser(token))) {
                const result = await refreshAccessToken()
                if (result === "refreshed") {
                    const refreshedToken = localStorage.getItem("token")
                    if (refreshedToken) await loadUser(refreshedToken)
                } else if (result === "expired") {
                    clearSession()
                }
            }
        } catch (error) {
            console.error("Refresh user error", error)
        }
    }

    const logout = () => {
        const token = localStorage.getItem("token")
        if (token) {
            void fetch(`${getApiBaseUrl()}/logout`, {
                method: "POST",
                headers: { Authorization: `Bearer ${token}` },
            }).catch(() => undefined)
        }
        clearSession()
    }

    useEffect(() => {
        const publicPaths = ["/login", "/"]
        if (!loading && !user && !publicPaths.includes(pathname)) {
            router.push("/login")
        }
    }, [user, loading, pathname, router])

    return (
        <AuthContext.Provider value={{ user, loading, login, logout, refreshUser }}>
            {children}
        </AuthContext.Provider>
    )
}
