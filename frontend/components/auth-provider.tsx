"use client"

import React, { createContext, useContext, useEffect, useState } from "react"
import { useRouter, usePathname } from "next/navigation"

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
    login: (token: string) => void
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

export const AuthProvider = ({ children }: { children: React.ReactNode }) => {
    const [user, setUser] = useState<User | null>(null)
    const [loading, setLoading] = useState(true)
    const router = useRouter()
    const pathname = usePathname()

    useEffect(() => {
        const initAuth = async () => {
            const token = localStorage.getItem("token")
            if (!token) {
                setLoading(false)
                return
            }

            try {
                const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1'}/login/test-token`, {
                    method: 'POST',
                    headers: { Authorization: `Bearer ${token}` }
                })

                if (res.ok) {
                    const userData = await res.json()
                    setUser(userData)
                } else {
                    localStorage.removeItem("token")
                }
            } catch (error) {
                console.error("Auth init error", error)
                localStorage.removeItem("token")
            } finally {
                setLoading(false)
            }
        }

        initAuth()
    }, [])

    const login = async (token: string) => {
        localStorage.setItem("token", token)
        // Fetch user data immediately
        try {
            const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1'}/login/test-token`, {
                method: 'POST',
                headers: { Authorization: `Bearer ${token}` }
            })
            if (res.ok) {
                const userData = await res.json()
                setUser(userData)
                router.push("/dashboard")
            }
        } catch (error) {
            console.error("Login fetch error", error)
        }
    }

    const refreshUser = async () => {
        const token = localStorage.getItem("token")
        if (!token) {
            setUser(null)
            return
        }
        try {
            const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1'}/login/test-token`, {
                method: 'POST',
                headers: { Authorization: `Bearer ${token}` }
            })
            if (res.ok) {
                const userData = await res.json()
                setUser(userData)
            }
        } catch (error) {
            console.error("Refresh user error", error)
        }
    }

    const logout = () => {
        localStorage.removeItem("token")
        setUser(null)
        router.push("/login")
    }

    // Protect routes
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
